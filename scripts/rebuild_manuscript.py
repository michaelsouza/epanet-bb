#!/usr/bin/env python3
"""Rebuild manuscript products from precomputed data without MPI or HPC."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).absolute().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "experiments" / "reproducibility.json"
DEFAULT_DATA_DIR = REPO_ROOT / "paper" / "data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "reproduced-manuscript"


class ConfigurationError(RuntimeError):
    """Raised when the reconstruction manifest cannot produce a safe plan."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def absolute_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.absolute()


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--select",
        action="append",
        help="rebuild only this task; may be supplied more than once",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved plan without creating files",
    )
    arguments = parser.parse_args(argv)
    if arguments.select:
        arguments.select = list(dict.fromkeys(arguments.select))
    return arguments


def substitute(value: str, variables: dict[str, str]) -> str:
    try:
        return value.format_map(variables)
    except KeyError as exc:
        raise ConfigurationError(f"unknown manifest placeholder: {exc}") from exc


def build_plan(arguments: argparse.Namespace) -> dict:
    manifest_path = absolute_path(arguments.manifest)
    data_directory = absolute_path(arguments.data_dir)
    output_directory = absolute_path(arguments.output_dir)
    if not manifest_path.is_file():
        raise ConfigurationError(f"manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ConfigurationError("manifest schema_version must be 1")

    tasks_by_id = {
        task["id"]: task for task in manifest.get("rebuild_tasks", [])
    }
    selected = arguments.select or list(tasks_by_id)
    unknown = [task_id for task_id in selected if task_id not in tasks_by_id]
    if unknown:
        raise ConfigurationError(f"unknown rebuild tasks: {', '.join(unknown)}")

    variables = {
        "repo_root": str(REPO_ROOT),
        "python": sys.executable,
        "data_dir": str(data_directory),
        "output_dir": str(output_directory),
    }
    resolved_tasks = []
    upstream_outputs: set[Path] = set()
    for task_id in selected:
        task = tasks_by_id[task_id]
        inputs = [
            absolute_path(substitute(value, variables))
            for value in task.get("inputs", [])
        ]
        missing = [
            path
            for path in inputs
            if not path.exists() and path not in upstream_outputs
        ]
        if missing:
            raise ConfigurationError(
                f"{task_id} is missing inputs: "
                + ", ".join(str(path) for path in missing)
            )
        outputs = [
            absolute_path(substitute(value, variables))
            for value in task.get("outputs", [])
        ]
        commands = [
            [substitute(argument, variables) for argument in command]
            for command in task.get("commands", [])
        ]
        if task.get("requires_hpc", False) or task.get("requires_mpi", False):
            raise ConfigurationError(
                f"rebuild task {task_id} requires HPC/MPI execution, "
                "which is prohibited in the local rebuild workflow"
            )
        resolved_tasks.append(
            {
                "id": task_id,
                "requires_hpc": bool(task.get("requires_hpc", False)),
                "inputs": [str(path) for path in inputs],
                "outputs": [str(path) for path in outputs],
                "commands": commands,
            }
        )
        upstream_outputs.update(outputs)

    return {
        "schema_version": 1,
        "manifest": str(manifest_path),
        "data_dir": str(data_directory),
        "output_dir": str(output_directory),
        "tasks": resolved_tasks,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = parse_arguments(argv)
        plan = build_plan(arguments)
    except (ConfigurationError, json.JSONDecodeError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(plan, indent=2, sort_keys=True))
    if arguments.dry_run:
        return 0

    output_directory = Path(plan["output_dir"])
    try:
        output_directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(
            f"configuration error: output directory already exists: "
            f"{output_directory}",
            file=sys.stderr,
        )
        return 2
    (output_directory / "rebuild-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    logs_directory = output_directory / "logs"
    logs_directory.mkdir()
    process_environment = os.environ.copy()
    process_environment.setdefault("MPLBACKEND", "Agg")
    results = {"status": "complete", "tasks": []}

    for task in plan["tasks"]:
        return_codes = []
        logs = []
        started = time.monotonic()
        for command_number, command in enumerate(task["commands"], start=1):
            log_path = logs_directory / (
                f"{task['id']}-{command_number:02d}.log"
            )
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command,
                    cwd=output_directory,
                    env=process_environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            return_codes.append(completed.returncode)
            logs.append(str(log_path))
            if completed.returncode != 0:
                break

        missing_outputs = [
            output
            for output in task["outputs"]
            if not Path(output).is_file() or Path(output).stat().st_size == 0
        ]
        task_result = {
            "id": task["id"],
            "return_codes": return_codes,
            "duration_seconds": time.monotonic() - started,
            "logs": logs,
            "outputs": task["outputs"],
            "output_sha256": {
                output: sha256(Path(output))
                for output in task["outputs"]
                if output not in missing_outputs
            },
            "missing_outputs": missing_outputs,
        }
        results["tasks"].append(task_result)
        if any(code != 0 for code in return_codes) or missing_outputs:
            results["status"] = "failed"
            break

    (output_directory / "rebuild-results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if results["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
