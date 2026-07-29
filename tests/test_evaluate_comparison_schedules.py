#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


if len(sys.argv) != 3:
    raise RuntimeError("expected evaluator and MPI launcher")
EVALUATOR = Path(sys.argv[1]).absolute()
MPI_LAUNCHER = Path(sys.argv[2]).absolute()
del sys.argv[1:]
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "evaluate_comparison_schedules",
    ROOT / "scripts" / "evaluate_comparison_schedules.py",
)
EVALUATE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATE)


class EvaluateComparisonSchedulesTests(unittest.TestCase):
    def test_replays_all_schedules_with_expected_feasibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = EVALUATE.evaluate_schedules(
                EVALUATOR,
                ROOT / "networks" / "any-town.inp",
                ROOT / "experiments" / "comparison-schedules",
                ROOT
                / "experiments"
                / "results"
                / "final-cases-anytown-24h-summary.json",
                MPI_LAUNCHER,
                Path(temporary) / "evaluation",
            )

            matrix = {
                source: {
                    record["actuations"]: record["feasible"]
                    for record in summary["records"]
                    if record["source"] == source
                }
                for source in EVALUATE.EXPECTED_FEASIBILITY
            }
            self.assertEqual(matrix, EVALUATE.EXPECTED_FEASIBILITY)
            revised = [
                record
                for record in summary["records"]
                if record["source"] == "Souza2026"
            ]
            self.assertTrue(all(record["feasible"] for record in revised))
            self.assertTrue(
                all(
                    abs(record["published_cost"] - record["reevaluated_cost"])
                    < 1e-6
                    for record in revised
                )
            )


if __name__ == "__main__":
    unittest.main()
