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
FIGURE_OUTPUT = "paper/figures/Figure_5_scalability.pdf"
DATA = [
    {"np": 1, "wall_time": 85.08, "speedup": 1.00, "efficiency": 100.0},
    {"np": 2, "wall_time": 46.13, "speedup": 1.84, "efficiency": 92.2},
    {"np": 4, "wall_time": 23.19, "speedup": 3.67, "efficiency": 91.7},
    {"np": 8, "wall_time": 12.35, "speedup": 6.89, "efficiency": 86.1},
    {"np": 16, "wall_time": 7.47, "speedup": 11.39, "efficiency": 71.2},
    {"np": 32, "wall_time": 4.26, "speedup": 20.00, "efficiency": 62.5},
    {"np": 64, "wall_time": 3.18, "speedup": 26.76, "efficiency": 41.8},
    {"np": 128, "wall_time": 3.59, "speedup": 23.69, "efficiency": 18.5},
]


def create_figure(df: pd.DataFrame):
    """Create scalability figure with speedup and efficiency."""
    plt.rcParams.update({"font.size": 14})
    fig, ax1 = plt.subplots(figsize=(10, 5.88), dpi=200)

    ranks = df["np"].values
    speedup = df["speedup"].values
    efficiency = df["efficiency"].values

    # Speedup plot (left axis)
    color_speedup = "#222222"
    ax1.set_xlabel("Number of MPI Processes", fontsize=16)
    ax1.set_ylabel("Speedup", color=color_speedup)
    (line1,) = ax1.plot(
        ranks,
        speedup,
        "o-",
        color=color_speedup,
        label="Speedup",
        markerfacecolor="#222222",
        markeredgecolor="#222222",
        markersize=4,
        linewidth=1.5,
    )
    # Ideal speedup line
    (line2,) = ax1.plot(
        ranks,
        ranks,
        "--",
        color="#9e9e9e",
        alpha=0.9,
        label="Ideal Speedup",
        linewidth=1.2,
    )
    ax1.tick_params(axis="y", labelcolor=color_speedup)
    ax1.set_xscale("log", base=2)
    ax1.set_yscale("log", base=2)
    ax1.set_xticks(ranks)
    ax1.set_xticklabels([rf"$2^{{{i}}}$" for i in range(len(ranks))])
    ax1.grid(True, which="both", linestyle="--", alpha=0.5, color="#c7c7c7")

    # Efficiency on secondary axis (right axis)
    ax2 = ax1.twinx()
    color_efficiency = "#7a7a7a"
    ax2.set_ylabel("Efficiency (%)", color=color_efficiency)
    (line3,) = ax2.plot(
        ranks,
        efficiency,
        "s-",
        color=color_efficiency,
        label="Efficiency",
        markerfacecolor="white",
        markeredgecolor="#555555",
        markersize=4,
        linewidth=1.5,
    )
    ax2.tick_params(axis="y", labelcolor=color_efficiency)
    ax2.set_ylim(0, 110)

    # Combine legends
    lines = [line1, line2, line3]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="lower right", fontsize=14, framealpha=0.9)
    plt.title("Scalability Analysis", fontsize=18)
    fig.tight_layout()
    plt.savefig(FIGURE_OUTPUT, dpi=500, bbox_inches="tight")
    print(f"Figure saved to {FIGURE_OUTPUT}")


def main():
    # Ensure output directory exists
    Path(FIGURE_OUTPUT).parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(DATA)

    # Create figure
    create_figure(df)


if __name__ == "__main__":
    main()
