#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_experiments.py"
NETWORK = ROOT / "networks" / "any-town.inp"


class RunExperimentsTests(unittest.TestCase):
    def write_executable(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def test_dry_run_resolves_explicit_resources_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            environment = os.environ.copy()
            environment["PATH"] = ""
            for variable in (
                "SLURM_NTASKS",
                "PBS_NP",
                "LSB_DJOB_NUMPROC",
                "NSLOTS",
            ):
                environment.pop(variable, None)

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--np",
                    "3",
                    "--binary",
                    sys.executable,
                    "--mpi-launcher",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--output-dir",
                    str(output_directory),
                    "--hours",
                    "3",
                    "--actuations",
                    "1",
                    "--hydraulic-accuracy",
                    "0.001",
                    "--hydraulic-max-trials",
                    "50",
                ],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(
                plan["process_count"],
                {
                    "allocation": None,
                    "allocation_source": None,
                    "source": "cli",
                    "value": 3,
                },
            )
            self.assertEqual(plan["paths"]["repo_root"], str(ROOT))
            self.assertEqual(plan["paths"]["binary"], sys.executable)
            self.assertEqual(plan["paths"]["input"], str(NETWORK))
            self.assertEqual(
                plan["paths"]["output_dir"], str(output_directory)
            )
            self.assertEqual(len(plan["experiments"]), 1)
            self.assertEqual(plan["experiments"][0]["actuations"], 1)
            self.assertEqual(
                plan["parameters"]["hydraulic_accuracy"], 0.001
            )
            self.assertEqual(
                plan["parameters"]["hydraulic_max_trials"], 50
            )
            self.assertEqual(
                plan["experiments"][0]["command"][-4:],
                [
                    "--hydraulic-accuracy",
                    "0.001",
                    "--hydraulic-max-trials",
                    "50",
                ],
            )
            self.assertEqual(
                plan["experiments"][0]["command"][:7],
                [
                    sys.executable,
                    "--map-by",
                    "core",
                    "--bind-to",
                    "core",
                    "-n",
                    "3",
                ],
            )
            self.assertFalse(output_directory.exists())

    def test_execution_persists_plan_and_isolates_solver_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            launcher = working_directory / "fake-mpiexec"
            solver = working_directory / "fake-solver"
            self.write_executable(
                launcher,
                """
import subprocess
import sys

arguments = sys.argv[1:]
rank_option = arguments.index("-n")
command = arguments[rank_option + 2:]
raise SystemExit(subprocess.run(command).returncode)
""",
            )
            self.write_executable(
                solver,
                """
import json
from pathlib import Path
import sys

output = Path("outputs")
output.mkdir()
(output / "solver-result.json").write_text(
    json.dumps({"arguments": sys.argv[1:]}),
    encoding="utf-8",
)
(output / "rank_0_stats.json").write_text(
    json.dumps({"search": {"status": "CONCLUSIVE"}}),
    encoding="utf-8",
)
(output / "rank_1_stats.json").write_text(
    json.dumps({"search": {"status": "CONCLUSIVE"}}),
    encoding="utf-8",
)
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--np",
                    "2",
                    "--mpi-launcher",
                    str(launcher),
                    "--binary",
                    str(solver),
                    "--input",
                    str(NETWORK),
                    "--output-dir",
                    str(output_directory),
                    "--hours",
                    "3",
                    "--actuations",
                    "1",
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(
                (output_directory / "execution-plan.json").read_text()
            )
            self.assertEqual(plan["process_count"]["value"], 2)
            experiment = plan["experiments"][0]
            experiment_directory = Path(experiment["working_directory"])
            solver_result = json.loads(
                (
                    experiment_directory
                    / "outputs"
                    / "solver-result.json"
                ).read_text()
            )
            self.assertEqual(
                solver_result["arguments"],
                [
                    "-i",
                    str(NETWORK),
                    "-h",
                    "3",
                    "-a",
                    "1",
                    "-l",
                    "8",
                    "-s",
                    "32768",
                ],
            )
            execution_results = json.loads(
                (output_directory / "execution-results.json").read_text()
            )
            self.assertEqual(execution_results["status"], "complete")
            self.assertEqual(
                execution_results["experiments"][0]["return_code"], 0
            )
            self.assertEqual(
                execution_results["experiments"][0]["search_statuses"],
                ["CONCLUSIVE", "CONCLUSIVE"],
            )

    def test_missing_rank_artifact_fails_the_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            launcher = working_directory / "fake-mpiexec"
            solver = working_directory / "fake-solver"
            self.write_executable(
                launcher,
                """
import subprocess
import sys

arguments = sys.argv[1:]
rank_option = arguments.index("-n")
command = arguments[rank_option + 2:]
raise SystemExit(subprocess.run(command).returncode)
""",
            )
            self.write_executable(
                solver,
                """
import json
from pathlib import Path

output = Path("outputs")
output.mkdir()
(output / "rank_0_stats.json").write_text(
    json.dumps({"search": {"status": "CONCLUSIVE"}}),
    encoding="utf-8",
)
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--np",
                    "2",
                    "--mpi-launcher",
                    str(launcher),
                    "--binary",
                    str(solver),
                    "--input",
                    str(NETWORK),
                    "--output-dir",
                    str(output_directory),
                    "--hours",
                    "3",
                    "--actuations",
                    "1",
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            receipt = json.loads(
                (output_directory / "execution-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "inconclusive")
            self.assertIn(
                "produced 1 rank statistics; expected 2",
                receipt["experiments"][0]["validation_error"],
            )

    def test_inconclusive_rank_artifact_fails_the_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            launcher = working_directory / "fake-mpiexec"
            solver = working_directory / "fake-solver"
            self.write_executable(
                launcher,
                """
import subprocess
import sys

arguments = sys.argv[1:]
rank_option = arguments.index("-n")
command = arguments[rank_option + 2:]
raise SystemExit(subprocess.run(command).returncode)
""",
            )
            self.write_executable(
                solver,
                """
import json
from pathlib import Path

output = Path("outputs")
output.mkdir()
(output / "rank_0_stats.json").write_text(
    json.dumps({"search": {"status": "INCONCLUSIVE_HYDRAULIC_NONCONVERGENCE"}}),
    encoding="utf-8",
)
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--np",
                    "1",
                    "--mpi-launcher",
                    str(launcher),
                    "--binary",
                    str(solver),
                    "--input",
                    str(NETWORK),
                    "--output-dir",
                    str(output_directory),
                    "--hours",
                    "3",
                    "--actuations",
                    "1",
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            receipt = json.loads(
                (output_directory / "execution-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "inconclusive")
            self.assertEqual(
                receipt["experiments"][0]["search_statuses"],
                ["INCONCLUSIVE_HYDRAULIC_NONCONVERGENCE"],
            )

    def test_process_count_rejects_exceeding_64(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--np",
                    "128",
                    "--binary",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exceeds the maximum allowed 64 MPI ranks", result.stderr)


if __name__ == "__main__":
    unittest.main()
