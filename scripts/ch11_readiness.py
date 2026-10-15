#!/usr/bin/env python3
"""Evaluate the Chapter 11 Phase 0 gate ledger without scoring readiness.

The mechanism is deliberately conservative. Every catalogued gate is required.
An unresolved gate produces ``narrow``, ``hold``, or ``stop`` according to a
fixed policy; several satisfied gates can never compensate for one blocker.
The output is a governance aid. It grants no production or action authority.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Iterable


COMPANION_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = COMPANION_ROOT / "fixtures" / "ch11" / "readiness-assessment.json"
REPORT_PATH = COMPANION_ROOT / "generated" / "ch11_readiness_report.md"
DECISION_PATH = COMPANION_ROOT / "generated" / "ch11_readiness_decision.json"
SCORECARD_PATH = COMPANION_ROOT / "generated" / "ch11_phase_0_gate_ledger.csv"
PROVENANCE_PATH = COMPANION_ROOT / "generated" / "ch11_readiness_provenance.json"

SCHEMA_VERSION = "ch11-readiness-1"
GENERATOR_VERSION = "ch11-readiness-generator-1"
MAX_INPUT_BYTES = 1_000_000

ALLOWED_ARTIFACT_CLASSES = {"illustrative_template", "reader_supplied"}
ALLOWED_STATES = {"satisfied", "unsatisfied", "unverified", "not_applicable"}
ALLOWED_CURRENT_GATES = {
    "assessment",
    "foundation",
    "context_enrichment",
    "shadow_evaluation",
    "bounded_operation",
    "scaled_operation",
}
ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,95}$")

# ``on_unsatisfied`` is policy, not a reader-selected weight. Order is the
# stable print and evaluation order. Only consequence/inverse can be N/A, and
# only while the declared use remains read-only before shadow evaluation.
CONTROL_CATALOG = [
    {
        "gate_id": "G0-PROBLEM",
        "family": "problem",
        "question": "Are the burden, eligible population, exclusions, and current workflow defined?",
        "on_unsatisfied": "stop",
        "window": "days_1_30",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-MEASUREMENT",
        "family": "measurement",
        "question": "Are clocks, outcomes, missingness, censoring, and analysis rules fixed?",
        "on_unsatisfied": "hold",
        "window": "days_1_30",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-EVIDENCE",
        "family": "evidence",
        "question": "Are required sources, owners, access, health, coverage, and conflict rules declared?",
        "on_unsatisfied": "narrow",
        "window": "days_31_60",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-AUTHORITY",
        "family": "authority",
        "question": "Are permitted assistance, human decisions, acknowledgement, and stop power explicit?",
        "on_unsatisfied": "stop",
        "window": "days_1_30",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-SECURITY-PRIVACY",
        "family": "security_privacy",
        "question": "Are purpose, principal, audience, retention, egress, and sensitive-data boundaries controlled?",
        "on_unsatisfied": "stop",
        "window": "days_1_30",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-EVALUATION",
        "family": "evaluation",
        "question": "Can outcomes be independently adjudicated, including indeterminate cases?",
        "on_unsatisfied": "hold",
        "window": "days_61_90",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-CONSEQUENCE",
        "family": "consequence",
        "question": "For contemplated writes, are target, impact dimensions, inverse, controller, and cumulative bounds defined?",
        "on_unsatisfied": "hold",
        "window": "days_61_90",
        "na_allowed": True,
    },
    {
        "gate_id": "G0-OPERATIONS",
        "family": "operations",
        "question": "Are source failure, manual fallback, observability, correction, and sustained ownership designed?",
        "on_unsatisfied": "hold",
        "window": "days_31_60",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-ECONOMICS",
        "family": "economics",
        "question": "Can cost be attributed and bounded outside the model without treating cost as value?",
        "on_unsatisfied": "hold",
        "window": "days_1_30",
        "na_allowed": False,
    },
    {
        "gate_id": "G0-GOVERNANCE",
        "family": "governance",
        "question": "Are promotion, change, demotion, exception, correction, and retirement owners named?",
        "on_unsatisfied": "stop",
        "window": "days_1_30",
        "na_allowed": False,
    },
]
CONTROL_BY_ID = {item["gate_id"]: item for item in CONTROL_CATALOG}

TOP_LEVEL_FIELDS = {
    "schema_version",
    "artifact_class",
    "source_label",
    "assessment_id",
    "assessment_as_of",
    "current_gate",
    "scope",
    "decision_owner",
    "decision_reviewer",
    "gate_rows",
}
SCOPE_FIELDS = {
    "eligible_population",
    "explicit_exclusions",
    "permitted_assistance",
    "prohibited_authority",
    "model_version",
    "prompt_version",
    "retrieval_version",
    "policy_version",
    "data_version",
}
ROW_FIELDS = {
    "gate_id",
    "state",
    "evidence_ref",
    "owner",
    "reviewer",
    "expires_on",
    "recertification_trigger",
    "not_applicable_reason",
    "next_action",
    "notes",
}

RECOMMENDATION_RANK = {"continue": 0, "narrow": 1, "hold": 2, "stop": 3}
RECOMMENDATION_MEANING = {
    "continue": "Continue the declared work at its current authority boundary; this is not promotion.",
    "narrow": "Reduce the declared scope to supported evidence or population before continuing.",
    "hold": "Do not advance the declared work until every listed blocker is resolved and reviewed.",
    "stop": "Stop the affected pilot or use until the failed boundary is redesigned and accepted by accountable humans.",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def load_input(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise ValueError("input must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("input root must be an object")
    validate_input(data)
    return data, raw


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected.difference(value))
    extra = sorted(set(value).difference(expected))
    if missing or extra:
        raise ValueError(f"{label} fields do not match; missing={missing}, extra={extra}")


def _safe_text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    cleaned = value.strip()
    if value != cleaned:
        raise ValueError(f"{label} must not contain surrounding whitespace")
    if not cleaned and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    if len(cleaned) > 1000:
        raise ValueError(f"{label} exceeds 1000 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise ValueError(f"{label} contains a control character")
    if cleaned[:1] in {"=", "+", "-", "@"}:
        raise ValueError(f"{label} begins with a spreadsheet-formula character")
    return cleaned


def _role(value: Any, label: str) -> str:
    cleaned = _safe_text(value, label)
    if not ROLE_RE.fullmatch(cleaned):
        raise ValueError(
            f"{label} must be a generic role identifier using lowercase letters, digits, '_' or '-'"
        )
    return cleaned


def _identifier(value: Any, label: str) -> str:
    cleaned = _safe_text(value, label)
    if not IDENTIFIER_RE.fullmatch(cleaned):
        raise ValueError(f"{label} is not a valid stable identifier")
    return cleaned


def _iso_date(value: Any, label: str) -> date:
    cleaned = _safe_text(value, label)
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != cleaned:
        raise ValueError(f"{label} must be canonical YYYY-MM-DD")
    return parsed


def validate_input(data: dict[str, Any]) -> None:
    _exact_fields(data, TOP_LEVEL_FIELDS, "input")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
    if data["artifact_class"] not in ALLOWED_ARTIFACT_CLASSES:
        raise ValueError(
            f"artifact_class must be one of {sorted(ALLOWED_ARTIFACT_CLASSES)}"
        )
    _identifier(data["source_label"], "source_label")
    _identifier(data["assessment_id"], "assessment_id")
    _iso_date(data["assessment_as_of"], "assessment_as_of")
    if data["current_gate"] not in ALLOWED_CURRENT_GATES:
        raise ValueError(f"current_gate must be one of {sorted(ALLOWED_CURRENT_GATES)}")

    if not isinstance(data["scope"], dict):
        raise ValueError("scope must be an object")
    _exact_fields(data["scope"], SCOPE_FIELDS, "scope")
    for field in sorted(SCOPE_FIELDS):
        _safe_text(data["scope"][field], f"scope.{field}")

    decision_owner = _role(data["decision_owner"], "decision_owner")
    decision_reviewer = _role(data["decision_reviewer"], "decision_reviewer")
    if decision_owner == decision_reviewer:
        raise ValueError("decision_owner and decision_reviewer must be distinct roles")

    rows = data["gate_rows"]
    if not isinstance(rows, list):
        raise ValueError("gate_rows must be an array")
    if len(rows) != len(CONTROL_CATALOG):
        raise ValueError(f"gate_rows must contain exactly {len(CONTROL_CATALOG)} rows")

    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        label = f"gate_rows[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{label} must be an object")
        _exact_fields(row, ROW_FIELDS, label)
        gate_id = _safe_text(row["gate_id"], f"{label}.gate_id")
        if gate_id not in CONTROL_BY_ID:
            raise ValueError(f"{label}.gate_id {gate_id!r} is not in the fixed gate catalog")
        if gate_id in seen:
            raise ValueError(f"duplicate gate_id {gate_id}")
        seen.add(gate_id)

        state = row["state"]
        if state not in ALLOWED_STATES:
            raise ValueError(f"{gate_id} state must be one of {sorted(ALLOWED_STATES)}")
        _safe_text(row["evidence_ref"], f"{gate_id}.evidence_ref")
        owner = _role(row["owner"], f"{gate_id}.owner")
        reviewer = _role(row["reviewer"], f"{gate_id}.reviewer")
        if owner == reviewer:
            raise ValueError(f"{gate_id} owner and reviewer must be distinct roles")
        _iso_date(row["expires_on"], f"{gate_id}.expires_on")
        _safe_text(row["recertification_trigger"], f"{gate_id}.recertification_trigger")
        na_reason = _safe_text(
            row["not_applicable_reason"],
            f"{gate_id}.not_applicable_reason",
            allow_empty=True,
        )
        _safe_text(row["next_action"], f"{gate_id}.next_action")
        _safe_text(row["notes"], f"{gate_id}.notes", allow_empty=True)

        if state == "not_applicable":
            if not CONTROL_BY_ID[gate_id]["na_allowed"]:
                raise ValueError(f"{gate_id} cannot be marked not_applicable")
            if not na_reason:
                raise ValueError(f"{gate_id} not_applicable requires a reason")
            if data["current_gate"] not in {
                "assessment",
                "foundation",
                "context_enrichment",
            }:
                raise ValueError(
                    f"{gate_id} not_applicable is allowed only before shadow evaluation"
                )
            assistance = data["scope"]["permitted_assistance"].lower()
            if "read-only" not in assistance and "read_only" not in assistance:
                raise ValueError(
                    f"{gate_id} not_applicable requires an explicitly read-only scope"
                )
        elif na_reason:
            raise ValueError(
                f"{gate_id} not_applicable_reason must be empty unless state is not_applicable"
            )

    expected = [item["gate_id"] for item in CONTROL_CATALOG]
    supplied = [row["gate_id"] for row in rows]
    missing = [gate_id for gate_id in expected if gate_id not in seen]
    if missing:
        raise ValueError(f"gate_rows is missing fixed gates: {missing}")
    if supplied != expected:
        raise ValueError("gate_rows must follow the fixed catalog order")


def evaluate(data: dict[str, Any], input_sha256: str) -> dict[str, Any]:
    as_of = date.fromisoformat(data["assessment_as_of"])
    rows_by_id = {row["gate_id"]: row for row in data["gate_rows"]}
    evaluated_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []

    for control in CONTROL_CATALOG:
        row = rows_by_id[control["gate_id"]]
        expires = date.fromisoformat(row["expires_on"])
        expired = expires < as_of
        state = row["state"]
        effective_state = "expired" if expired and state != "unsatisfied" else state
        disposition = ""
        rationale = ""
        if state == "unsatisfied":
            disposition = control["on_unsatisfied"]
            rationale = "required gate is unsatisfied"
        elif expired:
            disposition = "hold"
            rationale = "required gate evidence or review has expired"
        elif state == "unverified":
            disposition = "hold"
            rationale = "required gate remains unverified"

        evaluated = {
            "gate_id": control["gate_id"],
            "family": control["family"],
            "question": control["question"],
            "required": True,
            "state": state,
            "effective_state": effective_state,
            "on_unsatisfied": control["on_unsatisfied"],
            "blocking_disposition": disposition,
            "evidence_ref": row["evidence_ref"],
            "owner": row["owner"],
            "reviewer": row["reviewer"],
            "expires_on": row["expires_on"],
            "recertification_trigger": row["recertification_trigger"],
            "not_applicable_reason": row["not_applicable_reason"],
            "next_action": row["next_action"],
            "notes": row["notes"],
        }
        evaluated_rows.append(evaluated)
        if disposition:
            blockers.append(
                {
                    "gate_id": control["gate_id"],
                    "family": control["family"],
                    "source_state": state,
                    "effective_state": effective_state,
                    "disposition": disposition,
                    "rationale": rationale,
                    "evidence_ref": row["evidence_ref"],
                    "owner": row["owner"],
                    "reviewer": row["reviewer"],
                    "next_action": row["next_action"],
                }
            )

    recommendation = "continue"
    for blocker in blockers:
        if RECOMMENDATION_RANK[blocker["disposition"]] > RECOMMENDATION_RANK[recommendation]:
            recommendation = blocker["disposition"]

    starter_plan = build_starter_plan(
        evaluated_rows, data["decision_owner"], data["decision_reviewer"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_class": data["artifact_class"],
        "source_label": data["source_label"],
        "assessment_id": data["assessment_id"],
        "assessment_as_of": data["assessment_as_of"],
        "current_gate": data["current_gate"],
        "scope": deepcopy(data["scope"]),
        "decision_owner": data["decision_owner"],
        "decision_reviewer": data["decision_reviewer"],
        "recommendation": recommendation,
        "recommendation_meaning": RECOMMENDATION_MEANING[recommendation],
        "authority_effect": "none",
        "evidence_validation": (
            "The tool validates required references, dates, roles, and gate states. It does not "
            "dereference evidence or verify that a recorded state is true."
        ),
        "governance_notice": (
            "This deterministic result cannot promote an adoption gate, grant an action class, "
            "approve an exception, or accept residual risk. Accountable humans own those decisions."
        ),
        "blockers": blockers,
        "gate_rows": evaluated_rows,
        "starter_plan": starter_plan,
        "input_sha256": input_sha256,
    }


def build_starter_plan(
    rows: Iterable[dict[str, Any]], decision_owner: str, decision_reviewer: str
) -> list[dict[str, Any]]:
    rows = list(rows)
    windows = [
        (
            "days_1_30",
            "Define the population, baseline, authority boundary, ownership, and stop line.",
        ),
        (
            "days_31_60",
            "Build the read-only evidence path and make failure visible while preserving manual work.",
        ),
        (
            "days_61_90",
            "Enter shadow evaluation only if prior gates hold; adjudicate and run the governance review.",
        ),
    ]
    control_window = {item["gate_id"]: item["window"] for item in CONTROL_CATALOG}
    result = []
    for window_id, focus in windows:
        priorities = [
            {
                "gate_id": row["gate_id"],
                "next_action": row["next_action"],
                "owner": row["owner"],
                "reviewer": row["reviewer"],
            }
            for row in rows
            if row["blocking_disposition"] and control_window[row["gate_id"]] == window_id
        ]
        if not priorities:
            priorities = [
                {
                    "gate_id": "maintain-evidence",
                    "next_action": "Preserve the reviewed evidence and recertify it on the declared trigger.",
                    "owner": decision_owner,
                    "reviewer": decision_reviewer,
                }
            ]
        result.append(
            {
                "window": window_id,
                "planning_only": True,
                "focus": focus,
                "priority_actions": priorities,
                "calendar_effect_on_authority": "none",
            }
        )
    return result


def _md(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("`", "&#96;")
    )


def render_report(decision: dict[str, Any]) -> str:
    lines = [
        "# Chapter 11 Readiness Gate Report",
        "",
        f"**Artifact class:** `{_md(decision['artifact_class'])}`",
        f"**Assessment:** `{_md(decision['assessment_id'])}`",
        f"**As of:** `{_md(decision['assessment_as_of'])}`",
        f"**Current gate:** `{_md(decision['current_gate'])}`",
        f"**Recommendation:** **{_md(decision['recommendation']).upper()}**",
        "",
        _md(decision["recommendation_meaning"]),
        "",
        "> Governance notice: this report grants no production or action authority. "
        "It cannot approve promotion, exceptions, or residual risk. It checks that evidence "
        "references are present; it does not dereference them or verify a recorded state.",
        "",
        "## Required gate ledger",
        "",
        "Each row remains visible. Required gaps are not combined, weighted, or offset by other rows.",
        "",
        "| Gate | Family | Recorded state | Effective state | Evidence | Owner | Reviewer | Expiry | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in decision["gate_rows"]:
        result = row["blocking_disposition"] or "resolved"
        lines.append(
            "| "
            + " | ".join(
                _md(value)
                for value in (
                    row["gate_id"],
                    row["family"],
                    row["state"],
                    row["effective_state"],
                    row["evidence_ref"],
                    row["owner"],
                    row["reviewer"],
                    row["expires_on"],
                    result,
                )
            )
            + " |"
        )

    lines.extend(["", "## Unresolved required gates", ""])
    if decision["blockers"]:
        for blocker in decision["blockers"]:
            lines.extend(
                [
                    f"### {_md(blocker['gate_id'])} — {_md(blocker['disposition']).upper()}",
                    "",
                    f"- Condition: {_md(blocker['rationale'])}.",
                    f"- Evidence record: `{_md(blocker['evidence_ref'])}`.",
                    f"- Owner: `{_md(blocker['owner'])}`; reviewer: `{_md(blocker['reviewer'])}`.",
                    f"- Next action: {_md(blocker['next_action'])}",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "No required gate is unresolved at the stated review date. This supports only",
                "continuation at the declared boundary; it does not promote authority.",
                "",
            ]
        )

    lines.extend(["## Ninety-day starter plan", ""])
    for window in decision["starter_plan"]:
        lines.extend(
            [
                f"### {_md(window['window'])}",
                "",
                _md(window["focus"]),
                "",
            ]
        )
        for action in window["priority_actions"]:
            lines.append(
                f"- `{_md(action['gate_id'])}`: {_md(action['next_action'])} "
                f"(owner `{_md(action['owner'])}`, reviewer `{_md(action['reviewer'])}`)."
            )
        lines.extend(
            [
                "",
                "Calendar effect on authority: **none**.",
                "",
            ]
        )

    lines.extend(
        [
            "## Governance handoff",
            "",
            "Accountable humans review the blockers, direct evidence, adverse cases, transferred work,",
            "cost, non-AI alternative, dissent, and re-entry conditions. They choose whether to accept",
            "the deterministic recommendation and separately own every promotion or exception decision.",
            "",
            f"Input SHA-256: `{_md(decision['input_sha256'])}`",
            "",
        ]
    )
    return "\n".join(lines)


SCORECARD_FIELDS = [
    "artifact_class",
    "gate_id",
    "family",
    "required",
    "state",
    "effective_state",
    "on_unsatisfied",
    "blocking_disposition",
    "evidence_ref",
    "owner",
    "reviewer",
    "expires_on",
    "recertification_trigger",
    "not_applicable_reason",
    "next_action",
]


def scorecard_text(decision: dict[str, Any]) -> str:
    from io import StringIO

    handle = StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=SCORECARD_FIELDS, lineterminator="\n")
    writer.writeheader()
    for item in decision["gate_rows"]:
        row = {field: item.get(field, "") for field in SCORECARD_FIELDS}
        row["artifact_class"] = decision["artifact_class"]
        row["required"] = "true"
        writer.writerow(row)
    return handle.getvalue()


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate(
    input_path: Path = INPUT_PATH,
    report_path: Path = REPORT_PATH,
    decision_path: Path = DECISION_PATH,
    scorecard_path: Path = SCORECARD_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict[str, Any]:
    data, raw = load_input(input_path)
    input_hash = sha256_bytes(raw)
    decision = evaluate(data, input_hash)

    report_bytes = render_report(decision).encode("utf-8")
    decision_bytes = json_text(decision).encode("utf-8")
    scorecard_bytes = scorecard_text(decision).encode("utf-8")
    outputs = {
        "report": (report_path, report_bytes),
        "decision": (decision_path, decision_bytes),
        "gate_ledger": (scorecard_path, scorecard_bytes),
    }
    for _, (path, payload) in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    script_bytes = Path(__file__).read_bytes()
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "artifact_class": data["artifact_class"],
        "generator_version": GENERATOR_VERSION,
        "source_label": data["source_label"],
        "assessment_as_of": data["assessment_as_of"],
        "input_sha256": input_hash,
        "generator_sha256": sha256_bytes(script_bytes),
        "outputs": {
            name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
            for name, (_, payload) in outputs.items()
        },
        "determinism_note": (
            "The review date is supplied in the input. No wall clock, network service, model call, "
            "or production system contributes to this output."
        ),
        "authority_effect": "none",
        "evidence_validation": "references_and_metadata_only",
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json_text(provenance), encoding="utf-8")

    print(f"recommendation: {decision['recommendation']}")
    for name, (path, _) in outputs.items():
        print(f"wrote {name}: {path.resolve()}")
    print(f"wrote provenance: {provenance_path.resolve()}")
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--decision", type=Path, default=DECISION_PATH)
    parser.add_argument("--gate-ledger", type=Path, default=SCORECARD_PATH)
    parser.add_argument("--provenance", type=Path, default=PROVENANCE_PATH)
    args = parser.parse_args()
    generate(args.input, args.report, args.decision, args.gate_ledger, args.provenance)


if __name__ == "__main__":
    main()
