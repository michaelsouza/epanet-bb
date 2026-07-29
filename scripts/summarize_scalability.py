#!/usr/bin/env python3
"""Audit replicated scalability campaigns and export stable summaries."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median


class AuditError(RuntimeError):
    """Raised when campaign evidence is incomplete or incompatible."""


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise AuditError(f"missing required artifact: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def option_value(argv: list[str], option: str) -> str:
    try:
        return argv[argv.index(option) + 1]
    except (ValueError, IndexError) as exc:
        raise AuditError(f"missing {option} in command: {argv}") from exc


def command_signature(command: dict) -> dict:
    argv = command["argv"]
    actuations_start = argv.index("--actuations") + 1
    actuations_end = argv.index("--level")
    return {
        "np": int(command["np"]),
        "hours": int(option_value(argv, "--hours")),
        "actuations": [int(value) for value in argv[actuations_start:actuations_end]],
        "level": int(option_value(argv, "--level")),
        "sync_interval": int(option_value(argv, "--sync-interval")),
    }


def point_directory(campaign: Path, command: dict) -> Path:
    declared = Path(command["output_dir"])
    if declared.is_dir():
        return declared
    return campaign / "scalability" / declared.name


def audit_point(
    campaign: Path,
    command: dict,
    expected_executable_sha256: str,
) -> dict:
    signature = command_signature(command)
    process_count = signature["np"]
    point_id = f"np-{process_count:03d}"
    directory = point_directory(campaign, command)
    execution = load_json(directory / "execution-results.json")
    experiments = execution.get("experiments", [])
    if execution.get("status") != "complete" or len(experiments) != 1:
        raise AuditError(f"{point_id}: execution is not complete")
    experiment = experiments[0]
    if experiment.get("return_code") != 0:
        raise AuditError(f"{point_id}: solver returned {experiment.get('return_code')}")
    if signature["actuations"] != [2]:
        raise AuditError(f"{point_id}: expected exactly NA_max=2")

    outputs = directory / "actuations-02" / "outputs"
    stats_paths = sorted(outputs.glob("*_stats.json"))
    best_paths = sorted(outputs.glob("*_best.json"))
    if len(stats_paths) != process_count or len(best_paths) != process_count:
        raise AuditError(
            f"{point_id}: expected {process_count} stats and best files, "
            f"found {len(stats_paths)} and {len(best_paths)}"
        )

    rank_times = []
    candidate_assignments = 0
    tasks_processed = 0
    for path in stats_paths:
        stats = load_json(path)
        if stats.get("search", {}).get("status") != "CONCLUSIVE":
            raise AuditError(f"{point_id}: inconclusive stats artifact {path.name}")
        metadata = stats.get("metadata", {})
        configuration = metadata.get("configuration", {})
        observed = {
            "np": int(metadata.get("mpi_processes", -1)),
            "hours": int(configuration.get("horizon_hours", -1)),
            "actuations": [int(configuration.get("max_cycles_per_pump", -1))],
            "level": int(configuration.get("task_decomposition_level", -1)),
            "sync_interval": int(configuration.get("sync_interval", -1)),
        }
        if observed != signature:
            raise AuditError(
                f"{point_id}: artifact configuration {observed} differs from {signature}"
            )
        artifact_sha256 = metadata.get("software", {}).get("executable_sha256")
        if artifact_sha256 != expected_executable_sha256:
            raise AuditError(f"{point_id}: executable hash mismatch in {path.name}")
        rank_times.append(float(stats["time_total"]))
        candidate_assignments += int(
            stats.get("disaggregation_summary", {}).get("candidate_assignments", 0)
        )
        tasks_processed += int(stats.get("tasks_processed", 0))

    costs = []
    for path in best_paths:
        best = load_json(path)
        if best.get("search_status") != "CONCLUSIVE":
            raise AuditError(f"{point_id}: inconclusive best artifact {path.name}")
        cost = best.get("best_cost")
        if (
            isinstance(cost, (int, float))
            and math.isfinite(cost)
            and abs(float(cost)) < 1e100
        ):
            costs.append(float(cost))
    if not costs:
        raise AuditError(f"{point_id}: no finite best cost")

    average_rank_seconds = sum(rank_times) / len(rank_times)
    maximum_rank_seconds = max(rank_times)
    imbalance = (
        (maximum_rank_seconds - average_rank_seconds) / average_rank_seconds
        if average_rank_seconds > 0
        else 0.0
    )
    return {
        "id": point_id,
        "environment": dict(command.get("environment", {})),
        "configuration": signature,
        "wall_seconds": float(experiment["duration_seconds"]),
        "average_rank_seconds": average_rank_seconds,
        "maximum_rank_seconds": maximum_rank_seconds,
        "load_imbalance_factor": imbalance,
        "candidate_assignments": candidate_assignments,
        "tasks_processed": tasks_processed,
        "stats_files": len(stats_paths),
        "best_files": len(best_paths),
        "global_best_cost": min(costs),
    }


def audit_campaign(campaign: Path) -> dict:
    plan = load_json(campaign / "campaign-plan.json")
    receipt = load_json(campaign / "campaign-results.json")
    if receipt.get("status") != "complete":
        raise AuditError(f"campaign is not complete: {campaign}")
    git = plan.get("metadata", {}).get("git", {})
    if git.get("dirty") is not False:
        raise AuditError(f"campaign did not record a clean Git tree: {campaign}")
    tasks = plan.get("tasks", [])
    if len(tasks) != 1 or tasks[0].get("id") != "scalability":
        raise AuditError(
            f"campaign does not contain one scalability task: {campaign}"
        )
    commands = tasks[0].get("commands", [])
    result_tasks = receipt.get("tasks", [])
    if len(result_tasks) != 1:
        raise AuditError(f"campaign receipt has an invalid task count: {campaign}")
    if result_tasks[0].get("return_codes") != [0] * len(commands):
        raise AuditError(f"campaign has unsuccessful commands: {campaign}")

    executable_sha256 = plan["metadata"]["executable"]["sha256"]
    return {
        "campaign": campaign.name,
        "git": git,
        "executable_sha256": executable_sha256,
        "compatibility_sha256": plan["compatibility_sha256"],
        "duration_seconds": float(result_tasks[0]["duration_seconds"]),
        "points": [
            audit_point(campaign, command, executable_sha256)
            for command in commands
        ],
    }


def summarize_campaigns(campaigns: list[Path]) -> dict:
    if len(campaigns) < 3 or len(campaigns) % 2 == 0:
        raise AuditError("an odd number of at least three campaigns is required")
    audited = [audit_campaign(path.absolute()) for path in campaigns]
    executable_hashes = {item["executable_sha256"] for item in audited}
    if len(executable_hashes) != 1:
        raise AuditError("campaigns used different executables")
    commits = {item["git"].get("commit") for item in audited}
    if len(commits) != 1:
        raise AuditError("campaigns used different Git commits")

    orders = [[point["configuration"]["np"] for point in item["points"]] for item in audited]
    if any(order != orders[0] for order in orders[1:]):
        raise AuditError("campaigns used different process-count orders")
    if not orders[0] or orders[0][0] != 1:
        raise AuditError("the first scalability point must use one process")
    if len(set(orders[0])) != len(orders[0]):
        raise AuditError("process counts must be unique")

    by_round = [
        {point["configuration"]["np"]: point for point in campaign["points"]}
        for campaign in audited
    ]
    baseline_times = [round_[1]["wall_seconds"] for round_ in by_round]
    reference_configuration = {
        key: value
        for key, value in by_round[0][1]["configuration"].items()
        if key != "np"
    }
    reference_cost = by_round[0][1]["global_best_cost"]
    reference_tasks = by_round[0][1]["tasks_processed"]

    points = []
    for process_count in orders[0]:
        repetitions = []
        environments = []
        for number, (campaign, round_, baseline_seconds) in enumerate(
            zip(audited, by_round, baseline_times), start=1
        ):
            observed = round_[process_count]
            configuration = {
                key: value
                for key, value in observed["configuration"].items()
                if key != "np"
            }
            if configuration != reference_configuration:
                raise AuditError(
                    f"np={process_count}: configuration differs between points or rounds"
                )
            if not math.isclose(
                observed["global_best_cost"], reference_cost, rel_tol=1e-12
            ):
                raise AuditError(f"np={process_count}: global best cost differs")
            if observed["tasks_processed"] != reference_tasks:
                raise AuditError(f"np={process_count}: total task count differs")
            environments.append(observed["environment"])
            repetitions.append(
                {
                    "number": number,
                    "campaign": campaign["campaign"],
                    **{
                        key: value
                        for key, value in observed.items()
                        if key not in {"id", "environment", "configuration"}
                    },
                    "paired_speedup": baseline_seconds / observed["wall_seconds"],
                    "paired_parallel_efficiency": (
                        baseline_seconds / observed["wall_seconds"] / process_count
                    ),
                }
            )
        if any(environment != environments[0] for environment in environments[1:]):
            raise AuditError(f"np={process_count}: environment differs between rounds")
        wall_times = [item["wall_seconds"] for item in repetitions]
        speedups = [item["paired_speedup"] for item in repetitions]
        efficiencies = [
            item["paired_parallel_efficiency"] for item in repetitions
        ]
        candidates = [item["candidate_assignments"] for item in repetitions]
        imbalances = [item["load_imbalance_factor"] for item in repetitions]
        average_rank_times = [item["average_rank_seconds"] for item in repetitions]
        maximum_rank_times = [item["maximum_rank_seconds"] for item in repetitions]
        points.append(
            {
                "process_count": process_count,
                "environment": environments[0],
                "repetitions": repetitions,
                "summary": {
                    "wall_seconds_median": median(wall_times),
                    "wall_seconds_minimum": min(wall_times),
                    "wall_seconds_maximum": max(wall_times),
                    "paired_speedup_median": median(speedups),
                    "paired_speedup_minimum": min(speedups),
                    "paired_speedup_maximum": max(speedups),
                    "paired_parallel_efficiency_median": median(efficiencies),
                    "candidate_assignments_median": median(candidates),
                    "load_imbalance_factor_median": median(imbalances),
                    "average_rank_seconds_median": median(average_rank_times),
                    "maximum_rank_seconds_median": median(maximum_rank_times),
                },
            }
        )

    return {
        "schema_version": 1,
        "repetition_count": len(audited),
        "configuration": reference_configuration,
        "global_best_cost": reference_cost,
        "tasks_processed_per_point": reference_tasks,
        "executable_sha256": audited[0]["executable_sha256"],
        "campaigns": [
            {key: value for key, value in item.items() if key != "points"}
            for item in audited
        ],
        "points": points,
    }


def write_csv(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repetitions = summary["repetition_count"]
    fields = ["process_count"] + [
        f"wall_seconds_rep_{number}" for number in range(1, repetitions + 1)
    ] + [
        "wall_seconds_median",
        "wall_seconds_minimum",
        "wall_seconds_maximum",
        "paired_speedup_median",
        "paired_speedup_minimum",
        "paired_speedup_maximum",
        "paired_parallel_efficiency_median",
        "candidate_assignments_median",
        "load_imbalance_factor_median",
        "average_rank_seconds_median",
        "maximum_rank_seconds_median",
        "tasks_processed_per_point",
        "global_best_cost",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for point in summary["points"]:
            row = {"process_count": point["process_count"]}
            for repetition in point["repetitions"]:
                row[f"wall_seconds_rep_{repetition['number']}"] = repetition[
                    "wall_seconds"
                ]
            row.update(point["summary"])
            row["tasks_processed_per_point"] = summary["tasks_processed_per_point"]
            row["global_best_cost"] = summary["global_best_cost"]
            writer.writerow(row)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", action="append", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = summarize_campaigns(arguments.campaign_dir)
    except (AuditError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"scalability audit failed: {exc}")
        return 1
    arguments.output_json.parent.mkdir(parents=True, exist_ok=True)
    arguments.output_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(summary, arguments.output_csv)
    print(
        f"audited {summary['repetition_count']} campaigns and "
        f"{len(summary['points'])} process counts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
