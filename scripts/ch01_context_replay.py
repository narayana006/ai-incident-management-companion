#!/usr/bin/env python3
"""Assemble the Chapter 1 constructed evidence brief.

This deterministic replay compares read-only fixture records. It does not call
an AI model, hold production credentials, or change a production system. The
validator deliberately fails closed when evidence is unavailable, stale,
outside the declared scope, temporally impossible, or not integrity-protected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Any


COMPANION_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = COMPANION_ROOT / "fixtures" / "ch01" / "evidence.json"
JSON_OUTPUT = COMPANION_ROOT / "generated" / "ch01_context_brief.json"
MARKDOWN_OUTPUT = COMPANION_ROOT / "generated" / "ch01_context_brief.md"

SOURCE_STATE_CLASSES = {
    "recorded_intent",
    "live_state_observation",
    "derived_claim",
}
RETRIEVAL_STATUSES = {"retrieved", "failed", "unavailable"}
AUTHORIZATION_RESULTS = {"allowed", "denied", "not_attempted"}
SOURCE_HEALTH_STATUSES = {"healthy", "degraded", "unknown", "unavailable"}
HASH_PREFIX = "sha256:"

REQUIRED_FIELDS = {
    "evidence_id",
    "parent_evidence_ids",
    "subject",
    "source_state_class",
    "source",
    "adapter_id",
    "calling_principal",
    "valid_time",
    "source_update_time",
    "retrieval_time",
    "retrieval_status",
    "authorization_result",
    "source_health",
    "coverage",
    "query_parameters",
    "immutable_ref",
}


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def evidence_digest(item: dict[str, Any]) -> str:
    """Return the SHA-256 seal for the complete envelope except its seal."""

    payload = {key: value for key, value in item.items() if key != "immutable_ref"}
    return HASH_PREFIX + hashlib.sha256(_canonical_json(payload)).hexdigest()


def seal_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    """Seal a fixture mutation; exposed to tests so semantic checks are isolated."""

    item["immutable_ref"] = evidence_digest(item)
    return item


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid timestamp: {value!r}") from exc
    return parsed


def _verify_integrity(item: dict[str, Any]) -> None:
    evidence_id = item.get("evidence_id", "<unknown>")
    immutable_ref = item.get("immutable_ref")
    if not isinstance(immutable_ref, str) or not immutable_ref.startswith(HASH_PREFIX):
        raise ValueError(f"{evidence_id} immutable_ref must be sha256:<64 lowercase hex>")
    digest = immutable_ref[len(HASH_PREFIX) :]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{evidence_id} immutable_ref must be sha256:<64 lowercase hex>")
    expected = evidence_digest(item)
    if not hmac.compare_digest(immutable_ref, expected):
        raise ValueError(f"{evidence_id} failed SHA-256 integrity verification")


def _validate_freshness_policy(fixture: dict[str, Any]) -> None:
    policy = fixture.get("freshness_policy")
    if not isinstance(policy, dict):
        raise ValueError("freshness_policy is required")
    if not policy.get("policy_id") or not policy.get("version"):
        raise ValueError("freshness_policy needs policy_id and version")
    if policy.get("clock") != "replay_cutoff":
        raise ValueError("freshness_policy clock must be replay_cutoff")
    rules = policy.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise ValueError("freshness_policy rules are required")
    for source, rule in rules.items():
        if not isinstance(rule, dict):
            raise ValueError(f"freshness rule for {source} must be an object")
        if rule.get("timestamp_field") not in {
            "valid_time",
            "source_update_time",
            "retrieval_time",
        }:
            raise ValueError(f"freshness rule for {source} has an invalid timestamp_field")
        maximum = rule.get("max_age_seconds")
        if not isinstance(maximum, int) or maximum < 0:
            raise ValueError(f"freshness rule for {source} needs nonnegative max_age_seconds")


def validate_fixture(fixture: dict[str, Any]) -> None:
    """Validate structure, time boundaries, enums, and integrity.

    Missing required evidence is a runtime evidence gap, not a schema error, so
    the assembler can render a fail-visible hold. Retrieved and authorized
    evidence must carry content; denied or unavailable evidence need not.
    """

    if fixture.get("fixture_class") != "illustrative_constructed":
        raise ValueError("fixture must be marked illustrative_constructed")
    authority = fixture.get("system_authority", {})
    if authority.get("model_credentials") != "none":
        raise ValueError("model must not receive source credentials")
    if authority.get("adapter_access") != "least_privilege_read":
        raise ValueError("adapters must remain least-privilege read-only")
    if authority.get("production_write_credential") != "none":
        raise ValueError("fixture must not authorize production writes")

    replay_cutoff = _parse_timestamp(fixture.get("replay_cutoff"), "replay_cutoff")
    scope = fixture.get("analysis_scope")
    if not isinstance(scope, dict):
        raise ValueError("analysis_scope is required")
    for field in {
        "primary_subject",
        "surface",
        "region",
        "route_object",
        "protection_control",
        "window_start",
        "window_end",
        "affected_traffic_filter",
    }:
        if field not in scope:
            raise ValueError(f"analysis_scope missing {field}")
    window_start = _parse_timestamp(scope["window_start"], "analysis_scope.window_start")
    window_end = _parse_timestamp(scope["window_end"], "analysis_scope.window_end")
    if not window_start < window_end <= replay_cutoff:
        raise ValueError("analysis_scope window must end by replay_cutoff and start before it")

    _validate_freshness_policy(fixture)
    required = fixture.get("required_evidence_ids")
    if not isinstance(required, list) or not required:
        raise ValueError("required_evidence_ids must be a nonempty list")
    if len(required) != len(set(required)):
        raise ValueError("required_evidence_ids contains duplicates")

    evidence_items = fixture.get("evidence")
    if not isinstance(evidence_items, list):
        raise ValueError("evidence must be a list")
    seen: set[str] = set()
    policy_rules = fixture["freshness_policy"]["rules"]
    for item in evidence_items:
        if not isinstance(item, dict):
            raise ValueError("every evidence item must be an object")
        missing = REQUIRED_FIELDS.difference(item)
        if missing:
            raise ValueError(f"{item.get('evidence_id', '<unknown>')} missing {sorted(missing)}")
        evidence_id = item["evidence_id"]
        if evidence_id in seen:
            raise ValueError(f"duplicate evidence ID {evidence_id}")
        seen.add(evidence_id)

        if item["source_state_class"] not in SOURCE_STATE_CLASSES:
            raise ValueError(
                f"{evidence_id} source_state_class must be one of "
                f"{sorted(SOURCE_STATE_CLASSES)}"
            )
        if item["source_state_class"] == "derived_claim":
            raise ValueError(f"{evidence_id} input evidence cannot be a derived_claim")
        if item["retrieval_status"] not in RETRIEVAL_STATUSES:
            raise ValueError(f"{evidence_id} has an invalid retrieval_status")
        if item["authorization_result"] not in AUTHORIZATION_RESULTS:
            raise ValueError(f"{evidence_id} has an invalid authorization_result")
        health = item["source_health"]
        if not isinstance(health, dict) or health.get("status") not in SOURCE_HEALTH_STATUSES:
            raise ValueError(f"{evidence_id} has an invalid source_health status")
        assessed_at = _parse_timestamp(
            health.get("assessed_at"), f"{evidence_id}.source_health.assessed_at"
        )
        if assessed_at > replay_cutoff:
            raise ValueError(f"{evidence_id} source health is after replay_cutoff")
        if item["source"] not in policy_rules:
            raise ValueError(f"{evidence_id} has no named freshness rule for {item['source']}")

        valid_time = _parse_timestamp(item["valid_time"], f"{evidence_id}.valid_time")
        source_update = _parse_timestamp(
            item["source_update_time"], f"{evidence_id}.source_update_time"
        )
        retrieval_time = _parse_timestamp(
            item["retrieval_time"], f"{evidence_id}.retrieval_time"
        )
        if any(value > replay_cutoff for value in (valid_time, source_update, retrieval_time)):
            raise ValueError(f"{evidence_id} contains evidence after replay_cutoff")
        if valid_time > retrieval_time:
            raise ValueError(f"{evidence_id} valid_time is after retrieval_time")
        if source_update > retrieval_time:
            raise ValueError(f"{evidence_id} source_update_time is after retrieval_time")
        if assessed_at > retrieval_time:
            raise ValueError(f"{evidence_id} source health assessment is after retrieval_time")

        available = (
            item["retrieval_status"] == "retrieved"
            and item["authorization_result"] == "allowed"
        )
        if available and "content" not in item:
            raise ValueError(f"{evidence_id} retrieved/allowed evidence requires content")
        if "content" in item and not isinstance(item["content"], dict):
            raise ValueError(f"{evidence_id} content must be an object when present")
        if not isinstance(item["coverage"], dict) or not isinstance(
            item["query_parameters"], dict
        ):
            raise ValueError(f"{evidence_id} coverage and query_parameters must be objects")
        _verify_integrity(item)

    for item in evidence_items:
        unknown_parents = set(item["parent_evidence_ids"]).difference(seen)
        if unknown_parents:
            raise ValueError(
                f"{item['evidence_id']} references unknown parents {sorted(unknown_parents)}"
            )


def _freshness_result(fixture: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    policy = fixture["freshness_policy"]
    rule = policy["rules"][item["source"]]
    cutoff = _parse_timestamp(fixture["replay_cutoff"], "replay_cutoff")
    timestamp_field = rule["timestamp_field"]
    observed = _parse_timestamp(item[timestamp_field], f"{item['evidence_id']}.{timestamp_field}")
    age_seconds = int((cutoff - observed).total_seconds())
    maximum = rule["max_age_seconds"]
    return {
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "timestamp_field": timestamp_field,
        "observed_at": item[timestamp_field],
        "age_seconds": age_seconds,
        "max_age_seconds": maximum,
        "status": "within_policy" if age_seconds <= maximum else "stale",
    }


def _source_status(fixture: dict[str, Any], item: dict[str, Any] | None) -> dict[str, Any]:
    if item is None:
        return {
            "present": False,
            "subject": None,
            "source_state_class": None,
            "source": None,
            "adapter_id": None,
            "calling_principal": None,
            "valid_time": None,
            "source_update_time": None,
            "retrieval_time": None,
            "retrieval_status": "missing",
            "authorization_result": "unknown",
            "source_health": "unknown",
            "computed_freshness": "unknown",
            "freshness": None,
            "coverage": None,
            "query_parameters": None,
            "immutable_ref": None,
        }
    freshness = _freshness_result(fixture, item)
    return {
        "present": True,
        "subject": item["subject"],
        "source_state_class": item["source_state_class"],
        "source": item["source"],
        "adapter_id": item["adapter_id"],
        "calling_principal": item["calling_principal"],
        "valid_time": item["valid_time"],
        "source_update_time": item["source_update_time"],
        "retrieval_time": item["retrieval_time"],
        "retrieval_status": item["retrieval_status"],
        "authorization_result": item["authorization_result"],
        "source_health": item["source_health"]["status"],
        "computed_freshness": freshness["status"],
        "freshness": freshness,
        "coverage": item["coverage"],
        "query_parameters": item["query_parameters"],
        "immutable_ref": item["immutable_ref"],
    }


def _source_ready(status: dict[str, Any]) -> bool:
    return (
        status["present"]
        and status["retrieval_status"] == "retrieved"
        and status["authorization_result"] == "allowed"
        and status["source_health"] == "healthy"
        and status["computed_freshness"] == "within_policy"
    )


def _scope_failures(
    fixture: dict[str, Any], evidence: dict[str, dict[str, Any]]
) -> list[str]:
    """Return exact join/scope failures without guessing across identifiers."""

    scope = fixture["analysis_scope"]
    failures: list[str] = []

    expected_subjects = {
        "E-01": scope["primary_subject"],
        "E-02": scope["primary_subject"],
        "E-03": scope["route_object"],
        "E-04": scope["protection_control"],
        "E-05": scope["route_object"],
    }
    for evidence_id, expected in expected_subjects.items():
        if evidence[evidence_id]["subject"] != expected:
            failures.append(f"{evidence_id}:subject_mismatch")

    coverage_expectations = {
        "E-01": {
            "surface": scope["surface"],
            "region": scope["region"],
            "window_start": scope["window_start"],
            "window_end": scope["window_end"],
        },
        "E-02": {"surface": scope["surface"]},
        "E-03": {
            "surface": scope["surface"],
            "region": scope["region"],
            "route_object": scope["route_object"],
        },
        "E-04": {
            "surface": scope["surface"],
            "region": scope["region"],
            "protection_control": scope["protection_control"],
            "window_start": scope["window_start"],
            "window_end": scope["window_end"],
            "filter": scope["affected_traffic_filter"],
        },
        "E-05": {
            "surface": scope["surface"],
            "route_object": scope["route_object"],
        },
    }
    for evidence_id, expectations in coverage_expectations.items():
        coverage = evidence[evidence_id]["coverage"]
        for key, expected in expectations.items():
            if coverage.get(key) != expected:
                failures.append(f"{evidence_id}:coverage_{key}_mismatch")

    query_expectations = {
        "E-01": {
            "surface": scope["surface"],
            "window_start": scope["window_start"],
            "window_end": scope["window_end"],
        },
        "E-02": {"subject": scope["primary_subject"]},
        "E-03": {
            "route_object": scope["route_object"],
            "surface": scope["surface"],
        },
        "E-04": {
            "surface": scope["surface"],
            "window_start": scope["window_start"],
            "window_end": scope["window_end"],
            "filter": scope["affected_traffic_filter"],
        },
        "E-05": {
            "route_object": scope["route_object"],
            "before": fixture["replay_cutoff"],
        },
    }
    for evidence_id, expectations in query_expectations.items():
        query = evidence[evidence_id]["query_parameters"]
        for key, expected in expectations.items():
            if query.get(key) != expected:
                failures.append(f"{evidence_id}:query_{key}_mismatch")

    counter = evidence["E-04"]
    if counter["query_parameters"].get("counter") != "evaluated_requests":
        failures.append("E-04:counter_name_mismatch")
    counter_content = counter["content"]
    if counter_content.get("telemetry_health") != "healthy":
        failures.append("E-04:counter_telemetry_unhealthy")

    return sorted(set(failures))


def _derived_envelope(
    fixture: dict[str, Any],
    present_parent_ids: list[str],
    outcome: str,
    wording: str,
    source_gaps: list[str],
    validation_failures: list[str],
) -> dict[str, Any]:
    cutoff = fixture["replay_cutoff"]
    scope = fixture["analysis_scope"]
    derived = {
        "evidence_id": "E-06",
        "parent_evidence_ids": present_parent_ids,
        "subject": scope["primary_subject"],
        "source_state_class": "derived_claim",
        "source": "deterministic_context_assembler",
        "adapter_id": "local-fixture-replay-v2",
        "calling_principal": "local-read-only-replay",
        "valid_time": cutoff,
        "source_update_time": cutoff,
        "retrieval_time": cutoff,
        "retrieval_status": "generated",
        "authorization_result": "not_applicable",
        "source_health": {
            "status": "healthy",
            "assessed_at": cutoff,
            "detail": "local deterministic assembler",
        },
        "freshness": {
            "policy_id": fixture["freshness_policy"]["policy_id"],
            "policy_version": fixture["freshness_policy"]["version"],
            "timestamp_field": "valid_time",
            "observed_at": cutoff,
            "age_seconds": 0,
            "max_age_seconds": 0,
            "status": "within_policy",
        },
        "coverage": {
            "surface": scope["surface"],
            "region": scope["region"],
            "window_start": scope["window_start"],
            "window_end": scope["window_end"],
        },
        "query_parameters": {
            "rule_id": "route-conflict-v2",
            "required_evidence_ids": fixture["required_evidence_ids"],
            "replay_cutoff": cutoff,
        },
        "content": {
            "outcome": outcome,
            "wording": wording,
            "source_gaps": source_gaps,
            "validation_failures": validation_failures,
        },
        "transformation_versions": {
            "entity_mapping": "fixture-map-v2",
            "comparison_rule": "route-conflict-v2",
            "code": "ch01-context-replay-v2",
            "model": None,
            "prompt": None,
        },
    }
    seal_evidence_item(derived)
    return derived


def assemble_brief(fixture: dict[str, Any]) -> dict[str, Any]:
    validate_fixture(fixture)
    evidence = {item["evidence_id"]: item for item in fixture["evidence"]}
    required = fixture["required_evidence_ids"]
    source_status = {
        evidence_id: _source_status(fixture, evidence.get(evidence_id))
        for evidence_id in required
    }
    gaps = [evidence_id for evidence_id in required if not _source_ready(source_status[evidence_id])]
    present_parent_ids = [evidence_id for evidence_id in required if evidence_id in evidence]

    # Do not dereference content when any required source is missing, denied,
    # unhealthy, failed, or stale. The gap remains visible in the output.
    if gaps:
        derived = _derived_envelope(
            fixture,
            present_parent_ids,
            "incomplete_hold",
            "Required evidence is missing, denied, unhealthy, unavailable, or stale. "
            "The deterministic comparison did not inspect source content.",
            gaps,
            [],
        )
        return _brief_document(fixture, source_status, gaps, [], derived)

    scope_failures = _scope_failures(fixture, evidence)
    if scope_failures:
        derived = _derived_envelope(
            fixture,
            present_parent_ids,
            "incomplete_hold",
            "Evidence identifiers or scopes do not join exactly to the declared analysis "
            "scope. The route-conflict claim is withheld.",
            [],
            scope_failures,
        )
        return _brief_document(fixture, source_status, [], scope_failures, derived)

    recorded_path = evidence["E-02"]["content"].get("recorded_path", [])
    configured_path = evidence["E-03"]["content"].get("configured_path", [])
    edge_pressure = evidence["E-01"]["content"].get("edge_pressure") == "elevated"
    scoped_zero = evidence["E-04"]["content"].get("evaluated_requests") == 0
    recorded_control = fixture["analysis_scope"]["protection_control"] in recorded_path
    configured_bypass = fixture["analysis_scope"]["protection_control"] not in configured_path
    change_matches = (
        evidence["E-05"]["content"].get("route_object")
        == fixture["analysis_scope"]["route_object"]
    )

    rule_checks = {
        "recorded_intent_names_control": recorded_control,
        "configured_path_omits_control": configured_bypass,
        "edge_pressure_elevated": edge_pressure,
        "scoped_control_counter_zero": scoped_zero,
        "change_record_matches_route_object": change_matches,
    }
    rule_failures = [name for name, passed in rule_checks.items() if not passed]
    if not rule_failures:
        wording = (
            "Configured forwarding state differs from recorded intent. Edge telemetry "
            "and the scoped control counter corroborate a likely bypass for the affected "
            "surface. Responder verification is required before an action proposal."
        )
        outcome = "candidate_for_responder_verification"
    else:
        wording = (
            "Available, in-scope evidence does not satisfy the deterministic route-conflict "
            "rule. Keep the brief read-only and expose each failed check."
        )
        outcome = "incomplete_hold"
    derived = _derived_envelope(
        fixture,
        present_parent_ids,
        outcome,
        wording,
        [],
        rule_failures,
    )
    brief = _brief_document(fixture, source_status, [], rule_failures, derived)
    brief["rule_checks"] = rule_checks
    return brief


def _brief_document(
    fixture: dict[str, Any],
    source_status: dict[str, Any],
    gaps: list[str],
    validation_failures: list[str],
    derived: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_class": "illustrative_constructed",
        "replay_cutoff": fixture["replay_cutoff"],
        "analysis_scope": fixture["analysis_scope"],
        "freshness_policy": fixture["freshness_policy"],
        "system_authority": fixture["system_authority"],
        "required_source_status": source_status,
        "source_gaps": gaps,
        "validation_failures": validation_failures,
        "derived_claim": derived,
        "next_verification": [
            "collect a fresh routing snapshot",
            "verify destination capacity before proposing a traffic move",
        ],
    }


def _display(value: Any) -> str:
    if value is None:
        return "—"
    return str(value)


def render_markdown(brief: dict[str, Any]) -> str:
    claim = brief["derived_claim"]
    claim_content = claim["content"]
    status_rows = []
    for evidence_id, status in brief["required_source_status"].items():
        freshness = status.get("freshness") or {}
        status_rows.append(
            f"| `{evidence_id}` | {_display(status['source_state_class'])} | "
            f"`{_display(status['subject'])}` | {status['retrieval_status']} | "
            f"{status['authorization_result']} | {status['source_health']} | "
            f"{status['computed_freshness']} | {_display(freshness.get('age_seconds'))} / "
            f"{_display(freshness.get('max_age_seconds'))} |"
        )

    reference_rows = []
    for evidence_id, status in brief["required_source_status"].items():
        reference_rows.append(
            f"| `{evidence_id}` | `{_display(status['source'])}` | "
            f"`{_display(status['adapter_id'])}` | `{_display(status['calling_principal'])}` | "
            f"`{_display(status['valid_time'])}` | `{_display(status['retrieval_time'])}` | "
            f"`{_display(status['immutable_ref'])}` |"
        )
    reference_rows.append(
        f"| `{claim['evidence_id']}` | `{claim['source']}` | `{claim['adapter_id']}` | "
        f"`{claim['calling_principal']}` | `{claim['valid_time']}` | "
        f"`{claim['retrieval_time']}` | `{claim['immutable_ref']}` |"
    )

    failure_lines = (
        [f"- `{item}`" for item in claim_content["validation_failures"]]
        if claim_content["validation_failures"]
        else ["- None"]
    )
    gap_lines = (
        [f"- `{item}`" for item in claim_content["source_gaps"]]
        if claim_content["source_gaps"]
        else ["- None"]
    )
    transformation_json = json.dumps(claim["transformation_versions"], indent=2)
    coverage_json = json.dumps(claim["coverage"], indent=2)
    query_json = json.dumps(claim["query_parameters"], indent=2)
    source_query_json = json.dumps(
        {
            evidence_id: {
                "coverage": status["coverage"],
                "query_parameters": status["query_parameters"],
            }
            for evidence_id, status in brief["required_source_status"].items()
        },
        indent=2,
    )

    return "\n".join(
        [
            "# Constructed Chapter 1 Context Brief",
            "",
            "> Illustrative fixture. This is not production incident data or a model-performance result.",
            "",
            f"**Replay cutoff:** `{brief['replay_cutoff']}`  ",
            f"**Freshness policy:** `{brief['freshness_policy']['policy_id']}@{brief['freshness_policy']['version']}`",
            "",
            "## Required-source status",
            "",
            "| Evidence | Class | Subject | Retrieval | Authorization | Health | Computed freshness | Age / max (s) |",
            "|---|---|---|---|---|---|---|---:|",
            *status_rows,
            "",
            "## Inspectable evidence references",
            "",
            "| Evidence | Source | Adapter | Calling principal | Valid time | Retrieval time | Verified immutable reference |",
            "|---|---|---|---|---|---|---|",
            *reference_rows,
            "",
            "### Exact source coverage and query parameters",
            "",
            "```json",
            source_query_json,
            "```",
            "",
            "## Derived working claim",
            "",
            claim_content["wording"],
            "",
            f"**Outcome:** `{claim_content['outcome']}`  ",
            f"**Class:** `{claim['source_state_class']}`  ",
            f"**Subject:** `{claim['subject']}`  ",
            f"**Parents actually present:** {', '.join(f'`{item}`' for item in claim['parent_evidence_ids']) or 'None'}",
            "",
            "### Source gaps",
            "",
            *gap_lines,
            "",
            "### Validation or rule failures",
            "",
            *failure_lines,
            "",
            "### Derived-envelope coverage",
            "",
            "```json",
            coverage_json,
            "```",
            "",
            "### Derived-envelope query",
            "",
            "```json",
            query_json,
            "```",
            "",
            "### Transformation versions",
            "",
            "```json",
            transformation_json,
            "```",
            "",
            "## Next verification",
            "",
            *[f"- {item}" for item in brief["next_verification"]],
            "",
        ]
    )


def main() -> None:
    fixture = load_fixture()
    brief = assemble_brief(fixture)
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(brief, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_OUTPUT.write_text(render_markdown(brief), encoding="utf-8")
    print(f"wrote {JSON_OUTPUT.relative_to(COMPANION_ROOT)}")
    print(f"wrote {MARKDOWN_OUTPUT.relative_to(COMPANION_ROOT)}")


if __name__ == "__main__":
    main()
