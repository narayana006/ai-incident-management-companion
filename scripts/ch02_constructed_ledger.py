#!/usr/bin/env python3
"""Generate the Chapter 2 constructed incident-duration ledger.

The values in this module are illustrative. They are measurements of nothing.
The two periods are independent constructed cross-sections, not paired
incident observations. They demonstrate how body and tail summaries can point
in different directions without supporting an intervention-effect claim.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import Counter
from pathlib import Path


COMPANION_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = COMPANION_ROOT / "data" / "generated" / "ch02_constructed_incident_ledger.csv"
SUMMARY_PATH = COMPANION_ROOT / "generated" / "ch02_duration_summary.csv"
FIGURE_PATH = COMPANION_ROOT / "generated" / "figure-2-2-duration-distribution.svg"
DATA_CLASS = "illustrative_constructed"


BASELINE_MINUTES = (
    [10] * 16
    + [18] * 20
    + [24] * 20
    + [45] * 16
    + [150, 180, 210, 240]
    + [540, 840, 1320, 2160]
)

COMPARISON_MINUTES = (
    [8] * 15
    + [12] * 20
    + [15] * 25
    + [30] * 15
    + [90, 105, 120, 150]
    + [5760]
)

PERIODS = {
    "baseline": BASELINE_MINUTES,
    "comparison": COMPARISON_MINUTES,
}


def nearest_rank(values: list[int], quantile: float) -> int:
    """Return the nearest-rank sample percentile.

    The rank is ceil(q * n), using one-based ranks. The manuscript names this
    convention because percentile implementations differ.
    """

    if not values:
        raise ValueError("values must not be empty")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    rank = math.ceil(quantile * len(ordered))
    return ordered[rank - 1]


def summarize(values: list[int]) -> dict[str, float | int]:
    total = sum(values)
    top_three = sum(sorted(values, reverse=True)[:3])
    return {
        "incident_count": len(values),
        "mean_minutes": round(statistics.fmean(values), 1),
        "median_minutes": round(statistics.median(values), 1),
        "p95_nearest_rank_minutes": nearest_rank(values, 0.95),
        "within_60_count": sum(value <= 60 for value in values),
        "within_60_fraction": round(sum(value <= 60 for value in values) / len(values), 4),
        "longest_minutes": max(values),
        "total_incident_minutes": total,
        "top_three_share": round(top_three / total, 4),
    }


def band_counts(values: list[int]) -> Counter[str]:
    """Return the plotted count in each duration band."""

    return Counter(duration_band(value) for value in values)


def write_ledger() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["record_id", "period", "duration_minutes", "data_class"],
        )
        writer.writeheader()
        for period, values in PERIODS.items():
            for index, duration in enumerate(values, start=1):
                writer.writerow(
                    {
                        "record_id": f"{period[:1].upper()}-{index:03d}",
                        "period": period,
                        "duration_minutes": duration,
                        "data_class": DATA_CLASS,
                    }
                )


def write_summary() -> None:
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"period": period, "data_class": DATA_CLASS, **summarize(values)}
        for period, values in PERIODS.items()
    ]
    with SUMMARY_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def duration_band(value: int) -> str:
    if value <= 15:
        return "≤15 min"
    if value <= 30:
        return "16–30 min"
    if value <= 60:
        return "31–60 min"
    if value <= 120:
        return "61–120 min"
    if value <= 240:
        return "121–240 min"
    if value <= 960:
        return "241–960 min"
    return ">960 min"


def write_figure() -> None:
    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    bands = [
        "≤15 min",
        "16–30 min",
        "31–60 min",
        "61–120 min",
        "121–240 min",
        "241–960 min",
        ">960 min",
    ]
    counts = {period: band_counts(values) for period, values in PERIODS.items()}
    width, height = 1080, 620
    plot_left, plot_top, plot_width, plot_height = 110, 120, 900, 360
    max_count = max(count for period in counts.values() for count in period.values())
    group_width = plot_width / len(bands)
    bar_width = 38

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc" data-class="{DATA_CLASS}">',
        f'<metadata>data_class={DATA_CLASS}; independent_constructed_cross_sections=true</metadata>',
        '<title id="title">Constructed incident counts by duration band</title>',
        '<desc id="desc">A grouped bar chart compares two independent constructed cross-sections. The comparison has more rows in the shortest duration band and one row longer than 960 minutes. The chart does not represent paired incidents or an intervention effect.</desc>',
        '<rect x="1" y="1" width="1078" height="618" rx="16" fill="#FFFFFF" stroke="#D7DEE3" stroke-width="2"/>',
        '<text x="52" y="54" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" fill="#17324D">Body and far-tail summaries can point different ways</text>',
        '<text x="52" y="84" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#455A64">Independent constructed cross-sections — not production incident data</text>',
        f'<line x1="{plot_left}" y1="{plot_top + plot_height}" x2="{plot_left + plot_width}" y2="{plot_top + plot_height}" stroke="#7A8B99" stroke-width="2"/>',
        f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_top + plot_height}" stroke="#7A8B99" stroke-width="2"/>',
    ]

    for tick in range(0, max_count + 1, 10):
        y = plot_top + plot_height - (tick / max_count) * plot_height
        parts.append(
            f'<line x1="{plot_left}" y1="{y:.1f}" x2="{plot_left + plot_width}" y2="{y:.1f}" stroke="#E2E8EC" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{plot_left - 14}" y="{y + 5:.1f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="14" fill="#455A64">{tick}</text>'
        )

    colors = {"baseline": "#315D7D", "comparison": "#C65D21"}
    offsets = {"baseline": -bar_width, "comparison": 0}
    for index, band in enumerate(bands):
        center = plot_left + group_width * (index + 0.5)
        for period in ("baseline", "comparison"):
            count = counts[period][band]
            bar_height = (count / max_count) * plot_height
            x = center + offsets[period]
            y = plot_top + plot_height - bar_height
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" rx="3" fill="{colors[period]}" data-period="{period}" data-band="{band}" data-count="{count}" data-class="{DATA_CLASS}"/>'
            )
            if count:
                parts.append(
                    f'<text x="{x + bar_width / 2:.1f}" y="{y - 7:.1f}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" font-weight="700" fill="#17324D">{count}</text>'
                )
        parts.append(
            f'<text x="{center:.1f}" y="{plot_top + plot_height + 30}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="13" fill="#455A64">{band}</text>'
        )

    parts.extend(
        [
            '<rect x="660" y="540" width="18" height="18" rx="2" fill="#315D7D"/>',
            '<text x="688" y="555" font-family="Arial, Helvetica, sans-serif" font-size="15" fill="#17324D">Baseline (N=80)</text>',
            '<rect x="830" y="540" width="18" height="18" rx="2" fill="#C65D21"/>',
            '<text x="858" y="555" font-family="Arial, Helvetica, sans-serif" font-size="15" fill="#17324D">Comparison (N=80)</text>',
            '</svg>',
        ]
    )
    FIGURE_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")


def verify_expected_shape() -> None:
    baseline = summarize(BASELINE_MINUTES)
    comparison = summarize(COMPARISON_MINUTES)
    assert baseline["incident_count"] == comparison["incident_count"] == 80
    assert baseline["median_minutes"] == 24.0
    assert comparison["median_minutes"] == 15.0
    assert baseline["p95_nearest_rank_minutes"] == 240
    assert comparison["p95_nearest_rank_minutes"] == 90
    assert baseline["within_60_count"] == 72
    assert comparison["within_60_count"] == 75
    assert comparison["mean_minutes"] > baseline["mean_minutes"]
    assert baseline["total_incident_minutes"] == 7360
    assert comparison["total_incident_minutes"] == 7410
    assert baseline["longest_minutes"] == 2160
    assert comparison["longest_minutes"] == 5760
    assert baseline["top_three_share"] == 0.587
    assert comparison["top_three_share"] == 0.8138


def main() -> None:
    verify_expected_shape()
    write_ledger()
    write_summary()
    write_figure()
    print(f"wrote {DATA_PATH.relative_to(COMPANION_ROOT)}")
    print(f"wrote {SUMMARY_PATH.relative_to(COMPANION_ROOT)}")
    print(f"wrote {FIGURE_PATH.relative_to(COMPANION_ROOT)}")


if __name__ == "__main__":
    main()
