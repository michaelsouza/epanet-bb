#!/usr/bin/env python3
"""Audit a completed accuracy-sensitivity campaign and emit compact evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


class AuditError(RuntimeError):
    """Raised when a sensitivity campaign is incomplete or inconsistent."""


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise AuditError(f"missing input: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_manifest_digest(campaign: Path, records: list[dict]) -> tuple[int, str]:
    paths = []
    for record in records:
        working = Path(record["working_directory"])
        if record["kind"] == "fixed":
            result = Path(record["result"])
            if not result.is_file() or sha256_file(result) != record["result_sha256"]:
                raise AuditError(f"fixed result hash mismatch: {record['id']}")
            paths.append(result)
        else:
            output = working / "outputs"
            stats = sorted(output.glob("*_stats.json"))
            best = sorted(output.glob("*_best.json"))
            if len(stats) != record["stats_files"] or len(best) != record["best_files"]:
                raise AuditError(f"rank artifact count mismatch: {record['id']}")
            paths.extend(stats)
            paths.extend(best)
    digest = hashlib.sha256()
    for path in sorted(paths):
        try:
            relative = path.relative_to(campaign)
        except ValueError as exc:
            raise AuditError(f"artifact is outside campaign: {path}") from exc
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return len(paths), digest.hexdigest()


def audit_campaign(campaign: Path) -> dict:
    campaign = campaign.absolute()
    plan_path = campaign / "accuracy-sensitivity-plan.json"
    receipt_path = campaign / "accuracy-sensitivity-results.json"
    aggregate_path = campaign / "accuracy-sensitivity-aggregate.json"
    plan = load_json(plan_path)
    receipt = load_json(receipt_path)
    aggregate = load_json(aggregate_path)
    if plan.get("profile") != "final":
        raise AuditError("only a final-profile campaign is manuscript evidence")
    if plan.get("metadata", {}).get("git", {}).get("dirty") is not False:
        raise AuditError("campaign did not record a clean Git tree")
    if receipt.get("status") != "complete":
        raise AuditError("campaign receipt is not complete")
    planned_ids = [cell["id"] for cell in plan.get("cells", [])]
    records = receipt.get("records", [])
    record_ids = [record["id"] for record in records]
    if record_ids != planned_ids or len(set(record_ids)) != len(record_ids):
        raise AuditError("receipt records do not match the planned cell order")
    fixed = [record for record in records if record["kind"] == "fixed"]
    optimization = [record for record in records if record["kind"] == "optimization"]
    if len(fixed) != 45 or len(optimization) != 27:
        raise AuditError("final campaign must contain 45 fixed and 27 optimization cells")
    expected_fixed_grid = Counter({
        (actuations, accuracy_id): 5
        for actuations in (1, 2, 3)
        for accuracy_id in ("1e-3", "1e-4", "1e-7")
    })
    expected_optimization_grid = Counter({
        (actuations, accuracy_id): 3
        for actuations in (1, 2, 3)
        for accuracy_id in ("1e-3", "1e-4", "1e-7")
    })
    fixed_grid = Counter(
        (record.get("actuations"), record.get("accuracy_id")) for record in fixed
    )
    optimization_grid = Counter(
        (record.get("actuations"), record.get("accuracy_id"))
        for record in optimization
    )
    if fixed_grid != expected_fixed_grid:
        raise AuditError("fixed campaign does not contain the declared 5-repetition grid")
    if optimization_grid != expected_optimization_grid:
        raise AuditError(
            "optimization campaign does not contain the declared 3-repetition grid"
        )

    for record in fixed:
        if (
            record.get("return_code") != 0
            or record.get("timed_out") is not False
            or record.get("hydraulic_converged") is not True
            or record.get("feasible") is not True
        ):
            raise AuditError(f"fixed cell is not conclusive and feasible: {record['id']}")
    for record in optimization:
        cost = record.get("best_cost")
        if (
            record.get("return_code") != 0
            or record.get("timed_out") is not False
            or record.get("conclusive") is not True
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or record.get("stats_files") != record.get("np")
            or record.get("best_files") != record.get("np")
            or record.get("hydraulic_nonconvergence_events") != 0
        ):
            raise AuditError(f"optimization cell is not conclusive: {record['id']}")

    schedule_counts = {}
    cost_counts = {}
    for actuations in (1, 2, 3):
        actuation_records = [
            record for record in optimization if record["actuations"] == actuations
        ]
        schedule_counts[str(actuations)] = len(
            {record["schedule_sha256"] for record in actuation_records}
        )
        for accuracy_id in ("1e-3", "1e-4", "1e-7"):
            group = [
                record for record in actuation_records
                if record["accuracy_id"] == accuracy_id
            ]
            if len(group) != 3:
                raise AuditError(
                    f"optimization group has wrong repetitions: a{actuations} {accuracy_id}"
                )
            cost_counts[f"a{actuations}-{accuracy_id}"] = len(
                {record["best_cost"] for record in group}
            )
    if set(schedule_counts.values()) != {1} or set(cost_counts.values()) != {1}:
        raise AuditError("schedule or cost is not deterministic across repetitions")

    artifact_count, artifact_digest = artifact_manifest_digest(campaign, records)
    sources = {}
    for path in sorted(campaign.glob("*summary*")) + sorted(campaign.glob("*aggregate*")):
        if path.is_file():
            sources[path.name] = sha256_file(path)
    sources[plan_path.name] = sha256_file(plan_path)
    sources[receipt_path.name] = sha256_file(receipt_path)
    return {
        "schema_version": 1,
        "campaign": str(campaign),
        "commit": plan["metadata"]["git"]["commit"],
        "executable_sha256": plan["metadata"]["inputs"]["binary"]["sha256"],
        "network_sha256": plan["metadata"]["inputs"]["input"]["sha256"],
        "configuration_sha256": plan["metadata"]["inputs"]["config"]["sha256"],
        "compatibility_sha256": plan["compatibility_sha256"],
        "protocol": plan["protocol"],
        "fixed_records": len(fixed),
        "optimization_records": len(optimization),
        "rank_stats_files": sum(record["stats_files"] for record in optimization),
        "rank_best_files": sum(record["best_files"] for record in optimization),
        "all_return_codes": sorted({record["return_code"] for record in records}),
        "timeouts": sum(record["timed_out"] is True for record in records),
        "hydraulic_nonconvergence_events": sum(
            int(record.get("hydraulic_nonconvergence_events", 0))
            for record in optimization
        ),
        "duration_seconds_sum": sum(record["duration_seconds"] for record in records),
        "unique_schedules_across_accuracies": schedule_counts,
        "unique_costs_per_repeated_cell": cost_counts,
        "artifact_count": artifact_count,
        "artifact_manifest_sha256": artifact_digest,
        "source_sha256": sources,
        "aggregate": aggregate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        payload = audit_campaign(arguments.campaign)
    except (AuditError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"accuracy sensitivity audit failed: {exc}")
        return 1
    output = arguments.output or (
        arguments.campaign / "accuracy-sensitivity-audit.json"
    )
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"audited {payload['fixed_records']} fixed and "
        f"{payload['optimization_records']} optimization records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
