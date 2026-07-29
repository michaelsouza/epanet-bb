#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_accuracy_sensitivity.py"
AUDITOR = ROOT / "scripts" / "audit_accuracy_sensitivity.py"
CONFIG = ROOT / "experiments" / "accuracy-sensitivity-anytown-24h.json"
NETWORK = ROOT / "networks" / "any-town.inp"
FINAL_SUMMARY = (
    ROOT / "experiments" / "results" / "final-cases-anytown-24h-summary.json"
)


class AccuracySensitivityTests(unittest.TestCase):
    def write_executable(self, path: Path, body: str) -> None:
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def fixtures(self, root: Path) -> tuple[Path, Path, Path]:
        launcher = root / "fake-mpiexec"
        evaluator = root / "fake-evaluator"
        optimizer = root / "fake-optimizer"
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
            evaluator,
            """
import json
import os
from pathlib import Path
import sys

request = json.loads(Path(sys.argv[1]).read_text())
converged = (
    os.environ.get("FAKE_ALL_CONCLUSIVE") == "1"
    or request["hydraulic_accuracy"] != 1e-7
)
Path(sys.argv[2]).write_text(json.dumps({
    "feasible": converged,
    "cost": 123.5,
    "prune_reason": "NONE",
    "hour_failed": None if converged else 1,
    "hydraulic": {
        "converged": converged,
        "status": 0 if converged else -1,
        "solve_count": 49 if converged else 1,
        "trials_total": 98 if converged else 40,
        "trials_maximum": 2 if converged else 40,
        "solve_seconds": 0.25,
        "failure_time_seconds": None if converged else 0,
        "relative_accuracy": request["hydraulic_accuracy"],
    },
}), encoding="utf-8")
raise SystemExit(0 if converged else 1)
""",
        )
        self.write_executable(
            optimizer,
            """
import json
import os
from pathlib import Path
import sys

output = Path("outputs")
output.mkdir()
accuracy = float(sys.argv[sys.argv.index("--hydraulic-accuracy") + 1])
conclusive = os.environ.get("FAKE_ALL_CONCLUSIVE") == "1" or accuracy != 1e-7
(output / "rank_000_stats.json").write_text(json.dumps({
    "NONE": [1], "PRESSURES": [0], "LEVELS": [0],
    "TANK_SATURATION": [0], "STABILITY": [0], "COST": [0],
    "ACTUATIONS": [0], "TIMESTEP": [0],
    "tasks_processed": 1,
    "search": {"status": "CONCLUSIVE" if conclusive else "INCONCLUSIVE_HYDRAULIC_NONCONVERGENCE"},
    "disaggregation_summary": {"candidate_assignments": 2},
    "hydraulic_nonconvergence_events": [] if conclusive else [{"hour": 1}],
}), encoding="utf-8")
if conclusive:
    (output / "rank_000_best.json").write_text(json.dumps({
        "search_status": "CONCLUSIVE", "best_cost": 10.0,
        "best_x": [0, 1], "best_y": [0, 1],
    }), encoding="utf-8")
raise SystemExit(0 if conclusive else 1)
""",
        )
        return launcher, evaluator, optimizer

    def command(
        self,
        output: Path,
        launcher: Path,
        evaluator: Path,
        optimizer: Path,
    ) -> list[str]:
        return [
            sys.executable,
            str(RUNNER),
            "--profile",
            "smoke",
            "--all",
            "--config",
            str(CONFIG),
            "--binary",
            str(optimizer),
            "--evaluator",
            str(evaluator),
            "--input",
            str(NETWORK),
            "--final-summary",
            str(FINAL_SUMMARY),
            "--mpi-launcher",
            str(launcher),
            "--output-dir",
            str(output),
        ]

    def test_smoke_runs_both_parts_and_resumes_without_reexecution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, evaluator, optimizer = self.fixtures(root)
            output = root / "sensitivity"
            command = self.command(output, launcher, evaluator, optimizer)

            completed = subprocess.run(
                command, cwd=root, capture_output=True, text=True
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(
                (output / "accuracy-sensitivity-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(len(receipt["records"]), 4)
            fixed = [r for r in receipt["records"] if r["kind"] == "fixed"]
            optimization = [
                r for r in receipt["records"] if r["kind"] == "optimization"
            ]
            self.assertEqual(len(fixed), 3)
            self.assertEqual(len(optimization), 1)
            self.assertTrue(all(record["hydraulic_converged"] for record in fixed))
            self.assertTrue(optimization[0]["conclusive"])
            self.assertEqual(optimization[0]["nodes_total"], 1)
            self.assertTrue((output / "fixed-schedule-summary.csv").is_file())
            self.assertTrue((output / "optimization-summary.csv").is_file())
            self.assertTrue((output / "fixed-schedule-aggregate.csv").is_file())
            self.assertTrue((output / "optimization-aggregate.csv").is_file())

            resumed = subprocess.run(
                [*command, "--resume"], cwd=root, capture_output=True, text=True
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            resumed_receipt = json.loads(
                (output / "accuracy-sensitivity-results.json").read_text()
            )
            self.assertTrue(resumed_receipt["resumed"])
            self.assertEqual(len(resumed_receipt["records"]), 4)

    def test_final_dry_run_has_declared_repetition_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, evaluator, optimizer = self.fixtures(root)
            output = root / "sensitivity"
            command = self.command(output, launcher, evaluator, optimizer)
            smoke_index = command.index("smoke")
            command[smoke_index] = "final"
            command.append("--dry-run")

            completed = subprocess.run(
                command, cwd=root, capture_output=True, text=True
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            plan = json.loads(completed.stdout)
            fixed = [cell for cell in plan["cells"] if cell["kind"] == "fixed"]
            optimization = [
                cell for cell in plan["cells"] if cell["kind"] == "optimization"
            ]
            self.assertEqual(len(fixed), 45)
            self.assertEqual(len(optimization), 27)
            self.assertEqual(optimization[0]["actuations"], 3)
            self.assertEqual(optimization[0]["accuracy_id"], "1e-4")
            self.assertTrue(all(cell["np"] == 64 for cell in optimization))
            self.assertFalse(output.exists())

    def test_nonconvergence_is_preserved_without_failing_the_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, evaluator, optimizer = self.fixtures(root)
            config = json.loads(CONFIG.read_text(encoding="utf-8"))
            config["smoke"]["accuracy_id"] = "1e-7"
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output = root / "sensitivity"
            command = self.command(output, launcher, evaluator, optimizer)
            command[command.index(str(CONFIG))] = str(config_path)

            completed = subprocess.run(
                command, cwd=root, capture_output=True, text=True
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(
                (output / "accuracy-sensitivity-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "complete")
            fixed = [r for r in receipt["records"] if r["kind"] == "fixed"]
            optimization = [
                r for r in receipt["records"] if r["kind"] == "optimization"
            ]
            self.assertTrue(all(record["return_code"] == 1 for record in fixed))
            self.assertTrue(all(not record["hydraulic_converged"] for record in fixed))
            self.assertEqual(optimization[0]["return_code"], 1)
            self.assertFalse(optimization[0]["conclusive"])
            self.assertEqual(optimization[0]["best_cost"], None)
            self.assertEqual(optimization[0]["hydraulic_nonconvergence_events"], 1)

    def test_final_campaign_auditor_validates_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher, evaluator, optimizer = self.fixtures(root)
            output = root / "sensitivity"
            command = self.command(output, launcher, evaluator, optimizer)
            command[command.index("smoke")] = "final"
            command.extend(["--max-np", "1"])
            environment = os.environ.copy()
            environment["FAKE_ALL_CONCLUSIVE"] = "1"

            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            audit_path = output / "audit.json"
            audit_command = [
                sys.executable,
                str(AUDITOR),
                str(output),
                "--output",
                str(audit_path),
            ]
            audited = subprocess.run(
                audit_command,
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(audited.returncode, 0, audited.stdout + audited.stderr)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertFalse(Path(audit["campaign"]).is_absolute())
            self.assertEqual(audit["fixed_records"], 45)
            self.assertEqual(audit["optimization_records"], 27)
            self.assertEqual(audit["artifact_count"], 99)
            self.assertEqual(audit["timeouts"], 0)
            self.assertEqual(
                audit["unique_schedules_across_accuracies"],
                {"1": 1, "2": 1, "3": 1},
            )

            next(output.glob("work/optimization*/outputs/*_stats.json")).unlink()
            rejected = subprocess.run(
                audit_command,
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("rank artifact count mismatch", rejected.stdout)


if __name__ == "__main__":
    unittest.main()
