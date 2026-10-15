from __future__ import annotations

import csv
import importlib.util
import pathlib
import unittest
import xml.etree.ElementTree as ET


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch02_constructed_ledger.py"
SPEC = importlib.util.spec_from_file_location("ch02_constructed_ledger", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
BOOK_ROOT = SCRIPT_PATH.parents[2]
CHAPTER_PATH = BOOK_ROOT / "manuscript-v4" / "chapters" / "02-the-costs-your-dashboard-misses.md"


class ConstructedLedgerTest(unittest.TestCase):
    def test_expected_shape(self) -> None:
        MODULE.verify_expected_shape()

    def test_every_row_is_marked_constructed_when_generated(self) -> None:
        MODULE.write_ledger()
        with MODULE.DATA_PATH.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 160)
        self.assertEqual({row["data_class"] for row in rows}, {MODULE.DATA_CLASS})

    def test_every_summary_row_is_marked_and_matches_printed_results(self) -> None:
        MODULE.write_summary()
        expected = {
            "baseline": {
                "incident_count": "80",
                "mean_minutes": "92.0",
                "median_minutes": "24.0",
                "p95_nearest_rank_minutes": "240",
                "within_60_count": "72",
                "within_60_fraction": "0.9",
                "longest_minutes": "2160",
                "total_incident_minutes": "7360",
                "top_three_share": "0.587",
            },
            "comparison": {
                "incident_count": "80",
                "mean_minutes": "92.6",
                "median_minutes": "15.0",
                "p95_nearest_rank_minutes": "90",
                "within_60_count": "75",
                "within_60_fraction": "0.9375",
                "longest_minutes": "5760",
                "total_incident_minutes": "7410",
                "top_three_share": "0.8138",
            },
        }
        with MODULE.SUMMARY_PATH.open(newline="", encoding="utf-8") as handle:
            rows = {row["period"]: row for row in csv.DictReader(handle)}
        self.assertEqual(set(rows), set(expected))
        for period, expected_values in expected.items():
            self.assertEqual(rows[period]["data_class"], MODULE.DATA_CLASS)
            for field, value in expected_values.items():
                self.assertEqual(rows[period][field], value, f"{period}.{field}")

    def test_all_figure_band_counts_and_provenance(self) -> None:
        MODULE.write_figure()
        root = ET.parse(MODULE.FIGURE_PATH).getroot()
        self.assertEqual(root.attrib["data-class"], MODULE.DATA_CLASS)
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        metadata = root.find("svg:metadata", namespace)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertIn(f"data_class={MODULE.DATA_CLASS}", metadata.text or "")

        plotted: dict[tuple[str, str], int] = {}
        for rectangle in root.findall("svg:rect", namespace):
            if "data-period" not in rectangle.attrib:
                continue
            self.assertEqual(rectangle.attrib["data-class"], MODULE.DATA_CLASS)
            key = (rectangle.attrib["data-period"], rectangle.attrib["data-band"])
            plotted[key] = int(rectangle.attrib["data-count"])

        bands = [
            "≤15 min",
            "16–30 min",
            "31–60 min",
            "61–120 min",
            "121–240 min",
            "241–960 min",
            ">960 min",
        ]
        expected = {
            (period, band): MODULE.band_counts(values)[band]
            for period, values in MODULE.PERIODS.items()
            for band in bands
        }
        self.assertEqual(plotted, expected)

    def test_every_numeric_result_printed_in_chapter_matches_fixture(self) -> None:
        if not CHAPTER_PATH.is_file():
            self.skipTest(f"manuscript not present: {CHAPTER_PATH}")
        text = " ".join(CHAPTER_PATH.read_text(encoding="utf-8").split())
        required_snippets = (
            "In the baseline, 72 incidents finish inside one hour. The median is 24 minutes.",
            "Four incidents run between two and four hours, and four run longer. The longest is 36 hours.",
            "In the comparison, 75 incidents finish inside one hour and the median is 15 minutes.",
            "One constructed row lasts 96 hours.",
            "| Incident count | 80 | 80 |",
            "| Mean duration | 92.0 min | 92.6 min |",
            "| Median duration | 24 min | 15 min |",
            "| p95, nearest-rank convention | 240 min | 90 min |",
            "| Resolved within 60 min | 72/80 (90.0%) | 75/80 (93.75%) |",
            "| Longest incident | 36 h | 96 h |",
            "| Share of all minutes in the three longest rows | 58.7% | 81.38% |",
            "7,360 in the baseline and 7,410 in the comparison",
            "to about 20.9 minutes over 79 rows",
            "roughly 77%",
            "the 76th ordered duration—the fifth-largest row",
            "difference is three incidents: 72 versus 75 out of 80",
        )
        for snippet in required_snippets:
            self.assertIn(" ".join(snippet.split()), text)

    def test_summary_conventions_and_sensitivity_calculation(self) -> None:
        self.assertEqual(MODULE.nearest_rank(list(range(1, 41)), 0.95), 38)
        self.assertEqual(MODULE.nearest_rank(list(range(1, 81)), 0.95), 76)
        self.assertEqual(MODULE.summarize([1, 3])["median_minutes"], 2.0)
        self.assertEqual(sum(120 < value <= 240 for value in MODULE.BASELINE_MINUTES), 4)
        self.assertEqual(sum(value > 240 for value in MODULE.BASELINE_MINUTES), 4)
        self.assertEqual(max(MODULE.BASELINE_MINUTES) / 60, 36)
        self.assertEqual(max(MODULE.COMPARISON_MINUTES) / 60, 96)
        self.assertEqual(
            MODULE.summarize(list(MODULE.COMPARISON_MINUTES))["within_60_count"]
            - MODULE.summarize(list(MODULE.BASELINE_MINUTES))["within_60_count"],
            3,
        )
        comparison_without_longest = list(MODULE.COMPARISON_MINUTES)
        comparison_without_longest.remove(max(comparison_without_longest))
        reduced_mean = MODULE.summarize(comparison_without_longest)["mean_minutes"]
        self.assertEqual(reduced_mean, 20.9)
        original_mean = MODULE.summarize(list(MODULE.COMPARISON_MINUTES))["mean_minutes"]
        reduction = (original_mean - reduced_mean) / original_mean
        self.assertAlmostEqual(reduction, 0.7743, places=4)

    def test_nearest_rank_rejects_empty_input(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.nearest_rank([], 0.95)


if __name__ == "__main__":
    unittest.main()
