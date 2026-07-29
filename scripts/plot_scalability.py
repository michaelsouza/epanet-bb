#!/usr/bin/env python3
"""
plot_scalability.py - Generate scalability figure from CSV data.

This script reads scalability results from CSV and creates a publication-quality
figure showing speedup and efficiency vs number of MPI processes.

Usage:
    .venv/bin/python scripts/plot_scalability.py \
        --data paper/data/scalability_results.csv \
        --output build/reproduced-manuscript/Figure_5_scalability.pdf
"""

import argparse
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).absolute().parents[1]
DEFAULT_DATA = PROJECT_ROOT / "paper" / "data" / "scalability_results.csv"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "paper" / "figures" / "Figure_5_scalability.pdf"
)


def create_figure(df: pd.DataFrame, output_path: Path) -> None:
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
        markersize=8,
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
        markersize=8,
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
    plt.savefig(output_path, dpi=500, bbox_inches="tight")
    plt.close(fig)
    print(f"Figure saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    data_path = arguments.data.expanduser().absolute()
    output_path = arguments.output.expanduser().absolute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(data_path)
    required_columns = {"np", "speedup", "efficiency"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(
            "scalability data is missing columns: "
            + ", ".join(sorted(missing_columns))
        )
    create_figure(df, output_path)


if __name__ == "__main__":
    main()
