#!/usr/bin/env python3
"""Replay published and revised schedules under the same feasibility policy."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).absolute().parents[1]
EXTERNAL_SOURCES = ("Cimorelli2020", "Costa2016", "Paola2025")
EXPECTED_FEASIBILITY = {
    "Cimorelli2020": {1: False, 2: False, 3: False},
    "Costa2016": {1: True, 2: True, 3: True},
    "Paola2025": {1: True, 2: False, 3: False},
    "Souza2026": {1: True, 2: True, 3: True},
}


class EvaluationError(RuntimeError):
    """Raised when schedule replay cannot produce auditable evidence."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise EvaluationError(f"missing input: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def revised_solutions(final_summary: dict) -> list[tuple[str, int, dict]]:
    solutions = []
    for case in final_summary.get("cases", []):
        actuations = int(case["actuations"])
        solutions.append(
            (
                "Souza2026",
                actuations,
                {
                    "best_cost": case["global_best_cost"],
                    "best_x": case["best_x"],
                    "best_y": case["best_y"],
                    "max_actuations": actuations,
                },
            )
        )
    if [actuations for _, actuations, _ in solutions] != [1, 2, 3]:
        raise EvaluationError("final summary must contain NA_max=1,2,3")
    return solutions


def external_solutions(directory: Path) -> list[tuple[str, int, dict, Path]]:
    solutions = []
    pattern = re.compile(r"run_(.+)_a_(\d+)\.json$")
    for source in EXTERNAL_SOURCES:
        for actuations in (1, 2, 3):
            path = directory / f"run_{source}_a_{actuations:02d}.json"
            match = pattern.match(path.name)
            if not match:
                raise EvaluationError(f"unexpected comparison filename: {path}")
            payload = load_json(path)
            if int(payload.get("max_actuations", -1)) != actuations:
                raise EvaluationError(f"actuation metadata mismatch: {path}")
            solutions.append((source, actuations, payload, path))
    return solutions


def evaluate_schedules(
    evaluator: Path,
    network: Path,
    comparison_data_dir: Path,
    final_summary_path: Path,
    mpi_launcher: Path,
    output_dir: Path,
) -> dict:
    for path in (evaluator, network, final_summary_path, mpi_launcher):
        if not path.is_file():
            raise EvaluationError(f"missing executable or input: {path}")
    final_summary = load_json(final_summary_path)
    solutions = [
        (source, actuations, payload, path)
        for source, actuations, payload, path in external_solutions(
            comparison_data_dir
        )
    ]
    solutions.extend(
        (source, actuations, payload, final_summary_path)
        for source, actuations, payload in revised_solutions(final_summary)
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    requests_dir = output_dir / "requests"
    results_dir = output_dir / "results"
    logs_dir = output_dir / "logs"
    requests_dir.mkdir()
    results_dir.mkdir()
    logs_dir.mkdir()
    environment = os.environ.copy()
    environment["HWLOC_COMPONENTS"] = "-gl"
    records = []

    for source, actuations, payload, source_path in solutions:
        best_x = payload.get("best_x")
        best_y = payload.get("best_y")
        if not isinstance(best_x, list) or len(best_x) != 75:
            raise EvaluationError(f"{source} NA_max={actuations}: invalid best_x")
        if not isinstance(best_y, list) or len(best_y) != 25:
            raise EvaluationError(f"{source} NA_max={actuations}: invalid best_y")
        request_payload = {
            "best_x": best_x,
            "best_y": best_y,
            "h_max": 24,
            "max_actuations": actuations,
            "inp_file": str(network),
            "schedule_mode": "binary",
            "verbose": 0,
        }
        stem = f"{source}-a{actuations}"
        request_path = requests_dir / f"{stem}.json"
        result_path = results_dir / f"{stem}.json"
        log_path = logs_dir / f"{stem}.log"
        request_path.write_text(
            json.dumps(request_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        command = [
            str(mpi_launcher),
            "--map-by",
            "core",
            "--bind-to",
            "core",
            "-n",
            "1",
            str(evaluator),
            str(request_path),
            str(result_path),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_path.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode not in (0, 1) or not result_path.is_file():
            raise EvaluationError(
                f"{source} NA_max={actuations}: evaluator failed with "
                f"code {completed.returncode}"
            )
        observed = load_json(result_path)
        feasible = bool(observed["feasible"])
        if completed.returncode != (0 if feasible else 1):
            raise EvaluationError(f"{source} NA_max={actuations}: status/code mismatch")
        records.append(
            {
                "source": source,
                "actuations": actuations,
                "source_artifact": str(source_path.absolute()),
                "source_artifact_sha256": sha256(source_path),
                "published_cost": float(payload["best_cost"]),
                "feasible": feasible,
                "prune_reason": observed["prune_reason"],
                "hour_failed": observed["hour_failed"],
                "reevaluated_cost": float(observed["cost"]),
                "periodic_switch_counts": observed["periodic_switch_counts"],
                "request": str(request_path.relative_to(output_dir)),
                "result": str(result_path.relative_to(output_dir)),
                "log": str(log_path.relative_to(output_dir)),
            }
        )

    summary = {
        "schema_version": 1,
        "evaluator_sha256": sha256(evaluator),
        "network_sha256": sha256(network),
        "final_summary_sha256": sha256(final_summary_path),
        "schedule_mode": "binary",
        "periodic_horizon": "hours 1-24 with closure from hour 24 to hour 1",
        "records": records,
    }
    (output_dir / "comparison-feasibility-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    csv_path = output_dir / "comparison-feasibility-summary.csv"
    fields = [
        "source",
        "actuations",
        "published_cost",
        "feasible",
        "prune_reason",
        "hour_failed",
        "reevaluated_cost",
        "periodic_switch_counts",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = {key: record[key] for key in fields}
            row["periodic_switch_counts"] = "/".join(
                str(value) for value in record["periodic_switch_counts"]
            )
            writer.writerow(row)
    return summary


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator", required=True, type=Path)
    parser.add_argument(
        "--network", type=Path, default=ROOT / "networks" / "any-town.inp"
    )
    parser.add_argument(
        "--comparison-data-dir",
        type=Path,
        default=ROOT / "experiments" / "comparison-schedules",
    )
    parser.add_argument(
        "--final-summary",
        type=Path,
        default=ROOT / "experiments" / "results" / "final-cases-anytown-24h-summary.json",
    )
    parser.add_argument("--mpi-launcher", type=Path, default=Path("/usr/bin/mpiexec"))
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = evaluate_schedules(
            arguments.evaluator.absolute(),
            arguments.network.absolute(),
            arguments.comparison_data_dir.absolute(),
            arguments.final_summary.absolute(),
            arguments.mpi_launcher.absolute(),
            arguments.output_dir.absolute(),
        )
    except (EvaluationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"comparison schedule evaluation failed: {exc}")
        return 1
    feasible = sum(record["feasible"] for record in summary["records"])
    print(f"evaluated {len(summary['records'])} schedules; {feasible} are feasible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
