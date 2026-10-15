from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch10_human_boundary.py"
SPEC = importlib.util.spec_from_file_location("ch10_human_boundary", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter10HumanBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture, self.raw = MODULE.load_fixture()

    def case(self, case_id: str) -> dict:
        return copy.deepcopy(
            next(case for case in self.fixture["cases"] if case["case_id"] == case_id)
        )

    def test_every_constructed_case_matches_expected_result(self) -> None:
        result = MODULE.evaluate(self.fixture, self.raw)
        self.assertEqual(result["summary"]["case_count"], 7)
        self.assertEqual(result["expected_mismatches"], [])
        self.assertEqual(result["summary"]["expected_match_count"], 7)

    def test_expected_answer_is_not_used_to_classify(self) -> None:
        case = self.case("bounded-validated-restart")
        case["expected"] = "human_owned_unattended_blocked"
        self.assertEqual(
            MODULE.classify(case)["result"], "eligible_for_policy_evaluation"
        )

    def test_eligibility_is_not_authorization(self) -> None:
        decision = MODULE.classify(self.case("bounded-validated-restart"))
        self.assertTrue(decision["unattended_path_allowed"])
        self.assertIn("not action authorization", decision["policy_note"])

    def test_commitment_is_human_owned_and_unattended_is_blocked(self) -> None:
        decision = MODULE.classify(self.case("external-recovery-commitment"))
        self.assertEqual(decision["result"], "human_owned")
        self.assertTrue(decision["human_owned"])
        self.assertFalse(decision["unattended_path_allowed"])
        self.assertIn("COMMITMENT_REQUIRES_HUMAN", decision["human_boundary_reasons"])

    def test_people_decision_is_human_owned_and_unsafe_path_is_vetoed(self) -> None:
        decision = MODULE.classify(self.case("staffing-from-operational-traces"))
        self.assertEqual(decision["result"], "human_owned_unattended_blocked")
        self.assertIn("PEOPLE_DECISION_REQUIRES_HUMAN", decision["human_boundary_reasons"])
        self.assertIn("ACTION_CLASS_NOT_VALIDATED", decision["veto_reasons"])

    def test_novel_case_and_missing_owner_cannot_take_unattended_path(self) -> None:
        case = self.case("bounded-validated-restart")
        case["novel_or_outside_policy"] = True
        case["accountable_owner"] = False
        decision = MODULE.classify(case)
        self.assertEqual(decision["result"], "human_owned_unattended_blocked")
        self.assertFalse(decision["unattended_path_allowed"])
        self.assertIn("NOVEL_OR_OUTSIDE_POLICY", decision["veto_reasons"])
        self.assertIn("ACCOUNTABLE_OWNER_MISSING", decision["veto_reasons"])

    def test_each_incomplete_safety_gate_vetoes_unattended_path(self) -> None:
        fields = (
            "class_validated",
            "population_validated",
            "bounds_complete",
            "inverse_current_and_exercised",
            "evidence_current_authorized_scoped",
            "accountable_owner",
        )
        for field in fields:
            with self.subTest(field=field):
                case = self.case("bounded-validated-restart")
                case[field] = False
                decision = MODULE.classify(case)
                self.assertEqual(decision["result"], "human_owned_unattended_blocked")
                self.assertFalse(decision["unattended_path_allowed"])

    def test_schema_rejects_unknown_fields_integer_booleans_and_duplicate_ids(self) -> None:
        invalid = copy.deepcopy(self.fixture)
        invalid["surprise"] = "ignored-by-lenient-parser"
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            MODULE.validate_fixture(invalid)

        invalid = copy.deepcopy(self.fixture)
        invalid["cases"][0]["commitment"] = 1
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            MODULE.validate_fixture(invalid)

        invalid = copy.deepcopy(self.fixture)
        invalid["cases"][1]["case_id"] = invalid["cases"][0]["case_id"]
        with self.assertRaisesRegex(ValueError, "duplicate case_id"):
            MODULE.validate_fixture(invalid)

    def test_loader_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                MODULE.load_fixture(path)

    def test_output_is_deterministic_and_contains_provenance(self) -> None:
        first = MODULE.evaluate(self.fixture, self.raw)
        second = MODULE.evaluate(copy.deepcopy(self.fixture), self.raw)
        self.assertEqual(first, second)
        self.assertEqual(len(first["run_digest"]), 64)
        self.assertEqual(len(first["provenance"]["source_sha256"]), 64)
        self.assertEqual(len(first["provenance"]["fixture_digest"]), 64)

    def test_json_and_markdown_outputs_are_reproducible(self) -> None:
        result = MODULE.evaluate(self.fixture, self.raw)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            json_path = root / "result.json"
            report_path = root / "report.md"
            MODULE.write_outputs(result, json_path, report_path)
            first_json = json_path.read_bytes()
            first_report = report_path.read_bytes()
            MODULE.write_outputs(result, json_path, report_path)
            self.assertEqual(json_path.read_bytes(), first_json)
            self.assertEqual(report_path.read_bytes(), first_report)
            parsed = json.loads(first_json)
            self.assertEqual(parsed["run_digest"], result["run_digest"])
            self.assertIn(b"grants no production authority", first_report)


if __name__ == "__main__":
    unittest.main()
