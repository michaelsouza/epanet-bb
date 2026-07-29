#!/usr/bin/env python3
"""Run the final actuation cases with portable paths and resource selection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).absolute().parents[1]
DEFAULT_BINARY = REPO_ROOT / "build" / "run-epanet3-bb"
DEFAULT_INPUT = REPO_ROOT / "networks" / "any-town.inp"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "experiments" / "final-runs"
DEFAULT_MPI_LAUNCHER = "mpiexec"
ALLOCATION_VARIABLES = (
    "SLURM_NTASKS",
    "PBS_NP",
    "LSB_DJOB_NUMPROC",
    "NSLOTS",
)


class ConfigurationError(RuntimeError):
    """Raised when the requested execution cannot be made portable and safe."""


def portable_path(value: str | Path, *, relative_to: Path = REPO_ROOT) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = relative_to / path
    return path.absolute()


def executable_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return portable_path(candidate)
    resolved = shutil.which(str(candidate))
    if resolved is None:
        raise ConfigurationError(f"executable was not found on PATH: {candidate}")
    return Path(resolved).absolute()


def search_statuses(
    working_directory: Path, expected_ranks: int
) -> list[str]:
    paths = sorted((working_directory / "outputs").glob("*_stats.json"))
    if len(paths) != expected_ranks:
        raise ConfigurationError(
            f"solver produced {len(paths)} rank statistics; "
            f"expected {expected_ranks} in {working_directory / 'outputs'}"
        )
    statuses = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            status = payload["search"]["status"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ConfigurationError(f"invalid rank statistics: {path}") from exc
        statuses.append(str(status))
    return statuses


def allocated_processes(environment: dict[str, str]) -> tuple[int | None, str | None]:
    for variable in ALLOCATION_VARIABLES:
        raw_value = environment.get(variable)
        if raw_value is None:
            continue
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ConfigurationError(
                f"{variable} must be a positive integer, got {raw_value!r}"
            ) from exc
        if value <= 0:
            raise ConfigurationError(
                f"{variable} must be a positive integer, got {raw_value!r}"
            )
        return value, variable
    return None, None


MAX_MPI_RANKS = 64


def process_count_record(
    explicit: int | None, environment: dict[str, str]
) -> dict[str, int | str | None]:
    allocation, allocation_source = allocated_processes(environment)
    if explicit is not None:
        if explicit <= 0:
            raise ConfigurationError("--np must be a positive integer")
        if explicit > MAX_MPI_RANKS:
            raise ConfigurationError(
                f"--np={explicit} exceeds the maximum allowed {MAX_MPI_RANKS} MPI ranks"
            )
        if allocation is not None and explicit > allocation:
            raise ConfigurationError(
                f"--np={explicit} exceeds {allocation_source}={allocation}"
            )
        value = explicit
        source = "cli"
    elif allocation is not None:
        value = min(allocation, MAX_MPI_RANKS)
        source = "allocation"
    else:
        value = 1
        source = "fallback"
    return {
        "value": value,
        "source": source,
        "allocation": allocation,
        "allocation_source": allocation_source,
    }


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--np", type=int, help="MPI ranks; defaults to allocation or 1")
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--mpi-launcher", default=str(DEFAULT_MPI_LAUNCHER))
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--actuations", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--level", type=int, default=8)
    parser.add_argument("--sync-interval", type=int, default=32768)
    parser.add_argument(
        "--hydraulic-accuracy",
        type=float,
        help="override the input file's relative hydraulic accuracy",
    )
    parser.add_argument(
        "--hydraulic-max-trials",
        type=int,
        help="override the input file's maximum hydraulic trials",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved execution plan without creating files",
    )
    return parser.parse_args(argv)


def execution_plan(
    arguments: argparse.Namespace, environment: dict[str, str]
) -> dict:
    if arguments.hours <= 0:
        raise ConfigurationError("--hours must be positive")
    if any(value <= 0 for value in arguments.actuations):
        raise ConfigurationError("--actuations values must be positive")
    if arguments.level <= 0:
        raise ConfigurationError("--level must be positive")
    if arguments.sync_interval <= 0:
        raise ConfigurationError("--sync-interval must be positive")
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

    process_count = process_count_record(arguments.np, environment)
    binary = portable_path(arguments.binary)
    input_path = portable_path(arguments.input)
    output_directory = portable_path(arguments.output_dir)
    launcher = executable_path(arguments.mpi_launcher)
    for label, path in (
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

    experiments = []
    for actuations in arguments.actuations:
        working_directory = output_directory / f"actuations-{actuations:02d}"
        command = [
            str(launcher),
            "--map-by",
            "core",
            "--bind-to",
            "core",
            "-n",
            str(process_count["value"]),
            str(binary),
            "-i",
            str(input_path),
            "-h",
            str(arguments.hours),
            "-a",
            str(actuations),
            "-l",
            str(arguments.level),
            "-s",
            str(arguments.sync_interval),
        ]
        if arguments.hydraulic_accuracy is not None:
            command.extend(
                [
                    "--hydraulic-accuracy",
                    str(arguments.hydraulic_accuracy),
                ]
            )
        if arguments.hydraulic_max_trials is not None:
            command.extend(
                [
                    "--hydraulic-max-trials",
                    str(arguments.hydraulic_max_trials),
                ]
            )
        experiments.append(
            {
                "actuations": actuations,
                "working_directory": str(working_directory),
                "command": command,
            }
        )

    return {
        "schema_version": 1,
        "process_count": process_count,
        "paths": {
            "repo_root": str(REPO_ROOT),
            "binary": str(binary),
            "input": str(input_path),
            "output_dir": str(output_directory),
        },
        "parameters": {
            "hours": arguments.hours,
            "level": arguments.level,
            "sync_interval": arguments.sync_interval,
            "hydraulic_accuracy": arguments.hydraulic_accuracy,
            "hydraulic_max_trials": arguments.hydraulic_max_trials,
        },
        "experiments": experiments,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = parse_arguments(argv)
        plan = execution_plan(arguments, dict(os.environ))
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(plan, indent=2, sort_keys=True))
    if arguments.dry_run:
        return 0

    output_directory = Path(plan["paths"]["output_dir"])
    try:
        output_directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(
            f"configuration error: output directory already exists: "
            f"{output_directory}",
            file=sys.stderr,
        )
        return 2

    (output_directory / "execution-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    results = {"status": "complete", "experiments": []}
    process_environment = os.environ.copy()
    process_environment.setdefault("HWLOC_COMPONENTS", "-gl")

    for experiment in plan["experiments"]:
        working_directory = Path(experiment["working_directory"])
        working_directory.mkdir()
        log_path = working_directory / "console.log"
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                experiment["command"],
                cwd=working_directory,
                env=process_environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        record = {
            "actuations": experiment["actuations"],
            "return_code": completed.returncode,
            "duration_seconds": time.monotonic() - started,
            "log": str(log_path),
        }
        results["experiments"].append(record)
        if completed.returncode != 0:
            results["status"] = "failed"
            break
        try:
            statuses = search_statuses(
                working_directory, int(plan["process_count"]["value"])
            )
        except ConfigurationError as exc:
            record["search_statuses"] = []
            record["validation_error"] = str(exc)
            results["status"] = "inconclusive"
            break
        record["search_statuses"] = statuses
        if set(statuses) != {"CONCLUSIVE"}:
            results["status"] = "inconclusive"
            break

    (output_directory / "execution-results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if results["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
