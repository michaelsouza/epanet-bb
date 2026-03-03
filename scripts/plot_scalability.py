#!/usr/bin/env python3
"""
plot_scalability.py - Generate scalability figure from CSV data.

This script reads scalability results from CSV and creates a publication-quality
figure showing speedup and efficiency vs number of MPI processes.

Usage:
    .venv/bin/python scripts/plot_scalability.py
"""

import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path

# Configuration
CSV_INPUT = "article/data/scalability_results.csv"
FIGURE_OUTPUT = "article/figures/scalability.png"


def create_figure(df: pd.DataFrame):
    """Create scalability figure with speedup and efficiency."""
    plt.rcParams.update({"font.size": 10})
    fig, ax1 = plt.subplots(figsize=(5.0, 3.2), dpi=500)

    ranks = df["np"].values
    speedup = df["speedup"].values
    efficiency = df["efficiency"].values

    # Speedup plot (left axis)
    color_speedup = "tab:blue"
    ax1.set_xlabel("MPI processes")
    ax1.set_ylabel("Speedup", color=color_speedup)
    (line1,) = ax1.plot(
        ranks,
        speedup,
        "o-",
        color=color_speedup,
        label="Speedup",
        markersize=4,
        linewidth=1.5,
    )
    # Ideal speedup line
    (line2,) = ax1.plot(
        ranks,
        ranks,
        "--",
        color="gray",
        alpha=0.5,
        label="Ideal",
        linewidth=1.2,
    )
    ax1.tick_params(axis="y", labelcolor=color_speedup)
    ax1.set_xscale("log", base=2)
    ax1.set_yscale("log", base=2)
    ax1.set_xticks(ranks)
    ax1.set_xticklabels([str(r) for r in ranks])
    ax1.grid(True, which="both", linestyle="--", alpha=0.5)

    # Efficiency on secondary axis (right axis)
    ax2 = ax1.twinx()
    color_efficiency = "tab:red"
    ax2.set_ylabel("Efficiency (%)", color=color_efficiency)
    (line3,) = ax2.plot(
        ranks,
        efficiency,
        "s-",
        color=color_efficiency,
        label="Efficiency",
        markersize=4,
        linewidth=1.5,
    )
    ax2.tick_params(axis="y", labelcolor=color_efficiency)
    ax2.set_ylim(0, 110)

    # Combine legends
    lines = [line1, line2, line3]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="lower right", framealpha=0.9)
    fig.tight_layout()
    plt.savefig(FIGURE_OUTPUT, dpi=500, bbox_inches="tight")
    print(f"Figure saved to {FIGURE_OUTPUT}")


def main():
    # Ensure output directory exists
    Path(FIGURE_OUTPUT).parent.mkdir(parents=True, exist_ok=True)

    # Read CSV data
    df = pd.read_csv(CSV_INPUT)
    print(f"Read {len(df)} data points from {CSV_INPUT}")
    expected_columns = {"np", "wall_time", "speedup", "efficiency", "load_imbalance"}
    missing = expected_columns - set(df.columns)
    if missing:
        raise RuntimeError(f"Missing required columns in {CSV_INPUT}: {sorted(missing)}")

    # Create figure
    create_figure(df)


if __name__ == "__main__":
    main()
