from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import tempfile
import threading
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch06_guard.py"
SPEC = importlib.util.spec_from_file_location("ch06_guard", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter6GuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guard, self.executor, self.cases = MODULE.load_fixture_guard()
        self.valid = copy.deepcopy(self.cases["cases"][0]["proposal"])

    def case(self, case_id: str) -> dict:
        for item in self.cases["cases"]:
            if item["case_id"] == case_id:
                return copy.deepcopy(item["proposal"])
        raise KeyError(case_id)

    def test_valid_proposal_is_admitted_and_reserved(self) -> None:
        decision = self.guard.admit(self.valid)
        self.assertEqual(decision["outcome"], "admit")
        self.assertTrue(decision["reservation_id"].startswith("RSV-"))
        self.assertEqual(len(self.guard.reservations), 2)  # one recorded human action + one guard

    def test_idempotent_retry_reuses_reservation_without_spending_twice(self) -> None:
        first = self.guard.admit(self.valid)
        second = self.guard.admit(self.valid)
        self.assertEqual(first["reservation_id"], second["reservation_id"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(len(self.guard.reservations), 2)

    def test_reused_idempotency_key_with_different_payload_demotes(self) -> None:
        self.guard.admit(self.valid)
        changed = copy.deepcopy(self.valid)
        changed["parameters"]["units"] = 2
        decision = self.guard.admit(changed)
        self.assertIn("IDEMPOTENCY_KEY_CONFLICT", decision["reason_codes"])

    def test_stale_required_evidence_demotes(self) -> None:
        decision = self.guard.admit(self.case("stale-serving-evidence"))
        self.assertEqual(decision["outcome"], "demote")
        self.assertIn("EVIDENCE_STALE:serving", decision["reason_codes"])

    def test_denied_source_has_no_content_and_demotes(self) -> None:
        evidence = MODULE.read_json(MODULE.EVIDENCE_PATH)
        denied = next(i for i in evidence["evidence"] if i["evidence_id"] == "E-SERVING-DENIED")
        self.assertNotIn("content", denied)
        decision = self.guard.admit(self.case("denied-serving-source"))
        self.assertIn("EVIDENCE_DENIED:serving", decision["reason_codes"])

    def test_denied_source_with_content_is_rejected_as_invalid_fixture(self) -> None:
        evidence = MODULE.read_json(MODULE.EVIDENCE_PATH)
        denied = next(i for i in evidence["evidence"] if i["evidence_id"] == "E-SERVING-DENIED")
        denied["content"] = {"serving_units": 999}
        denied["content_sha256"] = MODULE.content_hash(denied["content"])
        with self.assertRaisesRegex(ValueError, "must not expose content"):
            MODULE.EvidenceStore(evidence)

    def test_tampered_available_evidence_is_rejected(self) -> None:
        evidence = MODULE.read_json(MODULE.EVIDENCE_PATH)
        fresh = next(i for i in evidence["evidence"] if i["evidence_id"] == "E-SERVING-FRESH")
        fresh["content"]["serving_units"] = 500
        with self.assertRaisesRegex(ValueError, "content hash mismatch"):
            MODULE.EvidenceStore(evidence)

    def test_active_owner_rejects_direct_owned_field_write(self) -> None:
        decision = self.guard.admit(self.case("direct-write-against-owner"))
        self.assertIn("CONTROLLER_SURFACE_MISMATCH", decision["reason_codes"])
        self.assertEqual(
            decision["details"]["controller_owner_result"]["supported_input"],
            "autoscaler.spec.max_units",
        )

    def test_executor_rechecks_scope_even_with_forged_admit(self) -> None:
        proposal = self.case("executor-scope-denied")
        forged = {
            "outcome": "admit",
            "reservation_id": "forged",
            "proposal_binding_sha256": MODULE.SerializedGuard._proposal_binding(proposal),
        }
        with self.assertRaisesRegex(PermissionError, "EXECUTOR_SCOPE_DENIED"):
            self.executor.execute(forged, proposal)

    def test_executor_records_simulation_without_external_write(self) -> None:
        decision = self.guard.admit(self.valid)
        execution = self.executor.execute(decision, self.valid)
        self.assertEqual(execution["execution"], "simulated")
        self.assertFalse(execution["external_write_performed"])

    def test_executor_idempotently_replays_same_reservation(self) -> None:
        first_decision = self.guard.admit(self.valid)
        first = self.executor.execute(first_decision, self.valid)
        replay_decision = self.guard.admit(self.valid)
        second = self.executor.execute(replay_decision, self.valid)
        self.assertEqual(first["reservation_id"], second["reservation_id"])
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])

    def test_missing_inverse_exercise_demotes(self) -> None:
        decision = self.guard.admit(self.case("inverse-not-verified"))
        self.assertIn("INVERSE_NOT_VERIFIED", decision["reason_codes"])

    def test_budget_includes_recorded_human_action(self) -> None:
        decision = self.guard.admit(self.valid)
        self.assertEqual(decision["budget_before"]["user_exposure_units"], 5)

    def test_cumulative_budget_blocks_third_distinct_reservation(self) -> None:
        proposals = []
        for suffix in ("A", "B", "C"):
            proposal = copy.deepcopy(self.valid)
            proposal["request_id"] = f"R-BUDGET-{suffix}"
            proposal["idempotency_key"] = f"IK-BUDGET-{suffix}"
            proposals.append(proposal)
        results = [self.guard.admit(proposal) for proposal in proposals]
        self.assertEqual([r["outcome"] for r in results], ["admit", "admit", "demote"])
        self.assertIn("CUMULATIVE_BUDGET_EXCEEDED", results[-1]["reason_codes"])

    def test_check_and_reserve_is_serialized_under_concurrency(self) -> None:
        first = copy.deepcopy(self.valid)
        first["request_id"] = "R-PRE"
        first["idempotency_key"] = "IK-PRE"
        self.assertEqual(self.guard.admit(first)["outcome"], "admit")

        barrier = threading.Barrier(3)
        results: list[dict] = []
        result_lock = threading.Lock()

        def submit(suffix: str) -> None:
            proposal = copy.deepcopy(self.valid)
            proposal["request_id"] = f"R-RACE-{suffix}"
            proposal["idempotency_key"] = f"IK-RACE-{suffix}"
            barrier.wait()
            decision = self.guard.admit(proposal)
            with result_lock:
                results.append(decision)

        threads = [threading.Thread(target=submit, args=(suffix,)) for suffix in ("A", "B")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sum(r["outcome"] == "admit" for r in results), 1)
        self.assertEqual(sum("CUMULATIVE_BUDGET_EXCEEDED" in r["reason_codes"] for r in results), 1)

    def test_indeterminate_outcome_preserves_reservation_and_demotes_class(self) -> None:
        first = self.guard.admit(self.valid)
        self.guard.mark_indeterminate(first["reservation_id"])
        record = next(
            r for r in self.guard.reservations if r["reservation_id"] == first["reservation_id"]
        )
        self.assertEqual(record["state"], "indeterminate")
        second = copy.deepcopy(self.valid)
        second["request_id"] = "R-AFTER-INDETERMINATE"
        second["idempotency_key"] = "IK-AFTER-INDETERMINATE"
        decision = self.guard.admit(second)
        self.assertIn("CLASS_DEMOTED_AFTER_INDETERMINATE", decision["reason_codes"])

    def test_invalid_parameter_is_rejected_before_reservation(self) -> None:
        proposal = copy.deepcopy(self.valid)
        proposal["parameters"]["units"] = 2
        decision = self.guard.admit(proposal)
        self.assertIn("PARAMETER_BOUND_EXCEEDED", decision["reason_codes"])
        self.assertIsNone(decision["reservation_id"])

    def test_missing_evidence_slot_is_fail_closed(self) -> None:
        proposal = copy.deepcopy(self.valid)
        del proposal["evidence_refs"]["serving"]
        decision = self.guard.admit(proposal)
        self.assertIn("EVIDENCE_MISSING:serving", decision["reason_codes"])

    def test_generated_artifacts_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            decisions = root / "decisions.json"
            report = root / "report.md"
            MODULE.generate(decisions, report)
            self.assertEqual(decisions.read_bytes(), MODULE.DECISIONS_PATH.read_bytes())
            self.assertEqual(report.read_bytes(), MODULE.REPORT_PATH.read_bytes())


if __name__ == "__main__":
    unittest.main()
