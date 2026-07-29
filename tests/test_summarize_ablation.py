#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_ablation", ROOT / "scripts" / "summarize_ablation.py"
)
SUMMARY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SUMMARY)


class SummarizeAblationTests(unittest.TestCase):
    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def make_campaign(self, root: Path, number: int, baseline: float, variant: float):
        campaign = root / f"round-{number}"
        commands = []
        for variant_id, environment in (
            ("baseline", {}),
            ("no-snapshots", {"BB_ENABLE_SNAPSHOTS": "0"}),
        ):
            directory = campaign / "ablation" / variant_id
            commands.append(
                {
                    "np": 2,
                    "argv": [
                        "python",
                        "run_experiments.py",
                        "--hours",
                        "24",
                        "--actuations",
                        "3",
                        "--level",
                        "8",
                        "--sync-interval",
                        "32768",
                    ],
                    "environment": environment,
                    "output_dir": str(directory),
                }
            )
            duration = baseline if variant_id == "baseline" else variant
            self.write_json(
                directory / "execution-results.json",
                {
                    "status": "complete",
                    "experiments": [
                        {"return_code": 0, "duration_seconds": duration}
                    ],
                },
            )
            outputs = directory / "actuations-03" / "outputs"
            for rank in range(2):
                metadata = {
                    "mpi_processes": 2,
                    "configuration": {
                        "horizon_hours": 24,
                        "max_cycles_per_pump": 3,
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
                        "time_total": duration - rank,
                        "tasks_processed": 10,
                        "disaggregation_summary": {
                            "candidate_assignments": 100 + number
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
                    "git": {"commit": f"commit-{number}", "dirty": False},
                    "executable": {"sha256": "binary-hash"},
                },
                "compatibility_sha256": f"protocol-{number}",
                "tasks": [{"id": "ablation", "commands": commands}],
            },
        )
        self.write_json(
            campaign / "campaign-results.json",
            {
                "status": "complete",
                "tasks": [
                    {
                        "return_codes": [0, 0],
                        "duration_seconds": baseline + variant,
                    }
                ],
            },
        )
        return campaign

    def test_summarizes_observed_medians_and_paired_slowdowns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaigns = [
                self.make_campaign(root, 1, 10.0, 20.0),
                self.make_campaign(root, 2, 12.0, 30.0),
                self.make_campaign(root, 3, 11.0, 22.0),
            ]

            summary = SUMMARY.summarize_campaigns(campaigns)

            self.assertEqual(summary["repetition_count"], 3)
            self.assertEqual(summary["global_best_cost"], 123.5)
            variants = {item["id"]: item for item in summary["variants"]}
            self.assertEqual(
                variants["baseline"]["summary"]["wall_seconds_median"], 11.0
            )
            no_snapshots = variants["no-snapshots"]["summary"]
            self.assertEqual(no_snapshots["wall_seconds_median"], 22.0)
            self.assertEqual(no_snapshots["wall_seconds_minimum"], 20.0)
            self.assertEqual(no_snapshots["wall_seconds_maximum"], 30.0)
            self.assertEqual(no_snapshots["paired_slowdown_median"], 2.0)

    def test_rejects_an_even_repetition_count(self) -> None:
        with self.assertRaisesRegex(SUMMARY.AuditError, "odd number"):
            SUMMARY.summarize_campaigns([Path("one"), Path("two")])


if __name__ == "__main__":
    unittest.main()
