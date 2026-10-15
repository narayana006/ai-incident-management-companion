from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch08_incident_replay.py"
SPEC = importlib.util.spec_from_file_location("ch08_incident_replay", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter8IncidentReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = MODULE.read_json()

    def test_fixture_is_constructed_generic_and_non_performance_claiming(self) -> None:
        self.assertEqual(self.fixture["artifact_class"], "illustrative_constructed")
        label = self.fixture["source_label"].lower()
        self.assertIn("constructed", label)
        self.assertIn("not production performance", label)
        serialized = json.dumps(self.fixture).lower()
        self.assertNotIn("equifax", serialized)
        self.assertNotIn("amazon", serialized)
        self.assertNotIn("confluent", serialized)

    def test_incident_states_are_typed_and_chain_reaches_reopen(self) -> None:
        replay = MODULE.replay_incident(self.fixture)
        states = [event["to"] for event in replay["transitions"]]
        self.assertEqual(states, list(MODULE.INCIDENT_STATES))
        self.assertEqual(replay["current_state"], "reopened")

    def test_cutoff_excludes_late_reopen_without_rewriting_close(self) -> None:
        at_close = MODULE.replay_incident(self.fixture, "sequence-08")
        self.assertEqual(at_close["current_state"], "closed")
        self.assertEqual(len(at_close["transitions"]), 8)
        self.assertEqual(at_close["transitions"][-1]["to"], "closed")
        full = MODULE.replay_incident(self.fixture)
        self.assertEqual(full["transitions"][-1]["from"], "closed")
        self.assertEqual(full["transitions"][-1]["to"], "reopened")

    def test_transition_provenance_is_hash_linked_and_stable(self) -> None:
        first = MODULE.replay_incident(self.fixture)
        second = MODULE.replay_incident(copy.deepcopy(self.fixture))
        self.assertEqual(first, second)
        self.assertEqual(first["transitions"][0]["prior_record_digest"], "GENESIS")
        for earlier, later in zip(first["transitions"], first["transitions"][1:]):
            self.assertEqual(later["prior_record_digest"], earlier["record_digest"])
        self.assertEqual(first["chain_head"], first["transitions"][-1]["record_digest"])

    def test_invalid_incident_transition_is_rejected(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        fixture["transitions"][3]["to"] = "closed"
        with self.assertRaisesRegex(ValueError, "invalid incident transition"):
            MODULE.validate_fixture(fixture)

    def test_incident_command_is_human_owned(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        command = next(
            role for role in fixture["role_assignments"] if role["role"] == "incident_command"
        )
        command["actor"] = "agent://fixture/model"
        with self.assertRaisesRegex(ValueError, "human actor"):
            MODULE.validate_fixture(fixture)

    def test_verified_action_requires_positive_human_acknowledgement(self) -> None:
        action = copy.deepcopy(self.fixture["action_record"])
        self.assertEqual(MODULE.evaluate_action(action)["state"], "verified")
        action["acknowledgement"]["state"] = "silent"
        held = MODULE.evaluate_action(action)
        self.assertEqual(held["state"], "held")
        self.assertEqual(held["reason"], "POSITIVE_ACKNOWLEDGEMENT_MISSING")

    def test_partial_execution_is_indeterminate_not_success(self) -> None:
        action = copy.deepcopy(self.fixture["action_record"])
        action["execution_result"] = "partial"
        result = MODULE.evaluate_action(action)
        self.assertEqual(result["state"], "indeterminate")
        self.assertEqual(result["reason"], "PARTIAL_EXECUTION")

    def test_lost_observation_path_is_indeterminate(self) -> None:
        action = copy.deepcopy(self.fixture["action_record"])
        action["observation_result"] = "unknown"
        action["observation_evidence_refs"] = []
        result = MODULE.evaluate_action(action)
        self.assertEqual(result["state"], "indeterminate")
        self.assertEqual(result["reason"], "OBSERVATION_PATH_INCOMPLETE")

    def test_sentinel_fixture_covers_supported_failed_and_indeterminate(self) -> None:
        failures = []
        for case in self.fixture["sentinel_cases"]:
            actual = MODULE.evaluate_sentinel(case)["result"]
            if actual != case["expected"]:
                failures.append((case["case_id"], case["expected"], actual))
        self.assertEqual(failures, [])

    def test_missing_source_never_becomes_recovery_supported(self) -> None:
        case = next(
            item
            for item in self.fixture["sentinel_cases"]
            if item["case_id"] == "required-source-missing"
        )
        result = MODULE.evaluate_sentinel(case)
        self.assertEqual(result["result"], "indeterminate")
        self.assertTrue(any("SOURCE_MISSING" in reason for reason in result["reasons"]))

    def test_role_scoped_briefs_share_cutoff_but_not_disallowed_claims(self) -> None:
        technical = MODULE.generate_late_arrival_brief(
            self.fixture, "technical_responder", "sequence-08"
        )
        communication = MODULE.generate_late_arrival_brief(
            self.fixture, "communication_owner", "sequence-08"
        )
        self.assertEqual(technical["evidence_cutoff"], communication["evidence_cutoff"])
        technical_ids = {claim["claim_id"] for claim in technical["claims"]}
        communication_ids = {claim["claim_id"] for claim in communication["claims"]}
        self.assertIn("claim-dependency", technical_ids)
        self.assertNotIn("claim-dependency", communication_ids)
        self.assertEqual(technical["execution_authority"], "none")
        self.assertTrue(technical["read_only"])

    def test_missing_source_is_visible_as_indeterminate_in_brief(self) -> None:
        technical = MODULE.generate_late_arrival_brief(
            self.fixture, "technical_responder", "sequence-08"
        )
        claim = next(
            item
            for item in technical["claims"]
            if item["claim_id"] == "claim-deferred-work-gap"
        )
        self.assertEqual(claim["support_state"], "indeterminate")
        self.assertEqual(
            claim["source_states"]["deferred-work-observation"]["health"], "missing"
        )

    def test_unsupported_generated_sentence_is_flagged_and_removed(self) -> None:
        brief = MODULE.generate_late_arrival_brief(
            self.fixture,
            "technical_responder",
            "sequence-08",
            injected_claims=[
                {
                    "claim_id": "unsupported-fluent-sentence",
                    "text": "Everything is fixed.",
                    "audiences": ["technical_responder"],
                    "evidence_refs": [],
                }
            ],
        )
        self.assertNotIn(
            "unsupported-fluent-sentence", {claim["claim_id"] for claim in brief["claims"]}
        )
        self.assertIn(
            {"claim_id": "unsupported-fluent-sentence", "reason": "EVIDENCE_REFERENCE_MISSING"},
            brief["flagged_claims"],
        )

    def test_delivery_detects_stale_record_and_audience_change(self) -> None:
        brief = MODULE.generate_late_arrival_brief(
            self.fixture, "technical_responder", "sequence-08"
        )
        stale = MODULE.deliver_brief(
            brief,
            delivery_audience="technical_responder",
            current_record_version="record-v2",
            current_cutoff="sequence-09",
        )
        self.assertEqual(stale["delivery_state"], "stale")
        denied = MODULE.deliver_brief(
            brief,
            delivery_audience="communication_owner",
            current_record_version="record-v1",
            current_cutoff="sequence-08",
        )
        self.assertEqual(denied["delivery_state"], "denied")

    def test_silence_does_not_publish_external_draft(self) -> None:
        negative = self.fixture["communication_records"][1]
        result = MODULE.evaluate_publication(negative)
        self.assertEqual(result, {"outcome": "hold", "reason": "EXTERNAL_APPROVAL_MISSING"})

    def test_run_output_contains_all_eight_promised_artifact_classes(self) -> None:
        result = MODULE.run_replay(self.fixture)
        expected = {
            "initial_evidence_brief",
            "role_assignments",
            "running_records",
            "late_arrival_briefs",
            "bounded_simulated_action",
            "post_fix_sentinel",
            "close_decision",
            "reopen_transition",
        }
        self.assertTrue(expected.issubset(result))
        self.assertEqual(result["human_authority"]["close"], "human_only")

    def test_generated_output_is_byte_deterministic_and_verifiable(self) -> None:
        result = MODULE.run_replay(self.fixture)
        first = json.dumps(result, indent=2, sort_keys=True) + "\n"
        second = json.dumps(MODULE.run_replay(copy.deepcopy(self.fixture)), indent=2, sort_keys=True) + "\n"
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "replay.json"
            path.write_text(first, encoding="utf-8")
            self.assertEqual(path.read_bytes(), first.encode("utf-8"))

    def test_canonicalization_is_domain_separated_and_rejects_floats(self) -> None:
        left = {"b": 2, "a": [1]}
        right = {"a": [1], "b": 2}
        self.assertEqual(MODULE.digest("ch08/a", left), MODULE.digest("ch08/a", right))
        self.assertNotEqual(MODULE.digest("ch08/a", left), MODULE.digest("ch08/b", left))
        with self.assertRaisesRegex(ValueError, "floating-point"):
            MODULE.canonical_json({"confidence": 0.5})


if __name__ == "__main__":
    unittest.main()
