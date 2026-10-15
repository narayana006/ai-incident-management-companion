#!/usr/bin/env python3
"""Validate the Chapter 3 layer worksheet and report contract gaps.

The worksheet is a decision aid for a proposed coverage model. This script is
deliberately non-evaluative: it lists missing contract elements but does not
rank layers, infer work priority, grant action authority, or collapse the
result into a universal number.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


COMPANION_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = COMPANION_ROOT / "templates" / "ch03-layer-readiness.csv"
REPORT_PATH = COMPANION_ROOT / "generated" / "ch03_layer_readiness_report.md"
GAPS_PATH = COMPANION_ROOT / "generated" / "ch03_layer_readiness_gaps.csv"

EXPECTED_LAYERS = [
    ("L1", "Foundation", "Service topology"),
    ("L2", "Foundation", "Ownership and stewardship"),
    ("L3", "Foundation", "Dependency structure"),
    ("L4", "Dynamic", "Change records"),
    ("L5", "Dynamic", "Deployment history"),
    ("L6", "Dynamic", "Configuration and policy drift"),
    (
        "L7",
        "Observed",
        "Telemetry: metrics, logs, traces, events, profiles, and synthetics",
    ),
    ("L8", "Learning", "Incident history"),
    ("L9", "Learning", "Known failure signatures and anomaly patterns"),
    ("L10", "Learning", "Runbooks and operational procedures"),
    ("L11", "External", "Supplier and ecosystem advisories"),
    ("L12", "External", "Threat and exposure intelligence"),
    (
        "L13",
        "Human and consequence",
        "Response roles, availability, and delegated authority",
    ),
    (
        "L14",
        "Human and consequence",
        "Service impact and business consequence",
    ),
]

BOOLEAN_FIELDS = [
    "stable_subject_identity",
    "bounded_read_interface",
    "valid_time_semantics",
    "source_update_time_semantics",
    "retrieval_time_semantics",
    "freshness_policy",
    "explicit_failure_states",
    "authorized_read_test",
    "denied_access_test",
    "coverage_and_source_health",
    "immutable_reference",
    "transformation_lineage",
    "sensitivity_rule",
    "replay_test",
]

EVIDENCE_FIELDS = {field: f"{field}_evidence" for field in BOOLEAN_FIELDS}
ALLOWED_APPLICABILITY = {"required", "optional", "not_applicable", "not_assessed"}
ALLOWED_BOOLEAN = {"true", "false"}
ALLOWED_SOURCE_STATE_CLASSES = {
    "recorded_intent",
    "live_state_observation",
    "derived_claim",
    "not_assessed",
}

REQUIRED_COLUMNS = [
    "layer_id",
    "family",
    "layer_name",
    "claim_applicability",
    "claim_scope",
    "accountable_owner",
    "recertification_trigger",
    "representative_source",
    "representative_adapter",
    "calling_principal",
    "declared_read_purpose",
    "intended_audience",
    "source_state_class",
    "source_state_class_evidence",
    "representative_query_scope",
    "coverage_definition",
    *[item for field in BOOLEAN_FIELDS for item in (field, EVIDENCE_FIELDS[field])],
    "notes",
]

GAP_FIELD_ORDER = [
    "claim_applicability",
    "claim_scope",
    "accountable_owner",
    "recertification_trigger",
    "representative_source",
    "representative_adapter",
    "calling_principal",
    "declared_read_purpose",
    "intended_audience",
    "source_state_class",
    "source_state_class_evidence",
    "representative_query_scope",
    "coverage_definition",
    *[item for field in BOOLEAN_FIELDS for item in (field, EVIDENCE_FIELDS[field])],
]

FIELD_LABELS = {
    "claim_applicability": "Claim applicability",
    "claim_scope": "Claim scope or rationale",
    "accountable_owner": "Accountable owner",
    "recertification_trigger": "Recertification trigger",
    "representative_source": "Representative source",
    "representative_adapter": "Representative adapter",
    "calling_principal": "Calling principal",
    "declared_read_purpose": "Declared read purpose",
    "intended_audience": "Intended audience",
    "source_state_class": "Representative source-state class",
    "source_state_class_evidence": "Source-state classification evidence",
    "representative_query_scope": "Representative query scope",
    "coverage_definition": "Coverage definition",
    "stable_subject_identity": "Stable subject identity",
    "stable_subject_identity_evidence": "Subject-identity evidence",
    "bounded_read_interface": "Bounded read interface",
    "bounded_read_interface_evidence": "Read-interface evidence",
    "valid_time_semantics": "Valid-time semantics",
    "valid_time_semantics_evidence": "Valid-time evidence",
    "source_update_time_semantics": "Source-update-time semantics",
    "source_update_time_semantics_evidence": "Source-update-time evidence",
    "retrieval_time_semantics": "Retrieval-time semantics",
    "retrieval_time_semantics_evidence": "Retrieval-time evidence",
    "freshness_policy": "Claim-specific freshness policy",
    "freshness_policy_evidence": "Freshness-policy evidence",
    "explicit_failure_states": "Explicit failure states",
    "explicit_failure_states_evidence": "Failure-state evidence",
    "authorized_read_test": "Authorized-read test",
    "authorized_read_test_evidence": "Authorized-read test evidence",
    "denied_access_test": "Denied-access test",
    "denied_access_test_evidence": "Denied-access test evidence",
    "coverage_and_source_health": "Coverage and source-health contract",
    "coverage_and_source_health_evidence": "Coverage and source-health evidence",
    "immutable_reference": "Immutable reference",
    "immutable_reference_evidence": "Immutable-reference evidence",
    "transformation_lineage": "Transformation lineage",
    "transformation_lineage_evidence": "Transformation-lineage evidence",
    "sensitivity_rule": "Sensitivity and audience rule",
    "sensitivity_rule_evidence": "Sensitivity-rule evidence",
    "replay_test": "Replay test",
    "replay_test_evidence": "Replay-test evidence",
}


def _clean(row: dict[str, str | None]) -> dict[str, str]:
    return {key: (value or "").strip() for key, value in row.items() if key is not None}


def read_worksheet(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REQUIRED_COLUMNS:
            missing = sorted(set(REQUIRED_COLUMNS).difference(reader.fieldnames or []))
            extra = sorted(set(reader.fieldnames or []).difference(REQUIRED_COLUMNS))
            raise ValueError(f"worksheet columns do not match; missing={missing}, extra={extra}")
        rows = [_clean(row) for row in reader]
    validate_rows(rows)
    return rows


def validate_rows(rows: list[dict[str, str]]) -> None:
    expected = {layer_id: (family, name) for layer_id, family, name in EXPECTED_LAYERS}
    seen: set[str] = set()

    for row_number, row in enumerate(rows, start=2):
        layer_id = row["layer_id"]
        if not layer_id:
            raise ValueError(f"row {row_number} has an empty layer_id")
        if layer_id in seen:
            raise ValueError(f"duplicate layer_id {layer_id}")
        seen.add(layer_id)
        if layer_id not in expected:
            raise ValueError(f"unexpected layer_id {layer_id}")

        expected_family, expected_name = expected[layer_id]
        if row["family"] != expected_family:
            raise ValueError(
                f"{layer_id} family must be {expected_family!r}, got {row['family']!r}"
            )
        if row["layer_name"] != expected_name:
            raise ValueError(
                f"{layer_id} name must be {expected_name!r}, got {row['layer_name']!r}"
            )

        status = row["claim_applicability"]
        if status not in ALLOWED_APPLICABILITY:
            raise ValueError(
                f"{layer_id} claim_applicability must be one of "
                f"{sorted(ALLOWED_APPLICABILITY)}, got {status!r}"
            )
        source_state_class = row["source_state_class"].lower()
        if source_state_class not in ALLOWED_SOURCE_STATE_CLASSES:
            raise ValueError(
                f"{layer_id} source_state_class must be one of "
                f"{sorted(ALLOWED_SOURCE_STATE_CLASSES)}, "
                f"got {row['source_state_class']!r}"
            )
        row["source_state_class"] = source_state_class
        for field in BOOLEAN_FIELDS:
            value = row[field].lower()
            if value not in ALLOWED_BOOLEAN:
                raise ValueError(
                    f"{layer_id} {field} must be 'true' or 'false', got {row[field]!r}"
                )
            row[field] = value

    missing = [layer_id for layer_id in expected if layer_id not in seen]
    if missing:
        raise ValueError(f"worksheet is missing layers: {missing}")
    if len(rows) != len(EXPECTED_LAYERS):
        raise ValueError(f"worksheet must contain exactly {len(EXPECTED_LAYERS)} layers")


def collect_gaps(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return deterministic field-level gaps without aggregating their severity."""

    rows_by_id = {row["layer_id"]: row for row in rows}
    gaps: list[dict[str, str]] = []

    def add(row: dict[str, str], field: str, reason: str) -> None:
        gaps.append(
            {
                "layer_id": row["layer_id"],
                "family": row["family"],
                "layer_name": row["layer_name"],
                "gap_field": field,
                "gap_reason": reason,
            }
        )

    for layer_id, _, _ in EXPECTED_LAYERS:
        row = rows_by_id[layer_id]
        if row["claim_applicability"] == "not_assessed":
            add(row, "claim_applicability", "claim applicability has not been assessed")
        if not row["claim_scope"]:
            add(
                row,
                "claim_scope",
                "record the supported claim scope or why the layer is not applicable",
            )
        if not row["accountable_owner"]:
            add(row, "accountable_owner", "no accountable owner is recorded")
        if not row["recertification_trigger"]:
            add(row, "recertification_trigger", "no recertification trigger is recorded")
        if not row["representative_source"]:
            add(row, "representative_source", "no representative source is recorded")
        if not row["representative_adapter"]:
            add(row, "representative_adapter", "no representative adapter is recorded")
        if not row["calling_principal"]:
            add(row, "calling_principal", "no calling principal is recorded")
        if not row["declared_read_purpose"]:
            add(row, "declared_read_purpose", "no declared read purpose is recorded")
        if not row["intended_audience"]:
            add(row, "intended_audience", "no intended audience is recorded")
        if row["source_state_class"] == "not_assessed":
            add(
                row,
                "source_state_class",
                "the representative source-state class has not been assessed",
            )
        elif not row["source_state_class_evidence"]:
            add(
                row,
                "source_state_class_evidence",
                "the source-state class lacks an evidence reference",
            )
        if not row["representative_query_scope"]:
            add(
                row,
                "representative_query_scope",
                "no bounded representative query scope is recorded",
            )
        if not row["coverage_definition"]:
            add(row, "coverage_definition", "no query-coverage definition is recorded")

        for field in BOOLEAN_FIELDS:
            evidence_field = EVIDENCE_FIELDS[field]
            if row[field] == "false":
                add(row, field, "capability is absent or has not been demonstrated")
            elif not row[evidence_field]:
                add(
                    row,
                    evidence_field,
                    f"{field} is true but its evidence reference is empty",
                )
    return gaps


def write_gap_csv(gaps: Iterable[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["layer_id", "family", "layer_name", "gap_field", "gap_reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(gaps)


def render_report(rows: list[dict[str, str]], gaps: list[dict[str, str]], source: Path) -> str:
    rows_by_id = {row["layer_id"]: row for row in rows}
    gaps_by_layer: dict[str, list[dict[str, str]]] = defaultdict(list)
    gaps_by_field: dict[str, list[str]] = defaultdict(list)
    for gap in gaps:
        gaps_by_layer[gap["layer_id"]].append(gap)
        gaps_by_field[gap["gap_field"]].append(gap["layer_id"])

    state_counts = Counter(row["claim_applicability"] for row in rows)
    lines = [
        "# Chapter 3 Layer-Readiness Gap Report",
        "",
        "> Deterministic decision aid for a proposed coverage model. It lists contract",
        "> gaps without ranking layers, inferring work priority, or authorizing action.",
        "",
        f"**Worksheet:** `{source.name}`  ",
        "**Operating boundary:** read-only context assembly; responders retain decision authority.",
        "**Source-state vocabulary:** `recorded_intent`, `live_state_observation`,",
        "or `derived_claim`; `not_assessed` means the representative source still needs classification.",
        "",
        "## Claim-applicability states",
        "",
        "| State | Layer count |",
        "|---|---:|",
    ]
    for state in ("required", "optional", "not_applicable", "not_assessed"):
        lines.append(f"| `{state}` | {state_counts[state]} |")

    lines.extend(["", "## Gaps by layer", ""])
    for layer_id, _, _ in EXPECTED_LAYERS:
        row = rows_by_id[layer_id]
        lines.append(f"### {layer_id} — {row['layer_name']}")
        lines.append("")
        lines.append(
            f"- **Representative source-state class:** `{row['source_state_class']}`."
        )
        layer_gaps = gaps_by_layer.get(layer_id, [])
        if not layer_gaps:
            lines.append("- No contract gaps detected in the worksheet fields.")
        else:
            for gap in layer_gaps:
                label = FIELD_LABELS[gap["gap_field"]]
                lines.append(f"- **{label}:** {gap['gap_reason']}.")
        lines.append("")

    lines.extend(
        [
            "## Gaps by field",
            "",
            "| Contract field | Affected layers | Layer IDs |",
            "|---|---:|---|",
        ]
    )
    for field in GAP_FIELD_ORDER:
        layer_ids = gaps_by_field.get(field, [])
        if layer_ids:
            lines.append(
                f"| {FIELD_LABELS[field]} | {len(layer_ids)} | "
                f"{', '.join(f'`{layer_id}`' for layer_id in layer_ids)} |"
            )

    lines.extend(
        [
            "",
            "## How to use this output",
            "",
            "Choose work using incident history, service risk, and the claims a pilot must",
            "support. A layer marked `not_applicable` for one claim is not declared complete.",
            "Run both the authorized-read and denied-access tests under the recorded calling",
            "principal, purpose, query scope, and audience policy. Also exercise stale, partial,",
            "conflicted, and unavailable responses. The expected result is a visible limitation",
            "or explicit hold, never action authority.",
            "",
        ]
    )
    return "\n".join(lines)


def generate(input_path: Path, report_path: Path, gaps_path: Path) -> tuple[int, int]:
    rows = read_worksheet(input_path)
    gaps = collect_gaps(rows)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(rows, gaps, input_path), encoding="utf-8")
    write_gap_csv(gaps, gaps_path)
    return len(rows), len(gaps)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--gaps", type=Path, default=GAPS_PATH)
    return parser.parse_args()


def display_path(path: Path) -> str:
    """Return a readable path whether or not it is inside the companion tree."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(COMPANION_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def main() -> None:
    args = parse_args()
    layer_count, gap_count = generate(args.input, args.report, args.gaps)
    print(f"validated {layer_count} layers; listed {gap_count} field-level gaps")
    print(f"wrote {display_path(args.report)}")
    print(f"wrote {display_path(args.gaps)}")


if __name__ == "__main__":
    main()
