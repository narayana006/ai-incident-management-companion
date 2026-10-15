from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch09_retrieval_eval.py"
SPEC = importlib.util.spec_from_file_location("ch09_retrieval_eval", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter9RetrievalEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data, self.raw = MODULE.load_input(MODULE.INPUT_PATH)
        self.result = MODULE.evaluate(self.data, MODULE.sha256_bytes(self.raw))

    def query(self, query_id: str) -> dict[str, object]:
        return next(
            row for row in self.result["per_query"] if row["query_id"] == query_id
        )

    def test_fixture_is_constructed_ten_query_audit(self) -> None:
        self.assertEqual(self.data["artifact_class"], "illustrative_constructed")
        self.assertEqual(len(self.data["queries"]), 10)
        self.assertIn("method demonstration only", self.data["source_label"])

    def test_provenance_binds_input_bundle_and_adjudication(self) -> None:
        provenance = self.result["provenance"]
        self.assertEqual(provenance["input_sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(provenance["bundle"], self.data["bundle"])
        self.assertEqual(provenance["adjudication"], self.data["adjudication"])
        self.assertEqual(provenance["generator_version"], MODULE.GENERATOR_VERSION)

    def test_denominators_separate_answerable_and_no_answer_queries(self) -> None:
        counts = self.result["denominator_counts"]
        self.assertEqual(counts["total_queries"], 10)
        self.assertEqual(counts["answerable_queries"], 7)
        self.assertEqual(counts["no_answer_queries"], 3)
        self.assertEqual(
            self.result["metrics"]["corpus_answerable_coverage"],
            {"numerator": 7, "denominator": 10, "value": 0.7},
        )

    def test_hit_recall_and_mrr_use_answerable_denominator(self) -> None:
        self.assertEqual(
            self.result["metrics"]["hit_at_3"],
            {"numerator": 5, "denominator": 7, "value": 0.714286},
        )
        # Equal to Hit@3 only because every answerable query in the published
        # fixture has exactly one adequate document. The test below separates
        # the two definitions on an input where they disagree.
        self.assertEqual(
            self.result["metrics"]["recall_at_3"],
            {"numerator": 5.0, "denominator": 7, "value": 0.714286},
        )
        self.assertEqual(
            self.result["metrics"]["mean_reciprocal_rank"],
            {"numerator": 4.5, "denominator": 7, "value": 0.642857},
        )
        report = MODULE._report_bytes(self.result).decode()
        self.assertIn("| Hit@3 (any adequate document served) | 5 / 7 = 0.714 |", report)
        self.assertIn(
            "| Recall@3 (adequate documents served / adequate documents) | 5 / 7 = 0.714 |",
            report,
        )

    def test_hit_and_recall_differ_when_one_of_two_adequate_docs_is_served(self) -> None:
        # Not in the published fixture: Chapter 9 ships ten queries. This query
        # is constructed here so the two definitions can be told apart. Two
        # adequate documents, the second displaced past k, so Hit@3 is 1.0 and
        # Recall@3 is 0.5 for the same served list.
        def candidate(rank: int, doc_id: str) -> dict[str, object]:
            return {
                "rank": rank,
                "doc_id": doc_id,
                "lifecycle": "active_verified",
                "scope_match": True,
                "access": "allowed",
                "hostile": False,
            }

        query = {
            "query_id": "constructed-two-adequate-one-served",
            "query_text": "failover leaves one shard read-only and one shard writable",
            "case_class": "answerable_polluted",
            "adequate_accessible_docs": ["doc-k-primary", "doc-k-secondary"],
            "abstained": False,
            "candidates": [
                candidate(1, "doc-k-primary"),
                candidate(2, "plausible-neighbor-k"),
                candidate(3, "second-neighbor-k"),
                candidate(4, "doc-k-secondary"),
            ],
        }
        # The constructed query satisfies the same input schema as the fixture.
        schema_check = copy.deepcopy(self.data)
        schema_check["queries"][0] = query
        MODULE.validate_input(schema_check)

        row = MODULE.evaluate_query(query, 3)
        self.assertEqual(row["adequate_document_count"], 2)
        self.assertEqual(row["adequate_documents_served"], 1)
        self.assertEqual(row["hit_at_k"], 1)
        self.assertEqual(row["recall_at_k"], 0.5)
        self.assertEqual(row["reciprocal_rank"], 1.0)
        self.assertEqual(
            [item["doc_id"] for item in row["served"]],
            ["doc-k-primary", "plausible-neighbor-k", "second-neighbor-k"],
        )
        self.assertTrue(row["polluted"])
        self.assertFalse(row["miss"])

        # Serve the displaced document and recall catches up with hit.
        complete = copy.deepcopy(query)
        complete["candidates"] = [
            candidate(1, "doc-k-primary"),
            candidate(2, "doc-k-secondary"),
            candidate(3, "plausible-neighbor-k"),
            candidate(4, "second-neighbor-k"),
        ]
        served_both = MODULE.evaluate_query(complete, 3)
        self.assertEqual(served_both["hit_at_k"], 1)
        self.assertEqual(served_both["recall_at_k"], 1.0)

    def test_not_applicable_metrics_are_blank_for_no_answer_queries(self) -> None:
        for query_id in (
            "q04-no-document",
            "q06-hostile-content-blocked",
            "q07-access-limited-no-answer",
        ):
            with self.subTest(query=query_id):
                row = self.query(query_id)
                self.assertIsNone(row["hit_at_k"])
                self.assertIsNone(row["recall_at_k"])
                self.assertIsNone(row["reciprocal_rank"])
                self.assertIsNone(row["first_adequate_rank"])
        rows = list(
            csv.DictReader(io.StringIO(MODULE._csv_bytes(self.result).decode()))
        )
        blank = next(row for row in rows if row["query_id"] == "q04-no-document")
        self.assertEqual(blank["hit_at_k"], "")
        self.assertEqual(blank["recall_at_k"], "")
        self.assertEqual(blank["reciprocal_rank"], "")
        answerable_zero = next(
            row for row in rows if row["query_id"] == "q03-eligible-miss"
        )
        self.assertEqual(answerable_zero["hit_at_k"], "0")
        self.assertEqual(answerable_zero["recall_at_k"], "0.0")

    def test_polluted_rank_two_case_preserves_rank_effect(self) -> None:
        row = self.query("q02-polluted-rank2")
        self.assertTrue(row["polluted"])
        self.assertEqual(row["first_adequate_rank"], 2)
        self.assertEqual(row["reciprocal_rank"], 0.5)

    def test_nonabstaining_miss_is_distinct_from_coverage_gap(self) -> None:
        row = self.query("q03-eligible-miss")
        self.assertTrue(row["answerable"])
        self.assertTrue(row["miss"])
        self.assertFalse(row["abstained"])
        self.assertEqual(row["hit_at_k"], 0)
        self.assertEqual(row["recall_at_k"], 0.0)

    def test_true_no_document_case_abstains(self) -> None:
        row = self.query("q04-no-document")
        self.assertFalse(row["answerable"])
        self.assertTrue(row["correct_no_answer_abstention"])
        self.assertEqual(row["served"], [])

    def test_retired_and_superseded_candidates_are_not_served(self) -> None:
        row = self.query("q05-stale-blocked-active-rank2")
        self.assertEqual(row["lifecycle_ineligible_candidates_blocked"], 2)
        self.assertEqual(
            row["blocked_candidate_counts"],
            {"lifecycle_retired": 1, "lifecycle_superseded": 1},
        )
        self.assertEqual([item["doc_id"] for item in row["served"]], ["doc-e-current"])
        self.assertEqual(row["first_adequate_rank"], 1)

    def test_instruction_like_content_is_blocked_without_tool_path(self) -> None:
        row = self.query("q06-hostile-content-blocked")
        self.assertEqual(row["hostile_candidates_blocked"], 1)
        self.assertEqual(row["served"], [])
        self.assertIn("no network or tool-execution path", MODULE._report_bytes(self.result).decode())

    def test_denied_identifier_is_withheld_from_every_generated_output(self) -> None:
        outputs = MODULE.render_outputs(self.data, self.raw)
        for name, payload in outputs.items():
            with self.subTest(name=name):
                self.assertNotIn(b"doc-denied", payload)
        row = self.query("q07-access-limited-no-answer")
        self.assertEqual(row["access_denied_candidates_blocked"], 1)
        self.assertEqual(
            row["blocked_candidates"][0]["document_reference"],
            "withheld_by_access_policy",
        )

    def test_wrong_scope_candidate_is_filtered_before_served_rank(self) -> None:
        row = self.query("q08-scope-filter-active-rank2")
        self.assertEqual(row["scope_mismatch_candidates_blocked"], 1)
        self.assertEqual(row["served"][0]["doc_id"], "doc-h-current-scope")
        self.assertEqual(row["served"][0]["served_rank"], 1)

    def test_false_abstention_counts_against_hit_and_recall(self) -> None:
        row = self.query("q09-false-abstention")
        self.assertTrue(row["false_abstention"])
        self.assertEqual(row["eligible_candidate_count"], 1)
        self.assertEqual(row["served_count"], 0)
        self.assertEqual(row["hit_at_k"], 0)
        self.assertEqual(row["recall_at_k"], 0.0)

    def test_no_ineligible_candidate_reaches_the_served_artifact(self) -> None:
        for name, encountered in (
            ("lifecycle_ineligible_served_rate", 2),
            ("scope_mismatch_served_rate", 1),
            ("access_denied_served_rate", 1),
            ("hostile_content_served_rate", 1),
        ):
            with self.subTest(metric=name):
                metric = self.result["metrics"][name]
                self.assertEqual(metric["denominator"], encountered)
                self.assertEqual(metric["numerator"], 0)
                self.assertEqual(metric["value"], 0.0)
        self.assertEqual(
            self.result["metrics"]["served_policy_violation_rate"],
            {"numerator": 0, "denominator": 7, "value": 0.0},
        )

    def test_served_violation_count_is_falsifiable(self) -> None:
        # The invariant above is a measurement, not an identity: hand a served
        # list that contains ineligible documents to the same measuring function
        # the report uses and the numerator has to move.
        candidates = next(
            item
            for item in self.data["queries"]
            if item["query_id"] == "q05-stale-blocked-active-rank2"
        )["candidates"]
        candidate_by_id = {item["doc_id"]: item for item in candidates}
        served = [
            {"served_rank": rank, "doc_id": item["doc_id"], "raw_rank": item["rank"]}
            for rank, item in enumerate(candidates, start=1)
        ]
        counts, violations = MODULE.served_violations(served, candidate_by_id)
        self.assertEqual(counts, {"lifecycle_retired": 1, "lifecycle_superseded": 1})
        self.assertEqual(violations, 2)
        eligible_only = [item for item in served if item["doc_id"] == "doc-e-current"]
        self.assertEqual(
            MODULE.served_violations(eligible_only, candidate_by_id), ({}, 0)
        )

    def test_result_carries_no_authority(self) -> None:
        self.assertEqual(self.result["authority"]["effect"], "none")
        self.assertIn("does not certify", self.result["authority"]["statement"])

    def test_unknown_fields_are_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["promotion_ready"] = True
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["queries"][0]["score"] = 0.99
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            MODULE.validate_input(data)

    def test_duplicate_query_and_candidate_ids_are_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["queries"][1]["query_id"] = data["queries"][0]["query_id"]
        with self.assertRaisesRegex(ValueError, "duplicate query_id"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["queries"][1]["candidates"][1]["doc_id"] = data["queries"][1]["candidates"][0]["doc_id"]
        with self.assertRaisesRegex(ValueError, "duplicate candidate"):
            MODULE.validate_input(data)

    def test_nonconsecutive_rank_and_invalid_lifecycle_are_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["queries"][0]["candidates"][0]["rank"] = 2
        with self.assertRaisesRegex(ValueError, "ranks must be consecutive"):
            MODULE.validate_input(data)

        data = copy.deepcopy(self.data)
        data["queries"][0]["candidates"][0]["lifecycle"] = "probably_current"
        with self.assertRaisesRegex(ValueError, "lifecycle is not recognized"):
            MODULE.validate_input(data)

    def test_ineligible_candidate_cannot_be_labeled_adequate_accessible(self) -> None:
        data = copy.deepcopy(self.data)
        query = data["queries"][6]
        query["adequate_accessible_docs"] = ["doc-denied"]
        with self.assertRaisesRegex(ValueError, "ineligible candidate"):
            MODULE.validate_input(data)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema_version":"a","schema_version":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                MODULE.load_input(duplicate)

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite JSON number"):
                MODULE.load_input(nonfinite)

    def test_outputs_are_byte_deterministic_and_verifyable(self) -> None:
        first = MODULE.render_outputs(self.data, self.raw)
        second = MODULE.render_outputs(self.data, self.raw)
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            MODULE.write_outputs(first, root)
            MODULE.verify_outputs(second, root)
            (root / MODULE.REPORT_PATH.name).write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stale output"):
                MODULE.verify_outputs(second, root)

    def test_manifest_hashes_each_generated_artifact(self) -> None:
        outputs = MODULE.render_outputs(self.data, self.raw)
        manifest = json.loads(outputs[MODULE.MANIFEST_PATH.name])
        for name, record in manifest["outputs"].items():
            with self.subTest(name=name):
                self.assertEqual(record["sha256"], hashlib.sha256(outputs[name]).hexdigest())
                self.assertEqual(record["bytes"], len(outputs[name]))


if __name__ == "__main__":
    unittest.main()
