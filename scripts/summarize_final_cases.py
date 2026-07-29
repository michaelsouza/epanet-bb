#!/usr/bin/env python3
"""Audit the final solver campaign and export a compact reusable summary."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


PRUNE_REASONS = (
    "ACTUATIONS",
    "COST",
    "LEVELS",
    "TANK_SATURATION",
    "PRESSURES",
    "STABILITY",
    "TIMESTEP",
    "NONE",
)
PRUNE_GROUPS = {
    "Actuation": ("ACTUATIONS",),
    "Cost bound": ("COST",),
    "Tank levels": ("LEVELS", "TANK_SATURATION"),
    "Pressure": ("PRESSURES",),
}


class AuditError(RuntimeError):
    """Raised when campaign evidence is incomplete or inconsistent."""


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise AuditError(f"missing required artifact: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def finite_cost(payload: dict) -> float | None:
    value = payload.get("best_cost")
    if (
        isinstance(value, (int, float))
        and math.isfinite(value)
        and abs(float(value)) < 1e100
    ):
        return float(value)
    return None


def command_option(command: list[str], option: str) -> str:
    try:
        return command[command.index(option) + 1]
    except (ValueError, IndexError) as exc:
        raise AuditError(f"missing {option} in solver command") from exc


def expected_configuration(experiment: dict, process_count: int) -> dict:
    command = experiment.get("command", [])
    return {
        "np": process_count,
        "hours": int(command_option(command, "-h")),
        "actuations": int(command_option(command, "-a")),
        "level": int(command_option(command, "-l")),
        "sync_interval": int(command_option(command, "-s")),
    }


def validate_schedule(best: dict, configuration: dict, case_id: str) -> None:
    hours = configuration["hours"]
    best_x = best.get("best_x")
    best_y = best.get("best_y")
    if not isinstance(best_x, list) or not isinstance(best_y, list):
        raise AuditError(f"{case_id}: missing best_x or best_y")
    if len(best_y) != hours + 1:
        raise AuditError(f"{case_id}: expected {hours + 1} aggregated decisions")
    if len(best_x) % (hours + 1) != 0:
        raise AuditError(f"{case_id}: binary schedule length is incompatible")
    pump_count = len(best_x) // (hours + 1)
    if pump_count <= 0:
        raise AuditError(f"{case_id}: binary schedule has no pumps")
    for hour, expected_active in enumerate(best_y):
        start = hour * pump_count
        observed_active = sum(int(value) for value in best_x[start : start + pump_count])
        if observed_active != int(expected_active):
            raise AuditError(
                f"{case_id}: binary and aggregated schedules differ at hour {hour}"
            )


def audit_case(
    final_cases: Path,
    execution: dict,
    plan_experiment: dict,
    process_count: int,
    executable_sha256: str,
) -> dict:
    configuration = expected_configuration(plan_experiment, process_count)
    actuations = configuration["actuations"]
    case_id = f"actuations-{actuations:02d}"
    if execution.get("actuations") != actuations:
        raise AuditError(f"{case_id}: receipt order differs from execution plan")
    if execution.get("return_code") != 0:
        raise AuditError(f"{case_id}: solver returned {execution.get('return_code')}")

    outputs = final_cases / case_id / "outputs"
    stats_paths = sorted(outputs.glob("*_stats.json"))
    best_paths = sorted(outputs.glob("*_best.json"))
    if len(stats_paths) != process_count or len(best_paths) != process_count:
        raise AuditError(
            f"{case_id}: expected {process_count} stats and best files, "
            f"found {len(stats_paths)} and {len(best_paths)}"
        )

    rank_times = []
    candidates = 0
    tasks = 0
    prune_counts = {reason: 0 for reason in PRUNE_REASONS}
    for path in stats_paths:
        stats = load_json(path)
        if stats.get("search", {}).get("status") != "CONCLUSIVE":
            raise AuditError(f"{case_id}: inconclusive stats artifact {path.name}")
        metadata = stats.get("metadata", {})
        observed_configuration = metadata.get("configuration", {})
        observed = {
            "np": int(metadata.get("mpi_processes", -1)),
            "hours": int(observed_configuration.get("horizon_hours", -1)),
            "actuations": int(
                observed_configuration.get("max_cycles_per_pump", -1)
            ),
            "level": int(
                observed_configuration.get("task_decomposition_level", -1)
            ),
            "sync_interval": int(
                observed_configuration.get("sync_interval", -1)
            ),
        }
        if observed != configuration:
            raise AuditError(
                f"{case_id}: artifact configuration {observed} differs from "
                f"{configuration}"
            )
        artifact_hash = metadata.get("software", {}).get("executable_sha256")
        if artifact_hash != executable_sha256:
            raise AuditError(f"{case_id}: executable hash mismatch in {path.name}")
        rank_times.append(float(stats["time_total"]))
        tasks += int(stats.get("tasks_processed", 0))
        candidates += int(
            stats.get("disaggregation_summary", {}).get("candidate_assignments", 0)
        )
        for reason in PRUNE_REASONS:
            values = stats.get(reason)
            if not isinstance(values, list):
                raise AuditError(f"{case_id}: missing pruning reason {reason}")
            prune_counts[reason] += sum(int(value) for value in values)

    best_candidates = []
    for path in best_paths:
        best = load_json(path)
        if best.get("search_status") != "CONCLUSIVE":
            raise AuditError(f"{case_id}: inconclusive best artifact {path.name}")
        cost = finite_cost(best)
        if cost is not None:
            best_candidates.append((cost, best, path.name))
    if not best_candidates:
        raise AuditError(f"{case_id}: no finite best cost")
    best_cost, best, best_filename = min(best_candidates, key=lambda item: item[0])
    validate_schedule(best, configuration, case_id)

    average_rank_seconds = sum(rank_times) / len(rank_times)
    maximum_rank_seconds = max(rank_times)
    imbalance = (
        (maximum_rank_seconds - average_rank_seconds) / average_rank_seconds
        if average_rank_seconds > 0
        else 0.0
    )
    total_nodes = sum(prune_counts.values())
    if total_nodes <= 0:
        raise AuditError(f"{case_id}: pruning counters are empty")
    pruning_percentages = {
        label: 100.0
        * sum(prune_counts[reason] for reason in reasons)
        / total_nodes
        for label, reasons in PRUNE_GROUPS.items()
    }
    pruning_percentages["Total pruned"] = (
        100.0 * (total_nodes - prune_counts["NONE"]) / total_nodes
    )
    pruning_percentages["Feasible"] = 100.0 * prune_counts["NONE"] / total_nodes

    return {
        "actuations": actuations,
        "configuration": configuration,
        "wall_seconds": float(execution["duration_seconds"]),
        "average_rank_seconds": average_rank_seconds,
        "maximum_rank_seconds": maximum_rank_seconds,
        "load_imbalance_factor": imbalance,
        "candidate_assignments": candidates,
        "tasks_processed": tasks,
        "stats_files": len(stats_paths),
        "best_files": len(best_paths),
        "global_best_cost": best_cost,
        "best_artifact": best_filename,
        "best_x": best["best_x"],
        "best_y": best["best_y"],
        "best_canonical_x": best.get("best_canonical_x"),
        "pruning_counts": prune_counts,
        "pruning_percentages": pruning_percentages,
        "nodes_total": total_nodes,
    }


def summarize_campaign(campaign: Path) -> dict:
    campaign = campaign.absolute()
    campaign_plan = load_json(campaign / "campaign-plan.json")
    campaign_results = load_json(campaign / "campaign-results.json")
    if campaign_results.get("status") != "complete":
        raise AuditError("campaign is not complete")
    git = campaign_plan.get("metadata", {}).get("git", {})
    if git.get("dirty") is not False:
        raise AuditError("campaign did not record a clean Git tree")
    tasks = campaign_plan.get("tasks", [])
    result_tasks = campaign_results.get("tasks", [])
    if len(tasks) != 1 or tasks[0].get("id") != "final-cases":
        raise AuditError("campaign does not contain exactly one final-cases task")
    if len(result_tasks) != 1 or result_tasks[0].get("return_codes") != [0]:
        raise AuditError("campaign receipt is incomplete or unsuccessful")
    commands = tasks[0].get("commands", [])
    if len(commands) != 1:
        raise AuditError("final-cases task must contain one runner command")

    final_cases = campaign / "final-cases"
    execution_plan = load_json(final_cases / "execution-plan.json")
    execution_results = load_json(final_cases / "execution-results.json")
    if execution_results.get("status") != "complete":
        raise AuditError("final-cases execution is not complete")
    plan_experiments = execution_plan.get("experiments", [])
    executions = execution_results.get("experiments", [])
    if len(plan_experiments) != 3 or len(executions) != 3:
        raise AuditError("expected exactly three final cases")
    process_count = int(execution_plan["process_count"]["value"])
    if process_count != int(commands[0]["np"]):
        raise AuditError("process count differs between campaign and execution plans")
    if [item.get("actuations") for item in plan_experiments] != [1, 2, 3]:
        raise AuditError("expected final cases in actuation order 1, 2, 3")
    executable_sha256 = campaign_plan["metadata"]["executable"]["sha256"]

    cases = [
        audit_case(
            final_cases,
            execution,
            plan_experiment,
            process_count,
            executable_sha256,
        )
        for execution, plan_experiment in zip(executions, plan_experiments)
    ]
    reference = {
        key: value
        for key, value in cases[0]["configuration"].items()
        if key != "actuations"
    }
    for case in cases[1:]:
        observed = {
            key: value
            for key, value in case["configuration"].items()
            if key != "actuations"
        }
        if observed != reference:
            raise AuditError("final cases used different common configurations")

    return {
        "schema_version": 1,
        "campaign": campaign.name,
        "git": git,
        "compatibility_sha256": campaign_plan["compatibility_sha256"],
        "executable_sha256": executable_sha256,
        "campaign_duration_seconds": float(result_tasks[0]["duration_seconds"]),
        "configuration": reference,
        "cases": cases,
    }


def write_csv(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "actuations",
        "global_best_cost",
        "wall_seconds",
        "average_rank_seconds",
        "maximum_rank_seconds",
        "load_imbalance_factor",
        "candidate_assignments",
        "tasks_processed",
        "nodes_total",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for case in summary["cases"]:
            writer.writerow({key: case[key] for key in fields})


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = summarize_campaign(arguments.campaign_dir)
    except (AuditError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"final-cases audit failed: {exc}")
        return 1
    arguments.output_json.parent.mkdir(parents=True, exist_ok=True)
    arguments.output_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(summary, arguments.output_csv)
    print(f"audited {len(summary['cases'])} final cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
