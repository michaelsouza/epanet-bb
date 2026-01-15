#!/usr/bin/env python3
"""
Generate comprehensive plots for tank levels and node pressures across different actuation limits.

This script reads aggregated optimization results, simulates the network hydraulic behavior
using WNTR for the best solutions found (for NA_max = 1, 2, and 3), and generates a
comparative figure.

The output figure consists of:
- Top row: Water levels for tanks 65, 165, and 265 over 24 hours.
- Bottom row: Pressure heads for critical nodes 55, 90, and 170 over 24 hours.

Inputs:
- `article/data/outputs/agg_outputs.json`: Aggregated B&B optimization results.
- `networks/any-town.inp`: The AnyTown water distribution network model.

Outputs:
- `article/figures/tank_levels_24h.png`: A 2x3 grid plot visualizing the hydraulic state constraints.

Dependencies:
- wntr: For EPANET hydraulic simulation.
- matplotlib: For plotting.
- numpy: For numerical operations.
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import wntr
from pathlib import Path

# Get the project root directory
script_dir = Path(__file__).parent
project_root = script_dir.parent

# Pump names in the order used by B&B (must match BBConstraints.cpp)
PUMP_ORDER = ["111", "222", "333"]
NUM_PUMPS = len(PUMP_ORDER)
HOURS = 24
TANK_IDS = ["65", "165", "265"]

# Tank level bounds from the network file
LEVEL_MIN = 66.53
LEVEL_MAX = 71.53
LEVEL_INIT = 66.93

# Pressure constraints (must match `src/CLI/BBConstraints.cpp`)
PRESSURE_NODE_IDS = ["55", "90", "170"]
PRESSURE_THRESHOLDS = {"55": 42.0, "90": 51.0, "170": 30.0}


def extract_pump_schedules(best_x: list) -> dict:
    """
    Extract per-pump schedules from best_x vector.

    best_x format: [h0_p0, h0_p1, h0_p2, h1_p0, h1_p1, h1_p2, ...]
    We use hours 1-24 (hour 0 is ignored by B&B).

    Returns dict: {pump_name: [24 binary values]}
    """
    schedules = {pump: [] for pump in PUMP_ORDER}

    # Extract values for hours 1 to 24
    for hour in range(1, HOURS + 1):
        base_idx = hour * NUM_PUMPS
        for i, pump in enumerate(PUMP_ORDER):
            if base_idx + i < len(best_x):
                schedules[pump].append(best_x[base_idx + i])
            else:
                schedules[pump].append(0)

    return schedules


def run_simulation_with_schedule(inp_path: str, schedules: dict) -> tuple[dict, dict]:
    """
    Run WNTR simulation with the given pump schedules.

    Returns:
        tank_levels: {tank_id: [level at each hour]}
        pressures: {node_id: [pressure at each hour]}
    """
    # Load the network
    wn = wntr.network.WaterNetworkModel(inp_path)

    # Modify pump patterns
    for pump_id, schedule in schedules.items():
        pattern_name = f"PMP{pump_id}"
        # Get existing pattern or create new one
        if pattern_name in wn.pattern_name_list:
            pattern = wn.get_pattern(pattern_name)
            if pattern is not None:
                # Update multipliers
                pattern.multipliers = schedule
            else:
                # Create new pattern if get_pattern returned None
                wn.add_pattern(pattern_name, schedule)
        else:
            # Create new pattern
            wn.add_pattern(pattern_name, schedule)

    # Run simulation
    sim = wntr.sim.EpanetSimulator(wn)
    results = sim.run_sim()

    # Extract tank levels at each hour
    tank_levels = {}
    for tank_id in TANK_IDS:
        # Results are indexed by time in seconds
        # We want levels at hours 0-24
        levels = []
        if "head" in results.node:
            head_df = results.node["head"]
            for hour in range(HOURS + 1):
                time_sec = hour * 3600
                if time_sec in head_df.index and tank_id in head_df.columns:
                    # For tanks, head = elevation + level
                    # AnyTown tanks have elevation 0, so head = level
                    level = head_df.loc[time_sec, tank_id]
                    levels.append(level)
                else:
                    levels.append(LEVEL_INIT)  # Fallback to initial level if missing
        tank_levels[tank_id] = levels

    pressures = {}
    for node_id in PRESSURE_NODE_IDS:
        values = []
        if "pressure" in results.node:
            pressure_df = results.node["pressure"]
            for hour in range(HOURS + 1):
                time_sec = hour * 3600
                if time_sec in pressure_df.index and node_id in pressure_df.columns:
                    values.append(pressure_df.loc[time_sec, node_id])
                else:
                    values.append(0.0)  # Fallback if missing
        pressures[node_id] = values

    return tank_levels, pressures


def main():
    """
    Main execution routine.

    1. Loads optimization results from `agg_outputs.json`.
    2. Filters for valid solutions (valid cost, correct horizon, known actuation limits).
    3. Simulates each valid solution using the AnyTown network model.
    4. Generates and saves a multi-panel figure comparing hydraulic responses.
    """
    # Load solutions for each actuation limit from the aggregated outputs.
    # Expected schema:
    #   {"runs": [{"config": {"a": 1, "h": 24, ...}, "best": {"x": [...], "cost": ...}}, ...]}
    agg_path = project_root / "article/data/outputs/agg_outputs.json"
    with open(agg_path, "r") as f:
        agg = json.load(f)

    solutions = {}
    for run in agg.get("runs", []):
        cfg = run.get("config", {})
        best = run.get("best", {})

        a_max = cfg.get("a")
        if a_max not in [1, 2, 3]:
            continue
        if cfg.get("h", HOURS) != HOURS:
            continue
        if "x" not in best or "cost" not in best:
            continue

        solutions[a_max] = {"best_x": best["x"], "best_cost": best["cost"]}

    missing = [a for a in [1, 2, 3] if a not in solutions]
    if missing:
        raise RuntimeError(
            f"Missing runs for actuation limits: {missing} in {agg_path}"
        )

    # Run simulations and collect tank levels + pressures
    all_tank_levels = {}
    all_pressures = {}
    inp_path = project_root / "networks/any-town.inp"

    for a_max, solution in solutions.items():
        print(f"Running simulation for NA_max = {a_max}...")
        schedules = extract_pump_schedules(solution["best_x"])
        tank_levels, pressures = run_simulation_with_schedule(str(inp_path), schedules)
        all_tank_levels[a_max] = tank_levels
        all_pressures[a_max] = pressures
        print(f"  Cost: ${solution['best_cost']:.2f}")

    # Create 2x3 figure: tank levels (top) + pressures (bottom)
    fig, axes = plt.subplots(2, 3, figsize=(10, 6.0), dpi=300, sharex=True)

    # Colors for different actuation limits
    colors = {1: "#E63946", 2: "#457B9D", 3: "#2A9D8F"}
    linestyles = {1: "-", 2: "--", 3: ":"}

    hours = np.arange(HOURS + 1)

    for idx, tank_id in enumerate(TANK_IDS):
        ax = axes[0, idx]

        for a_max in [1, 2, 3]:
            levels = all_tank_levels[a_max][tank_id]
            ax.plot(
                hours,
                levels,
                color=colors[a_max],
                linestyle=linestyles[a_max],
                linewidth=1.5,
                label=f"$NA_{{\\max}}={a_max}$",
            )

        # Add horizontal lines for bounds
        ax.axhline(y=LEVEL_MIN, color="gray", linestyle="--", alpha=0.7, linewidth=0.8)
        ax.axhline(y=LEVEL_MAX, color="gray", linestyle="--", alpha=0.7, linewidth=0.8)
        ax.axhline(y=LEVEL_INIT, color="gray", linestyle=":", alpha=0.5, linewidth=0.8)

        # Fill region outside bounds
        ax.axhspan(LEVEL_MIN - 0.5, LEVEL_MIN, alpha=0.1, color="red")
        ax.axhspan(LEVEL_MAX, LEVEL_MAX + 0.5, alpha=0.1, color="red")

        # Labels and formatting
        ax.set_ylabel("Water Level (m)")
        ax.set_title(f"Tank {tank_id}")
        ax.set_xlim(0, 24)
        ax.set_ylim(LEVEL_MIN - 0.3, LEVEL_MAX + 0.3)
        ax.set_xticks([0, 6, 12, 18, 24])
        ax.grid(True, alpha=0.3)

        # Add bound labels on the first subplot
        if idx == 0:
            ax.text(24.5, LEVEL_MIN, "$L_{min}$", va="center", fontsize=8)
            ax.text(24.5, LEVEL_MAX, "$L_{max}$", va="center", fontsize=8)
            ax.text(24.5, LEVEL_INIT, "$L_0$", va="center", fontsize=8)

    for idx, node_id in enumerate(PRESSURE_NODE_IDS):
        ax = axes[1, idx]

        series_by_a = {}
        for a_max in [1, 2, 3]:
            values = all_pressures[a_max][node_id]
            series_by_a[a_max] = values
            ax.plot(
                hours[: len(values)],
                values,
                color=colors[a_max],
                linestyle=linestyles[a_max],
                linewidth=1.5,
                label=f"$NA_{{\\max}}={a_max}$",
            )

        threshold = PRESSURE_THRESHOLDS.get(node_id)
        all_values = [v for values in series_by_a.values() for v in values]
        if threshold is not None:
            ax.axhline(
                y=threshold, color="gray", linestyle="--", alpha=0.7, linewidth=0.8
            )

        if all_values:
            y_min = min(all_values + ([threshold] if threshold is not None else [])) - 1
            y_max = max(all_values + ([threshold] if threshold is not None else [])) + 1
            ax.set_ylim(y_min, y_max)
            if threshold is not None and y_min < threshold:
                ax.axhspan(y_min, threshold, alpha=0.08, color="red")

        ax.set_xlabel("Hour")
        ax.set_ylabel("Pressure (m)")
        ax.set_title(f"Node {node_id}")
        ax.set_xlim(0, 24)
        ax.set_xticks([0, 6, 12, 18, 24])
        ax.grid(True, alpha=0.3)

    # Add horizontal legend at the bottom (outside the plot)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    legend = fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=3,
        fontsize=16,
        bbox_to_anchor=(0.5, -0.08),
        frameon=True,
        fancybox=True,
        shadow=True,
        framealpha=0.95,
        edgecolor="gray",
        facecolor="white",
    )

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.13)

    # Save figure
    output_path = project_root / "article/figures/tank_levels_24h.png"
    plt.savefig(
        output_path, dpi=300, bbox_inches="tight", facecolor="white", edgecolor="none"
    )
    plt.close()

    print(f"\nTank levels plot saved to {output_path}")


if __name__ == "__main__":
    main()
