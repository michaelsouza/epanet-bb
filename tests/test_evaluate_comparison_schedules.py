#!/usr/bin/env python3

import importlib.util
import json
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
NETWORK = ROOT / "networks" / "any-town.inp"
SCHEDULES = ROOT / "experiments" / "comparison-schedules"
FINAL_SUMMARY = ROOT / "experiments" / "results" / "final-cases-anytown-24h-summary.json"
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
            self.assertEqual(EVALUATE.expectation_mismatches(summary), [])
            self.assertNotIn("switch_count_convention", summary)
            self.assertEqual(
                [
                    record["periodic_switch_counts"]
                    for record in summary["records"]
                    if record["source"] == "Cimorelli2021"
                ],
                [[2, 2, 2], [4, 4, 4], [6, 6, 6]],
            )
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
            self.assertTrue(
                all(
                    not Path(record["source_artifact"]).is_absolute()
                    for record in summary["records"]
                )
            )

    def test_single_day_replay_without_revised_solutions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evaluation"
            summary = EVALUATE.evaluate_schedules(
                EVALUATOR,
                NETWORK,
                SCHEDULES,
                None,
                MPI_LAUNCHER,
                output,
                "single_day",
            )
            self.assertEqual(summary["switch_count_convention"], "single_day")
            self.assertIsNone(summary["final_summary_sha256"])
            self.assertEqual(
                {record["source"] for record in summary["records"]},
                set(EVALUATE.EXTERNAL_SOURCES),
            )
            self.assertEqual(len(summary["records"]), 3 * len(EVALUATE.EXTERNAL_SOURCES))
            self.assertEqual(EVALUATE.expectation_mismatches(summary), [])
            cimorelli = {
                record["actuations"]: record
                for record in summary["records"]
                if record["source"] == "Cimorelli2020"
            }
            self.assertTrue(all(record["feasible"] for record in cimorelli.values()))
            for record in summary["records"]:
                counts = record["single_day_switch_on_counts"]
                self.assertEqual(len(counts), 3)
                if record["feasible"]:
                    self.assertLessEqual(max(counts), record["actuations"])
            request = json.loads(
                (output / cimorelli[1]["request"]).read_text(encoding="utf-8")
            )
            self.assertEqual(request["switch_count_convention"], "single_day")
            header = (
                (output / "comparison-feasibility-summary.csv")
                .read_text(encoding="utf-8")
                .splitlines()[0]
                .split(",")
            )
            self.assertEqual(header[0], "switch_count_convention")
            self.assertIn("single_day_switch_on_counts", header)

    def test_rejects_final_summary_with_other_convention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                EVALUATE.EvaluationError, "records the periodic switch count"
            ):
                EVALUATE.evaluate_schedules(
                    EVALUATOR,
                    NETWORK,
                    SCHEDULES,
                    FINAL_SUMMARY,
                    MPI_LAUNCHER,
                    Path(temporary) / "single-day",
                    "single_day",
                )
            single_day_summary = Path(temporary) / "single-day-summary.json"
            payload = json.loads(FINAL_SUMMARY.read_text(encoding="utf-8"))
            payload["switch_count_convention"] = "single_day"
            single_day_summary.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                EVALUATE.EvaluationError, "records the single_day switch count"
            ):
                EVALUATE.evaluate_schedules(
                    EVALUATOR,
                    NETWORK,
                    SCHEDULES,
                    single_day_summary,
                    MPI_LAUNCHER,
                    Path(temporary) / "periodic",
                )
            with self.assertRaisesRegex(
                EVALUATE.EvaluationError, "requires a final summary"
            ):
                EVALUATE.evaluate_schedules(
                    EVALUATOR,
                    NETWORK,
                    SCHEDULES,
                    None,
                    MPI_LAUNCHER,
                    Path(temporary) / "periodic",
                )
            # Every rejection happens before an output directory is created.
            self.assertFalse(
                any(path.is_dir() for path in Path(temporary).iterdir())
            )


if __name__ == "__main__":
    unittest.main()
