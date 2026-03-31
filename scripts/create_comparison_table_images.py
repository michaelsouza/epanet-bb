import csv
import json
import re
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path

DATA_DIR = Path("paper/data")
OUTPUT_DIR = Path("paper/figures")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Source display configuration (key -> label, color)
SOURCE_CONFIG = {
    "Costa2016": ("Costa et al. (2016)", "#e74c3c"),
    "Cimorelli2020": ("Cimorelli et al. (2020)", "#3498db"),
    "Paola2025": ("De Paola et al. (2025)", "#9b59b6"),
    "Souza2026": ("EPANET-BB", "#27ae60"),
}


def discover_sources():
    """Discover available sources and actuation levels from JSON files."""
    data = {1: [], 2: [], 3: []}
    pattern = re.compile(r"run_(.+)_a_(\d+)\.json")

    for filepath in sorted(DATA_DIR.glob("run_*_a_*.json")):
        match = pattern.match(filepath.name)
        if not match:
            continue

        source_key = match.group(1)
        na_max = int(match.group(2))

        if source_key not in SOURCE_CONFIG or na_max not in data:
            continue

        with open(filepath) as f:
            content = json.load(f)

        label, color = SOURCE_CONFIG[source_key]
        x_full = np.array(content["best_x"], dtype=int).reshape(-1, 3)
        x_24h = x_full[1:, :]  # Drop hour 0

        # Calculate switches per pump
        switches = [np.sum(x_full[1:, p] != x_full[:-1, p]) for p in range(3)]

        data[na_max].append(
            {
                "key": source_key,
                "label": label,
                "color": color,
                "cost": content["best_cost"],
                "time": content.get("duration", 0.0),
                "schedule": x_24h,
                "switches": switches,
            }
        )

    # Sort by source order and mark best
    for na_max in data:
        order = list(SOURCE_CONFIG.keys())
        data[na_max].sort(key=lambda e: order.index(e["key"]))

        if data[na_max]:
            best_cost = min(e["cost"] for e in data[na_max])
            best_time = min(
                (e["time"] for e in data[na_max] if e["time"] > 0), default=float("inf")
            )
            for e in data[na_max]:
                e["is_best"] = abs(e["cost"] - best_cost) < 1e-6
                e["is_fastest"] = e["time"] > 0 and abs(e["time"] - best_time) < 1e-6

    return data


def draw_table(na_max, entries, output_path):
    """Draw comparison table for a specific NA_max."""
    H_HEADER, H_ROW = 0.6, 0.4
    H_SOURCE = 3 * H_ROW
    W_SOURCE, W_COST, W_TIME, W_PUMP, W_SW, W_HOUR = 2.5, 1.2, 1.0, 0.6, 0.6, 0.3

    W_TOTAL = W_SOURCE + W_COST + W_TIME + W_PUMP + W_SW + 24 * W_HOUR
    H_TOTAL = H_HEADER + len(entries) * H_SOURCE + 0.5

    fig, ax = plt.subplots(figsize=(W_TOTAL, H_TOTAL))
    ax.set_xlim(0, W_TOTAL)
    ax.set_ylim(0, H_TOTAL)
    ax.axis("off")

    y = H_TOTAL - 0.5
    x_src = 0
    x_cost = x_src + W_SOURCE
    x_time = x_cost + W_COST
    x_pump = x_time + W_TIME
    x_sw = x_pump + W_PUMP
    x_hours = x_sw + W_SW

    header_bg, border = "#34495e", "#dddddd"

    def cell(x, y, w, h, text, bg, fg="black", bold=False, align="center", size=10):
        ax.add_patch(patches.Rectangle((x, y - h), w, h, ec=border, fc=bg))
        ha = {"left": "left", "right": "right"}.get(align, "center")
        cx = x + (0.1 if align == "left" else w - 0.1 if align == "right" else w / 2)
        ax.text(
            cx,
            y - h / 2,
            text,
            ha=ha,
            va="center",
            color=fg,
            fontweight="bold" if bold else "normal",
            fontsize=size,
        )

    # Header
    headers = [
        ("Source", W_SOURCE, "left"),
        ("Cost ($)", W_COST, "center"),
        ("Time (s)", W_TIME, "center"),
        ("Pump", W_PUMP, "center"),
        ("SW", W_SW, "center"),
    ]
    x = 0
    for txt, w, align in headers:
        cell(x, y, w, H_HEADER, txt, header_bg, "white", True, align)
        x += w
    for h in range(24):
        cell(
            x_hours + h * W_HOUR,
            y,
            W_HOUR,
            H_HEADER,
            f"{h+1:02d}",
            header_bg,
            "white",
            True,
            size=8,
        )
    y -= H_HEADER

    # Data rows
    for entry in entries:
        bg_cost = "#d5f5e3" if entry["is_best"] else "#f8f9fa"
        bg_time = "#d5f5e3" if entry["is_fastest"] else "#f8f9fa"

        cell(x_src, y, W_SOURCE, H_SOURCE, entry["label"], "#f8f9fa", align="left")
        ax.add_patch(
            patches.Rectangle(
                (x_src, y - H_SOURCE), 0.08, H_SOURCE, fc=entry["color"], ec="none"
            )
        )
        cell(x_cost, y, W_COST, H_SOURCE, f"{entry['cost']:.2f}", bg_cost, bold=True)
        cell(x_time, y, W_TIME, H_SOURCE, f"{entry['time']:.2f}", bg_time)

        for p in range(3):
            yp = y - p * H_ROW
            cell(x_pump, yp, W_PUMP, H_ROW, f"P{p+1}", "#f8f9fa")
            cell(x_sw, yp, W_SW, H_ROW, str(entry["switches"][p]), "#f8f9fa")

            for h in range(24):
                on = entry["schedule"][h, p] == 1
                bg = "#27ae60" if on else "#ecf0f1"
                ax.add_patch(
                    patches.Rectangle(
                        (x_hours + h * W_HOUR, yp - H_ROW),
                        W_HOUR,
                        H_ROW,
                        ec=border,
                        fc=bg,
                        lw=0.5,
                    )
                )
                if on:
                    ax.text(
                        x_hours + h * W_HOUR + W_HOUR / 2,
                        yp - H_ROW / 2,
                        "\u25cf",
                        ha="center",
                        va="center",
                        color="white",
                        fontsize=10,
                    )

        y -= H_SOURCE

    ax.text(
        0,
        H_TOTAL - 0.25,
        f"Maximum Actuations: {na_max}",
        fontsize=14,
        fontweight="bold",
        color="#2c3e50",
    )

    plt.tight_layout(pad=1.0)
    plt.savefig(output_path, dpi=500, bbox_inches="tight", pad_inches=0.1)
    plt.close()
    print(f"Generated: {output_path}")


def export_csv(data, output_path):
    """Export comparison data to CSV file."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Cost", "Time", "Pump", "SW"])

        for na_max in [1, 2, 3]:
            for entry in data[na_max]:
                for p in range(3):
                    writer.writerow([
                        entry["label"],
                        f"{entry['cost']:.2f}",
                        f"{entry['time']:.2f}",
                        f"P{p+1}",
                        entry["switches"][p],
                    ])

    print(f"Generated: {output_path}")


def main():
    data = discover_sources()
    for na_max in [1, 2, 3]:
        if data[na_max]:
            draw_table(
                na_max, data[na_max], OUTPUT_DIR / f"Figure_{na_max + 6}_comparison_table_a{na_max}.pdf"
            )
    export_csv(data, DATA_DIR / "comparison_table.csv")
    print("Done.")


if __name__ == "__main__":
    main()
