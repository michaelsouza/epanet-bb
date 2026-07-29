#!/usr/bin/env python3
"""Generate Figure 2 (tree decomposition diagram) as a vector PDF."""

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Polygon

mpl.rcParams.update(
    {
        "font.family": "serif",
        "mathtext.fontset": "stix",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "paper/figures/Figure_2_tree_decomposition.pdf"
RANK_STYLES = [
    {"face": "#111111", "hatch": None, "label": "Rank 0"},
    {"face": "#7a7a7a", "hatch": "///", "label": "Rank 1"},
    {"face": "#d9d9d9", "hatch": "...", "label": "Rank 2"},
]


def draw_node(
    ax,
    x: float,
    y: float,
    label: str,
    radius: float,
    edge: str = "#333",
    face: str = "white",
    size: int = 10,
) -> None:
    ax.add_patch(Circle((x, y), radius, facecolor=face, edgecolor=edge, linewidth=1.5))
    ax.text(x, y, label, ha="center", va="center", fontsize=size, color="#333")


def main(output: Path = OUTPUT) -> None:
    width, height = 480, 260
    fig, ax = plt.subplots(figsize=(width / 72, height / 72))
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis("off")

    center_x = width / 2
    root_y = 30
    node_r = 10
    small_r = 9
    level_h = 55

    draw_node(ax, center_x, root_y, "root", 15, size=9)
    ax.text(
        width - 25,
        root_y,
        "h=0",
        ha="center",
        va="center",
        fontsize=10,
        style="italic",
        color="#333",
    )
    ax.plot([30, width - 30], [root_y + 27, root_y + 27], color="#333", linewidth=1)

    level1_y = root_y + level_h
    level1_x = [center_x + (i - 1.5) * 90 for i in range(4)]
    for i, x in enumerate(level1_x):
        ax.plot(
            [center_x, x], [root_y + 14, level1_y - node_r], color="#555", linewidth=1
        )
        draw_node(ax, x, level1_y, str(i), node_r)
    ax.text(
        width - 25,
        level1_y,
        "h=1",
        ha="center",
        va="center",
        fontsize=10,
        style="italic",
        color="#333",
    )
    ax.plot(
        [30, width - 30],
        [level1_y + node_r + 15, level1_y + node_r + 15],
        color="#333",
        linewidth=1,
    )

    level2_y = root_y + 2 * level_h
    nodes = []
    task_index = 0
    for parent_x in level1_x:
        for child in range(4):
            x = parent_x + (child - 1.5) * 22
            rank = task_index % 3
            nodes.append((x, rank, child))
            ax.plot(
                [parent_x, x],
                [level1_y + node_r, level2_y - small_r],
                color="#888",
                linewidth=1,
            )
            draw_node(ax, x, level2_y, str(child), small_r, edge="#555", size=8)
            task_index += 1
    ax.text(
        width - 25,
        level2_y,
        "h=d",
        ha="center",
        va="center",
        fontsize=10,
        style="italic",
        color="#333",
    )

    subtree_y = level2_y + small_r + 2
    subtree_h = 40
    for x, rank, _ in nodes:
        ax.add_patch(
            Polygon(
                [
                    [x, subtree_y],
                    [x - 9, subtree_y + subtree_h],
                    [x + 9, subtree_y + subtree_h],
                ],
                closed=True,
                facecolor=RANK_STYLES[rank]["face"],
                edgecolor="#222222",
                hatch=RANK_STYLES[rank]["hatch"],
                linewidth=1,
            )
        )
        dot_y = subtree_y + subtree_h * 0.55
        for offset in (-5, 0, 5):
            ax.add_patch(
                Circle((x, dot_y + offset), 1.5, facecolor="white", edgecolor="white")
            )

    bottom_y = subtree_y + subtree_h + 15
    ax.text(
        center_x,
        bottom_y + 20,
        "Subtree Decomposition",
        ha="center",
        va="center",
        fontsize=10,
        style="italic",
        color="#555",
    )

    legend_y = bottom_y + 35
    legend_start = center_x - 100
    for rank in range(3):
        x = legend_start + rank * 75
        ax.add_patch(
            FancyBboxPatch(
                (x - 8, legend_y - 6),
                12,
                12,
                boxstyle="round,pad=0,rounding_size=2",
                facecolor=RANK_STYLES[rank]["face"],
                edgecolor="#222222",
                hatch=RANK_STYLES[rank]["hatch"],
                linewidth=1,
            )
        )
        ax.text(
            x + 10,
            legend_y + 2,
            RANK_STYLES[rank]["label"],
            ha="left",
            va="center",
            fontsize=10,
            color="#333",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight", pad_inches=0.01)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    main(arguments.output.absolute())
