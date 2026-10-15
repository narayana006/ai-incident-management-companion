#!/usr/bin/env python3
"""Run the deterministic Chapter 9 constructed retrieval audit.

The fixture contains no production data, model call, network path, or tool
authority.  It starts with a frozen ranked candidate list, applies lifecycle,
scope, access, and hostile-content eligibility rules, then measures the exact
artifact that would be shown after an abstention decision.  The outputs
demonstrate an evaluation method; they do not certify a retriever or authorize
promotion.

Two metrics are reported separately because they answer different questions:
Hit@K is 1 when any adequate document reached the responder, and Recall@K is
|served adequate| / |adequate| for that query.  They are equal only when every
answerable query has exactly one adequate document, which happens to be true of
this ten-query fixture; the unit tests score a two-adequate-document query to
show the two metrics coming apart.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any


COMPANION_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = COMPANION_ROOT / "fixtures" / "ch09" / "retrieval-evaluation.json"
OUTPUT_ROOT = COMPANION_ROOT / "generated" / "ch09"
RESULTS_PATH = OUTPUT_ROOT / "retrieval_evaluation_results.json"
ROWS_PATH = OUTPUT_ROOT / "per_query_results.csv"
REPORT_PATH = OUTPUT_ROOT / "retrieval_evaluation_report.md"
MANIFEST_PATH = OUTPUT_ROOT / "retrieval_evaluation_run_manifest.json"

SCHEMA_VERSION = "ch09-retrieval-evaluation-1"
GENERATOR_VERSION = "ch09-retrieval-evaluator-1.0.0"
MAX_INPUT_BYTES = 1_000_000
EXPECTED_QUERY_COUNT = 10
ALLOWED_ARTIFACT_CLASSES = {"illustrative_constructed"}
ALLOWED_CASE_CLASSES = {
    "answerable",
    "answerable_polluted",
    "miss",
    "no_answer",
    "stale_index",
    "hostile_content",
    "access_limited",
    "scope_mismatch",
    "false_abstention",
}
ALLOWED_LIFECYCLES = {
    "active_verified",
    "retired",
    "superseded",
    "quarantined",
}
ALLOWED_ACCESS = {"allowed", "denied"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,95}$")

TOP_LEVEL_FIELDS = {
    "schema_version",
    "artifact_class",
    "source_label",
    "evaluation_id",
    "adjudication",
    "bundle",
    "queries",
}
ADJUDICATION_FIELDS = {
    "review_role",
    "rubric_version",
    "reviewed_on",
    "disagreement_state",
}
BUNDLE_FIELDS = {
    "corpus_snapshot",
    "index_version",
    "chunking_version",
    "ranker_version",
    "audience",
    "k",
}
QUERY_FIELDS = {
    "query_id",
    "query_text",
    "case_class",
    "adequate_accessible_docs",
    "abstained",
    "candidates",
}
CANDIDATE_FIELDS = {
    "rank",
    "doc_id",
    "lifecycle",
    "scope_match",
    "access",
    "hostile",
}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected.difference(value))
    extra = sorted(set(value).difference(expected))
    if missing or extra:
        raise ValueError(f"{label} fields do not match; missing={missing}, extra={extra}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty string without surrounding whitespace")
    if "\x00" in value:
        raise ValueError(f"{label} contains a NUL byte")
    return value


def _identifier(value: Any, label: str) -> str:
    item = _text(value, label)
    if not ID_RE.fullmatch(item):
        raise ValueError(f"{label} must match {ID_RE.pattern}")
    return item


def _date(value: Any, label: str) -> str:
    item = _text(value, label)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item):
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return item


def load_input(path: Path = INPUT_PATH) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise ValueError("input must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("input root must be an object")
    validate_input(value)
    return value, raw


def validate_input(data: dict[str, Any]) -> None:
    _exact_fields(data, TOP_LEVEL_FIELDS, "input")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
    if data["artifact_class"] not in ALLOWED_ARTIFACT_CLASSES:
        raise ValueError("artifact_class must be illustrative_constructed")
    _text(data["source_label"], "source_label")
    _identifier(data["evaluation_id"], "evaluation_id")

    adjudication = data["adjudication"]
    if not isinstance(adjudication, dict):
        raise ValueError("adjudication must be an object")
    _exact_fields(adjudication, ADJUDICATION_FIELDS, "adjudication")
    _identifier(adjudication["review_role"], "adjudication.review_role")
    _identifier(adjudication["rubric_version"], "adjudication.rubric_version")
    _date(adjudication["reviewed_on"], "adjudication.reviewed_on")
    _identifier(
        adjudication["disagreement_state"], "adjudication.disagreement_state"
    )

    bundle = data["bundle"]
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be an object")
    _exact_fields(bundle, BUNDLE_FIELDS, "bundle")
    for field in BUNDLE_FIELDS.difference({"k"}):
        _identifier(bundle[field], f"bundle.{field}")
    k = bundle["k"]
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
        raise ValueError("bundle.k must be an integer from 1 through 20")

    queries = data["queries"]
    if not isinstance(queries, list) or len(queries) != EXPECTED_QUERY_COUNT:
        raise ValueError(f"queries must contain exactly {EXPECTED_QUERY_COUNT} cases")
    query_ids: set[str] = set()
    observed_classes: set[str] = set()
    for query_number, query in enumerate(queries, start=1):
        label = f"queries[{query_number - 1}]"
        if not isinstance(query, dict):
            raise ValueError(f"{label} must be an object")
        _exact_fields(query, QUERY_FIELDS, label)
        query_id = _identifier(query["query_id"], f"{label}.query_id")
        if query_id in query_ids:
            raise ValueError(f"duplicate query_id {query_id!r}")
        query_ids.add(query_id)
        _text(query["query_text"], f"{query_id}.query_text")
        case_class = query["case_class"]
        if case_class not in ALLOWED_CASE_CLASSES:
            raise ValueError(f"{query_id}.case_class is not recognized")
        observed_classes.add(case_class)
        if not isinstance(query["abstained"], bool):
            raise ValueError(f"{query_id}.abstained must be boolean")

        adequate = query["adequate_accessible_docs"]
        if not isinstance(adequate, list):
            raise ValueError(f"{query_id}.adequate_accessible_docs must be a list")
        adequate_ids = [
            _identifier(item, f"{query_id}.adequate_accessible_docs")
            for item in adequate
        ]
        if len(set(adequate_ids)) != len(adequate_ids):
            raise ValueError(f"{query_id} has duplicate adequate document IDs")

        candidates = query["candidates"]
        if not isinstance(candidates, list):
            raise ValueError(f"{query_id}.candidates must be a list")
        document_ids: set[str] = set()
        for expected_rank, candidate in enumerate(candidates, start=1):
            candidate_label = f"{query_id}.candidates[{expected_rank - 1}]"
            if not isinstance(candidate, dict):
                raise ValueError(f"{candidate_label} must be an object")
            _exact_fields(candidate, CANDIDATE_FIELDS, candidate_label)
            if candidate["rank"] != expected_rank:
                raise ValueError(f"{query_id} candidate ranks must be consecutive from 1")
            document_id = _identifier(candidate["doc_id"], f"{candidate_label}.doc_id")
            if document_id in document_ids:
                raise ValueError(f"{query_id} has duplicate candidate {document_id!r}")
            document_ids.add(document_id)
            if candidate["lifecycle"] not in ALLOWED_LIFECYCLES:
                raise ValueError(f"{candidate_label}.lifecycle is not recognized")
            if candidate["access"] not in ALLOWED_ACCESS:
                raise ValueError(f"{candidate_label}.access is not recognized")
            for field in ("scope_match", "hostile"):
                if not isinstance(candidate[field], bool):
                    raise ValueError(f"{candidate_label}.{field} must be boolean")
            if document_id in adequate_ids and (
                candidate["access"] != "allowed"
                or candidate["lifecycle"] != "active_verified"
                or not candidate["scope_match"]
                or candidate["hostile"]
            ):
                raise ValueError(
                    f"{query_id} marks ineligible candidate {document_id!r} as adequate/accessibile"
                )

    required_classes = {
        "no_answer",
        "stale_index",
        "hostile_content",
        "access_limited",
        "scope_mismatch",
        "false_abstention",
    }
    missing_classes = sorted(required_classes.difference(observed_classes))
    if missing_classes:
        raise ValueError(f"fixture lacks required failure classes: {missing_classes}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fraction(numerator: int | float, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else round(numerator / denominator, 6),
    }


def _blocked_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if candidate["lifecycle"] != "active_verified":
        reasons.append(f"lifecycle_{candidate['lifecycle']}")
    if not candidate["scope_match"]:
        reasons.append("scope_mismatch")
    if candidate["access"] != "allowed":
        reasons.append("access_denied")
    if candidate["hostile"]:
        reasons.append("hostile_instruction_like_content")
    return reasons


def _lifecycle_total(counts: dict[str, int]) -> int:
    return sum(count for reason, count in counts.items() if reason.startswith("lifecycle_"))


def served_violations(
    served: list[dict[str, Any]], candidate_by_id: dict[str, dict[str, Any]]
) -> tuple[dict[str, int], int]:
    """Re-derive eligibility for every document that actually reached the responder.

    This is a measurement over the served artifact rather than a restatement of
    the filter: if the eligibility filter were removed or weakened, the counts
    returned here would rise above zero.
    """
    counts: dict[str, int] = {}
    violating_documents = 0
    for item in served:
        reasons = _blocked_reasons(candidate_by_id[item["doc_id"]])
        if reasons:
            violating_documents += 1
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts, violating_documents


def evaluate_query(query: dict[str, Any], k: int) -> dict[str, Any]:
    adequate = set(query["adequate_accessible_docs"])
    candidate_by_id = {item["doc_id"]: item for item in query["candidates"]}
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    blocked_counts: dict[str, int] = {}

    for candidate in query["candidates"]:
        reasons = _blocked_reasons(candidate)
        if reasons:
            for reason in reasons:
                blocked_counts[reason] = blocked_counts.get(reason, 0) + 1
            reference = (
                "withheld_by_access_policy"
                if candidate["access"] == "denied"
                else candidate["doc_id"]
            )
            blocked.append(
                {
                    "raw_rank": candidate["rank"],
                    "document_reference": reference,
                    "reasons": reasons,
                }
            )
        else:
            eligible.append(candidate)

    # Abstention applies to what the responder sees, not merely to candidates
    # found internally.  This makes false abstention visible in Hit@K and
    # Recall@K rather than hiding it inside candidate generation.
    served_candidates = [] if query["abstained"] else eligible[:k]
    served = [
        {"served_rank": rank, "doc_id": item["doc_id"], "raw_rank": item["rank"]}
        for rank, item in enumerate(served_candidates, start=1)
    ]
    first_adequate_rank = next(
        (item["served_rank"] for item in served if item["doc_id"] in adequate), None
    )
    answerable = bool(adequate)
    # Hit@K asks whether *any* adequate document reached the responder.
    # Recall@K asks what share of the adequate set reached the responder.
    # They coincide only when every answerable query has exactly one adequate
    # document, which is true of this fixture and not true in general; see
    # tests/test_ch09_retrieval_eval.py for a two-document query where Hit
    # reads 1.0 and Recall reads 0.5.
    hit = first_adequate_rank is not None
    adequate_served = [item for item in served if item["doc_id"] in adequate]
    nonadequate_served = [item for item in served if item["doc_id"] not in adequate]
    lifecycle_blocked = _lifecycle_total(blocked_counts)

    served_violation_counts, served_policy_violations = served_violations(
        served, candidate_by_id
    )

    return {
        "query_id": query["query_id"],
        "case_class": query["case_class"],
        "answerable": answerable,
        "adequate_document_count": len(adequate),
        "raw_candidate_count": len(query["candidates"]),
        "eligible_candidate_count": len(eligible),
        "abstained": query["abstained"],
        "served": served,
        "served_count": len(served),
        "blocked_candidates": blocked,
        "blocked_candidate_counts": dict(sorted(blocked_counts.items())),
        "first_adequate_rank": first_adequate_rank,
        "hit_at_k": None if not answerable else (1 if hit else 0),
        "recall_at_k": (
            None if not answerable else round(len(adequate_served) / len(adequate), 6)
        ),
        "adequate_documents_served": len(adequate_served),
        "reciprocal_rank": (
            None
            if not answerable
            else (0.0 if first_adequate_rank is None else round(1 / first_adequate_rank, 6))
        ),
        "miss": answerable and not query["abstained"] and not hit,
        "false_abstention": answerable and query["abstained"],
        "correct_no_answer_abstention": not answerable and query["abstained"],
        "no_answer_leak": not answerable and bool(served),
        "polluted": answerable and bool(nonadequate_served),
        "nonadequate_served_count": len(nonadequate_served),
        "lifecycle_ineligible_candidates_blocked": lifecycle_blocked,
        "scope_mismatch_candidates_blocked": blocked_counts.get("scope_mismatch", 0),
        "access_denied_candidates_blocked": blocked_counts.get("access_denied", 0),
        "hostile_candidates_blocked": blocked_counts.get(
            "hostile_instruction_like_content", 0
        ),
        "lifecycle_ineligible_candidates_served": _lifecycle_total(served_violation_counts),
        "scope_mismatch_candidates_served": served_violation_counts.get("scope_mismatch", 0),
        "access_denied_candidates_served": served_violation_counts.get("access_denied", 0),
        "hostile_candidates_served": served_violation_counts.get(
            "hostile_instruction_like_content", 0
        ),
        "served_policy_violations": served_policy_violations,
    }


def evaluate(data: dict[str, Any], input_sha256: str) -> dict[str, Any]:
    validate_input(data)
    k = data["bundle"]["k"]
    rows = [evaluate_query(query, k) for query in data["queries"]]
    total = len(rows)
    answerable = sum(row["answerable"] for row in rows)
    no_answer = total - answerable
    total_raw_candidates = sum(row["raw_candidate_count"] for row in rows)
    total_served = sum(row["served_count"] for row in rows)
    lifecycle_encountered = sum(
        row["lifecycle_ineligible_candidates_blocked"] for row in rows
    )
    scope_encountered = sum(row["scope_mismatch_candidates_blocked"] for row in rows)
    access_encountered = sum(row["access_denied_candidates_blocked"] for row in rows)
    hostile_encountered = sum(row["hostile_candidates_blocked"] for row in rows)
    lifecycle_served = sum(row["lifecycle_ineligible_candidates_served"] for row in rows)
    scope_served = sum(row["scope_mismatch_candidates_served"] for row in rows)
    access_served = sum(row["access_denied_candidates_served"] for row in rows)
    hostile_served = sum(row["hostile_candidates_served"] for row in rows)
    hits = sum(row["hit_at_k"] for row in rows if row["answerable"])
    recall_sum = round(sum(row["recall_at_k"] for row in rows if row["answerable"]), 6)
    reciprocal_rank_sum = round(
        sum(row["reciprocal_rank"] for row in rows if row["answerable"]), 6
    )

    metrics = {
        f"hit_at_{k}": _fraction(hits, answerable),
        f"recall_at_{k}": _fraction(recall_sum, answerable),
        "mean_reciprocal_rank": _fraction(reciprocal_rank_sum, answerable),
        "corpus_answerable_coverage": _fraction(answerable, total),
        "overall_abstention_rate": _fraction(sum(row["abstained"] for row in rows), total),
        "correct_no_answer_abstention_rate": _fraction(
            sum(row["correct_no_answer_abstention"] for row in rows), no_answer
        ),
        "false_abstention_rate": _fraction(
            sum(row["false_abstention"] for row in rows), answerable
        ),
        "nonabstaining_miss_rate": _fraction(
            sum(row["miss"] for row in rows), answerable
        ),
        "polluted_answerable_query_rate": _fraction(
            sum(row["polluted"] for row in rows), answerable
        ),
        "no_answer_leak_rate": _fraction(
            sum(row["no_answer_leak"] for row in rows), no_answer
        ),
        # Measured invariants: the numerator is re-derived from what was served,
        # so each rate is falsifiable.  Expected 0 of N for every class.
        "lifecycle_ineligible_served_rate": _fraction(
            lifecycle_served, lifecycle_encountered
        ),
        "scope_mismatch_served_rate": _fraction(scope_served, scope_encountered),
        "access_denied_served_rate": _fraction(access_served, access_encountered),
        "hostile_content_served_rate": _fraction(hostile_served, hostile_encountered),
        "served_policy_violation_rate": _fraction(
            sum(row["served_policy_violations"] for row in rows), total_served
        ),
    }

    return {
        "schema_version": "ch09-retrieval-results-1",
        "artifact_class": data["artifact_class"],
        "source_label": data["source_label"],
        "evaluation_id": data["evaluation_id"],
        "provenance": {
            "generator_version": GENERATOR_VERSION,
            "input_sha256": input_sha256,
            "bundle": data["bundle"],
            "adjudication": data["adjudication"],
            "determinism": "No clock, randomness, network, model, or external service is used.",
        },
        "authority": {
            "effect": "none",
            "statement": "This constructed evaluation does not certify a retriever or authorize promotion, production access, or tool execution.",
        },
        "denominator_counts": {
            "total_queries": total,
            "answerable_queries": answerable,
            "no_answer_queries": no_answer,
            "raw_candidates": total_raw_candidates,
            "served_candidates": total_served,
            "lifecycle_ineligible_candidates_encountered": lifecycle_encountered,
            "scope_mismatch_candidates_encountered": scope_encountered,
            "access_denied_candidates_encountered": access_encountered,
            "hostile_candidates_encountered": hostile_encountered,
        },
        "metrics": metrics,
        "per_query": rows,
        "limitations": [
            "The ten constructed queries demonstrate mechanics and are not a statistically sufficient promotion corpus.",
            "Candidate rankings are frozen fixture inputs; this evaluator does not compare lexical, semantic, hybrid, or reranked retrieval systems.",
            "Adequacy labels are constructed reviewer judgments, not observed production outcomes.",
            "Blocked hostile text is never interpreted and no denied document identifier is emitted.",
        ],
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _csv_bytes(result: dict[str, Any]) -> bytes:
    buffer = io.StringIO(newline="")
    fieldnames = [
        "query_id",
        "case_class",
        "answerable",
        "abstained",
        "raw_candidate_count",
        "eligible_candidate_count",
        "served_count",
        "first_adequate_rank",
        "hit_at_k",
        "recall_at_k",
        "adequate_document_count",
        "adequate_documents_served",
        "reciprocal_rank",
        "miss",
        "false_abstention",
        "correct_no_answer_abstention",
        "polluted",
        "lifecycle_ineligible_candidates_blocked",
        "scope_mismatch_candidates_blocked",
        "access_denied_candidates_blocked",
        "hostile_candidates_blocked",
        "lifecycle_ineligible_candidates_served",
        "scope_mismatch_candidates_served",
        "access_denied_candidates_served",
        "hostile_candidates_served",
        "served_policy_violations",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in result["per_query"]:
        writer.writerow(
            {
                field: "" if row[field] is None else row[field]
                for field in fieldnames
            }
        )
    return buffer.getvalue().encode("utf-8")


def _not_applicable(value: Any, template: str = "{}") -> str:
    """Render a per-query cell, marking not-applicable rather than printing zero."""
    return "—" if value is None else template.format(value)


def _count(value: int | float) -> str:
    """Print a whole-numbered count without a trailing .0.

    Recall numerators are sums of per-query fractions, so they are floats even
    when every query contributes 1.0.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _display_fraction(metric: dict[str, Any]) -> str:
    value = metric["value"]
    shown = "N/A" if value is None else f"{value:.3f}"
    return f"{_count(metric['numerator'])} / {metric['denominator']} = {shown}"


def _report_bytes(result: dict[str, Any]) -> bytes:
    metrics = result["metrics"]
    k = result["provenance"]["bundle"]["k"]
    lines = [
        "# Chapter 9 Constructed Retrieval Evaluation",
        "",
        f"**Artifact class:** `{result['artifact_class']}`  ",
        f"**Evaluation:** `{result['evaluation_id']}`  ",
        f"**Input SHA-256:** `{result['provenance']['input_sha256']}`  ",
        f"**Generator:** `{result['provenance']['generator_version']}`",
        "",
        result["authority"]["statement"],
        "",
        "## Aggregate results",
        "",
        "Every rate displays its numerator and eligible denominator.",
        "",
        "| Metric | Numerator / denominator = value |",
        "|---|---:|",
        f"| Hit@{k} (any adequate document served) | "
        f"{_display_fraction(metrics[f'hit_at_{k}'])} |",
        f"| Recall@{k} (adequate documents served / adequate documents) | "
        f"{_display_fraction(metrics[f'recall_at_{k}'])} |",
        f"| Mean reciprocal rank | {_display_fraction(metrics['mean_reciprocal_rank'])} |",
        f"| Corpus answerable coverage | {_display_fraction(metrics['corpus_answerable_coverage'])} |",
        f"| Overall abstention | {_display_fraction(metrics['overall_abstention_rate'])} |",
        f"| Correct no-answer abstention | {_display_fraction(metrics['correct_no_answer_abstention_rate'])} |",
        f"| False abstention | {_display_fraction(metrics['false_abstention_rate'])} |",
        f"| Non-abstaining miss | {_display_fraction(metrics['nonabstaining_miss_rate'])} |",
        f"| Polluted answerable queries | {_display_fraction(metrics['polluted_answerable_query_rate'])} |",
        f"| No-answer leak | {_display_fraction(metrics['no_answer_leak_rate'])} |",
        f"| Retired/superseded lifecycle candidates served | {_display_fraction(metrics['lifecycle_ineligible_served_rate'])} |",
        f"| Wrong-scope candidates served | {_display_fraction(metrics['scope_mismatch_served_rate'])} |",
        f"| Access-denied candidates served | {_display_fraction(metrics['access_denied_served_rate'])} |",
        f"| Hostile instruction-like candidates served | {_display_fraction(metrics['hostile_content_served_rate'])} |",
        f"| Served policy violations | {_display_fraction(metrics['served_policy_violation_rate'])} |",
        "",
        "Hit@K counts a query once if any adequate document reached the responder.",
        "Recall@K is the share of that query's adequate documents that reached the",
        "responder, averaged over answerable queries. The two agree here only because",
        "every answerable query in this fixture has exactly one adequate document; a",
        "query with two adequate documents of which one is served reads Hit 1.000 and",
        "Recall 0.500. The last five rows are measured invariants: the numerator is",
        "re-derived from the served artifact, so a weakened eligibility filter would",
        "show up as a non-zero count.",
        "",
        "## Per-query inspection",
        "",
        "| Query | Class | Answerable | Abstained | Served | First adequate rank | Hit | Recall | RR | Flags |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["per_query"]:
        flags = []
        for field, label in (
            ("miss", "miss"),
            ("false_abstention", "false abstention"),
            ("polluted", "pollution"),
            ("correct_no_answer_abstention", "correct no-answer"),
        ):
            if row[field]:
                flags.append(label)
        if row["lifecycle_ineligible_candidates_blocked"]:
            flags.append("lifecycle blocked")
        if row["scope_mismatch_candidates_blocked"]:
            flags.append("scope blocked")
        if row["access_denied_candidates_blocked"]:
            flags.append("access blocked")
        if row["hostile_candidates_blocked"]:
            flags.append("hostile content blocked")
        lines.append(
            "| {query_id} | {case_class} | {answerable} | {abstained} | "
            "{served_count} | {rank} | {hit} | {recall} | {rr} | {flags} |".format(
                query_id=row["query_id"],
                case_class=row["case_class"],
                answerable=str(row["answerable"]).lower(),
                abstained=str(row["abstained"]).lower(),
                served_count=row["served_count"],
                rank=_not_applicable(row["first_adequate_rank"]),
                hit=_not_applicable(row["hit_at_k"]),
                recall=_not_applicable(row["recall_at_k"], "{:.3f}"),
                rr=_not_applicable(row["reciprocal_rank"], "{:.3f}"),
                flags=", ".join(flags) if flags else "—",
            )
        )
    lines.extend(
        [
            "",
            "## Lifecycle and content boundary",
            "",
            "Eligibility is deterministic: only `active_verified`, in-scope, access-allowed, non-hostile candidates may be served. Retired and superseded versions remain in the audit trail but not in active guidance. Denied identifiers are withheld in generated output. Instruction-like content is classified and blocked as untrusted data; this program has no network or tool-execution path.",
            "",
            "## Limits",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in result["limitations"])
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_outputs(data: dict[str, Any], input_raw: bytes) -> dict[str, bytes]:
    result = evaluate(data, sha256_bytes(input_raw))
    outputs = {
        RESULTS_PATH.name: _json_bytes(result),
        ROWS_PATH.name: _csv_bytes(result),
        REPORT_PATH.name: _report_bytes(result),
    }
    manifest = {
        "schema_version": "ch09-retrieval-run-manifest-1",
        "artifact_class": data["artifact_class"],
        "generator_version": GENERATOR_VERSION,
        "input": {
            "path": "fixtures/ch09/retrieval-evaluation.json",
            "sha256": sha256_bytes(input_raw),
        },
        "outputs": {
            name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
            for name, payload in sorted(outputs.items())
        },
        "deterministic": True,
        "authority_effect": "none",
    }
    outputs[MANIFEST_PATH.name] = _json_bytes(manifest)
    return outputs


def write_outputs(outputs: dict[str, bytes], output_root: Path = OUTPUT_ROOT) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (output_root / name).write_bytes(payload)


def verify_outputs(outputs: dict[str, bytes], output_root: Path = OUTPUT_ROOT) -> None:
    failures: list[str] = []
    for name, expected in outputs.items():
        path = output_root / name
        if not path.exists():
            failures.append(f"missing {path}")
        elif path.read_bytes() != expected:
            failures.append(f"non-deterministic or stale output {path}")
    if failures:
        raise ValueError("; ".join(failures))


def generate(
    input_path: Path = INPUT_PATH,
    output_root: Path = OUTPUT_ROOT,
    *,
    verify: bool = False,
) -> dict[str, Any]:
    data, raw = load_input(input_path)
    outputs = render_outputs(data, raw)
    if verify:
        verify_outputs(outputs, output_root)
    else:
        write_outputs(outputs, output_root)
    return json.loads(outputs[RESULTS_PATH.name].decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write deterministic outputs")
    mode.add_argument("--verify", action="store_true", help="compare outputs byte-for-byte")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = generate(args.input, args.output_dir, verify=args.verify)
    k = result["provenance"]["bundle"]["k"]
    hit = result["metrics"][f"hit_at_{k}"]
    recall = result["metrics"][f"recall_at_{k}"]
    verb = "verified" if args.verify else "wrote"
    print(
        f"Chapter 9 retrieval evaluation {verb}: "
        f"Hit@{k}={_count(hit['numerator'])}/{hit['denominator']}, "
        f"Recall@{k}={_count(recall['numerator'])}/{recall['denominator']}, "
        f"queries={result['denominator_counts']['total_queries']}, authority=none"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
