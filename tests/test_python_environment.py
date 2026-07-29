#!/usr/bin/env python3

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_python_environment.py"


class PythonEnvironmentTests(unittest.TestCase):
    def run_validator(self, *arguments):
        with tempfile.TemporaryDirectory() as temporary:
            return subprocess.run(
                [sys.executable, str(VALIDATOR), *arguments],
                cwd=temporary,
                capture_output=True,
                text=True,
            )

    def test_manifest_declares_every_direct_script_dependency(self):
        result = self.run_validator("--audit-only")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["undeclared_imports"], [])
        self.assertEqual(
            report["direct_distributions"],
            [
                "matplotlib",
                "networkx",
                "numpy",
                "optuna",
                "pandas",
                "pillow",
                "rich",
                "wntr",
            ],
        )

    def test_smoke_run_simulates_network_and_writes_nonempty_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "smoke"
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertGreater(report["simulation"]["time_steps"], 1)
            self.assertGreater(report["simulation"]["nodes"], 0)

            artifact = output_directory / "environment-smoke.png"
            self.assertEqual(artifact.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(artifact.stat().st_size, 1024)

            receipt = output_directory / "environment-smoke.json"
            self.assertEqual(json.loads(receipt.read_text()), report)
            self.assertEqual(
                sorted(path.name for path in working_directory.iterdir()),
                ["smoke"],
            )


if __name__ == "__main__":
    unittest.main()
