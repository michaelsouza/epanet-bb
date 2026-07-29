#!/usr/bin/env python3
"""Aggregate paired hydraulic-accuracy records without rerunning experiments."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics


class SummaryError(RuntimeError):
    """Raised when sensitivity records cannot be summarized."""


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise SummaryError(f"missing input: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def numeric(values: list) -> list[float]:
    return [
        float(value)
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]


def median(values: list) -> float | None:
    selected = numeric(values)
    return statistics.median(selected) if selected else None


def value_range(values: list) -> float | None:
    selected = numeric(values)
    return max(selected) - min(selected) if selected else None


def ratio(numerator, denominator) -> float | None:
    selected = numeric([numerator, denominator])
    if len(selected) != 2 or float(denominator) == 0.0:
        return None
    return float(numerator) / float(denominator)


def trace_differences(left_path: str | None, right_path: str | None) -> dict | None:
    if not left_path or not right_path:
        return None
    left = load_json(Path(left_path)).get("hydraulic", {})
    right = load_json(Path(right_path)).get("hydraulic", {})
    if not left.get("converged") or not right.get("converged"):
        return None
    left_trace = left.get("trace", [])
    right_trace = right.get("trace", [])
    if len(left_trace) != len(right_trace):
        return None
    maxima = {"pressure": 0.0, "flow": 0.0, "level": 0.0}
    for left_step, right_step in zip(left_trace, right_trace):
        if (
            left_step.get("time_seconds") != right_step.get("time_seconds")
            or left_step.get("hour") != right_step.get("hour")
        ):
            return None
        left_nodes = {record["id"]: record for record in left_step.get("nodes", [])}
        right_nodes = {record["id"]: record for record in right_step.get("nodes", [])}
        left_links = {record["id"]: record for record in left_step.get("links", [])}
        right_links = {record["id"]: record for record in right_step.get("links", [])}
        if set(left_nodes) != set(right_nodes) or set(left_links) != set(right_links):
            return None
        for node_id, left_node in left_nodes.items():
            right_node = right_nodes[node_id]
            maxima["pressure"] = max(
                maxima["pressure"],
                abs(float(left_node["pressure"]) - float(right_node["pressure"])),
            )
            if "level" in left_node and "level" in right_node:
                maxima["level"] = max(
                    maxima["level"],
                    abs(float(left_node["level"]) - float(right_node["level"])),
                )
        for link_id, left_link in left_links.items():
            maxima["flow"] = max(
                maxima["flow"],
                abs(float(left_link["flow"]) - float(right_links[link_id]["flow"])),
            )
    return maxima


def fixed_aggregate(records: list[dict]) -> list[dict]:
    by_pair = {
        (record["actuations"], record["repetition"], record["accuracy_id"]): record
        for record in records
    }
    groups = {}
    for record in records:
        groups.setdefault((record["actuations"], record["accuracy_id"]), []).append(record)
    rows = []
    for (actuations, accuracy_id), group in sorted(groups.items()):
        ratios = []
        launcher_ratios = []
        pressure_deltas = []
        flow_deltas = []
        level_deltas = []
        cost_deltas = []
        paired = 0
        for record in group:
            baseline = by_pair.get((actuations, record["repetition"], "1e-4"))
            if baseline is None:
                continue
            hydraulic_ratio = ratio(
                record.get("hydraulic_solve_seconds"),
                baseline.get("hydraulic_solve_seconds"),
            )
            launcher_ratio = ratio(
                record.get("duration_seconds"), baseline.get("duration_seconds")
            )
            differences = trace_differences(record.get("result"), baseline.get("result"))
            if hydraulic_ratio is not None:
                ratios.append(hydraulic_ratio)
            if launcher_ratio is not None:
                launcher_ratios.append(launcher_ratio)
            if differences is not None:
                paired += 1
                pressure_deltas.append(differences["pressure"])
                flow_deltas.append(differences["flow"])
                level_deltas.append(differences["level"])
                if numeric([record.get("cost"), baseline.get("cost")]):
                    cost_deltas.append(abs(record["cost"] - baseline["cost"]))
        rows.append(
            {
                "actuations": actuations,
                "accuracy_id": accuracy_id,
                "accuracy": group[0]["accuracy"],
                "records": len(group),
                "hydraulic_converged": sum(r.get("hydraulic_converged") is True for r in group),
                "feasible": sum(r.get("feasible") is True for r in group),
                "paired_complete_traces": paired,
                "cost_median": median([r.get("cost") for r in group]),
                "cost_range": value_range([r.get("cost") for r in group]),
                "hydraulic_seconds_median": median(
                    [r.get("hydraulic_solve_seconds") for r in group]
                ),
                "launcher_seconds_median": median([r.get("duration_seconds") for r in group]),
                "trials_total_median": median(
                    [r.get("hydraulic_trials_total") for r in group]
                ),
                "hydraulic_slowdown_vs_1e-4_median": median(ratios),
                "launcher_slowdown_vs_1e-4_median": median(launcher_ratios),
                "max_cost_delta_vs_1e-4": max(cost_deltas, default=None),
                "max_pressure_delta_vs_1e-4": max(pressure_deltas, default=None),
                "max_flow_delta_vs_1e-4": max(flow_deltas, default=None),
                "max_tank_level_delta_vs_1e-4": max(level_deltas, default=None),
            }
        )
    return rows


def optimization_aggregate(records: list[dict]) -> list[dict]:
    by_pair = {
        (record["actuations"], record["repetition"], record["accuracy_id"]): record
        for record in records
    }
    groups = {}
    for record in records:
        groups.setdefault((record["actuations"], record["accuracy_id"]), []).append(record)
    rows = []
    for (actuations, accuracy_id), group in sorted(groups.items()):
        conclusive = [record for record in group if record.get("conclusive") is True]
        paired_ratios = []
        for record in conclusive:
            baseline = by_pair.get((actuations, record["repetition"], "1e-4"))
            if baseline and baseline.get("conclusive") is True:
                observed = ratio(record.get("duration_seconds"), baseline.get("duration_seconds"))
                if observed is not None:
                    paired_ratios.append(observed)
        rows.append(
            {
                "actuations": actuations,
                "accuracy_id": accuracy_id,
                "accuracy": group[0]["accuracy"],
                "records": len(group),
                "conclusive": len(conclusive),
                "nonconclusive": sum(
                    not record.get("conclusive") and not record.get("timed_out")
                    for record in group
                ),
                "timed_out": sum(record.get("timed_out") is True for record in group),
                "wall_seconds_median": median(
                    [record.get("duration_seconds") for record in conclusive]
                ),
                "paired_slowdown_vs_1e-4_median": median(paired_ratios),
                "cost_median": median([record.get("best_cost") for record in conclusive]),
                "cost_range": value_range([record.get("best_cost") for record in conclusive]),
                "unique_schedules": len(
                    {record.get("schedule_sha256") for record in conclusive}
                ),
                "nodes_median": median([record.get("nodes_total") for record in conclusive]),
                "tasks_median": median([record.get("tasks_processed") for record in conclusive]),
                "candidate_assignments_median": median(
                    [record.get("candidate_assignments") for record in conclusive]
                ),
                "hydraulic_nonconvergence_events": sum(
                    int(record.get("hydraulic_nonconvergence_events", 0)) for record in group
                ),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summarize_records(records: list[dict], output_directory: Path) -> dict:
    fixed = fixed_aggregate([record for record in records if record["kind"] == "fixed"])
    optimization = optimization_aggregate(
        [record for record in records if record["kind"] == "optimization"]
    )
    payload = {
        "schema_version": 1,
        "fixed_schedule_aggregate": fixed,
        "optimization_aggregate": optimization,
    }
    (output_directory / "accuracy-sensitivity-aggregate.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(output_directory / "fixed-schedule-aggregate.csv", fixed)
    write_csv(output_directory / "optimization-aggregate.csv", optimization)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    arguments = parser.parse_args()
    campaign = arguments.campaign.absolute()
    try:
        summary = load_json(campaign / "accuracy-sensitivity-summary.json")
        records = summary.get("fixed_records", []) + summary.get("optimization_records", [])
        summarize_records(records, campaign)
    except (SummaryError, KeyError, TypeError, ValueError) as exc:
        print(f"accuracy sensitivity summary failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
