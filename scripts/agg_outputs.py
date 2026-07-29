#!/usr/bin/env python3
"""
Aggregate BB solver output JSON files (best + stats) into a single summary.
"""

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import mean

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)
from rich.text import Text
from rich import box

console = Console()


RUN_RE = re.compile(
    r"^run_a_(\d+)_h_(\d+)_l_(\d+)_s_(\d+)_n_(\d+)_r_(\d+)_(best|stats)\.json$"
)
PRUNE_KEYS = (
    "NONE",
    "PRESSURES",
    "LEVELS",
    "TANK_SATURATION",
    "STABILITY",
    "COST",
    "ACTUATIONS",
    "TIMESTEP",
)
# Groups raw, mutually exclusive solver reasons under manuscript table labels.
# LEVELS is the legacy hydraulic bound check; TANK_SATURATION records the
# revised physical intervention at a tank limit. Preserve both raw series and
# combine them only in the editorial table.
PRUNING_TABLE_GROUPS = {
    "Actuation": ("ACTUATIONS",),
    "Cost bound": ("COST",),
    "Tank levels": ("LEVELS", "TANK_SATURATION"),
    "Pressure": ("PRESSURES",),
}
# Order for the pruning table (matches article Table 4)
PRUNING_TABLE_ORDER = ["Actuation", "Cost bound", "Tank levels", "Pressure"]


def parse_run_filename(path: Path):
    match = RUN_RE.match(path.name)
    if not match:
        return None
    a, h, l, s, n, r, kind = match.groups()
    return {
        "a": int(a),
        "h": int(h),
        "l": int(l),
        "s": int(s),
        "n": int(n),
        "r": int(r),
        "kind": kind,
    }


def relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def compute_duration_imbalance_factor(stats_by_rank):
    durations = []
    for stats in stats_by_rank.values():
        duration = stats.get("duration")
        if isinstance(duration, (int, float)):
            durations.append(float(duration))

    if not durations:
        return None

    avg_duration = mean(durations)
    if avg_duration <= 0:
        return 0.0

    return (max(durations) - avg_duration) / avg_duration


def select_primary_stats(run_entry, data, rank, path, base_dir):
    stats_rank = run_entry.get("stats_rank")
    if run_entry.get("stats") is None:
        run_entry["stats"] = data
        run_entry["stats_rank"] = rank
        run_entry["stats_file"] = relpath(path, base_dir)
        return
    if stats_rank != 0 and rank == 0:
        run_entry["stats"] = data
        run_entry["stats_rank"] = rank
        run_entry["stats_file"] = relpath(path, base_dir)


def aggregate_outputs(outputs_dir: Path, base_dir: Path, progress_callback=None):
    runs = {}
    warnings = []

    json_files = sorted(outputs_dir.glob("*.json"))
    total_files = len(json_files)

    for idx, path in enumerate(json_files):
        if progress_callback:
            progress_callback(idx, total_files, path.name)
        info = parse_run_filename(path)
        if not info:
            continue

        key = (info["a"], info["h"], info["l"], info["s"], info["n"])
        run_entry = runs.setdefault(
            key,
            {
                "best_by_rank": {},
                "best_files": {},
                "stats_by_rank": {},
                "stats_files": {},
                "stats": None,
                "stats_rank": None,
                "stats_file": None,
            },
        )

        try:
            data = load_json(path)
        except json.JSONDecodeError as exc:
            warnings.append(f"Failed to parse {relpath(path, base_dir)}: {exc}")
            continue

        if info["kind"] == "best":
            run_entry["best_by_rank"][info["r"]] = data
            run_entry["best_files"][info["r"]] = relpath(path, base_dir)
        else:
            rank = info["r"]
            if rank in run_entry["stats_by_rank"]:
                warnings.append(
                    f"Overwriting stats for rank {rank} in {relpath(path, base_dir)}."
                )
            run_entry["stats_by_rank"][rank] = data
            run_entry["stats_files"][rank] = relpath(path, base_dir)
            select_primary_stats(run_entry, data, rank, path, base_dir)

    aggregated = []
    for key in sorted(runs.keys()):
        a, h, l, s, n = key
        run_entry = runs[key]
        best_by_rank = run_entry["best_by_rank"]

        best_costs = {}
        for rank, data in best_by_rank.items():
            cost = data.get("best_cost")
            if isinstance(cost, (int, float)):
                best_costs[rank] = float(cost)

        best_rank = None
        best_cost_stats = None
        best_payload = None
        if best_costs:
            best_rank = min(best_costs, key=best_costs.get)
            costs = list(best_costs.values())
            best_cost_stats = {
                "min": min(costs),
                "max": max(costs),
                "mean": mean(costs),
                "spread": max(costs) - min(costs),
            }
            best_payload = {
                "rank": best_rank,
                "cost": best_costs[best_rank],
                "x": best_by_rank[best_rank].get("best_x"),
                "y": best_by_rank[best_rank].get("best_y"),
            }

        missing_best_ranks = []
        if n > 0:
            seen = set(best_by_rank.keys())
            missing_best_ranks = sorted(r for r in range(n) if r not in seen)

        run_key = f"run_a_{a:02d}_h_{h:02d}_l_{l:02d}_s_{s:02d}_n_{n:02d}"

        prune_counts = {}
        stats_by_rank = run_entry["stats_by_rank"]

        # Calculate max duration across all ranks
        max_duration = 0.0
        has_duration = False
        for stats in stats_by_rank.values():
            d = stats.get("duration")
            if isinstance(d, (int, float)):
                max_duration = max(max_duration, float(d))
                has_duration = True

        imbalance_factor = compute_duration_imbalance_factor(stats_by_rank)
        if imbalance_factor is not None:
            if run_entry.get("stats") is None:
                run_entry["stats"] = {}
            run_entry["stats"]["load_imbalance_factor"] = imbalance_factor

        if has_duration:
            if run_entry.get("stats") is None:
                run_entry["stats"] = {}
            run_entry["stats"]["duration"] = max_duration

        for reason in PRUNE_KEYS:
            totals = None
            for rank, stats in stats_by_rank.items():
                counts = stats.get(reason)
                if counts is None:
                    continue
                if not isinstance(counts, list):
                    warnings.append(
                        f"{run_key}: stats {reason} in rank {rank} is not a list."
                    )
                    continue
                if totals is None:
                    totals = [0] * len(counts)
                if len(counts) != len(totals):
                    warnings.append(
                        f"{run_key}: stats {reason} length mismatch in rank {rank}."
                    )
                    min_len = min(len(counts), len(totals))
                    totals = totals[:min_len]
                    counts = counts[:min_len]
                for idx, value in enumerate(counts):
                    try:
                        totals[idx] += int(value)
                    except (TypeError, ValueError):
                        warnings.append(
                            f"{run_key}: stats {reason} has non-integer at hour {idx}."
                        )
                        break
            if totals is not None:
                prune_counts[reason] = totals
        aggregated.append(
            {
                "run_key": run_key,
                "config": {"a": a, "h": h, "l": l, "s": s, "n": n},
                "best": best_payload,
                "best_costs_by_rank": {
                    str(rank): cost for rank, cost in sorted(best_costs.items())
                },
                "best_cost_stats": best_cost_stats,
                "missing_best_ranks": missing_best_ranks,
                "prune_counts_by_type_hour": prune_counts,
                "stats": run_entry["stats"],
                "stats_rank": run_entry["stats_rank"],
                "files": {
                    "best_by_rank": {
                        str(rank): path
                        for rank, path in sorted(run_entry["best_files"].items())
                    },
                    "stats": run_entry["stats_file"],
                    "stats_by_rank": {
                        str(rank): path
                        for rank, path in sorted(run_entry["stats_files"].items())
                    },
                },
            }
        )

    return {
        "source_dir": relpath(outputs_dir, base_dir),
        "runs": aggregated,
        "warnings": warnings,
    }


def format_node_count(count: int) -> str:
    """Format node count with M/B suffixes."""
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B"
    elif count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    else:
        return str(count)


def export_pruning_csv(aggregated: dict, out_path: Path, quiet: bool = False):
    """Export pruning statistics to CSV for the pruning table (Table 4 in article)."""
    runs = aggregated.get("runs", [])

    # Group runs by actuation limit
    runs_by_a = {}
    for run in runs:
        config = run.get("config", {})
        a = config.get("a")
        if a is not None:
            runs_by_a.setdefault(a, []).append(run)

    # Process each actuation limit
    a_values = sorted(runs_by_a.keys())

    # Initialize data structures for raw counts
    raw_counts = {key: {a: 0 for a in a_values} for key in PRUNE_KEYS}

    # Aggregate data across all runs for each actuation limit
    for a in a_values:
        runs_for_a = runs_by_a[a]
        for run in runs_for_a:
            prune_counts = run.get("prune_counts_by_type_hour", {})

            # Sum counts across all hours for each prune key
            for key in PRUNE_KEYS:
                counts = prune_counts.get(key, [])
                if isinstance(counts, list):
                    raw_counts[key][a] += sum(counts)

    # Total nodes = NONE counts (nodes that were not pruned = feasible nodes explored)
    # But we need total nodes explored = sum of all categories
    node_totals = {a: 0 for a in a_values}
    for a in a_values:
        for key in PRUNE_KEYS:
            node_totals[a] += raw_counts[key][a]

    # Calculate percentages for each editorial group. Raw reasons remain
    # separate in the aggregate JSON for traceability.
    percentages = {label: {a: 0.0 for a in a_values} for label in PRUNING_TABLE_ORDER}
    for label, internal_keys in PRUNING_TABLE_GROUPS.items():
        for a in a_values:
            total = node_totals[a]
            if total > 0:
                grouped_count = sum(raw_counts[key][a] for key in internal_keys)
                pct = (grouped_count / total) * 100
                percentages[label][a] = round(pct, 1)

    # Calculate the total from raw counts so minor reasons remain represented
    # and independently rounded table rows cannot introduce drift.
    total_pruned = {a: 0.0 for a in a_values}
    for a in a_values:
        total = node_totals[a]
        if total > 0:
            pruned_count = total - raw_counts["NONE"][a]
            total_pruned[a] = round((pruned_count / total) * 100, 1)

    # Calculate feasible percentage (NONE / total * 100)
    feasible = {a: 0.0 for a in a_values}
    for a in a_values:
        total = node_totals[a]
        if total > 0:
            feasible[a] = round((raw_counts["NONE"][a] / total) * 100, 1)

    # Write CSV matching Table 4 format
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)

        # Header: Criterion, then one column per actuation limit
        writer.writerow(["Criterion"] + [str(a) for a in a_values])

        # Write each pruning criterion row
        for label in PRUNING_TABLE_ORDER:
            row = [label] + [percentages[label][a] for a in a_values]
            writer.writerow(row)

        # Write Total pruned row
        writer.writerow(["Total pruned"] + [total_pruned[a] for a in a_values])

        # Write Feasible row
        writer.writerow(["Feasible"] + [feasible[a] for a in a_values])

        # Write Nodes (total) row with formatted counts
        writer.writerow(["Nodes (total)"] + [format_node_count(node_totals[a]) for a in a_values])

    if quiet:
        print(f"Wrote pruning CSV to {out_path}")
    else:
        console.print(
            f"[green]Wrote pruning CSV to [cyan]{out_path}[/cyan][/green]"
        )

    # Display the CSV contents as a table
    if not quiet:
        prune_table = Table(
            title="Pruning Statistics (% of nodes)",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        prune_table.add_column("Criterion", style="bold white")
        for a in a_values:
            prune_table.add_column(f"NA_max={a}", justify="right", style="yellow")

        for label in PRUNING_TABLE_ORDER:
            prune_table.add_row(label, *[str(percentages[label][a]) for a in a_values])

        prune_table.add_row(
            "[bold]Total pruned[/bold]",
            *[f"[bold]{total_pruned[a]}[/bold]" for a in a_values],
            style="on grey23",
        )
        prune_table.add_row(
            "Feasible",
            *[str(feasible[a]) for a in a_values],
        )
        prune_table.add_row(
            "[dim]Nodes (total)[/dim]",
            *[f"[dim]{format_node_count(node_totals[a])}[/dim]" for a in a_values],
        )

        console.print()
        console.print(prune_table)


def display_results(aggregated: dict, out_path: Path):
    """Display aggregated results using rich tables."""
    runs = aggregated.get("runs", [])
    warnings = aggregated.get("warnings", [])

    if not runs:
        console.print("[yellow]No runs found in the output directory.[/yellow]")
        return

    # Summary table
    table = Table(
        title="BB Solver Run Summary",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Run Key", style="bold white", no_wrap=True)
    table.add_column("Config", style="dim")
    table.add_column("Best Cost", justify="right", style="green")
    table.add_column("Best Rank", justify="center")
    table.add_column("Cost Range", justify="right", style="yellow")
    table.add_column("Duration", justify="right", style="magenta")
    table.add_column("Imbalance", justify="right", style="cyan")

    for run in runs:
        run_key = run.get("run_key", "N/A")
        config = run.get("config", {})
        config_str = f"a={config.get('a')} h={config.get('h')} l={config.get('l')} n={config.get('n')}"

        best = run.get("best") or {}
        best_cost = best.get("cost")
        best_rank = best.get("rank")

        stats = run.get("best_cost_stats") or {}
        cost_min = stats.get("min")
        cost_max = stats.get("max")
        spread = stats.get("spread")

        run_stats = run.get("stats") or {}
        duration = run_stats.get("duration")
        imbalance_factor = run_stats.get("load_imbalance_factor")

        cost_str = f"{best_cost:,.2f}" if best_cost is not None else "-"
        rank_str = str(best_rank) if best_rank is not None else "-"
        range_str = (
            f"{cost_min:,.2f} - {cost_max:,.2f}" if cost_min and cost_max else "-"
        )
        if spread is not None:
            range_str += f" ({spread:,.2f})"
        duration_str = f"{duration:.2f}s" if duration is not None else "-"
        imbalance_str = (
            f"{imbalance_factor * 100:.1f}%" if imbalance_factor is not None else "-"
        )

        table.add_row(
            run_key, config_str, cost_str, rank_str, range_str, duration_str, imbalance_str
        )

    console.print()
    console.print(table)

    # Pruning statistics table by hour (if available)
    if runs and runs[0].get("prune_counts_by_type_hour"):
        for run in runs:  # Show for all runs
            prune_counts = run.get("prune_counts_by_type_hour", {})

            # Filter to prune types that have non-zero values
            active_types = [
                ptype
                for ptype, counts in prune_counts.items()
                if isinstance(counts, list) and sum(counts) > 0
            ]

            if not active_types:
                continue

            prune_table = Table(
                title=f"Pruning Statistics by Hour ({run.get('run_key', 'N/A')})",
                box=box.SIMPLE,
                header_style="bold blue",
            )
            prune_table.add_column("Hour", style="bold", justify="right")
            for ptype in active_types:
                prune_table.add_column(ptype, justify="right", style="cyan")
            prune_table.add_column("Total", justify="right", style="bold green")

            # Determine number of hours from first active type
            num_hours = len(prune_counts[active_types[0]])

            # Add rows for each hour
            col_totals = {ptype: 0 for ptype in active_types}
            for hour in range(num_hours):
                row_values = []
                row_total = 0
                for ptype in active_types:
                    counts = prune_counts.get(ptype, [])
                    val = counts[hour] if hour < len(counts) else 0
                    row_values.append(f"{val:,}" if val > 0 else "-")
                    row_total += val
                    col_totals[ptype] += val
                row_values.append(f"{row_total:,}" if row_total > 0 else "-")
                prune_table.add_row(str(hour), *row_values)

            # Add totals row
            total_values = [f"{col_totals[ptype]:,}" for ptype in active_types]
            grand_total = sum(col_totals.values())
            total_values.append(f"{grand_total:,}")
            prune_table.add_row(
                "[bold]Total[/bold]",
                *[f"[bold]{v}[/bold]" for v in total_values],
                style="on grey23",
            )

            console.print()
            console.print(prune_table)

    # Warnings panel
    if warnings:
        warning_text = Text()
        for w in warnings[:10]:  # Limit to first 10
            warning_text.append(f"  {w}\n", style="yellow")
        if len(warnings) > 10:
            warning_text.append(f"  ... and {len(warnings) - 10} more\n", style="dim")
        console.print()
        console.print(
            Panel(
                warning_text,
                title=f"[bold yellow]Warnings ({len(warnings)})",
                border_style="yellow",
            )
        )

    # Output summary
    console.print()
    console.print(
        Panel(
            f"[green]Wrote [bold]{len(runs)}[/bold] run summaries to [cyan]{out_path}[/cyan][/green]",
            title="Output",
            border_style="green",
        )
    )


def main():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    default_outputs = project_root / "article/data/outputs"
    default_outfile = default_outputs / "agg_outputs.json"
    default_pruning_csv = project_root / "article/data/pruning.csv"

    parser = argparse.ArgumentParser(
        description="Aggregate BB solver output JSON files into a summary."
    )
    parser.add_argument(
        "--outputs-dir",
        default=str(default_outputs),
        help="Directory containing BB solver output JSON files.",
    )
    parser.add_argument(
        "--out",
        default=str(default_outfile),
        help="Output JSON path for the aggregated summary.",
    )
    parser.add_argument(
        "--pruning-csv",
        default=str(default_pruning_csv),
        help="Output CSV path for pruning table.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress rich output, only show minimal info.",
    )
    args = parser.parse_args()

    outputs_dir = Path(args.outputs_dir)
    if not outputs_dir.exists():
        console.print(
            f"[bold red]Error:[/bold red] Outputs directory does not exist: {outputs_dir}"
        )
        raise SystemExit(1)

    out_path = Path(args.out)
    pruning_csv_path = Path(args.pruning_csv)

    # Header
    if not args.quiet:
        console.print()
        console.print(
            Panel(
                "[bold]BB Solver Output Aggregator[/bold]\n"
                f"Source: [cyan]{outputs_dir}[/cyan]",
                border_style="blue",
            )
        )

    # Process with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        disable=args.quiet,
    ) as progress:
        task = progress.add_task("[cyan]Processing JSON files...", total=None)

        def update_progress(idx, total, filename):
            if progress.tasks[task].total is None:
                progress.update(task, total=total)
            progress.update(
                task,
                completed=idx + 1,
                description=f"[cyan]Processing: {filename[:40]}...",
            )

        aggregated = aggregate_outputs(
            outputs_dir, project_root, progress_callback=update_progress
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(aggregated, indent=2), encoding="utf-8")

    if args.quiet:
        print(f"Wrote {len(aggregated['runs'])} run summaries to {out_path}")
        if aggregated["warnings"]:
            print(f"Warnings: {len(aggregated['warnings'])} (see output JSON)")
    else:
        display_results(aggregated, out_path)

    # Export pruning CSV if path is provided
    if pruning_csv_path:
        export_pruning_csv(aggregated, pruning_csv_path, quiet=args.quiet)


if __name__ == "__main__":
    main()
