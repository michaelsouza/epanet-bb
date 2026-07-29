#!/usr/bin/env python3
"""Run a persistent and reproducible Optuna grid search for EPANET-BB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "experiments" / "tuning-anytown-24h-a2.json"
PROTOCOL_SCHEMA_VERSION = 1


class ConfigurationError(ValueError):
    """The tuning protocol is incomplete or internally inconsistent."""


class TrialRejected(RuntimeError):
    """A run cannot contribute a valid timing observation."""


class ProcessTimeout(TrialRejected):
    """A solver process exceeded the timeout assigned to this attempt."""

    def __init__(self, duration_seconds: float, timeout_seconds: float):
        self.duration_seconds = duration_seconds
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"timeout after {duration_seconds:.3f}s "
            f"(limit {timeout_seconds:.3f}s)"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def load_configuration(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ConfigurationError("the configuration root must be a JSON object")
    return config


def require_positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def normalize_configuration(
    raw: dict[str, Any],
    *,
    config_path: Path,
    binary_override: str | None = None,
    input_override: str | None = None,
    output_override: str | None = None,
    timeout_override: float | None = None,
    repetitions_override: int | None = None,
    max_np_override: int | None = None,
    mpi_launcher_override: str | None = None,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "study_name",
        "binary",
        "input",
        "output_dir",
        "hours",
        "max_actuations",
        "search_space",
        "timeout_seconds",
        "repetitions",
        "sampler_seed",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise ConfigurationError(
            "missing required configuration keys: " + ", ".join(missing)
        )
    if raw["schema_version"] != PROTOCOL_SCHEMA_VERSION:
        raise ConfigurationError(
            f"unsupported schema_version {raw['schema_version']!r}; "
            f"expected {PROTOCOL_SCHEMA_VERSION}"
        )
    if not isinstance(raw["study_name"], str) or not raw["study_name"].strip():
        raise ConfigurationError("study_name must be a non-empty string")

    search_space = raw["search_space"]
    if not isinstance(search_space, dict):
        raise ConfigurationError("search_space must be a JSON object")
    expected_parameters = {"np", "level", "sync_interval"}
    if set(search_space) != expected_parameters:
        raise ConfigurationError(
            "search_space must contain exactly np, level, and sync_interval"
        )

    normalized_space: dict[str, list[int]] = {}
    for name in sorted(expected_parameters):
        values = search_space[name]
        if not isinstance(values, list) or not values:
            raise ConfigurationError(f"search_space.{name} must be a non-empty list")
        normalized = [
            require_positive_integer(item, f"search_space.{name}") for item in values
        ]
        if len(set(normalized)) != len(normalized):
            raise ConfigurationError(f"search_space.{name} contains duplicate values")
        normalized_space[name] = normalized

    if max_np_override is not None:
        if max_np_override <= 0:
            raise ConfigurationError("--max-np must be a positive integer")
        filtered_np = [val for val in normalized_space["np"] if val <= max_np_override]
        if not filtered_np:
            raise ConfigurationError(
                f"no process count in search_space.np is <= max_np={max_np_override}"
            )
        normalized_space["np"] = filtered_np

    binary = resolve_repo_path(binary_override or raw["binary"])
    input_path = resolve_repo_path(input_override or raw["input"])
    output_dir = resolve_repo_path(output_override or raw["output_dir"])
    if not binary.is_file():
        raise ConfigurationError(f"optimizer binary not found: {binary}")
    if not os.access(binary, os.X_OK):
        raise ConfigurationError(f"optimizer binary is not executable: {binary}")
    if not input_path.is_file():
        raise ConfigurationError(f"EPANET input file not found: {input_path}")

    launcher_value = mpi_launcher_override or raw.get("mpi_launcher") or shutil.which("mpiexec")
    if not launcher_value:
        raise ConfigurationError("mpiexec was not found; set mpi_launcher explicitly")
    launcher = resolve_repo_path(launcher_value) if "/" in launcher_value else Path(
        shutil.which(launcher_value) or launcher_value
    ).resolve()
    if not launcher.is_file():
        raise ConfigurationError(f"MPI launcher not found: {launcher}")

    launcher_args = raw.get("mpi_launcher_args", [])
    if not isinstance(launcher_args, list) or not all(
        isinstance(item, str) for item in launcher_args
    ):
        raise ConfigurationError("mpi_launcher_args must be a list of strings")
    environment = raw.get("environment", {})
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ConfigurationError("environment must map strings to strings")

    timeout = (
        timeout_override if timeout_override is not None else raw["timeout_seconds"]
    )
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigurationError("timeout_seconds must be positive")
    repetitions = (
        repetitions_override
        if repetitions_override is not None
        else raw["repetitions"]
    )
    repetitions = require_positive_integer(repetitions, "repetitions")

    racing_raw = raw.get("racing")
    racing = None
    if racing_raw is not None:
        if not isinstance(racing_raw, dict):
            raise ConfigurationError("racing must be a JSON object")
        expected_racing_keys = {
            "relative_cutoff_factor",
            "initial_incumbent",
            "validation_repetitions",
        }
        if set(racing_raw) != expected_racing_keys:
            raise ConfigurationError(
                "racing must contain exactly relative_cutoff_factor, "
                "initial_incumbent, and validation_repetitions"
            )
        factor = racing_raw["relative_cutoff_factor"]
        if (
            isinstance(factor, bool)
            or not isinstance(factor, (int, float))
            or factor < 1.0
        ):
            raise ConfigurationError(
                "racing.relative_cutoff_factor must be at least 1"
            )
        if repetitions % 2 == 0:
            raise ConfigurationError("racing requires an odd repetitions count")
        validation_repetitions = require_positive_integer(
            racing_raw["validation_repetitions"],
            "racing.validation_repetitions",
        )
        if validation_repetitions % 2 == 0:
            raise ConfigurationError(
                "racing.validation_repetitions must be odd"
            )
        initial_raw = racing_raw["initial_incumbent"]
        if not isinstance(initial_raw, dict) or set(initial_raw) != expected_parameters:
            raise ConfigurationError(
                "racing.initial_incumbent must contain exactly np, level, "
                "and sync_interval"
            )
        initial = {
            name: require_positive_integer(
                initial_raw[name], f"racing.initial_incumbent.{name}"
            )
            for name in sorted(expected_parameters)
        }
        if max_np_override is not None and initial["np"] not in normalized_space["np"]:
            initial["np"] = max(normalized_space["np"])
        for name, value in initial.items():
            if value not in normalized_space[name]:
                raise ConfigurationError(
                    f"racing.initial_incumbent.{name}={value} is not in "
                    f"search_space.{name}"
                )
        racing = {
            "relative_cutoff_factor": float(factor),
            "initial_incumbent": initial,
            "validation_repetitions": validation_repetitions,
        }

    hydraulic_accuracy = raw.get("hydraulic_accuracy")
    if hydraulic_accuracy is not None and (
        isinstance(hydraulic_accuracy, bool)
        or not isinstance(hydraulic_accuracy, (int, float))
        or hydraulic_accuracy <= 0
    ):
        raise ConfigurationError("hydraulic_accuracy must be null or positive")
    hydraulic_max_trials = raw.get("hydraulic_max_trials")
    if hydraulic_max_trials is not None:
        require_positive_integer(hydraulic_max_trials, "hydraulic_max_trials")

    return {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "config_file": str(config_path.resolve()),
        "study_name": raw["study_name"].strip(),
        "binary": str(binary),
        "input": str(input_path),
        "output_dir": str(output_dir),
        "hours": require_positive_integer(raw["hours"], "hours"),
        "max_actuations": require_positive_integer(
            raw["max_actuations"], "max_actuations"
        ),
        "search_space": normalized_space,
        "timeout_seconds": float(timeout),
        "repetitions": repetitions,
        "racing": racing,
        "sampler_seed": require_positive_integer(raw["sampler_seed"], "sampler_seed"),
        "mpi_launcher": str(launcher),
        "mpi_launcher_args": launcher_args,
        "environment": environment,
        "hydraulic_accuracy": hydraulic_accuracy,
        "hydraulic_max_trials": hydraulic_max_trials,
        "objective": "median_wall_time_seconds",
        "sampler": "optuna.samplers.GridSampler",
        "parallel_optuna_jobs": 1,
    }


def build_command(config: dict[str, Any], params: dict[str, int]) -> list[str]:
    command = [
        config["mpi_launcher"],
        *config["mpi_launcher_args"],
        "-n",
        str(params["np"]),
        config["binary"],
        "-i",
        config["input"],
        "-h",
        str(config["hours"]),
        "-a",
        str(config["max_actuations"]),
        "-l",
        str(params["level"]),
        "-s",
        str(params["sync_interval"]),
    ]
    if config["hydraulic_accuracy"] is not None:
        command.extend(
            ["--hydraulic-accuracy", str(config["hydraulic_accuracy"])]
        )
    if config["hydraulic_max_trials"] is not None:
        command.extend(
            ["--hydraulic-max-trials", str(config["hydraulic_max_trials"])]
        )
    return command


def run_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
    log_path: Path,
) -> tuple[int, float]:
    def terminate_process_group(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    child_environment = os.environ.copy()
    child_environment.update(environment)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=child_environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            terminate_process_group(process)
            duration = time.monotonic() - started
            raise ProcessTimeout(duration, timeout_seconds)
        except BaseException:
            terminate_process_group(process)
            raise
    return return_code, time.monotonic() - started


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise TrialRejected(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TrialRejected(f"JSON artifact is not an object: {path}")
    return value


def validate_artifacts(run_dir: Path, expected_ranks: int) -> dict[str, Any]:
    output_dir = run_dir / "outputs"
    stats_paths = sorted(output_dir.glob("*_stats.json"))
    best_paths = sorted(output_dir.glob("*_best.json"))
    if len(stats_paths) != expected_ranks:
        raise TrialRejected(
            f"expected {expected_ranks} statistics files, found {len(stats_paths)}"
        )
    if len(best_paths) != expected_ranks:
        raise TrialRejected(
            f"expected {expected_ranks} best-solution files, found {len(best_paths)}"
        )

    stats = [read_json(path) for path in stats_paths]
    best = [read_json(path) for path in best_paths]
    bad_stats = [
        path.name
        for path, value in zip(stats_paths, stats)
        if value.get("search", {}).get("status") != "CONCLUSIVE"
    ]
    bad_best = [
        path.name
        for path, value in zip(best_paths, best)
        if value.get("search_status") != "CONCLUSIVE"
    ]
    if bad_stats or bad_best:
        names = ", ".join(bad_stats + bad_best)
        raise TrialRejected(f"inconclusive search artifact(s): {names}")

    costs = [
        float(value["best_cost"])
        for value in best
        if isinstance(value.get("best_cost"), (int, float))
        and math.isfinite(float(value["best_cost"]))
    ]
    if not costs:
        raise TrialRejected("no finite best_cost was recorded")

    return {
        "best_cost": min(costs),
        "stats_files": [str(path.relative_to(run_dir)) for path in stats_paths],
        "best_files": [str(path.relative_to(run_dir)) for path in best_paths],
    }


def git_metadata() -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else None

    status = git("status", "--porcelain")
    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "status_porcelain": status,
    }


def protocol_record(config: dict[str, Any], optuna_version: str) -> dict[str, Any]:
    runner_path = Path(__file__).resolve()
    compatibility = {
        "configuration": {
            key: value
            for key, value in config.items()
            if key not in {"config_file", "output_dir"}
        },
        "binary_sha256": sha256_file(Path(config["binary"])),
        "input_sha256": sha256_file(Path(config["input"])),
        "runner_sha256": sha256_file(runner_path),
        "optuna_version": optuna_version,
    }
    return {
        "protocol_schema_version": PROTOCOL_SCHEMA_VERSION,
        "compatibility_sha256": canonical_hash(compatibility),
        "compatibility": compatibility,
        "provenance": {
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command_line": sys.argv,
            "python": sys.version,
            "platform": platform.platform(),
            "hostname": platform.node(),
            "git": git_metadata(),
        },
    }


def preserve_protocol(output_dir: Path, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "protocol.json"
    if path.exists():
        existing = read_json(path)
        if existing.get("compatibility_sha256") != record["compatibility_sha256"]:
            raise ConfigurationError(
                f"{path} belongs to an incompatible protocol; select a new "
                "--output-dir or restore the original configuration"
            )
        return
    with path.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")


def parameter_combinations(search_space: dict[str, list[int]]) -> Iterable[dict[str, int]]:
    names = sorted(search_space)
    for values in itertools.product(*(search_space[name] for name in names)):
        yield dict(zip(names, values))


def completed_parameter_sets(study: Any) -> set[tuple[tuple[str, int], ...]]:
    completed = set()
    for trial in study.trials:
        if (
            trial.state.name != "RUNNING"
            and set(trial.params) == {"np", "level", "sync_interval"}
        ):
            completed.add(
                tuple(sorted((name, int(value)) for name, value in trial.params.items()))
            )
    return completed


def enqueue_initial_incumbent(study: Any, config: dict[str, Any]) -> None:
    racing = config.get("racing")
    if racing is None:
        return
    study.enqueue_trial(
        racing["initial_incumbent"],
        skip_if_exists=True,
    )


def eligible_incumbent_seconds(study: Any) -> float | None:
    candidates = [
        float(trial.value)
        for trial in study.trials
        if trial.state.name == "COMPLETE"
        and trial.value is not None
        and trial.user_attrs.get("eligible_incumbent") is True
    ]
    return min(candidates) if candidates else None


def reuse_previous_parameter_result(
    trial: Any,
    params: dict[str, int],
    optuna: Any,
) -> float | None:
    parameter_key = tuple(sorted(params.items()))
    for previous in trial.study.trials:
        if previous.number == trial.number or previous.state.name in {
            "RUNNING",
            "WAITING",
        }:
            continue
        previous_key = tuple(
            sorted((name, int(value)) for name, value in previous.params.items())
        )
        if previous_key != parameter_key:
            continue

        trial.set_user_attr("duplicate_of_trial", previous.number)
        if previous.state.name == "COMPLETE" and previous.value is not None:
            for name in (
                "best_cost",
                "costs",
                "eligible_incumbent",
                "repetition_wall_times",
                "racing_wall_times",
                "racing_cutoff_count",
                "validation_performed",
            ):
                if name in previous.user_attrs:
                    trial.set_user_attr(name, previous.user_attrs[name])
            return float(previous.value)

        message = (
            f"parameter set already recorded by {previous.state.name.lower()} "
            f"trial {previous.number}"
        )
        trial.set_user_attr("failure", message)
        raise optuna.TrialPruned(message)
    return None


def write_measurement(run_dir: Path, measurement: dict[str, Any]) -> None:
    with (run_dir / "measurement.json").open("w", encoding="utf-8") as stream:
        json.dump(measurement, stream, indent=2, sort_keys=True)
        stream.write("\n")


def costs_are_consistent(costs: list[float]) -> bool:
    if not costs:
        return False
    reference = costs[0]
    return all(
        math.isclose(cost, reference, rel_tol=1.0e-10, abs_tol=1.0e-8)
        for cost in costs[1:]
    )


def export_study(study: Any, output_dir: Path) -> None:
    csv_path = output_dir / "trials.csv"
    columns = [
        "number",
        "state",
        "value",
        "np",
        "level",
        "sync_interval",
        "duration_seconds",
        "best_cost",
        "repetition_wall_times",
        "racing_wall_times",
        "racing_cutoff_count",
        "incumbent_seconds_at_start",
        "effective_timeout_seconds",
        "validation_performed",
        "duplicate_of_trial",
        "trial_directory",
        "failure",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for trial in study.trials:
            attrs = trial.user_attrs
            writer.writerow(
                {
                    "number": trial.number,
                    "state": trial.state.name,
                    "value": trial.value,
                    "np": trial.params.get("np"),
                    "level": trial.params.get("level"),
                    "sync_interval": trial.params.get("sync_interval"),
                    "duration_seconds": (
                        trial.duration.total_seconds() if trial.duration else None
                    ),
                    "best_cost": attrs.get("best_cost"),
                    "repetition_wall_times": json.dumps(
                        attrs.get("repetition_wall_times")
                    ),
                    "racing_wall_times": json.dumps(
                        attrs.get("racing_wall_times")
                    ),
                    "racing_cutoff_count": attrs.get("racing_cutoff_count"),
                    "incumbent_seconds_at_start": attrs.get(
                        "incumbent_seconds_at_start"
                    ),
                    "effective_timeout_seconds": attrs.get(
                        "effective_timeout_seconds"
                    ),
                    "validation_performed": attrs.get("validation_performed"),
                    "duplicate_of_trial": attrs.get("duplicate_of_trial"),
                    "trial_directory": attrs.get("trial_directory"),
                    "failure": attrs.get("failure"),
                }
            )

    complete = [trial for trial in study.trials if trial.state.name == "COMPLETE"]
    summary = {
        "study_name": study.study_name,
        "direction": study.direction.name,
        "trial_counts": {
            state: sum(trial.state.name == state for trial in study.trials)
            for state in ("COMPLETE", "PRUNED", "FAIL", "RUNNING", "WAITING")
        },
        "best_trial": None,
    }
    if complete:
        best = study.best_trial
        summary["best_trial"] = {
            "number": best.number,
            "objective_seconds": best.value,
            "params": best.params,
            "best_cost": best.user_attrs.get("best_cost"),
            "repetition_wall_times": best.user_attrs.get(
                "repetition_wall_times"
            ),
            "racing_wall_times": best.user_attrs.get("racing_wall_times"),
            "racing_cutoff_count": best.user_attrs.get("racing_cutoff_count"),
            "validation_performed": best.user_attrs.get("validation_performed"),
        }
    with (output_dir / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")


def create_objective(config: dict[str, Any], output_dir: Path, optuna: Any):
    def objective(trial: Any) -> float:
        params = {
            "np": trial.suggest_categorical("np", config["search_space"]["np"]),
            "level": trial.suggest_categorical(
                "level", config["search_space"]["level"]
            ),
            "sync_interval": trial.suggest_categorical(
                "sync_interval", config["search_space"]["sync_interval"]
            ),
        }
        previous_result = reuse_previous_parameter_result(
            trial, params, optuna
        )
        if previous_result is not None:
            return previous_result

        trial_dir = output_dir / "trials" / f"trial-{trial.number:05d}"
        trial_dir.mkdir(parents=True, exist_ok=False)
        trial.set_user_attr("trial_directory", str(trial_dir.relative_to(output_dir)))
        command = build_command(config, params)
        trial.set_user_attr("command", command)

        racing = config.get("racing")
        incumbent_seconds = (
            eligible_incumbent_seconds(trial.study) if racing is not None else None
        )
        relative_timeout = (
            incumbent_seconds * racing["relative_cutoff_factor"]
            if incumbent_seconds is not None
            else None
        )
        relative_cutoff_active = (
            relative_timeout is not None
            and relative_timeout < config["timeout_seconds"]
        )
        effective_timeout = (
            relative_timeout
            if relative_cutoff_active
            else config["timeout_seconds"]
        )
        trial.set_user_attr("incumbent_seconds_at_start", incumbent_seconds)
        trial.set_user_attr("effective_timeout_seconds", effective_timeout)
        trial.set_user_attr(
            "relative_cutoff_factor",
            racing["relative_cutoff_factor"] if racing is not None else None,
        )

        durations: list[float] = []
        costs: list[float] = []
        racing_wall_times: list[float] = []
        racing_cutoff_count = 0

        def record_completed_repetition(
            run_dir: Path,
            timeout_seconds: float,
        ) -> tuple[float, float]:
            log_path = run_dir / "console.log"
            return_code, duration = run_process(
                command,
                cwd=run_dir,
                environment=config["environment"],
                timeout_seconds=timeout_seconds,
                log_path=log_path,
            )
            if return_code != 0:
                raise TrialRejected(
                    f"{run_dir.name} returned exit status {return_code}"
                )
            artifacts = validate_artifacts(run_dir, params["np"])
            write_measurement(
                run_dir,
                {
                    "status": "complete",
                    "command": command,
                    "environment": config["environment"],
                    "return_code": return_code,
                    "timeout_seconds": timeout_seconds,
                    "wall_time_seconds": duration,
                    **artifacts,
                },
            )
            return duration, artifacts["best_cost"]

        def reject(message: str) -> None:
            trial.set_user_attr("failure", message)
            trial.set_user_attr("repetition_wall_times", durations)
            trial.set_user_attr("racing_wall_times", racing_wall_times)
            trial.set_user_attr("racing_cutoff_count", racing_cutoff_count)
            raise optuna.TrialPruned(message)

        try:
            for repetition in range(config["repetitions"]):
                run_dir = trial_dir / f"repetition-{repetition:03d}"
                run_dir.mkdir()
                try:
                    duration, cost = record_completed_repetition(
                        run_dir, effective_timeout
                    )
                except ProcessTimeout as exc:
                    if not relative_cutoff_active:
                        raise
                    racing_cutoff_count += 1
                    racing_wall_times.append(exc.duration_seconds)
                    write_measurement(
                        run_dir,
                        {
                            "status": "competitive_cutoff",
                            "command": command,
                            "environment": config["environment"],
                            "return_code": None,
                            "timeout_seconds": exc.timeout_seconds,
                            "wall_time_seconds": exc.duration_seconds,
                            "incumbent_seconds": incumbent_seconds,
                            "relative_cutoff_factor": racing[
                                "relative_cutoff_factor"
                            ],
                        },
                    )
                    trial.set_user_attr(
                        "racing_cutoff_count", racing_cutoff_count
                    )
                    if racing_cutoff_count >= config["repetitions"] // 2 + 1:
                        reject(
                            "racing cutoff: a majority of repetitions exceeded "
                            f"{effective_timeout:.3f}s, so the median cannot be "
                            "competitive"
                        )
                    continue
                durations.append(duration)
                racing_wall_times.append(duration)
                costs.append(cost)
        except TrialRejected as exc:
            trial.set_user_attr("failure", str(exc))
            trial.set_user_attr("repetition_wall_times", durations)
            trial.set_user_attr("racing_wall_times", racing_wall_times)
            trial.set_user_attr("racing_cutoff_count", racing_cutoff_count)
            raise optuna.TrialPruned(str(exc)) from exc

        trial.set_user_attr("racing_wall_times", racing_wall_times)
        trial.set_user_attr("racing_cutoff_count", racing_cutoff_count)
        if not costs_are_consistent(costs):
            message = f"repetitions produced inconsistent global costs: {costs}"
            trial.set_user_attr("costs", costs)
            reject(message)

        if racing_cutoff_count:
            racing_median = statistics.median(racing_wall_times)
            trial.set_user_attr("racing_median_seconds", racing_median)
            if incumbent_seconds is None or racing_median >= incumbent_seconds:
                reject(
                    f"racing median {racing_median:.3f}s cannot improve the "
                    f"{incumbent_seconds:.3f}s incumbent"
                )

            validation_durations: list[float] = []
            validation_costs: list[float] = []
            try:
                for repetition in range(racing["validation_repetitions"]):
                    run_dir = (
                        trial_dir / f"validation-repetition-{repetition:03d}"
                    )
                    run_dir.mkdir()
                    duration, cost = record_completed_repetition(
                        run_dir, config["timeout_seconds"]
                    )
                    validation_durations.append(duration)
                    validation_costs.append(cost)
            except TrialRejected as exc:
                trial.set_user_attr("validation_performed", True)
                trial.set_user_attr("validation_wall_times", validation_durations)
                trial.set_user_attr("failure", str(exc))
                trial.set_user_attr("repetition_wall_times", validation_durations)
                raise optuna.TrialPruned(str(exc)) from exc

            all_costs = costs + validation_costs
            if not costs_are_consistent(all_costs):
                trial.set_user_attr("costs", all_costs)
                reject(
                    "racing and validation repetitions produced inconsistent "
                    f"global costs: {all_costs}"
                )
            durations = validation_durations
            costs = all_costs
            trial.set_user_attr("validation_performed", True)
            trial.set_user_attr("validation_wall_times", validation_durations)
        else:
            trial.set_user_attr("validation_performed", False)

        trial.set_user_attr("repetition_wall_times", durations)
        trial.set_user_attr("best_cost", min(costs))
        trial.set_user_attr("costs", costs)
        trial.set_user_attr("eligible_incumbent", True)
        return statistics.median(durations)

    return objective


def optimize_unique_parameter_sets(
    study: Any,
    objective: Any,
    all_combinations: set[tuple[tuple[str, int], ...]],
    requested: int,
    callback: Any,
) -> None:
    completed_before = completed_parameter_sets(study) & all_combinations
    target_count = len(completed_before) + requested
    stagnant_trials = 0
    while len(completed_parameter_sets(study) & all_combinations) < target_count:
        count_before = len(completed_parameter_sets(study) & all_combinations)
        study.optimize(
            objective,
            n_trials=1,
            n_jobs=1,
            callbacks=[callback],
        )
        count_after = len(completed_parameter_sets(study) & all_combinations)
        if count_after == count_before:
            stagnant_trials += 1
            if stagnant_trials > len(all_combinations):
                raise ConfigurationError(
                    "Optuna repeatedly produced duplicate parameter sets"
                )
        else:
            stagnant_trials = 0


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run or resume the serial Optuna GridSampler protocol described "
            "by a JSON configuration."
        )
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--binary", help="override the optimizer executable")
    parser.add_argument("--input", help="override the EPANET input file")
    parser.add_argument("--output-dir", help="override the non-destructive run directory")
    parser.add_argument(
        "--timeout",
        type=float,
        help="absolute timeout per repetition, including uncensored validation",
    )
    parser.add_argument("--repetitions", type=int, help="repetitions per combination")
    parser.add_argument("--max-np", type=int, help="upper limit on MPI ranks per trial")
    parser.add_argument("--mpi-launcher", help="override the MPI launcher executable")
    parser.add_argument(
        "--n-trials",
        type=int,
        help="maximum new combinations to evaluate; default exhausts the grid",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and display the resolved protocol without creating files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    if args.n_trials is not None and args.n_trials <= 0:
        raise ConfigurationError("--n-trials must be positive")

    config_path = resolve_repo_path(args.config)
    config = normalize_configuration(
        load_configuration(config_path),
        config_path=config_path,
        binary_override=args.binary,
        input_override=args.input,
        output_override=args.output_dir,
        timeout_override=args.timeout,
        repetitions_override=args.repetitions,
        max_np_override=args.max_np,
        mpi_launcher_override=args.mpi_launcher,
    )
    total = math.prod(len(values) for values in config["search_space"].values())
    print(json.dumps({"resolved_protocol": config, "grid_size": total}, indent=2))
    if args.dry_run:
        return 0

    try:
        import optuna
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Optuna is missing. Activate .venv and run "
            "`pip install -r requirements.txt`."
        ) from exc

    output_dir = Path(config["output_dir"])
    preserve_protocol(output_dir, protocol_record(config, optuna.__version__))
    storage = f"sqlite:///{(output_dir / 'study.sqlite3').resolve()}"
    sampler = optuna.samplers.GridSampler(
        config["search_space"], seed=config["sampler_seed"]
    )
    study = optuna.create_study(
        study_name=config["study_name"],
        storage=storage,
        direction="minimize",
        sampler=sampler,
        load_if_exists=True,
    )
    study.set_user_attr(
        "protocol_compatibility_sha256",
        read_json(output_dir / "protocol.json")["compatibility_sha256"],
    )
    enqueue_initial_incumbent(study, config)

    all_combinations = {
        tuple(sorted(combination.items()))
        for combination in parameter_combinations(config["search_space"])
    }
    remaining = len(all_combinations - completed_parameter_sets(study))
    requested = remaining if args.n_trials is None else min(args.n_trials, remaining)
    print(
        f"Study {study.study_name}: {len(study.trials)} recorded, "
        f"{remaining} combinations remaining, {requested} requested."
    )
    if requested:
        objective = create_objective(config, output_dir, optuna)
        optimize_unique_parameter_sets(
            study,
            objective,
            all_combinations,
            requested,
            lambda current, _trial: export_study(current, output_dir),
        )
    export_study(study, output_dir)
    if any(trial.state.name == "COMPLETE" for trial in study.trials):
        print(
            f"Best trial {study.best_trial.number}: "
            f"{study.best_value:.6f}s, {study.best_params}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigurationError, TrialRejected) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
