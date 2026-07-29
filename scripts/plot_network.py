#!/usr/bin/env python3
"""Generate plots for a water-network case study using WNTR."""

import argparse
import wntr
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import networkx as nx
from pathlib import Path

PROJECT_ROOT = Path(__file__).absolute().parents[1]


def plot_network(wn: wntr.network.WaterNetworkModel, output_path: Path) -> None:
    # Create figure with appropriate size for single column
    fig, ax = plt.subplots(figsize=(5, 5), dpi=500)


    # Get the network graph
    G = wn.to_graph()

    # Get node positions from coordinates
    pos = {}
    for name, node in wn.nodes():
        pos[name] = (node.coordinates[0], node.coordinates[1])

    # Separate nodes by type
    junctions = [name for name, node in wn.junctions()]
    tanks = [name for name, node in wn.tanks()]
    reservoirs = [name for name, node in wn.reservoirs()]

    # Use grayscale plus distinct shapes so the figure remains legible in black and white.
    junction_face = '#f2f2f2'
    tank_face = '#9e9e9e'
    reservoir_face = '#222222'
    pipe_color = '#666666'
    edge_color = '#222222'

    # Draw edges (pipes and pumps)
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color=pipe_color, width=1.5, alpha=0.9)

    # Draw nodes by type with different colors and larger sizes
    nx.draw_networkx_nodes(G, pos, nodelist=junctions, ax=ax,
                           node_color=junction_face, edgecolors=edge_color,
                           linewidths=1.2, node_size=350, alpha=1.0)
    nx.draw_networkx_nodes(G, pos, nodelist=tanks, ax=ax,
                           node_color=tank_face, edgecolors=edge_color,
                           linewidths=1.2, node_size=500,
                           node_shape='s', alpha=1.0)  # Square for tanks
    nx.draw_networkx_nodes(G, pos, nodelist=reservoirs, ax=ax,
                           node_color=reservoir_face, edgecolors=edge_color,
                           linewidths=1.2, node_size=550,
                           node_shape='^', alpha=1.0)  # Triangle for reservoir

    # Draw labels inside nodes with colors chosen for grayscale contrast.
    for node, (x, y) in pos.items():
        text_color = 'white' if node in tanks or node in reservoirs else '#222222'
        ax.annotate(node, (x, y), fontsize=6, fontweight='bold',
                    color=text_color, ha='center', va='center')

    # Create custom legend with matching grayscale fills and outlines.
    junction_patch = mpatches.Patch(facecolor=junction_face, edgecolor=edge_color, label='Junctions')
    tank_patch = mpatches.Patch(facecolor=tank_face, edgecolor=edge_color, label='Tanks')
    reservoir_patch = mpatches.Patch(facecolor=reservoir_face, edgecolor=edge_color, label='Reservoir')
    pipe_line = Line2D([0], [0], color=pipe_color, linewidth=1.5, label='Pipes')

    ax.legend(
        handles=[junction_patch, tank_patch, reservoir_patch, pipe_line],
        loc='upper right',
        fontsize=7,
        framealpha=0.95
    )

    # Remove axes for cleaner look
    ax.set_axis_off()

    # Set equal aspect ratio
    ax.set_aspect('equal')

    plt.tight_layout()

    plt.savefig(output_path, dpi=500, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)

    if output_path.suffix.lower() in {".png", ".tif", ".tiff"}:
        # Crop raster outputs to remove any remaining white borders.
        from PIL import Image

        img = Image.open(output_path)
        bbox = img.getbbox()
        if bbox:
            img_cropped = img.crop(bbox)
            img_cropped.save(output_path, dpi=(500, 500))
            print(f"Cropped image saved to {output_path}")
        else:
            print(f"No cropping needed, saved to {output_path}")
    else:
        print(f"Saved vector figure to {output_path}")


def plot_energy_cost_by_hour(
    wn: wntr.network.WaterNetworkModel,
    output_path: Path,
    pattern_name: str = "PRICES",
) -> None:
    pattern = wn.get_pattern(pattern_name)
    if pattern is None:
        raise RuntimeError(f"Pattern '{pattern_name}' not found in network.")

    prices = [float(x) for x in pattern.multipliers]
    hours = list(range(1, len(prices) + 1))

    fig, ax = plt.subplots(figsize=(5, 2.7), dpi=500)
    ax.bar(
        hours,
        prices,
        color="#8c8c8c",
        edgecolor="#222222",
        linewidth=0.8,
        width=0.9,
    )
    ax.set_xlim(0.5, len(prices) + 0.5)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Energy price")
    ax.grid(True, axis="y", linestyle="--", linewidth=0.6, alpha=0.5, color="#bdbdbd")
    plt.tight_layout()
    plt.savefig(output_path, dpi=500, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "networks" / "any-town.inp",
    )
    parser.add_argument(
        "--network-output",
        type=Path,
        default=PROJECT_ROOT / "paper" / "figures" / "Figure_3_anytown_network.pdf",
    )
    parser.add_argument(
        "--energy-output",
        type=Path,
        default=PROJECT_ROOT / "paper" / "figures" / "Figure_4_anytown_energy_cost.pdf",
    )
    arguments = parser.parse_args()

    input_path = arguments.input.expanduser().absolute()
    network_output = arguments.network_output.expanduser().absolute()
    energy_output = arguments.energy_output.expanduser().absolute()
    network_output.parent.mkdir(parents=True, exist_ok=True)
    energy_output.parent.mkdir(parents=True, exist_ok=True)

    wn = wntr.network.WaterNetworkModel(input_path)
    plot_network(wn, network_output)
    plot_energy_cost_by_hour(wn, energy_output)


if __name__ == "__main__":
    main()
