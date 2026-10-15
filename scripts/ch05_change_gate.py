#!/usr/bin/env python3
"""Run the deterministic Chapter 5 change-gate demonstration.

All inputs are generic constructed fixtures. The gate has no network access,
model call, secret, or production credential. It demonstrates proposal binding,
typed evidence checks, positive acknowledgement, execution-time recheck,
separation of duties, simulated idempotent execution, and explicit verification.
Those mechanisms are proposed safety invariants, not evidence that a change is
safe or that the design reduces change failures.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any


COMPANION_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = COMPANION_ROOT.parent
FIXTURE_ROOT = COMPANION_ROOT / "fixtures" / "ch05"
POLICY_PATH = FIXTURE_ROOT / "policy.json"
CATALOG_PATH = FIXTURE_ROOT / "catalog.json"
SCENARIOS_PATH = FIXTURE_ROOT / "scenarios.json"
TEMPLATE_PATH = COMPANION_ROOT / "templates" / "ch05-freeze-exception-packet.json"
GENERATED_ROOT = COMPANION_ROOT / "generated" / "ch05"
DECISIONS_PATH = GENERATED_ROOT / "change_gate_decisions.json"
COMPARISON_PATH = GENERATED_ROOT / "declared_live_comparison.csv"
PACKET_JSON_PATH = GENERATED_ROOT / "freeze_exception_packet.json"
PACKET_MD_PATH = GENERATED_ROOT / "freeze_exception_packet.md"
MANIFEST_PATH = GENERATED_ROOT / "change_gate_run_manifest.json"
DIAGRAM_SOURCE_ROOT = COMPANION_ROOT / "diagrams" / "src"
BOOK_FIGURE_ROOT = Path(os.environ.get("BOOK_FIGURE_ROOT", COMPANION_ROOT / "generated" / "published-figures"))
FIGURE_NAMES = (
    "figure-5-1-change-gate-decision-flow.svg",
    "figure-5-2-decision-vs-execution-recheck.svg",
)

DATA_CLASS = "illustrative_constructed"
TRANSFORMATION_VERSION = "ch05-change-gate-v1.0.0"
ALLOWED_SOURCE_STATE_CLASSES = {
    "recorded_intent",
    "live_state_observation",
    "derived_claim",
}
ALLOWED_SOURCE_STATUS = {"available", "denied", "unavailable", "partial"}
ALLOWED_AUTHORIZATION = {"allowed", "denied"}
ALLOWED_SOURCE_HEALTH = {"healthy", "degraded", "unavailable", "unknown"}


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: Any) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_ref(value: Any) -> str:
    return f"sha256:{sha256_hex(value)}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_text(value: dict[str, Any], field: str, label: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{label} requires non-empty {field}")
    return item


class EvidenceStore:
    """Validate and expose typed, fail-visible evidence envelopes."""

    REQUIRED_FIELDS = {
        "evidence_id",
        "claim",
        "source_state_class",
        "source",
        "adapter_id",
        "calling_principal",
        "subject",
        "scope",
        "valid_time",
        "source_update_time",
        "retrieval_time",
        "source_status",
        "authorization_result",
        "source_health",
        "query_scope",
    }

    def __init__(self, document: dict[str, Any]):
        if document.get("artifact_class") != DATA_CLASS:
            raise ValueError("Chapter 5 scenarios must be labeled illustrative_constructed")
        self.by_id: dict[str, dict[str, Any]] = {}
        for raw in document.get("evidence", []):
            if not isinstance(raw, dict):
                raise ValueError("each evidence item must be an object")
            item = copy.deepcopy(raw)
            evidence_id = _require_text(item, "evidence_id", "evidence item")
            if evidence_id in self.by_id:
                raise ValueError(f"duplicate evidence_id {evidence_id}")
            missing = self.REQUIRED_FIELDS.difference(item)
            if missing:
                raise ValueError(f"{evidence_id} missing fields {sorted(missing)}")
            if item["source_state_class"] not in ALLOWED_SOURCE_STATE_CLASSES:
                raise ValueError(f"{evidence_id} has invalid source_state_class")
            if item["source_status"] not in ALLOWED_SOURCE_STATUS:
                raise ValueError(f"{evidence_id} has invalid source_status")
            if item["authorization_result"] not in ALLOWED_AUTHORIZATION:
                raise ValueError(f"{evidence_id} has invalid authorization_result")
            if item["source_health"] not in ALLOWED_SOURCE_HEALTH:
                raise ValueError(f"{evidence_id} has invalid source_health")
            for field in ("valid_time", "source_update_time", "retrieval_time"):
                parse_time(_require_text(item, field, evidence_id))
            if not isinstance(item["query_scope"], dict):
                raise ValueError(f"{evidence_id}.query_scope must be an object")
            if item["source_status"] == "available":
                if "content" not in item:
                    raise ValueError(f"{evidence_id} available evidence requires content")
            elif "content" in item:
                raise ValueError(
                    f"{evidence_id} must not expose content when source_status is "
                    f"{item['source_status']}"
                )
            item["content_sha256"] = (
                sha256_ref(item["content"]) if "content" in item else None
            )
            item["immutable_ref"] = sha256_ref(
                {key: item[key] for key in sorted(item) if key != "immutable_ref"}
            )
            self.by_id[evidence_id] = item

    def get(self, evidence_id: str) -> dict[str, Any]:
        if evidence_id not in self.by_id:
            raise ValueError(f"unknown evidence reference {evidence_id}")
        return copy.deepcopy(self.by_id[evidence_id])


class SnapshotAssessment:
    def __init__(
        self,
        phase: str,
        evaluated_at: str,
        source_statuses: dict[str, dict[str, Any]],
        selected_evidence: dict[str, dict[str, Any]],
        comparison_rows: list[dict[str, str]],
        reason_codes: list[str],
        snapshot_sha256: str,
    ) -> None:
        self.phase = phase
        self.evaluated_at = evaluated_at
        self.source_statuses = source_statuses
        self.selected_evidence = selected_evidence
        self.comparison_rows = comparison_rows
        self.reason_codes = reason_codes
        self.snapshot_sha256 = snapshot_sha256

    def public_record(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "evaluated_at": self.evaluated_at,
            "source_statuses": self.source_statuses,
            "selected_evidence_refs": {
                claim: item["immutable_ref"]
                for claim, item in sorted(self.selected_evidence.items())
            },
            "selected_content_sha256": {
                claim: item["content_sha256"]
                for claim, item in sorted(self.selected_evidence.items())
            },
            "comparison_rows": self.comparison_rows,
            "reason_codes": self.reason_codes,
            "snapshot_sha256": self.snapshot_sha256,
        }


class ChangeGate:
    """Deterministic policy boundary with no model or production write path."""

    def __init__(
        self,
        policy: dict[str, Any],
        catalog: dict[str, Any],
        scenarios: dict[str, Any],
    ):
        if policy.get("artifact_class") != DATA_CLASS:
            raise ValueError("policy must be labeled illustrative_constructed")
        if catalog.get("artifact_class") != DATA_CLASS:
            raise ValueError("catalog must be labeled illustrative_constructed")
        if policy.get("catalog_version") != catalog.get("version"):
            raise ValueError("policy catalog_version does not match catalog version")
        self.policy = copy.deepcopy(policy)
        self.catalog = copy.deepcopy(catalog)
        self.scenarios = copy.deepcopy(scenarios)
        self.evidence = EvidenceStore(scenarios)
        self.catalog_by_id = {
            entry["class_id"]: copy.deepcopy(entry)
            for entry in catalog.get("entries", [])
        }
        if len(self.catalog_by_id) != len(catalog.get("entries", [])):
            raise ValueError("catalog class_id values must be unique")
        self._validate_policy()
        self._validate_scenarios()

    def _validate_policy(self) -> None:
        _require_text(self.policy, "policy_id", "policy")
        _require_text(self.policy, "version", "policy")
        required_claims = self.policy.get("required_claims")
        if not isinstance(required_claims, dict) or not required_claims:
            raise ValueError("policy.required_claims must be a non-empty object")
        for claim, contract in required_claims.items():
            if contract.get("source_state_class") not in ALLOWED_SOURCE_STATE_CLASSES:
                raise ValueError(f"{claim} has invalid policy source_state_class")
            age = contract.get("max_age_seconds")
            if isinstance(age, bool) or not isinstance(age, int) or age <= 0:
                raise ValueError(f"{claim}.max_age_seconds must be a positive integer")
        ttl = self.policy.get("approval_ttl_seconds")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise ValueError("approval_ttl_seconds must be a positive integer")
        executor = self.policy.get("executor", {})
        if executor.get("simulated_only") is not True:
            raise ValueError("Chapter 5 fixture executor must be simulated_only")
        if executor.get("production_write_credential") != "none":
            raise ValueError("Chapter 5 fixture must not contain a production credential")

    def _validate_scenarios(self) -> None:
        for name, proposal in self.scenarios.get("proposals", {}).items():
            self._validate_proposal(proposal, f"proposal {name}")
        evidence_sets = self.scenarios.get("evidence_sets", {})
        for set_name, references in evidence_sets.items():
            if not isinstance(references, list) or not references:
                raise ValueError(f"evidence set {set_name} must be a non-empty list")
            for evidence_id in references:
                self.evidence.get(evidence_id)
        case_ids: set[str] = set()
        for case in self.scenarios.get("cases", []):
            case_id = _require_text(case, "case_id", "case")
            if case_id in case_ids:
                raise ValueError(f"duplicate case_id {case_id}")
            case_ids.add(case_id)
            proposal_ref = _require_text(case, "proposal_ref", case_id)
            if proposal_ref not in self.scenarios["proposals"]:
                raise ValueError(f"{case_id} has unknown proposal_ref {proposal_ref}")
            decision_set = _require_text(case, "decision_evidence_set", case_id)
            if decision_set not in evidence_sets:
                raise ValueError(f"{case_id} has unknown decision evidence set")
            if case.get("execution_requested"):
                execution_set = _require_text(case, "execution_evidence_set", case_id)
                if execution_set not in evidence_sets:
                    raise ValueError(f"{case_id} has unknown execution evidence set")

    @staticmethod
    def _validate_proposal(proposal: dict[str, Any], label: str) -> None:
        for field in ("proposal_id", "proposal_version", "action_class"):
            _require_text(proposal, field, label)
        targets = proposal.get("resolved_targets")
        if (
            not isinstance(targets, list)
            or not targets
            or any(not isinstance(item, str) or not item for item in targets)
            or len(set(targets)) != len(targets)
        ):
            raise ValueError(f"{label}.resolved_targets must contain unique strings")
        artifact = proposal.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError(f"{label}.artifact must be an object")
        target = artifact.get("target", {})
        if target.get("subject_id") not in targets:
            raise ValueError(f"{label} artifact target must be in resolved_targets")
        proposer = proposal.get("proposer", {})
        _require_text(proposer, "principal", f"{label}.proposer")
        if proposer.get("production_write_credential") != "none":
            raise ValueError(f"{label} proposer must not hold a production credential")
        if not isinstance(proposal.get("verification"), dict):
            raise ValueError(f"{label}.verification is required")
        if not isinstance(proposal.get("reversal"), dict):
            raise ValueError(f"{label}.reversal is required")

    def proposal(self, reference: str) -> dict[str, Any]:
        proposal = copy.deepcopy(self.scenarios["proposals"][reference])
        self._validate_proposal(proposal, f"proposal {reference}")
        return proposal

    @staticmethod
    def artifact_sha256(proposal: dict[str, Any]) -> str:
        return sha256_ref(proposal["artifact"])

    @staticmethod
    def proposal_binding_sha256(proposal: dict[str, Any]) -> str:
        return sha256_ref(
            {
                "proposal_id": proposal["proposal_id"],
                "proposal_version": proposal["proposal_version"],
                "action_class": proposal["action_class"],
                "catalog_class_id": proposal.get("catalog_class_id"),
                "artifact": proposal["artifact"],
                "resolved_targets": proposal["resolved_targets"],
                "verification": proposal["verification"],
                "reversal": proposal["reversal"],
            }
        )

    def _evidence_items(self, set_name: str) -> list[dict[str, Any]]:
        return [
            self.evidence.get(evidence_id)
            for evidence_id in self.scenarios["evidence_sets"][set_name]
        ]

    def _assess_claim(
        self,
        claim: str,
        items: list[dict[str, Any]],
        evaluated_at: datetime,
        targets: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any] | None, list[str]]:
        contract = self.policy["required_claims"][claim]
        candidates = [item for item in items if item["claim"] == claim]
        status: dict[str, Any] = {
            "claim": claim,
            "required_source_state_class": contract["source_state_class"],
            "freshness_policy": {
                "policy_id": self.policy["policy_id"],
                "policy_version": self.policy["version"],
                "timestamp_field": "source_update_time",
                "max_age_seconds": contract["max_age_seconds"],
            },
            "candidate_evidence_ids": [item["evidence_id"] for item in candidates],
            "candidate_immutable_refs": [item["immutable_ref"] for item in candidates],
            "state": "usable",
            "reason_codes": [],
        }
        reasons: list[str] = []
        if not candidates:
            code = f"EVIDENCE_MISSING:{claim}"
            status.update({"state": "missing", "reason_codes": [code]})
            return status, None, [code]

        usable: list[dict[str, Any]] = []
        for item in candidates:
            item_codes: list[str] = []
            if item["source_state_class"] != contract["source_state_class"]:
                item_codes.append(f"EVIDENCE_TYPE_MISMATCH:{claim}")
            if item["authorization_result"] == "denied":
                item_codes.append(f"EVIDENCE_DENIED:{claim}")
            if item["source_status"] != "available":
                item_codes.append(f"EVIDENCE_{item['source_status'].upper()}:{claim}")
            if item["source_health"] != "healthy":
                item_codes.append(f"SOURCE_HEALTH_{item['source_health'].upper()}:{claim}")
            source_time = parse_time(item["source_update_time"])
            retrieval_time = parse_time(item["retrieval_time"])
            if retrieval_time > evaluated_at or source_time > evaluated_at:
                item_codes.append(f"EVIDENCE_FROM_FUTURE:{claim}")
                age_seconds: int | None = None
            else:
                age_seconds = int((evaluated_at - source_time).total_seconds())
                if age_seconds > contract["max_age_seconds"]:
                    item_codes.append(f"EVIDENCE_STALE:{claim}")
            item["computed_freshness"] = {
                "age_seconds": age_seconds,
                "max_age_seconds": contract["max_age_seconds"],
                "status": "within_policy" if not any("STALE" in c or "FUTURE" in c for c in item_codes) else "not_usable",
            }
            if not item_codes:
                usable.append(item)
            else:
                reasons.extend(item_codes)

        if not usable:
            status["state"] = "not_usable"
            status["reason_codes"] = sorted(set(reasons))
            return status, None, sorted(set(reasons))

        distinct = {item["content_sha256"] for item in usable}
        if len(distinct) > 1:
            code = f"EVIDENCE_CONFLICTING:{claim}"
            status["state"] = "conflicting"
            status["reason_codes"] = [code]
            status["conflicting_content_sha256"] = sorted(distinct)
            return status, None, [code]

        selected = sorted(usable, key=lambda item: item["evidence_id"])[0]
        if claim in {"declared_configuration", "current_configuration"}:
            subjects = selected.get("content", {}).get("subjects")
            if not isinstance(subjects, dict) or not set(targets).issubset(subjects):
                code = f"EVIDENCE_UNJOINABLE:{claim}"
                status["state"] = "unjoinable"
                status["reason_codes"] = [code]
                return status, None, [code]

        status["selected_evidence_id"] = selected["evidence_id"]
        status["selected_immutable_ref"] = selected["immutable_ref"]
        status["selected_content_sha256"] = selected["content_sha256"]
        status["computed_freshness"] = selected["computed_freshness"]
        status["source_status"] = selected["source_status"]
        status["authorization_result"] = selected["authorization_result"]
        status["source_health"] = selected["source_health"]
        status["subject"] = selected["subject"]
        status["scope"] = selected["scope"]
        status["valid_time"] = selected["valid_time"]
        status["source_update_time"] = selected["source_update_time"]
        status["retrieval_time"] = selected["retrieval_time"]
        status["query_scope"] = selected["query_scope"]
        return status, selected, []

    @staticmethod
    def _comparison_rows(
        proposal: dict[str, Any],
        phase: str,
        declared: dict[str, Any],
        observed: dict[str, Any],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        declared_subjects = declared["content"]["subjects"]
        observed_subjects = observed["content"]["subjects"]
        for subject in sorted(proposal["resolved_targets"]):
            declared_state = declared_subjects.get(subject, {})
            observed_state = observed_subjects.get(subject, {})
            for field in sorted(set(declared_state).union(observed_state)):
                declared_value = declared_state.get(field, "<missing>")
                observed_value = observed_state.get(field, "<missing>")
                rows.append(
                    {
                        "artifact_class": DATA_CLASS,
                        "proposal_id": proposal["proposal_id"],
                        "phase": phase,
                        "subject_id": subject,
                        "field": field,
                        "declared_value": canonical_json(declared_value),
                        "observed_value": canonical_json(observed_value),
                        "comparison": "match" if declared_value == observed_value else "different",
                        "declared_evidence_ref": declared["immutable_ref"],
                        "observed_evidence_ref": observed["immutable_ref"],
                        "coverage": canonical_json(
                            {
                                "declared": declared["query_scope"],
                                "observed": observed["query_scope"],
                            }
                        ),
                    }
                )
        return rows

    def assess_snapshot(
        self,
        proposal: dict[str, Any],
        evidence_set: str,
        phase: str,
        evaluated_at_text: str,
    ) -> SnapshotAssessment:
        evaluated_at = parse_time(evaluated_at_text)
        items = self._evidence_items(evidence_set)
        statuses: dict[str, dict[str, Any]] = {}
        selected: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        for claim in self.policy["required_claims"]:
            status, item, claim_reasons = self._assess_claim(
                claim, items, evaluated_at, proposal["resolved_targets"]
            )
            statuses[claim] = status
            reasons.extend(claim_reasons)
            if item is not None:
                selected[claim] = item

        comparisons: list[dict[str, str]] = []
        if {
            "declared_configuration",
            "current_configuration",
        }.issubset(selected):
            comparisons = self._comparison_rows(
                proposal,
                phase,
                selected["declared_configuration"],
                selected["current_configuration"],
            )
            if any(row["comparison"] != "match" for row in comparisons):
                reasons.append(f"CONFIGURATION_DRIFT_AT_{phase.upper()}")

        in_flight = selected.get("in_flight_changes")
        if in_flight and in_flight["content"].get("interactions"):
            reasons.append("INTERACTING_CHANGE_PRESENT")

        dependency = selected.get("dependency_coverage")
        if dependency:
            coverage = dependency["content"]
            if (
                coverage.get("coverage_status") != "bounded_complete_for_policy"
                or coverage.get("excluded_classes")
            ):
                reasons.append("DEPENDENCY_COVERAGE_INCOMPLETE")

        reliability = selected.get("canonical_reliability_state")
        if reliability and reliability["content"].get("change_permitted") is not True:
            reasons.append("CANONICAL_RELIABILITY_POLICY_BLOCK")

        authority = selected.get("signer_authority")
        if authority:
            content = authority["content"]
            if content.get("proposer_may_execute") is not False:
                reasons.append("PROPOSER_EXECUTION_AUTHORITY_NOT_SEPARATED")
            if content.get("authorizer_may_execute") is not False:
                reasons.append("AUTHORIZER_EXECUTION_AUTHORITY_NOT_SEPARATED")
            if content.get("executor_principal") != self.policy["executor"]["principal"]:
                reasons.append("EXECUTOR_IDENTITY_CONFLICT")

        reasons = sorted(set(reasons))
        snapshot_payload = {
            "artifact_class": DATA_CLASS,
            "phase": phase,
            "evaluated_at": evaluated_at_text,
            "proposal_binding_sha256": self.proposal_binding_sha256(proposal),
            "source_statuses": statuses,
            "selected_evidence_refs": {
                claim: item["immutable_ref"] for claim, item in sorted(selected.items())
            },
            "comparison_rows": comparisons,
            "reason_codes": reasons,
            "transformation_version": TRANSFORMATION_VERSION,
        }
        return SnapshotAssessment(
            phase=phase,
            evaluated_at=evaluated_at_text,
            source_statuses=statuses,
            selected_evidence=selected,
            comparison_rows=comparisons,
            reason_codes=reasons,
            snapshot_sha256=sha256_ref(snapshot_payload),
        )

    def _catalog_result(self, proposal: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        class_id = proposal.get("catalog_class_id")
        if class_id is None:
            return None, []
        entry = self.catalog_by_id.get(class_id)
        if entry is None:
            return None, ["CATALOG_CLASS_NOT_FOUND"]
        reasons: list[str] = []
        artifact = proposal["artifact"]
        target = artifact.get("target", {})
        if proposal["action_class"] != entry["action_class"]:
            reasons.append("CATALOG_ACTION_CLASS_MISMATCH")
        if target.get("kind") != entry["eligible_target_kind"]:
            reasons.append("CATALOG_TARGET_KIND_DENIED")
        if not set(proposal["resolved_targets"]).issubset(entry["eligible_subjects"]):
            reasons.append("CATALOG_TARGET_DENIED")
        if len(proposal["resolved_targets"]) > entry["maximum_resolved_targets"]:
            reasons.append("CATALOG_SCOPE_EXCEEDED")
        if artifact.get("operation") != entry["allowed_operation"]:
            reasons.append("CATALOG_OPERATION_DENIED")
        desired = artifact.get("desired_state", {})
        constraints = entry["allowed_desired_state"]
        if set(desired) != set(constraints):
            reasons.append("CATALOG_PARAMETER_SET_MISMATCH")
        else:
            for field, allowed in constraints.items():
                if desired[field] not in allowed:
                    reasons.append(f"CATALOG_PARAMETER_DENIED:{field}")
        if proposal.get("freeze_active") and not entry.get("allowed_in_freeze"):
            reasons.append("CATALOG_CLASS_NOT_PREAUTHORIZED_IN_FREEZE")
        return copy.deepcopy(entry), sorted(set(reasons))

    def _decision_binding(
        self, proposal: dict[str, Any], assessment: SnapshotAssessment
    ) -> str:
        """Hash the exact thing a signer is asked to approve.

        A signer who saw a different artifact, a different target set, different
        evidence, or a different policy or catalog version computes a different
        value, so an acknowledgement cannot be carried across an edit.
        """
        return sha256_ref(
            {
                "proposal_binding_sha256": self.proposal_binding_sha256(proposal),
                "artifact_sha256": self.artifact_sha256(proposal),
                "resolved_targets": proposal["resolved_targets"],
                "evidence_snapshot_sha256": assessment.snapshot_sha256,
                "policy_id": self.policy["policy_id"],
                "policy_version": self.policy["version"],
                "catalog_version": self.catalog["version"],
            }
        )

    def _acknowledgement_result(
        self,
        acknowledgement: dict[str, Any] | None,
        assessment: SnapshotAssessment,
        proposal: dict[str, Any],
        expires_at: datetime,
        execution_requested: bool,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if acknowledgement is None:
            if execution_requested:
                return None, ["ACKNOWLEDGEMENT_MISSING"]
            return None, []
        ack = copy.deepcopy(acknowledgement)
        reasons: list[str] = []
        required_role = self.policy["freeze_policy"]["required_role"]
        signer_authority = assessment.selected_evidence.get("signer_authority")
        signers = (
            signer_authority.get("content", {})
            .get("authorized_signers", {})
            .get(required_role, [])
            if signer_authority
            else []
        )
        if ack.get("decision") != "approve":
            reasons.append("ACKNOWLEDGEMENT_NOT_POSITIVE")
        if ack.get("role") != required_role:
            reasons.append("ACKNOWLEDGEMENT_ROLE_INVALID")
        if ack.get("signer_id") not in signers:
            reasons.append("ACKNOWLEDGEMENT_SIGNER_UNAUTHORIZED")
        acknowledged_at = parse_time(_require_text(ack, "acknowledged_at", "acknowledgement"))
        decision_at = parse_time(assessment.evaluated_at)
        if acknowledged_at < decision_at:
            reasons.append("ACKNOWLEDGEMENT_BEFORE_DECISION")
        if acknowledged_at > expires_at:
            reasons.append("ACKNOWLEDGEMENT_EXPIRED")
        # The signer supplies the binding of what the signer actually saw. The
        # gate recomputes it and compares; it never fills the value in.
        signed_binding = ack.get("decision_binding_sha256")
        computed_binding = self._decision_binding(proposal, assessment)
        if not isinstance(signed_binding, str) or not signed_binding:
            reasons.append("ACKNOWLEDGEMENT_BINDING_MISSING")
        elif signed_binding != computed_binding:
            reasons.append("ACKNOWLEDGEMENT_BINDING_MISMATCH")
        ack["gate_computed"] = {
            "proposal_binding_sha256": self.proposal_binding_sha256(proposal),
            "artifact_sha256": self.artifact_sha256(proposal),
            "evidence_snapshot_sha256": assessment.snapshot_sha256,
            "decision_binding_sha256": computed_binding,
        }
        ack["decision_binding_verified"] = signed_binding == computed_binding
        ack["acknowledgement_sha256"] = sha256_ref(
            {key: value for key, value in ack.items() if key != "acknowledgement_sha256"}
        )
        return ack, sorted(set(reasons))

    def _approval_record(
        self,
        proposal: dict[str, Any],
        assessment: SnapshotAssessment,
        decision_route: str,
        authority_type: str,
        authority_identity: str,
        decision_at: datetime,
        expires_at: datetime,
        catalog_entry: dict[str, Any] | None,
        acknowledgement: dict[str, Any] | None,
    ) -> dict[str, Any]:
        core = {
            "artifact_class": DATA_CLASS,
            "proposal_id": proposal["proposal_id"],
            "proposal_binding_sha256": self.proposal_binding_sha256(proposal),
            "artifact_sha256": self.artifact_sha256(proposal),
            "resolved_targets": proposal["resolved_targets"],
            "evidence_snapshot_sha256": assessment.snapshot_sha256,
            "policy_id": self.policy["policy_id"],
            "policy_version": self.policy["version"],
            "catalog_version": self.catalog["version"],
            "catalog_class_id": catalog_entry["class_id"] if catalog_entry else None,
            "decision_route": decision_route,
            "authority_type": authority_type,
            "authority_identity": authority_identity,
            "decision_at": format_time(decision_at),
            "expires_at": format_time(expires_at),
            "required_executor": self.policy["executor"]["principal"],
            "acknowledgement_ref": (
                acknowledgement["acknowledgement_sha256"] if acknowledgement else None
            ),
            "execution_time_recheck_required": True,
            "single_use": True,
        }
        approval_id = sha256_ref(core)
        core["approval_id"] = approval_id
        core["permit_nonce"] = sha256_ref(
            {"approval_id": approval_id, "purpose": "single-use-simulated-execution"}
        )
        core["protected_record_ref"] = sha256_ref(core)
        return core

    def decide(self, case: dict[str, Any]) -> dict[str, Any]:
        proposal = self.proposal(case["proposal_ref"])
        decision_at = parse_time(self.scenarios["decision_time"])
        expires_at = decision_at + timedelta(seconds=self.policy["approval_ttl_seconds"])
        proposal_binding = self.proposal_binding_sha256(proposal)
        artifact_hash = self.artifact_sha256(proposal)

        if proposal["action_class"] in self.policy["gate_self_change"]["action_classes"]:
            return {
                "status": "HOLD",
                "decision_route": "SEPARATE_HUMAN_OWNED_PATH",
                "reason_codes": ["GATE_SELF_CHANGE_REQUIRES_SEPARATE_PATH"],
                "proposal_binding_sha256": proposal_binding,
                "artifact_sha256": artifact_hash,
                "assessment": None,
                "acknowledgement": None,
                "approval": None,
            }

        assessment = self.assess_snapshot(
            proposal,
            case["decision_evidence_set"],
            "decision",
            self.scenarios["decision_time"],
        )
        reasons = list(assessment.reason_codes)
        catalog_entry, catalog_reasons = self._catalog_result(proposal)
        reasons.extend(catalog_reasons)
        if reasons:
            return {
                "status": "HOLD",
                "decision_route": "HOLD",
                "reason_codes": sorted(set(reasons)),
                "proposal_binding_sha256": proposal_binding,
                "artifact_sha256": artifact_hash,
                "assessment": assessment.public_record(),
                "acknowledgement": None,
                "approval": None,
            }

        if catalog_entry is not None:
            decision_route = "PREAUTHORIZED_STANDARD_CLASS"
            authority_type = "human_approved_catalog_class"
            authority_identity = catalog_entry["approval_record_ref"]
            acknowledgement = None
            ack_reasons: list[str] = []
        else:
            decision_route = "NAMED_REVIEW"
            authority_type = "named_positive_acknowledgement"
            acknowledgement, ack_reasons = self._acknowledgement_result(
                case.get("acknowledgement"),
                assessment,
                proposal,
                expires_at,
                bool(case.get("execution_requested")),
            )
            authority_identity = (
                acknowledgement["signer_id"] if acknowledgement else "pending"
            )

        if ack_reasons:
            return {
                "status": "HOLD",
                "decision_route": decision_route,
                "reason_codes": ack_reasons,
                "proposal_binding_sha256": proposal_binding,
                "artifact_sha256": artifact_hash,
                "assessment": assessment.public_record(),
                "acknowledgement": acknowledgement,
                "approval": None,
            }

        if decision_route == "NAMED_REVIEW" and acknowledgement is None:
            return {
                "status": "AWAITING_POSITIVE_ACKNOWLEDGEMENT",
                "decision_route": decision_route,
                "reason_codes": [],
                "proposal_binding_sha256": proposal_binding,
                "artifact_sha256": artifact_hash,
                "assessment": assessment.public_record(),
                "acknowledgement": None,
                "approval": None,
                "expires_at": format_time(expires_at),
            }

        approval = self._approval_record(
            proposal,
            assessment,
            decision_route,
            authority_type,
            authority_identity,
            decision_at,
            expires_at,
            catalog_entry,
            acknowledgement,
        )
        return {
            "status": "AUTHORIZED_PENDING_RECHECK",
            "decision_route": decision_route,
            "reason_codes": [],
            "proposal_binding_sha256": proposal_binding,
            "artifact_sha256": artifact_hash,
            "assessment": assessment.public_record(),
            "acknowledgement": acknowledgement,
            "approval": approval,
        }

    def recheck(
        self,
        case: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        proposal = self.proposal(case["proposal_ref"])
        approval = decision["approval"]
        execution_at = parse_time(self.scenarios["execution_time"])
        reasons: list[str] = []
        execution_artifact = copy.deepcopy(
            case.get("execution_artifact_override", proposal["artifact"])
        )
        execution_targets = copy.deepcopy(
            case.get("execution_resolved_targets", proposal["resolved_targets"])
        )
        execution_artifact_hash = sha256_ref(execution_artifact)
        if execution_artifact_hash != approval["artifact_sha256"]:
            reasons.append("ARTIFACT_CHANGED_AFTER_APPROVAL")
        if execution_targets != approval["resolved_targets"]:
            reasons.append("TARGET_SCOPE_CHANGED_AFTER_APPROVAL")
        if execution_artifact.get("target", {}).get("subject_id") not in execution_targets:
            reasons.append("EXECUTION_ARTIFACT_TARGET_MISMATCH")
        if execution_at > parse_time(approval["expires_at"]):
            reasons.append("APPROVAL_EXPIRED")
        if approval["policy_version"] != self.policy["version"]:
            reasons.append("POLICY_VERSION_CHANGED")
        if approval["catalog_version"] != self.catalog["version"]:
            reasons.append("CATALOG_VERSION_CHANGED")

        execution_proposal = copy.deepcopy(proposal)
        execution_proposal["artifact"] = execution_artifact
        execution_proposal["resolved_targets"] = execution_targets
        assessment = self.assess_snapshot(
            execution_proposal,
            case["execution_evidence_set"],
            "execution",
            self.scenarios["execution_time"],
        )
        reasons.extend(assessment.reason_codes)

        decision_current_hash = (
            decision.get("assessment", {})
            .get("selected_content_sha256", {})
            .get("current_configuration")
        )
        execution_current = assessment.selected_evidence.get("current_configuration")
        if (
            decision_current_hash
            and execution_current
            and execution_current["content_sha256"] != decision_current_hash
        ):
            reasons.append("STATE_CHANGED_SINCE_DECISION")

        acknowledgement = decision.get("acknowledgement")
        if acknowledgement:
            authority = assessment.selected_evidence.get("signer_authority")
            required_role = self.policy["freeze_policy"]["required_role"]
            current_signers = (
                authority.get("content", {})
                .get("authorized_signers", {})
                .get(required_role, [])
                if authority
                else []
            )
            if acknowledgement["signer_id"] not in current_signers:
                reasons.append("SIGNER_AUTHORITY_CHANGED")

        if case.get("execution_principal") != self.policy["executor"]["principal"]:
            reasons.append("EXECUTOR_IDENTITY_DENIED")
        if case.get("execution_principal") in self.policy["executor"]["forbidden_principals"]:
            reasons.append("SEPARATION_OF_DUTIES_VIOLATION")

        reasons = sorted(set(reasons))
        return {
            "status": "HOLD" if reasons else "RECHECK_PASSED",
            "reason_codes": reasons,
            "execution_at": self.scenarios["execution_time"],
            "execution_artifact_sha256": execution_artifact_hash,
            "execution_resolved_targets": execution_targets,
            "assessment": assessment.public_record(),
            "recheck_sha256": sha256_ref(
                {
                    "approval_id": approval["approval_id"],
                    "execution_at": self.scenarios["execution_time"],
                    "execution_artifact_sha256": execution_artifact_hash,
                    "execution_resolved_targets": execution_targets,
                    "execution_snapshot_sha256": assessment.snapshot_sha256,
                    "reason_codes": reasons,
                    "transformation_version": TRANSFORMATION_VERSION,
                }
            ),
        }


class SimulatedExecutor:
    """Narrow executor with independent binding, nonce, and replay checks."""

    def __init__(self, policy: dict[str, Any]):
        self.policy = copy.deepcopy(policy)
        self.by_idempotency_key: dict[str, tuple[str, dict[str, Any]]] = {}
        self.consumed_nonces: set[str] = set()
        self.mutation_count = 0

    def execute(
        self,
        proposal: dict[str, Any],
        approval: dict[str, Any],
        recheck: dict[str, Any],
        execution_principal: str,
        idempotency_key: str,
        post_state: dict[str, Any],
        execution_artifact: dict[str, Any] | None = None,
        execution_targets: list[str] | None = None,
    ) -> dict[str, Any]:
        artifact = copy.deepcopy(execution_artifact or proposal["artifact"])
        targets = copy.deepcopy(execution_targets or proposal["resolved_targets"])
        request_core = {
            "proposal_id": proposal["proposal_id"],
            "approval_id": approval["approval_id"],
            "artifact_sha256": sha256_ref(artifact),
            "resolved_targets": targets,
            "execution_principal": execution_principal,
            "post_state": post_state,
        }
        request_hash = sha256_ref(request_core)
        if idempotency_key in self.by_idempotency_key:
            previous_hash, previous_result = self.by_idempotency_key[idempotency_key]
            if previous_hash != request_hash:
                return {
                    "status": "HOLD",
                    "reason_codes": ["IDEMPOTENCY_KEY_CONFLICT"],
                    "idempotency_key": idempotency_key,
                    "simulated_execution": True,
                    "external_write_performed": False,
                    "idempotent_replay": False,
                }
            replay = copy.deepcopy(previous_result)
            replay["idempotent_replay"] = True
            return replay

        reasons: list[str] = []
        protected_core = {
            key: value for key, value in approval.items() if key != "protected_record_ref"
        }
        if sha256_ref(protected_core) != approval.get("protected_record_ref"):
            reasons.append("APPROVAL_RECORD_INTEGRITY_MISMATCH")
        approval_core = {
            key: value
            for key, value in approval.items()
            if key not in {"approval_id", "permit_nonce", "protected_record_ref"}
        }
        if sha256_ref(approval_core) != approval.get("approval_id"):
            reasons.append("APPROVAL_ID_MISMATCH")
        expected_nonce = sha256_ref(
            {
                "approval_id": approval.get("approval_id"),
                "purpose": "single-use-simulated-execution",
            }
        )
        if expected_nonce != approval.get("permit_nonce"):
            reasons.append("PERMIT_NONCE_BINDING_MISMATCH")
        if recheck.get("status") != "RECHECK_PASSED":
            reasons.append("EXECUTION_RECHECK_REQUIRED")
        if execution_principal != approval.get("required_executor"):
            reasons.append("EXECUTOR_IDENTITY_DENIED")
        if execution_principal != self.policy["executor"]["principal"]:
            reasons.append("EXECUTOR_OUTSIDE_POLICY")
        if sha256_ref(artifact) != approval.get("artifact_sha256"):
            reasons.append("EXECUTOR_ARTIFACT_BINDING_MISMATCH")
        if targets != approval.get("resolved_targets"):
            reasons.append("EXECUTOR_SCOPE_BINDING_MISMATCH")
        if approval.get("permit_nonce") in self.consumed_nonces:
            reasons.append("PERMIT_NONCE_REUSED")
        if not idempotency_key:
            reasons.append("IDEMPOTENCY_KEY_REQUIRED")
        if reasons:
            return {
                "status": "HOLD",
                "reason_codes": sorted(set(reasons)),
                "idempotency_key": idempotency_key,
                "simulated_execution": True,
                "external_write_performed": False,
                "idempotent_replay": False,
            }

        self.consumed_nonces.add(approval["permit_nonce"])
        self.mutation_count += 1
        desired = artifact.get("desired_state", {})
        verification_failures = [
            target for target in targets if post_state.get(target) != desired
        ]
        if verification_failures:
            status = "VERIFICATION_FAILED"
            verification_status = "not_supported"
            result_reasons = ["POST_EXECUTION_STATE_MISMATCH"]
        else:
            status = "EXECUTED_AND_VERIFIED"
            verification_status = "supported_for_exact_target_state"
            result_reasons = []
        result = {
            "status": status,
            "reason_codes": result_reasons,
            "idempotency_key": idempotency_key,
            "idempotent_replay": False,
            "simulated_execution": True,
            "external_write_performed": False,
            "production_write_credential": "none",
            "executor_principal": execution_principal,
            "permit_nonce": approval["permit_nonce"],
            "execution_request_sha256": request_hash,
            "execution_accepted": True,
            "target_state_changed": "simulated",
            "verification_status": verification_status,
            "verification_failures": verification_failures,
            "reversal_record": {
                "reviewed_operation": proposal["reversal"]["operation"],
                "artifact_ref": proposal["reversal"]["artifact_ref"],
                "invoked": False,
                "reason": "not automatically invoked by this demonstration",
            },
        }
        self.by_idempotency_key[idempotency_key] = (request_hash, copy.deepcopy(result))
        return result


def load_gate() -> tuple[ChangeGate, dict[str, Any]]:
    policy = read_json(POLICY_PATH)
    catalog = read_json(CATALOG_PATH)
    scenarios = read_json(SCENARIOS_PATH)
    return ChangeGate(policy, catalog, scenarios), scenarios


def run_case(
    gate: ChangeGate,
    case: dict[str, Any],
    executor: SimulatedExecutor | None = None,
) -> dict[str, Any]:
    proposal = gate.proposal(case["proposal_ref"])
    decision = gate.decide(case)
    record: dict[str, Any] = {
        "artifact_class": DATA_CLASS,
        "case_id": case["case_id"],
        "proposal_id": proposal["proposal_id"],
        "proposal_ref": case["proposal_ref"],
        "proposal_binding_sha256": gate.proposal_binding_sha256(proposal),
        "artifact_sha256": gate.artifact_sha256(proposal),
        "decision": decision,
        "execution_recheck": None,
        "execution": None,
        "execution_retry": None,
        "executor_mutation_count": None,
        "final_status": decision["status"],
        "reason_codes": decision["reason_codes"],
    }
    if decision["status"] == "AUTHORIZED_PENDING_RECHECK" and case.get(
        "execution_requested"
    ):
        recheck = gate.recheck(case, decision)
        record["execution_recheck"] = recheck
        if recheck["status"] == "HOLD":
            record["final_status"] = "HOLD"
            record["reason_codes"] = recheck["reason_codes"]
        else:
            runner = executor or SimulatedExecutor(gate.policy)
            execution = runner.execute(
                proposal,
                decision["approval"],
                recheck,
                case["execution_principal"],
                case["idempotency_key"],
                copy.deepcopy(case["post_state"]),
                copy.deepcopy(case.get("execution_artifact_override")),
                copy.deepcopy(case.get("execution_resolved_targets")),
            )
            record["execution"] = execution
            if case.get("repeat_execution"):
                record["execution_retry"] = runner.execute(
                    proposal,
                    decision["approval"],
                    recheck,
                    case["execution_principal"],
                    case["idempotency_key"],
                    copy.deepcopy(case["post_state"]),
                    copy.deepcopy(case.get("execution_artifact_override")),
                    copy.deepcopy(case.get("execution_resolved_targets")),
                )
            record["executor_mutation_count"] = runner.mutation_count
            record["final_status"] = execution["status"]
            record["reason_codes"] = execution["reason_codes"]
    expected = case.get("expected_final_status")
    if expected and record["final_status"] != expected:
        raise AssertionError(
            f"{case['case_id']} expected {expected}, got {record['final_status']}"
        )
    record["record_sha256"] = sha256_ref(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )
    return record


def _packet_payload(
    gate: ChangeGate, scenarios: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    template = read_json(TEMPLATE_PATH)
    required = {"proposal", "evidence", "safety_and_recovery", "authority", "provenance"}
    if not required.issubset(template):
        raise ValueError("freeze-exception template is missing required sections")
    record = next(item for item in records if item["case_id"] == "freeze-named-review-ready")
    proposal = gate.proposal("freeze_exception")
    assessment = record["decision"]["assessment"]
    dependency = gate.evidence.get("E-DEPENDENCY-DECISION-OK")
    expires_at = record["decision"]["expires_at"]
    packet = {
        "artifact_class": DATA_CLASS,
        "packet_type": "freeze_exception_decision_support",
        "supported_boundary": (
            "Constructed decision-support packet. It does not approve the exception, "
            "prove safety, or establish complete dependency coverage."
        ),
        "proposal": {
            "proposal_id": proposal["proposal_id"],
            "proposal_binding_sha256": record["proposal_binding_sha256"],
            "artifact_sha256": record["artifact_sha256"],
            "artifact": proposal["artifact"],
            "resolved_targets": proposal["resolved_targets"],
            "assertions_with_owner": [
                {
                    "assertion": proposal["assertions"]["justification"],
                    "owner": proposal["assertions"]["deadline_owner"],
                },
                {
                    "assertion": proposal["assertions"]["requested_window"],
                    "owner": proposal["assertions"]["deadline_owner"],
                },
            ],
            "requested_authority_path": "named_positive_acknowledgement",
        },
        "evidence": {
            "decision_snapshot_sha256": assessment["snapshot_sha256"],
            "declared_live_comparison": assessment["comparison_rows"],
            "source_statuses": assessment["source_statuses"],
            "dependency_bound_and_blind_spots": dependency["content"],
            "in_flight_changes": [],
            "canonical_reliability_policy_state": gate.evidence.get(
                "E-RELIABILITY-DECISION-GO"
            )["content"],
            "prior_cases_with_applicability_limits": [],
        },
        "safety_and_recovery": {
            "preconditions": [
                "all required evidence is usable under claim-specific policy",
                "declared and scoped live configuration match on the touched subject",
                "no interacting change is reported in the stated scope",
                "the canonical reliability policy permits the change",
            ],
            "stop_conditions": proposal["stop_conditions"],
            "verification_contract": proposal["verification"],
            "reversal_contract": proposal["reversal"],
            "conditions_for_re_review": [
                "artifact hash changes",
                "target scope changes",
                "approval expires",
                "volatile evidence changes or becomes unusable",
                "signer authority changes",
            ],
        },
        "authority": {
            "policy_id": gate.policy["policy_id"],
            "policy_version": gate.policy["version"],
            "catalog_version": gate.catalog["version"],
            "required_signers": [
                {"role": "change-authority", "eligible_signers": ["reviewer-a"]}
            ],
            "positive_acknowledgements": [],
            "current_status": "AWAITING_POSITIVE_ACKNOWLEDGEMENT",
            "silence_result": "HOLD",
            "rejected_alternatives": [
                {
                    "alternative": "automatic exception approval",
                    "reason": "the action is outside the human-approved standard catalog",
                },
                {
                    "alternative": "approval by timeout",
                    "reason": "silence carries no authority",
                },
            ],
            "expires_at": expires_at,
            "execution_time_recheck_required": True,
            "executor_principal": gate.policy["executor"]["principal"],
            "proposer_may_execute": False,
            "authorizer_may_execute": False,
        },
        "provenance": {
            "input_refs": {
                "policy": f"sha256:{file_sha256(POLICY_PATH)}",
                "catalog": f"sha256:{file_sha256(CATALOG_PATH)}",
                "scenarios": f"sha256:{file_sha256(SCENARIOS_PATH)}",
                "template": f"sha256:{file_sha256(TEMPLATE_PATH)}",
            },
            "transformation_version": TRANSFORMATION_VERSION,
            "generated_from_case": record["case_id"],
        },
    }
    packet["provenance"]["packet_payload_sha256"] = sha256_ref(packet)
    return packet


def _render_packet_markdown(packet: dict[str, Any]) -> str:
    proposal = packet["proposal"]
    evidence = packet["evidence"]
    authority = packet["authority"]
    lines = [
        "# Chapter 5 Freeze-Exception Packet",
        "",
        "> Constructed illustration. This packet supports a named human decision; it",
        "> does not approve the exception, prove safety, or establish complete dependency",
        "> coverage.",
        "",
        "## Proposal binding",
        "",
        f"- Proposal: `{proposal['proposal_id']}`",
        f"- Proposal binding: `{proposal['proposal_binding_sha256']}`",
        f"- Exact artifact: `{proposal['artifact_sha256']}`",
        f"- Resolved targets: `{', '.join(proposal['resolved_targets'])}`",
        f"- Requested authority path: `{proposal['requested_authority_path']}`",
        "- Proposer production write credential: `none`",
        "",
        "The deadline and justification are assertions by `request-owner`; they are not",
        "authorization tokens.",
        "",
        "## Decision-time evidence",
        "",
        f"Snapshot: `{evidence['decision_snapshot_sha256']}`",
        "",
        "| Claim | State | Evidence ID | Freshness | Source health |",
        "|---|---|---|---|---|",
    ]
    for claim, status in evidence["source_statuses"].items():
        freshness = status.get("computed_freshness", {}).get("status", "not_usable")
        lines.append(
            f"| `{claim}` | `{status['state']}` | "
            f"`{status.get('selected_evidence_id', 'none')}` | `{freshness}` | "
            f"`{status.get('source_health', 'unknown')}` |"
        )
    lines.extend(
        [
            "",
            "## Declared/live comparison",
            "",
            "| Subject | Field | Declared | Observed | Result |",
            "|---|---|---|---|---|",
        ]
    )
    for row in evidence["declared_live_comparison"]:
        lines.append(
            f"| `{row['subject_id']}` | `{row['field']}` | `{row['declared_value']}` | "
            f"`{row['observed_value']}` | `{row['comparison']}` |"
        )
    dependency = evidence["dependency_bound_and_blind_spots"]
    lines.extend(
        [
            "",
            "## Dependency interpretation",
            "",
            f"- Coverage status: `{dependency['coverage_status']}`",
            f"- Checked classes: `{', '.join(dependency['checked_classes'])}`",
            f"- Excluded classes: `{', '.join(dependency['excluded_classes']) or 'none recorded'}`",
            f"- Observed reachable subjects: `{', '.join(dependency['reachable_subjects'])}`",
            "- Interpretation: a lower bound under the stated representation and window;",
            "  it is not a maximum blast-radius claim.",
            "",
            "## Preconditions, stop, and recovery",
            "",
        ]
    )
    for item in packet["safety_and_recovery"]["preconditions"]:
        lines.append(f"- Preconditions: {item}.")
    for item in packet["safety_and_recovery"]["stop_conditions"]:
        lines.append(f"- Stop on: `{item}`.")
    lines.extend(
        [
            f"- Verification: `{packet['safety_and_recovery']['verification_contract']['method']}`.",
            f"- Reviewed reversal: `{packet['safety_and_recovery']['reversal_contract']['operation']}`.",
            "",
            "## Authority",
            "",
            f"- Current status: `{authority['current_status']}`",
            f"- Policy: `{authority['policy_id']}@{authority['policy_version']}`",
            f"- Decision expires: `{authority['expires_at']}`",
            f"- Silence: `{authority['silence_result']}`",
            f"- Required executor: `{authority['executor_principal']}`",
            "- A separately credentialed executor rechecks artifact, scope, policy,",
            "  evidence, signer authority, and state immediately before simulated execution.",
            "",
            "## Alternatives retained",
            "",
        ]
    )
    for alternative in authority["rejected_alternatives"]:
        lines.append(f"- **{alternative['alternative']}:** {alternative['reason']}.")
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- Transformation: `{packet['provenance']['transformation_version']}`",
            f"- Packet payload: `{packet['provenance']['packet_payload_sha256']}`",
        ]
    )
    for name, reference in packet["provenance"]["input_refs"].items():
        lines.append(f"- `{name}`: `{reference}`")
    lines.append("")
    return "\n".join(lines)


def _comparison_csv(records: list[dict[str, Any]]) -> str:
    fields = [
        "artifact_class",
        "case_id",
        "proposal_id",
        "phase",
        "subject_id",
        "field",
        "declared_value",
        "observed_value",
        "comparison",
        "declared_evidence_ref",
        "observed_evidence_ref",
        "coverage",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        assessments = [record["decision"].get("assessment")]
        if record.get("execution_recheck"):
            assessments.append(record["execution_recheck"]["assessment"])
        for assessment in assessments:
            if not assessment:
                continue
            for row in assessment.get("comparison_rows", []):
                writer.writerow({"case_id": record["case_id"], **row})
    return output.getvalue()


def artifact_label(path: Path) -> str:
    """Name an output by where it is actually written.

    Paths inside the companion are reported relative to the companion root;
    anything published outside it (a manuscript tree, a temporary directory)
    is reported as an absolute path. The manifest therefore cannot claim a
    location the run did not write to.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(COMPANION_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def render_artifacts(
    output_root: Path = GENERATED_ROOT,
    figure_root: Path = BOOK_FIGURE_ROOT,
) -> dict[str, tuple[Path, bytes]]:
    """Build every Chapter 5 output in memory, keyed by logical name.

    Rendering is separate from writing so that --verify can compare the real
    committed paths without writing anything.
    """
    gate, scenarios = load_gate()
    records = [run_case(gate, copy.deepcopy(case)) for case in scenarios["cases"]]
    decisions = {
        "artifact_class": DATA_CLASS,
        "supported_boundary": (
            "Deterministic constructed demonstration of binding and hold behavior; "
            "not a production safety or effectiveness result."
        ),
        "policy": {
            "policy_id": gate.policy["policy_id"],
            "version": gate.policy["version"],
            "catalog_version": gate.catalog["version"],
        },
        "authority_boundary": {
            "model_credentials": "none",
            "proposer_production_write_credential": "none",
            "executor": gate.policy["executor"],
            "silence_executes": False,
            "gate_self_change_route": "separate_human_owned_path",
        },
        "decision_time": scenarios["decision_time"],
        "execution_time": scenarios["execution_time"],
        "transformation_version": TRANSFORMATION_VERSION,
        "cases": records,
    }
    packet = _packet_payload(gate, scenarios, records)
    artifacts: dict[str, tuple[Path, bytes]] = {
        "decisions": (output_root / DECISIONS_PATH.name, _json_bytes(decisions)),
        "comparison": (
            output_root / COMPARISON_PATH.name,
            _comparison_csv(records).encode("utf-8"),
        ),
        "packet_json": (output_root / PACKET_JSON_PATH.name, _json_bytes(packet)),
        "packet_markdown": (
            output_root / PACKET_MD_PATH.name,
            _render_packet_markdown(packet).encode("utf-8"),
        ),
    }
    for name in FIGURE_NAMES:
        source = DIAGRAM_SOURCE_ROOT / name
        if not source.is_file():
            raise FileNotFoundError(f"missing Chapter 5 diagram source {source}")
        artifacts[name] = (figure_root / name, source.read_bytes())

    manifest = {
        "artifact_class": DATA_CLASS,
        "run_id": "ch05-constructed-run-1",
        "command": "make ch05-change-gate",
        "runtime_contract": "Python 3.11 or newer; standard library only; no network",
        "production_write_credential": "none",
        "external_write_performed": False,
        "transformation_version": TRANSFORMATION_VERSION,
        "inputs": {
            "companion/fixtures/ch05/policy.json": file_sha256(POLICY_PATH),
            "companion/fixtures/ch05/catalog.json": file_sha256(CATALOG_PATH),
            "companion/fixtures/ch05/scenarios.json": file_sha256(SCENARIOS_PATH),
            "companion/templates/ch05-freeze-exception-packet.json": file_sha256(
                TEMPLATE_PATH
            ),
            "companion/scripts/ch05_change_gate.py": file_sha256(Path(__file__)),
            **{
                f"companion/diagrams/src/{name}": file_sha256(
                    DIAGRAM_SOURCE_ROOT / name
                )
                for name in FIGURE_NAMES
            },
        },
        "outputs": {
            artifact_label(path): sha256_hex(payload)
            for path, payload in artifacts.values()
        },
        "limitations": [
            "constructed fixtures only",
            "dependency reachability remains a lower bound under stated coverage",
            "the executor records a simulated effect and performs no external write",
            "binding and recheck do not prove the proposed change is safe",
            "no causal change-failure or approval-time effect is estimated",
        ],
    }
    artifacts["manifest"] = (output_root / MANIFEST_PATH.name, _json_bytes(manifest))
    return artifacts


def generate(
    output_root: Path = GENERATED_ROOT,
    figure_root: Path = BOOK_FIGURE_ROOT,
) -> dict[str, Path]:
    artifacts = render_artifacts(output_root, figure_root)
    for path, payload in artifacts.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return {name: path for name, (path, _) in artifacts.items()}


def verify() -> None:
    mismatches = [
        name
        for name, (path, payload) in render_artifacts().items()
        if not path.is_file() or path.read_bytes() != payload
    ]
    if mismatches:
        raise SystemExit(
            "Chapter 5 generated artifacts are stale or missing: "
            + ", ".join(sorted(mismatches))
        )
    print("Chapter 5 generated artifacts match their constructed sources")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate committed outputs")
    mode.add_argument("--verify", action="store_true", help="fail if committed output drifts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.verify:
        verify()
        return
    outputs = generate()
    case_count = len(read_json(SCENARIOS_PATH).get("cases", []))
    print(f"evaluated {case_count} constructed Chapter 5 change-gate cases")
    for name in ("decisions", "comparison", "packet_json", "packet_markdown", "manifest"):
        print(f"wrote {outputs[name].relative_to(WORKSPACE_ROOT)}")
    for name in FIGURE_NAMES:
        print(f"wrote {outputs[name].relative_to(WORKSPACE_ROOT)}")


if __name__ == "__main__":
    main()
