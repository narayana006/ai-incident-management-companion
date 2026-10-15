from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch11_readiness.py"
SPEC = importlib.util.spec_from_file_location("ch11_readiness", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter11ReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data, _ = MODULE.load_input(MODULE.INPUT_PATH)

    def row(self, gate_id: str) -> dict[str, object]:
        return next(row for row in self.data["gate_rows"] if row["gate_id"] == gate_id)

    def all_satisfied(self) -> dict[str, object]:
        data = copy.deepcopy(self.data)
        for row in data["gate_rows"]:
            row["state"] = "satisfied"
            row["not_applicable_reason"] = ""
        return data

    def write_input(self, data: dict[str, object], root: pathlib.Path) -> pathlib.Path:
        path = root / "assessment.json"
        path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return path

    def generate_in(self, data: dict[str, object], root: pathlib.Path):
        input_path = self.write_input(data, root)
        report = root / "report.md"
        decision = root / "decision.json"
        ledger = root / "ledger.csv"
        provenance = root / "provenance.json"
        result = MODULE.generate(input_path, report, decision, ledger, provenance)
        return result, report, decision, ledger, provenance

    def test_fixed_catalog_is_complete_and_ordered(self) -> None:
        self.assertEqual(len(MODULE.CONTROL_CATALOG), 10)
        self.assertEqual(
            [row["gate_id"] for row in self.data["gate_rows"]],
            [control["gate_id"] for control in MODULE.CONTROL_CATALOG],
        )

    def test_illustrative_fixture_returns_narrow(self) -> None:
        decision = MODULE.evaluate(self.data, "fixture-hash")
        self.assertEqual(decision["recommendation"], "narrow")
        self.assertEqual([item["gate_id"] for item in decision["blockers"]], ["G0-EVIDENCE"])
        self.assertEqual(decision["authority_effect"], "none")
        self.assertIn("does not dereference", decision["evidence_validation"])

    def test_all_required_rows_resolved_returns_continue_without_promotion(self) -> None:
        data = self.all_satisfied()
        MODULE.validate_input(data)
        decision = MODULE.evaluate(data, "fixture-hash")
        self.assertEqual(decision["recommendation"], "continue")
        self.assertEqual(decision["blockers"], [])
        self.assertIn("not promotion", decision["recommendation_meaning"])
        self.assertEqual(decision["authority_effect"], "none")

    def test_one_unverified_row_holds_despite_every_other_row(self) -> None:
        data = self.all_satisfied()
        data["gate_rows"][5]["state"] = "unverified"
        decision = MODULE.evaluate(data, "fixture-hash")
        self.assertEqual(decision["recommendation"], "hold")
        self.assertEqual(decision["blockers"][0]["gate_id"], "G0-EVALUATION")

    def test_expired_satisfied_row_holds(self) -> None:
        data = self.all_satisfied()
        data["gate_rows"][1]["expires_on"] = "2026-08-17"
        decision = MODULE.evaluate(data, "fixture-hash")
        self.assertEqual(decision["recommendation"], "hold")
        self.assertEqual(decision["blockers"][0]["effective_state"], "expired")

    def test_failed_authority_boundary_stops(self) -> None:
        data = self.all_satisfied()
        data["gate_rows"][3]["state"] = "unsatisfied"
        decision = MODULE.evaluate(data, "fixture-hash")
        self.assertEqual(decision["recommendation"], "stop")
        self.assertEqual(decision["blockers"][0]["gate_id"], "G0-AUTHORITY")

    def test_stop_precedes_hold_and_narrow(self) -> None:
        data = self.all_satisfied()
        data["gate_rows"][2]["state"] = "unsatisfied"
        data["gate_rows"][5]["state"] = "unverified"
        data["gate_rows"][4]["state"] = "unsatisfied"
        decision = MODULE.evaluate(data, "fixture-hash")
        self.assertEqual(decision["recommendation"], "stop")
        self.assertEqual(
            {item["disposition"] for item in decision["blockers"]},
            {"narrow", "hold", "stop"},
        )

    def test_reader_cannot_supply_or_downgrade_failure_policy(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][2]["on_unsatisfied"] = "continue"
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            MODULE.validate_input(data)

    def test_gate_may_not_be_removed_duplicated_or_reordered(self) -> None:
        missing = copy.deepcopy(self.data)
        missing["gate_rows"].pop()
        with self.assertRaisesRegex(ValueError, "exactly"):
            MODULE.validate_input(missing)

        duplicate = copy.deepcopy(self.data)
        duplicate["gate_rows"][9]["gate_id"] = "G0-PROBLEM"
        with self.assertRaisesRegex(ValueError, "duplicate gate_id"):
            MODULE.validate_input(duplicate)

        reordered = copy.deepcopy(self.data)
        reordered["gate_rows"][0], reordered["gate_rows"][1] = (
            reordered["gate_rows"][1],
            reordered["gate_rows"][0],
        )
        with self.assertRaisesRegex(ValueError, "fixed catalog order"):
            MODULE.validate_input(reordered)

    def test_owner_reviewer_and_evidence_are_mandatory(self) -> None:
        for field in ("owner", "reviewer", "evidence_ref"):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data["gate_rows"][0][field] = ""
                with self.assertRaisesRegex(ValueError, "must not be empty"):
                    MODULE.validate_input(data)

    def test_owner_and_reviewer_roles_must_be_distinct(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["reviewer"] = data["gate_rows"][0]["owner"]
        with self.assertRaisesRegex(ValueError, "distinct roles"):
            MODULE.validate_input(data)

    def test_decision_owner_and_reviewer_must_be_distinct(self) -> None:
        data = copy.deepcopy(self.data)
        data["decision_reviewer"] = data["decision_owner"]
        with self.assertRaisesRegex(ValueError, "distinct roles"):
            MODULE.validate_input(data)

    def test_not_applicable_requires_reason_and_review(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][6]["not_applicable_reason"] = ""
        with self.assertRaisesRegex(ValueError, "requires a reason"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["gate_rows"][6]["reviewer"] = ""
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            MODULE.validate_input(data)

    def test_not_applicable_cannot_bypass_a_fixed_gate(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["state"] = "not_applicable"
        data["gate_rows"][0]["not_applicable_reason"] = "Attempted bypass."
        with self.assertRaisesRegex(ValueError, "cannot be marked"):
            MODULE.validate_input(data)

    def test_consequence_na_is_limited_to_early_read_only_work(self) -> None:
        MODULE.validate_input(copy.deepcopy(self.data))

        data = copy.deepcopy(self.data)
        data["current_gate"] = "shadow_evaluation"
        with self.assertRaisesRegex(ValueError, "before shadow"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["scope"]["permitted_assistance"] = "Recommendation only."
        with self.assertRaisesRegex(ValueError, "read-only"):
            MODULE.validate_input(data)

    def test_na_reason_is_rejected_on_other_states(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["not_applicable_reason"] = "Not actually N/A."
        with self.assertRaisesRegex(ValueError, "must be empty"):
            MODULE.validate_input(data)

    def test_invalid_state_and_expiry_are_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["state"] = "mostly_ready"
        with self.assertRaisesRegex(ValueError, "state must be"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["expires_on"] = "next quarter"
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            MODULE.validate_input(data)

    def test_unknown_top_level_and_row_fields_are_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["maturity"] = "high"
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["weight"] = 10
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            MODULE.validate_input(data)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":"a","schema_version":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                MODULE.load_input(path)

    def test_spreadsheet_formula_prefix_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["next_action"] = "=HYPERLINK(\"unsafe\")"
        with self.assertRaisesRegex(ValueError, "spreadsheet-formula"):
            MODULE.validate_input(data)

    def test_surrounding_whitespace_is_rejected_instead_of_hidden(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][0]["owner"] = " pilot_service_owner"
        with self.assertRaisesRegex(ValueError, "surrounding whitespace"):
            MODULE.validate_input(data)

    def test_reader_text_is_escaped_in_markdown_report(self) -> None:
        data = copy.deepcopy(self.data)
        data["gate_rows"][2]["evidence_ref"] = "evidence://illustrative/`gap`<script>"
        MODULE.validate_input(data)
        decision = MODULE.evaluate(data, "fixture-hash")
        report = MODULE.render_report(decision)
        self.assertNotIn("<script>", report)
        self.assertNotIn("`gap`", report)
        self.assertIn("&#96;gap&#96;&lt;script&gt;", report)

    def test_report_and_decision_contain_no_aggregate_readiness_metric(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            _, report, decision, _, _ = self.generate_in(self.data, root)
            report_text = report.read_text(encoding="utf-8").lower()
            decision_text = decision.read_text(encoding="utf-8").lower()
            for forbidden in ("maturity score", "readiness percentage", "autonomy tier"):
                self.assertNotIn(forbidden, report_text)
                self.assertNotIn(forbidden, decision_text)
            self.assertNotIn("%", report_text)
            parsed = json.loads(decision_text)
            self.assertNotIn("score", parsed)
            self.assertNotIn("tier", parsed)

    def test_starter_plan_has_three_planning_only_windows(self) -> None:
        decision = MODULE.evaluate(self.data, "fixture-hash")
        self.assertEqual(
            [item["window"] for item in decision["starter_plan"]],
            ["days_1_30", "days_31_60", "days_61_90"],
        )
        self.assertTrue(all(item["planning_only"] for item in decision["starter_plan"]))
        self.assertTrue(
            all(item["calendar_effect_on_authority"] == "none" for item in decision["starter_plan"])
        )

    def test_generated_gate_ledger_preserves_every_required_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            _, _, _, ledger, _ = self.generate_in(self.data, root)
            with ledger.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), len(MODULE.CONTROL_CATALOG))
            self.assertTrue(all(row["required"] == "true" for row in rows))
            evidence = next(row for row in rows if row["gate_id"] == "G0-EVIDENCE")
            self.assertEqual(evidence["blocking_disposition"], "narrow")

    def test_provenance_hashes_match_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            _, report, decision, ledger, provenance = self.generate_in(self.data, root)
            record = json.loads(provenance.read_text(encoding="utf-8"))
            for key, path in {
                "report": report,
                "decision": decision,
                "gate_ledger": ledger,
            }.items():
                payload = path.read_bytes()
                self.assertEqual(record["outputs"][key]["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(record["outputs"][key]["bytes"], len(payload))
            self.assertEqual(record["authority_effect"], "none")
            self.assertEqual(record["evidence_validation"], "references_and_metadata_only")

    def test_generation_is_deterministic_across_external_directories(self) -> None:
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            left = pathlib.Path(left_dir)
            right = pathlib.Path(right_dir)
            left_files = self.generate_in(self.data, left)[1:]
            right_files = self.generate_in(self.data, right)[1:]
            for left_path, right_path in zip(left_files, right_files):
                self.assertEqual(left_path.read_bytes(), right_path.read_bytes())

    def test_cli_supports_external_input_and_relative_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            input_path = self.write_input(self.data, root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(input_path),
                    "--report",
                    "report.md",
                    "--decision",
                    "decision.json",
                    "--gate-ledger",
                    "ledger.csv",
                    "--provenance",
                    "provenance.json",
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("report.md", "decision.json", "ledger.csv", "provenance.json"):
                self.assertTrue((root / name).is_file())
                self.assertIn(str(root / name), result.stdout)
            self.assertIn("recommendation: narrow", result.stdout)


if __name__ == "__main__":
    unittest.main()
