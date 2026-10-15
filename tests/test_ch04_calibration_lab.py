from __future__ import annotations

import ast
import copy
import csv
import importlib.util
import json
import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch04_calibration_lab.py"
SPEC = importlib.util.spec_from_file_location("ch04_calibration_lab", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
BOOK_ROOT = SCRIPT_PATH.parents[2]
CHAPTER_PATH = BOOK_ROOT / "manuscript-v4" / "chapters" / "04-evidence-before-authority.md"
SVG = {"svg": "http://www.w3.org/2000/svg"}


class CalibrationLabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.input_hash = MODULE.verify_pinned_input()
        cls.rows = MODULE.read_rows()
        cls.summaries = MODULE.summarize(cls.rows)

    def changed_row(self, index: int = 0, **changes: str) -> list[dict[str, str]]:
        rows = copy.deepcopy(self.rows)
        rows[index].update(changes)
        return rows

    def test_authoritative_input_hash_row_count_and_label(self) -> None:
        self.assertEqual(self.input_hash, MODULE.EXPECTED_INPUT_SHA256)
        self.assertEqual(len(self.rows), 254)
        self.assertEqual({row["evidence_label"] for row in self.rows}, {MODULE.DATA_CLASS})
        self.assertEqual(
            len({(row["incident_group_id"], row["action_class"]) for row in self.rows}),
            254,
        )

    def test_repaired_bin_counts_include_ten_not_eleven_in_first_upper_bin(self) -> None:
        self.assertEqual([summary["n"] for summary in self.summaries], [40, 55, 80, 62, 10, 7])
        self.assertEqual([summary["correct_k"] for summary in self.summaries], [24, 33, 53, 53, 10, 7])
        self.assertEqual(sum(int(row["adjudicated_correct"]) for row in self.rows), 180)

    def test_wilson_interval_and_every_fixture_bin_are_uncertified(self) -> None:
        lower, upper = MODULE.wilson_interval(10, 10)
        self.assertAlmostEqual(lower, 0.722467, places=6)
        self.assertEqual(upper, 1.0)
        self.assertEqual(
            {summary["decision"] for summary in self.summaries},
            {"uncertified_interval_crosses_boundary"},
        )
        self.assertAlmostEqual(float(self.summaries[-1]["wilson_lower"]), 0.64567, places=5)

    def test_last_bin_includes_one_and_empty_bins_remain_visible(self) -> None:
        rows = copy.deepcopy(self.rows[:1])
        rows[0]["calibrated_confidence"] = "1.0"
        rows[0]["adjudicated_correct"] = "1"
        MODULE.validate_rows(rows)
        summaries = MODULE.summarize(rows)
        self.assertEqual([summary["n"] for summary in summaries], [0, 0, 0, 0, 0, 1])
        self.assertEqual(
            [summary["decision"] for summary in summaries[:5]],
            ["uncertified_empty_bin"] * 5,
        )

    def test_duplicate_independent_unit_is_rejected_not_deduplicated(self) -> None:
        rows = copy.deepcopy(self.rows[:2])
        rows[1]["incident_group_id"] = rows[0]["incident_group_id"]
        with self.assertRaisesRegex(MODULE.CalibrationInputError, "duplicate incident_group_id"):
            MODULE.validate_rows(rows)

    def test_duplicate_record_id_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows[:2])
        rows[1]["record_id"] = rows[0]["record_id"]
        with self.assertRaisesRegex(MODULE.CalibrationInputError, "duplicate record_id"):
            MODULE.validate_rows(rows)

    def test_wrong_label_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.CalibrationInputError, "evidence_label"):
            MODULE.validate_rows(self.changed_row(evidence_label="production"))

    def test_version_or_action_class_pooling_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.CalibrationInputError, "refusing to pool"):
            MODULE.validate_rows(self.changed_row(model_version="m2"))
        with self.assertRaisesRegex(MODULE.CalibrationInputError, "refusing to pool"):
            MODULE.validate_rows(self.changed_row(action_class="different_action"))

    def test_invalid_scores_and_outcomes_are_rejected(self) -> None:
        for value in ("nan", "inf", "0.49", "1.01", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(MODULE.CalibrationInputError):
                    MODULE.validate_rows(self.changed_row(calibrated_confidence=value))
        with self.assertRaisesRegex(MODULE.CalibrationInputError, "must be 0 or 1"):
            MODULE.validate_rows(self.changed_row(adjudicated_correct="indeterminate"))

    def test_input_hash_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "fixture.csv"
            path.write_bytes(MODULE.INPUT_PATH.read_bytes() + b"\n")
            with self.assertRaisesRegex(MODULE.CalibrationInputError, "hash mismatch"):
                MODULE.verify_pinned_input(path)

    def test_generated_tables_carry_label_hash_and_exact_results(self) -> None:
        MODULE.write_artifacts(MODULE.build_artifacts())
        with MODULE.SUMMARY_PATH.open(newline="", encoding="utf-8") as handle:
            summary_rows = list(csv.DictReader(handle))
        self.assertEqual(len(summary_rows), 6)
        self.assertEqual({row["data_class"] for row in summary_rows}, {MODULE.DATA_CLASS})
        self.assertEqual({row["input_sha256"] for row in summary_rows}, {self.input_hash})
        self.assertEqual([row["n"] for row in summary_rows], ["40", "55", "80", "62", "10", "7"])
        self.assertEqual(summary_rows[4]["wilson_95_lower"], "0.7225")
        self.assertEqual(summary_rows[5]["wilson_95_lower"], "0.6457")
        self.assertEqual(
            {row["decision"] for row in summary_rows},
            {"uncertified_interval_crosses_boundary"},
        )
        with MODULE.INTERVAL_PATH.open(newline="", encoding="utf-8") as handle:
            interval_rows = list(csv.DictReader(handle))
        self.assertEqual(
            {row["count_interpretation"] for row in interval_rows},
            {"shown_without_universal_minimum"},
        )

    def test_manifest_hashes_every_non_manifest_output(self) -> None:
        MODULE.write_artifacts(MODULE.build_artifacts())
        manifest = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["data_class"], MODULE.DATA_CLASS)
        self.assertEqual(manifest["input"]["rows"], 254)
        self.assertEqual(manifest["input"]["indeterminate"], 0)
        self.assertEqual(manifest["input"]["excluded"], 0)
        self.assertIsNone(manifest["contract"]["count_minimum_used_for_certification"])
        self.assertFalse(manifest["contract"]["version_pooling_allowed"])
        for relative_path, expected_hash in manifest["output_sha256"].items():
            path = MODULE.COMPANION_ROOT / relative_path
            self.assertEqual(MODULE.sha256_path(path), expected_hash, relative_path)

    def test_artifact_generation_is_byte_deterministic_and_detects_drift(self) -> None:
        first = MODULE.build_artifacts()
        second = MODULE.build_artifacts()
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "result.csv"
            output.write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "drift"):
                MODULE.verify_artifacts({output: b"expected\n"})

    def test_reliability_svg_exposes_counts_intervals_and_synthetic_scope(self) -> None:
        MODULE.write_artifacts(MODULE.build_artifacts())
        root = ET.parse(MODULE.FIGURE_PATH).getroot()
        self.assertEqual(root.attrib["data-class"], MODULE.DATA_CLASS)
        metadata = root.find("svg:metadata", SVG)
        self.assertIsNotNone(metadata)
        self.assertIn(self.input_hash, metadata.text or "")
        circles = [
            node
            for node in root.findall("svg:circle", SVG)
            if "data-decision" in node.attrib
        ]
        self.assertEqual([node.attrib["data-n"] for node in circles], ["40", "55", "80", "62", "10", "7"])
        self.assertEqual(
            {node.attrib["data-decision"] for node in circles},
            {"uncertified_interval_crosses_boundary"},
        )
        text = " ".join("".join(root.itertext()).split())
        self.assertIn("Constructed data", text)
        self.assertIn("no production model or threshold is validated", text)
        self.assertIn("upper bins: N=10 and N=7", text)

    def test_authority_svg_has_three_states_gates_and_failure_paths(self) -> None:
        MODULE.write_artifacts(MODULE.build_artifacts())
        root = ET.parse(MODULE.AUTHORITY_FIGURE_PATH).getroot()
        self.assertEqual(root.attrib["data-class"], "proposed_design")
        text = " ".join("".join(root.itertext()).split())
        for required in (
            "1 Suggest",
            "2 Propose + positive acknowledgement",
            "3 Eligible for bounded automated execution",
            "Deterministic authority-ceiling checks",
            "not confidence alone",
            "failed required check → hold execution",
            "no / silence / expiry",
            "material change also invalidates approval",
            "Execution-time recheck",
            "Any changed check → HOLD",
        ):
            self.assertIn(required, text)

    def test_lab_has_no_network_or_production_execution_import(self) -> None:
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            {"subprocess", "socket", "urllib", "http", "requests"}.isdisjoint(imported)
        )

    def test_chapter_references_generated_figures_and_scopes_lab(self) -> None:
        if not CHAPTER_PATH.is_file():
            self.skipTest(f"manuscript not present: {CHAPTER_PATH}")
        text = " ".join(CHAPTER_PATH.read_text(encoding="utf-8").split())
        self.assertIn("companion/generated/figure-4-1-calibration-reliability.svg", text)
        self.assertIn("companion/generated/figure-4-2-three-state-authority-flow.svg", text)
        self.assertIn("Every input row and generated output is labeled `illustrative_constructed`", text)
        self.assertIn("make calibration", text)
        self.assertIn("It measures no deployed model and supplies no production threshold", text)


if __name__ == "__main__":
    unittest.main()
