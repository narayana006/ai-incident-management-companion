from __future__ import annotations

import copy
import csv
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch06_k8s_mechanism.py"
SPEC = importlib.util.spec_from_file_location("ch06_k8s_mechanism", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter6K8SMechanismTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pins = MODULE.read_json(MODULE.PINS_PATH)

    def test_all_pinned_source_hashes_match(self) -> None:
        validated = MODULE.validate_pins(MODULE.SOURCE_ROOT, self.pins)
        self.assertEqual(len(validated), 9)
        self.assertTrue(all(item["validation"] == "match" for item in validated))

    def test_tampered_source_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = pathlib.Path(directory) / "K8S-01"
            shutil.copytree(MODULE.SOURCE_ROOT, copied)
            with (copied / "trials.csv").open("a", encoding="utf-8") as handle:
                handle.write("tamper\n")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                MODULE.validate_pins(copied, self.pins)

    def test_completed_rows_are_exactly_one_sequential_run_each(self) -> None:
        rows = MODULE.read_trials(MODULE.SOURCE_ROOT)
        self.assertEqual([(r["run_id"], r["treatment"]) for r in rows], [
            ("S01A", "direct_write"),
            ("S01B", "setpoint_override"),
        ])

    def test_ttl_treatment_is_explicitly_not_run(self) -> None:
        rows = MODULE.read_trials(MODULE.SOURCE_ROOT)
        observations = MODULE.validate_observations(MODULE.SOURCE_ROOT, rows)
        ttl = observations[-1]
        self.assertEqual(ttl["status"], "not_run")
        self.assertEqual(ttl["completed_runs_n"], 0)

    def test_s01a_supports_only_direct_write_overwrite_mechanism(self) -> None:
        observations = MODULE.validate_observations(
            MODULE.SOURCE_ROOT, MODULE.read_trials(MODULE.SOURCE_ROOT)
        )
        direct = observations[0]
        self.assertEqual(direct["owned_target_field_intervention_value"], 24)
        self.assertEqual(direct["owned_target_field_later_value"], 15)
        self.assertEqual(direct["controller_decision_value_observed"], 15)
        self.assertEqual(direct["completed_runs_n"], 1)

    def test_s01b_supports_only_controller_input_and_governed_state_change(self) -> None:
        observations = MODULE.validate_observations(
            MODULE.SOURCE_ROOT, MODULE.read_trials(MODULE.SOURCE_ROOT)
        )
        setpoint = observations[1]
        self.assertEqual(setpoint["controller_input_value_before"], 15)
        self.assertEqual(setpoint["controller_input_value_after"], 30)
        self.assertEqual(setpoint["controller_decision_value_observed"], 30)
        self.assertEqual(setpoint["owned_target_field_value_observed"], 30)
        self.assertEqual(setpoint["completed_runs_n"], 1)

    def test_endpoint_labels_are_exact_and_distinct(self) -> None:
        endpoints = self.pins["endpoint_definitions"]
        self.assertEqual(
            endpoints,
            {
                "controller_input": "HorizontalPodAutoscaler/cpu-svc.spec.maxReplicas",
                "controller_decision": "HorizontalPodAutoscaler/cpu-svc.status.desiredReplicas",
                "owned_target_field": "Deployment/cpu-svc.spec.replicas",
                "observed_workload_state": "Deployment/cpu-svc.status.readyReplicas",
            },
        )
        self.assertEqual(len(set(endpoints.values())), 4)

    def test_default_generation_does_not_modify_source_records(self) -> None:
        before = {
            item["path"]: MODULE.sha256_file(MODULE.SOURCE_ROOT / item["path"])
            for item in self.pins["files"]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            MODULE.generate(
                MODULE.SOURCE_ROOT,
                MODULE.PINS_PATH,
                root / "manifest.json",
                root / "table.csv",
                root / "report.md",
                root / "figure.svg",
            )
        after = {
            item["path"]: MODULE.sha256_file(MODULE.SOURCE_ROOT / item["path"])
            for item in self.pins["files"]
        }
        self.assertEqual(before, after)

    def test_generated_manifest_excludes_legacy_timing_from_inference(self) -> None:
        manifest = MODULE.read_json(MODULE.OUTPUT_MANIFEST)
        self.assertEqual(manifest["default_mode"], "read_only_committed_evidence")
        self.assertIn("time_to_revert_or_converge_s", manifest["legacy_fields_not_used_for_inference"])
        self.assertIn("oscillation_count", manifest["legacy_fields_not_used_for_inference"])
        self.assertEqual(manifest["execution_design"], "S01A then S01B sequentially; not randomized; not replicated")

    def test_generated_table_includes_not_run_row(self) -> None:
        with MODULE.OUTPUT_TABLE.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["treatment"], "ttl_override")
        self.assertEqual(rows[-1]["status"], "not_run")
        self.assertEqual(rows[-1]["completed_runs_n"], "0")

    def test_figure_is_accessible_and_scoped(self) -> None:
        figure = MODULE.OUTPUT_FIGURE.read_text(encoding="utf-8")
        self.assertIn('role="img"', figure)
        self.assertIn('aria-labelledby="title desc"', figure)
        self.assertIn("n = 1 sequential run per completed treatment", figure)
        self.assertIn("TTL OVERRIDE  •  NOT RUN  •  n = 0", figure)
        self.assertNotIn("faster", figure.lower())
        self.assertNotIn("safer", figure.lower())

    def test_generated_artifacts_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            outputs = [
                root / "manifest.json",
                root / "table.csv",
                root / "report.md",
                root / "figure.svg",
            ]
            MODULE.generate(MODULE.SOURCE_ROOT, MODULE.PINS_PATH, *outputs)
            committed = [
                MODULE.OUTPUT_MANIFEST,
                MODULE.OUTPUT_TABLE,
                MODULE.OUTPUT_REPORT,
                MODULE.OUTPUT_FIGURE,
            ]
            for actual, expected in zip(outputs, committed):
                self.assertEqual(actual.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
