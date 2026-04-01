#!/usr/bin/env python3
"""Generate Figure 1 (two-level schedule representation) as a vector PDF."""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

mpl.rcParams.update(
    {
        "font.family": "serif",
        "mathtext.fontset": "stix",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "paper/figures/Figure_1_two_level_diagram.pdf"


def main() -> None:
    fig_w, fig_h = 300, 160
    fig, ax = plt.subplots(figsize=(fig_w / 72, fig_h / 72))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(fig_h, 0)
    ax.axis("off")

    left = 86
    top = 22
    cell_w = 20
    y_cell_h = 20
    x_cell_h = 18
    gap = 2

    hour_y = top - 10
    for i, label in enumerate(["1", "2", "3", "4", "5", "6"]):
        x = left + i * (cell_w + gap) + cell_w / 2
        ax.text(
            x,
            hour_y,
            label,
            ha="center",
            va="center",
            fontsize=9,
            style="italic",
            color="#555",
        )

    ax.text(
        70,
        hour_y,
        r"$h$",
        ha="right",
        va="center",
        fontsize=12,
        color="#333",
    )

    ax.text(
        70,
        top + y_cell_h / 2,
        r"$y_h$",
        ha="right",
        va="center",
        fontsize=12,
        color="#333",
    )
    for i, val in enumerate([2, 3, 3, 2, 1, 0]):
        x = left + i * (cell_w + gap)
        ax.add_patch(
            Rectangle(
                (x, top),
                cell_w,
                y_cell_h,
                facecolor="#e0e0f0",
                edgecolor="#777",
                linewidth=1.0,
            )
        )
        ax.text(
            x + cell_w / 2,
            top + y_cell_h / 2,
            str(val),
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color="#333",
        )

    arrow_x = left + 2.5 * (cell_w + gap)
    ax.text(arrow_x, 60, "↓", ha="center", va="center", fontsize=20, color="#444")
    ax.text(
        arrow_x,
        78,
        r"$M(y_h, x_{h-1}, R)$",
        ha="center",
        va="center",
        fontsize=12,
        color="#444",
    )

    row_top = 92
    rows = [
        [1, 1, 1, 1, 1, 0],
        [1, 1, 1, 1, 0, 0],
        [0, 1, 1, 0, 0, 0],
    ]
    labels = [r"$x_{1,h}$", r"$x_{2,h}$", r"$x_{3,h}$"]
    for r, (label, row) in enumerate(zip(labels, rows)):
        y = row_top + r * (x_cell_h + gap)
        ax.text(
            70,
            y + x_cell_h / 2,
            label,
            ha="right",
            va="center",
            fontsize=13,
            style="italic",
            color="#555",
        )
        for i, on in enumerate(row):
            x = left + i * (cell_w + gap)
            face = "#404040" if on else "#f0f0f0"
            text = "white" if on else "#aaaaaa"
            ax.add_patch(
                Rectangle(
                    (x, y),
                    cell_w,
                    x_cell_h,
                    facecolor=face,
                    edgecolor="#777",
                    linewidth=1.0,
                )
            )
            ax.text(
                x + cell_w / 2,
                y + x_cell_h / 2,
                str(on),
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold",
                color=text,
            )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, bbox_inches="tight", pad_inches=0.01)
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
