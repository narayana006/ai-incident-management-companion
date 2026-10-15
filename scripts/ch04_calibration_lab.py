#!/usr/bin/env python3
"""Reproduce the Chapter 4 CAL-01 synthetic calibration artifacts.

This lab reads one pinned, constructed row-level fixture. It performs no
network calls and has no production write path. The output demonstrates
equal-width binning, Wilson 95% intervals, and boundary-aware uncertainty; it
does not validate a model, action class, threshold, or operational effect.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import textwrap
from xml.sax.saxutils import escape
from pathlib import Path


COMPANION_ROOT = Path(__file__).resolve().parents[1]
BOOK_ROOT = COMPANION_ROOT.parent
INPUT_PATH = COMPANION_ROOT / "fixtures" / "ch04" / "CAL-01" / "synthetic_smoke.csv"
SUMMARY_PATH = COMPANION_ROOT / "generated" / "ch04_calibration_bin_summary.csv"
INTERVAL_PATH = COMPANION_ROOT / "generated" / "ch04_calibration_interval_table.csv"
FIGURE_PATH = COMPANION_ROOT / "generated" / "figure-4-1-calibration-reliability.svg"
AUTHORITY_SOURCE_PATH = (
    COMPANION_ROOT / "diagrams" / "src" / "figure-4-2-three-state-authority-flow.json"
)
AUTHORITY_FIGURE_PATH = (
    COMPANION_ROOT / "generated" / "figure-4-2-three-state-authority-flow.svg"
)
PROVENANCE_PATH = COMPANION_ROOT / "generated" / "ch04_calibration_provenance.md"
MANIFEST_PATH = COMPANION_ROOT / "generated" / "ch04_calibration_run_manifest.json"

DATA_CLASS = "illustrative_constructed"
EXPECTED_INPUT_SHA256 = "b6e914b2a3482236b8356a1c7cfb52dd5815e34008351face95b047572a661fc"
RELEASE_RUNTIME = "CPython 3.12.13"
RUNTIME_CONTRACT = "CPython >=3.11; Python standard library only"
COMMAND = "cd companion && make calibration"
Z_95 = 1.959963984540054
ILLUSTRATIVE_BOUNDARIES = (0.70, 0.90)
BINS = (
    (0.50, 0.60, False),
    (0.60, 0.70, False),
    (0.70, 0.80, False),
    (0.80, 0.90, False),
    (0.90, 0.95, False),
    (0.95, 1.00, True),
)
REQUIRED_COLUMNS = (
    "record_id",
    "incident_group_id",
    "action_class",
    "calibrated_confidence",
    "adjudicated_correct",
    "model_version",
    "calibration_version",
    "evidence_label",
)
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CalibrationInputError(ValueError):
    """The authoritative fixture violates its declared contract."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def verify_pinned_input(path: Path = INPUT_PATH) -> str:
    if not path.is_file():
        raise CalibrationInputError(f"authoritative input is missing: {path}")
    actual = sha256_path(path)
    if actual != EXPECTED_INPUT_SHA256:
        raise CalibrationInputError(
            "authoritative input hash mismatch: "
            f"expected {EXPECTED_INPUT_SHA256}, found {actual}"
        )
    return actual


def read_rows(path: Path = INPUT_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise CalibrationInputError(
                f"schema mismatch: expected {REQUIRED_COLUMNS}, found {reader.fieldnames}"
            )
        rows = list(reader)
    validate_rows(rows)
    return rows


def validate_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise CalibrationInputError("fixture contains no rows")

    record_ids: set[str] = set()
    independent_units: set[tuple[str, str]] = set()
    version_bundles: set[tuple[str, str, str]] = set()

    for line_number, row in enumerate(rows, start=2):
        missing = [column for column in REQUIRED_COLUMNS if not row.get(column, "").strip()]
        if missing:
            raise CalibrationInputError(f"line {line_number}: blank fields {missing}")

        if row["evidence_label"] != DATA_CLASS:
            raise CalibrationInputError(
                f"line {line_number}: evidence_label must be {DATA_CLASS!r}"
            )

        for field in (
            "record_id",
            "incident_group_id",
            "action_class",
            "model_version",
            "calibration_version",
        ):
            if not SAFE_IDENTIFIER.fullmatch(row[field]):
                raise CalibrationInputError(
                    f"line {line_number}: invalid {field} {row[field]!r}"
                )

        record_id = row["record_id"]
        if record_id in record_ids:
            raise CalibrationInputError(f"line {line_number}: duplicate record_id {record_id!r}")
        record_ids.add(record_id)

        unit = (row["incident_group_id"], row["action_class"])
        if unit in independent_units:
            raise CalibrationInputError(
                "line "
                f"{line_number}: duplicate incident_group_id/action_class unit {unit!r}"
            )
        independent_units.add(unit)

        version_bundles.add(
            (row["model_version"], row["calibration_version"], row["action_class"])
        )

        try:
            score = float(row["calibrated_confidence"])
        except ValueError as error:
            raise CalibrationInputError(
                f"line {line_number}: calibrated_confidence is not numeric"
            ) from error
        if not math.isfinite(score) or not 0.50 <= score <= 1.00:
            raise CalibrationInputError(
                f"line {line_number}: calibrated_confidence must be finite and in [0.50, 1.00]"
            )

        if row["adjudicated_correct"] not in {"0", "1"}:
            raise CalibrationInputError(
                f"line {line_number}: adjudicated_correct must be 0 or 1"
            )

    if len(version_bundles) != 1:
        raise CalibrationInputError(
            "refusing to pool action classes or model/calibration versions: "
            f"found {sorted(version_bundles)!r}"
        )


def wilson_interval(correct: int, total: int, z: float = Z_95) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("Wilson interval requires total > 0")
    if not 0 <= correct <= total:
        raise ValueError("correct must be between 0 and total")
    observed = correct / total
    denominator = 1 + z * z / total
    center = (observed + z * z / (2 * total)) / denominator
    half_width = (
        z
        * math.sqrt(
            observed * (1 - observed) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    lower = max(0.0, center - half_width)
    upper = min(1.0, center + half_width)
    if correct == 0:
        lower = 0.0
    if correct == total:
        upper = 1.0
    return lower, upper


def in_bin(score: float, lower: float, upper: float, upper_inclusive: bool) -> bool:
    return lower <= score <= upper if upper_inclusive else lower <= score < upper


def nearest_boundary(mean_score: float) -> float:
    return min(ILLUSTRATIVE_BOUNDARIES, key=lambda value: (abs(value - mean_score), value))


def summarize(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    action_class = rows[0]["action_class"]
    model_version = rows[0]["model_version"]
    calibration_version = rows[0]["calibration_version"]
    summaries: list[dict[str, object]] = []

    for lower, upper, upper_inclusive in BINS:
        selected = [
            row
            for row in rows
            if in_bin(float(row["calibrated_confidence"]), lower, upper, upper_inclusive)
        ]
        total = len(selected)
        correct = sum(int(row["adjudicated_correct"]) for row in selected)
        if total:
            mean_score = sum(float(row["calibrated_confidence"]) for row in selected) / total
            observed = correct / total
            interval_lower, interval_upper = wilson_interval(correct, total)
            boundary = nearest_boundary(mean_score)
            if interval_lower > boundary:
                decision = "interval_above_illustrative_boundary"
            elif interval_upper < boundary:
                decision = "interval_below_illustrative_boundary"
            else:
                decision = "uncertified_interval_crosses_boundary"
        else:
            mean_score = observed = interval_lower = interval_upper = None
            boundary = nearest_boundary((lower + upper) / 2)
            decision = "uncertified_empty_bin"

        summaries.append(
            {
                "data_class": DATA_CLASS,
                "action_class": action_class,
                "model_version": model_version,
                "calibration_version": calibration_version,
                "bin_lower": lower,
                "bin_upper": upper,
                "upper_inclusive": upper_inclusive,
                "n": total,
                "correct_k": correct,
                "mean_score": mean_score,
                "observed_rate": observed,
                "wilson_lower": interval_lower,
                "wilson_upper": interval_upper,
                "illustrative_boundary": boundary,
                "decision": decision,
            }
        )
    return summaries


def decimal(value: object) -> str:
    return "" if value is None else f"{float(value):.4f}"


def csv_bytes(fieldnames: list[str], rows: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_summary_csv(summaries: list[dict[str, object]], input_hash: str) -> bytes:
    rows = []
    for item in summaries:
        rows.append(
            {
                "data_class": DATA_CLASS,
                "input_sha256": input_hash,
                "action_class": item["action_class"],
                "model_version": item["model_version"],
                "calibration_version": item["calibration_version"],
                "bin": (
                    f"[{item['bin_lower']:.2f},{item['bin_upper']:.2f}]"
                    if item["upper_inclusive"]
                    else f"[{item['bin_lower']:.2f},{item['bin_upper']:.2f})"
                ),
                "n": item["n"],
                "correct_k": item["correct_k"],
                "mean_calibrated_score": decimal(item["mean_score"]),
                "observed_right_rate": decimal(item["observed_rate"]),
                "wilson_95_lower": decimal(item["wilson_lower"]),
                "wilson_95_upper": decimal(item["wilson_upper"]),
                "illustrative_boundary": decimal(item["illustrative_boundary"]),
                "decision": item["decision"],
            }
        )
    return csv_bytes(list(rows[0]), rows)


def build_interval_csv(summaries: list[dict[str, object]], input_hash: str) -> bytes:
    rows = []
    for item in summaries:
        rows.append(
            {
                "data_class": DATA_CLASS,
                "input_sha256": input_hash,
                "bin_lower_inclusive": f"{item['bin_lower']:.2f}",
                "bin_upper": f"{item['bin_upper']:.2f}",
                "upper_endpoint": "inclusive" if item["upper_inclusive"] else "exclusive",
                "independent_n": item["n"],
                "right_k": item["correct_k"],
                "observed_right_rate": decimal(item["observed_rate"]),
                "wilson_95_lower": decimal(item["wilson_lower"]),
                "wilson_95_upper": decimal(item["wilson_upper"]),
                "count_interpretation": "shown_without_universal_minimum",
            }
        )
    return csv_bytes(list(rows[0]), rows)


def build_figure_svg(summaries: list[dict[str, object]], input_hash: str) -> bytes:
    width, height = 1200, 760
    left, top, plot_width, plot_height = 120, 145, 960, 455
    x_min, x_max, y_min, y_max = 0.45, 1.00, 0.40, 1.00

    def x_position(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def y_position(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_height

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc" data-class="{DATA_CLASS}">',
        f'<metadata>data_class={DATA_CLASS};input_sha256={input_hash};method=Wilson_95_two_sided;bins=predeclared_equal_width_with_split_upper_band</metadata>',
        '<title id="title">CAL-01 constructed reliability diagram with denominators and Wilson intervals</title>',
        '<desc id="desc">Six hollow points compare mean calibrated scores with observed right rates in 254 unique constructed incident-group and action-class pairs. Every point includes its count and a two-sided 95 percent Wilson interval. All intervals cross the nearest illustrative policy boundary, so every bin is marked uncertified. The two upper bins contain ten and seven rows.</desc>',
        '<rect x="1" y="1" width="1198" height="758" rx="18" fill="#FFFFFF" stroke="#D4DDE4" stroke-width="2"/>',
        '<text x="54" y="54" font-family="Arial, Helvetica, sans-serif" font-size="30" font-weight="700" fill="#17324D">CAL-01: the denominator stays visible</text>',
        '<text x="54" y="88" font-family="Arial, Helvetica, sans-serif" font-size="17" fill="#455A64">Constructed data — method demonstration only; no production model or threshold is validated</text>',
    ]

    for tick in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        x = x_position(tick)
        y = y_position(tick)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#E4EAEE" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#E4EAEE" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{top + plot_height + 28}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">{tick:.1f}</text>'
        )
        parts.append(
            f'<text x="{left - 16}" y="{y + 5:.1f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">{tick:.1f}</text>'
        )

    parts.extend(
        [
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#607D8B" stroke-width="2"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#607D8B" stroke-width="2"/>',
            f'<line x1="{x_position(0.45):.1f}" y1="{y_position(0.45):.1f}" x2="{x_position(1.0):.1f}" y2="{y_position(1.0):.1f}" stroke="#8295A3" stroke-width="2" stroke-dasharray="8 7"/>',
        ]
    )

    for boundary in ILLUSTRATIVE_BOUNDARIES:
        x = x_position(boundary)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="#B24A3B" stroke-width="2" stroke-dasharray="3 7"/>'
        )
        parts.append(
            f'<text x="{x + 7:.1f}" y="{top + 20}" font-family="Arial, Helvetica, sans-serif" font-size="13" fill="#8D342A">{boundary:.2f} illustrative boundary</text>'
        )

    label_offsets = ((10, -12), (10, 23), (10, -12), (10, 23), (-82, 28), (-58, 56))
    for index, item in enumerate(summaries):
        if not item["n"]:
            continue
        mean_score = float(item["mean_score"])
        observed = float(item["observed_rate"])
        lower_interval = float(item["wilson_lower"])
        upper_interval = float(item["wilson_upper"])
        x = x_position(mean_score)
        y = y_position(observed)
        y_low = y_position(lower_interval)
        y_high = y_position(upper_interval)
        parts.extend(
            [
                f'<line x1="{x:.1f}" y1="{y_high:.1f}" x2="{x:.1f}" y2="{y_low:.1f}" stroke="#244E70" stroke-width="3"/>',
                f'<line x1="{x - 8:.1f}" y1="{y_high:.1f}" x2="{x + 8:.1f}" y2="{y_high:.1f}" stroke="#244E70" stroke-width="3"/>',
                f'<line x1="{x - 8:.1f}" y1="{y_low:.1f}" x2="{x + 8:.1f}" y2="{y_low:.1f}" stroke="#244E70" stroke-width="3"/>',
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="#FFFFFF" stroke="#244E70" stroke-width="4" data-n="{item["n"]}" data-k="{item["correct_k"]}" data-decision="{item["decision"]}" data-class="{DATA_CLASS}"/>',
            ]
        )
        dx, dy = label_offsets[index]
        parts.append(
            f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" font-family="Arial, Helvetica, sans-serif" font-size="14" font-weight="700" fill="#17324D">N={item["n"]}</text>'
        )

    parts.extend(
        [
            f'<text x="{left + plot_width / 2:.1f}" y="{top + plot_height + 65}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" fill="#17324D">Mean calibrated score in bin</text>',
            f'<text x="35" y="{top + plot_height / 2:.1f}" text-anchor="middle" transform="rotate(-90 35 {top + plot_height / 2:.1f})" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" fill="#17324D">Observed right rate</text>',
            '<circle cx="64" cy="687" r="7" fill="#FFFFFF" stroke="#244E70" stroke-width="3"/>',
            '<text x="82" y="692" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">Hollow = 95% interval crosses nearest illustrative boundary</text>',
            '<text x="64" y="721" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">Wilson 95% intervals · counts shown without a universal minimum · upper bins: N=10 and N=7</text>',
            f'<text x="1135" y="721" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#6C7D88">input sha256 {input_hash[:12]}…</text>',
            '</svg>',
        ]
    )
    return ("\n".join(parts) + "\n").encode("utf-8")


def read_authority_source(path: Path = AUTHORITY_SOURCE_PATH) -> tuple[dict[str, object], str]:
    content = path.read_bytes()
    source_hash = sha256_bytes(content)
    try:
        source = json.loads(content)
    except json.JSONDecodeError as error:
        raise CalibrationInputError(f"authority diagram source is invalid JSON: {error}") from error
    required = {
        "schema_version",
        "data_class",
        "figure_id",
        "title",
        "claim_boundary",
        "gates",
        "states",
        "hold_conditions",
    }
    if set(source) != required:
        raise CalibrationInputError(
            f"authority diagram source fields must be {sorted(required)!r}"
        )
    if source["data_class"] != "proposed_design":
        raise CalibrationInputError("authority diagram must be labeled proposed_design")
    if len(source["gates"]) != 6 or len(source["states"]) != 3:
        raise CalibrationInputError("authority diagram requires six gates and three states")
    expected_ids = ["suggest", "acknowledge", "bounded_auto"]
    if [state.get("id") for state in source["states"]] != expected_ids:
        raise CalibrationInputError(f"authority states must be ordered {expected_ids!r}")
    if len(source["hold_conditions"]) != 3:
        raise CalibrationInputError("authority diagram requires three explicit hold conditions")
    return source, source_hash


def build_authority_svg(source: dict[str, object], source_hash: str) -> bytes:
    states = source["states"]
    gates = source["gates"]
    assert isinstance(states, list) and isinstance(gates, list)

    def wrapped_text(
        value: str,
        x: int,
        y: int,
        width_chars: int,
        font_size: int = 16,
        line_height: int = 23,
        color: str = "#455A64",
        weight: str = "400",
        anchor: str = "start",
    ) -> list[str]:
        return [
            f'<text x="{x}" y="{y + index * line_height}" text-anchor="{anchor}" font-family="Arial, Helvetica, sans-serif" font-size="{font_size}" font-weight="{weight}" fill="{color}">{escape(line)}</text>'
            for index, line in enumerate(textwrap.wrap(value, width=width_chars))
        ]

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="900" viewBox="0 0 1500 900" role="img" aria-labelledby="title desc" data-class="proposed_design">',
        f'<metadata>data_class=proposed_design;source_sha256={source_hash};model_score_grants_authority=false;silence_executes=false</metadata>',
        '<title id="title">Three visible authority states behind deterministic policy checks</title>',
        '<desc id="desc">A candidate recommendation enters deterministic model-independent ceiling checks. Policy routes it to Suggest, Propose and await positive acknowledgement, or Eligible for bounded automated execution. A failed check holds execution. In the acknowledgement branch, silence, rejection, expiry, or a material change holds and demotes the proposal. The automated branch reaches a separately credentialed executor only after an execution-time recheck.</desc>',
        '<defs><marker id="arrow" markerWidth="11" markerHeight="8" refX="10" refY="4" orient="auto"><path d="M0,0 L11,4 L0,8 Z" fill="#536B7A"/></marker><marker id="red-arrow" markerWidth="11" markerHeight="8" refX="10" refY="4" orient="auto"><path d="M0,0 L11,4 L0,8 Z" fill="#A43D34"/></marker></defs>',
        '<rect x="1" y="1" width="1498" height="898" rx="18" fill="#FFFFFF" stroke="#D4DDE4" stroke-width="2"/>',
        f'<text x="54" y="58" font-family="Arial, Helvetica, sans-serif" font-size="31" font-weight="700" fill="#17324D">{escape(str(source["title"]))}</text>',
        f'<text x="54" y="92" font-family="Arial, Helvetica, sans-serif" font-size="17" fill="#455A64">{escape(str(source["claim_boundary"]))}</text>',
        '<rect x="45" y="140" width="290" height="120" rx="14" fill="#EEF4F8" stroke="#315D7D" stroke-width="2"/>',
        '<text x="68" y="176" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" fill="#17324D">Candidate recommendation</text>',
        '<text x="68" y="211" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#455A64">Evidence + named score</text>',
        '<text x="68" y="239" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#455A64">Action class + exact target</text>',
        '<line x1="335" y1="200" x2="380" y2="200" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
        '<rect x="385" y="115" width="515" height="200" rx="14" fill="#F7F9FA" stroke="#607D8B" stroke-width="2"/>',
        '<text x="410" y="150" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" fill="#17324D">Deterministic authority-ceiling checks</text>',
        '<text x="410" y="178" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#6C7D88">Outside the model; one failed required check holds execution</text>',
    ]
    gate_positions = ((410, 214), (410, 250), (410, 286), (665, 214), (665, 250), (665, 286))
    for gate, (x, y) in zip(gates, gate_positions):
        parts.append(f'<circle cx="{x}" cy="{y - 5}" r="4" fill="#315D7D"/>')
        parts.extend(wrapped_text(str(gate), x + 12, y, 28, font_size=14, line_height=17))

    parts.extend(
        [
            '<line x1="900" y1="200" x2="950" y2="200" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
            '<polygon points="1050,120 1155,200 1050,280 945,200" fill="#FFF7E7" stroke="#A96B17" stroke-width="2"/>',
            '<text x="1050" y="185" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#6E4915">Policy-selected</text>',
            '<text x="1050" y="212" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#6E4915">maximum state</text>',
            '<text x="1050" y="238" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="13" fill="#6E4915">not confidence alone</text>',
            '<path d="M642 315 L642 328 L150 328 L150 375" fill="none" stroke="#A43D34" stroke-width="3" marker-end="url(#red-arrow)"/>',
            '<text x="410" y="320" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" font-weight="700" fill="#A43D34">failed required check → hold execution</text>',
            '<path d="M1005 263 L1005 350 L350 350 L350 375" fill="none" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
            '<path d="M1050 280 L1050 350 L750 350 L750 375" fill="none" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
            '<path d="M1095 263 L1095 350 L1250 350 L1250 375" fill="none" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
        ]
    )

    card_specs = (
        (40, "#EAF3F8", "#315D7D"),
        (540, "#FFF5DF", "#A96B17"),
        (1040, "#EAF6EF", "#2C7250"),
    )
    for state, (x, fill, stroke) in zip(states, card_specs):
        assert isinstance(state, dict)
        parts.append(
            f'<rect x="{x}" y="380" width="420" height="145" rx="15" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'
        )
        parts.extend(
            wrapped_text(str(state["name"]), x + 22, 418, 36, 19, 22, "#17324D", "700")
        )
        parts.extend(wrapped_text(str(state["detail"]), x + 22, 475, 48, 16, 22))

    parts.extend(
        [
            '<line x1="250" y1="525" x2="250" y2="585" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
            '<rect x="95" y="590" width="310" height="84" rx="12" fill="#F7F9FA" stroke="#607D8B" stroke-width="2"/>',
            '<text x="250" y="625" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#17324D">Human decides</text>',
            '<text x="250" y="652" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">accept, reject, modify, or ignore</text>',
            '<line x1="750" y1="525" x2="750" y2="563" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
            '<polygon points="750,568 848,632 750,696 652,632" fill="#FFF7E7" stroke="#A96B17" stroke-width="2"/>',
            '<text x="750" y="622" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="16" font-weight="700" fill="#6E4915">Authorized positive</text>',
            '<text x="750" y="646" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="16" font-weight="700" fill="#6E4915">acknowledgement?</text>',
            '<path d="M652 632 L565 632 L565 718" fill="none" stroke="#A43D34" stroke-width="3" marker-end="url(#red-arrow)"/>',
            '<text x="640" y="617" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="13" font-weight="700" fill="#A43D34">no / silence / expiry</text>',
            '<rect x="395" y="723" width="340" height="94" rx="12" fill="#FCEDEC" stroke="#A43D34" stroke-width="2"/>',
            '<text x="565" y="758" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#842F29">HOLD — demote to Suggest</text>',
            '<text x="565" y="786" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#6E3B36">material change also invalidates approval</text>',
            '<path d="M848 632 L935 632 L935 718" fill="none" stroke="#2C7250" stroke-width="3" marker-end="url(#arrow)"/>',
            '<text x="875" y="617" font-family="Arial, Helvetica, sans-serif" font-size="14" font-weight="700" fill="#2C7250">yes</text>',
            '<rect x="760" y="723" width="315" height="94" rx="12" fill="#EAF6EF" stroke="#2C7250" stroke-width="2"/>',
            '<text x="918" y="758" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#245E43">Exact approved request</text>',
            '<text x="918" y="786" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#376D56">immutable target, scope, and expiry</text>',
            '<line x1="1250" y1="525" x2="1250" y2="585" stroke="#536B7A" stroke-width="3" marker-end="url(#arrow)"/>',
            '<rect x="1080" y="590" width="340" height="112" rx="12" fill="#F7F9FA" stroke="#607D8B" stroke-width="2"/>',
            '<text x="1250" y="626" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#17324D">Execution-time recheck</text>',
            '<text x="1250" y="654" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">separate identity · current state</text>',
            '<text x="1250" y="680" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">bounded request · auditable result</text>',
            '<line x1="1250" y1="702" x2="1250" y2="738" stroke="#A43D34" stroke-width="3" marker-end="url(#red-arrow)"/>',
            '<rect x="1100" y="743" width="320" height="74" rx="12" fill="#FCEDEC" stroke="#A43D34" stroke-width="2"/>',
            '<text x="1250" y="775" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" fill="#842F29">Any changed check → HOLD</text>',
            '<text x="1250" y="800" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="13" fill="#6E3B36">eligibility is not a standing credential</text>',
            '<text x="54" y="864" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#6C7D88">Proposed design. Confidence is one policy input; it cannot override evidence, reversibility, bounds, authority, or current system state.</text>',
            f'<text x="1445" y="864" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#6C7D88">source sha256 {source_hash[:12]}…</text>',
            '</svg>',
        ]
    )
    return ("\n".join(parts) + "\n").encode("utf-8")


def build_provenance(input_hash: str, generator_hash: str, summaries: list[dict[str, object]]) -> bytes:
    counts = ", ".join(f"{item['n']}" for item in summaries)
    text = f"""# CAL-01 v4 provenance

Data class: `{DATA_CLASS}`. Every source row and generated table row carries this label.

- Scope: constructed, held-out-style binary outcomes for one illustrative action class and one version bundle
- Claim boundary: method mechanics only; no production model, threshold, action class, or operational effect is validated
- Authoritative input: `fixtures/ch04/CAL-01/synthetic_smoke.csv`
- Input SHA-256: `{input_hash}`
- Generator SHA-256: `{generator_hash}`
- Independent unit rule: at most one row per `incident_group_id` and `action_class`
- Eligible rows in this fixture: 254
- Adjudicated binary rows: 254
- Indeterminate rows: 0
- Excluded rows: 0
- Bin convention: `[0.50,0.60)`, `[0.60,0.70)`, `[0.70,0.80)`, `[0.80,0.90)`, `[0.90,0.95)`, `[0.95,1.00]`
- Bin counts in that order: {counts}
- Interval: two-sided 95% Wilson score interval, `z={Z_95}`
- Illustrative boundaries: 0.70 and 0.90; neither is a recommendation
- Decision rule: a bin is uncertified when its interval crosses the nearest illustrative boundary; no sample-count minimum certifies a bin
- Version rule: pooling across action classes or model/calibrator versions is rejected
- Runtime used for release artifacts: {RELEASE_RUNTIME}
- Dependency versions: Python standard library from {RELEASE_RUNTIME}; no third-party package
- Exact command: `{COMMAND}`

The fixture contains no indeterminate or excluded examples. The zero counts above describe this constructed input; the lab does not silently remove either outcome class from a larger population.
"""
    return text.encode("utf-8")


def build_artifacts() -> dict[Path, bytes]:
    input_hash = verify_pinned_input()
    rows = read_rows()
    summaries = summarize(rows)
    generator_hash = sha256_path(Path(__file__).resolve())

    summary = build_summary_csv(summaries, input_hash)
    intervals = build_interval_csv(summaries, input_hash)
    figure = build_figure_svg(summaries, input_hash)
    authority_source, authority_source_hash = read_authority_source()
    authority_figure = build_authority_svg(authority_source, authority_source_hash)
    provenance = build_provenance(input_hash, generator_hash, summaries)
    non_manifest = {
        SUMMARY_PATH: summary,
        INTERVAL_PATH: intervals,
        FIGURE_PATH: figure,
        AUTHORITY_FIGURE_PATH: authority_figure,
        PROVENANCE_PATH: provenance,
    }
    manifest = {
        "schema_version": "cal-01-run-manifest-v1",
        "data_class": DATA_CLASS,
        "claim_boundary": "method_mechanics_only_no_production_validation",
        "command": COMMAND,
        "runtime_contract": RUNTIME_CONTRACT,
        "release_runtime": RELEASE_RUNTIME,
        "dependencies": {"third_party": [], "python_standard_library": RELEASE_RUNTIME},
        "input": {
            "path": "fixtures/ch04/CAL-01/synthetic_smoke.csv",
            "sha256": input_hash,
            "rows": len(rows),
            "eligible": len(rows),
            "adjudicated_binary": len(rows),
            "indeterminate": 0,
            "excluded": 0,
        },
        "contract": {
            "independent_unit": "one incident_group_id/action_class pair",
            "interval": "two-sided Wilson 95%",
            "z": Z_95,
            "illustrative_boundaries": list(ILLUSTRATIVE_BOUNDARIES),
            "boundary_transfer_allowed": False,
            "count_minimum_used_for_certification": None,
            "version_pooling_allowed": False,
        },
        "generator_sha256": generator_hash,
        "diagram_sources": {
            "diagrams/src/figure-4-2-three-state-authority-flow.json": authority_source_hash
        },
        "output_sha256": {
            str(path.relative_to(COMPANION_ROOT)): sha256_bytes(content)
            for path, content in sorted(non_manifest.items(), key=lambda item: str(item[0]))
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return {**non_manifest, MANIFEST_PATH: manifest_bytes}


def write_artifacts(artifacts: dict[Path, bytes]) -> None:
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)


def verify_artifacts(artifacts: dict[Path, bytes]) -> None:
    failures: list[str] = []
    for path, expected in artifacts.items():
        try:
            display_path = str(path.relative_to(COMPANION_ROOT))
        except ValueError:
            display_path = str(path)
        if not path.is_file():
            failures.append(f"missing {display_path}")
            continue
        actual = path.read_bytes()
        if actual != expected:
            failures.append(
                f"drift in {display_path}: "
                f"expected sha256 {sha256_bytes(expected)}, found {sha256_bytes(actual)}"
            )
    if failures:
        raise RuntimeError("generated CAL-01 artifacts failed verification:\n- " + "\n- ".join(failures))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate committed artifacts")
    mode.add_argument("--verify", action="store_true", help="fail if committed artifacts drift")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifacts = build_artifacts()
        if args.write:
            write_artifacts(artifacts)
            print("wrote CAL-01 v4 artifacts")
        verify_artifacts(artifacts)
        print(f"verified {len(artifacts)} CAL-01 artifacts from pinned input")
        return 0
    except (CalibrationInputError, OSError, RuntimeError, ValueError) as error:
        print(f"CAL-01 failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
