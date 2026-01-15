#!/usr/bin/env python3
"""
run_scalability.py - Run scalability tests and analyze results.

This script runs the EPANET B&B optimizer with different numbers of MPI processes
and measures speedup, efficiency, and load imbalance.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Configuration
NP_VALUES = [1, 2, 4, 8, 16, 32, 64, 128]
ACTUATIONS = 1
H_MAX = 24
EXECUTABLE = "build/run-epanet3-bb"
OUTPUT_DIR = "outputs"
CSV_OUTPUT = "outputs/scalability_results.csv"
FIGURE_OUTPUT = "article/figures/scalability.png"


def run_test(nprocs: int) -> dict:
    """Run a single scalability test with nprocs MPI processes."""
    cmd = f"mpirun -n {nprocs} {EXECUTABLE} -a {ACTUATIONS} -h {H_MAX}"
    print(f"Running: {cmd}")

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error running with nprocs={nprocs}:")
        print(result.stderr)
        return None

    # Parse JSON stats files from all ranks
    stats = parse_stats_files(nprocs)
    return stats


def parse_stats_files(nprocs: int) -> dict:
    """Parse JSON stats files from all ranks and compute aggregate metrics."""
    durations = []
    tasks_list = []
    time_totals = []
    time_syncs = []

    for rank in range(nprocs):
        # Pattern: outputs/run_a_XX_h_XX_l_XX_s_XX_n_XX_r_XX_stats.json
        pattern = f"run_a_{ACTUATIONS:02d}_h_{H_MAX:02d}_*_n_{nprocs:02d}_r_{rank:02d}_stats.json"
        matches = list(Path(OUTPUT_DIR).glob(pattern))

        if not matches:
            print(f"Warning: No stats file found for nprocs={nprocs}, rank={rank}")
            continue

        stats_file = matches[0]
        with open(stats_file) as f:
            data = json.load(f)
            durations.append(data.get("duration", 0))
            tasks_list.append(data.get("tasks_processed", 0))
            time_totals.append(data.get("time_total", 0))
            time_syncs.append(data.get("time_sync", 0))

    if not durations:
        return None

    durations = np.array(durations)
    time_totals = np.array(time_totals)

    # Use max total time as the wall-clock time for this run
    wall_time = float(np.max(time_totals))

    # Load imbalance metrics based on processing time (duration)
    proc_min = float(np.min(durations))
    proc_avg = float(np.mean(durations))
    proc_max = float(np.max(durations))
    load_imbalance = (proc_max - proc_avg) / proc_avg * 100 if proc_avg > 0 else 0

    return {
        "np": nprocs,
        "wall_time": wall_time,
        "proc_min": proc_min,
        "proc_avg": proc_avg,
        "proc_max": proc_max,
        "load_imbalance": load_imbalance,
        "total_tasks": sum(tasks_list),
    }


def run_all_tests() -> pd.DataFrame:
    """Run tests for all np values and collect results."""
    results = []

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(FIGURE_OUTPUT), exist_ok=True)

    for np_val in NP_VALUES:
        stats = run_test(np_val)
        if stats:
            results.append(stats)
        else:
            print(f"Skipping np={np_val} due to errors")

    if not results:
        print("No successful runs!")
        sys.exit(1)

    df = pd.DataFrame(results)

    # Compute speedup and efficiency
    t1 = df.loc[df["np"] == 1, "wall_time"].values
    if len(t1) == 0:
        # Estimate T1 from smallest np run
        t1 = df.iloc[0]["wall_time"] * df.iloc[0]["np"]
    else:
        t1 = t1[0]

    df["speedup"] = t1 / df["wall_time"]
    df["efficiency"] = df["speedup"] / df["np"] * 100

    return df


def save_csv(df: pd.DataFrame):
    """Save results to CSV."""
    df.to_csv(CSV_OUTPUT, index=False)
    print(f"Results saved to {CSV_OUTPUT}")


def create_figure(df: pd.DataFrame):
    """Create scalability figure with speedup and efficiency."""
    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Set larger font sizes
    plt.rcParams.update({"font.size": 14})

    ranks = df["np"].values
    speedup = df["speedup"].values
    efficiency = df["efficiency"].values
    load_imbalance = df["load_imbalance"].values

    # Speedup plot
    color = "tab:blue"
    ax1.set_xlabel("Number of MPI Processes", fontsize=16)
    ax1.set_ylabel("Speedup", color=color, fontsize=16)
    (line1,) = ax1.plot(
        ranks, speedup, "o-", color=color, label="Speedup", markersize=8, linewidth=2
    )
    (line2,) = ax1.plot(
        ranks, ranks, "--", color="gray", alpha=0.5, label="Ideal Speedup", linewidth=2
    )
    ax1.tick_params(axis="y", labelcolor=color, labelsize=14)
    ax1.tick_params(axis="x", labelsize=14)
    ax1.set_xscale("log", base=2)
    ax1.set_yscale("log", base=2)
    ax1.grid(True, which="both", linestyle="--", alpha=0.5)

    # Efficiency on secondary axis
    ax2 = ax1.twinx()
    color = "tab:red"
    ax2.set_ylabel("Efficiency (%)", color=color, fontsize=16)
    (line3,) = ax2.plot(
        ranks,
        efficiency,
        "s-",
        color=color,
        label="Efficiency",
        markersize=8,
        linewidth=2,
    )
    ax2.tick_params(axis="y", labelcolor=color, labelsize=14)
    ax2.set_ylim(0, 110)

    # Combine legends
    lines = [line1, line2, line3]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="lower right", fontsize=14, framealpha=0.9)

    plt.title("Scalability Analysis", fontsize=18)
    fig.tight_layout()
    plt.savefig(FIGURE_OUTPUT, dpi=300, bbox_inches="tight")
    print(f"Figure saved to {FIGURE_OUTPUT}")


def main():
    print("=" * 60)
    print("EPANET B&B Scalability Test")
    print(f"Configuration: -a {ACTUATIONS} -h {H_MAX}")
    print(f"Process counts: {NP_VALUES}")
    print("=" * 60)

    df = run_all_tests()

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    print(df.to_string(index=False))

    save_csv(df)
    create_figure(df)


if __name__ == "__main__":
    main()
