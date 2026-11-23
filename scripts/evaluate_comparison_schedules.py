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
import shutil
import subprocess


ROOT = Path(__file__).absolute().parents[1]
# Chronological order of publication.
EXTERNAL_SOURCES = ("Costa2016", "Cimorelli2020", "Cimorelli2021", "Paola2025")
EXPECTED_FEASIBILITY = {
    "Costa2016": {1: True, 2: True, 3: True},
    "Cimorelli2020": {1: False, 2: False, 3: False},
    "Cimorelli2021": {1: True, 2: True, 3: True},
    "Paola2025": {1: False, 2: False, 3: False},
    "Souza2026": {1: True, 2: True, 3: True},
}
# Re-evaluated costs ($) asserted to within COST_TOLERANCE.
EXPECTED_COSTS = {
    "Cimorelli2021": {1: 3915.785179, 2: 3618.595780, 3: 3575.538064},
}
# Under the single-day switch count (switch-ons between consecutive hours,
# no closure from hour 24 to hour 1) only the schedules optimized under that
# convention carry an expectation; the other external sources are recorded.
EXPECTED_SINGLE_DAY_FEASIBILITY = {
    "Cimorelli2020": {1: True, 2: True, 3: True},
    "Souza2026": {1: True, 2: True, 3: True},
}
EXPECTED_SINGLE_DAY_COSTS = {
    "Cimorelli2020": {1: 3634.602760, 2: 3580.033092, 3: 3575.463604},
}
SWITCH_COUNT_CONVENTIONS = ("periodic", "single_day")
EXPECTATIONS = {
    "periodic": (EXPECTED_FEASIBILITY, EXPECTED_COSTS),
    "single_day": (EXPECTED_SINGLE_DAY_FEASIBILITY, EXPECTED_SINGLE_DAY_COSTS),
}
COST_TOLERANCE = 1e-6
DEFAULT_FINAL_SUMMARY = (
    ROOT / "experiments" / "results" / "final-cases-anytown-24h-summary.json"
)


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


def executable_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.absolute()
    resolved = shutil.which(str(candidate))
    if resolved is None:
        raise EvaluationError(f"executable was not found on PATH: {candidate}")
    return Path(resolved).absolute()


def repository_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise EvaluationError(
            f"source artifact is outside the repository: {path}"
        ) from exc


def recorded_convention(payload: dict) -> str:
    """Switch-count convention recorded in a summary; absent means periodic."""
    return str(payload.get("switch_count_convention", "periodic"))


def expectation_mismatches(summary: dict) -> list[str]:
    """Records that contradict the expectations of the summary's convention."""
    feasibility, costs = EXPECTATIONS[recorded_convention(summary)]
    mismatches = []
    for record in summary["records"]:
        source, actuations = record["source"], record["actuations"]
        expected = feasibility.get(source, {}).get(actuations)
        if expected is not None and record["feasible"] != expected:
            mismatches.append(
                f"{source} NA_max={actuations}: feasible={record['feasible']}, "
                f"expected {expected}"
            )
        cost = costs.get(source, {}).get(actuations)
        if cost is not None and abs(record["reevaluated_cost"] - cost) > COST_TOLERANCE:
            mismatches.append(
                f"{source} NA_max={actuations}: cost "
                f"{record['reevaluated_cost']:.6f}, expected {cost:.6f}"
            )
    return mismatches


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
    final_summary_path: Path | None,
    mpi_launcher: Path,
    output_dir: Path,
    switch_count_convention: str = "periodic",
) -> dict:
    """Replay every schedule; the revised solutions need a final summary.

    The final summary may be omitted only under the single-day convention,
    and its recorded convention must match the requested one.
    """
    if switch_count_convention not in SWITCH_COUNT_CONVENTIONS:
        raise EvaluationError(
            f"unknown switch-count convention: {switch_count_convention}"
        )
    single_day = switch_count_convention == "single_day"
    if final_summary_path is None and not single_day:
        raise EvaluationError("the periodic comparison requires a final summary")
    required = [evaluator, network, mpi_launcher]
    if final_summary_path is not None:
        required.append(final_summary_path)
    for path in required:
        if not path.is_file():
            raise EvaluationError(f"missing executable or input: {path}")
    solutions = [
        (source, actuations, payload, path)
        for source, actuations, payload, path in external_solutions(
            comparison_data_dir
        )
    ]
    if final_summary_path is not None:
        final_summary = load_json(final_summary_path)
        observed_convention = recorded_convention(final_summary)
        if observed_convention != switch_count_convention:
            raise EvaluationError(
                f"final summary {final_summary_path} records the "
                f"{observed_convention} switch count; expected "
                f"{switch_count_convention}"
            )
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
        if single_day:
            request_payload["switch_count_convention"] = switch_count_convention
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
        if recorded_convention(observed) != switch_count_convention:
            raise EvaluationError(
                f"{source} NA_max={actuations}: evaluator did not apply the "
                f"{switch_count_convention} switch count"
            )
        feasible = bool(observed["feasible"])
        if completed.returncode != (0 if feasible else 1):
            raise EvaluationError(f"{source} NA_max={actuations}: status/code mismatch")
        record = {
            "source": source,
            "actuations": actuations,
            "source_artifact": repository_path(source_path),
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
        if single_day:
            record["single_day_switch_on_counts"] = observed[
                "single_day_switch_on_counts"
            ]
        records.append(record)

    summary = {
        "schema_version": 1,
        "evaluator_sha256": sha256(evaluator),
        "network_sha256": sha256(network),
        "final_summary_sha256": (
            sha256(final_summary_path) if final_summary_path is not None else None
        ),
        "schedule_mode": "binary",
        "records": records,
    }
    # Periodic summaries keep their historical layout without a convention
    # field; single-day summaries record it explicitly.
    if single_day:
        summary["switch_count_convention"] = switch_count_convention
        summary["switch_count_horizon"] = (
            "switch-ons between consecutive hours 1-24 without closure"
        )
    else:
        summary["periodic_horizon"] = "hours 1-24 with closure from hour 24 to hour 1"
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
    count_fields = ["periodic_switch_counts"]
    if single_day:
        fields.append("single_day_switch_on_counts")
        count_fields.append("single_day_switch_on_counts")
        fields.insert(0, "switch_count_convention")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = {
                key: (
                    switch_count_convention
                    if key == "switch_count_convention"
                    else record[key]
                )
                for key in fields
            }
            for key in count_fields:
                row[key] = "/".join(str(value) for value in record[key])
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
        "--switch-count-convention",
        choices=SWITCH_COUNT_CONVENTIONS,
        default="periodic",
        help="switch-count limits applied by the evaluator (default: periodic)",
    )
    parser.add_argument(
        "--final-summary",
        type=Path,
        help=(
            "final-cases summary with the revised solutions; it must record "
            "the selected convention. Defaults to "
            f"{DEFAULT_FINAL_SUMMARY.relative_to(ROOT)} for the periodic "
            "convention; without it the single-day evaluation omits the "
            "revised solutions"
        ),
    )
    parser.add_argument("--mpi-launcher", default="mpiexec")
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.final_summary is None and arguments.switch_count_convention == "periodic":
        arguments.final_summary = DEFAULT_FINAL_SUMMARY
    return arguments


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = evaluate_schedules(
            arguments.evaluator.absolute(),
            arguments.network.absolute(),
            arguments.comparison_data_dir.absolute(),
            (
                arguments.final_summary.absolute()
                if arguments.final_summary is not None
                else None
            ),
            executable_path(arguments.mpi_launcher),
            arguments.output_dir.absolute(),
            arguments.switch_count_convention,
        )
    except (EvaluationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"comparison schedule evaluation failed: {exc}")
        return 1
    feasible = sum(record["feasible"] for record in summary["records"])
    print(f"evaluated {len(summary['records'])} schedules; {feasible} are feasible")
    for mismatch in expectation_mismatches(summary):
        print(f"warning: expectation mismatch: {mismatch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
