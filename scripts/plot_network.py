#!/usr/bin/env python3
"""Generate plots for the AnyTown case study using WNTR."""

import wntr
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import networkx as nx
from pathlib import Path

# Get the project root directory
script_dir = Path(__file__).parent
project_root = script_dir.parent

# Load the network
wn = wntr.network.WaterNetworkModel(project_root / 'networks/any-town.inp')

def plot_network(output_path: Path) -> None:
    # Create figure with appropriate size for single column
    fig, ax = plt.subplots(figsize=(5, 5), dpi=300)

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

    # Define colors
    junction_color = '#2E86AB'  # Blue
    tank_color = '#A23B72'      # Magenta/Purple
    reservoir_color = '#F18F01' # Orange
    pipe_color = '#555555'      # Dark gray

    # Draw edges (pipes and pumps)
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color=pipe_color, width=1.5, alpha=0.8)

    # Draw nodes by type with different colors and larger sizes
    nx.draw_networkx_nodes(G, pos, nodelist=junctions, ax=ax,
                           node_color=junction_color, node_size=350, alpha=0.95)
    nx.draw_networkx_nodes(G, pos, nodelist=tanks, ax=ax,
                           node_color=tank_color, node_size=500,
                           node_shape='s', alpha=0.95)  # Square for tanks
    nx.draw_networkx_nodes(G, pos, nodelist=reservoirs, ax=ax,
                           node_color=reservoir_color, node_size=550,
                           node_shape='^', alpha=0.95)  # Triangle for reservoir

    # Draw labels inside nodes with white color
    for node, (x, y) in pos.items():
        ax.annotate(node, (x, y), fontsize=6, fontweight='bold',
                    color='white', ha='center', va='center')

    # Create custom legend with matching colors
    junction_patch = mpatches.Patch(color=junction_color, label='Junctions')
    tank_patch = mpatches.Patch(color=tank_color, label='Tanks')
    reservoir_patch = mpatches.Patch(color=reservoir_color, label='Reservoir')
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

    plt.savefig(output_path, dpi=300, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)

    # Crop the image to remove any remaining white borders
    from PIL import Image
    img = Image.open(output_path)
    bbox = img.getbbox()
    if bbox:
        img_cropped = img.crop(bbox)
        img_cropped.save(output_path)
        print(f"Cropped image saved to {output_path}")
    else:
        print(f"No cropping needed, saved to {output_path}")


def plot_energy_cost_by_hour(output_path: Path, pattern_name: str = "PRICES") -> None:
    pattern = wn.get_pattern(pattern_name)
    if pattern is None:
        raise RuntimeError(f"Pattern '{pattern_name}' not found in network.")

    prices = [float(x) for x in pattern.multipliers]
    hours = list(range(1, len(prices) + 1))

    fig, ax = plt.subplots(figsize=(5, 2.6), dpi=300)
    ax.bar(hours, prices, color="#2E86AB", width=0.9)
    ax.set_xlim(0.5, len(prices) + 0.5)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Energy price")
    ax.grid(True, axis="y", linestyle="--", linewidth=0.6, alpha=0.5)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)


def main() -> None:
    figures_dir = project_root / "article/figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    plot_network(figures_dir / "anytown_network.png")
    plot_energy_cost_by_hour(figures_dir / "anytown_energy_cost.png")


if __name__ == "__main__":
    main()
