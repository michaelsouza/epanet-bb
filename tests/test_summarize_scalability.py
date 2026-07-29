#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_scalability", ROOT / "scripts" / "summarize_scalability.py"
)
SUMMARY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SUMMARY)


class SummarizeScalabilityTests(unittest.TestCase):
    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def make_campaign(self, root: Path, number: int, times: dict[int, float]):
        campaign = root / f"round-{number}"
        commands = []
        for process_count, duration in times.items():
            directory = campaign / "scalability" / f"np-{process_count:03d}"
            commands.append(
                {
                    "np": process_count,
                    "argv": [
                        "python",
                        "run_experiments.py",
                        "--hours",
                        "24",
                        "--actuations",
                        "2",
                        "--level",
                        "8",
                        "--sync-interval",
                        "32768",
                    ],
                    "environment": {},
                    "output_dir": str(directory),
                }
            )
            self.write_json(
                directory / "execution-results.json",
                {
                    "status": "complete",
                    "experiments": [
                        {"return_code": 0, "duration_seconds": duration}
                    ],
                },
            )
            outputs = directory / "actuations-02" / "outputs"
            for rank in range(process_count):
                metadata = {
                    "mpi_processes": process_count,
                    "configuration": {
                        "horizon_hours": 24,
                        "max_cycles_per_pump": 2,
                        "task_decomposition_level": 8,
                        "sync_interval": 32768,
                    },
                    "software": {"executable_sha256": "binary-hash"},
                }
                self.write_json(
                    outputs / f"run_r_{rank:02d}_stats.json",
                    {
                        "search": {"status": "CONCLUSIVE"},
                        "metadata": metadata,
                        "time_total": duration - rank / 10,
                        "tasks_processed": 12 // process_count,
                        "disaggregation_summary": {
                            "candidate_assignments": 1000 // process_count + number
                        },
                    },
                )
                self.write_json(
                    outputs / f"run_r_{rank:02d}_best.json",
                    {
                        "search_status": "CONCLUSIVE",
                        "best_cost": 123.5 if rank == 0 else 130.0,
                    },
                )
        self.write_json(
            campaign / "campaign-plan.json",
            {
                "metadata": {
                    "git": {"commit": "same-commit", "dirty": False},
                    "executable": {"sha256": "binary-hash"},
                },
                "compatibility_sha256": f"protocol-{number}",
                "tasks": [{"id": "scalability", "commands": commands}],
            },
        )
        self.write_json(
            campaign / "campaign-results.json",
            {
                "status": "complete",
                "tasks": [
                    {
                        "return_codes": [0] * len(commands),
                        "duration_seconds": sum(times.values()),
                    }
                ],
            },
        )
        return campaign

    def test_summarizes_observed_medians_and_paired_speedups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaigns = [
                self.make_campaign(root, 1, {1: 100.0, 2: 55.0, 4: 30.0}),
                self.make_campaign(root, 2, {1: 110.0, 2: 50.0, 4: 25.0}),
                self.make_campaign(root, 3, {1: 105.0, 2: 52.5, 4: 27.5}),
            ]

            summary = SUMMARY.summarize_campaigns(campaigns)

            self.assertEqual(summary["repetition_count"], 3)
            self.assertEqual(summary["global_best_cost"], 123.5)
            self.assertEqual(summary["tasks_processed_per_point"], 12)
            points = {item["process_count"]: item for item in summary["points"]}
            four = points[4]["summary"]
            self.assertEqual(four["wall_seconds_median"], 27.5)
            self.assertEqual(four["wall_seconds_minimum"], 25.0)
            self.assertEqual(four["wall_seconds_maximum"], 30.0)
            expected_speedup = 105.0 / 27.5
            self.assertEqual(four["paired_speedup_median"], expected_speedup)
            self.assertEqual(
                four["paired_parallel_efficiency_median"],
                expected_speedup / 4,
            )

            csv_path = root / "summary.csv"
            SUMMARY.write_csv(summary, csv_path)
            self.assertNotIn(b"\r\n", csv_path.read_bytes())

    def test_rejects_an_even_repetition_count(self) -> None:
        with self.assertRaisesRegex(SUMMARY.AuditError, "odd number"):
            SUMMARY.summarize_campaigns([Path("one"), Path("two")])

    def test_rejects_different_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaigns = [
                self.make_campaign(root, number, {1: 10.0, 2: 5.0})
                for number in range(1, 4)
            ]
            plan_path = campaigns[-1] / "campaign-plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["metadata"]["git"]["commit"] = "different-commit"
            self.write_json(plan_path, plan)

            with self.assertRaisesRegex(SUMMARY.AuditError, "different Git commits"):
                SUMMARY.summarize_campaigns(campaigns)


if __name__ == "__main__":
    unittest.main()
