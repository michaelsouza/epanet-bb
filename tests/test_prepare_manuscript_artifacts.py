#!/usr/bin/env python3

import csv
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_manuscript_artifacts",
    ROOT / "scripts" / "prepare_manuscript_artifacts.py",
)
PREPARE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PREPARE)
RESULTS = ROOT / "experiments" / "results"
COMPARISON_SCHEDULES = ROOT / "experiments" / "comparison-schedules"


class PrepareManuscriptArtifactsTests(unittest.TestCase):
    def test_relative_range_is_normalized_by_the_median(self) -> None:
        self.assertAlmostEqual(
            PREPARE.relative_range_percentage(
                {
                    "wall_seconds_minimum": 8.0,
                    "wall_seconds_median": 10.0,
                    "wall_seconds_maximum": 13.0,
                }
            ),
            50.0,
        )
        with self.assertRaisesRegex(
            PREPARE.PreparationError, "median must be positive"
        ):
            PREPARE.relative_range_percentage(
                {
                    "wall_seconds_minimum": 0.0,
                    "wall_seconds_median": 0.0,
                    "wall_seconds_maximum": 0.0,
                }
            )

    def prepare(self, output: Path) -> dict:
        return PREPARE.prepare_package(
            RESULTS / "ablation-anytown-24h-a3-summary.json",
            RESULTS / "scalability-anytown-24h-a2-summary.json",
            RESULTS / "final-cases-anytown-24h-summary.json",
            RESULTS / "comparison-feasibility-summary.json",
            RESULTS / "accuracy-sensitivity-anytown-24h-audit.json",
            RESULTS / "accuracy-sensitivity-anytown-24h-fixed.csv",
            RESULTS / "accuracy-sensitivity-anytown-24h-optimization.csv",
            COMPARISON_SCHEDULES,
            output,
        )

    def test_prepares_consistent_csv_tex_and_solution_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manuscript"
            receipt = self.prepare(output)

            with (output / "data" / "scalability.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                scalability = list(csv.DictReader(stream))
            self.assertEqual(
                [int(row["np"]) for row in scalability],
                [1, 2, 4, 8, 16, 32, 64],
            )
            self.assertAlmostEqual(
                float(scalability[-1]["speedup"]), 28.675051757437444
            )
            self.assertAlmostEqual(
                float(scalability[-1]["efficiency"]), 44.80476837099601
            )

            with (output / "data" / "final_cases.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                final_cases = list(csv.DictReader(stream))
            self.assertEqual([row["NA_max"] for row in final_cases], ["1", "2", "3"])
            self.assertAlmostEqual(float(final_cases[2]["cost"]), 3575.5380640403023)

            tex = (output / "tables" / "scalability.tex").read_text(
                encoding="utf-8"
            )
            self.assertIn("\\multicolumn{2}{c}{Wall time (s)}", tex)
            self.assertIn("\\cline{2-3}", tex)
            self.assertIn("r@{\\quad}r@{}", tex)
            self.assertIn(
                "$N_{\\mathrm{procs}}$ & Median & Range (\\%) & Speedup & "
                "Eff. (\\%) & Load imb. (\\%)",
                tex,
            )
            self.assertIn("64 & 24.44 & 0.2 & 28.68 & 44.8 & 87.7", tex)
            self.assertIn("28.68", tex)
            self.assertNotIn("caption", tex)
            self.assertNotIn("label", tex)
            self.assertNotIn(b"\r\n", (output / "data" / "scalability.csv").read_bytes())

            ablation_tex = (output / "tables" / "ablation.tex").read_text(
                encoding="utf-8"
            )
            self.assertIn("\\multicolumn{2}{c}{Wall time (s)}", ablation_tex)
            self.assertIn("\\cline{2-3}", ablation_tex)
            self.assertIn("r@{\\;}c@{\\quad}", ablation_tex)
            self.assertIn("Median & Range (\\%)", ablation_tex)
            self.assertIn("433 & 1.2", ablation_tex)
            self.assertIn("26.86$\\times$", ablation_tex)
            self.assertIn("Load imb. (\\%)", ablation_tex)
            self.assertIn("1.00$\\times$ & 49.3", ablation_tex)
            self.assertIn("5.84$\\times$ & 701.2", ablation_tex)
            self.assertNotIn("Cost (\\$)", ablation_tex)
            self.assertNotIn("Range (s)", ablation_tex)
            self.assertNotIn("pump sorting", ablation_tex.lower())

            with (output / "data" / "ablation.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                ablation_rows = list(csv.DictReader(stream))
            self.assertEqual(len(ablation_rows), 5)
            self.assertNotIn(
                "no-pump-sorting", {row["variant"] for row in ablation_rows}
            )
            self.assertAlmostEqual(
                float(ablation_rows[0]["wall_seconds_minimum"]),
                431.1286457721144,
            )
            self.assertAlmostEqual(
                float(ablation_rows[0]["wall_seconds_maximum"]),
                436.1380685600452,
            )

            final_cases_tex = (
                output / "tables" / "final_cases.tex"
            ).read_text(encoding="utf-8")
            self.assertIn("3{,}900.25 & 1.6 & 227.5", final_cases_tex)

            pruning_tex = (output / "tables" / "pruning.tex").read_text(
                encoding="utf-8"
            )
            self.assertIn("\\multicolumn{3}{c}{$NA_{\\max}$}", pruning_tex)
            self.assertIn("Classification (\\% of nodes)", pruning_tex)
            self.assertIn("Explored nodes (count)", pruning_tex)

            solution = json.loads(
                (output / "data" / "run_Souza2026_a_03.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(solution["max_actuations"], 3)
            self.assertEqual(len(solution["best_x"]), 75)
            self.assertEqual(receipt["manuscript_modified"], False)
            self.assertIn("tables/pruning.tex", receipt["outputs"])
            self.assertIn("tables/comparison_feasibility.tex", receipt["outputs"])
            self.assertIn("data/accuracy_audit.json", receipt["outputs"])
            self.assertIn("tables/accuracy_fixed.tex", receipt["outputs"])
            self.assertIn("tables/accuracy_optimization.tex", receipt["outputs"])
            comparison_tex = (
                output / "tables" / "comparison_feasibility.tex"
            ).read_text(encoding="utf-8")
            self.assertIn("Tank saturation", comparison_tex)
            self.assertNotIn("TANK_SATURATION", comparison_tex)
            self.assertNotIn("Souza2026", comparison_tex)
            for source_label in PREPARE.EXTERNAL_SOURCE_LABELS.values():
                self.assertIn(source_label, comparison_tex)
            with (output / "data" / "comparison_feasibility.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                comparison_rows = list(csv.DictReader(stream))
            self.assertEqual(len(comparison_rows), 12)
            self.assertEqual(
                sum(row["source"] == "Souza2026" for row in comparison_rows),
                3,
            )
            self.assertFalse(
                json.loads(
                    (output / "data" / "run_Cimorelli2020_a_01.json").read_text()
                )["revised_validation"]["feasible"]
            )

            with (output / "data" / "accuracy_fixed.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                fixed_accuracy = list(csv.DictReader(stream))
            with (output / "data" / "accuracy_optimization.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                optimization_accuracy = list(csv.DictReader(stream))
            self.assertEqual(len(fixed_accuracy), 9)
            self.assertEqual(len(optimization_accuracy), 9)
            fixed_a3_tight = fixed_accuracy[-1]
            optimization_a3_tight = optimization_accuracy[-1]
            self.assertEqual(fixed_a3_tight["trials_total_median"], "328.0")
            self.assertAlmostEqual(
                float(fixed_a3_tight["hydraulic_slowdown_vs_1e-4_median"]),
                1.1388511778308814,
            )
            self.assertAlmostEqual(
                float(optimization_a3_tight["wall_seconds_median"]),
                462.2319227620028,
            )
            self.assertAlmostEqual(
                float(optimization_a3_tight["paired_slowdown_vs_1e-4_median"]),
                1.0802802993843004,
            )
            self.assertEqual(optimization_a3_tight["unique_schedules"], "1")
            for name in ("accuracy_fixed", "accuracy_optimization"):
                accuracy_tex = (output / "tables" / f"{name}.tex").read_text(
                    encoding="utf-8"
                )
                self.assertIn("$10^{-7}$", accuracy_tex)
                self.assertNotIn("caption", accuracy_tex)
                self.assertNotIn("label", accuracy_tex)
                self.assertTrue(accuracy_tex.endswith("\n"))

    def test_rejects_cross_campaign_cost_disagreement(self) -> None:
        ablation = PREPARE.load_json(
            RESULTS / "ablation-anytown-24h-a3-summary.json"
        )
        scalability = PREPARE.load_json(
            RESULTS / "scalability-anytown-24h-a2-summary.json"
        )
        final_cases = PREPARE.load_json(
            RESULTS / "final-cases-anytown-24h-summary.json"
        )
        final_cases["cases"][1]["global_best_cost"] += 1.0

        with self.assertRaisesRegex(PREPARE.PreparationError, "NA_max=2 cost"):
            PREPARE.validate_summaries(ablation, scalability, final_cases)

    def test_rejects_accuracy_csv_that_differs_from_audit(self) -> None:
        audit_path = RESULTS / "accuracy-sensitivity-anytown-24h-audit.json"
        fixed_path = RESULTS / "accuracy-sensitivity-anytown-24h-fixed.csv"
        optimization_path = (
            RESULTS / "accuracy-sensitivity-anytown-24h-optimization.csv"
        )
        final_cases = PREPARE.load_json(
            RESULTS / "final-cases-anytown-24h-summary.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            modified_fixed = Path(temporary) / fixed_path.name
            shutil.copyfile(fixed_path, modified_fixed)
            content = modified_fixed.read_text(encoding="utf-8")
            modified_fixed.write_text(
                content.replace("0.9309758044241271", "0.9309758044241272", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                PREPARE.PreparationError, "fixed-schedule CSV hash"
            ):
                PREPARE.validate_accuracy_inputs(
                    PREPARE.load_json(audit_path),
                    modified_fixed,
                    optimization_path,
                    final_cases,
                )


if __name__ == "__main__":
    unittest.main()
