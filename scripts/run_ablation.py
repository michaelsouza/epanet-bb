#!/usr/bin/env python3
"""
EPANET-BB Ablation Study Experiments

This script runs a series of experiments to evaluate the impact of different
B&B features on performance and solution quality.

Environment Variables:
    H: Maximum hours for simulation (default: 24).
    A: Maximum pump actuations allowed (default: 2).
    L: B&B tree level (default: 6).
    S: Synchronization interval (default: 7000).
    NP: Number of MPI processes (default: 15).

Usage:
    python3 run_ablation.py
"""

import os
import subprocess
import time
import re
import multiprocessing
from datetime import datetime
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich import box

# Configuration
H = os.environ.get("H", "24")
A = os.environ.get("A", "1")
L = os.environ.get("L", "8")
S = os.environ.get("S", "32768")
NP = os.environ.get("NP", "128")
BINARY = "./build/run-epanet3-bb"
LOG_DIR = "logs_ablation"

os.makedirs(LOG_DIR, exist_ok=True)
console = Console()


# Experiment Definitions
ABLATION_EXPERIMENTS = [
    {"name": "01_baseline", "env": {}, "np": NP},
    {"name": "02_no_snapshots", "env": {"BB_ENABLE_SNAPSHOTS": "0"}, "np": NP},
    {"name": "03_no_cost_pruning", "env": {"BB_ENABLE_COST_PRUNING": "0"}, "np": NP},
    {"name": "04_no_pump_sorting", "env": {"BB_ENABLE_PUMP_SORTING": "0"}, "np": NP},
    {"name": "05_no_task_shuffle", "env": {"BB_ENABLE_TASK_SHUFFLE": "0"}, "np": NP},
    {"name": "06_no_global_sync", "env": {"BB_ENABLE_GLOBAL_SYNC": "0"}, "np": NP},
]

# Baseline is also part of scalability, but we keep it in ablation for clarity
EXPERIMENTS = ABLATION_EXPERIMENTS

# Results table for live display
results_table = Table(
    show_header=True,
    header_style="bold magenta",
    box=box.ROUNDED,
    expand=True,
)
results_table.add_column("ID", justify="center", style="dim")
results_table.add_column("NP", justify="right", style="magenta")
results_table.add_column("Experiment Name", justify="left")
results_table.add_column("Duration", justify="right")
results_table.add_column("Cost", justify="right", style="cyan")
results_table.add_column("Status", justify="left")


def run_experiment(exp, row_index):
    name = exp["name"]
    env_vars = exp["env"]
    log_path = f"{LOG_DIR}/{name}.log"

    # Merge current environment with experiment-specific environment
    current_env = os.environ.copy()
    current_env.update(env_vars)

    exp_np = exp.get("np", NP)
    cmd = ["mpirun", "-n", exp_np, BINARY, "-h", H, "-a", A, "-l", L, "-s", S]

    start_time = time.time()
    start_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Update table to show "Running"
    results_table.columns[3]._cells[row_index] = Text("running...")
    results_table.columns[5]._cells[row_index] = Text("[yellow]In Progress[/yellow]")

    try:
        with open(log_path, "w") as log:
            log.write(f"Experiment: {name}\n")
            log.write(f"Environment: {env_vars}\n")
            log.write(f"Command: {' '.join(cmd)}\n")
            log.write(f"Started at: {start_date}\n\n")
            log.flush()

            process = subprocess.run(
                cmd, stdout=log, stderr=subprocess.STDOUT, env=current_env, check=True
            )

        duration = time.time() - start_time
        end_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(log_path, "a") as log:
            log.write(f"\nFinished at: {end_date}\n")
            log.write(f"Duration: {duration:.2f} seconds\n")

        # Extract cost from log
        cost_str = "N/A"
        with open(log_path, "r") as log:
            content = log.read()
            match = re.search(r"Global best cost:\s*([^\s]+)", content)
            if match:
                cost_str = match.group(1)

        # Update table row
        results_table.columns[3]._cells[row_index] = Text(f"{duration:.2f}s")
        results_table.columns[4]._cells[row_index] = Text(cost_str, style="cyan")
        results_table.columns[5]._cells[row_index] = Text("[green]Done[/green]")

        return True
    except subprocess.CalledProcessError as e:
        results_table.columns[5]._cells[row_index] = Text(
            f"[bold red]Failed ({e.returncode})[/bold red]"
        )
        return False
    except Exception as e:
        results_table.columns[5]._cells[row_index] = Text(f"[bold red]Error[/bold red]")
        return False


def show_header():
    header_text = Text.from_markup(
        f"""
[bold cyan]EPANET-BB Ablation Study[/bold cyan]
[dim]Evaluating performance impact of B&B optimization features[/dim]

[bold]Global Settings:[/bold]
• Simulation Hours (H): [green]{H}[/green]
• Max Actuations (A): [green]{A}[/green]
• Tree Level (L): [green]{L}[/green]
• Sync Interval (S): [green]{S}[/green]
• MPI Processes (NP): [magenta]{NP}[/magenta]
• Binary: [blue]{BINARY}[/blue]
• Log Directory: [blue]{LOG_DIR}[/blue]
    """
    )
    console.print(
        Panel(
            header_text,
            border_style="cyan",
            title="[bold white]Experiment Settings[/bold white]",
        )
    )


def main():
    show_header()

    # Initialize table with experiment rows
    for i, exp in enumerate(EXPERIMENTS):
        results_table.add_row(
            str(i + 1),
            exp.get("np", NP),
            exp["name"],
            "waiting...",
            "...",
            "[dim]Waiting[/dim]",
        )

    with Live(
        results_table,
        console=console,
        refresh_per_second=4,
        vertical_overflow="visible",
    ):
        for i, exp in enumerate(EXPERIMENTS):
            run_experiment(exp, i)

    console.print("\n[bold green]All experiments completed.[/bold green]")


if __name__ == "__main__":
    main()
