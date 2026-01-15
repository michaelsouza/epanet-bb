#!/usr/bin/env python3
"""Validate pump schedule feasibility using WNTR hydraulic simulations.

This script checks whether a given pump schedule satisfies all hydraulic constraints:
- Pressure thresholds at critical nodes (55, 90, 170)
- Tank level bounds at tanks (65, 165, 265)
- Tank stability constraint (final level >= initial level)
"""

import json
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import ListedColormap
import wntr
import wntr
from pathlib import Path

# Rich imports
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.status import Status
from rich import print as rprint
from rich.traceback import install

install(show_locals=True)

console = Console()

# Get the project root directory
script_dir = Path(__file__).parent
project_root = script_dir.parent

# Network constants (AnyTown)
PUMP_ORDER = ["111", "222", "333"]
NUM_PUMPS = len(PUMP_ORDER)
HOURS = 24

# Tank constraints
TANK_IDS = ["65", "165", "265"]
LEVEL_MIN = 66.53
LEVEL_MAX = 71.53
LEVEL_INIT = 66.93

# Pressure constraints
PRESSURE_NODE_IDS = ["55", "90", "170"]
PRESSURE_THRESHOLDS = {"55": 42.0, "90": 51.0, "170": 30.0}


def extract_pump_schedules(best_x: list) -> dict:
    """Extract per-pump schedules from best_x vector."""
    schedules = {pump: [] for pump in PUMP_ORDER}
    for hour in range(1, HOURS + 1):
        base_idx = hour * NUM_PUMPS
        for i, pump in enumerate(PUMP_ORDER):
            if base_idx + i < len(best_x):
                schedules[pump].append(best_x[base_idx + i])
            else:
                schedules[pump].append(0)
    return schedules


def run_simulation(inp_path: str, schedules: dict) -> tuple:
    """Run WNTR simulation and extract tank levels and node pressures at 30-min intervals."""
    wn = wntr.network.WaterNetworkModel(inp_path)

    # Update pump patterns
    for pump_id, schedule in schedules.items():
        pattern_name = f"PMP{pump_id}"
        if pattern_name in wn.pattern_name_list:
            pattern = wn.get_pattern(pattern_name)
            pattern.multipliers = schedule
        else:
            wn.add_pattern(pattern_name, schedule)

    with console.status("[bold green]Running hydraulic simulation...", spinner="dots"):
        sim = wntr.sim.EpanetSimulator(wn)
        results = sim.run_sim()

    # Extract results at 30-minute intervals (0, 1800, 3600, ..., 86400 seconds)
    # 49 timesteps for 24 hours at 30-min intervals
    times_30min = [t * 1800 for t in range(49)]
    times_hours = [t / 3600.0 for t in times_30min]

    tank_levels = {}
    node_pressures = {}

    for tank_id in TANK_IDS:
        tank_levels[tank_id] = []
        for t in times_30min:
            if t in results.node["head"].index:
                tank_levels[tank_id].append(results.node["head"].loc[t, tank_id])
            else:
                # Interpolate if exact time not available
                available_times = results.node["head"].index.values
                idx = np.searchsorted(available_times, t)
                if idx == 0:
                    tank_levels[tank_id].append(results.node["head"].iloc[0][tank_id])
                elif idx >= len(available_times):
                    tank_levels[tank_id].append(results.node["head"].iloc[-1][tank_id])
                else:
                    # Linear interpolation
                    t0, t1 = available_times[idx - 1], available_times[idx]
                    v0 = results.node["head"].loc[t0, tank_id]
                    v1 = results.node["head"].loc[t1, tank_id]
                    frac = (t - t0) / (t1 - t0)
                    tank_levels[tank_id].append(v0 + frac * (v1 - v0))

    for node_id in PRESSURE_NODE_IDS:
        node_pressures[node_id] = []
        for t in times_30min:
            if t in results.node["pressure"].index:
                node_pressures[node_id].append(results.node["pressure"].loc[t, node_id])
            else:
                # Interpolate if exact time not available
                available_times = results.node["pressure"].index.values
                idx = np.searchsorted(available_times, t)
                if idx == 0:
                    node_pressures[node_id].append(
                        results.node["pressure"].iloc[0][node_id]
                    )
                elif idx >= len(available_times):
                    node_pressures[node_id].append(
                        results.node["pressure"].iloc[-1][node_id]
                    )
                else:
                    # Linear interpolation
                    t0, t1 = available_times[idx - 1], available_times[idx]
                    v0 = results.node["pressure"].loc[t0, node_id]
                    v1 = results.node["pressure"].loc[t1, node_id]
                    frac = (t - t0) / (t1 - t0)
                    node_pressures[node_id].append(v0 + frac * (v1 - v0))

    return tank_levels, node_pressures, times_hours


def validate_constraints(
    tank_levels: dict, node_pressures: dict, times_hours: list
) -> tuple:
    """Validate all constraints and return violations and statistics."""
    violations = []
    stats = {
        "tanks": {},
        "nodes": {},
    }

    # Check tank level constraints
    for tank_id in TANK_IDS:
        levels = tank_levels[tank_id]
        stats["tanks"][tank_id] = {
            "min": min(levels),
            "max": max(levels),
            "final": levels[-1],
        }

        for i, (t, level) in enumerate(zip(times_hours, levels)):
            if level < LEVEL_MIN:
                violations.append(
                    {
                        "type": "level_low",
                        "location": tank_id,
                        "time_hours": t,
                        "value": level,
                        "limit": LEVEL_MIN,
                    }
                )
            if level > LEVEL_MAX:
                violations.append(
                    {
                        "type": "level_high",
                        "location": tank_id,
                        "time_hours": t,
                        "value": level,
                        "limit": LEVEL_MAX,
                    }
                )

        # Stability constraint: final level >= initial level
        if levels[-1] < LEVEL_INIT:
            violations.append(
                {
                    "type": "stability",
                    "location": tank_id,
                    "time_hours": 24.0,
                    "value": levels[-1],
                    "limit": LEVEL_INIT,
                }
            )

    # Check pressure constraints
    for node_id in PRESSURE_NODE_IDS:
        pressures = node_pressures[node_id]
        threshold = PRESSURE_THRESHOLDS[node_id]
        stats["nodes"][node_id] = {
            "min": min(pressures),
            "max": max(pressures),
            "threshold": threshold,
        }

        for i, (t, pressure) in enumerate(zip(times_hours, pressures)):
            if pressure < threshold:
                violations.append(
                    {
                        "type": "pressure",
                        "location": node_id,
                        "time_hours": t,
                        "value": pressure,
                        "limit": threshold,
                    }
                )

    return violations, stats


def generate_report(
    solution_path: str, inp_path: str, violations: list, stats: dict
) -> str:
    """Generate a validation report string."""
    lines = []
    lines.append("=" * 60)
    lines.append("PUMP SCHEDULE FEASIBILITY REPORT")
    lines.append("=" * 60)
    lines.append(f"Solution: {solution_path}")
    lines.append(f"Network:  {inp_path}")
    lines.append("")

    # Constraint check summary
    lines.append("=" * 60)
    lines.append("CONSTRAINT CHECK")
    lines.append("=" * 60)

    pressure_violations = [v for v in violations if v["type"] == "pressure"]
    level_violations = [
        v for v in violations if v["type"] in ("level_low", "level_high")
    ]
    stability_violations = [v for v in violations if v["type"] == "stability"]

    if pressure_violations:
        lines.append(f"Pressures:   FAIL ({len(pressure_violations)} violations)")
    else:
        lines.append("Pressures:   OK (all nodes above minimum thresholds)")

    if level_violations:
        lines.append(f"Tank Levels: FAIL ({len(level_violations)} violations)")
    else:
        lines.append("Tank Levels: OK (all within [66.53, 71.53] m)")

    if stability_violations:
        lines.append(f"Stability:   FAIL ({len(stability_violations)} violations)")
    else:
        lines.append("Stability:   OK (final levels >= 66.93 m)")

    lines.append("")

    # Violations detail
    if violations:
        lines.append("=" * 60)
        lines.append("VIOLATIONS")
        lines.append("=" * 60)
        for v in violations:
            if v["type"] == "pressure":
                lines.append(
                    f"  Node {v['location']} at t={v['time_hours']:.1f}h: "
                    f"pressure={v['value']:.2f}m < threshold={v['limit']}m"
                )
            elif v["type"] == "level_low":
                lines.append(
                    f"  Tank {v['location']} at t={v['time_hours']:.1f}h: "
                    f"level={v['value']:.2f}m < min={v['limit']}m"
                )
            elif v["type"] == "level_high":
                lines.append(
                    f"  Tank {v['location']} at t={v['time_hours']:.1f}h: "
                    f"level={v['value']:.2f}m > max={v['limit']}m"
                )
            elif v["type"] == "stability":
                lines.append(
                    f"  Tank {v['location']} at t=24h: "
                    f"final_level={v['value']:.2f}m < initial={v['limit']}m"
                )
        lines.append("")

    # Summary statistics
    lines.append("=" * 60)
    lines.append("SUMMARY")
    lines.append("=" * 60)
    for node_id in PRESSURE_NODE_IDS:
        s = stats["nodes"][node_id]
        lines.append(
            f"Node {node_id}:  min={s['min']:.2f}m, max={s['max']:.2f}m "
            f"(threshold: {s['threshold']}m)"
        )
    for tank_id in TANK_IDS:
        s = stats["tanks"][tank_id]
        lines.append(
            f"Tank {tank_id}:  min={s['min']:.2f}m, max={s['max']:.2f}m, "
            f"final={s['final']:.2f}m"
        )
    lines.append("")

    # Overall result
    lines.append("=" * 60)
    if violations:
        lines.append("RESULT: FAIL")
    else:
        lines.append("RESULT: PASS")
    lines.append("=" * 60)

    return "\n".join(lines)


def print_rich_report(
    solution_path: str, inp_path: str, violations: list, stats: dict
) -> None:
    """Print a validation report using Rich."""
    console.print()
    console.rule("[bold blue]PUMP SCHEDULE FEASIBILITY REPORT")

    # Info Panel
    grid = Table.grid(expand=True)
    grid.add_column(justify="right", style="cyan bold")
    grid.add_column(style="white")
    grid.add_row("Solution:", solution_path)
    grid.add_row("Network:", inp_path)
    console.print(Panel(grid, title="Input Details", border_style="blue"))
    console.print()

    # Constraint Check Summary
    console.rule("[bold blue]CONSTRAINT CHECK")

    pressure_violations = [v for v in violations if v["type"] == "pressure"]
    level_violations = [
        v for v in violations if v["type"] in ("level_low", "level_high")
    ]
    stability_violations = [v for v in violations if v["type"] == "stability"]

    summary_table = Table(show_header=True, header_style="bold magenta", expand=True)
    summary_table.add_column("Constraint", style="cyan", width=20)
    summary_table.add_column("Status", justify="center", width=10)
    summary_table.add_column("Details", style="italic")

    def get_status(count):
        return "[bold green]OK[/]" if count == 0 else f"[bold red]FAIL ({count})[/]"

    summary_table.add_row(
        "Pressures",
        get_status(len(pressure_violations)),
        (
            "All nodes above minimum thresholds"
            if not pressure_violations
            else f"{len(pressure_violations)} violations"
        ),
    )
    summary_table.add_row(
        "Tank Levels",
        get_status(len(level_violations)),
        (
            "All within [66.53, 71.53] m"
            if not level_violations
            else f"{len(level_violations)} violations"
        ),
    )
    summary_table.add_row(
        "Stability",
        get_status(len(stability_violations)),
        (
            "Final levels >= 66.93 m"
            if not stability_violations
            else f"{len(stability_violations)} violations"
        ),
    )
    console.print(summary_table)
    console.print()

    # Violations Detail
    if violations:
        console.rule("[bold red]VIOLATIONS")
        v_table = Table(
            show_header=True,
            header_style="bold red",
            expand=True,
            title="Detailed Violations",
        )
        v_table.add_column("Type", style="red")
        v_table.add_column("Location", justify="center")
        v_table.add_column("Time (h)", justify="right")
        v_table.add_column("Value", justify="right")
        v_table.add_column("Limit", justify="right")
        v_table.add_column("Message", style="yellow")

        for v in violations:
            msg = ""
            if v["type"] == "pressure":
                msg = "Pressure too low"
            elif v["type"] == "level_low":
                msg = "Level too low"
            elif v["type"] == "level_high":
                msg = "Level too high"
            elif v["type"] == "stability":
                msg = "Final level too low"

            v_table.add_row(
                v["type"],
                v["location"],
                f"{v['time_hours']:.1f}",
                f"{v['value']:.2f}",
                f"{v['limit']:.2f}",
                msg,
            )
        console.print(v_table)
        console.print()

    # Statistics
    console.rule("[bold blue]SUMMARY STATISTICS")

    # Node Stats
    node_table = Table(
        title="Node Pressures (m)", show_header=True, header_style="bold blue"
    )
    node_table.add_column("Node ID", style="cyan")
    node_table.add_column("Min", justify="right")
    node_table.add_column("Max", justify="right")
    node_table.add_column("Threshold", justify="right")

    for node_id in PRESSURE_NODE_IDS:
        s = stats["nodes"][node_id]
        min_color = "red" if s["min"] < s["threshold"] else "green"
        node_table.add_row(
            node_id,
            f"[{min_color}]{s['min']:.2f}[/]",
            f"{s['max']:.2f}",
            f"{s['threshold']:.2f}",
        )

    # Tank Stats
    tank_table = Table(
        title="Tank Levels (m)", show_header=True, header_style="bold blue"
    )
    tank_table.add_column("Tank ID", style="cyan")
    tank_table.add_column("Min", justify="right")
    tank_table.add_column("Max", justify="right")
    tank_table.add_column("Final", justify="right")

    for tank_id in TANK_IDS:
        s = stats["tanks"][tank_id]
        min_color = "red" if s["min"] < LEVEL_MIN else "green"
        max_color = "red" if s["max"] > LEVEL_MAX else "green"
        final_color = "red" if s["final"] < LEVEL_INIT else "green"

        tank_table.add_row(
            tank_id,
            f"[{min_color}]{s['min']:.2f}[/]",
            f"[{max_color}]{s['max']:.2f}[/]",
            f"[{final_color}]{s['final']:.2f}[/]",
        )

    stats_grid = Table.grid(expand=True, padding=2)
    stats_grid.add_column()
    stats_grid.add_column()
    stats_grid.add_row(node_table, tank_table)
    console.print(stats_grid)
    console.print()

    # Overall Result
    if violations:
        console.print(
            Panel(
                "[bold red]RESULT: FAIL[/]\nSolution violates hydraulic constraints.",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]RESULT: PASS[/]\nSolution satisfies all hydraulic constraints.",
                border_style="green",
            )
        )
    console.print()


def generate_plots(
    tank_levels: dict,
    node_pressures: dict,
    times_hours: list,
    violations: list,
    output_path: str,
    schedules: dict,
):
    """Generate constraint validation plots."""
    fig = plt.figure(figsize=(15, 10), dpi=150)
    gs = gridspec.GridSpec(3, 3, height_ratios=[1, 1, 0.6])

    # Row 1: Tank levels
    for i, tank_id in enumerate(TANK_IDS):
        ax = fig.add_subplot(gs[0, i])
        levels = tank_levels[tank_id]
        ax.plot(times_hours, levels, color="tab:blue", linewidth=1.5, label="Level")

        # Constraint lines
        ax.axhline(
            y=LEVEL_MIN,
            color="red",
            linestyle="--",
            alpha=0.6,
            label="Level Limits" if i == 0 else "",
        )
        ax.axhline(y=LEVEL_MAX, color="red", linestyle="--", alpha=0.6)
        ax.axhline(
            y=LEVEL_INIT,
            color="gray",
            linestyle=":",
            alpha=0.6,
            label="Initial Level" if i == 0 else "",
        )

        # Mark violations
        tank_violations = [
            v
            for v in violations
            if v["location"] == tank_id
            and v["type"] in ("level_low", "level_high", "stability")
        ]
        if tank_violations:
            vt = [v["time_hours"] for v in tank_violations]
            vv = [v["value"] for v in tank_violations]
            ax.scatter(
                vt,
                vv,
                color="red",
                s=50,
                zorder=5,
                label="Violations" if i == 0 else "",
            )

        ax.set_title(f"Tank {tank_id}", fontsize=11, fontweight="bold")
        if i == 0:
            ax.set_ylabel("Level (m)")
        ax.set_xlabel("Hour")
        ax.grid(True, alpha=0.2)
        ax.set_xlim(0, 24)

    # Row 2: Node pressures
    for i, node_id in enumerate(PRESSURE_NODE_IDS):
        ax = fig.add_subplot(gs[1, i])
        pressures = node_pressures[node_id]
        ax.plot(
            times_hours, pressures, color="tab:blue", linewidth=1.5, label="Pressure"
        )

        # Constraint line
        threshold = PRESSURE_THRESHOLDS[node_id]
        ax.axhline(
            y=threshold,
            color="orange",
            linestyle="--",
            alpha=0.6,
            label="Min Pressure" if i == 0 else "",
        )

        # Mark violations
        node_violations = [
            v
            for v in violations
            if v["location"] == node_id and v["type"] == "pressure"
        ]
        if node_violations:
            vt = [v["time_hours"] for v in node_violations]
            vv = [v["value"] for v in node_violations]
            ax.scatter(
                vt,
                vv,
                color="red",
                s=50,
                zorder=5,
                label="Violations" if i == 0 else "",
            )

        ax.set_title(f"Node {node_id}", fontsize=11, fontweight="bold")
        if i == 0:
            ax.set_ylabel("Pressure (m)")
        ax.set_xlabel("Hour")
        ax.grid(True, alpha=0.2)
        ax.set_xlim(0, 24)

    # Row 3: Pump Schedule Table
    ax_table = fig.add_subplot(gs[2, :])

    # Prepare data matrix for pump schedules
    table_rows = []
    row_labels = []
    for pump_id in PUMP_ORDER:
        table_rows.append(schedules[pump_id])
        row_labels.append(f"Pump {pump_id}")

    data_matrix = np.array(table_rows)

    # Custom colormap: white for OFF, green for ON
    on_off_cmap = ListedColormap(["#f5f5f5", "#2ca02c"])

    im = ax_table.imshow(data_matrix, aspect="auto", cmap=on_off_cmap)

    # Add markers in green cells
    for r in range(data_matrix.shape[0]):
        for c in range(data_matrix.shape[1]):
            if data_matrix[r, c] == 1:
                ax_table.text(
                    c, r, "•", ha="center", va="center", color="white", fontsize=12
                )

    # Format table axis
    ax_table.set_xticks(np.arange(HOURS))
    ax_table.set_xticklabels([f"{h+1:02d}" for h in range(HOURS)])
    ax_table.set_yticks(np.arange(len(row_labels)))
    ax_table.set_yticklabels(row_labels, fontsize=10)

    # Add vertical lines to separate hours
    for x in range(HOURS + 1):
        ax_table.axvline(x - 0.5, color="gray", linewidth=0.5, alpha=0.3)

    ax_table.set_title(
        "Pump Operation Schedule (ON/OFF)", fontsize=11, fontweight="bold", pad=10
    )
    ax_table.set_xlabel("Hour")

    # Add legend
    handles, labels = [], []
    for ax in fig.axes:
        h, l = ax.get_legend_handles_labels()
        for handle, label in zip(h, l):
            if label not in labels:
                handles.append(handle)
                labels.append(label)

    fig.legend(
        handles,
        labels,
        loc="upper right",
        bbox_to_anchor=(0.98, 0.98),
        fontsize="small",
    )

    plt.tight_layout()
    plt.subplots_adjust(right=0.88)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Plot saved to: {output_path}")

    # Clean up temp files
    Path("temp.bin").unlink(missing_ok=True)
    Path("temp.inp").unlink(missing_ok=True)
    Path("temp.rpt").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Validate pump schedule feasibility using WNTR simulation."
    )
    parser.add_argument(
        "solution_json", help="Path to JSON file with pump schedule (best_x)."
    )
    parser.add_argument(
        "--inp", default="networks/any-town.inp", help="Path to EPANET .inp file."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file for validation report (default: <input>_check.rpt).",
    )
    parser.add_argument(
        "--plot",
        default=None,
        help="Output path for validation plot (default: <input>_check.png).",
    )
    args = parser.parse_args()

    # Auto-generate output paths based on input file
    input_path = Path(args.solution_json)
    base_path = input_path.with_suffix("")  # Remove .json extension

    if args.output is None:
        args.output = str(base_path) + "_check.rpt"
    if args.plot is None:
        args.plot = str(base_path) + "_check.png"

    # Load solution
    try:
        with open(args.solution_json, "r") as f:
            data = json.load(f)
    except Exception as e:
        console.print(f"[bold red]Error loading solution file:[/bold red] {e}")
        return 1

    best_x = data.get("best_x")
    if not best_x:
        console.print(
            "[bold red]Error: Solution file does not contain 'best_x' vector.[/bold red]"
        )
        return 1

    # Extract pump schedules
    schedules = extract_pump_schedules(best_x)

    # Run simulation
    console.print(f"Running simulation for [bold cyan]{args.solution_json}[/]...")
    try:
        tank_levels, node_pressures, times_hours = run_simulation(args.inp, schedules)
    except Exception as e:
        console.print(f"[bold red]Error during simulation:[/bold red] {e}")
        return 1

    # Validate constraints
    violations, stats = validate_constraints(tank_levels, node_pressures, times_hours)

    # Generate report
    report = generate_report(args.solution_json, args.inp, violations, stats)
    # print(report) # Replaced by rich output

    # Print rich report
    print_rich_report(args.solution_json, args.inp, violations, stats)

    # Save report
    with open(args.output, "w") as f:
        f.write(report)
    console.print(f"[dim]Report saved to: {args.output}[/dim]")

    # Generate plots
    Path(args.plot).parent.mkdir(parents=True, exist_ok=True)
    generate_plots(tank_levels, node_pressures, times_hours, violations, args.plot, schedules)

    return 0 if not violations else 1


if __name__ == "__main__":
    exit(main())
