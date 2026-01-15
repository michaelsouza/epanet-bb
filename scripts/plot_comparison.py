import os
import json
import matplotlib.pyplot as plt
import numpy as np

# Configuration
METHODS = ["Costa2016", "Cimorelli2020", "Paola2025", "Souza2026"]
ACTUATIONS = [1, 2, 3]
LABELS = {
    "Costa2016": "Costa et al. (2016)",
    "Cimorelli2020": "Cimorelli et al. (2020)",
    "Paola2025": "De Paola et al. (2025)",
    "Souza2026": "EPANET-BB",
}
MARKERS = {"Costa2016": "o", "Cimorelli2020": "s", "Paola2025": "^", "Souza2026": "*"}
COLORS = {
    "Costa2016": "#e41a1c",
    "Cimorelli2020": "#377eb8",
    "Paola2025": "#4daf4a",
    "Souza2026": "#984ea3",
}


def load_data():
    data = {method: {"cost": [], "time": []} for method in METHODS}
    for method in METHODS:
        for a in ACTUATIONS:
            fn = f"outputs/run_{method}_a_{a:02d}.json"
            if os.path.exists(fn):
                with open(fn, "r") as f:
                    content = json.load(f)
                    data[method]["cost"].append(content["best_cost"])
                    data[method]["time"].append(content["duration"])
            else:
                print(f"Warning: {fn} not found.")
                data[method]["cost"].append(None)
                data[method]["time"].append(None)
    return data


def plot_summary(data):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)

    # X-axis setup
    x = np.arange(len(ACTUATIONS))
    width = 0.18  # the width of the bars

    # 1. Top Subplot: Cost
    all_costs = [c for m in METHODS for c in data[m]["cost"] if c is not None]
    if all_costs:
        ymin = min(all_costs) * 0.99
        ymax = max(all_costs) * 1.01
        ax1.set_ylim(ymin, ymax + (ymax - ymin) * 0.3)  # Space for 45 deg labels
    else:
        ymin, ymax = 0, 1

    for i, method in enumerate(METHODS):
        costs = data[method]["cost"]
        pos = x + (i - 1.5) * width
        bars = ax1.bar(
            pos,
            costs,
            width,
            label=LABELS[method],
            color=COLORS[method],
            edgecolor="black",
            alpha=0.8,
        )

        # Add value labels
        for bar in bars:
            height = bar.get_height()
            if height:
                ax1.text(
                    bar.get_x() + bar.get_width() / 2,
                    height + (ymax - ymin) * 0.02,
                    f"${height:,.2f}",
                    ha="center",
                    va="bottom",
                    rotation=45,
                    fontsize=8,
                )

    ax1.set_ylabel("Optimal Cost ($)", fontsize=12, fontweight="bold")
    ax1.set_title("AnyTown Modified: Optimal Energy Cost", fontsize=13)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.7)

    # 2. Bottom Subplot: Speedup
    # Calculate speedup relative to Souza2026
    souza_times = np.array(data["Souza2026"]["time"])
    all_speedups = []
    method_speedups = {}
    for i, method in enumerate(METHODS):
        if method == "Souza2026":
            speedups = [1.0] * len(ACTUATIONS)
        else:
            other_times = np.array(data[method]["time"])
            speedups = [
                t_o / t_s if t_s and t_o else 0
                for t_o, t_s in zip(other_times, souza_times)
            ]
        method_speedups[method] = speedups
        all_speedups.extend([s for s in speedups if s > 0])

    if all_speedups:
        smax = max(all_speedups)
        # Increase ylim for log scale to fit labels
        ax2.set_ylim(0.8, smax * 10)

    for i, method in enumerate(METHODS):
        speedups = method_speedups[method]
        pos = x + (i - 1.5) * width
        bars = ax2.bar(
            pos,
            speedups,
            width,
            label=LABELS[method],
            color=COLORS[method],
            edgecolor="black",
            alpha=0.8,
        )

        # Add speedup labels
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                label = f"{height:.1f}x" if height >= 10 else f"{height:.2f}x"
                if method == "Souza2026":
                    label = "1.0x"
                # For log scale, offset should be multiplicative
                ax2.text(
                    bar.get_x() + bar.get_width() / 2,
                    height * 1.2,
                    label,
                    ha="center",
                    va="bottom",
                    rotation=45,
                    fontsize=8,
                )

    # Add a horizontal line at Speedup = 1
    ax2.axhline(1, color="black", linestyle="-", linewidth=0.8, alpha=0.5)

    ax2.set_ylabel("Speedup (relative to Proposed)", fontsize=12, fontweight="bold")
    ax2.set_yscale("log")
    ax2.set_title("Computational Speedup (Log Scale)", fontsize=13)
    ax2.grid(True, axis="y", which="both", linestyle="--", alpha=0.5)

    # X-axis labels
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"$NA_{{max}}={a}$" for a in ACTUATIONS], fontsize=11)
    ax2.set_xlabel("Maximum Actuations", fontsize=12)

    # Legends - inside the plot area
    ax1.legend(
        loc="upper right",
        ncol=1,
        frameon=True,
        fontsize=9,
        framealpha=0.9,
    )

    plt.tight_layout()

    os.makedirs("article/figures", exist_ok=True)
    out_fn = "article/figures/comparison_summary.png"
    plt.savefig(out_fn, dpi=300, bbox_inches="tight")
    print(f"Plot saved to {out_fn}")


if __name__ == "__main__":
    data = load_data()
    plot_summary(data)
