#!/usr/bin/env python3
"""Prepare auditable manuscript data and LaTeX fragments from final summaries."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil


ROOT = Path(__file__).absolute().parents[1]
DEFAULT_RESULTS = ROOT / "experiments" / "results"
DEFAULT_COMPARISON_DATA = ROOT / "experiments" / "comparison-schedules"

VARIANT_LABELS = {
    "baseline": "All features",
    "no-cost-pruning": "No cost pruning",
    "no-cost-to-go": "No cost-to-go bound",
    "no-snapshots": "No snapshots",
    "no-task-shuffle": "No task shuffling",
    "no-global-sync": "No global synchronization",
}
VARIANT_ORDER = tuple(VARIANT_LABELS)
EXPECTED_ABLATION_VARIANTS = set(VARIANT_ORDER) | {"no-pump-sorting"}
PRUNING_ORDER = (
    "Actuation",
    "Cost bound",
    "Cost-to-go bound",
    "Tank levels",
    "Pressure",
    "Total pruned",
    "Feasible",
)
# Chronological order of publication; the comparison table follows it.
EXTERNAL_SOURCES = ("Costa2016", "Cimorelli2020", "Cimorelli2021", "Paola2025")
EXTERNAL_SOURCE_LABELS = {
    "Costa2016": "Costa et al. (2016)",
    "Cimorelli2020": "Cimorelli et al. (2020)",
    "Cimorelli2021": "Cimorelli et al. (2021)",
    "Paola2025": "De Paola et al. (2025)",
}
COMPARISON_SOURCES = (*EXTERNAL_SOURCES, "Souza2026")
COMPARISON_REASON_LABELS = {
    "NONE": "--",
    "ACTUATIONS": "Periodic actuation",
    "LEVELS": "Tank level",
    "PRESSURES": "Pressure",
    "TANK_SATURATION": "Tank saturation",
}
# The single-day table names the switch count it applies.
SINGLE_DAY_REASON_LABELS = {
    **COMPARISON_REASON_LABELS,
    "ACTUATIONS": "Single-day actuation",
}
ACCURACY_ORDER = ("1e-3", "1e-4", "1e-7")
ACCURACY_LABELS = {
    "1e-3": "$10^{-3}$",
    "1e-4": "$10^{-4}$",
    "1e-7": "$10^{-7}$",
}


class PreparationError(RuntimeError):
    """Raised when audited inputs are absent or mutually inconsistent."""


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise PreparationError(f"missing required input: {path}")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def validate_summaries(
    ablation: dict,
    scalability: dict,
    final_cases: dict,
) -> None:
    for name, payload in (
        ("ablation", ablation),
        ("scalability", scalability),
        ("final cases", final_cases),
    ):
        if payload.get("schema_version") != 1:
            raise PreparationError(f"{name} summary has an unsupported schema")
    # The original final-cases summary predates the field and is periodic.
    if final_cases.get("switch_count_convention", "periodic") != "periodic":
        raise PreparationError("final cases summary must use the periodic switch count")
    hashes = {
        ablation.get("executable_sha256"),
        scalability.get("executable_sha256"),
        final_cases.get("executable_sha256"),
    }
    if None in hashes or len(hashes) != 1:
        raise PreparationError("summaries used different executables")

    ablation_configuration = ablation.get("configuration", {})
    scalability_configuration = scalability.get("configuration", {})
    final_configuration = final_cases.get("configuration", {})
    common_expected = {"hours": 24, "level": 8, "sync_interval": 32768}
    for name, configuration in (
        ("ablation", ablation_configuration),
        ("scalability", scalability_configuration),
        ("final cases", final_configuration),
    ):
        observed = {key: configuration.get(key) for key in common_expected}
        if observed != common_expected:
            raise PreparationError(f"{name} configuration differs from the final protocol")
    if ablation_configuration.get("actuations") != [3]:
        raise PreparationError("ablation summary is not the NA_max=3 study")
    if scalability_configuration.get("actuations") != [2]:
        raise PreparationError("scalability summary is not the NA_max=2 study")
    if ablation_configuration.get("np") != 64 or final_configuration.get("np") != 64:
        raise PreparationError("ablation and final cases must use 64 ranks")

    cases = {case["actuations"]: case for case in final_cases.get("cases", [])}
    if sorted(cases) != [1, 2, 3]:
        raise PreparationError("final summary must contain NA_max=1,2,3")
    if not close(cases[2]["global_best_cost"], scalability["global_best_cost"]):
        raise PreparationError("NA_max=2 cost differs between final and scalability data")
    if not close(cases[3]["global_best_cost"], ablation["global_best_cost"]):
        raise PreparationError("NA_max=3 cost differs between final and ablation data")

    variants = {variant["id"] for variant in ablation.get("variants", [])}
    if variants != EXPECTED_ABLATION_VARIANTS:
        raise PreparationError("ablation summary has an unexpected variant set")
    process_counts = [point["process_count"] for point in scalability.get("points", [])]
    if process_counts != [1, 2, 4, 8, 16, 32, 64]:
        raise PreparationError("scalability summary has an unexpected process grid")


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PreparationError(f"missing required input: {path}")
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def format_cost(value: float) -> str:
    return f"{value:,.2f}".replace(",", "{,}")


def format_scientific(value: float) -> str:
    if value == 0.0:
        return "$0$"
    mantissa, exponent = f"{value:.3e}".split("e")
    return f"${mantissa}\\times10^{{{int(exponent)}}}$"


def relative_range_percentage(values: dict) -> float:
    median = float(values["wall_seconds_median"])
    if median <= 0.0:
        raise PreparationError("wall-time median must be positive")
    return 100.0 * (
        float(values["wall_seconds_maximum"])
        - float(values["wall_seconds_minimum"])
    ) / median


def tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def tex_table(column_specification: str, header: list[str], rows: list[list[str]]) -> str:
    lines = [
        f"\\begin{{tabular}}{{{column_specification}}}",
        "  \\hline",
        "  " + " & ".join(header) + " \\\\",
        "  \\hline",
    ]
    lines.extend("  " + " & ".join(row) + " \\\\" for row in rows)
    lines.extend(["  \\hline", "\\end{tabular}", ""])
    return "\n".join(lines)


def tex_table_with_grouped_wall_time(
    column_specification: str,
    leading_headers: list[str],
    trailing_headers: list[str],
    rows: list[list[str]],
) -> str:
    grouped_header = (
        ["" for _ in leading_headers]
        + ["\\multicolumn{2}{c}{Wall time (s)}"]
        + ["" for _ in trailing_headers]
    )
    detail_header = [*leading_headers, "Median", "Range (\\%)", *trailing_headers]
    wall_time_start = len(leading_headers) + 1
    wall_time_end = wall_time_start + 1
    lines = [
        f"\\begin{{tabular}}{{{column_specification}}}",
        "  \\hline",
        "  " + " & ".join(grouped_header) + " \\\\",
        f"  \\cline{{{wall_time_start}-{wall_time_end}}}",
        "  " + " & ".join(detail_header) + " \\\\",
        "  \\hline",
    ]
    lines.extend("  " + " & ".join(row) + " \\\\" for row in rows)
    lines.extend(["  \\hline", "\\end{tabular}", ""])
    return "\n".join(lines)


def validate_accuracy_inputs(
    audit: dict,
    fixed_path: Path,
    optimization_path: Path,
    final_cases: dict,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if audit.get("schema_version") != 1:
        raise PreparationError("accuracy audit has an unsupported schema")
    expected_counts = {
        "fixed_records": 45,
        "optimization_records": 27,
        "rank_stats_files": 1728,
        "rank_best_files": 1728,
        "timeouts": 0,
        "hydraulic_nonconvergence_events": 0,
        "artifact_count": 3501,
    }
    if any(audit.get(key) != value for key, value in expected_counts.items()):
        raise PreparationError("accuracy audit is incomplete or inconclusive")
    if audit.get("all_return_codes") != [0]:
        raise PreparationError("accuracy audit contains a nonzero return code")
    if audit.get("unique_schedules_across_accuracies") != {
        "1": 1,
        "2": 1,
        "3": 1,
    }:
        raise PreparationError("accuracy audit did not preserve one schedule per case")
    if set(audit.get("unique_costs_per_repeated_cell", {}).values()) != {1}:
        raise PreparationError("accuracy repetitions did not preserve deterministic costs")

    protocol = audit.get("protocol", {})
    fixed_protocol = protocol.get("fixed", {})
    optimization_protocol = protocol.get("optimization", {})
    observed_accuracies = [
        entry.get("id") for entry in protocol.get("accuracies", [])
    ]
    if observed_accuracies != list(ACCURACY_ORDER):
        raise PreparationError("accuracy audit has an unexpected accuracy grid")
    if fixed_protocol != {"hydraulic_max_trials": 40, "repetitions": 5}:
        raise PreparationError("accuracy fixed-schedule protocol differs")
    expected_optimization_protocol = {
        "actuations": [1, 2, 3],
        "hours": 24,
        "hydraulic_max_trials": 40,
        "level": 8,
        "process_count": 64,
        "repetitions": 3,
        "sync_interval": 32768,
        "timeout_seconds": 900,
    }
    if optimization_protocol != expected_optimization_protocol:
        raise PreparationError("accuracy optimization protocol differs")

    source_hashes = audit.get("source_sha256", {})
    if source_hashes.get("fixed-schedule-aggregate.csv") != sha256(fixed_path):
        raise PreparationError("accuracy fixed-schedule CSV hash differs from audit")
    if source_hashes.get("optimization-aggregate.csv") != sha256(
        optimization_path
    ):
        raise PreparationError("accuracy optimization CSV hash differs from audit")

    fixed_rows = read_rows(fixed_path)
    optimization_rows = read_rows(optimization_path)
    expected_grid = {
        (str(actuations), accuracy_id)
        for actuations in (1, 2, 3)
        for accuracy_id in ACCURACY_ORDER
    }
    fixed_grid = {(row["actuations"], row["accuracy_id"]) for row in fixed_rows}
    optimization_grid = {
        (row["actuations"], row["accuracy_id"])
        for row in optimization_rows
    }
    if len(fixed_rows) != 9 or fixed_grid != expected_grid:
        raise PreparationError("accuracy fixed-schedule CSV has an unexpected grid")
    if len(optimization_rows) != 9 or optimization_grid != expected_grid:
        raise PreparationError("accuracy optimization CSV has an unexpected grid")

    final_costs = {
        str(case["actuations"]): case["global_best_cost"]
        for case in final_cases.get("cases", [])
    }
    if set(final_costs) != {"1", "2", "3"}:
        raise PreparationError("final cases are missing an accuracy reference cost")
    for row in fixed_rows:
        if (
            row["records"] != "5"
            or row["hydraulic_converged"] != "5"
            or row["feasible"] != "5"
            or row["paired_complete_traces"] != "5"
        ):
            raise PreparationError("accuracy fixed-schedule row is inconclusive")
        if row["accuracy_id"] == "1e-4" and not close(
            float(row["cost_median"]), final_costs[row["actuations"]]
        ):
            raise PreparationError("accuracy fixed-schedule reference cost differs")
    for row in optimization_rows:
        if (
            row["records"] != "3"
            or row["conclusive"] != "3"
            or row["nonconclusive"] != "0"
            or row["timed_out"] != "0"
            or row["unique_schedules"] != "1"
            or row["hydraulic_nonconvergence_events"] != "0"
        ):
            raise PreparationError("accuracy optimization row is inconclusive")
        if row["accuracy_id"] == "1e-4" and not close(
            float(row["cost_median"]), final_costs[row["actuations"]]
        ):
            raise PreparationError("accuracy optimization reference cost differs")
    return fixed_rows, optimization_rows


def prepare_accuracy(
    audit: dict,
    audit_path: Path,
    fixed_path: Path,
    optimization_path: Path,
    final_cases: dict,
    data_dir: Path,
    tables_dir: Path,
) -> None:
    fixed_rows, optimization_rows = validate_accuracy_inputs(
        audit, fixed_path, optimization_path, final_cases
    )
    shutil.copyfile(audit_path, data_dir / "accuracy_audit.json")
    shutil.copyfile(fixed_path, data_dir / "accuracy_fixed.csv")
    shutil.copyfile(optimization_path, data_dir / "accuracy_optimization.csv")

    fixed_by_key = {
        (int(row["actuations"]), row["accuracy_id"]): row
        for row in fixed_rows
    }
    fixed_tex_rows = []
    for actuations in (1, 2, 3):
        for accuracy_id in ACCURACY_ORDER:
            row = fixed_by_key[(actuations, accuracy_id)]
            fixed_tex_rows.append(
                [
                    str(actuations),
                    ACCURACY_LABELS[accuracy_id],
                    f"{float(row['trials_total_median']):.0f}",
                    f"{1000.0 * float(row['hydraulic_seconds_median']):.3f}",
                    f"{float(row['hydraulic_slowdown_vs_1e-4_median']):.3f}",
                    format_scientific(float(row["max_cost_delta_vs_1e-4"])),
                ]
            )
    (tables_dir / "accuracy_fixed.tex").write_text(
        tex_table(
            "@{}rrrcrc@{}",
            [
                "$NA_{\\max}$",
                "Accuracy",
                "Hyd. trials",
                "Hyd. time (ms)",
                "Time ratio",
                "Max. cost $\\Delta$ (\\$)",
            ],
            fixed_tex_rows,
        ),
        encoding="utf-8",
    )

    optimization_by_key = {
        (int(row["actuations"]), row["accuracy_id"]): row
        for row in optimization_rows
    }
    optimization_tex_rows = []
    for actuations in (1, 2, 3):
        for accuracy_id in ACCURACY_ORDER:
            row = optimization_by_key[(actuations, accuracy_id)]
            optimization_tex_rows.append(
                [
                    str(actuations),
                    ACCURACY_LABELS[accuracy_id],
                    f"{float(row['wall_seconds_median']):.3f}",
                    f"{float(row['paired_slowdown_vs_1e-4_median']):.3f}",
                    format_cost(float(row["cost_median"])),
                    f"{float(row['nodes_median']):,.0f}".replace(",", "{,}"),
                    row["unique_schedules"],
                ]
            )
    (tables_dir / "accuracy_optimization.tex").write_text(
        tex_table(
            "@{}ccrrrrc@{}",
            [
                "$NA_{\\max}$",
                "Accuracy",
                "Median (s)",
                "Time ratio",
                "Cost (\\$)",
                "Nodes",
                "Distinct schedules",
            ],
            optimization_tex_rows,
        ),
        encoding="utf-8",
    )


def prepare_ablation(summary: dict, data_dir: Path, tables_dir: Path) -> None:
    by_id = {variant["id"]: variant for variant in summary["variants"]}
    rows = []
    tex_rows = []
    for variant_id in VARIANT_ORDER:
        variant = by_id[variant_id]
        values = variant["summary"]
        row = {
            "variant": variant_id,
            "configuration": VARIANT_LABELS[variant_id],
            **values,
            "global_best_cost": summary["global_best_cost"],
        }
        rows.append(row)
        tex_rows.append(
            [
                VARIANT_LABELS[variant_id],
                f"{values['wall_seconds_median']:.0f}",
                f"{relative_range_percentage(values):.1f}",
                f"{values['paired_slowdown_median']:.2f}$\\times$",
                f"{100.0 * values['load_imbalance_factor_median']:.1f}",
            ]
        )
    fields = list(rows[0])
    write_rows(data_dir / "ablation.csv", fields, rows)
    (tables_dir / "ablation.tex").write_text(
        tex_table_with_grouped_wall_time(
            "@{}l@{\\quad}r@{\\;}c@{\\quad}r@{\\quad}r@{}",
            ["Configuration"],
            ["Slowdown", "Load imb. (\\%)"],
            tex_rows,
        ),
        encoding="utf-8",
    )


def prepare_scalability(summary: dict, data_dir: Path, tables_dir: Path) -> None:
    rows = []
    tex_rows = []
    for point in summary["points"]:
        values = point["summary"]
        row = {
            "np": point["process_count"],
            "wall_time": values["wall_seconds_median"],
            "wall_min": values["wall_seconds_minimum"],
            "wall_max": values["wall_seconds_maximum"],
            "proc_avg": values["average_rank_seconds_median"],
            "proc_max": values["maximum_rank_seconds_median"],
            "load_imbalance": values["load_imbalance_factor_median"],
            "total_tasks": summary["tasks_processed_per_point"],
            "speedup": values["paired_speedup_median"],
            "efficiency": 100.0 * values["paired_parallel_efficiency_median"],
            "candidate_assignments": values["candidate_assignments_median"],
        }
        rows.append(row)
        tex_rows.append(
            [
                str(point["process_count"]),
                f"{values['wall_seconds_median']:.2f}",
                f"{relative_range_percentage(values):.1f}",
                f"{values['paired_speedup_median']:.2f}",
                f"{100.0 * values['paired_parallel_efficiency_median']:.1f}",
                f"{100.0 * values['load_imbalance_factor_median']:.1f}",
            ]
        )
    write_rows(data_dir / "scalability.csv", list(rows[0]), rows)
    (tables_dir / "scalability.tex").write_text(
        tex_table_with_grouped_wall_time(
            "@{}r@{\\quad}r@{\\enspace}c@{\\quad}r@{\\quad}r@{\\quad}r@{}",
            ["$N_{\\mathrm{procs}}$"],
            ["Speedup", "Eff. (\\%)", "Load imb. (\\%)"],
            tex_rows,
        ),
        encoding="utf-8",
    )


PRUNING_REASONS = {
    "Actuation": ("ACTUATIONS",),
    "Cost bound": ("COST",),
    "Cost-to-go bound": ("COST_TO_GO",),
    "Tank levels": ("LEVELS", "TANK_SATURATION"),
    "Pressure": ("PRESSURES",),
}
# Column groups of the final-cases and pruning tables when both switch-count
# conventions are reported.
CONVENTION_GROUP_LABELS = {
    "periodic": "Periodic count",
    "single_day": "Single-day count",
}


def validate_single_day_final_cases(final_cases: dict, single_day: dict) -> None:
    """Check that the single-day final cases repeat the periodic protocol."""
    if single_day.get("schema_version") != 1:
        raise PreparationError("single-day final cases summary has an unsupported schema")
    if single_day.get("switch_count_convention") != "single_day":
        raise PreparationError(
            "single-day final cases summary must use the single_day switch count"
        )
    if single_day.get("max_switch_count_per_pump", {"1": 1, "2": 2, "3": 3}) != {
        "1": 1,
        "2": 2,
        "3": 3,
    }:
        raise PreparationError(
            "single-day final cases summary has unexpected switch limits"
        )
    if single_day.get("configuration") != final_cases.get("configuration"):
        raise PreparationError(
            "periodic and single-day final cases used different configurations"
        )
    periodic_cases = {case["actuations"]: case for case in final_cases["cases"]}
    single_day_cases = {
        case["actuations"]: case for case in single_day.get("cases", [])
    }
    if sorted(single_day_cases) != [1, 2, 3] or len(single_day.get("cases", [])) != 3:
        raise PreparationError("single-day final summary must contain NA_max=1,2,3")
    for actuations, case in single_day_cases.items():
        if case.get("configuration") != periodic_cases[actuations].get("configuration"):
            raise PreparationError(
                "periodic and single-day final cases used different "
                f"configurations: NA_max={actuations}"
            )


def tex_count(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def prepare_final_cases(
    summary: dict,
    data_dir: Path,
    tables_dir: Path,
    single_day_summary: dict | None = None,
) -> None:
    """Final-cases and pruning tables; single-day results add column groups."""
    grouped = single_day_summary is not None
    summaries = {"periodic": summary}
    if grouped:
        summaries["single_day"] = single_day_summary
    cases_by_convention = {
        convention: sorted(payload["cases"], key=lambda case: case["actuations"])
        for convention, payload in summaries.items()
    }
    rows = []
    pruning_rows = []
    for convention, cases in cases_by_convention.items():
        for case in cases:
            row = {
                "NA_max": case["actuations"],
                "cost": case["global_best_cost"],
                "wall_time": case["wall_seconds"],
                "proc_avg": case["average_rank_seconds"],
                "proc_max": case["maximum_rank_seconds"],
                "load_imbalance": case["load_imbalance_factor"],
                "candidate_assignments": case["candidate_assignments"],
                "total_tasks": case["tasks_processed"],
                "nodes_total": case["nodes_total"],
            }
            if grouped:
                row["switch_count_convention"] = convention
            rows.append(row)
            for criterion in PRUNING_ORDER:
                if criterion == "Feasible":
                    count = case["pruning_counts"]["NONE"]
                elif criterion == "Total pruned":
                    count = case["nodes_total"] - case["pruning_counts"]["NONE"]
                else:
                    count = sum(
                        case["pruning_counts"][reason]
                        for reason in PRUNING_REASONS[criterion]
                    )
                pruning_row = {
                    "NA_max": case["actuations"],
                    "criterion": criterion,
                    "count": count,
                    "percentage": case["pruning_percentages"][criterion],
                    "nodes_total": case["nodes_total"],
                }
                if grouped:
                    pruning_row["switch_count_convention"] = convention
                pruning_rows.append(pruning_row)

    for case in cases_by_convention["periodic"]:
        solution = {
            "best_cost": case["global_best_cost"],
            "duration": case["wall_seconds"],
            "max_actuations": case["actuations"],
            "inp_file": "networks/any-town.inp",
            "best_x": case["best_x"],
            "best_y": case["best_y"],
            "best_canonical_x": case.get("best_canonical_x"),
            "provenance": {
                "summary": "experiments/results/final-cases-anytown-24h-summary.json",
                "executable_sha256": summary["executable_sha256"],
                "git": summary["git"],
            },
        }
        (data_dir / f"run_Souza2026_a_{case['actuations']:02d}.json").write_text(
            json.dumps(solution, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    write_rows(data_dir / "final_cases.csv", list(rows[0]), rows)
    write_rows(data_dir / "pruning.csv", list(pruning_rows[0]), pruning_rows)

    def case_cells(case: dict) -> list[str]:
        return [
            format_cost(case["global_best_cost"]),
            f"{case['wall_seconds']:.1f}",
            f"{100.0 * case['load_imbalance_factor']:.1f}",
        ]

    conventions = list(cases_by_convention)

    def grouped_cells(cells_by_convention: list[list[str]]) -> list[str]:
        # An empty spacer column separates the convention groups so that the
        # \cline under each group header stays visibly separate.
        joined = list(cells_by_convention[0])
        for cells in cells_by_convention[1:]:
            joined.extend(["", *cells])
        return joined

    # Column layout of the grouped tables: leading column, three periodic
    # columns, a 1em spacer, three single-day columns.
    group_header = (
        "   & \\multicolumn{3}{c}{%s} &  & \\multicolumn{3}{c}{%s} \\\\"
    )
    group_rules = "  \\cline{2-4} \\cline{6-8}"
    group_columns = "rrr@{}p{1em}@{}rrr@{}}"
    tex_rows = [
        [str(actuations)]
        + grouped_cells(
            [
                case_cells(cases_by_convention[convention][index])
                for convention in conventions
            ]
        )
        for index, actuations in enumerate((1, 2, 3))
    ]
    if not grouped:
        final_cases_tex = tex_table(
            "@{}rrrr@{}",
            ["$NA_{\\max}$", "Cost (\\$)", "Time (s)", "Load imb. (\\%)"],
            tex_rows,
        )
    else:
        final_lines = [
            "\\begin{tabular}{@{}r@{\\quad}" + group_columns,
            "  \\hline",
            group_header
            % tuple(CONVENTION_GROUP_LABELS[convention] for convention in conventions),
            group_rules,
            "  "
            + " & ".join(
                ["$NA_{\\max}$"]
                + grouped_cells(
                    [["Cost (\\$)", "Time (s)", "Load imb. (\\%)"]] * len(conventions)
                )
            )
            + " \\\\",
            "  \\hline",
        ]
        final_lines.extend("  " + " & ".join(row) + " \\\\" for row in tex_rows)
        final_lines.extend(["  \\hline", "\\end{tabular}", ""])
        final_cases_tex = "\n".join(final_lines)
    (tables_dir / "final_cases.tex").write_text(final_cases_tex, encoding="utf-8")

    pruning_tex_rows = [
        ["Not pruned" if criterion == "Feasible" else criterion]
        + grouped_cells(
            [
                [
                    f"{case['pruning_percentages'][criterion]:.1f}"
                    for case in cases_by_convention[convention]
                ]
                for convention in conventions
            ]
        )
        for criterion in PRUNING_ORDER
    ]
    pruning_tex_rows.append(
        ["Explored nodes (count)"]
        + grouped_cells(
            [
                [tex_count(case["nodes_total"]) for case in cases_by_convention[convention]]
                for convention in conventions
            ]
        )
    )
    if not grouped:
        pruning_lines = [
            "\\begin{tabular}{@{}lrrr@{}}",
            "  \\hline",
            "   & \\multicolumn{3}{c}{$NA_{\\max}$} \\\\",
            "  \\cline{2-4}",
            "  Classification (\\% of nodes) & 1 & 2 & 3 \\\\",
            "  \\hline",
        ]
    else:
        pruning_lines = [
            "\\begin{tabular}{@{}l@{\\quad}" + group_columns,
            "  \\hline",
            group_header
            % tuple(
                f"{CONVENTION_GROUP_LABELS[convention]} ($NA_{{\\max}}$)"
                for convention in conventions
            ),
            group_rules,
            "  "
            + " & ".join(
                ["Classification (\\% of nodes)"]
                + grouped_cells([["1", "2", "3"]] * len(conventions))
            )
            + " \\\\",
            "  \\hline",
        ]
    pruning_lines.extend(
        "  " + " & ".join(row) + " \\\\" for row in pruning_tex_rows[:-1]
    )
    pruning_lines.extend(
        [
            "  \\hline",
            "  " + " & ".join(pruning_tex_rows[-1]) + " \\\\",
            "  \\hline",
            "\\end{tabular}",
            "",
        ]
    )
    (tables_dir / "pruning.tex").write_text(
        "\n".join(pruning_lines), encoding="utf-8"
    )


def validate_external_solution(path: Path) -> None:
    payload = load_json(path)
    best_x = payload.get("best_x")
    if not isinstance(best_x, list) or len(best_x) != 75:
        raise PreparationError(f"comparison solution has an invalid schedule: {path}")
    cost = payload.get("best_cost")
    if not isinstance(cost, (int, float)) or not math.isfinite(cost):
        raise PreparationError(f"comparison solution has an invalid cost: {path}")


def comparison_grid(
    summary: dict,
    convention: str,
    revised_required: bool,
    name: str = "comparison feasibility summary",
) -> tuple[dict[tuple[str, int], dict], tuple[str, ...]]:
    """Validate a replay summary; return its records by key and its sources.

    Our own source (Souza2026) is optional when revised_required is false,
    but must then be present for all three cases or for none.
    """
    if summary.get("schema_version") != 1 or summary.get("schedule_mode") != "binary":
        raise PreparationError(f"{name} is incompatible")
    # Summaries without the field predate the option and are periodic.
    if summary.get("switch_count_convention", "periodic") != convention:
        raise PreparationError(f"{name} must use the {convention} switch count")
    records = summary.get("records", [])
    sources = COMPARISON_SOURCES
    if not revised_required and not any(
        record.get("source") == "Souza2026" for record in records
    ):
        sources = EXTERNAL_SOURCES
    expected_records = 3 * len(sources)
    if len(records) != expected_records:
        raise PreparationError(f"{name} must contain {expected_records} records")
    by_key = {
        (record["source"], int(record["actuations"])): record
        for record in records
    }
    expected = {
        (source, actuations)
        for source in sources
        for actuations in (1, 2, 3)
    }
    if set(by_key) != expected:
        raise PreparationError(f"{name} has an unexpected grid")
    if len(by_key) != len(records):
        raise PreparationError(f"{name} contains duplicate records")
    return by_key, sources


def write_comparison_outputs(
    by_key: dict[tuple[str, int], dict],
    sources: tuple[str, ...],
    count_keys: tuple[str, ...],
    reason_labels: dict[str, str],
    csv_path: Path,
    tex_path: Path,
) -> None:
    """Write the CSV of every record and the LaTeX table of external sources."""
    fields = [
        "source",
        "actuations",
        "published_cost",
        "feasible",
        "prune_reason",
        "hour_failed",
        "reevaluated_cost",
        *count_keys,
    ]
    rows = []
    tex_rows = []
    for source in sources:
        for actuations in (1, 2, 3):
            record = by_key[(source, actuations)]
            row = {key: record[key] for key in fields}
            for key in count_keys:
                switches = record.get(key)
                if (
                    not isinstance(switches, list)
                    or len(switches) != 3
                    or any(
                        not isinstance(value, int) or value < 0
                        for value in switches
                    )
                ):
                    raise PreparationError(
                        f"invalid {key.replace('_', ' ')}: "
                        f"{source} NA_max={actuations}"
                    )
                row[key] = "/".join(str(value) for value in switches)
            if record["feasible"] != (record["prune_reason"] == "NONE"):
                raise PreparationError(
                    f"inconsistent replay status: {source} NA_max={actuations}"
                )
            rows.append(row)
            if source in EXTERNAL_SOURCES:
                tex_rows.append(
                    [
                        EXTERNAL_SOURCE_LABELS[source],
                        str(actuations),
                        "Yes" if record["feasible"] else "No",
                        reason_labels[record["prune_reason"]],
                        format_cost(record["published_cost"]),
                        format_cost(record["reevaluated_cost"])
                        if record["feasible"]
                        else "--",
                    ]
                )
    write_rows(csv_path, fields, rows)
    tex_path.write_text(
        tex_table(
            "@{}lrrlrr@{}",
            [
                "Source",
                "$NA_{\\max}$",
                "Feasible",
                "Reason",
                "Published (\\$)",
                "Replay (\\$)",
            ],
            tex_rows,
        ),
        encoding="utf-8",
    )


def prepare_comparison_validation(
    summary: dict,
    data_dir: Path,
    tables_dir: Path,
) -> dict[tuple[str, int], dict]:
    """Periodic replay table; every source, including ours, is required."""
    by_key, sources = comparison_grid(summary, "periodic", revised_required=True)
    write_comparison_outputs(
        by_key,
        sources,
        ("periodic_switch_counts",),
        COMPARISON_REASON_LABELS,
        data_dir / "comparison_feasibility.csv",
        tables_dir / "comparison_feasibility.tex",
    )
    return by_key


def prepare_single_day_comparison(
    summary: dict,
    data_dir: Path,
    tables_dir: Path,
) -> dict[tuple[str, int], dict]:
    """Single-day replay table; our own source is included when present."""
    by_key, sources = comparison_grid(
        summary,
        "single_day",
        revised_required=False,
        name="single-day comparison feasibility summary",
    )
    write_comparison_outputs(
        by_key,
        sources,
        ("periodic_switch_counts", "single_day_switch_on_counts"),
        SINGLE_DAY_REASON_LABELS,
        data_dir / "comparison_feasibility_single_day.csv",
        tables_dir / "comparison_feasibility_single_day.tex",
    )
    return by_key


def annotate_comparison_solutions(
    data_dir: Path,
    validation: dict[tuple[str, int], dict],
) -> None:
    for (source, actuations), record in validation.items():
        path = data_dir / f"run_{source}_a_{actuations:02d}.json"
        payload = load_json(path)
        if not close(payload["best_cost"], record["published_cost"]):
            raise PreparationError(
                f"comparison cost differs from validation: {source} NA_max={actuations}"
            )
        payload["revised_validation"] = {
            "feasible": record["feasible"],
            "prune_reason": record["prune_reason"],
            "hour_failed": record["hour_failed"],
            "reevaluated_cost": record["reevaluated_cost"],
            "periodic_switch_counts": record["periodic_switch_counts"],
            "schedule_mode": "binary",
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def prepare_package(
    ablation_path: Path,
    scalability_path: Path,
    final_cases_path: Path,
    comparison_validation_path: Path,
    accuracy_audit_path: Path,
    accuracy_fixed_path: Path,
    accuracy_optimization_path: Path,
    comparison_data_dir: Path,
    output_dir: Path,
    single_day_comparison_path: Path | None = None,
    single_day_final_cases_path: Path | None = None,
) -> dict:
    input_paths = [
        ablation_path,
        scalability_path,
        final_cases_path,
        comparison_validation_path,
        accuracy_audit_path,
        accuracy_fixed_path,
        accuracy_optimization_path,
    ]
    ablation = load_json(ablation_path)
    scalability = load_json(scalability_path)
    final_cases = load_json(final_cases_path)
    comparison_validation = load_json(comparison_validation_path)
    accuracy_audit = load_json(accuracy_audit_path)
    validate_summaries(ablation, scalability, final_cases)
    single_day_final_cases = None
    if single_day_final_cases_path is not None:
        single_day_final_cases = load_json(single_day_final_cases_path)
        validate_single_day_final_cases(final_cases, single_day_final_cases)
        input_paths.append(single_day_final_cases_path)
    if comparison_validation.get("final_summary_sha256") != sha256(final_cases_path):
        raise PreparationError(
            "comparison replay used a different final-cases summary"
        )

    data_dir = output_dir / "data"
    tables_dir = output_dir / "tables"
    data_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    prepare_ablation(ablation, data_dir, tables_dir)
    prepare_scalability(scalability, data_dir, tables_dir)
    prepare_final_cases(final_cases, data_dir, tables_dir, single_day_final_cases)
    prepare_accuracy(
        accuracy_audit,
        accuracy_audit_path,
        accuracy_fixed_path,
        accuracy_optimization_path,
        final_cases,
        data_dir,
        tables_dir,
    )
    validation = prepare_comparison_validation(
        comparison_validation, data_dir, tables_dir
    )

    for source in EXTERNAL_SOURCES:
        for actuations in (1, 2, 3):
            source_path = comparison_data_dir / f"run_{source}_a_{actuations:02d}.json"
            validate_external_solution(source_path)
            replay_record = validation[(source, actuations)]
            if replay_record.get("source_artifact_sha256") != sha256(source_path):
                raise PreparationError(
                    f"comparison replay used a different source artifact: "
                    f"{source} NA_max={actuations}"
                )
            input_paths.append(source_path)
            shutil.copyfile(source_path, data_dir / source_path.name)
    annotate_comparison_solutions(data_dir, validation)

    if single_day_comparison_path is not None:
        single_day_summary = load_json(single_day_comparison_path)
        if single_day_summary.get("network_sha256") != comparison_validation.get(
            "network_sha256"
        ):
            raise PreparationError(
                "periodic and single-day comparison replays used different networks"
            )
        single_day = prepare_single_day_comparison(
            single_day_summary, data_dir, tables_dir
        )
        for source in EXTERNAL_SOURCES:
            for actuations in (1, 2, 3):
                source_path = (
                    comparison_data_dir / f"run_{source}_a_{actuations:02d}.json"
                )
                if single_day[(source, actuations)].get(
                    "source_artifact_sha256"
                ) != sha256(source_path):
                    raise PreparationError(
                        "single-day comparison replay used a different source "
                        f"artifact: {source} NA_max={actuations}"
                    )
        if single_day_final_cases is not None and ("Souza2026", 1) in single_day:
            if single_day_summary.get("final_summary_sha256") != sha256(
                single_day_final_cases_path
            ):
                raise PreparationError(
                    "single-day comparison replay used a different final-cases summary"
                )
            for case in single_day_final_cases["cases"]:
                record = single_day[("Souza2026", case["actuations"])]
                if not close(record["published_cost"], case["global_best_cost"]):
                    raise PreparationError(
                        "single-day comparison cost differs from the final cases: "
                        f"NA_max={case['actuations']}"
                    )
        input_paths.append(single_day_comparison_path)

    output_paths = sorted(
        path
        for directory in (data_dir, tables_dir)
        for path in directory.rglob("*")
        if path.is_file()
    )
    receipt = {
        "schema_version": 1,
        "inputs": {
            (
                path.resolve().relative_to(ROOT.resolve()).as_posix()
                if path.resolve().is_relative_to(ROOT.resolve())
                else path.name
            ): sha256(path)
            for path in sorted(input_paths)
        },
        "outputs": {
            str(path.relative_to(output_dir)): sha256(path) for path in output_paths
        },
        "executable_sha256": final_cases["executable_sha256"],
        "manuscript_modified": False,
    }
    (output_dir / "artifact-manifest.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ablation-summary",
        type=Path,
        default=DEFAULT_RESULTS / "ablation-anytown-24h-a3-summary.json",
    )
    parser.add_argument(
        "--scalability-summary",
        type=Path,
        default=DEFAULT_RESULTS / "scalability-anytown-24h-a2-summary.json",
    )
    parser.add_argument(
        "--final-cases-summary",
        type=Path,
        default=DEFAULT_RESULTS / "final-cases-anytown-24h-summary.json",
    )
    parser.add_argument(
        "--single-day-final-cases",
        type=Path,
        help=(
            "optional final-cases summary searched under the single-day switch "
            "count; adds its columns to the final-cases and pruning tables"
        ),
    )
    parser.add_argument(
        "--comparison-validation",
        type=Path,
        default=DEFAULT_RESULTS / "comparison-feasibility-summary.json",
    )
    parser.add_argument(
        "--single-day-comparison-validation",
        type=Path,
        help=(
            "optional comparison summary replayed under the single-day switch "
            "count; adds the single-day comparison table"
        ),
    )
    parser.add_argument(
        "--accuracy-audit",
        type=Path,
        default=DEFAULT_RESULTS / "accuracy-sensitivity-anytown-24h-audit.json",
    )
    parser.add_argument(
        "--accuracy-fixed",
        type=Path,
        default=DEFAULT_RESULTS / "accuracy-sensitivity-anytown-24h-fixed.csv",
    )
    parser.add_argument(
        "--accuracy-optimization",
        type=Path,
        default=DEFAULT_RESULTS / "accuracy-sensitivity-anytown-24h-optimization.csv",
    )
    parser.add_argument(
        "--comparison-data-dir", type=Path, default=DEFAULT_COMPARISON_DATA
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        receipt = prepare_package(
            arguments.ablation_summary.absolute(),
            arguments.scalability_summary.absolute(),
            arguments.final_cases_summary.absolute(),
            arguments.comparison_validation.absolute(),
            arguments.accuracy_audit.absolute(),
            arguments.accuracy_fixed.absolute(),
            arguments.accuracy_optimization.absolute(),
            arguments.comparison_data_dir.absolute(),
            arguments.output_dir.absolute(),
            (
                arguments.single_day_comparison_validation.absolute()
                if arguments.single_day_comparison_validation is not None
                else None
            ),
            (
                arguments.single_day_final_cases.absolute()
                if arguments.single_day_final_cases is not None
                else None
            ),
        )
    except (PreparationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"manuscript artifact preparation failed: {exc}")
        return 1
    print(
        f"prepared {len(receipt['outputs'])} auditable data and table artifacts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
