#!/usr/bin/env python3
"""Deterministic, constructed Chapter 8 incident-lifecycle replay.

The fixture is an isolated record-behavior demonstration.  It does not model a
real organization, make a production-performance claim, call a network, or
grant an AI system incident-command authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


COMPANION_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = COMPANION_ROOT / "fixtures" / "ch08" / "incident-replay.json"
OUTPUT_JSON = COMPANION_ROOT / "generated" / "ch08_incident_replay.json"
OUTPUT_REPORT = COMPANION_ROOT / "generated" / "ch08_incident_replay.md"

INCIDENT_STATES = (
    "detected",
    "acknowledged",
    "assessed",
    "coordinated",
    "mitigating",
    "verifying_recovery",
    "monitoring",
    "closed",
    "reopened",
)
INCIDENT_EDGES = {
    (None, "detected"),
    ("detected", "acknowledged"),
    ("acknowledged", "assessed"),
    ("assessed", "coordinated"),
    ("coordinated", "mitigating"),
    ("mitigating", "verifying_recovery"),
    ("verifying_recovery", "monitoring"),
    ("monitoring", "closed"),
    ("closed", "reopened"),
}
ACTION_STATES = (
    "proposed",
    "held",
    "authorized",
    "reserved",
    "executing",
    "observing",
    "verified",
    "failed",
    "indeterminate",
    "reversed",
    "contained",
    "spent",
)
ACTION_EDGES = {
    (None, "proposed"),
    ("proposed", "held"),
    ("proposed", "authorized"),
    ("authorized", "reserved"),
    ("authorized", "executing"),
    ("reserved", "executing"),
    ("executing", "observing"),
    ("executing", "failed"),
    ("executing", "indeterminate"),
    ("observing", "verified"),
    ("observing", "failed"),
    ("observing", "indeterminate"),
    ("verified", "spent"),
    ("failed", "reversed"),
    ("indeterminate", "contained"),
}


def read_json(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("fixture must contain a JSON object")
    return value


def canonical_json(value: Any) -> str:
    """Return the fixture's stable, whitespace-free JSON representation."""
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
    payload = f"{domain}\x00canonical-json-sorted-v1\x00{canonical_json(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sequence_number(value: str) -> int:
    prefix = "sequence-"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"invalid sequence value: {value!r}")
    suffix = value[len(prefix) :]
    if not suffix.isdigit():
        raise ValueError(f"invalid sequence value: {value!r}")
    return int(suffix)


def _require_unique(records: Iterable[dict[str, Any]], field: str) -> None:
    values = [record.get(field) for record in records]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"every record requires {field}")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {field}")


def validate_fixture(fixture: dict[str, Any]) -> None:
    if fixture.get("schema_version") != "ch08-incident-replay-1":
        raise ValueError("unsupported schema_version")
    if fixture.get("artifact_class") != "illustrative_constructed":
        raise ValueError("fixture must be explicitly illustrative and constructed")
    if "not production performance" not in fixture.get("source_label", "").lower():
        raise ValueError("fixture source label must disclaim production performance")

    sources = fixture.get("sources")
    transitions = fixture.get("transitions")
    if not isinstance(sources, list) or not isinstance(transitions, list):
        raise ValueError("sources and transitions must be lists")
    _require_unique(sources, "source_id")
    source_ids = {source["source_id"] for source in sources}
    previous: str | None = None
    prior_sequence = 0
    provenance_refs: set[str] = set()
    for transition in transitions:
        edge = (transition.get("from"), transition.get("to"))
        if edge not in INCIDENT_EDGES:
            raise ValueError(f"invalid incident transition: {edge}")
        if transition.get("from") != previous:
            raise ValueError("incident transition chain is discontinuous")
        if transition.get("to") not in INCIDENT_STATES:
            raise ValueError("untyped incident state")
        current_sequence = sequence_number(transition.get("valid_time"))
        if current_sequence <= prior_sequence:
            raise ValueError("incident transition times must increase")
        prior_sequence = current_sequence
        missing = set(transition.get("evidence_refs", [])) - source_ids
        if missing:
            raise ValueError(f"unknown evidence reference: {sorted(missing)}")
        provenance_ref = transition.get("provenance_ref")
        if not provenance_ref or provenance_ref in provenance_refs:
            raise ValueError("transition provenance references must be unique")
        provenance_refs.add(provenance_ref)
        previous = transition["to"]

    roles = fixture.get("role_assignments", [])
    _require_unique(roles, "role")
    if not any(record.get("role") == "incident_command" for record in roles):
        raise ValueError("a human incident-command assignment is required")
    command = next(record for record in roles if record.get("role") == "incident_command")
    if not str(command.get("actor", "")).startswith("human://"):
        raise ValueError("incident command must be assigned to a human actor")


def replay_incident(
    fixture: dict[str, Any], cutoff: str | None = None
) -> dict[str, Any]:
    """Replay immutable transition records through an optional sequence cutoff."""
    validate_fixture(fixture)
    cutoff_value = sequence_number(cutoff or fixture["transitions"][-1]["valid_time"])
    accepted: list[dict[str, Any]] = []
    prior_digest = "GENESIS"
    for raw in fixture["transitions"]:
        if sequence_number(raw["valid_time"]) > cutoff_value:
            continue
        event = copy.deepcopy(raw)
        material = {
            "incident_id": fixture["incident_id"],
            "record_version": fixture["record_version"],
            "event": event,
            "prior_digest": prior_digest,
        }
        record_digest = digest("ch08/incident-transition", material)
        event["prior_record_digest"] = prior_digest
        event["record_digest"] = record_digest
        accepted.append(event)
        prior_digest = record_digest
    return {
        "incident_id": fixture["incident_id"],
        "cutoff": f"sequence-{cutoff_value:02d}",
        "current_state": accepted[-1]["to"] if accepted else None,
        "transitions": accepted,
        "chain_head": prior_digest,
    }


def evaluate_action(action: dict[str, Any]) -> dict[str, Any]:
    """Validate typed action state and map incomplete observation to indeterminate."""
    acknowledgement = action.get("acknowledgement", {})
    if (
        acknowledgement.get("state") != "acknowledged"
        or not str(acknowledgement.get("actor", "")).startswith("human://")
    ):
        return {"state": "held", "reason": "POSITIVE_ACKNOWLEDGEMENT_MISSING"}

    previous: str | None = None
    prior_sequence = 0
    for event in action.get("state_events", []):
        state = event.get("state")
        if state not in ACTION_STATES or (previous, state) not in ACTION_EDGES:
            return {"state": "held", "reason": "INVALID_ACTION_STATE_TRANSITION"}
        current_sequence = sequence_number(event.get("valid_time"))
        if current_sequence < prior_sequence:
            return {"state": "held", "reason": "ACTION_TIME_REGRESSION"}
        prior_sequence = current_sequence
        previous = state

    execution = action.get("execution_result")
    observation = action.get("observation_result")
    evidence_refs = action.get("observation_evidence_refs", [])
    if execution == "partial":
        return {"state": "indeterminate", "reason": "PARTIAL_EXECUTION"}
    if execution != "complete":
        return {"state": "failed", "reason": "EXECUTION_FAILED"}
    if observation != "verified" or not evidence_refs:
        return {"state": "indeterminate", "reason": "OBSERVATION_PATH_INCOMPLETE"}
    if previous != "verified":
        return {"state": "held", "reason": "DECLARED_ACTION_STATE_MISMATCH"}
    return {
        "state": "verified",
        "reason": "DECLARED_OBSERVATION_VERIFIED",
        "action_digest": digest("ch08/action-record", action),
    }


def evaluate_sentinel(case: dict[str, Any]) -> dict[str, Any]:
    """Return tri-state recovery support; it never makes a close decision."""
    criteria = case.get("criteria", [])
    if not criteria:
        return {"result": "indeterminate", "reasons": ["NO_CRITERIA"]}

    failed = [item["criterion_id"] for item in criteria if item.get("observation") == "failed"]
    if failed:
        return {
            "result": "recovery_not_supported",
            "reasons": [f"CRITERION_FAILED:{item}" for item in failed],
        }

    indeterminate: list[str] = []
    for item in criteria:
        criterion = item.get("criterion_id", "unnamed")
        if item.get("source_health") != "healthy":
            indeterminate.append(f"SOURCE_{str(item.get('source_health')).upper()}:{criterion}")
        if item.get("coverage") != "complete_for_declared_scope":
            indeterminate.append(f"COVERAGE_INCOMPLETE:{criterion}")
        if item.get("window_complete") is not True:
            indeterminate.append(f"WINDOW_INCOMPLETE:{criterion}")
        if item.get("observation") not in {"passed", "failed"}:
            indeterminate.append(f"OBSERVATION_UNKNOWN:{criterion}")
    if indeterminate:
        return {"result": "indeterminate", "reasons": sorted(set(indeterminate))}
    return {"result": "recovery_supported", "reasons": []}


def _source_index(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["source_id"]: source for source in fixture["sources"]}


def generate_late_arrival_brief(
    fixture: dict[str, Any],
    audience: str,
    cutoff: str,
    injected_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a read-only, audience-projected brief with claim-level support state."""
    replay = replay_incident(fixture, cutoff)
    sources = _source_index(fixture)
    claims: list[dict[str, Any]] = []
    flagged: list[dict[str, str]] = []
    all_claims = copy.deepcopy(fixture.get("brief_claims", []))
    all_claims.extend(copy.deepcopy(injected_claims or []))
    for claim in all_claims:
        claim_id = claim.get("claim_id", "unidentified")
        refs = claim.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            flagged.append({"claim_id": claim_id, "reason": "EVIDENCE_REFERENCE_MISSING"})
            continue
        if any(ref not in sources for ref in refs):
            flagged.append({"claim_id": claim_id, "reason": "EVIDENCE_REFERENCE_UNKNOWN"})
            continue
        if audience not in claim.get("audiences", []):
            continue
        if any(audience not in sources[ref].get("audiences", []) for ref in refs):
            flagged.append({"claim_id": claim_id, "reason": "AUDIENCE_NOT_AUTHORIZED"})
            continue
        unhealthy = [ref for ref in refs if sources[ref].get("health") != "healthy"]
        rendered = copy.deepcopy(claim)
        rendered["support_state"] = "indeterminate" if unhealthy else "supported"
        rendered["source_states"] = {
            ref: {
                "health": sources[ref]["health"],
                "coverage": sources[ref]["coverage"],
                "freshness": sources[ref]["freshness"],
            }
            for ref in refs
        }
        claims.append(rendered)

    requests = [
        request
        for request in fixture.get("brief_requests", [])
        if request.get("role") == audience
    ]
    brief = {
        "artifact_type": "late_arrival_brief",
        "read_only": True,
        "incident_id": fixture["incident_id"],
        "record_version": fixture["record_version"],
        "audience": audience,
        "evidence_cutoff": replay["cutoff"],
        "current_state": replay["current_state"],
        "claims": claims,
        "flagged_claims": flagged,
        "requested_contributions": requests,
        "provenance_chain_head": replay["chain_head"],
        "recommendations": [],
        "execution_authority": "none",
    }
    brief["brief_digest"] = digest("ch08/late-arrival-brief", brief)
    return brief


def deliver_brief(
    brief: dict[str, Any],
    *,
    delivery_audience: str,
    current_record_version: str,
    current_cutoff: str,
) -> dict[str, Any]:
    if delivery_audience != brief.get("audience"):
        return {"delivery_state": "denied", "reason": "AUDIENCE_CHANGED"}
    if (
        current_record_version != brief.get("record_version")
        or sequence_number(current_cutoff) > sequence_number(brief["evidence_cutoff"])
    ):
        return {
            "delivery_state": "stale",
            "reason": "RECORD_ADVANCED_AFTER_GENERATION",
            "brief_cutoff": brief["evidence_cutoff"],
            "current_cutoff": current_cutoff,
        }
    return {"delivery_state": "current", "reason": "BOUND_RECORD_MATCH"}


def evaluate_publication(record: dict[str, Any]) -> dict[str, str]:
    if record.get("audience") == "external" and (
        record.get("state") != "approved" or not record.get("approved_by")
    ):
        return {"outcome": "hold", "reason": "EXTERNAL_APPROVAL_MISSING"}
    return {"outcome": "release_allowed", "reason": "HUMAN_APPROVAL_RECORDED"}


def run_replay(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = copy.deepcopy(fixture or read_json())
    validate_fixture(fixture)
    cutoff = fixture["evidence_cutoff"]
    full_replay = replay_incident(fixture)
    cutoff_replay = replay_incident(fixture, cutoff)
    briefs = {
        audience: generate_late_arrival_brief(fixture, audience, cutoff)
        for audience in ("technical_responder", "communication_owner")
    }
    sentinel_results = [
        {
            "case_id": case["case_id"],
            "expected": case["expected"],
            **evaluate_sentinel(case),
        }
        for case in fixture["sentinel_cases"]
    ]
    action_result = evaluate_action(fixture["action_record"])
    result = {
        "schema_version": "ch08-incident-replay-output-1",
        "fixture_notice": fixture["source_label"],
        "fixture_digest": digest("ch08/source-fixture", fixture),
        "incident_id": fixture["incident_id"],
        "initial_evidence_brief": generate_late_arrival_brief(
            fixture, "technical_responder", "sequence-03"
        ),
        "role_assignments": fixture["role_assignments"],
        "running_records": {
            "hypotheses": fixture["hypothesis_records"],
            "decisions": fixture["decision_records"],
            "communications": fixture["communication_records"],
            "incident_at_brief_cutoff": cutoff_replay,
        },
        "late_arrival_briefs": briefs,
        "bounded_simulated_action": {
            "record": fixture["action_record"],
            "evaluation": action_result,
        },
        "post_fix_sentinel": sentinel_results,
        "close_decision": fixture["decision_records"][1],
        "reopen_transition": full_replay["transitions"][-1],
        "full_incident_replay": full_replay,
        "negative_controls": {
            "external_publication_on_silence": evaluate_publication(
                fixture["communication_records"][1]
            ),
            "stale_brief_delivery": deliver_brief(
                briefs["technical_responder"],
                delivery_audience="technical_responder",
                current_record_version="record-v2",
                current_cutoff="sequence-09",
            ),
        },
        "human_authority": {
            "incident_command": "human_only",
            "recovery_acceptance": "human_only",
            "close": "human_only",
            "external_release": "human_approval_required",
        },
    }
    result["replay_digest"] = digest("ch08/replay-output-without-self-digest", result)
    return result


def render_report(result: dict[str, Any]) -> str:
    sentinel_lines = "\n".join(
        f"- `{case['case_id']}`: `{case['result']}` (expected `{case['expected']}`)"
        for case in result["post_fix_sentinel"]
    )
    state_path = " -> ".join(
        transition["to"]
        for transition in result["full_incident_replay"]["transitions"]
    )
    return f"""# Chapter 8 constructed incident replay

> {result['fixture_notice']}

- Incident: `{result['incident_id']}`
- Replay digest: `{result['replay_digest']}`
- Lifecycle: `{state_path}`
- Action result: `{result['bounded_simulated_action']['evaluation']['state']}`
- Incident command: `{result['human_authority']['incident_command']}`

## Late Arrival briefs

- Technical responder: cutoff `{result['late_arrival_briefs']['technical_responder']['evidence_cutoff']}`, {len(result['late_arrival_briefs']['technical_responder']['claims'])} visible claims.
- Communication owner: cutoff `{result['late_arrival_briefs']['communication_owner']['evidence_cutoff']}`, {len(result['late_arrival_briefs']['communication_owner']['claims'])} visible claims.
- The briefs are read-only and carry no execution authority.

## Post-fix sentinel

{sentinel_lines}

The sentinel reports evidence state only. A human commander retains recovery,
residual-risk, close, and reopen authority.
"""


def write_outputs(result: dict[str, Any]) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    OUTPUT_REPORT.write_text(render_report(result), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify checked-in outputs")
    args = parser.parse_args()
    result = run_replay()
    expected_json = json.dumps(result, indent=2, sort_keys=True) + "\n"
    expected_report = render_report(result)
    if args.verify:
        if not OUTPUT_JSON.exists() or not OUTPUT_REPORT.exists():
            raise SystemExit("generated Chapter 8 artifacts are missing")
        if OUTPUT_JSON.read_text(encoding="utf-8") != expected_json:
            raise SystemExit("generated Chapter 8 JSON is stale")
        if OUTPUT_REPORT.read_text(encoding="utf-8") != expected_report:
            raise SystemExit("generated Chapter 8 report is stale")
        print(f"verified {OUTPUT_JSON.relative_to(COMPANION_ROOT)}")
        print(f"verified {OUTPUT_REPORT.relative_to(COMPANION_ROOT)}")
        return 0
    write_outputs(result)
    print(f"wrote {OUTPUT_JSON.relative_to(COMPANION_ROOT)}")
    print(f"wrote {OUTPUT_REPORT.relative_to(COMPANION_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
