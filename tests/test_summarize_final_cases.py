#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_final_cases", ROOT / "scripts" / "summarize_final_cases.py"
)
SUMMARY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SUMMARY)


class SummarizeFinalCasesTests(unittest.TestCase):
    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def make_campaign(self, root: Path) -> Path:
        campaign = root / "campaign"
        final_cases = campaign / "final-cases"
        plan_experiments = []
        result_experiments = []
        for actuations in (1, 2, 3):
            command = [
                "mpiexec",
                "-n",
                "2",
                "solver",
                "-h",
                "24",
                "-a",
                str(actuations),
                "-l",
                "8",
                "-s",
                "32768",
            ]
            plan_experiments.append(
                {"actuations": actuations, "command": command}
            )
            result_experiments.append(
                {
                    "actuations": actuations,
                    "duration_seconds": float(actuations * 10),
                    "return_code": 0,
                }
            )
            outputs = (
                final_cases / f"actuations-{actuations:02d}" / "outputs"
            )
            for rank in range(2):
                metadata = {
                    "mpi_processes": 2,
                    "configuration": {
                        "horizon_hours": 24,
                        "max_cycles_per_pump": actuations,
                        "task_decomposition_level": 8,
                        "sync_interval": 32768,
                    },
                    "software": {"executable_sha256": "binary-hash"},
                }
                pruning = {
                    "ACTUATIONS": [10 + actuations],
                    "COST": [5],
                    "LEVELS": [0],
                    "TANK_SATURATION": [2],
                    "PRESSURES": [1],
                    "STABILITY": [0],
                    "TIMESTEP": [0],
                    "NONE": [20],
                }
                self.write_json(
                    outputs / f"run_r_{rank:02d}_stats.json",
                    {
                        **pruning,
                        "search": {"status": "CONCLUSIVE"},
                        "metadata": metadata,
                        "time_total": actuations * 10 - rank,
                        "tasks_processed": 6,
                        "disaggregation_summary": {
                            "candidate_assignments": 100 + rank
                        },
                    },
                )
                cost = 1000.0 + actuations + rank
                self.write_json(
                    outputs / f"run_r_{rank:02d}_best.json",
                    {
                        "search_status": "CONCLUSIVE",
                        "best_cost": cost,
                        "best_x": [0, 1] * 25,
                        "best_y": [1] * 25,
                        "best_canonical_x": [1, 0] * 25,
                    },
                )
        self.write_json(
            campaign / "campaign-plan.json",
            {
                "compatibility_sha256": "protocol-hash",
                "metadata": {
                    "git": {"commit": "commit", "dirty": False},
                    "executable": {"sha256": "binary-hash"},
                },
                "tasks": [
                    {
                        "id": "final-cases",
                        "commands": [{"np": 2}],
                    }
                ],
            },
        )
        self.write_json(
            campaign / "campaign-results.json",
            {
                "status": "complete",
                "tasks": [
                    {
                        "id": "final-cases",
                        "return_codes": [0],
                        "duration_seconds": 60.0,
                    }
                ],
            },
        )
        self.write_json(
            final_cases / "execution-plan.json",
            {
                "process_count": {"value": 2},
                "experiments": plan_experiments,
            },
        )
        self.write_json(
            final_cases / "execution-results.json",
            {"status": "complete", "experiments": result_experiments},
        )
        return campaign

    def test_audits_final_cases_and_preserves_schedules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = self.make_campaign(Path(temporary))

            summary = SUMMARY.summarize_campaign(campaign)

            self.assertEqual(summary["configuration"]["np"], 2)
            self.assertEqual(len(summary["cases"]), 3)
            case = summary["cases"][1]
            self.assertEqual(case["actuations"], 2)
            self.assertEqual(case["global_best_cost"], 1002.0)
            self.assertEqual(case["tasks_processed"], 12)
            self.assertEqual(case["candidate_assignments"], 201)
            self.assertEqual(case["best_y"], [1] * 25)
            self.assertAlmostEqual(
                case["pruning_percentages"]["Tank levels"],
                5.0,
            )

    def test_rejects_missing_rank_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = self.make_campaign(Path(temporary))
            missing = next(
                (
                    campaign
                    / "final-cases"
                    / "actuations-02"
                    / "outputs"
                ).glob("*_stats.json")
            )
            missing.unlink()

            with self.assertRaisesRegex(SUMMARY.AuditError, "expected 2 stats"):
                SUMMARY.summarize_campaign(campaign)

    def test_rejects_inconsistent_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = self.make_campaign(Path(temporary))
            best_path = sorted(
                (
                    campaign
                    / "final-cases"
                    / "actuations-01"
                    / "outputs"
                ).glob("*_best.json")
            )[0]
            best = json.loads(best_path.read_text(encoding="utf-8"))
            best["best_y"][0] = 0
            self.write_json(best_path, best)

            with self.assertRaisesRegex(SUMMARY.AuditError, "schedules differ"):
                SUMMARY.summarize_campaign(campaign)


if __name__ == "__main__":
    unittest.main()
