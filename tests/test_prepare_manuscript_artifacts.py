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
# Single-day replay of the external schedules, produced by
# evaluate_comparison_schedules.py --switch-count-convention single_day.
SINGLE_DAY_SUMMARY = ROOT / "tests" / "data" / "comparison-single-day-summary.json"
SINGLE_DAY_FINAL_CASES = RESULTS / "final-cases-single-day-anytown-24h-summary.json"


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
                float(scalability[-1]["speedup"]), 28.645975625066683
            )
            self.assertAlmostEqual(
                float(scalability[-1]["efficiency"]), 44.759336914166695
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
            self.assertIn("64 & 9.01 & 3.0 & 28.65 & 44.8 & 59.9", tex)
            self.assertIn("28.65", tex)
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
            self.assertIn("79 & 3.6", ablation_tex)
            self.assertIn("130.36$\\times$", ablation_tex)
            self.assertIn("Load imb. (\\%)", ablation_tex)
            self.assertIn("1.00$\\times$ & 39.8", ablation_tex)
            self.assertIn("4.68$\\times$ & 513.4", ablation_tex)
            self.assertNotIn("Cost (\\$)", ablation_tex)
            self.assertNotIn("Range (s)", ablation_tex)
            self.assertNotIn("pump sorting", ablation_tex.lower())

            with (output / "data" / "ablation.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                ablation_rows = list(csv.DictReader(stream))
            self.assertEqual(len(ablation_rows), 6)
            self.assertNotIn(
                "no-pump-sorting", {row["variant"] for row in ablation_rows}
            )
            self.assertAlmostEqual(
                float(ablation_rows[0]["wall_seconds_minimum"]),
                77.03998587839305,
            )
            self.assertAlmostEqual(
                float(ablation_rows[0]["wall_seconds_maximum"]),
                79.87313793227077,
            )

            final_cases_tex = (
                output / "tables" / "final_cases.tex"
            ).read_text(encoding="utf-8")
            self.assertIn("3{,}914.40 & 1.3 & 137.2", final_cases_tex)

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
            self.assertTrue(
                all(not Path(path).is_absolute() for path in receipt["inputs"])
            )
            self.assertIn("tables/pruning.tex", receipt["outputs"])
            self.assertIn("tables/comparison_feasibility.tex", receipt["outputs"])
            self.assertIn("data/accuracy_audit.json", receipt["outputs"])
            self.assertIn("tables/accuracy_fixed.tex", receipt["outputs"])
            self.assertIn("tables/accuracy_optimization.tex", receipt["outputs"])
            comparison_tex = (
                output / "tables" / "comparison_feasibility.tex"
            ).read_text(encoding="utf-8")
            self.assertIn("Tank level", comparison_tex)
            self.assertNotIn("LEVELS", comparison_tex)
            self.assertNotIn("Souza2026", comparison_tex)
            label_positions = [
                comparison_tex.index(PREPARE.EXTERNAL_SOURCE_LABELS[source])
                for source in PREPARE.EXTERNAL_SOURCES
            ]
            self.assertEqual(label_positions, sorted(label_positions))
            self.assertEqual(
                PREPARE.EXTERNAL_SOURCES,
                ("Costa2016", "Cimorelli2020", "Cimorelli2021", "Paola2025"),
            )
            with (output / "data" / "comparison_feasibility.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                comparison_rows = list(csv.DictReader(stream))
            self.assertEqual(
                len(comparison_rows), 3 * len(PREPARE.COMPARISON_SOURCES)
            )
            self.assertEqual(
                sum(row["source"] == "Souza2026" for row in comparison_rows),
                3,
            )
            self.assertFalse(
                json.loads(
                    (output / "data" / "run_Cimorelli2020_a_01.json").read_text()
                )["revised_validation"]["feasible"]
            )
            for actuations in (1, 2, 3):
                self.assertTrue(
                    json.loads(
                        (
                            output / "data" / f"run_Cimorelli2021_a_{actuations:02d}.json"
                        ).read_text()
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
                1.124351487742587,
            )
            self.assertAlmostEqual(
                float(optimization_a3_tight["wall_seconds_median"]),
                82.34207210317254,
            )
            self.assertAlmostEqual(
                float(optimization_a3_tight["paired_slowdown_vs_1e-4_median"]),
                1.0689175990985598,
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

    def test_single_day_final_cases_add_column_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manuscript"
            receipt = PREPARE.prepare_package(
                RESULTS / "ablation-anytown-24h-a3-summary.json",
                RESULTS / "scalability-anytown-24h-a2-summary.json",
                RESULTS / "final-cases-anytown-24h-summary.json",
                RESULTS / "comparison-feasibility-summary.json",
                RESULTS / "accuracy-sensitivity-anytown-24h-audit.json",
                RESULTS / "accuracy-sensitivity-anytown-24h-fixed.csv",
                RESULTS / "accuracy-sensitivity-anytown-24h-optimization.csv",
                COMPARISON_SCHEDULES,
                output,
                RESULTS / "comparison-feasibility-single-day-summary.json",
                SINGLE_DAY_FINAL_CASES,
            )
            self.assertIn(
                "experiments/results/final-cases-single-day-anytown-24h-summary.json",
                receipt["inputs"],
            )
            final_cases_tex = (output / "tables" / "final_cases.tex").read_text(
                encoding="utf-8"
            )
            self.assertTrue(
                final_cases_tex.startswith(
                    "\\begin{tabular}{@{}r@{\\quad}rrr@{}p{1em}@{}rrr@{}}"
                )
            )
            self.assertIn(
                "   & \\multicolumn{3}{c}{Periodic count} &  & "
                "\\multicolumn{3}{c}{Single-day count} \\\\",
                final_cases_tex,
            )
            self.assertIn("\\cline{2-4} \\cline{6-8}", final_cases_tex)
            self.assertIn(
                "1 & 3{,}914.40 & 1.3 & 137.2 &  & 3{,}634.60 & 1.8 & 108.0",
                final_cases_tex,
            )
            self.assertIn(
                "3 & 3{,}575.54 & 74.8 & 33.2 &  & 3{,}575.46 & 84.4 & 26.3",
                final_cases_tex,
            )
            pruning_tex = (output / "tables" / "pruning.tex").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "Classification (\\% of nodes) & 1 & 2 & 3 &  & 1 & 2 & 3", pruning_tex
            )
            self.assertIn(
                "Actuation & 53.0 & 44.7 & 25.6 &  & 52.3 & 42.2 & 23.4", pruning_tex
            )
            self.assertIn(
                "Explored nodes (count) & 226{,}745 & 10{,}675{,}946 & "
                "81{,}103{,}914 &  & 930{,}961 & 23{,}448{,}712 & 112{,}154{,}963",
                pruning_tex,
            )

            with (output / "data" / "final_cases.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                final_rows = list(csv.DictReader(stream))
            self.assertEqual(
                [(row["switch_count_convention"], row["NA_max"]) for row in final_rows],
                [
                    (convention, actuations)
                    for convention in ("periodic", "single_day")
                    for actuations in ("1", "2", "3")
                ],
            )
            self.assertAlmostEqual(float(final_rows[2]["cost"]), 3575.538064040429)
            self.assertAlmostEqual(float(final_rows[5]["cost"]), 3575.463601765812)
            with (output / "data" / "pruning.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                pruning_rows = list(csv.DictReader(stream))
            self.assertEqual(len(pruning_rows), 2 * 3 * len(PREPARE.PRUNING_ORDER))
            self.assertEqual(
                {row["switch_count_convention"] for row in pruning_rows},
                {"periodic", "single_day"},
            )

            # Without the option, the periodic tables keep their layout.
            plain = Path(temporary) / "plain"
            self.prepare(plain)
            for name in ("final_cases.tex", "pruning.tex"):
                self.assertNotIn(
                    "Single-day",
                    (plain / "tables" / name).read_text(encoding="utf-8"),
                )

    def test_single_day_final_cases_are_validated(self) -> None:
        final_cases = PREPARE.load_json(RESULTS / "final-cases-anytown-24h-summary.json")
        single_day = PREPARE.load_json(SINGLE_DAY_FINAL_CASES)
        PREPARE.validate_single_day_final_cases(final_cases, single_day)
        with self.assertRaisesRegex(
            PREPARE.PreparationError, "must use the single_day switch count"
        ):
            PREPARE.validate_single_day_final_cases(final_cases, final_cases)
        changed = json.loads(json.dumps(single_day))
        changed["configuration"]["level"] = 9
        with self.assertRaisesRegex(
            PREPARE.PreparationError, "different configurations"
        ):
            PREPARE.validate_single_day_final_cases(final_cases, changed)
        changed = json.loads(json.dumps(single_day))
        changed["cases"] = changed["cases"][:2]
        with self.assertRaisesRegex(PREPARE.PreparationError, "NA_max=1,2,3"):
            PREPARE.validate_single_day_final_cases(final_cases, changed)
        with self.assertRaisesRegex(
            PREPARE.PreparationError, "must use the periodic switch count"
        ):
            PREPARE.validate_summaries(
                PREPARE.load_json(RESULTS / "ablation-anytown-24h-a3-summary.json"),
                PREPARE.load_json(RESULTS / "scalability-anytown-24h-a2-summary.json"),
                single_day,
            )

    def test_single_day_comparison_costs_match_single_day_final_cases(self) -> None:
        comparison = PREPARE.load_json(
            RESULTS / "comparison-feasibility-single-day-summary.json"
        )
        for record in comparison["records"]:
            if record["source"] == "Souza2026" and record["actuations"] == 2:
                record["published_cost"] += 1.0
        with tempfile.TemporaryDirectory() as temporary:
            modified = Path(temporary) / "comparison-single-day.json"
            modified.write_text(json.dumps(comparison), encoding="utf-8")
            with self.assertRaisesRegex(
                PREPARE.PreparationError, "differs from the final cases: NA_max=2"
            ):
                PREPARE.prepare_package(
                    RESULTS / "ablation-anytown-24h-a3-summary.json",
                    RESULTS / "scalability-anytown-24h-a2-summary.json",
                    RESULTS / "final-cases-anytown-24h-summary.json",
                    RESULTS / "comparison-feasibility-summary.json",
                    RESULTS / "accuracy-sensitivity-anytown-24h-audit.json",
                    RESULTS / "accuracy-sensitivity-anytown-24h-fixed.csv",
                    RESULTS / "accuracy-sensitivity-anytown-24h-optimization.csv",
                    COMPARISON_SCHEDULES,
                    Path(temporary) / "manuscript",
                    modified,
                    SINGLE_DAY_FINAL_CASES,
                )

    def prepare_single_day(self, summary: dict, output: Path) -> dict:
        (output / "data").mkdir(parents=True)
        (output / "tables").mkdir()
        return PREPARE.prepare_single_day_comparison(
            summary, output / "data", output / "tables"
        )

    def test_single_day_comparison_table_follows_periodic_layout(self) -> None:
        summary = PREPARE.load_json(SINGLE_DAY_SUMMARY)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.prepare_single_day(summary, output)
            tex = (
                output / "tables" / "comparison_feasibility_single_day.tex"
            ).read_text(encoding="utf-8")
            self.assertTrue(tex.startswith("\\begin{tabular}{@{}lrrlrr@{}}"))
            self.assertIn(
                "Source & $NA_{\\max}$ & Feasible & Reason & Published (\\$) & "
                "Replay (\\$)",
                tex,
            )
            positions = [
                tex.index(PREPARE.EXTERNAL_SOURCE_LABELS[source])
                for source in PREPARE.EXTERNAL_SOURCES
            ]
            self.assertEqual(positions, sorted(positions))
            self.assertIn(
                "Cimorelli et al. (2020) & 1 & Yes & -- & 3{,}634.67 & 3{,}634.60",
                tex,
            )
            with (output / "data" / "comparison_feasibility_single_day.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3 * len(PREPARE.EXTERNAL_SOURCES))
            self.assertNotIn("Souza2026", {row["source"] for row in rows})
            self.assertEqual(rows[6]["source"], "Cimorelli2021")
            self.assertEqual(rows[6]["single_day_switch_on_counts"], "1/0/1")
            self.assertEqual(rows[6]["periodic_switch_counts"], "2/2/2")

    def test_single_day_table_names_its_actuation_rule(self) -> None:
        summary = PREPARE.load_json(SINGLE_DAY_SUMMARY)
        record = summary["records"][0]
        record.update(
            feasible=False, prune_reason="ACTUATIONS", hour_failed=24
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.prepare_single_day(summary, output)
            tex = (
                output / "tables" / "comparison_feasibility_single_day.tex"
            ).read_text(encoding="utf-8")
        self.assertIn("Costa et al. (2016) & 1 & No & Single-day actuation", tex)
        self.assertNotIn("Periodic actuation", tex)
        self.assertEqual(
            PREPARE.COMPARISON_REASON_LABELS["ACTUATIONS"], "Periodic actuation"
        )

    def test_single_day_table_accepts_complete_revised_source(self) -> None:
        summary = PREPARE.load_json(SINGLE_DAY_SUMMARY)
        revised = [
            dict(record, source="Souza2026")
            for record in summary["records"]
            if record["source"] == "Cimorelli2020"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "complete"
            by_key = self.prepare_single_day(
                dict(summary, records=summary["records"] + revised), output
            )
            self.assertIn(("Souza2026", 3), by_key)
            with (output / "data" / "comparison_feasibility_single_day.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3 * len(PREPARE.COMPARISON_SOURCES))
            self.assertEqual(rows[-1]["source"], "Souza2026")
            self.assertNotIn(
                "Souza2026",
                (
                    output / "tables" / "comparison_feasibility_single_day.tex"
                ).read_text(encoding="utf-8"),
            )
            with self.assertRaisesRegex(
                PREPARE.PreparationError, "must contain 15 records"
            ):
                self.prepare_single_day(
                    dict(summary, records=summary["records"] + revised[:2]),
                    Path(temporary) / "partial",
                )

    def test_comparison_tables_reject_the_other_convention(self) -> None:
        summary = PREPARE.load_json(SINGLE_DAY_SUMMARY)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaisesRegex(
                PREPARE.PreparationError, "must use the periodic switch count"
            ):
                PREPARE.prepare_comparison_validation(summary, output, output)
            periodic = dict(summary)
            del periodic["switch_count_convention"]
            with self.assertRaisesRegex(
                PREPARE.PreparationError, "must use the single_day switch count"
            ):
                self.prepare_single_day(periodic, output / "periodic")

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
                content + "\n",
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
