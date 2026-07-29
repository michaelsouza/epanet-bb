#!/usr/bin/env python3
"""Plan or execute reproducible EPANET-BB experiment campaign subsets."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from run_experiments import (
    ConfigurationError,
    executable_path,
    portable_path,
    process_count_record,
)


REPO_ROOT = Path(__file__).absolute().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "experiments" / "reproducibility.json"
DEFAULT_BINARY = REPO_ROOT / "build" / "run-epanet3-bb"
DEFAULT_INPUT = REPO_ROOT / "networks" / "any-town.inp"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "experiments" / "campaign"
DEFAULT_MPI_LAUNCHER = "mpiexec"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def command_version(command: list[str]) -> str | None:
    try:
        process_env = dict(os.environ, HWLOC_COMPONENTS="-gl")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            env=process_env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.strip() or completed.stderr.strip()
    return output.splitlines()[0] if output else None


def git_metadata() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--mpi-launcher", default=str(DEFAULT_MPI_LAUNCHER))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--np", type=int, help="maximum/selected MPI ranks")
    parser.add_argument(
        "--hydraulic-accuracy",
        type=float,
        help="override input-file accuracy for solver campaign tasks",
    )
    parser.add_argument(
        "--hydraulic-max-trials",
        type=int,
        help="override input-file maximum trials for solver campaign tasks",
    )
    parser.add_argument(
        "--profile",
        choices=("final", "smoke"),
        default="final",
        help="final protocol or bounded validation protocol",
    )
    parser.add_argument(
        "--select",
        action="append",
        help="execute only this task; may be supplied more than once",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="explicitly select every campaign task for execution",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="continue a compatible campaign and skip completed commands",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved plan without creating files",
    )
    args = parser.parse_args(argv)
    if args.select:
        args.select = list(dict.fromkeys(args.select))
    return args


def solver_command(
    *,
    binary: Path,
    input_path: Path,
    launcher: Path,
    output_directory: Path,
    process_count: int,
    hours: int,
    actuations: list[int],
    level: int,
    sync_interval: int,
    hydraulic_accuracy: float | None,
    hydraulic_max_trials: int | None,
    environment: dict[str, str] | None = None,
) -> dict[str, object]:
    argv = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_experiments.py"),
        "--np",
        str(process_count),
        "--binary",
        str(binary),
        "--input",
        str(input_path),
        "--mpi-launcher",
        str(launcher),
        "--output-dir",
        str(output_directory),
        "--hours",
        str(hours),
        "--actuations",
        *[str(value) for value in actuations],
        "--level",
        str(level),
        "--sync-interval",
        str(sync_interval),
    ]
    if hydraulic_accuracy is not None:
        argv.extend(["--hydraulic-accuracy", str(hydraulic_accuracy)])
    if hydraulic_max_trials is not None:
        argv.extend(["--hydraulic-max-trials", str(hydraulic_max_trials)])
    return {
        "np": process_count,
        "argv": argv,
        "environment": environment or {},
        "output_dir": str(output_directory),
    }


def task_commands(
    task: dict,
    *,
    profile: str,
    resources: dict,
    binary: Path,
    input_path: Path,
    launcher: Path,
    output_directory: Path,
    hydraulic_accuracy: float | None,
    hydraulic_max_trials: int | None,
) -> list[dict[str, object]]:
    selected_processes = min(int(resources["process_count"]["value"]), 64)
    if profile == "smoke":
        hours, actuations, level, sync_interval = 3, [1], 1, 32
    else:
        hours = int(task.get("hours", 24))
        actuations = [int(value) for value in task.get("actuations", [1])]
        level = int(task.get("level", 8))
        sync_interval = int(task.get("sync_interval", 32768))

    if task["kind"] == "tuning":
        variables = {"repo_root": str(REPO_ROOT)}
        config_key = "smoke_config" if profile == "smoke" else "final_config"
        config_path = Path(task[config_key].format_map(variables)).absolute()
        max_tuning_np = 1 if profile == "smoke" else selected_processes
        argv = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_tuning.py"),
            "--config",
            str(config_path),
            "--binary",
            str(binary),
            "--input",
            str(input_path),
            "--mpi-launcher",
            str(launcher),
            "--max-np",
            str(max_tuning_np),
            "--output-dir",
            str(output_directory / task["id"]),
        ]
        if profile == "smoke":
            argv.extend(["--n-trials", "1"])
        return [
            {
                "np": max_tuning_np,
                "argv": argv,
                "environment": {},
                "output_dir": str(output_directory / task["id"]),
            }
        ]

    if task["kind"] == "accuracy-sensitivity":
        if hydraulic_accuracy is not None or hydraulic_max_trials is not None:
            raise ConfigurationError(
                "accuracy-sensitivity owns its accuracy and trial grids; "
                "do not use global hydraulic overrides"
            )
        variables = {"repo_root": str(REPO_ROOT)}
        config_path = Path(task["config"].format_map(variables)).absolute()
        argv = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_accuracy_sensitivity.py"),
            "--config",
            str(config_path),
            "--binary",
            str(binary),
            "--evaluator",
            str(binary.with_name("run-epanet3-bb-eval")),
            "--input",
            str(input_path),
            "--mpi-launcher",
            str(launcher),
            "--max-np",
            str(selected_processes),
            "--profile",
            profile,
            "--all",
            "--output-dir",
            str(output_directory / task["id"]),
        ]
        return [
            {
                "np": 1 if profile == "smoke" else selected_processes,
                "argv": argv,
                "environment": {},
                "output_dir": str(output_directory / task["id"]),
            }
        ]

    configured_counts = task.get("process_counts", "selected")
    if configured_counts == "selected":
        process_counts = [selected_processes]
    else:
        process_counts = [
            int(value)
            for value in configured_counts
            if int(value) <= selected_processes
        ]
    if profile == "smoke":
        process_counts = [1]
    if not process_counts:
        raise ConfigurationError(
            f"{task['id']} has no process count within the selected resources"
        )

    if task["kind"] == "solver-matrix":
        return [
            solver_command(
                binary=binary,
                input_path=input_path,
                launcher=launcher,
                output_directory=(
                    output_directory / task["id"] / f"np-{process_count:03d}"
                    if len(process_counts) > 1
                    else output_directory / task["id"]
                ),
                process_count=process_count,
                hours=hours,
                actuations=actuations,
                level=level,
                sync_interval=sync_interval,
                hydraulic_accuracy=hydraulic_accuracy,
                hydraulic_max_trials=hydraulic_max_trials,
            )
            for process_count in process_counts
        ]

    if task["kind"] == "solver-variants":
        commands = []
        for variant in task.get("variants", []):
            commands.append(
                solver_command(
                    binary=binary,
                    input_path=input_path,
                    launcher=launcher,
                    output_directory=(
                        output_directory / task["id"] / variant["id"]
                    ),
                    process_count=process_counts[0],
                    hours=hours,
                    actuations=actuations,
                    level=level,
                    sync_interval=sync_interval,
                    hydraulic_accuracy=hydraulic_accuracy,
                    hydraulic_max_trials=hydraulic_max_trials,
                    environment=variant.get("environment", {}),
                )
            )
        return commands

    raise ConfigurationError(
        f"unsupported campaign task kind {task['kind']!r}"
    )


def build_plan(
    arguments: argparse.Namespace, environment: dict[str, str]
) -> dict:
    manifest_path = portable_path(arguments.manifest)
    binary = portable_path(arguments.binary)
    input_path = portable_path(arguments.input)
    launcher = executable_path(arguments.mpi_launcher)
    output_directory = portable_path(arguments.output_dir)
    for label, path in (
        ("manifest", manifest_path),
        ("binary", binary),
        ("input", input_path),
        ("MPI launcher", launcher),
    ):
        if not path.is_file():
            raise ConfigurationError(f"{label} does not exist: {path}")
    if not os.access(binary, os.X_OK):
        raise ConfigurationError(f"binary is not executable: {binary}")
    if not os.access(launcher, os.X_OK):
        raise ConfigurationError(f"MPI launcher is not executable: {launcher}")
    if (
        arguments.hydraulic_accuracy is not None
        and arguments.hydraulic_accuracy <= 0
    ):
        raise ConfigurationError("--hydraulic-accuracy must be positive")
    if (
        arguments.hydraulic_max_trials is not None
        and arguments.hydraulic_max_trials <= 0
    ):
        raise ConfigurationError("--hydraulic-max-trials must be positive")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ConfigurationError("manifest schema_version must be 1")
    tasks_by_id = {
        task["id"]: task for task in manifest.get("campaign_tasks", [])
    }
    if arguments.select and arguments.all:
        raise ConfigurationError("--select and --all cannot be combined")
    if arguments.resume and arguments.dry_run:
        raise ConfigurationError("--resume and --dry-run cannot be combined")
    if not arguments.dry_run and not arguments.select and not arguments.all:
        raise ConfigurationError(
            "execution requires at least one --select or explicit --all"
        )
    selected = (
        list(tasks_by_id)
        if arguments.all or not arguments.select
        else arguments.select
    )
    unknown = [task_id for task_id in selected if task_id not in tasks_by_id]
    if unknown:
        raise ConfigurationError(
            "unknown campaign tasks: " + ", ".join(unknown)
        )

    resources = {
        "process_count": process_count_record(arguments.np, environment)
    }
    resolved_tasks = []
    for task_id in selected:
        task = tasks_by_id[task_id]
        resolved_tasks.append(
            {
                "id": task_id,
                "kind": task["kind"],
                "requires_mpi": bool(task.get("requires_mpi", False)),
                "requires_hpc": bool(task.get("requires_hpc", False)),
                "commands": task_commands(
                    task,
                    profile=arguments.profile,
                    resources=resources,
                    binary=binary,
                    input_path=input_path,
                    launcher=launcher,
                    output_directory=output_directory,
                    hydraulic_accuracy=arguments.hydraulic_accuracy,
                    hydraulic_max_trials=arguments.hydraulic_max_trials,
                ),
            }
        )

    plan = {
        "schema_version": 1,
        "profile": arguments.profile,
        "paths": {
            "repo_root": str(REPO_ROOT),
            "manifest": str(manifest_path),
            "binary": str(binary),
            "input": str(input_path),
            "mpi_launcher": str(launcher),
            "output_dir": str(output_directory),
        },
        "resources": resources,
        "hydraulics": {
            "accuracy_override": arguments.hydraulic_accuracy,
            "max_trials_override": arguments.hydraulic_max_trials,
            "otherwise": "input_file",
        },
        "metadata": {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "git": git_metadata(),
            "executable": {
                "path": str(binary),
                "sha256": sha256_file(binary),
            },
            "compiler": command_version(["c++", "--version"]),
            "mpi": command_version([str(launcher), "--version"]),
            "hardware": {
                "node": platform.node(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "logical_cpu_count": os.cpu_count(),
            },
        },
        "tasks": resolved_tasks,
    }
    compatibility = {
        "profile": plan["profile"],
        "paths": plan["paths"],
        "resources": plan["resources"],
        "hydraulics": plan["hydraulics"],
        "tasks": plan["tasks"],
        "git_commit": plan["metadata"]["git"]["commit"],
        "executable": plan["metadata"]["executable"],
    }
    plan["compatibility_sha256"] = canonical_sha256(compatibility)
    return plan


def next_available_path(path: Path) -> Path:
    for attempt in range(1, 1000):
        candidate = path.with_name(f"{path.name}-resume-{attempt:03d}")
        if not candidate.exists():
            return candidate
    raise ConfigurationError(f"too many resume attempts for {path}")


def resumed_command(command: dict[str, object]) -> dict[str, object]:
    runtime = {
        "np": command["np"],
        "argv": list(command["argv"]),
        "environment": dict(command["environment"]),
        "output_dir": command["output_dir"],
    }
    output_directory = Path(str(command["output_dir"]))
    if not output_directory.exists():
        return runtime
    if Path(runtime["argv"][1]).name == "run_tuning.py":
        return runtime
    retry_directory = next_available_path(output_directory)
    output_option = runtime["argv"].index("--output-dir")
    runtime["argv"][output_option + 1] = str(retry_directory)
    runtime["output_dir"] = str(retry_directory)
    return runtime


def next_log_path(
    logs_directory: Path, task_id: str, command_number: int
) -> Path:
    base = logs_directory / f"{task_id}-{command_number:02d}.log"
    if not base.exists():
        return base
    for attempt in range(1, 1000):
        candidate = logs_directory / (
            f"{task_id}-{command_number:02d}-resume-{attempt:03d}.log"
        )
        if not candidate.exists():
            return candidate
    raise ConfigurationError(f"too many resume logs for {task_id}")


def write_json_atomic(path: Path, payload: object) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = parse_arguments(argv)
        plan = build_plan(arguments, dict(os.environ))
    except (ConfigurationError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(plan, indent=2, sort_keys=True))
    if arguments.dry_run:
        return 0

    output_directory = Path(plan["paths"]["output_dir"])
    previous_receipt = {"tasks": []}
    if arguments.resume:
        plan_path = output_directory / "campaign-plan.json"
        receipt_path = output_directory / "campaign-results.json"
        if not plan_path.is_file() or not receipt_path.is_file():
            print(
                "configuration error: --resume requires campaign-plan.json "
                "and campaign-results.json",
                file=sys.stderr,
            )
            return 2
        stored_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if stored_plan.get("compatibility_sha256") != plan[
            "compatibility_sha256"
        ]:
            print(
                "configuration error: existing campaign is incompatible "
                "with the resolved plan",
                file=sys.stderr,
            )
            return 2
        previous_receipt = json.loads(
            receipt_path.read_text(encoding="utf-8")
        )
    else:
        try:
            output_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(
                f"configuration error: output directory already exists: "
                f"{output_directory}",
                file=sys.stderr,
            )
            return 2
        (output_directory / "campaign-plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    logs_directory = output_directory / "logs"
    logs_directory.mkdir(exist_ok=True)
    receipt_path = output_directory / "campaign-results.json"
    receipt = {
        "status": "running",
        "resumed": arguments.resume,
        "skipped_complete_tasks": [],
        "tasks": [],
    }
    previous_by_id = {
        task["id"]: task for task in previous_receipt.get("tasks", [])
    }

    for task in plan["tasks"]:
        previous = previous_by_id.get(task["id"], {})
        previous_codes = previous.get("return_codes", [])
        previous_dirs = previous.get("output_dirs", [])
        successful_prefix = 0
        for code, directory in zip(previous_codes, previous_dirs):
            output_path = Path(directory)
            if (
                code != 0
                or not output_path.is_dir()
                or not any(output_path.iterdir())
            ):
                break
            successful_prefix += 1
        if (
            successful_prefix == len(task["commands"])
            and len(previous_codes) == len(task["commands"])
        ):
            receipt["skipped_complete_tasks"].append(task["id"])
            receipt["tasks"].append(previous)
            write_json_atomic(receipt_path, receipt)
            continue

        task_result = {
            "id": task["id"],
            "return_codes": list(previous_codes[:successful_prefix]),
            "logs": list(previous.get("logs", [])[:successful_prefix]),
            "output_dirs": list(
                previous.get("output_dirs", [])[:successful_prefix]
            ),
        }
        receipt["tasks"].append(task_result)
        write_json_atomic(receipt_path, receipt)
        started = time.monotonic()
        for number, planned_command in enumerate(
            task["commands"][successful_prefix:],
            start=successful_prefix + 1,
        ):
            command = (
                resumed_command(planned_command)
                if arguments.resume
                else planned_command
            )
            log_path = next_log_path(logs_directory, task["id"], number)
            process_environment = os.environ.copy()
            process_environment.setdefault("HWLOC_COMPONENTS", "-gl")
            process_environment.update(command["environment"])
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command["argv"],
                    cwd=output_directory,
                    env=process_environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            task_result["return_codes"].append(completed.returncode)
            task_result["logs"].append(str(log_path))
            task_result["output_dirs"].append(command["output_dir"])
            if completed.returncode != 0:
                receipt["status"] = "failed"
                write_json_atomic(receipt_path, receipt)
                break
            write_json_atomic(receipt_path, receipt)
        task_result["duration_seconds"] = time.monotonic() - started
        write_json_atomic(receipt_path, receipt)
        if receipt["status"] == "failed":
            break

    if receipt["status"] != "failed":
        receipt["status"] = "complete"
    write_json_atomic(receipt_path, receipt)
    return 0 if receipt["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
