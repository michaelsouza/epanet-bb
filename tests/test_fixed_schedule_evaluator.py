#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


if len(sys.argv) != 6:
    raise RuntimeError(
        "expected evaluator, network, reference optimum, invalid schedule, and MPI launcher"
    )
EVALUATOR = Path(sys.argv[1]).absolute()
NETWORK = Path(sys.argv[2]).absolute()
SUMMARY_PATH = Path(sys.argv[3]).absolute()
INVALID_PATH = Path(sys.argv[4]).absolute()
MPI_LAUNCHER = Path(sys.argv[5]).absolute()
del sys.argv[1:]


class FixedScheduleEvaluatorTests(unittest.TestCase):
    def run_evaluator(
        self, payload: dict
    ) -> tuple[subprocess.CompletedProcess, dict | None]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = root / "request.json"
            result = root / "result.json"
            request.write_text(json.dumps(payload), encoding="utf-8")
            environment = os.environ.copy()
            environment["HWLOC_COMPONENTS"] = "-gl"
            completed = subprocess.run(
                [
                    str(MPI_LAUNCHER),
                    "--map-by",
                    "core",
                    "--bind-to",
                    "core",
                    "-n",
                    "1",
                    str(EVALUATOR),
                    str(request),
                    str(result),
                ],
                cwd=NETWORK.parent.parent,
                env=environment,
                capture_output=True,
                text=True,
            )
            if not result.is_file():
                return completed, None
            return completed, json.loads(result.read_text(encoding="utf-8"))

    def evaluate(self, payload: dict) -> tuple[subprocess.CompletedProcess, dict]:
        completed, result = self.run_evaluator(payload)
        self.assertIsNotNone(result, completed.stdout + completed.stderr)
        return completed, result

    def binary_request(self, source: dict) -> dict:
        return {
            "best_x": source["best_x"],
            "best_y": source["best_y"],
            "h_max": 24,
            "max_actuations": source["max_actuations"],
            "inp_file": str(NETWORK),
            "schedule_mode": "binary",
            "verbose": 0,
        }

    def test_accepts_a_revised_binary_schedule_and_reproduces_its_cost(self) -> None:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        case = next(case for case in summary["cases"] if case["actuations"] == 1)
        source = {
            "best_x": case["best_x"],
            "best_y": case["best_y"],
            "max_actuations": 1,
        }

        completed, result = self.evaluate(self.binary_request(source))

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["schedule_mode"], "binary")
        self.assertTrue(all(count <= 2 for count in result["periodic_switch_counts"]))
        self.assertAlmostEqual(result["cost"], case["global_best_cost"], places=6)
        self.assertEqual(result["switch_count_convention"], "periodic")
        self.assertEqual(result["max_switch_count_per_pump"], 2)
        self.assertEqual(len(result["single_day_switch_on_counts"]), 3)

    def test_rejects_the_original_binary_schedule_when_cycles_exceed_limit(self) -> None:
        source = json.loads(INVALID_PATH.read_text(encoding="utf-8"))

        completed, result = self.evaluate(self.binary_request(source))

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(result["feasible"])
        self.assertEqual(result["prune_reason"], "ACTUATIONS")
        self.assertGreater(max(result["periodic_switch_counts"]), 2)

    def test_single_day_count_accepts_the_original_binary_schedule(self) -> None:
        # The published NA_max=1 schedule switches each pump on at most once
        # within the day; only the periodic closure makes it infeasible.
        source = json.loads(INVALID_PATH.read_text(encoding="utf-8"))
        request = self.binary_request(source)
        request["switch_count_convention"] = "single_day"

        completed, result = self.evaluate(request)

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["switch_count_convention"], "single_day")
        self.assertEqual(result["max_switch_count_per_pump"], 1)
        self.assertTrue(
            all(count <= 1 for count in result["single_day_switch_on_counts"])
        )
        self.assertGreater(max(result["periodic_switch_counts"]), 2)
        self.assertAlmostEqual(result["cost"], 3634.602760, places=4)

    def test_single_day_count_rejects_repeated_switch_ons(self) -> None:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        case = next(case for case in summary["cases"] if case["actuations"] == 1)
        pumps = len(case["best_x"]) // 25
        best_x = [0] * (25 * pumps)
        for hour in range(1, 25):
            best_x[hour * pumps] = hour % 2
        best_y = [sum(best_x[hour * pumps : (hour + 1) * pumps]) for hour in range(25)]
        request = self.binary_request(
            {"best_x": best_x, "best_y": best_y, "max_actuations": 1}
        )
        request["switch_count_convention"] = "single_day"

        completed, result = self.evaluate(request)

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(result["feasible"])
        self.assertEqual(result["prune_reason"], "ACTUATIONS")
        self.assertEqual(result["single_day_switch_on_counts"], [11, 0, 0])
        self.assertEqual(result["periodic_switch_counts"], [24, 0, 0])

    def test_single_day_aggregate_mode_uses_an_exact_witness(self) -> None:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        case = next(case for case in summary["cases"] if case["actuations"] == 1)
        request = self.binary_request(
            {
                "best_x": case["best_x"],
                "best_y": case["best_y"],
                "max_actuations": 1,
            }
        )
        request["schedule_mode"] = "aggregate"
        request["switch_count_convention"] = "single_day"

        completed, result = self.evaluate(request)

        # A periodic-feasible schedule is feasible under the single-day count.
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(result["feasible"])
        self.assertAlmostEqual(result["cost"], case["global_best_cost"], places=6)
        self.assertTrue(
            all(count <= 1 for count in result["single_day_switch_on_counts"])
        )
        pumps = len(result["periodic_switch_counts"])
        for hour, active in enumerate(result["y"]):
            self.assertEqual(
                sum(result["x"][hour * pumps : (hour + 1) * pumps]), active
            )

    def test_rejects_an_unknown_switch_count_convention(self) -> None:
        source = json.loads(INVALID_PATH.read_text(encoding="utf-8"))
        request = self.binary_request(source)
        request["switch_count_convention"] = "weekly"

        completed, result = self.run_evaluator(request)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(result)
        self.assertIn("switch_count_convention", completed.stdout + completed.stderr)

    def test_accuracy_override_records_trials_and_hydraulic_trace(self) -> None:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        case = next(case for case in summary["cases"] if case["actuations"] == 1)
        request = self.binary_request(
            {
                "best_x": case["best_x"],
                "best_y": case["best_y"],
                "max_actuations": 1,
            }
        )
        request["hydraulic_accuracy"] = 0.001
        request["hydraulic_max_trials"] = 40

        completed, result = self.evaluate(request)

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        hydraulic = result["hydraulic"]
        self.assertTrue(hydraulic["converged"])
        self.assertEqual(hydraulic["relative_accuracy"], 0.001)
        self.assertEqual(hydraulic["relative_accuracy_origin"], "request")
        self.assertEqual(hydraulic["max_trials"], 40)
        self.assertGreater(hydraulic["solve_count"], 24)
        self.assertGreater(hydraulic["trials_total"], hydraulic["solve_count"])
        self.assertEqual(len(hydraulic["trace"]), hydraulic["solve_count"])
        first = hydraulic["trace"][0]
        self.assertGreater(len(first["nodes"]), 0)
        self.assertGreater(len(first["links"]), 0)
        self.assertIn("pressure", first["nodes"][0])
        self.assertIn("flow", first["links"][0])


if __name__ == "__main__":
    unittest.main()
