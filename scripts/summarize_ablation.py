#!/usr/bin/env python3
"""Audit replicated ablation campaigns and export stable summaries."""

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


def variant_directory(campaign: Path, command: dict) -> Path:
    declared = Path(command["output_dir"])
    if declared.is_dir():
        return declared
    return campaign / "ablation" / declared.name


def audit_variant(
    campaign: Path,
    command: dict,
    expected_executable_sha256: str,
) -> dict:
    variant = Path(command["output_dir"]).name
    directory = variant_directory(campaign, command)
    execution = load_json(directory / "execution-results.json")
    experiments = execution.get("experiments", [])
    if execution.get("status") != "complete" or len(experiments) != 1:
        raise AuditError(f"{variant}: execution is not complete")
    experiment = experiments[0]
    if experiment.get("return_code") != 0:
        raise AuditError(f"{variant}: solver returned {experiment.get('return_code')}")

    signature = command_signature(command)
    if signature["actuations"] != [3]:
        raise AuditError(f"{variant}: expected exactly NA_max=3")
    outputs = directory / "actuations-03" / "outputs"
    stats_paths = sorted(outputs.glob("*_stats.json"))
    best_paths = sorted(outputs.glob("*_best.json"))
    expected_ranks = signature["np"]
    if len(stats_paths) != expected_ranks or len(best_paths) != expected_ranks:
        raise AuditError(
            f"{variant}: expected {expected_ranks} stats and best files, "
            f"found {len(stats_paths)} and {len(best_paths)}"
        )

    rank_times = []
    candidate_assignments = 0
    tasks_processed = 0
    for path in stats_paths:
        stats = load_json(path)
        if stats.get("search", {}).get("status") != "CONCLUSIVE":
            raise AuditError(f"{variant}: inconclusive stats artifact {path.name}")
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
                f"{variant}: artifact configuration {observed} differs from {signature}"
            )
        artifact_sha256 = (
            metadata.get("software", {}).get("executable_sha256")
        )
        if artifact_sha256 != expected_executable_sha256:
            raise AuditError(f"{variant}: executable hash mismatch in {path.name}")
        rank_times.append(float(stats["time_total"]))
        disaggregation = stats.get("disaggregation_summary", {})
        candidate_assignments += int(
            disaggregation.get("candidate_assignments", 0)
        )
        tasks_processed += int(stats.get("tasks_processed", 0))

    costs = []
    for path in best_paths:
        best = load_json(path)
        if best.get("search_status") != "CONCLUSIVE":
            raise AuditError(f"{variant}: inconclusive best artifact {path.name}")
        cost = best.get("best_cost")
        if (
            isinstance(cost, (int, float))
            and math.isfinite(cost)
            and abs(float(cost)) < 1e100
        ):
            costs.append(float(cost))
    if not costs:
        raise AuditError(f"{variant}: no finite best cost")

    average_rank_seconds = sum(rank_times) / len(rank_times)
    maximum_rank_seconds = max(rank_times)
    imbalance = (
        (maximum_rank_seconds - average_rank_seconds) / average_rank_seconds
        if average_rank_seconds > 0
        else 0.0
    )
    return {
        "id": variant,
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
    tasks = plan.get("tasks", [])
    if len(tasks) != 1 or tasks[0].get("id") != "ablation":
        raise AuditError(f"campaign does not contain one ablation task: {campaign}")
    commands = tasks[0].get("commands", [])
    result_tasks = receipt.get("tasks", [])
    if len(result_tasks) != 1:
        raise AuditError(f"campaign receipt has an invalid task count: {campaign}")
    if result_tasks[0].get("return_codes") != [0] * len(commands):
        raise AuditError(f"campaign has unsuccessful commands: {campaign}")

    executable_sha256 = plan["metadata"]["executable"]["sha256"]
    return {
        "campaign": campaign.name,
        "git": plan["metadata"]["git"],
        "executable_sha256": executable_sha256,
        "compatibility_sha256": plan["compatibility_sha256"],
        "duration_seconds": float(result_tasks[0]["duration_seconds"]),
        "variants": [
            audit_variant(campaign, command, executable_sha256)
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

    orders = [[variant["id"] for variant in item["variants"]] for item in audited]
    if any(order != orders[0] for order in orders[1:]):
        raise AuditError("campaigns used different variant orders")
    by_round = [
        {variant["id"]: variant for variant in campaign["variants"]}
        for campaign in audited
    ]
    baseline_times = [round_["baseline"]["wall_seconds"] for round_ in by_round]
    reference_configuration = by_round[0]["baseline"]["configuration"]
    reference_cost = by_round[0]["baseline"]["global_best_cost"]

    variants = []
    for variant_id in orders[0]:
        repetitions = []
        environments = []
        for number, (campaign, round_, baseline_seconds) in enumerate(
            zip(audited, by_round, baseline_times), start=1
        ):
            observed = round_[variant_id]
            if observed["configuration"] != reference_configuration:
                raise AuditError(f"{variant_id}: configuration differs between rounds")
            if not math.isclose(
                observed["global_best_cost"], reference_cost, rel_tol=1e-12
            ):
                raise AuditError(f"{variant_id}: global best cost differs")
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
                    "paired_slowdown": observed["wall_seconds"] / baseline_seconds,
                }
            )
        if any(environment != environments[0] for environment in environments[1:]):
            raise AuditError(f"{variant_id}: environment differs between rounds")
        wall_times = [item["wall_seconds"] for item in repetitions]
        slowdowns = [item["paired_slowdown"] for item in repetitions]
        candidates = [item["candidate_assignments"] for item in repetitions]
        imbalances = [item["load_imbalance_factor"] for item in repetitions]
        variants.append(
            {
                "id": variant_id,
                "environment": environments[0],
                "repetitions": repetitions,
                "summary": {
                    "wall_seconds_median": median(wall_times),
                    "wall_seconds_minimum": min(wall_times),
                    "wall_seconds_maximum": max(wall_times),
                    "paired_slowdown_median": median(slowdowns),
                    "paired_slowdown_minimum": min(slowdowns),
                    "paired_slowdown_maximum": max(slowdowns),
                    "candidate_assignments_median": median(candidates),
                    "load_imbalance_factor_median": median(imbalances),
                },
            }
        )

    return {
        "schema_version": 1,
        "repetition_count": len(audited),
        "configuration": reference_configuration,
        "global_best_cost": reference_cost,
        "executable_sha256": audited[0]["executable_sha256"],
        "campaigns": [
            {key: value for key, value in item.items() if key != "variants"}
            for item in audited
        ],
        "variants": variants,
    }


def write_csv(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repetitions = summary["repetition_count"]
    fields = ["variant"] + [
        f"wall_seconds_rep_{number}" for number in range(1, repetitions + 1)
    ] + [
        "wall_seconds_median",
        "wall_seconds_minimum",
        "wall_seconds_maximum",
        "paired_slowdown_median",
        "paired_slowdown_minimum",
        "paired_slowdown_maximum",
        "candidate_assignments_median",
        "load_imbalance_factor_median",
        "global_best_cost",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for variant in summary["variants"]:
            row = {"variant": variant["id"]}
            for repetition in variant["repetitions"]:
                row[f"wall_seconds_rep_{repetition['number']}"] = repetition[
                    "wall_seconds"
                ]
            row.update(variant["summary"])
            row["global_best_cost"] = summary["global_best_cost"]
            writer.writerow(row)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign-dir", action="append", required=True, type=Path
    )
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = summarize_campaigns(arguments.campaign_dir)
    except (AuditError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ablation audit failed: {exc}")
        return 1
    arguments.output_json.parent.mkdir(parents=True, exist_ok=True)
    arguments.output_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(summary, arguments.output_csv)
    print(
        f"audited {summary['repetition_count']} campaigns and "
        f"{len(summary['variants'])} variants"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
