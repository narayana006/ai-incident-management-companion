#!/usr/bin/env python3
"""Deterministic Chapter 10 human-boundary tabletop checker.

This constructed fixture explains a policy boundary.  It does not grant
production authority, evaluate a person, or prove that an action is safe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


COMPANION_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = COMPANION_ROOT / "fixtures" / "ch10" / "human-boundary-cases.json"
RESULTS_PATH = COMPANION_ROOT / "generated" / "ch10_human_boundary_results.json"
REPORT_PATH = COMPANION_ROOT / "generated" / "ch10_human_boundary_report.md"

SCHEMA_VERSION = "ch10-human-boundary-1"
OUTPUT_SCHEMA_VERSION = "ch10-human-boundary-results-1"
GENERATOR_VERSION = "ch10-human-boundary-generator-1"
POLICY_VERSION = "human-boundary-policy-1"
MAX_INPUT_BYTES = 1_000_000
EXPECTED_RESULTS = {
    "eligible_for_policy_evaluation",
    "human_owned",
    "human_owned_unattended_blocked",
}
TOP_LEVEL_FIELDS = {"schema_version", "artifact_class", "source_label", "cases"}
CASE_FIELDS = {
    "case_id",
    "description",
    "class_validated",
    "population_validated",
    "bounds_complete",
    "inverse_current_and_exercised",
    "evidence_current_authorized_scoped",
    "commitment",
    "people_primary",
    "novel_or_outside_policy",
    "organizationally_sensitive",
    "accountable_owner",
    "expected",
}
BOOLEAN_FIELDS = CASE_FIELDS - {"case_id", "description", "expected"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")


def canonical_json(value: Any) -> str:
    """Return stable JSON and reject non-finite/floating fixture numbers."""
    if isinstance(value, float):
        raise ValueError("floating-point values are not admitted")
    if isinstance(value, dict):
        for child in value.values():
            canonical_json(child)
    elif isinstance(value, list):
        for child in value:
            canonical_json(child)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(domain: str, value: Any) -> str:
    if not domain or "\x00" in domain:
        raise ValueError("digest domain must be non-empty and contain no NUL")
    material = f"{domain}\x00canonical-json-sorted-v1\x00{canonical_json(value)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected.difference(value))
    extra = sorted(set(value).difference(expected))
    if missing or extra:
        raise ValueError(f"{label} fields do not match; missing={missing}, extra={extra}")


def validate_fixture(fixture: dict[str, Any]) -> None:
    _exact_fields(fixture, TOP_LEVEL_FIELDS, "fixture")
    if fixture["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    if fixture["artifact_class"] != "illustrative_constructed":
        raise ValueError("fixture must be explicitly illustrative and constructed")
    if not isinstance(fixture["source_label"], str) or "constructed" not in fixture[
        "source_label"
    ].lower():
        raise ValueError("source_label must identify the cases as constructed")
    cases = fixture["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        _exact_fields(case, CASE_FIELDS, f"case {index}")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not ID_RE.fullmatch(case_id):
            raise ValueError(f"case {index} has invalid case_id")
        if case_id in seen:
            raise ValueError(f"duplicate case_id {case_id!r}")
        seen.add(case_id)
        description = case["description"]
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"case {case_id} requires a description")
        if any(ord(character) < 32 for character in description):
            raise ValueError(f"case {case_id} description contains a control character")
        for field in BOOLEAN_FIELDS:
            if type(case[field]) is not bool:  # bool is intentionally stricter than int.
                raise ValueError(f"case {case_id} field {field} must be boolean")
        if case["expected"] not in EXPECTED_RESULTS:
            raise ValueError(f"case {case_id} has unsupported expected result")


def load_fixture(path: Path = FIXTURE_PATH) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        fixture = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise ValueError("input must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(fixture, dict):
        raise ValueError("fixture root must be an object")
    validate_fixture(fixture)
    return fixture, raw


def classify(case: dict[str, Any]) -> dict[str, Any]:
    """Classify without consulting the fixture's expected-answer field."""
    human_reasons: list[str] = []
    veto_reasons: list[str] = []

    if case["commitment"]:
        human_reasons.append("COMMITMENT_REQUIRES_HUMAN")
    if case["people_primary"]:
        human_reasons.append("PEOPLE_DECISION_REQUIRES_HUMAN")
    if case["organizationally_sensitive"]:
        human_reasons.append("ORGANIZATIONALLY_SENSITIVE")
    if case["novel_or_outside_policy"]:
        human_reasons.append("NOVEL_OR_OUTSIDE_POLICY")
        veto_reasons.append("NOVEL_OR_OUTSIDE_POLICY")

    gate_map = (
        ("class_validated", "ACTION_CLASS_NOT_VALIDATED"),
        ("population_validated", "POPULATION_NOT_VALIDATED"),
        ("bounds_complete", "BOUNDS_INCOMPLETE"),
        ("inverse_current_and_exercised", "INVERSE_NOT_CURRENT_AND_EXERCISED"),
        (
            "evidence_current_authorized_scoped",
            "EVIDENCE_NOT_CURRENT_AUTHORIZED_AND_SCOPED",
        ),
        ("accountable_owner", "ACCOUNTABLE_OWNER_MISSING"),
    )
    for field, reason in gate_map:
        if not case[field]:
            veto_reasons.append(reason)

    if veto_reasons:
        result = "human_owned_unattended_blocked"
        human_owned = True
    elif human_reasons:
        result = "human_owned"
        human_owned = True
    else:
        result = "eligible_for_policy_evaluation"
        human_owned = False

    decision = {
        "case_id": case["case_id"],
        "result": result,
        "human_owned": human_owned,
        "unattended_path_allowed": result == "eligible_for_policy_evaluation",
        "human_boundary_reasons": sorted(set(human_reasons)),
        "veto_reasons": sorted(set(veto_reasons)),
        "policy_note": (
            "Eligibility permits further policy evaluation only; it is not action authorization."
        ),
    }
    decision["decision_digest"] = digest("ch10/human-boundary-decision", decision)
    return decision


def evaluate(fixture: dict[str, Any], source_bytes: bytes | None = None) -> dict[str, Any]:
    validate_fixture(fixture)
    decisions = [classify(case) for case in fixture["cases"]]
    mismatches = [
        {
            "case_id": case["case_id"],
            "expected": case["expected"],
            "actual": decision["result"],
        }
        for case, decision in zip(fixture["cases"], decisions)
        if case["expected"] != decision["result"]
    ]
    provenance = {
        "input_schema_version": fixture["schema_version"],
        "artifact_class": fixture["artifact_class"],
        "source_label": fixture["source_label"],
        "generator_version": GENERATOR_VERSION,
        "policy_version": POLICY_VERSION,
        "fixture_digest": digest("ch10/human-boundary-fixture", fixture),
        "source_sha256": hashlib.sha256(
            source_bytes if source_bytes is not None else canonical_json(fixture).encode("utf-8")
        ).hexdigest(),
    }
    result = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "provenance": provenance,
        "summary": {
            "case_count": len(decisions),
            "expected_match_count": len(decisions) - len(mismatches),
            "expected_mismatch_count": len(mismatches),
            "unattended_path_allowed_count": sum(
                decision["unattended_path_allowed"] for decision in decisions
            ),
            "human_owned_count": sum(decision["human_owned"] for decision in decisions),
        },
        "decisions": decisions,
        "expected_mismatches": mismatches,
        "limitations": [
            "Constructed cases explain a boundary and are not production evidence.",
            "A result never grants authority or proves an action safe.",
            "Human-owned decisions remain subject to organizational review and accountability.",
        ],
    }
    result["run_digest"] = digest("ch10/human-boundary-results", result)
    return result


def render_markdown(result: dict[str, Any]) -> str:
    provenance = result["provenance"]
    lines = [
        "# Chapter 10 Human-Boundary Tabletop",
        "",
        "> Constructed rule explanation. This report grants no production authority and does not score people.",
        "",
        f"- Policy version: `{provenance['policy_version']}`",
        f"- Fixture digest: `{provenance['fixture_digest']}`",
        f"- Cases: {result['summary']['case_count']}",
        f"- Expected classifications matched: {result['summary']['expected_match_count']}",
        "",
        "| Case | Result | Human owned | Unattended path | Reasons |",
        "|---|---|---:|---:|---|",
    ]
    for decision in result["decisions"]:
        reasons = decision["human_boundary_reasons"] + decision["veto_reasons"]
        lines.append(
            "| {case} | `{result}` | {human} | {unattended} | {reasons} |".format(
                case=decision["case_id"],
                result=decision["result"],
                human="yes" if decision["human_owned"] else "no",
                unattended="allowed for policy evaluation" if decision["unattended_path_allowed"] else "blocked",
                reasons=", ".join(dict.fromkeys(reasons)) or "all declared gates satisfied",
            )
        )
    lines.extend(["", "## Interpretation", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.extend(["", f"Run digest: `{result['run_digest']}`", ""])
    return "\n".join(lines)


def write_outputs(
    result: dict[str, Any],
    results_path: Path = RESULTS_PATH,
    report_path: Path = REPORT_PATH,
) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_markdown(result), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--verify", action="store_true", help="fail on expected-answer mismatch")
    args = parser.parse_args()
    fixture, raw = load_fixture(args.fixture)
    result = evaluate(fixture, raw)
    write_outputs(result, args.results, args.report)
    if result["expected_mismatches"]:
        for mismatch in result["expected_mismatches"]:
            print(
                f"{mismatch['case_id']}: expected {mismatch['expected']}, "
                f"got {mismatch['actual']}"
            )
        return 1 if args.verify else 0
    print(
        f"Chapter 10 human-boundary fixture: {result['summary']['expected_match_count']}/"
        f"{result['summary']['case_count']} classifications matched"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
