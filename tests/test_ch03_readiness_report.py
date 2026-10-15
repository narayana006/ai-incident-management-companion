from __future__ import annotations

import csv
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch03_readiness_report.py"
SPEC = importlib.util.spec_from_file_location("ch03_readiness_report", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LayerReadinessReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = MODULE.read_worksheet(MODULE.TEMPLATE_PATH)

    def write_rows(self, rows: list[dict[str, str]], directory: pathlib.Path) -> pathlib.Path:
        path = directory / "worksheet.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MODULE.REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_template_contains_every_layer_exactly_once(self) -> None:
        self.assertEqual(len(self.rows), 14)
        self.assertEqual(
            [row["layer_id"] for row in self.rows],
            [layer_id for layer_id, _, _ in MODULE.EXPECTED_LAYERS],
        )

    def test_invalid_applicability_status_is_rejected(self) -> None:
        self.rows[0]["claim_applicability"] = "ready"
        with self.assertRaisesRegex(ValueError, "claim_applicability"):
            MODULE.validate_rows(self.rows)

    def test_invalid_boolean_value_is_rejected(self) -> None:
        self.rows[0]["bounded_read_interface"] = "maybe"
        with self.assertRaisesRegex(ValueError, "bounded_read_interface"):
            MODULE.validate_rows(self.rows)

    def test_invalid_source_state_class_is_rejected(self) -> None:
        self.rows[0]["source_state_class"] = "governed_record"
        with self.assertRaisesRegex(ValueError, "source_state_class"):
            MODULE.validate_rows(self.rows)

    def test_duplicate_layer_is_rejected(self) -> None:
        self.rows[-1]["layer_id"] = "L13"
        with self.assertRaisesRegex(ValueError, "duplicate layer_id"):
            MODULE.validate_rows(self.rows)

    def test_missing_layer_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing layers"):
            MODULE.validate_rows(self.rows[:-1])

    def test_true_field_without_evidence_is_reported(self) -> None:
        self.rows[0]["stable_subject_identity"] = "true"
        gaps = MODULE.collect_gaps(self.rows)
        matching = [
            gap
            for gap in gaps
            if gap["layer_id"] == "L1"
            and gap["gap_field"] == "stable_subject_identity_evidence"
        ]
        self.assertEqual(len(matching), 1)

    def test_source_state_and_access_controls_are_reported(self) -> None:
        gaps = MODULE.collect_gaps(self.rows)
        l1_fields = {
            gap["gap_field"] for gap in gaps if gap["layer_id"] == "L1"
        }
        self.assertIn("source_state_class", l1_fields)
        self.assertIn("declared_read_purpose", l1_fields)
        self.assertIn("intended_audience", l1_fields)
        self.assertIn("authorized_read_test", l1_fields)
        self.assertIn("denied_access_test", l1_fields)
        self.assertIn("coverage_and_source_health", l1_fields)
        self.assertIn("source_update_time_semantics", l1_fields)
        self.assertIn("retrieval_time_semantics", l1_fields)
        self.assertIn("transformation_lineage", l1_fields)

    def test_assessed_source_state_requires_evidence(self) -> None:
        self.rows[0]["source_state_class"] = "recorded_intent"
        gaps = MODULE.collect_gaps(self.rows)
        matching = [
            gap
            for gap in gaps
            if gap["layer_id"] == "L1"
            and gap["gap_field"] == "source_state_class_evidence"
        ]
        self.assertEqual(len(matching), 1)

    def test_generated_output_contains_no_aggregate_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = pathlib.Path(temp_dir)
            worksheet = self.write_rows(self.rows, temp)
            report = temp / "report.md"
            gaps = temp / "gaps.csv"
            MODULE.generate(worksheet, report, gaps)
            contents = report.read_text(encoding="utf-8").lower()
            self.assertNotIn("score", contents)
            self.assertNotIn("percent", contents)
            self.assertNotIn("threshold", contents)
            self.assertNotIn("promotion", contents)
            self.assertIn("gaps by layer", contents)
            self.assertIn("gaps by field", contents)

    def test_cli_accepts_relative_output_paths_outside_companion_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = pathlib.Path(temp_dir)
            worksheet = self.write_rows(self.rows, temp)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(worksheet),
                    "--report",
                    "report.md",
                    "--gaps",
                    "gaps.csv",
                ],
                cwd=temp,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((temp / "report.md").is_file())
            self.assertTrue((temp / "gaps.csv").is_file())
            self.assertIn(str(temp / "report.md"), result.stdout)
            self.assertIn(str(temp / "gaps.csv"), result.stdout)


if __name__ == "__main__":
    unittest.main()
