#!/usr/bin/env python3
"""Generate hydraulic results plot with a tabular pump view, inspired by AnyTown comparison tables."""

import json
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import wntr
from pathlib import Path

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
    """Run WNTR simulation and extract tank levels and node pressures."""
    wn = wntr.network.WaterNetworkModel(inp_path)

    # Update pump patterns
    for pump_id, schedule in schedules.items():
        pattern_name = f"PMP{pump_id}"
        if pattern_name in wn.pattern_name_list:
            pattern = wn.get_pattern(pattern_name)
            pattern.multipliers = schedule
        else:
            wn.add_pattern(pattern_name, schedule)

    sim = wntr.sim.EpanetSimulator(wn)
    results = sim.run_sim()

    # Extract results
    tank_levels = {}
    node_pressures = {}

    hours_range = np.arange(HOURS + 1)

    for tank_id in TANK_IDS:
        tank_levels[tank_id] = [
            results.node["head"].loc[h * 3600, tank_id] for h in hours_range
        ]

    for node_id in PRESSURE_NODE_IDS:
        node_pressures[node_id] = [
            results.node["pressure"].loc[h * 3600, node_id] for h in hours_range
        ]

    return tank_levels, node_pressures


def get_energy_prices(inp_path: str) -> list:
    """Extract energy prices from the input file."""
    wn = wntr.network.WaterNetworkModel(inp_path)
    if "PRICES" in wn.pattern_name_list:
        pattern = wn.get_pattern("PRICES")
        return list(pattern.multipliers)
    return [0.0] * HOURS


def main():
    parser = argparse.ArgumentParser(
        description="Plot hydraulic results with tabular pump schedule."
    )
    parser.add_argument("json_files", nargs="+", help="One or more JSON result files.")
    parser.add_argument(
        "--output",
        default="article/figures/hydraulic_results.png",
        help="Output plot path.",
    )
    parser.add_argument(
        "--inp", default="networks/any-town.inp", help="Path to EPANET .inp file."
    )
    args = parser.parse_args()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    solutions = []
    for fpath in args.json_files:
        with open(fpath, "r") as f:
            data = json.load(f)
            label = Path(fpath).stem
            solutions.append({"data": data, "label": label})

    # Run simulations
    results_data = []
    for sol in solutions:
        print(f"Running simulation for {sol['label']}...")
        best_x = sol["data"].get("best_x")
        if not best_x:
            continue

        schedules = extract_pump_schedules(best_x)
        tanks, pressures = run_simulation(args.inp, schedules)
        results_data.append(
            {
                "label": sol["label"],
                "tanks": tanks,
                "pressures": pressures,
                "schedules": schedules,
            }
        )

    # Create figure with GridSpec
    # 2 rows for hydraulic plots, 1 row for energy prices, 1 row (taller) for pump table
    fig = plt.figure(figsize=(15, 14), dpi=150)
    gs = gridspec.GridSpec(4, 3, height_ratios=[1, 1, 0.6, 1.2])

    hours = np.arange(HOURS + 1)
    plot_hours = np.arange(1, HOURS + 1)
    cmap = plt.get_cmap("tab10")

    # Row 1: Tanks
    for i, tank_id in enumerate(TANK_IDS):
        ax = fig.add_subplot(gs[0, i])
        for idx, res in enumerate(results_data):
            ax.plot(
                hours,
                res["tanks"][tank_id],
                label=res["label"],
                color=cmap(idx),
                linewidth=1.5,
            )

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

        ax.set_title(f"Tank {tank_id}", fontsize=11, fontweight="bold")
        if i == 0:
            ax.set_ylabel("Level (m)")
        ax.grid(True, alpha=0.2)
        ax.set_xlim(0, 24)

    # Row 2: Pressures
    for i, node_id in enumerate(PRESSURE_NODE_IDS):
        ax = fig.add_subplot(gs[1, i])
        for idx, res in enumerate(results_data):
            ax.plot(
                hours,
                res["pressures"][node_id],
                label=res["label"],
                color=cmap(idx),
                linewidth=1.5,
            )

        threshold = PRESSURE_THRESHOLDS[node_id]
        ax.axhline(
            y=threshold,
            color="orange",
            linestyle="--",
            alpha=0.6,
            label="Min Pressure" if i == 0 else "",
        )

        ax.set_title(f"Node {node_id}", fontsize=11, fontweight="bold")
        if i == 0:
            ax.set_ylabel("Pressure (m)")
        ax.set_xlabel("Hour")
        ax.grid(True, alpha=0.2)
        ax.set_xlim(0, 24)

    # Add legend centered between row 1 and 2
    handles, labels = fig.axes[0].get_legend_handles_labels()
    # Add Min Pressure if not in labels
    h_p, l_p = fig.axes[3].get_legend_handles_labels()
    for h, l in zip(h_p, l_p):
        if l not in labels:
            handles.append(h)
            labels.append(l)

    fig.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.82, 0.95),
        fontsize="small",
    )

    # Row 3: Energy Prices
    ax_prices = fig.add_subplot(gs[2, :])
    prices = get_energy_prices(args.inp)

    # Extend prices to match HOURS + 1 for step plot if needed,
    # but pattern is usually hourly. WNTR multipliers are hourly.
    # For 24 hours simulation, we have 24 multipliers.
    price_hours = np.arange(len(prices))
    ax_prices.step(price_hours, prices, where="post", color="darkblue", linewidth=2)
    ax_prices.fill_between(
        price_hours, prices, step="post", alpha=0.1, color="darkblue"
    )

    ax_prices.set_title(
        "Energy Prices (PRICES Pattern)", fontsize=12, fontweight="bold"
    )
    ax_prices.set_ylabel("Price ($/kWh)")
    ax_prices.set_xlim(0, 24)
    ax_prices.set_xticks(np.arange(0, 25, 2))
    ax_prices.grid(True, alpha=0.2)

    # Row 4: Pump Comparison Table
    ax_table = fig.add_subplot(gs[3, :])

    # Prepare data for "heatmap"
    # One row for each pump of each solution
    table_rows = []
    row_labels = []
    row_colors = []

    for idx, res in enumerate(results_data):
        for pump_id in PUMP_ORDER:
            table_rows.append(res["schedules"][pump_id])
            row_labels.append(f"{res['label']} - P{pump_id}")
            row_colors.append(cmap(idx))

    data_matrix = np.array(table_rows)

    # Custom color map: white for Off, green for On
    from matplotlib.colors import ListedColormap

    on_off_cmap = ListedColormap(["#f5f5f5", "#2ca02c"])

    im = ax_table.imshow(data_matrix, aspect="auto", cmap=on_off_cmap)

    # Add markers like in the reference image (dots in green cells)
    for r in range(data_matrix.shape[0]):
        for c in range(data_matrix.shape[1]):
            if data_matrix[r, c] == 1:
                ax_table.text(
                    c, r, "•", ha="center", va="center", color="white", fontsize=12
                )

    # Formatting the table axis
    ax_table.set_xticks(np.arange(HOURS))
    ax_table.set_xticklabels([f"{h+1:02d}" for h in range(HOURS)])
    ax_table.set_yticks(np.arange(len(row_labels)))
    ax_table.set_yticklabels(row_labels, fontsize=9)
    # ax_table.tick_params(axis='both', which='both', length=0)

    # Add vertical lines to separate hours
    for x in range(HOURS + 1):
        ax_table.axvline(x - 0.5, color="gray", linewidth=0.5, alpha=0.3)

    # Add horizontal lines to group solutions
    for i in range(1, len(results_data)):
        ax_table.axhline(i * 3 - 0.5, color="black", linewidth=1.5, alpha=0.7)

    ax_table.set_title(
        "Pump Operation Schedules (ON/OFF)", fontsize=12, fontweight="bold", pad=15
    )
    ax_table.set_xlabel("Hour")

    plt.tight_layout()
    # Adjust layout to make room for the legend on the right
    plt.subplots_adjust(right=0.81)
    plt.savefig(args.output, dpi=300, bbox_inches="tight")
    print(f"\nImproved plot saved to {args.output}")

    # Remove the temp files (temp.bin, temp.inp, temp.rpt)
    Path("temp.bin").unlink(missing_ok=True)
    Path("temp.inp").unlink(missing_ok=True)
    Path("temp.rpt").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
