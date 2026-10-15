#!/usr/bin/env python3
"""Deterministic Chapter 6 blast-radius guard fixture.

This is a constructed mechanism demonstration. The in-memory ledger is a
process-local serialized writer for tests; it is not a production consistency
or safety claim. The executor records a simulated effect and has no external
credential or production write path.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMPANION_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = COMPANION_ROOT / "fixtures" / "ch06"
CATALOG_PATH = FIXTURE_ROOT / "action_catalog.json"
EVIDENCE_PATH = FIXTURE_ROOT / "evidence.json"
SCOPE_PATH = FIXTURE_ROOT / "executor_scope.json"
CASES_PATH = FIXTURE_ROOT / "guard_cases.json"
DECISIONS_PATH = COMPANION_ROOT / "generated" / "ch06_guard_decisions.json"
REPORT_PATH = COMPANION_ROOT / "generated" / "ch06_guard_report.md"

IMPACT_DIMENSIONS = (
    "capacity_units_removed",
    "failure_domains_affected",
    "user_exposure_units",
    "persistent_state_writes",
    "canonical_policy_units",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_impact(value: dict[str, Any], label: str) -> dict[str, int]:
    if set(value) != set(IMPACT_DIMENSIONS):
        raise ValueError(f"{label} must contain exactly {list(IMPACT_DIMENSIONS)}")
    result: dict[str, int] = {}
    for dimension in IMPACT_DIMENSIONS:
        amount = value[dimension]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(f"{label}.{dimension} must be a non-negative integer")
        result[dimension] = amount
    return result


class EvidenceStore:
    """Typed, hash-checked evidence with fail-visible unavailable states."""

    ALLOWED_STATUS = {"available", "denied", "unavailable", "partial"}
    ALLOWED_HEALTH = {"healthy", "degraded", "unavailable", "unknown"}

    def __init__(self, document: dict[str, Any]):
        if document.get("fixture_class") != "constructed_illustration":
            raise ValueError("Chapter 6 evidence must be labeled constructed_illustration")
        self.by_id: dict[str, dict[str, Any]] = {}
        for raw in document.get("evidence", []):
            item = copy.deepcopy(raw)
            evidence_id = item.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError("evidence_id is required")
            if evidence_id in self.by_id:
                raise ValueError(f"duplicate evidence_id {evidence_id}")
            for field in ("claim_type", "subject", "scope", "observed_at"):
                if not isinstance(item.get(field), str) or not item[field]:
                    raise ValueError(f"{evidence_id} requires {field}")
            parse_time(item["observed_at"])
            if item.get("source_status") not in self.ALLOWED_STATUS:
                raise ValueError(f"{evidence_id} has invalid source_status")
            if item.get("source_health") not in self.ALLOWED_HEALTH:
                raise ValueError(f"{evidence_id} has invalid source_health")

            if item["source_status"] != "available":
                if "content" in item or "content_sha256" in item:
                    raise ValueError(
                        f"{evidence_id} must not expose content when source_status is "
                        f"{item['source_status']}"
                    )
            else:
                if "content" not in item or "content_sha256" not in item:
                    raise ValueError(f"{evidence_id} available evidence requires content and hash")
                actual = content_hash(item["content"])
                if actual != item["content_sha256"]:
                    raise ValueError(f"{evidence_id} content hash mismatch")
            self.by_id[evidence_id] = item

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        item = self.by_id.get(evidence_id)
        return copy.deepcopy(item) if item is not None else None


class ScopeCheck:
    def __init__(self, allowed: bool, reason: str | None = None):
        self.allowed = allowed
        self.reason = reason


class NarrowExecutor:
    """Second, independent scope check followed by a simulated effect."""

    def __init__(self, scope: dict[str, Any]):
        self.scope = copy.deepcopy(scope)
        if not self.scope.get("executor_id") or not self.scope.get("scope_id"):
            raise ValueError("executor scope requires executor_id and scope_id")
        self._lock = threading.Lock()
        self._executions: dict[str, dict[str, Any]] = {}

    def check_scope(self, proposal: dict[str, Any]) -> ScopeCheck:
        if proposal.get("executor_id") != self.scope["executor_id"]:
            return ScopeCheck(False, "EXECUTOR_ID_DENIED")
        target = proposal.get("target", {})
        parameters = proposal.get("parameters", {})
        for rule in self.scope.get("allowed", []):
            if proposal.get("action_class_id") != rule.get("action_class_id"):
                continue
            if proposal.get("operation") != rule.get("operation"):
                continue
            if proposal.get("surface") != rule.get("surface"):
                continue
            if target.get("kind") != rule.get("target_kind"):
                continue
            if target.get("namespace") != rule.get("namespace"):
                continue
            if not str(target.get("name", "")).startswith(rule.get("name_prefix", "")):
                continue
            if not self._parameters_fit(parameters, rule.get("parameters", {})):
                continue
            return ScopeCheck(True)
        return ScopeCheck(False, "EXECUTOR_SCOPE_DENIED")

    @staticmethod
    def _parameters_fit(parameters: dict[str, Any], constraints: dict[str, Any]) -> bool:
        if set(parameters) != set(constraints):
            return False
        for name, rule in constraints.items():
            value = parameters.get(name)
            if isinstance(value, bool) or not isinstance(value, int):
                return False
            if value < rule["minimum"] or value > rule["maximum"]:
                return False
        return True

    def execute(self, decision: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
        scope_check = self.check_scope(proposal)
        if not scope_check.allowed:
            raise PermissionError(scope_check.reason)
        if decision.get("outcome") != "admit" or not decision.get("reservation_id"):
            raise PermissionError("GUARD_ADMISSION_REQUIRED")
        binding = content_hash(
            {
                "action_class_id": proposal["action_class_id"],
                "action_class_version": proposal["action_class_version"],
                "operation": proposal["operation"],
                "surface": proposal["surface"],
                "target": proposal["target"],
                "parameters": proposal["parameters"],
            }
        )
        if decision.get("proposal_binding_sha256") != binding:
            raise PermissionError("DECISION_PROPOSAL_BINDING_MISMATCH")
        reservation_id = decision["reservation_id"]
        with self._lock:
            previous = self._executions.get(reservation_id)
            if previous is not None:
                replay = copy.deepcopy(previous)
                replay["idempotent_replay"] = True
                return replay
            result = {
                "execution": "simulated",
                "external_write_performed": False,
                "idempotent_replay": False,
                "reservation_id": reservation_id,
                "executor_scope_id": self.scope["scope_id"],
                "operation": proposal["operation"],
                "target": proposal["target"],
            }
            self._executions[reservation_id] = copy.deepcopy(result)
            return result


class SerializedGuard:
    """Single-process serialized check-and-reserve mechanism."""

    def __init__(
        self,
        catalog: dict[str, Any],
        evidence: EvidenceStore,
        executor: NarrowExecutor,
        evaluation_time: str,
    ):
        self.catalog = copy.deepcopy(catalog)
        self.evidence = evidence
        self.executor = executor
        self.evaluation_time_text = evaluation_time
        self.evaluation_time = parse_time(evaluation_time)
        self.budget = validate_impact(catalog["coordination_budget"], "coordination_budget")
        self.classes: dict[tuple[str, str], dict[str, Any]] = {}
        for action_class in catalog.get("action_classes", []):
            key = (action_class["action_class_id"], action_class["version"])
            if key in self.classes:
                raise ValueError(f"duplicate action class {key}")
            validate_impact(action_class["fixed_impact"], f"action class {key} impact")
            self.classes[key] = action_class
        self._lock = threading.Lock()
        self._idempotency: dict[str, tuple[str, dict[str, Any]]] = {}
        self._reservations: list[dict[str, Any]] = []
        self._demoted_classes: set[tuple[str, str]] = set()

    @property
    def reservations(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._reservations)

    def record_external_reservation(self, incident_id: str, record: dict[str, Any]) -> None:
        impact = validate_impact(record["impact"], "external reservation impact")
        with self._lock:
            if any(r["reservation_id"] == record["reservation_id"] for r in self._reservations):
                raise ValueError(f"duplicate reservation_id {record['reservation_id']}")
            self._reservations.append(
                {
                    "incident_id": incident_id,
                    "reservation_id": record["reservation_id"],
                    "actor_type": record["actor_type"],
                    "actor_id": record["actor_id"],
                    "action_class_id": "external-record",
                    "action_class_version": "recorded",
                    "idempotency_key": None,
                    "state": "spent",
                    "impact": impact,
                }
            )

    def _budget_used_locked(self, incident_id: str) -> dict[str, int]:
        used = {dimension: 0 for dimension in IMPACT_DIMENSIONS}
        for record in self._reservations:
            if record["incident_id"] != incident_id or record["state"] == "released":
                continue
            for dimension in IMPACT_DIMENSIONS:
                used[dimension] += record["impact"][dimension]
        return used

    @staticmethod
    def _proposal_binding(proposal: dict[str, Any]) -> str:
        return content_hash(
            {
                "action_class_id": proposal.get("action_class_id"),
                "action_class_version": proposal.get("action_class_version"),
                "operation": proposal.get("operation"),
                "surface": proposal.get("surface"),
                "target": proposal.get("target"),
                "parameters": proposal.get("parameters"),
            }
        )

    def admit(self, proposal: dict[str, Any]) -> dict[str, Any]:
        key = proposal.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise ValueError("proposal requires a non-empty idempotency_key")
        fingerprint = content_hash(proposal)
        with self._lock:
            cached = self._idempotency.get(key)
            if cached:
                cached_fingerprint, cached_decision = cached
                if cached_fingerprint != fingerprint:
                    return self._decision(
                        proposal,
                        "demote",
                        ["IDEMPOTENCY_KEY_CONFLICT"],
                        {},
                        {},
                        self._budget_used_locked(str(proposal.get("incident_id", ""))),
                        None,
                    )
                replay = copy.deepcopy(cached_decision)
                replay["idempotent_replay"] = True
                return replay
            decision = self._evaluate_locked(proposal)
            self._idempotency[key] = (fingerprint, copy.deepcopy(decision))
            return decision

    def _evaluate_locked(self, proposal: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        details: dict[str, Any] = {}
        evidence_manifest: dict[str, Any] = {}
        incident_id = str(proposal.get("incident_id", ""))
        prior = self._budget_used_locked(incident_id)
        key = (str(proposal.get("action_class_id", "")), str(proposal.get("action_class_version", "")))
        action_class = self.classes.get(key)
        if not action_class:
            return self._decision(
                proposal, "demote", ["ACTION_CLASS_UNKNOWN"], details, evidence_manifest, prior, None
            )
        if key in self._demoted_classes:
            reasons.append("CLASS_DEMOTED_AFTER_INDETERMINATE")
        if not action_class.get("enabled"):
            reasons.append("ACTION_CLASS_DISABLED")
        if proposal.get("permit_id") != action_class.get("permit_id"):
            reasons.append("PERMIT_MISMATCH")
        self._check_class_scope(proposal, action_class, reasons)

        usable = self._check_evidence(proposal, action_class, reasons, evidence_manifest)
        owner = usable.get("owner", {}).get("content")
        if owner:
            details["controller_owner_result"] = {
                "owner_state": owner.get("owner_state"),
                "owner_id": owner.get("owner_id"),
                "owned_field": owner.get("owned_field"),
                "supported_input": owner.get("supported_input"),
            }
            owner_state = owner.get("owner_state")
            if owner_state == "one_active" and proposal.get("surface") == owner.get("owned_field"):
                reasons.append("CONTROLLER_SURFACE_MISMATCH")
            elif owner_state == "one_active" and proposal.get("surface") != owner.get("supported_input"):
                reasons.append("CONTROLLER_SURFACE_UNCONFIRMED")
            elif owner_state in {"several_active", "conflicting"}:
                reasons.append("CONTROLLER_OWNER_CONFLICT")
            elif owner_state == "unknown":
                reasons.append("CONTROLLER_OWNER_UNKNOWN")
        reliability = usable.get("reliability", {}).get("content")
        if reliability and reliability.get("execution_posture") != "allow":
            reasons.append("CANONICAL_POLICY_DEMOTES")
        if action_class.get("requires_verified_inverse"):
            inverse = usable.get("inverse", {}).get("content")
            if inverse is not None and inverse.get("verified") is not True:
                reasons.append("INVERSE_NOT_VERIFIED")
        if action_class.get("requires_serving_headroom"):
            serving = usable.get("serving", {}).get("content")
            if serving is not None:
                try:
                    headroom = (
                        int(serving["serving_units"])
                        - int(serving["required_units"])
                        - int(serving["reserved_units"])
                    )
                    removal = action_class["fixed_impact"]["capacity_units_removed"]
                    details["serving_headroom"] = {
                        "serving_units": serving["serving_units"],
                        "required_units": serving["required_units"],
                        "reserved_units": serving["reserved_units"],
                        "headroom_before_action": headroom,
                        "worst_case_removed": removal,
                    }
                    if serving.get("coverage") != "target_and_failure_domain":
                        reasons.append("SERVING_COVERAGE_INSUFFICIENT")
                    if headroom - removal < 0:
                        reasons.append("SERVING_HEADROOM_INSUFFICIENT")
                except (KeyError, TypeError, ValueError):
                    reasons.append("SERVING_EVIDENCE_INVALID")

        scope_check = self.executor.check_scope(proposal)
        if not scope_check.allowed:
            reasons.append(scope_check.reason or "EXECUTOR_SCOPE_DENIED")

        impact = validate_impact(action_class["fixed_impact"], "action impact")
        reservation_id: str | None = None
        if not reasons:
            exceeded = [
                dimension
                for dimension in IMPACT_DIMENSIONS
                if prior[dimension] + impact[dimension] > self.budget[dimension]
            ]
            if exceeded:
                reasons.append("CUMULATIVE_BUDGET_EXCEEDED")
                details["exceeded_dimensions"] = exceeded
            else:
                reservation_id = "RSV-" + content_hash(
                    {
                        "incident_id": incident_id,
                        "idempotency_key": proposal["idempotency_key"],
                        "action_class": key,
                        "target": proposal.get("target"),
                    }
                )[:16]
                self._reservations.append(
                    {
                        "incident_id": incident_id,
                        "reservation_id": reservation_id,
                        "actor_type": "guarded_executor",
                        "actor_id": proposal.get("executor_id"),
                        "action_class_id": key[0],
                        "action_class_version": key[1],
                        "idempotency_key": proposal["idempotency_key"],
                        "state": "reserved",
                        "impact": impact,
                    }
                )
        outcome = "demote" if reasons else "admit"
        return self._decision(
            proposal, outcome, reasons, details, evidence_manifest, prior, reservation_id, impact
        )

    def _check_class_scope(
        self, proposal: dict[str, Any], action_class: dict[str, Any], reasons: list[str]
    ) -> None:
        target = proposal.get("target", {})
        target_rule = action_class["target"]
        if (
            target.get("kind") != target_rule["kind"]
            or target.get("namespace") != target_rule["namespace"]
            or not str(target.get("name", "")).startswith(target_rule["name_prefix"])
        ):
            reasons.append("TARGET_OUT_OF_CLASS_SCOPE")
        if proposal.get("operation") not in action_class["allowed_operations"]:
            reasons.append("OPERATION_OUT_OF_CLASS_SCOPE")
        if proposal.get("surface") not in action_class["allowed_surfaces"]:
            reasons.append("SURFACE_OUT_OF_CLASS_SCOPE")
        if proposal.get("executor_id") != action_class.get("executor_id"):
            reasons.append("EXECUTOR_ID_MISMATCH")
        parameters = proposal.get("parameters", {})
        constraints = action_class["parameter_constraints"]
        if set(parameters) != set(constraints):
            reasons.append("PARAMETERS_OUT_OF_CLASS_SCOPE")
            return
        for name, rule in constraints.items():
            value = parameters.get(name)
            if rule.get("type") == "integer" and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                reasons.append("PARAMETER_TYPE_INVALID")
                continue
            if value < rule["minimum"] or value > rule["maximum"]:
                reasons.append("PARAMETER_BOUND_EXCEEDED")

    def _check_evidence(
        self,
        proposal: dict[str, Any],
        action_class: dict[str, Any],
        reasons: list[str],
        manifest: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        usable: dict[str, dict[str, Any]] = {}
        refs = proposal.get("evidence_refs", {})
        target = proposal.get("target", {})
        target_subject = f"{target.get('namespace')}/{target.get('name')}"
        class_subject = f"{action_class['action_class_id']}@{action_class['version']}"
        for requirement in action_class["required_evidence"]:
            slot = requirement["slot"]
            evidence_id = refs.get(slot)
            if not evidence_id:
                reasons.append(f"EVIDENCE_MISSING:{slot}")
                continue
            item = self.evidence.get(evidence_id)
            if item is None:
                reasons.append(f"EVIDENCE_UNKNOWN:{slot}")
                continue
            age_seconds = (self.evaluation_time - parse_time(item["observed_at"])).total_seconds()
            manifest[slot] = {
                "evidence_id": evidence_id,
                "claim_type": item["claim_type"],
                "source_status": item["source_status"],
                "source_health": item["source_health"],
                "observed_at": item["observed_at"],
                "age_seconds": age_seconds,
                "content_sha256": item.get("content_sha256"),
            }
            if item["claim_type"] != requirement["claim_type"]:
                reasons.append(f"EVIDENCE_TYPE_MISMATCH:{slot}")
            if item["scope"] != requirement["required_scope"]:
                reasons.append(f"EVIDENCE_SCOPE_MISMATCH:{slot}")
            expected_subject = class_subject if slot == "inverse" else target_subject
            if item["subject"] != expected_subject:
                reasons.append(f"EVIDENCE_SUBJECT_MISMATCH:{slot}")
            if item["source_status"] != "available":
                reasons.append(f"EVIDENCE_{item['source_status'].upper()}:{slot}")
                continue
            if item["source_health"] != "healthy":
                reasons.append(f"EVIDENCE_SOURCE_UNHEALTHY:{slot}")
                continue
            if age_seconds < 0:
                reasons.append(f"EVIDENCE_TIME_IN_FUTURE:{slot}")
                continue
            if age_seconds > requirement["max_age_seconds"]:
                reasons.append(f"EVIDENCE_STALE:{slot}")
                continue
            usable[slot] = item
        return usable

    def _decision(
        self,
        proposal: dict[str, Any],
        outcome: str,
        reasons: list[str],
        details: dict[str, Any],
        evidence_manifest: dict[str, Any],
        prior: dict[str, int],
        reservation_id: str | None,
        impact: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        unique_reasons = list(dict.fromkeys(reasons))
        binding = self._proposal_binding(proposal)
        decision_seed = {
            "evaluation_time": self.evaluation_time_text,
            "request_id": proposal.get("request_id"),
            "idempotency_key": proposal.get("idempotency_key"),
            "outcome": outcome,
            "reasons": unique_reasons,
            "prior": prior,
            "reservation_id": reservation_id,
            "binding": binding,
        }
        return {
            "decision_id": "DEC-" + content_hash(decision_seed)[:16],
            "evaluated_at": self.evaluation_time_text,
            "outcome": outcome,
            "reason_codes": unique_reasons,
            "demotion_owner": "incident-commander" if outcome == "demote" else None,
            "idempotent_replay": False,
            "incident_id": proposal.get("incident_id"),
            "request_id": proposal.get("request_id"),
            "action_class_id": proposal.get("action_class_id"),
            "action_class_version": proposal.get("action_class_version"),
            "catalog_version": self.catalog["catalog_version"],
            "policy_version": self.catalog["policy_version"],
            "executor_scope_id": self.executor.scope["scope_id"],
            "executor_scope_version": self.executor.scope["version"],
            "proposal_binding_sha256": binding,
            "evidence_manifest": evidence_manifest,
            "impact": impact,
            "budget_before": prior,
            "budget_limit": self.budget,
            "reservation_id": reservation_id,
            "details": details,
        }

    def mark_indeterminate(self, reservation_id: str) -> None:
        with self._lock:
            for record in self._reservations:
                if record["reservation_id"] == reservation_id:
                    record["state"] = "indeterminate"
                    self._demoted_classes.add(
                        (record["action_class_id"], record["action_class_version"])
                    )
                    return
            raise KeyError(reservation_id)


def load_fixture_guard() -> tuple[SerializedGuard, NarrowExecutor, dict[str, Any]]:
    cases = read_json(CASES_PATH)
    executor = NarrowExecutor(read_json(SCOPE_PATH))
    guard = SerializedGuard(
        read_json(CATALOG_PATH),
        EvidenceStore(read_json(EVIDENCE_PATH)),
        executor,
        cases["evaluation_time"],
    )
    for external in cases.get("external_reservations", []):
        guard.record_external_reservation(cases["incident_id"], external)
    return guard, executor, cases


def render_report(results: list[dict[str, Any]], reservations: list[dict[str, Any]]) -> str:
    lines = [
        "# Chapter 6 Guard Fixture Report",
        "",
        "> Constructed mechanism demonstration. It tests deterministic demotion,",
        "> serialized reservation, and executor scope; it does not establish production safety.",
        "",
        "| Case | Outcome | Reasons | Reservation | Idempotent replay |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        decision = result["decision"]
        reasons = ", ".join(decision["reason_codes"]) or "—"
        lines.append(
            f"| `{result['case_id']}` | `{decision['outcome']}` | {reasons} | "
            f"`{decision.get('reservation_id') or '—'}` | "
            f"`{str(decision['idempotent_replay']).lower()}` |"
        )
    lines.extend(
        [
            "",
            "## Serialized reservation ledger",
            "",
            "| Reservation | Actor | Class | State | Impact vector |",
            "|---|---|---|---|---|",
        ]
    )
    for record in reservations:
        impact = "; ".join(f"{key}={record['impact'][key]}" for key in IMPACT_DIMENSIONS)
        lines.append(
            f"| `{record['reservation_id']}` | `{record['actor_type']}` | "
            f"`{record['action_class_id']}@{record['action_class_version']}` | "
            f"`{record['state']}` | {impact} |"
        )
    lines.extend(
        [
            "",
            "The ledger is an in-memory, process-local single writer. A production guard needs a",
            "durable strongly consistent store or equivalent serialization mechanism, plus crash",
            "reconciliation. The fixture makes no production, performance, or safety claim.",
            "",
        ]
    )
    return "\n".join(lines)


def generate(decisions_path: Path = DECISIONS_PATH, report_path: Path = REPORT_PATH) -> None:
    guard, executor, cases = load_fixture_guard()
    results: list[dict[str, Any]] = []
    for case in cases["cases"]:
        decision = guard.admit(case["proposal"])
        if decision["outcome"] != case["expected"]:
            raise RuntimeError(
                f"case {case['case_id']} expected {case['expected']}, got {decision['outcome']}"
            )
        execution = None
        if decision["outcome"] == "admit":
            execution = executor.execute(decision, case["proposal"])
        results.append({"case_id": case["case_id"], "decision": decision, "execution": execution})
    document = {
        "artifact_class": "constructed_mechanism_demonstration",
        "claim_boundary": (
            "Demonstrates deterministic checks and serialized in-process reservation only; "
            "does not establish production safety, performance, or distributed durability."
        ),
        "results": results,
        "reservations": guard.reservations,
    }
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    decisions_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(results, guard.reservations), encoding="utf-8")
    print(f"wrote {decisions_path}")
    print(f"wrote {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, default=DECISIONS_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    generate(args.decisions, args.report)


if __name__ == "__main__":
    main()
