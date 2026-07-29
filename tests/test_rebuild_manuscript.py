#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REBUILDER = ROOT / "scripts" / "rebuild_manuscript.py"


def load_module(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RebuildManuscriptTests(unittest.TestCase):
    def test_comparison_cost_retains_published_value_for_infeasible_entry(self):
        comparison = load_module(
            "create_comparison_table_images",
            ROOT / "scripts" / "create_comparison_table_images.py",
        )
        self.assertEqual(
            comparison.displayed_cost(
                {
                    "feasible": False,
                    "cost": 3580.11,
                    "reevaluated_cost": 0.0,
                }
            ),
            "3580.11\nInfeasible",
        )
        self.assertEqual(
            comparison.displayed_cost(
                {
                    "feasible": True,
                    "cost": 3618.59,
                    "reevaluated_cost": 3618.595780,
                }
            ),
            "3618.60",
        )

    def test_dry_run_maps_every_manuscript_figure_without_creating_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "rebuilt"
            environment = os.environ.copy()
            environment["PATH"] = ""

            result = subprocess.run(
                [
                    sys.executable,
                    str(REBUILDER),
                    "--dry-run",
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(
                [task["id"] for task in plan["tasks"]],
                [
                    "manuscript-data",
                    "diagrams",
                    "case-study",
                    "scalability",
                    "hydraulics",
                    "comparisons",
                ],
            )
            figure_names = sorted(
                Path(output).name
                for task in plan["tasks"]
                for output in task["outputs"]
                if Path(output).suffix == ".pdf"
            )
            self.assertEqual(
                figure_names,
                [
                    f"Figure_{number}_{suffix}.pdf"
                    for number, suffix in (
                        (1, "two_level_diagram"),
                        (2, "tree_decomposition"),
                        (3, "anytown_network"),
                        (4, "anytown_energy_cost"),
                        (5, "scalability"),
                        (6, "tank_levels_24h"),
                        (7, "comparison_table_a1"),
                        (8, "comparison_table_a2"),
                        (9, "comparison_table_a3"),
                    )
                ],
            )
            self.assertFalse(output_directory.exists())

    def test_selected_diagrams_are_rebuilt_with_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "rebuilt"
            environment = os.environ.copy()
            environment["MPLBACKEND"] = "Agg"

            result = subprocess.run(
                [
                    sys.executable,
                    str(REBUILDER),
                    "--select",
                    "diagrams",
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            for name in (
                "Figure_1_two_level_diagram.pdf",
                "Figure_2_tree_decomposition.pdf",
            ):
                artifact = output_directory / "figures" / name
                self.assertEqual(artifact.read_bytes()[:4], b"%PDF")
                self.assertGreater(artifact.stat().st_size, 1000)

            plan = json.loads(
                (output_directory / "rebuild-plan.json").read_text()
            )
            self.assertEqual([task["id"] for task in plan["tasks"]], ["diagrams"])
            receipt = json.loads(
                (output_directory / "rebuild-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["tasks"][0]["id"], "diagrams")
            self.assertEqual(receipt["tasks"][0]["return_codes"], [0, 0])

    def test_repeated_selection_is_planned_once(self):
        result = subprocess.run(
            [
                sys.executable,
                str(REBUILDER),
                "--dry-run",
                "--select",
                "diagrams",
                "--select",
                "diagrams",
            ],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual([task["id"] for task in plan["tasks"]], ["diagrams"])

    def test_complete_rebuild_uses_only_precomputed_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            working_directory = Path(temporary)
            output_directory = working_directory / "rebuilt"
            environment = os.environ.copy()
            environment["MPLBACKEND"] = "Agg"

            result = subprocess.run(
                [
                    sys.executable,
                    str(REBUILDER),
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            for number in range(1, 10):
                matches = list(
                    (output_directory / "figures").glob(
                        f"Figure_{number}_*.pdf"
                    )
                )
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].read_bytes()[:4], b"%PDF")
                self.assertGreater(matches[0].stat().st_size, 1000)
            comparison_csv = (
                output_directory / "data" / "comparison_table.csv"
            )
            self.assertGreater(comparison_csv.stat().st_size, 100)

            receipt = json.loads(
                (output_directory / "rebuild-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(len(receipt["tasks"]), 6)
            self.assertEqual(
                sorted(path.name for path in working_directory.iterdir()),
                ["rebuilt"],
            )
            self.assertEqual(list(output_directory.glob("temp.*")), [])

    def test_rebuild_rejects_hpc_task(self):
        import importlib.util
        SPEC = importlib.util.spec_from_file_location(
            "rebuild_manuscript", ROOT / "scripts" / "rebuild_manuscript.py"
        )
        rebuild_module = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(rebuild_module)

        with tempfile.TemporaryDirectory() as temporary:
            manifest_file = Path(temporary) / "manifest.json"
            manifest_file.write_text(
                json.dumps({
                    "schema_version": 1,
                    "rebuild_tasks": [{
                        "id": "hpc_task",
                        "requires_hpc": True,
                        "inputs": [],
                        "outputs": [],
                        "commands": []
                    }]
                })
            )
            args = rebuild_module.parse_arguments([
                "--manifest", str(manifest_file),
                "--output-dir", str(Path(temporary) / "out")
            ])
            with self.assertRaisesRegex(rebuild_module.ConfigurationError, "prohibited"):
                rebuild_module.build_plan(args)

    def test_complete_package_uses_generated_data_without_touching_paper(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "manuscript"
            protected = [
                ROOT / "paper" / "paper.tex",
                *sorted((ROOT / "paper" / "data").glob("*")),
                *sorted((ROOT / "paper" / "tables").glob("*")),
                *sorted((ROOT / "paper" / "figures").glob("*")),
            ]
            before = {
                path: (path.stat().st_size, path.stat().st_mtime_ns)
                for path in protected
                if path.is_file()
            }
            result = subprocess.run(
                [
                    sys.executable,
                    str(REBUILDER),
                    "--output-dir",
                    str(output_directory),
                ],
                cwd=Path(temporary),
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("ablation", "scalability", "final_cases", "pruning"):
                self.assertGreater((output_directory / "data" / f"{name}.csv").stat().st_size, 50)
                self.assertGreater((output_directory / "tables" / f"{name}.tex").stat().st_size, 50)
            self.assertGreater(
                (output_directory / "data" / "comparison_feasibility.csv").stat().st_size,
                50,
            )
            self.assertGreater(
                (output_directory / "tables" / "comparison_feasibility.tex").stat().st_size,
                50,
            )
            self.assertGreater(
                (output_directory / "data" / "accuracy_audit.json").stat().st_size,
                50,
            )
            for name in ("accuracy_fixed", "accuracy_optimization"):
                self.assertGreater(
                    (output_directory / "data" / f"{name}.csv").stat().st_size,
                    50,
                )
                self.assertGreater(
                    (output_directory / "tables" / f"{name}.tex").stat().st_size,
                    50,
                )
            for number in range(1, 10):
                matches = list((output_directory / "figures").glob(f"Figure_{number}_*.pdf"))
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].read_bytes()[:4], b"%PDF")
            receipt = json.loads(
                (output_directory / "rebuild-results.json").read_text()
            )
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(len(receipt["tasks"]), 6)
            output_hashes = {
                path: digest
                for task in receipt["tasks"]
                for path, digest in task["output_sha256"].items()
            }
            self.assertEqual(
                len(
                    [
                        path
                        for path in output_hashes
                        if Path(path).suffix == ".pdf"
                    ]
                ),
                9,
            )
            self.assertTrue(all(len(digest) == 64 for digest in output_hashes.values()))
            self.assertNotIn(
                b"\r\n",
                (output_directory / "data" / "comparison_table.csv").read_bytes(),
            )
            comparison_rows = (
                output_directory / "data" / "comparison_table.csv"
            ).read_text(encoding="utf-8")
            self.assertIn("PublishedCost,ReevaluatedCost,Feasible,Reason", comparison_rows)
            self.assertIn(
                "Cimorelli et al. (2020),3634.67,0.000000,False,ACTUATIONS",
                comparison_rows,
            )
            artifact_manifest = json.loads(
                (output_directory / "artifact-manifest.json").read_text()
            )
            self.assertFalse(artifact_manifest["manuscript_modified"])
            after = {
                path: (path.stat().st_size, path.stat().st_mtime_ns)
                for path in before
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
