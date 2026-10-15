from __future__ import annotations

import copy
import csv
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch05_change_gate.py"
SPEC = importlib.util.spec_from_file_location("ch05_change_gate", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter5ChangeGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate, self.scenarios = MODULE.load_gate()

    def case(self, case_id: str) -> dict:
        for case in self.scenarios["cases"]:
            if case["case_id"] == case_id:
                return copy.deepcopy(case)
        raise KeyError(case_id)

    def run_case_id(self, case_id: str) -> dict:
        return MODULE.run_case(self.gate, self.case(case_id))

    def test_fixture_and_executor_have_no_production_write_path(self) -> None:
        self.assertEqual(self.scenarios["artifact_class"], "illustrative_constructed")
        self.assertEqual(self.gate.policy["executor"]["production_write_credential"], "none")
        for proposal in self.scenarios["proposals"].values():
            self.assertEqual(proposal["proposer"]["production_write_credential"], "none")
        result = self.run_case_id("standard-executes-and-verifies")
        self.assertFalse(result["execution"]["external_write_performed"])
        self.assertTrue(result["execution"]["simulated_execution"])

    def test_freeze_exception_routes_to_named_review_without_execution(self) -> None:
        result = self.run_case_id("freeze-named-review-ready")
        self.assertEqual(result["decision"]["decision_route"], "NAMED_REVIEW")
        self.assertEqual(result["final_status"], "AWAITING_POSITIVE_ACKNOWLEDGEMENT")
        self.assertIsNone(result["decision"]["approval"])
        self.assertIsNone(result["execution"])

    def test_positive_acknowledgement_authorizes_exact_request_then_rechecks(self) -> None:
        signed = self.case("named-positive-ack-executes")["acknowledgement"][
            "decision_binding_sha256"
        ]
        result = self.run_case_id("named-positive-ack-executes")
        self.assertEqual(result["final_status"], "EXECUTED_AND_VERIFIED")
        self.assertEqual(result["decision"]["decision_route"], "NAMED_REVIEW")
        acknowledgement = result["decision"]["acknowledgement"]
        approval = result["decision"]["approval"]
        # The binding under test is the one the signer supplied in the fixture,
        # not a value the gate wrote into the record it accepted.
        self.assertEqual(acknowledgement["decision_binding_sha256"], signed)
        self.assertEqual(
            acknowledgement["gate_computed"]["decision_binding_sha256"], signed
        )
        self.assertTrue(acknowledgement["decision_binding_verified"])
        self.assertEqual(
            acknowledgement["gate_computed"]["artifact_sha256"],
            result["artifact_sha256"],
        )
        self.assertEqual(
            acknowledgement["gate_computed"]["evidence_snapshot_sha256"],
            approval["evidence_snapshot_sha256"],
        )
        self.assertEqual(result["execution_recheck"]["status"], "RECHECK_PASSED")

    def test_acknowledgement_bound_to_a_stale_artifact_holds(self) -> None:
        result = self.run_case_id("hold-acknowledgement-bound-to-stale-artifact")
        self.assertEqual(result["final_status"], "HOLD")
        self.assertEqual(result["reason_codes"], ["ACKNOWLEDGEMENT_BINDING_MISMATCH"])
        acknowledgement = result["decision"]["acknowledgement"]
        self.assertFalse(acknowledgement["decision_binding_verified"])
        # The signer signed the pre-edit proposal, so the two bindings differ.
        self.assertEqual(
            acknowledgement["decision_binding_sha256"],
            self.case("named-positive-ack-executes")["acknowledgement"][
                "decision_binding_sha256"
            ],
        )
        self.assertNotEqual(
            acknowledgement["decision_binding_sha256"],
            acknowledgement["gate_computed"]["decision_binding_sha256"],
        )
        self.assertIsNone(result["decision"]["approval"])
        self.assertIsNone(result["execution"])

    def test_altered_or_absent_signer_binding_cannot_authorize(self) -> None:
        tampered = self.case("named-positive-ack-executes")
        tampered["acknowledgement"]["decision_binding_sha256"] = "sha256:" + "0" * 64
        tampered["expected_final_status"] = None
        decision = self.gate.decide(tampered)
        self.assertEqual(decision["status"], "HOLD")
        self.assertIn("ACKNOWLEDGEMENT_BINDING_MISMATCH", decision["reason_codes"])

        silent = self.case("named-positive-ack-executes")
        del silent["acknowledgement"]["decision_binding_sha256"]
        decision = self.gate.decide(silent)
        self.assertEqual(decision["status"], "HOLD")
        self.assertIn("ACKNOWLEDGEMENT_BINDING_MISSING", decision["reason_codes"])

    def test_missing_live_evidence_holds(self) -> None:
        result = self.run_case_id("hold-missing-live")
        self.assertIn("EVIDENCE_MISSING:current_configuration", result["reason_codes"])

    def test_stale_live_evidence_holds_under_named_policy(self) -> None:
        result = self.run_case_id("hold-stale-live")
        self.assertIn("EVIDENCE_STALE:current_configuration", result["reason_codes"])
        status = result["decision"]["assessment"]["source_statuses"][
            "current_configuration"
        ]
        self.assertEqual(status["freshness_policy"]["policy_id"], "ch05-change-gate-policy")
        self.assertEqual(status["freshness_policy"]["policy_version"], "1.0.0")

    def test_denied_evidence_holds_without_exposing_content(self) -> None:
        result = self.run_case_id("hold-denied-live")
        self.assertIn("EVIDENCE_DENIED:current_configuration", result["reason_codes"])
        denied = next(
            item for item in self.scenarios["evidence"] if item["evidence_id"] == "E-LIVE-DENIED"
        )
        self.assertNotIn("content", denied)

    def test_unavailable_or_denied_envelope_with_content_is_rejected(self) -> None:
        scenarios = copy.deepcopy(self.scenarios)
        denied = next(
            item for item in scenarios["evidence"] if item["evidence_id"] == "E-LIVE-DENIED"
        )
        denied["content"] = {"subjects": {"route-a": {"route_mode": "shared"}}}
        with self.assertRaisesRegex(ValueError, "must not expose content"):
            MODULE.EvidenceStore(scenarios)

    def test_partial_dependency_evidence_holds(self) -> None:
        result = self.run_case_id("hold-partial-dependency")
        self.assertIn("EVIDENCE_PARTIAL:dependency_coverage", result["reason_codes"])

    def test_conflicting_live_sources_are_preserved_and_hold(self) -> None:
        result = self.run_case_id("hold-conflicting-live")
        self.assertIn("EVIDENCE_CONFLICTING:current_configuration", result["reason_codes"])
        status = result["decision"]["assessment"]["source_statuses"][
            "current_configuration"
        ]
        self.assertEqual(status["state"], "conflicting")
        self.assertEqual(len(status["candidate_immutable_refs"]), 2)

    def test_silence_never_executes(self) -> None:
        result = self.run_case_id("hold-silence")
        self.assertEqual(result["final_status"], "HOLD")
        self.assertIn("ACKNOWLEDGEMENT_MISSING", result["reason_codes"])
        self.assertIsNone(result["execution"])

    def test_acknowledgement_after_expiry_holds(self) -> None:
        result = self.run_case_id("hold-timeout")
        self.assertIn("ACKNOWLEDGEMENT_EXPIRED", result["reason_codes"])
        self.assertIsNone(result["decision"]["approval"])

    def test_standard_class_is_human_catalog_authority_not_model_authority(self) -> None:
        result = self.run_case_id("standard-executes-and-verifies")
        approval = result["decision"]["approval"]
        self.assertEqual(result["decision"]["decision_route"], "PREAUTHORIZED_STANDARD_CLASS")
        self.assertEqual(approval["authority_type"], "human_approved_catalog_class")
        self.assertEqual(approval["catalog_class_id"], "standard-route-isolation-v1")
        self.assertEqual(result["final_status"], "EXECUTED_AND_VERIFIED")
        self.assertTrue(result["execution_retry"]["idempotent_replay"])
        self.assertEqual(result["executor_mutation_count"], 1)

    def test_catalog_parameter_outside_human_approved_class_holds(self) -> None:
        scenarios = copy.deepcopy(self.scenarios)
        scenarios["proposals"]["standard_change"]["artifact"]["desired_state"][
            "security_boundary"
        ] = "boundary-b"
        gate = MODULE.ChangeGate(self.gate.policy, self.gate.catalog, scenarios)
        result = gate.decide(self.case("standard-executes-and-verifies"))
        self.assertEqual(result["status"], "HOLD")
        self.assertIn("CATALOG_PARAMETER_DENIED:security_boundary", result["reason_codes"])

    def test_artifact_hash_change_invalidates_approval(self) -> None:
        result = self.run_case_id("hold-artifact-changed")
        self.assertIn("ARTIFACT_CHANGED_AFTER_APPROVAL", result["reason_codes"])
        self.assertNotEqual(
            result["artifact_sha256"], result["execution_recheck"]["execution_artifact_sha256"]
        )

    def test_artifact_hash_is_exact_and_changes_with_one_parameter(self) -> None:
        proposal = self.gate.proposal("standard_change")
        original = self.gate.artifact_sha256(proposal)
        proposal["artifact"]["desired_state"]["security_boundary"] = "boundary-b"
        self.assertNotEqual(original, self.gate.artifact_sha256(proposal))

    def test_changed_target_and_artifact_target_mismatch_hold(self) -> None:
        result = self.run_case_id("hold-target-changed")
        self.assertIn("TARGET_SCOPE_CHANGED_AFTER_APPROVAL", result["reason_codes"])
        self.assertIn("EXECUTION_ARTIFACT_TARGET_MISMATCH", result["reason_codes"])

    def test_execution_time_state_drift_holds(self) -> None:
        result = self.run_case_id("hold-execution-state-drift")
        self.assertIn("STATE_CHANGED_SINCE_DECISION", result["reason_codes"])
        self.assertIn("CONFIGURATION_DRIFT_AT_EXECUTION", result["reason_codes"])

    def test_interacting_change_holds(self) -> None:
        result = self.run_case_id("hold-interacting-change")
        self.assertIn("INTERACTING_CHANGE_PRESENT", result["reason_codes"])

    def test_canonical_reliability_policy_stop_holds(self) -> None:
        result = self.run_case_id("hold-canonical-policy-stop")
        self.assertIn("CANONICAL_RELIABILITY_POLICY_BLOCK", result["reason_codes"])

    def test_proposer_cannot_act_as_executor(self) -> None:
        result = self.run_case_id("hold-proposer-as-executor")
        self.assertIn("SEPARATION_OF_DUTIES_VIOLATION", result["reason_codes"])
        self.assertIsNone(result["execution"])

    def test_execution_acceptance_and_verification_are_separate(self) -> None:
        result = self.run_case_id("verification-fails")
        execution = result["execution"]
        self.assertTrue(execution["execution_accepted"])
        self.assertEqual(execution["target_state_changed"], "simulated")
        self.assertEqual(execution["verification_status"], "not_supported")
        self.assertEqual(result["final_status"], "VERIFICATION_FAILED")

    def test_idempotent_retry_replays_result_without_second_mutation(self) -> None:
        case = self.case("standard-executes-and-verifies")
        proposal = self.gate.proposal(case["proposal_ref"])
        decision = self.gate.decide(case)
        recheck = self.gate.recheck(case, decision)
        executor = MODULE.SimulatedExecutor(self.gate.policy)
        args = (
            proposal,
            decision["approval"],
            recheck,
            case["execution_principal"],
            case["idempotency_key"],
            case["post_state"],
        )
        first = executor.execute(*args)
        second = executor.execute(*args)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(executor.mutation_count, 1)

    def test_reused_idempotency_key_with_different_request_holds(self) -> None:
        case = self.case("standard-executes-and-verifies")
        proposal = self.gate.proposal(case["proposal_ref"])
        decision = self.gate.decide(case)
        recheck = self.gate.recheck(case, decision)
        executor = MODULE.SimulatedExecutor(self.gate.policy)
        executor.execute(
            proposal,
            decision["approval"],
            recheck,
            case["execution_principal"],
            case["idempotency_key"],
            case["post_state"],
        )
        changed_post_state = copy.deepcopy(case["post_state"])
        changed_post_state["route-a"]["route_mode"] = "shared"
        second = executor.execute(
            proposal,
            decision["approval"],
            recheck,
            case["execution_principal"],
            case["idempotency_key"],
            changed_post_state,
        )
        self.assertIn("IDEMPOTENCY_KEY_CONFLICT", second["reason_codes"])
        self.assertEqual(executor.mutation_count, 1)

    def test_single_use_permit_cannot_run_under_a_new_idempotency_key(self) -> None:
        case = self.case("standard-executes-and-verifies")
        proposal = self.gate.proposal(case["proposal_ref"])
        decision = self.gate.decide(case)
        recheck = self.gate.recheck(case, decision)
        executor = MODULE.SimulatedExecutor(self.gate.policy)
        executor.execute(
            proposal,
            decision["approval"],
            recheck,
            case["execution_principal"],
            case["idempotency_key"],
            case["post_state"],
        )
        replay = executor.execute(
            proposal,
            decision["approval"],
            recheck,
            case["execution_principal"],
            "IK-STANDARD-NEW",
            case["post_state"],
        )
        self.assertIn("PERMIT_NONCE_REUSED", replay["reason_codes"])
        self.assertEqual(executor.mutation_count, 1)

    def test_executor_refuses_a_request_without_passing_recheck(self) -> None:
        case = self.case("standard-executes-and-verifies")
        proposal = self.gate.proposal(case["proposal_ref"])
        decision = self.gate.decide(case)
        executor = MODULE.SimulatedExecutor(self.gate.policy)
        result = executor.execute(
            proposal,
            decision["approval"],
            {"status": "HOLD"},
            case["execution_principal"],
            case["idempotency_key"],
            case["post_state"],
        )
        self.assertIn("EXECUTION_RECHECK_REQUIRED", result["reason_codes"])

    def test_executor_rejects_a_tampered_approval_record(self) -> None:
        case = self.case("standard-executes-and-verifies")
        proposal = self.gate.proposal(case["proposal_ref"])
        decision = self.gate.decide(case)
        recheck = self.gate.recheck(case, decision)
        approval = copy.deepcopy(decision["approval"])
        approval["authority_identity"] = "forged-authority"
        executor = MODULE.SimulatedExecutor(self.gate.policy)
        result = executor.execute(
            proposal,
            approval,
            recheck,
            case["execution_principal"],
            case["idempotency_key"],
            case["post_state"],
        )
        self.assertIn("APPROVAL_RECORD_INTEGRITY_MISMATCH", result["reason_codes"])
        self.assertIn("APPROVAL_ID_MISMATCH", result["reason_codes"])
        self.assertEqual(executor.mutation_count, 0)

    def test_future_evidence_is_fail_visible(self) -> None:
        scenarios = copy.deepcopy(self.scenarios)
        live = next(
            item
            for item in scenarios["evidence"]
            if item["evidence_id"] == "E-LIVE-DECISION-OK"
        )
        live["source_update_time"] = "2026-02-10T12:00:01Z"
        live["retrieval_time"] = "2026-02-10T12:00:02Z"
        gate = MODULE.ChangeGate(self.gate.policy, self.gate.catalog, scenarios)
        result = gate.decide(self.case("freeze-named-review-ready"))
        self.assertIn("EVIDENCE_FROM_FUTURE:current_configuration", result["reason_codes"])

    def test_wrong_source_state_class_holds(self) -> None:
        scenarios = copy.deepcopy(self.scenarios)
        live = next(
            item
            for item in scenarios["evidence"]
            if item["evidence_id"] == "E-LIVE-DECISION-OK"
        )
        live["source_state_class"] = "recorded_intent"
        gate = MODULE.ChangeGate(self.gate.policy, self.gate.catalog, scenarios)
        result = gate.decide(self.case("freeze-named-review-ready"))
        self.assertIn("EVIDENCE_TYPE_MISMATCH:current_configuration", result["reason_codes"])

    def test_gate_cannot_approve_its_own_policy_change(self) -> None:
        result = self.run_case_id("hold-gate-self-change")
        self.assertEqual(result["decision"]["decision_route"], "SEPARATE_HUMAN_OWNED_PATH")
        self.assertIn("GATE_SELF_CHANGE_REQUIRES_SEPARATE_PATH", result["reason_codes"])

    def test_packet_is_constructed_and_keeps_dependency_limit_visible(self) -> None:
        packet = json.loads(MODULE.PACKET_JSON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(packet["artifact_class"], "illustrative_constructed")
        self.assertEqual(packet["authority"]["current_status"], "AWAITING_POSITIVE_ACKNOWLEDGEMENT")
        self.assertEqual(packet["authority"]["silence_result"], "HOLD")
        markdown = MODULE.PACKET_MD_PATH.read_text(encoding="utf-8")
        self.assertIn("lower bound", markdown)
        self.assertIn("does not approve the exception", markdown)

    def test_comparison_csv_labels_every_row_constructed(self) -> None:
        rows = list(
            csv.DictReader(io.StringIO(MODULE.COMPARISON_PATH.read_text(encoding="utf-8")))
        )
        self.assertGreater(len(rows), 0)
        self.assertEqual({row["artifact_class"] for row in rows}, {"illustrative_constructed"})
        drift = [
            row
            for row in rows
            if row["case_id"] == "hold-execution-state-drift"
            and row["phase"] == "execution"
            and row["comparison"] == "different"
        ]
        self.assertEqual(len(drift), 1)

    def test_manifest_records_inputs_outputs_and_limitations(self) -> None:
        manifest = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["artifact_class"], "illustrative_constructed")
        self.assertFalse(manifest["external_write_performed"])
        self.assertIn("companion/scripts/ch05_change_gate.py", manifest["inputs"])
        self.assertIn(
            "generated/published-figures/figure-5-1-change-gate-decision-flow.svg",
            manifest["outputs"],
        )
        self.assertTrue(any("do not prove" in item for item in manifest["limitations"]))

    def test_generated_outputs_and_figures_are_deterministic(self) -> None:
        rendered = MODULE.render_artifacts()
        self.assertEqual(rendered, MODULE.render_artifacts())
        committed = {
            "decisions": MODULE.DECISIONS_PATH,
            "comparison": MODULE.COMPARISON_PATH,
            "packet_json": MODULE.PACKET_JSON_PATH,
            "packet_markdown": MODULE.PACKET_MD_PATH,
            "manifest": MODULE.MANIFEST_PATH,
            **{name: MODULE.BOOK_FIGURE_ROOT / name for name in MODULE.FIGURE_NAMES},
        }
        for name, (path, payload) in rendered.items():
            self.assertEqual(path, committed[name], name)
            self.assertEqual(payload, committed[name].read_bytes(), name)

    def test_manifest_names_the_root_the_run_actually_wrote_to(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            generated = MODULE.generate(root / "generated", root / "figures")
            manifest = json.loads(
                generated["manifest"].read_text(encoding="utf-8")
            )
            figure = MODULE.FIGURE_NAMES[0]
            self.assertIn(
                str((root / "figures" / figure).resolve()), manifest["outputs"]
            )
            self.assertNotIn(
                "generated/published-figures/" + figure, manifest["outputs"]
            )
            self.assertEqual(
                generated[figure].read_bytes(),
                (MODULE.DIAGRAM_SOURCE_ROOT / figure).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
