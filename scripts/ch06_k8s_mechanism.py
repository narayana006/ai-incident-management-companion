#!/usr/bin/env python3
"""Validate and render the committed K8S-01 mechanism evidence.

Default operation is read-only with respect to the experiment record. It does
not create a cluster or append a trial. The supported evidence is one sequential
run for each of two completed treatments in one disposable configuration; the
declared TTL treatment was not run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
from typing import Any


COMPANION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = COMPANION_ROOT.parent
SOURCE_ROOT = COMPANION_ROOT / "fixtures" / "ch06" / "K8S-01"
PINS_PATH = COMPANION_ROOT / "fixtures" / "ch06" / "k8s01_source_manifest.json"
OUTPUT_MANIFEST = COMPANION_ROOT / "generated" / "ch06_k8s01_manifest.json"
OUTPUT_TABLE = COMPANION_ROOT / "generated" / "ch06_k8s01_observations.csv"
OUTPUT_REPORT = COMPANION_ROOT / "generated" / "ch06_k8s01_report.md"
OUTPUT_FIGURE = COMPANION_ROOT / "generated" / "figure-6-6-k8s01-observed-mechanism.svg"

TRIAL_COLUMNS = [
    "run_id",
    "treatment",
    "requested_value",
    "replicas_before",
    "observed_utilization",
    "hpa_max_before",
    "time_to_first_reconcile_s",
    "time_to_revert_or_converge_s",
    "ttl_seconds",
    "ttl_cleanup_result",
    "oscillation_count",
    "utc",
]

ENDPOINT_KEYS = (
    "controller_input",
    "controller_decision",
    "owned_target_field",
    "observed_workload_state",
)

DISALLOWED_CLAIMS = [
    "comparative speed",
    "safety",
    "general performance",
    "oscillation frequency",
    "production generalization",
    "TTL cleanup",
    "user-facing improvement",
]


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_pins(source_root: Path, pins: dict[str, Any]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for expected in pins.get("files", []):
        relative = Path(expected["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe pinned path {relative}")
        path = source_root / relative
        if not path.is_file():
            raise ValueError(f"pinned source file is missing: {relative}")
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != expected["bytes"]:
            raise ValueError(f"byte-count mismatch for {relative}: {size} != {expected['bytes']}")
        if digest != expected["sha256"]:
            raise ValueError(f"SHA-256 mismatch for {relative}")
        validated.append(
            {
                "path": relative.as_posix(),
                "bytes": size,
                "sha256": digest,
                "role": expected["role"],
                "validation": "match",
            }
        )
    return validated


def read_trials(source_root: Path) -> list[dict[str, str]]:
    with (source_root / "trials.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != TRIAL_COLUMNS:
            raise ValueError(f"trials.csv columns must be exactly {TRIAL_COLUMNS}")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if [(row["run_id"], row["treatment"]) for row in rows] != [
        ("S01A", "direct_write"),
        ("S01B", "setpoint_override"),
    ]:
        raise ValueError("committed completed treatments must be S01A/direct_write then S01B/setpoint_override")
    if any(row["treatment"] == "ttl_override" for row in rows):
        raise ValueError("TTL treatment must remain not_run in the committed evidence")
    if any(row["ttl_seconds"] for row in rows):
        raise ValueError("completed rows must not imply TTL execution")
    return rows


def _first(samples: list[dict[str, Any]], predicate: Any, label: str) -> dict[str, Any]:
    for sample in samples:
        if predicate(sample):
            return sample
    raise ValueError(f"required sample not found: {label}")


def validate_observations(source_root: Path, trials: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_run = {row["run_id"]: row for row in trials}
    samples_a = read_json(source_root / "events" / "S01A" / "samples.json")
    samples_b = read_json(source_root / "events" / "S01B" / "samples.json")
    if not isinstance(samples_a, list) or not samples_a:
        raise ValueError("S01A samples must be a non-empty JSON array")
    if not isinstance(samples_b, list) or not samples_b:
        raise ValueError("S01B samples must be a non-empty JSON array")

    direct = _first(samples_a, lambda item: item.get("dep_spec") == 24, "S01A direct desired-state write")
    reverted = _first(
        samples_a,
        lambda item: item.get("dt", -1) > direct["dt"] and item.get("dep_spec") == 15,
        "S01A owned target field overwritten to 15",
    )
    if any(item.get("hpa_max") != 15 for item in samples_a):
        raise ValueError("S01A controller input endpoint must remain maxReplicas=15")
    if any(item.get("desired") != 15 for item in samples_a):
        raise ValueError("S01A controller decision endpoint must remain desiredReplicas=15")
    if by_run["S01A"]["hpa_max_before"] != "15":
        raise ValueError("S01A hpa_max_before must be 15")

    changed_input = _first(samples_b, lambda item: item.get("hpa_max") == 30, "S01B changed controller input")
    changed_decision = _first(
        samples_b, lambda item: item.get("desired") == 30, "S01B changed controller decision"
    )
    changed_target = _first(
        samples_b, lambda item: item.get("dep_spec") == 30, "S01B changed owned target field"
    )
    observed_ready = _first(
        samples_b, lambda item: item.get("dep_ready") == 30, "S01B observed workload state"
    )
    if by_run["S01B"]["hpa_max_before"] != "15":
        raise ValueError("S01B pre-intervention controller input must be 15")

    return [
        {
            "run_id": "S01A",
            "treatment": "direct_write",
            "status": "completed",
            "completed_runs_n": 1,
            "execution_order": 1,
            "evidence_class": "single_environment_mechanism_demonstration",
            "controller_input_value_before": 15,
            "controller_input_value_after": 15,
            "controller_decision_value_observed": 15,
            "owned_target_field_intervention_value": 24,
            "owned_target_field_later_value": 15,
            "direct_write_sample_dt_seconds": direct["dt"],
            "later_target_sample_dt_seconds": reverted["dt"],
            "mechanism_observation": (
                "The active controller overwrote the direct desired-state write in this recorded run."
            ),
            "limits": (
                "One sequential run; no typical timing, oscillation-rate, safety, user-outcome, "
                "or production inference."
            ),
        },
        {
            "run_id": "S01B",
            "treatment": "setpoint_override",
            "status": "completed",
            "completed_runs_n": 1,
            "execution_order": 2,
            "evidence_class": "single_environment_mechanism_demonstration",
            "controller_input_value_before": 15,
            "controller_input_value_after": 30,
            "controller_input_change_sample_dt_seconds": changed_input["dt"],
            "controller_decision_value_observed": 30,
            "controller_decision_sample_dt_seconds": changed_decision["dt"],
            "owned_target_field_value_observed": 30,
            "owned_target_field_sample_dt_seconds": changed_target["dt"],
            "observed_workload_state_value": 30,
            "observed_workload_state_sample_dt_seconds": observed_ready["dt"],
            "mechanism_observation": (
                "Changing the active controller's configuration changed the governed state in this recorded run."
            ),
            "limits": (
                "One sequential run; no superiority, stability, safety, user-outcome, or production inference."
            ),
        },
        {
            "run_id": "NOT-RUN",
            "treatment": "ttl_override",
            "status": "not_run",
            "completed_runs_n": 0,
            "execution_order": None,
            "evidence_class": "no_observation",
            "mechanism_observation": "No completed TTL treatment exists in the committed evidence.",
            "limits": "No TTL cleanup or automatic rollback claim is supported.",
        },
    ]


def table_rows(observations: list[dict[str, Any]], endpoints: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in observations:
        rows.append(
            {
                "run_id": item["run_id"],
                "treatment": item["treatment"],
                "status": item["status"],
                "execution_order": item["execution_order"] if item["execution_order"] is not None else "",
                "completed_runs_n": item["completed_runs_n"],
                "evidence_class": item["evidence_class"],
                "controller_input_endpoint": endpoints["controller_input"],
                "controller_decision_endpoint": endpoints["controller_decision"],
                "owned_target_field_endpoint": endpoints["owned_target_field"],
                "observed_workload_state_endpoint": endpoints["observed_workload_state"],
                "mechanism_observation": item["mechanism_observation"],
                "limits": item["limits"],
            }
        )
    return rows


def write_table(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def render_report(observations: list[dict[str, Any]], endpoints: dict[str, str]) -> str:
    lines = [
        "# K8S-01 Committed-Evidence Report",
        "",
        "> Observed once in the stated test environment; mechanism demonstration only.",
        "> The default command reads committed files and does not create a cluster or execute a treatment.",
        "",
        "## Exact endpoints",
        "",
        f"- Controller input: `{endpoints['controller_input']}`",
        f"- Controller decision: `{endpoints['controller_decision']}`",
        f"- Owned target field: `{endpoints['owned_target_field']}`",
        f"- Observed workload state: `{endpoints['observed_workload_state']}`",
        "",
        "## Recorded treatments",
        "",
        "| Run | Treatment | Status | Independent unit | Observation |",
        "|---|---|---|---|---|",
    ]
    for item in observations:
        unit = (
            "one sequential run in one disposable configuration"
            if item["completed_runs_n"] == 1
            else "no completed run"
        )
        lines.append(
            f"| `{item['run_id']}` | `{item['treatment']}` | `{item['status']}` | "
            f"{unit} | {item['mechanism_observation']} |"
        )
    lines.extend(
        [
            "",
            "The two completed treatments were run sequentially, not randomized or replicated.",
            "The legacy summary's combined timing and oscillation columns are retained as raw",
            "record fields but are not used for a comparative, frequency, convergence, or safety claim.",
            "",
            "## Unsupported inferences",
            "",
            *[f"- {claim}" for claim in DISALLOWED_CLAIMS],
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(observations: list[dict[str, Any]], endpoints: dict[str, str]) -> str:
    first, second, ttl = observations
    esc = html.escape
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="960" viewBox="0 0 1200 960" role="img" aria-labelledby="title desc">
  <title id="title">K8S-01 recorded controller-ownership mechanism</title>
  <desc id="desc">Two separate panels show one sequential direct-write run and one sequential controller-setpoint run in one disposable configuration. The direct desired-state write was overwritten by the active controller in S01A. The controller input change was followed by a changed controller decision and governed field in S01B. A third TTL treatment is explicitly marked not run. No comparison, safety, or production claim is made.</desc>
  <defs>
    <marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#315D7D"/></marker>
    <marker id="arrow-orange" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#C65D21"/></marker>
    <style>
      .title {{font:700 32px Arial,Helvetica,sans-serif;fill:#17324D}}
      .subtitle {{font:18px Arial,Helvetica,sans-serif;fill:#455A64}}
      .panel-title {{font:700 23px Arial,Helvetica,sans-serif;fill:#17324D}}
      .node-title {{font:700 18px Arial,Helvetica,sans-serif;fill:#17324D}}
      .body {{font:16px Arial,Helvetica,sans-serif;fill:#344B58}}
      .small {{font:15px Arial,Helvetica,sans-serif;fill:#455A64}}
      .white-title {{font:700 20px Arial,Helvetica,sans-serif;fill:#FFFFFF}}
      .white-body {{font:16px Arial,Helvetica,sans-serif;fill:#EAF3F7}}
      .warn-title {{font:700 20px Arial,Helvetica,sans-serif;fill:#7A3714}}
      .warn-body {{font:16px Arial,Helvetica,sans-serif;fill:#6A4634}}
    </style>
  </defs>
  <rect x="1" y="1" width="1198" height="958" rx="18" fill="#F8FAFB" stroke="#D7DEE3" stroke-width="2"/>
  <text x="50" y="52" class="title">One run can expose the ownership mechanism</text>
  <text x="50" y="83" class="subtitle">K8S-01 — n = 1 sequential run per completed treatment; one disposable configuration; mechanism evidence only.</text>

  <g>
    <rect x="50" y="120" width="1100" height="286" rx="16" fill="#FFFFFF" stroke="#A8BBC7" stroke-width="2"/>
    <rect x="50" y="120" width="1100" height="52" rx="16" fill="#EAF2F7"/>
    <text x="80" y="154" class="panel-title">S01A  DIRECT WRITE  •  COMPLETED  •  n = {first['completed_runs_n']}</text>
    <path d="M350 277 H440 M730 277 H820" stroke="#C65D21" stroke-width="4" fill="none" marker-end="url(#arrow-orange)"/>
    <rect x="80" y="195" width="270" height="170" rx="12" fill="#FFF3EA" stroke="#D99A71" stroke-width="2"/>
    <text x="100" y="226" class="node-title">Direct desired-state write</text>
    <text x="100" y="254" class="body">Deployment/cpu-svc</text>
    <text x="100" y="278" class="body">.spec.replicas</text>
    <text x="100" y="306" class="body">observed: 24 at dt={first['direct_write_sample_dt_seconds']:.2f}s</text>
    <text x="100" y="338" class="small">Foreign write to owned field</text>
    <rect x="440" y="195" width="290" height="170" rx="12" fill="#EAF2F7" stroke="#7E9DB0" stroke-width="2"/>
    <text x="460" y="226" class="node-title">Active controller remains at 15</text>
    <text x="460" y="252" class="small">HorizontalPodAutoscaler/cpu-svc</text>
    <text x="460" y="275" class="body">.spec.maxReplicas = 15</text>
    <text x="460" y="301" class="small">HorizontalPodAutoscaler/cpu-svc</text>
    <text x="460" y="324" class="body">.status.desiredReplicas = 15</text>
    <text x="460" y="349" class="small">Controller stays active</text>
    <rect x="820" y="195" width="300" height="170" rx="12" fill="#17324D"/>
    <text x="840" y="226" class="white-title">Owned field later reads 15</text>
    <text x="840" y="254" class="white-body">Deployment/cpu-svc</text>
    <text x="840" y="278" class="white-body">.spec.replicas</text>
    <text x="840" y="306" class="white-body">observed at dt={first['later_target_sample_dt_seconds']:.2f}s</text>
    <text x="840" y="338" class="white-body">Overwritten in this run</text>
    <text x="80" y="390" class="small">No typical reconcile time or oscillation frequency follows from one run.</text>
  </g>

  <g>
    <rect x="50" y="432" width="1100" height="286" rx="16" fill="#FFFFFF" stroke="#A8BBC7" stroke-width="2"/>
    <rect x="50" y="432" width="1100" height="52" rx="16" fill="#EAF2F7"/>
    <text x="80" y="466" class="panel-title">S01B  CONTROLLER SETPOINT  •  COMPLETED  •  n = {second['completed_runs_n']}</text>
    <path d="M350 589 H440 M730 589 H820" stroke="#315D7D" stroke-width="4" fill="none" marker-end="url(#arrow-blue)"/>
    <rect x="80" y="505" width="270" height="170" rx="12" fill="#EAF2F7" stroke="#7E9DB0" stroke-width="2"/>
    <text x="100" y="536" class="node-title">Controller input changed</text>
    <text x="100" y="564" class="small">HorizontalPodAutoscaler/cpu-svc</text>
    <text x="100" y="588" class="body">.spec.maxReplicas</text>
    <text x="100" y="616" class="body">15 before; 30 after</text>
    <text x="100" y="648" class="small">Change enters through owner</text>
    <rect x="440" y="505" width="290" height="170" rx="12" fill="#EAF2F7" stroke="#7E9DB0" stroke-width="2"/>
    <text x="460" y="536" class="node-title">Controller decision changed</text>
    <text x="460" y="564" class="small">HorizontalPodAutoscaler/cpu-svc</text>
    <text x="460" y="588" class="body">.status.desiredReplicas</text>
    <text x="460" y="616" class="body">observed: 30 at dt={second['controller_decision_sample_dt_seconds']:.2f}s</text>
    <text x="460" y="648" class="small">Controller decision endpoint</text>
    <rect x="820" y="505" width="300" height="170" rx="12" fill="#17324D"/>
    <text x="840" y="536" class="white-title">Governed field changed</text>
    <text x="840" y="560" class="white-body">Deployment/cpu-svc</text>
    <text x="840" y="583" class="white-body">.spec.replicas = 30</text>
    <text x="840" y="608" class="white-body">Deployment/cpu-svc</text>
    <text x="840" y="631" class="white-body">.status.readyReplicas = 30</text>
    <text x="840" y="656" class="white-body">Mechanism observation in this run</text>
    <text x="80" y="702" class="small">No superiority, stability, safety, user-outcome, or production inference is made.</text>
  </g>

  <g>
    <rect x="50" y="744" width="1100" height="88" rx="14" fill="#FFF3EA" stroke="#D99A71" stroke-width="2"/>
    <text x="80" y="778" class="warn-title">TTL OVERRIDE  •  NOT RUN  •  n = {ttl['completed_runs_n']}</text>
    <text x="80" y="807" class="warn-body">No completed TTL record exists. This evidence supports no automatic-cleanup or rollback claim.</text>
  </g>

  <g>
    <rect x="50" y="855" width="1100" height="70" rx="14" fill="#17324D"/>
    <text x="600" y="884" text-anchor="middle" class="white-title">SUPPORTED BOUNDARY</text>
    <text x="600" y="910" text-anchor="middle" class="white-body">Controller ownership mechanism observed once per completed treatment; no comparative, safety, or production claim.</text>
  </g>
</svg>
'''


def generate(
    source_root: Path = SOURCE_ROOT,
    pins_path: Path = PINS_PATH,
    manifest_path: Path = OUTPUT_MANIFEST,
    table_path: Path = OUTPUT_TABLE,
    report_path: Path = OUTPUT_REPORT,
    figure_path: Path = OUTPUT_FIGURE,
) -> None:
    pins = read_json(pins_path)
    validated_files = validate_pins(source_root, pins)
    endpoints = pins.get("endpoint_definitions", {})
    if tuple(endpoints) != ENDPOINT_KEYS:
        raise ValueError(f"endpoint definitions must appear as {ENDPOINT_KEYS}")
    trials = read_trials(source_root)
    observations = validate_observations(source_root, trials)
    declared = pins.get("declared_treatments")
    observed_status = [
        {
            "treatment": item["treatment"],
            "run_id": None if item["run_id"] == "NOT-RUN" else item["run_id"],
            "status": item["status"],
            "completed_runs_n": item["completed_runs_n"],
            "execution_order": item["execution_order"],
        }
        for item in observations
    ]
    if observed_status != declared:
        raise ValueError("declared treatment status does not match committed records")

    rows = table_rows(observations, endpoints)
    manifest = {
        "manifest_version": "ch06-k8s01-render-1",
        "artifact_class": "single_environment_mechanism_demonstration",
        "default_mode": "read_only_committed_evidence",
        "command": "make ch06-k8s-mechanism",
        "source_manifest_version": pins["manifest_version"],
        "independent_unit": "one run in one disposable configuration",
        "execution_design": "S01A then S01B sequentially; not randomized; not replicated",
        "endpoint_definitions": endpoints,
        "treatments": observed_status,
        "source_files": validated_files,
        "observations": observations,
        "legacy_fields_not_used_for_inference": [
            "time_to_first_reconcile_s",
            "time_to_revert_or_converge_s",
            "oscillation_count",
        ],
        "supported_claim": (
            "In S01A the active controller overwrote a direct desired-state write; in S01B "
            "changing the active controller configuration changed the governed state. "
            "Each statement is limited to its one recorded run."
        ),
        "unsupported_claims": DISALLOWED_CLAIMS,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_table(rows, table_path)
    report_path.write_text(render_report(observations, endpoints), encoding="utf-8")
    figure_path.write_text(render_svg(observations, endpoints), encoding="utf-8")
    for path in (manifest_path, table_path, report_path, figure_path):
        print(f"wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--pins", type=Path, default=PINS_PATH)
    parser.add_argument("--manifest", type=Path, default=OUTPUT_MANIFEST)
    parser.add_argument("--table", type=Path, default=OUTPUT_TABLE)
    parser.add_argument("--report", type=Path, default=OUTPUT_REPORT)
    parser.add_argument("--figure", type=Path, default=OUTPUT_FIGURE)
    args = parser.parse_args()
    generate(args.source_root, args.pins, args.manifest, args.table, args.report, args.figure)


if __name__ == "__main__":
    main()
