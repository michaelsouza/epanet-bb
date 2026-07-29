#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_campaign.py"
NETWORK = ROOT / "networks" / "any-town.inp"


class RunCampaignTests(unittest.TestCase):
    def write_executable(self, path: Path, body: str) -> None:
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def test_dry_run_resolves_selected_tasks_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--np",
                    "4",
                    "--binary",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    sys.executable,
                    "--output-dir",
                    str(output_directory),
                    "--hydraulic-accuracy",
                    "0.001",
                    "--hydraulic-max-trials",
                    "50",
                    "--select",
                    "final-cases",
                    "--select",
                    "scalability",
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["profile"], "final")
            self.assertEqual(
                [task["id"] for task in plan["tasks"]],
                ["final-cases", "scalability"],
            )
            self.assertEqual(plan["resources"]["process_count"]["value"], 4)
            self.assertEqual(
                [command["np"] for command in plan["tasks"][1]["commands"]],
                [1, 2, 4],
            )
            self.assertTrue(plan["tasks"][0]["requires_mpi"])
            self.assertTrue(plan["tasks"][0]["requires_hpc"])
            final_command = plan["tasks"][0]["commands"][0]["argv"]
            self.assertEqual(
                final_command[-4:],
                [
                    "--hydraulic-accuracy",
                    "0.001",
                    "--hydraulic-max-trials",
                    "50",
                ],
            )
            self.assertEqual(
                plan["hydraulics"],
                {
                    "accuracy_override": 0.001,
                    "max_trials_override": 50,
                    "otherwise": "input_file",
                },
            )
            self.assertEqual(
                plan["metadata"]["executable"]["sha256"],
                hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            )
            self.assertEqual(plan["paths"]["repo_root"], str(ROOT))
            self.assertFalse(output_directory.exists())

    def test_smoke_profile_executes_controlled_subset_with_receipts(self) -> None:
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
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--profile",
                    "smoke",
                    "--select",
                    "final-cases",
                    "--np",
                    "2",
                    "--binary",
                    str(solver),
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    str(launcher),
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(
                (output_directory / "campaign-plan.json").read_text()
            )
            command = plan["tasks"][0]["commands"][0]
            self.assertEqual(command["np"], 1)
            self.assertIn("--hours", command["argv"])
            self.assertEqual(
                command["argv"][command["argv"].index("--hours") + 1], "3"
            )
            child_plan = json.loads(
                (
                    output_directory
                    / "final-cases"
                    / "execution-plan.json"
                ).read_text()
            )
            self.assertEqual(child_plan["process_count"]["value"], 1)
            self.assertEqual(child_plan["parameters"]["hours"], 3)
            self.assertEqual(
                child_plan["experiments"][0]["actuations"], 1
            )
            receipt = json.loads(
                (output_directory / "campaign-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["tasks"][0]["return_codes"], [0])

            resumed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--resume",
                    "--profile",
                    "smoke",
                    "--select",
                    "final-cases",
                    "--np",
                    "2",
                    "--binary",
                    str(solver),
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    str(launcher),
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            resumed_receipt = json.loads(
                (output_directory / "campaign-results.json").read_text()
            )
            self.assertTrue(resumed_receipt["resumed"])
            self.assertEqual(
                resumed_receipt["skipped_complete_tasks"], ["final-cases"]
            )
            self.assertEqual(
                list((output_directory / "logs").glob("final-cases-*.log")),
                [output_directory / "logs" / "final-cases-01.log"],
            )

    def test_resume_reexecutes_if_output_directory_missing(self) -> None:
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
                "from pathlib import Path; output = Path('outputs'); output.mkdir(); (output / 'res.json').write_text('{}')",
            )

            args = [
                sys.executable,
                str(RUNNER),
                "--profile",
                "smoke",
                "--select",
                "final-cases",
                "--binary",
                str(solver),
                "--input",
                str(NETWORK),
                "--mpi-launcher",
                str(launcher),
                "--output-dir",
                str(output_directory),
            ]
            res = subprocess.run(args, cwd=working_directory, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)

            # Remove output directory of final-cases
            import shutil
            shutil.rmtree(output_directory / "final-cases")

            # Run with --resume
            resumed = subprocess.run(args + ["--resume"], cwd=working_directory, capture_output=True, text=True)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            receipt = json.loads((output_directory / "campaign-results.json").read_text())
            # Should NOT skip final-cases because directory was missing
            self.assertEqual(receipt["skipped_complete_tasks"], [])
            recreated_result = (
                output_directory
                / "final-cases"
                / "actuations-01"
                / "outputs"
                / "res.json"
            )
            self.assertTrue(recreated_result.is_file())
            self.assertEqual(receipt["tasks"][0]["return_codes"], [0])

    def test_interruption_leaves_atomic_resumable_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "campaign"
            launcher = working_directory / "fake-mpiexec"
            solver = working_directory / "blocking-solver"
            started_marker = working_directory / "solver-started"
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
                f"""
from pathlib import Path
import time

marker = Path({str(started_marker)!r})
if marker.exists():
    output = Path("outputs")
    output.mkdir()
    (output / "resumed.json").write_text("{{}}", encoding="utf-8")
else:
    marker.write_text("started", encoding="utf-8")
    time.sleep(60)
""",
            )

            arguments = [
                sys.executable,
                str(RUNNER),
                "--profile",
                "smoke",
                "--select",
                "final-cases",
                "--binary",
                str(solver),
                "--input",
                str(NETWORK),
                "--mpi-launcher",
                str(launcher),
                "--output-dir",
                str(output_directory),
            ]
            process = subprocess.Popen(
                arguments,
                cwd=working_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 10
                while (
                    not started_marker.exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                self.assertTrue(started_marker.is_file())
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=10)

            receipt_path = output_directory / "campaign-results.json"
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "running")
            self.assertEqual(receipt["tasks"][0]["id"], "final-cases")
            self.assertEqual(receipt["tasks"][0]["return_codes"], [])
            self.assertFalse(
                (output_directory / "campaign-results.json.tmp").exists()
            )

            resumed = subprocess.run(
                [*arguments, "--resume"],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            resumed_receipt = json.loads(receipt_path.read_text())
            self.assertEqual(resumed_receipt["status"], "complete")
            resumed_output = Path(
                resumed_receipt["tasks"][0]["output_dirs"][0]
            )
            self.assertNotEqual(
                resumed_output, output_directory / "final-cases"
            )
            self.assertTrue(
                (
                    resumed_output
                    / "actuations-01"
                    / "outputs"
                    / "resumed.json"
                ).is_file()
            )


    def test_legacy_entrypoints_select_their_campaign_tasks(self) -> None:
        for script_name, task_id in (
            ("run_scalability.py", "scalability"),
            ("run_ablation.py", "ablation"),
        ):
            with self.subTest(script=script_name):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / script_name),
                        "--dry-run",
                        "--profile",
                        "smoke",
                        "--binary",
                        sys.executable,
                        "--input",
                        str(NETWORK),
                        "--mpi-launcher",
                        sys.executable,
                    ],
                    cwd=ROOT.parent,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(result.stdout)
                self.assertEqual(
                    [task["id"] for task in plan["tasks"]], [task_id]
                )

    def test_final_ablation_starts_with_no_snapshots_on_na_max_three(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--select",
                    "ablation",
                    "--np",
                    "64",
                    "--binary",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    sys.executable,
                    "--output-dir",
                    str(Path(temporary) / "ablation"),
                ],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            commands = plan["tasks"][0]["commands"]
            self.assertEqual(len(commands), 6)
            self.assertEqual(
                commands[0]["environment"], {"BB_ENABLE_SNAPSHOTS": "0"}
            )
            self.assertEqual(commands[0]["np"], 64)
            argv = commands[0]["argv"]
            actuations_index = argv.index("--actuations")
            self.assertEqual(argv[actuations_index + 1], "3")

    def test_final_scalability_uses_tuned_na_max_two_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--select",
                    "scalability",
                    "--np",
                    "64",
                    "--binary",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    sys.executable,
                    "--output-dir",
                    str(Path(temporary) / "scalability"),
                ],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            commands = plan["tasks"][0]["commands"]
            self.assertEqual(
                [command["np"] for command in commands],
                [1, 2, 4, 8, 16, 32, 64],
            )
            for command in commands:
                argv = command["argv"]
                actuations_index = argv.index("--actuations")
                self.assertEqual(argv[actuations_index + 1], "2")

    def test_tuning_plan_propagates_process_envelope_and_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "campaign"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--select",
                    "tuning",
                    "--np",
                    "4",
                    "--binary",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    sys.executable,
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            command = plan["tasks"][0]["commands"][0]
            self.assertEqual(command["np"], 4)
            self.assertEqual(
                command["argv"][command["argv"].index("--max-np") + 1],
                "4",
            )
            self.assertEqual(
                command["argv"][
                    command["argv"].index("--mpi-launcher") + 1
                ],
                sys.executable,
            )
            self.assertFalse(output_directory.exists())

    def test_accuracy_sensitivity_uses_its_versioned_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "campaign"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--dry-run",
                    "--select",
                    "accuracy-sensitivity",
                    "--np",
                    "64",
                    "--binary",
                    sys.executable,
                    "--input",
                    str(NETWORK),
                    "--mpi-launcher",
                    sys.executable,
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=ROOT.parent,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(
                [task["id"] for task in plan["tasks"]],
                ["accuracy-sensitivity"],
            )
            command = plan["tasks"][0]["commands"][0]
            self.assertEqual(command["np"], 64)
            self.assertIn("run_accuracy_sensitivity.py", command["argv"][1])
            self.assertIn("--all", command["argv"])
            self.assertEqual(
                command["argv"][command["argv"].index("--max-np") + 1],
                "64",
            )
            self.assertFalse(output_directory.exists())


if __name__ == "__main__":
    unittest.main()
