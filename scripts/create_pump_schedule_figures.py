#!/usr/bin/env python3
"""
Generate pump schedule visualization figures similar to Paola et al. (2025).
Creates one figure for each value of NA_max (1, 2, 3) showing the pump schedules
from different methods (Costa, Cimorelli, De Paola, and our Proposed method).
"""

import json
import glob
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

# Configuration
OUTPUT_DIR = Path("figures")
OUTPUT_DIR.mkdir(exist_ok=True)

# Colors for different methods (matching the reference figure style)
COLORS = {
    'Costa': '#4472C4',      # Blue
    'Cimorelli': '#ED7D31',  # Orange
    'Paola': '#70AD47',      # Green
    'Proposed': '#9933FF',   # Purple (our method)
}

# Reference data from literature (extracted from outputs/)
REFERENCE_DATA = {
    1: {  # NA_max = 1
        'Costa': {
            'cost': 3916.98,
            'x': [0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0]
        },
        'Cimorelli': {
            'cost': 3634.67,
            'x': [0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
        },
        'Paola': {
            'cost': 3911.52,
            'x': [0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
        }
    },
    2: {  # NA_max = 2
        'Costa': {
            'cost': 3618.59,
            'x': [0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0]  # Placeholder
        },
        'Cimorelli': {
            'cost': 3580.11,
            'x': [0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]  # Placeholder
        },
        'Paola': {
            'cost': 3606.22,
            'x': [0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]  # Placeholder
        }
    },
    3: {  # NA_max = 3
        'Costa': {
            'cost': 3578.67,
            'x': [0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0]  # Placeholder
        },
        'Cimorelli': {
            'cost': 3575.54,
            'x': [0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]  # Placeholder
        },
        'Paola': {
            'cost': 3577.40,
            'x': [0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]  # Placeholder
        }
    }
}


def load_reference_solutions():
    """Load reference solutions from JSON files."""
    refs = {}
    for method in ['Costa2016', 'Cimorelli2020', 'Paola2025']:
        refs[method] = {}
        for a in [1, 2, 3]:
            filepath = f'../outputs/run_{method}_a_{a:02d}.json'
            try:
                with open(filepath) as f:
                    data = json.load(f)
                    refs[method][a] = data
            except FileNotFoundError:
                print(f"Warning: {filepath} not found")
    return refs


def load_proposed_solutions():
    """Load best solutions from our proposed method."""
    proposed = {}
    for a in [1, 2, 3]:
        pattern = f'../outputs/run_a_{a:02d}_h_24_l_08_s_8500_n_14_r_*_best.json'
        files = glob.glob(pattern)

        best_cost = float('inf')
        best_data = None

        for f in files:
            with open(f) as fp:
                data = json.load(fp)
                if data['best_cost'] < best_cost:
                    best_cost = data['best_cost']
                    best_data = data

        proposed[a] = best_data
    return proposed


def x_to_pump_schedules(x, n_pumps=3):
    """Convert x vector to pump schedules (hours 1-24)."""
    schedules = []
    for p in range(n_pumps):
        # Extract every n_pumps-th element starting at p, skip hour 0
        pump_schedule = x[p::n_pumps][1:25]  # hours 1-24
        schedules.append(pump_schedule)
    return schedules


def count_switches(schedule):
    """Count number of switches (ON/OFF transitions) in a schedule."""
    switches = 0
    for i in range(1, len(schedule)):
        if schedule[i] != schedule[i-1]:
            switches += 1
    return switches


def create_schedule_figure(na_max, refs, proposed, output_path):
    """Create a pump schedule visualization figure for a given NA_max."""

    # Methods to display (in order)
    methods = [
        ('Costa2016', 'Costa et al. (2016)', COLORS['Costa']),
        ('Cimorelli2020', 'Cimorelli et al. (2020)', COLORS['Cimorelli']),
        ('Paola2025', 'De Paola et al. (2025)', COLORS['Paola']),
        ('Proposed', 'Proposed Model', COLORS['Proposed']),
    ]

    n_methods = len(methods)
    n_pumps = 3
    hours = list(range(1, 25))

    # Figure setup
    fig, axes = plt.subplots(n_methods, 1, figsize=(14, 2.5 * n_methods),
                             gridspec_kw={'hspace': 0.4})

    if n_methods == 1:
        axes = [axes]

    for idx, (method_key, method_name, color) in enumerate(methods):
        ax = axes[idx]

        # Get data
        if method_key == 'Proposed':
            data = proposed[na_max]
        else:
            data = refs[method_key].get(na_max)

        if data is None:
            ax.text(0.5, 0.5, f"No data for {method_name}",
                   ha='center', va='center', transform=ax.transAxes)
            continue

        cost = data['best_cost']
        x = data['best_x']
        schedules = x_to_pump_schedules(x)

        # Calculate total switches
        total_switches = sum(count_switches(s) for s in schedules)

        # Create table-like visualization
        cell_width = 1
        cell_height = 0.8

        # Draw grid and cells
        for pump_idx, schedule in enumerate(schedules):
            y_base = (n_pumps - 1 - pump_idx) * cell_height

            for hour_idx, is_on in enumerate(schedule):
                x_pos = hour_idx * cell_width

                if is_on:
                    rect = mpatches.FancyBboxPatch(
                        (x_pos + 0.05, y_base + 0.05),
                        cell_width - 0.1, cell_height - 0.1,
                        boxstyle="round,pad=0.02",
                        facecolor=color,
                        edgecolor='none',
                        alpha=0.9
                    )
                    ax.add_patch(rect)
                    # Add marker
                    ax.plot(x_pos + cell_width/2, y_base + cell_height/2,
                           marker='x' if method_key in ['Costa2016'] else '+' if method_key == 'Cimorelli2020' else 'o',
                           color='white', markersize=6, markeredgewidth=1.5)

                # Draw cell border
                rect_border = mpatches.Rectangle(
                    (x_pos, y_base), cell_width, cell_height,
                    fill=False, edgecolor='lightgray', linewidth=0.5
                )
                ax.add_patch(rect_border)

        # Add pump labels on the left
        for pump_idx in range(n_pumps):
            y_pos = (n_pumps - 1 - pump_idx) * cell_height + cell_height/2
            ax.text(-0.5, y_pos, f'P{pump_idx + 1}', ha='right', va='center',
                   fontsize=10, fontweight='bold')

        # Add switches count on the right
        for pump_idx, schedule in enumerate(schedules):
            y_pos = (n_pumps - 1 - pump_idx) * cell_height + cell_height/2
            switches = count_switches(schedule)
            ax.text(24.5, y_pos, str(switches), ha='left', va='center',
                   fontsize=9, color='gray')

        # Set axis properties
        ax.set_xlim(-1.5, 25.5)
        ax.set_ylim(-0.3, n_pumps * cell_height + 0.3)
        ax.set_aspect('equal')

        # X-axis (hours)
        ax.set_xticks([i + 0.5 for i in range(24)])
        ax.set_xticklabels([str(i) for i in range(1, 25)], fontsize=8)
        ax.tick_params(axis='x', length=0)

        # Remove y-axis
        ax.set_yticks([])
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_visible(False)

        # Title with cost and method name
        ax.set_title(f'{method_name}  |  Cost: ${cost:,.2f}  |  Total Switches: {total_switches}',
                    fontsize=11, fontweight='bold', loc='left', pad=10)

    # Add hour label at bottom
    fig.text(0.5, 0.02, 'Hour', ha='center', fontsize=11)

    # Main title
    fig.suptitle(f'Pump Schedules Comparison - NA$_{{max}}$ = {na_max}',
                fontsize=14, fontweight='bold', y=0.98)

    # Add legend
    legend_elements = [
        mpatches.Patch(facecolor=COLORS['Costa'], label='Costa et al. (2016)'),
        mpatches.Patch(facecolor=COLORS['Cimorelli'], label='Cimorelli et al. (2020)'),
        mpatches.Patch(facecolor=COLORS['Paola'], label='De Paola et al. (2025)'),
        mpatches.Patch(facecolor=COLORS['Proposed'], label='Proposed Model'),
    ]
    fig.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(0.98, 0.96),
              fontsize=9, frameon=True)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Saved: {output_path}")


def create_combined_table_figure(refs, proposed, output_path):
    """Create a single combined figure with all NA_max values, similar to the reference."""

    na_max_values = [3, 2, 1]  # Order: 6, 4, 2 in original (we use 3, 2, 1)
    methods = [
        ('Costa2016', 'Costa et al.\n(2016)', COLORS['Costa']),
        ('Cimorelli2020', 'Cimorelli et al.\n(2020)', COLORS['Cimorelli']),
        ('Paola2025', 'De Paola et al.\n(2025)', COLORS['Paola']),
        ('Proposed', 'Proposed\nModel', COLORS['Proposed']),
    ]

    n_pumps = 3
    n_methods = len(methods)
    n_na_values = len(na_max_values)

    # Calculate dimensions
    cell_width = 0.8
    cell_height = 0.5
    row_height = n_pumps * cell_height
    section_gap = 0.8

    total_height = n_na_values * (n_methods * row_height + (n_methods - 1) * 0.1) + (n_na_values - 1) * section_gap

    fig_width = 16
    fig_height = total_height * 0.6 + 2

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    y_offset = total_height

    for na_idx, na_max in enumerate(na_max_values):
        # Section header
        section_y = y_offset

        for method_idx, (method_key, method_name, color) in enumerate(methods):
            # Get data
            if method_key == 'Proposed':
                data = proposed.get(na_max)
            else:
                data = refs.get(method_key, {}).get(na_max)

            if data is None:
                continue

            cost = data['best_cost']
            x = data['best_x']
            schedules = x_to_pump_schedules(x)

            method_y = y_offset - (method_idx + 1) * row_height - method_idx * 0.1

            # Draw pump schedules
            for pump_idx, schedule in enumerate(schedules):
                pump_y = method_y + (n_pumps - 1 - pump_idx) * cell_height

                for hour_idx, is_on in enumerate(schedule):
                    x_pos = 4 + hour_idx * cell_width

                    if is_on:
                        rect = mpatches.FancyBboxPatch(
                            (x_pos + 0.02, pump_y + 0.02),
                            cell_width - 0.04, cell_height - 0.04,
                            boxstyle="round,pad=0.01",
                            facecolor=color,
                            edgecolor='none',
                            alpha=0.9
                        )
                        ax.add_patch(rect)

                        # Marker
                        marker = 'x' if 'Costa' in method_key else '+' if 'Cimorelli' in method_key else 'o'
                        ax.plot(x_pos + cell_width/2, pump_y + cell_height/2,
                               marker=marker, color='white', markersize=4, markeredgewidth=1)

                    # Cell border
                    rect_border = mpatches.Rectangle(
                        (x_pos, pump_y), cell_width, cell_height,
                        fill=False, edgecolor='lightgray', linewidth=0.3
                    )
                    ax.add_patch(rect_border)

                # Pump label
                ax.text(3.8, pump_y + cell_height/2, f'P{pump_idx + 1}',
                       ha='right', va='center', fontsize=7)

                # Switches count
                switches = count_switches(schedule)
                ax.text(4 + 24 * cell_width + 0.3, pump_y + cell_height/2,
                       str(switches), ha='left', va='center', fontsize=7, color='gray')

            # Method name and cost
            method_center_y = method_y + row_height / 2
            ax.text(1.5, method_center_y, method_name, ha='center', va='center', fontsize=8)
            ax.text(3.0, method_center_y, f'${cost:,.2f}', ha='center', va='center', fontsize=8)

        # NA_max label
        na_section_center = y_offset - (n_methods * row_height + (n_methods - 1) * 0.1) / 2
        ax.text(0.3, na_section_center, f'{na_max}', ha='center', va='center',
               fontsize=12, fontweight='bold')

        y_offset -= n_methods * row_height + (n_methods - 1) * 0.1 + section_gap

    # Column headers
    header_y = total_height + 0.5
    ax.text(0.3, header_y, 'NA$_{max}$', ha='center', va='center', fontsize=9, fontweight='bold')
    ax.text(1.5, header_y, 'Model', ha='center', va='center', fontsize=9, fontweight='bold')
    ax.text(3.0, header_y, 'Cost\n[$/day]', ha='center', va='center', fontsize=9, fontweight='bold')
    ax.text(3.8, header_y, 'Pump', ha='right', va='center', fontsize=9, fontweight='bold')

    # Hour labels
    for h in range(1, 25):
        ax.text(4 + (h - 0.5) * cell_width, header_y, str(h), ha='center', va='center', fontsize=7)

    ax.text(4 + 12 * cell_width, header_y + 0.6, 'Hour', ha='center', va='center', fontsize=9, fontweight='bold')
    ax.text(4 + 24 * cell_width + 0.5, header_y, 'SW', ha='center', va='center', fontsize=8, fontweight='bold')

    # Set limits and remove axes
    ax.set_xlim(-0.5, 4 + 24 * cell_width + 1.5)
    ax.set_ylim(-1, total_height + 1.5)
    ax.set_aspect('equal')
    ax.axis('off')

    # Title
    fig.suptitle('Comparison of Pump Schedules - AnyTown Modified Network',
                fontsize=14, fontweight='bold', y=0.98)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Saved: {output_path}")


def main():
    # Load data
    print("Loading reference solutions...")
    refs = load_reference_solutions()

    print("Loading proposed solutions...")
    proposed = load_proposed_solutions()

    # Print summary
    print("\n=== Solutions Summary ===")
    for a in [1, 2, 3]:
        print(f"\nNA_max = {a}:")
        for method, data_dict in refs.items():
            if a in data_dict:
                print(f"  {method}: ${data_dict[a]['best_cost']:,.2f}")
        if a in proposed and proposed[a]:
            print(f"  Proposed: ${proposed[a]['best_cost']:,.2f}")

    # Generate individual figures for each NA_max
    print("\n=== Generating Figures ===")
    for na_max in [1, 2, 3]:
        output_path = OUTPUT_DIR / f'pump_schedule_na{na_max}.png'
        create_schedule_figure(na_max, refs, proposed, output_path)

    # Generate combined table figure
    combined_path = OUTPUT_DIR / 'pump_schedule_comparison.png'
    create_combined_table_figure(refs, proposed, combined_path)

    print("\nDone!")


if __name__ == '__main__':
    main()
