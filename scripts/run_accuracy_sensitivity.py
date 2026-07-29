#!/usr/bin/env python3
"""Run paired fixed-schedule and full-optimization accuracy experiments."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

from summarize_accuracy_sensitivity import summarize_records


ROOT = Path(__file__).absolute().parents[1]
DEFAULT_CONFIG = ROOT / "experiments" / "accuracy-sensitivity-anytown-24h.json"
DEFAULT_BINARY = ROOT / "build" / "run-epanet3-bb"
DEFAULT_EVALUATOR = ROOT / "build" / "run-epanet3-bb-eval"
DEFAULT_NETWORK = ROOT / "networks" / "any-town.inp"
DEFAULT_FINAL_SUMMARY = (
    ROOT / "experiments" / "results" / "final-cases-anytown-24h-summary.json"
)
DEFAULT_MPI = "mpiexec"
DEFAULT_OUTPUT = ROOT / "build" / "experiments" / "accuracy-sensitivity"
PRUNE_REASONS = (
    "NONE",
    "PRESSURES",
    "LEVELS",
    "TANK_SATURATION",
    "STABILITY",
    "COST",
    "ACTUATIONS",
    "TIMESTEP",
)


class ConfigurationError(RuntimeError):
    """Raised when a sensitivity campaign cannot be executed safely."""


def absolute_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.absolute()


def executable_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return absolute_path(candidate)
    resolved = shutil.which(str(candidate))
    if resolved is None:
        raise ConfigurationError(f"executable was not found on PATH: {candidate}")
    return Path(resolved).absolute()


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise ConfigurationError(f"missing input: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def git_metadata() -> dict:
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--evaluator", default=str(DEFAULT_EVALUATOR))
    parser.add_argument("--input", default=str(DEFAULT_NETWORK))
    parser.add_argument("--final-summary", default=str(DEFAULT_FINAL_SUMMARY))
    parser.add_argument("--mpi-launcher", default=str(DEFAULT_MPI))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-np", type=int)
    parser.add_argument("--profile", choices=("final", "smoke"), default="final")
    parser.add_argument("--select", action="append", choices=("fixed", "optimization"))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.select:
        args.select = list(dict.fromkeys(args.select))
    return args


def validate_config(raw: dict) -> dict:
    if raw.get("schema_version") != 1:
        raise ConfigurationError("accuracy config schema_version must be 1")
    accuracies = raw.get("accuracies", [])
    if not accuracies or len({entry.get("id") for entry in accuracies}) != len(accuracies):
        raise ConfigurationError("accuracy identifiers must be present and unique")
    for entry in accuracies:
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigurationError("accuracy values must be positive numbers")
    fixed = raw.get("fixed_schedules", {})
    optimization = raw.get("optimizations", {})
    required_positive = (
        ("fixed_schedules.repetitions", fixed.get("repetitions")),
        ("fixed_schedules.hydraulic_max_trials", fixed.get("hydraulic_max_trials")),
        ("optimizations.repetitions", optimization.get("repetitions")),
        ("optimizations.process_count", optimization.get("process_count")),
        ("optimizations.hours", optimization.get("hours")),
        ("optimizations.level", optimization.get("level")),
        ("optimizations.sync_interval", optimization.get("sync_interval")),
        ("optimizations.hydraulic_max_trials", optimization.get("hydraulic_max_trials")),
        ("optimizations.timeout_seconds", optimization.get("timeout_seconds")),
    )
    for name, value in required_positive:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigurationError(f"{name} must be positive")
    if sorted(int(value) for value in optimization.get("actuations", [])) != [1, 2, 3]:
        raise ConfigurationError("final optimization grid must contain NA_max=1,2,3")
    return raw


def rotated(values: list[dict], offset: int) -> list[dict]:
    offset %= len(values)
    return values[offset:] + values[:offset]


def fixed_cells(accuracies: list[dict], repetitions: int) -> list[dict]:
    cells = []
    for repetition in range(1, repetitions + 1):
        for actuations in (1, 2, 3):
            order = rotated(accuracies, repetition + actuations - 2)
            for accuracy in order:
                cells.append(
                    {
                        "id": f"fixed-r{repetition:02d}-a{actuations}-{accuracy['id']}",
                        "kind": "fixed",
                        "repetition": repetition,
                        "actuations": actuations,
                        "accuracy_id": accuracy["id"],
                        "accuracy": float(accuracy["value"]),
                        "np": 1,
                    }
                )
    return cells


def optimization_cells(
    accuracies: list[dict], repetitions: int, process_count: int,
    actuations: list[int],
) -> list[dict]:
    cells = []
    preferred = sorted(
        accuracies,
        key=lambda item: {"1e-4": 0, "1e-3": 1, "1e-7": 2}.get(item["id"], 3),
    )
    for repetition in range(1, repetitions + 1):
        order = rotated(preferred, repetition - 1)
        for actuations_value in sorted(actuations, reverse=True):
            for accuracy in order:
                cells.append(
                    {
                        "id": f"optimization-r{repetition:02d}-a{actuations_value}-{accuracy['id']}",
                        "kind": "optimization",
                        "repetition": repetition,
                        "actuations": actuations_value,
                        "accuracy_id": accuracy["id"],
                        "accuracy": float(accuracy["value"]),
                        "np": process_count,
                    }
                )
    return cells


def build_plan(arguments: argparse.Namespace) -> dict:
    if arguments.select and arguments.all:
        raise ConfigurationError("--select and --all cannot be combined")
    if arguments.resume and arguments.dry_run:
        raise ConfigurationError("--resume and --dry-run cannot be combined")
    if not arguments.dry_run and not arguments.select and not arguments.all:
        raise ConfigurationError("execution requires --select or --all")
    selected = arguments.select or ["fixed", "optimization"]
    paths = {
        "config": absolute_path(arguments.config),
        "binary": absolute_path(arguments.binary),
        "evaluator": absolute_path(arguments.evaluator),
        "input": absolute_path(arguments.input),
        "final_summary": absolute_path(arguments.final_summary),
        "mpi_launcher": executable_path(arguments.mpi_launcher),
        "output_dir": absolute_path(arguments.output_dir),
    }
    for name, path in paths.items():
        if name == "output_dir":
            continue
        if not path.is_file():
            raise ConfigurationError(f"{name} does not exist: {path}")
    for name in ("binary", "evaluator", "mpi_launcher"):
        if not os.access(paths[name], os.X_OK):
            raise ConfigurationError(f"{name} is not executable: {paths[name]}")
    config = validate_config(load_json(paths["config"]))
    summary = load_json(paths["final_summary"])
    cases = {int(case["actuations"]): case for case in summary.get("cases", [])}
    if sorted(cases) != [1, 2, 3]:
        raise ConfigurationError("final summary must contain NA_max=1,2,3")

    accuracies = config["accuracies"]
    fixed_repetitions = int(config["fixed_schedules"]["repetitions"])
    optimization = dict(config["optimizations"])
    if arguments.profile == "smoke":
        smoke = config["smoke"]
        accuracies = [
            entry for entry in accuracies if entry["id"] == smoke["accuracy_id"]
        ]
        fixed_repetitions = 1
        optimization.update(
            {
                "repetitions": 1,
                "process_count": int(smoke["process_count"]),
                "hours": int(smoke["hours"]),
                "actuations": [int(value) for value in smoke["actuations"]],
                "level": int(smoke["level"]),
                "sync_interval": int(smoke["sync_interval"]),
                "timeout_seconds": float(smoke["timeout_seconds"]),
            }
        )
    process_count = int(optimization["process_count"])
    if process_count > 64:
        raise ConfigurationError("optimization process_count cannot exceed 64")
    if arguments.max_np is not None:
        if arguments.max_np <= 0 or arguments.max_np > 64:
            raise ConfigurationError("--max-np must be between 1 and 64")
        process_count = min(process_count, arguments.max_np)
    cells = []
    if "fixed" in selected:
        cells.extend(fixed_cells(accuracies, fixed_repetitions))
    if "optimization" in selected:
        cells.extend(
            optimization_cells(
                accuracies,
                int(optimization["repetitions"]),
                process_count,
                [int(value) for value in optimization["actuations"]],
            )
        )
    metadata = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git": git_metadata(),
        "host": platform.node(),
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "inputs": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in paths.items()
            if name != "output_dir"
        },
    }
    resolved_paths = {name: str(path) for name, path in paths.items()}
    protocol = {
        "selected": selected,
        "accuracies": accuracies,
        "fixed": {
            "repetitions": fixed_repetitions,
            "hydraulic_max_trials": int(
                config["fixed_schedules"]["hydraulic_max_trials"]
            ),
        },
        "optimization": {
            **optimization,
            "process_count": process_count,
        },
    }
    compatibility = {
        "profile": arguments.profile,
        "paths": resolved_paths,
        "protocol": protocol,
        "cells": cells,
        "git_commit": metadata["git"]["commit"],
        "input_hashes": metadata["inputs"],
    }
    return {
        "schema_version": 1,
        "profile": arguments.profile,
        "paths": resolved_paths,
        "protocol": protocol,
        "cells": cells,
        "metadata": metadata,
        "compatibility_sha256": canonical_sha256(compatibility),
    }


def terminate_process_group(process: subprocess.Popen) -> None:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_command(
    command: list[str], cwd: Path, log_path: Path, timeout_seconds: float
) -> dict:
    environment = os.environ.copy()
    environment["HWLOC_COMPONENTS"] = "-gl"
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            terminate_process_group(process)
            return_code = 124
            timed_out = True
    return {
        "command": command,
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": time.monotonic() - started,
        "log": str(log_path),
    }


def available_work_directory(root: Path, cell_id: str) -> Path:
    candidate = root / cell_id
    if not candidate.exists():
        return candidate
    for attempt in range(1, 1000):
        candidate = root / f"{cell_id}-retry-{attempt:03d}"
        if not candidate.exists():
            return candidate
    raise ConfigurationError(f"too many retries for {cell_id}")


def fixed_record(cell: dict, plan: dict, working: Path) -> dict:
    summary = load_json(Path(plan["paths"]["final_summary"]))
    case = next(
        case for case in summary["cases"]
        if int(case["actuations"]) == cell["actuations"]
    )
    request = {
        "best_x": case["best_x"],
        "best_y": case["best_y"],
        "h_max": 24,
        "max_actuations": cell["actuations"],
        "inp_file": plan["paths"]["input"],
        "schedule_mode": "binary",
        "hydraulic_accuracy": cell["accuracy"],
        "hydraulic_max_trials": plan["protocol"]["fixed"]["hydraulic_max_trials"],
        "verbose": 0,
    }
    request_path = working / "request.json"
    result_path = working / "result.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    command = [
        plan["paths"]["mpi_launcher"],
        "--map-by", "core", "--bind-to", "core", "-n", "1",
        plan["paths"]["evaluator"], str(request_path), str(result_path),
    ]
    execution = run_command(command, ROOT, working / "console.log", 120.0)
    result = load_json(result_path) if result_path.is_file() else {}
    hydraulic = result.get("hydraulic", {})
    return {
        **cell,
        **execution,
        "working_directory": str(working),
        "request": str(request_path),
        "result": str(result_path) if result_path.is_file() else None,
        "result_sha256": sha256_file(result_path) if result_path.is_file() else None,
        "feasible": result.get("feasible"),
        "cost": result.get("cost"),
        "prune_reason": result.get("prune_reason"),
        "hour_failed": result.get("hour_failed"),
        "hydraulic_converged": hydraulic.get("converged"),
        "hydraulic_status": hydraulic.get("status"),
        "hydraulic_solve_count": hydraulic.get("solve_count"),
        "hydraulic_trials_total": hydraulic.get("trials_total"),
        "hydraulic_trials_maximum": hydraulic.get("trials_maximum"),
        "hydraulic_solve_seconds": hydraulic.get("solve_seconds"),
        "hydraulic_failure_time_seconds": hydraulic.get("failure_time_seconds"),
    }


def sum_reason(payloads: list[dict], reason: str) -> int:
    total = 0
    for payload in payloads:
        values = payload.get(reason, [])
        if isinstance(values, list):
            total += sum(int(value) for value in values)
    return total


def optimization_record(cell: dict, plan: dict, working: Path) -> dict:
    protocol = plan["protocol"]["optimization"]
    command = [
        plan["paths"]["mpi_launcher"],
        "--map-by", "core", "--bind-to", "core", "-n", str(cell["np"]),
        plan["paths"]["binary"],
        "-i", plan["paths"]["input"],
        "-h", str(protocol["hours"]),
        "-a", str(cell["actuations"]),
        "-l", str(protocol["level"]),
        "-s", str(protocol["sync_interval"]),
        "--hydraulic-accuracy", str(cell["accuracy"]),
        "--hydraulic-max-trials", str(protocol["hydraulic_max_trials"]),
    ]
    execution = run_command(
        command, working, working / "console.log", float(protocol["timeout_seconds"])
    )
    output_directory = working / "outputs"
    stats_paths = sorted(output_directory.glob("*_stats.json"))
    best_paths = sorted(output_directory.glob("*_best.json"))
    stats = [load_json(path) for path in stats_paths]
    best = [load_json(path) for path in best_paths]
    finite_best = [
        payload for payload in best
        if payload.get("search_status") == "CONCLUSIVE"
        and isinstance(payload.get("best_cost"), (int, float))
        and math.isfinite(float(payload["best_cost"]))
    ]
    selected = min(finite_best, key=lambda payload: payload["best_cost"]) if finite_best else {}
    status_values = {payload.get("search", {}).get("status") for payload in stats}
    conclusive = bool(stats) and status_values == {"CONCLUSIVE"} and bool(selected)
    pruning = {reason: sum_reason(stats, reason) for reason in PRUNE_REASONS}
    return {
        **cell,
        **execution,
        "working_directory": str(working),
        "stats_files": len(stats_paths),
        "best_files": len(best_paths),
        "conclusive": conclusive,
        "search_statuses": sorted(str(value) for value in status_values),
        "best_cost": selected.get("best_cost"),
        "best_x": selected.get("best_x"),
        "best_y": selected.get("best_y"),
        "schedule_sha256": canonical_sha256(selected.get("best_x")) if selected else None,
        "tasks_processed": sum(int(payload.get("tasks_processed", 0)) for payload in stats),
        "candidate_assignments": sum(
            int(payload.get("disaggregation_summary", {}).get("candidate_assignments", 0))
            for payload in stats
        ),
        "nodes_total": sum(pruning.values()),
        "pruning_counts": pruning,
        "hydraulic_nonconvergence_events": sum(
            len(payload.get("hydraulic_nonconvergence_events", [])) for payload in stats
        ),
    }


def write_csv(path: Path, records: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fields})


def write_summaries(output: Path, plan: dict, records: list[dict]) -> None:
    fixed = [record for record in records if record["kind"] == "fixed"]
    optimization = [record for record in records if record["kind"] == "optimization"]
    write_json_atomic(
        output / "accuracy-sensitivity-summary.json",
        {
            "schema_version": 1,
            "compatibility_sha256": plan["compatibility_sha256"],
            "profile": plan["profile"],
            "fixed_records": fixed,
            "optimization_records": optimization,
        },
    )
    common = ["id", "repetition", "actuations", "accuracy_id", "accuracy"]
    write_csv(
        output / "fixed-schedule-summary.csv",
        fixed,
        common + [
            "return_code", "timed_out", "duration_seconds", "feasible", "cost",
            "prune_reason", "hour_failed", "hydraulic_converged", "hydraulic_status",
            "hydraulic_solve_count", "hydraulic_trials_total",
            "hydraulic_trials_maximum", "hydraulic_solve_seconds",
            "hydraulic_failure_time_seconds", "result_sha256", "working_directory",
        ],
    )
    write_csv(
        output / "optimization-summary.csv",
        optimization,
        common + [
            "np", "return_code", "timed_out", "duration_seconds", "conclusive",
            "best_cost", "schedule_sha256", "stats_files", "best_files",
            "tasks_processed", "candidate_assignments", "nodes_total",
            "hydraulic_nonconvergence_events", "working_directory",
        ],
    )
    summarize_records(records, output)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = parse_arguments(argv)
        plan = build_plan(arguments)
    except (ConfigurationError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, sort_keys=True))
    if arguments.dry_run:
        return 0
    if plan["metadata"]["git"]["dirty"]:
        print("configuration error: execution requires a clean Git tree", file=sys.stderr)
        return 2

    output = Path(plan["paths"]["output_dir"])
    plan_path = output / "accuracy-sensitivity-plan.json"
    receipt_path = output / "accuracy-sensitivity-results.json"
    if arguments.resume:
        if not plan_path.is_file() or not receipt_path.is_file():
            print("configuration error: --resume requires existing plan and receipt", file=sys.stderr)
            return 2
        stored = load_json(plan_path)
        if stored.get("compatibility_sha256") != plan["compatibility_sha256"]:
            print("configuration error: existing campaign is incompatible", file=sys.stderr)
            return 2
        receipt = load_json(receipt_path)
        records = receipt.get("records", [])
    else:
        try:
            output.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(f"configuration error: output directory exists: {output}", file=sys.stderr)
            return 2
        write_json_atomic(plan_path, plan)
        records = []
    work = output / "work"
    work.mkdir(exist_ok=True)
    complete_ids = {record["id"] for record in records}
    receipt = {"status": "running", "resumed": arguments.resume, "records": records}
    write_json_atomic(receipt_path, receipt)

    for cell in plan["cells"]:
        if cell["id"] in complete_ids:
            continue
        working = available_work_directory(work, cell["id"])
        working.mkdir()
        record = (
            fixed_record(cell, plan, working)
            if cell["kind"] == "fixed"
            else optimization_record(cell, plan, working)
        )
        records.append(record)
        complete_ids.add(cell["id"])
        receipt["records"] = records
        write_json_atomic(receipt_path, receipt)
        write_summaries(output, plan, records)

    receipt["status"] = "complete"
    write_json_atomic(receipt_path, receipt)
    write_summaries(output, plan, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
