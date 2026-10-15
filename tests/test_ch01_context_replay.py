from __future__ import annotations

import copy
import importlib.util
import pathlib
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch01_context_replay.py"
SPEC = importlib.util.spec_from_file_location("ch01_context_replay", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def evidence(fixture: dict, evidence_id: str) -> dict:
    return next(item for item in fixture["evidence"] if item["evidence_id"] == evidence_id)


class ContextReplayTest(unittest.TestCase):
    def test_complete_fixture_produces_verification_candidate(self) -> None:
        brief = MODULE.assemble_brief(MODULE.load_fixture())
        claim = brief["derived_claim"]
        self.assertEqual(
            claim["content"]["outcome"],
            "candidate_for_responder_verification",
        )
        self.assertEqual(
            claim["parent_evidence_ids"],
            ["E-01", "E-02", "E-03", "E-04", "E-05"],
        )
        self.assertEqual(brief["source_gaps"], [])
        self.assertEqual(brief["validation_failures"], [])
        self.assertEqual(brief["system_authority"]["production_write_credential"], "none")
        self.assertEqual(brief["system_authority"]["model_credentials"], "none")

    def test_only_three_source_state_classes_are_used(self) -> None:
        fixture = MODULE.load_fixture()
        classes = {item["source_state_class"] for item in fixture["evidence"]}
        brief = MODULE.assemble_brief(fixture)
        classes.add(brief["derived_claim"]["source_state_class"])
        self.assertEqual(
            classes,
            {"recorded_intent", "live_state_observation", "derived_claim"},
        )
        self.assertEqual(evidence(fixture, "E-05")["source_state_class"], "recorded_intent")

    def test_freshness_is_named_versioned_and_computed(self) -> None:
        fixture = MODULE.load_fixture()
        brief = MODULE.assemble_brief(fixture)
        route_status = brief["required_source_status"]["E-03"]
        self.assertEqual(
            route_status["freshness"]["policy_id"],
            "ch01-replay-freshness",
        )
        self.assertEqual(route_status["freshness"]["policy_version"], "1.0.0")
        self.assertEqual(route_status["freshness"]["age_seconds"], 23)
        self.assertEqual(route_status["computed_freshness"], "within_policy")

    def test_denied_route_source_without_content_holds_without_dereference(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        route = evidence(fixture, "E-03")
        route["retrieval_status"] = "failed"
        route["authorization_result"] = "denied"
        route["source_health"]["status"] = "unavailable"
        route.pop("content")
        MODULE.seal_evidence_item(route)

        brief = MODULE.assemble_brief(fixture)
        self.assertEqual(brief["derived_claim"]["content"]["outcome"], "incomplete_hold")
        self.assertEqual(brief["source_gaps"], ["E-03"])
        self.assertIn(
            "did not inspect source content",
            brief["derived_claim"]["content"]["wording"],
        )

    def test_missing_required_source_is_fail_visible(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        fixture["evidence"] = [
            item for item in fixture["evidence"] if item["evidence_id"] != "E-03"
        ]
        brief = MODULE.assemble_brief(fixture)
        self.assertEqual(brief["source_gaps"], ["E-03"])
        self.assertFalse(brief["required_source_status"]["E-03"]["present"])
        self.assertEqual(
            brief["derived_claim"]["content"]["outcome"],
            "incomplete_hold",
        )
        self.assertNotIn("E-03", brief["derived_claim"]["parent_evidence_ids"])

    def test_subject_mismatch_fails_closed(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        route = evidence(fixture, "E-03")
        route["subject"] = "route-object-b"
        MODULE.seal_evidence_item(route)

        brief = MODULE.assemble_brief(fixture)
        self.assertEqual(brief["derived_claim"]["content"]["outcome"], "incomplete_hold")
        self.assertIn("E-03:subject_mismatch", brief["validation_failures"])

    def test_future_evidence_is_rejected_at_replay_cutoff(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        route = evidence(fixture, "E-03")
        route["retrieval_time"] = "2026-01-01T00:05:01Z"
        MODULE.seal_evidence_item(route)
        with self.assertRaisesRegex(ValueError, "after replay_cutoff"):
            MODULE.assemble_brief(fixture)

    def test_stale_evidence_holds_the_claim(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        route = evidence(fixture, "E-03")
        route["valid_time"] = "2026-01-01T00:00:00Z"
        route["source_update_time"] = "2026-01-01T00:00:00Z"
        MODULE.seal_evidence_item(route)

        brief = MODULE.assemble_brief(fixture)
        self.assertEqual(brief["source_gaps"], ["E-03"])
        self.assertEqual(
            brief["required_source_status"]["E-03"]["computed_freshness"],
            "stale",
        )
        self.assertEqual(brief["derived_claim"]["content"]["outcome"], "incomplete_hold")

    def test_unscoped_zero_counter_cannot_support_claim(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        counter = evidence(fixture, "E-04")
        counter["coverage"].pop("filter")
        MODULE.seal_evidence_item(counter)

        brief = MODULE.assemble_brief(fixture)
        self.assertEqual(brief["derived_claim"]["content"]["outcome"], "incomplete_hold")
        self.assertIn("E-04:coverage_filter_mismatch", brief["validation_failures"])

    def test_mutable_reference_is_rejected(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        evidence(fixture, "E-01")["immutable_ref"] = "edge-metrics:latest"
        with self.assertRaisesRegex(ValueError, "immutable_ref"):
            MODULE.assemble_brief(fixture)

    def test_tampering_is_detected(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        evidence(fixture, "E-03")["content"]["configured_path"].append(
            "protection-control-a"
        )
        with self.assertRaisesRegex(ValueError, "integrity verification"):
            MODULE.assemble_brief(fixture)

    def test_arbitrary_source_state_enum_is_rejected(self) -> None:
        fixture = copy.deepcopy(MODULE.load_fixture())
        change = evidence(fixture, "E-05")
        change["source_state_class"] = "recorded_history"
        MODULE.seal_evidence_item(change)
        with self.assertRaisesRegex(ValueError, "source_state_class"):
            MODULE.assemble_brief(fixture)

    def test_derived_e06_has_full_envelope_and_verified_seal(self) -> None:
        claim = MODULE.assemble_brief(MODULE.load_fixture())["derived_claim"]
        self.assertEqual(MODULE.REQUIRED_FIELDS.difference(claim), set())
        self.assertIn("freshness", claim)
        self.assertIn("transformation_versions", claim)
        self.assertEqual(claim["source_state_class"], "derived_claim")
        self.assertTrue(claim["immutable_ref"].startswith("sha256:"))
        MODULE._verify_integrity(claim)

    def test_markdown_exposes_verified_references_and_envelope(self) -> None:
        brief = MODULE.assemble_brief(MODULE.load_fixture())
        markdown = MODULE.render_markdown(brief)
        self.assertIn("## Inspectable evidence references", markdown)
        self.assertIn(brief["required_source_status"]["E-01"]["immutable_ref"], markdown)
        self.assertIn(brief["derived_claim"]["immutable_ref"], markdown)
        self.assertIn("### Exact source coverage and query parameters", markdown)
        self.assertIn('"traffic_class=affected"', markdown)
        self.assertIn("### Derived-envelope query", markdown)
        self.assertIn("### Transformation versions", markdown)


if __name__ == "__main__":
    unittest.main()
