#!/usr/bin/env python3
"""
EPANET-BB Parameter Optimization Script

This script uses Optuna to optimize the hyperparameters of the Branch-and-Bound (B&B)
pump scheduling algorithm. It performs exhaustive search over all combinations of
MPI ranks (np), B&B tree level, and synchronization interval to minimize execution
time while maintaining hydraulic constraints. Uses BruteForceSampler to ensure each
configuration is tested exactly once.

Environment Variables:
    H: Maximum hours for simulation (default: 16).
    A: Maximum pump actuations allowed (default: 2).
    BINARY: Path to the optimizer executable (default: ./build/run-epanet3-bb).
    TIMEOUT: Initial timeout for the first trial (default: 120s).
    TIMEOUT_MULTIPLIER: Scaling factor for adaptive timeout (default: 1.1).
    NP_LIST: Comma-separated list of MPI ranks to try (overrides auto-generation).
    NP_MIN: Minimum MPI ranks, powers of 2 start from here (default: 8).
    NP_MAX: Maximum MPI ranks (default: cpu_count).

Usage Examples:
    Basic usage with default settings (200 trials):
        python3 run_tuning.py

    Run with custom number of trials:
        python3 run_tuning.py --n-trials 100

    Set simulation parameters via environment variables:
        H=48 A=3 python3 run_tuning.py --n-trials 150

    Adjust timeout settings for longer-running simulations:
        TIMEOUT=1200 TIMEOUT_MULTIPLIER=1.5 python3 run_tuning.py

    Complete example with all parameters:
        H=24 A=2 TIMEOUT=50 TIMEOUT_MULTIPLIER=1.25 python3 run_tuning.py --n-trials 200

    Run within virtual environment:
        source .venv/bin/activate
        python3 run_tuning.py --n-trials 100

Output:
    - Live progress display with rich console output
    - Results saved to tuning_results.csv
    - Individual trial logs in logs_tuning/ directory
"""

import os
import subprocess
import time
import csv
import re
import multiprocessing
import argparse

try:
    import optuna
    import numpy as np
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "Missing Python dependencies. Activate a virtual environment and run "
        "`pip install -r requirements.txt`."
    ) from exc

from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich import box

# Configuration
H = os.environ.get("H", "16")
A = os.environ.get("A", "2")
BINARY = os.environ.get("BINARY", "./build/run-epanet3-bb")
LOG_DIR = "logs_tuning"
CSV_FILE = "tuning_results.csv"
INITIAL_TIMEOUT = int(os.environ.get("TIMEOUT", "120"))
TIMEOUT_MULTIPLIER = float(os.environ.get("TIMEOUT_MULTIPLIER", "1.1"))
N_TRIALS = int(os.environ.get("N_TRIALS", "1000"))  # BruteForceSampler stops when exhausted

# Optimization parameter ranges
LEVEL_MIN = 8
LEVEL_MAX = 10
# Sync intervals as powers of 2: 2^10 to 2^16
SYNC_INTERVALS = [2**i for i in range(10, 17)]  # [1024, 2048, 4096, 8192, 16384, 32768, 65536]


def get_possible_nps():
    """
    Generate a list of possible MPI rank counts using powers of 2.

    Powers of 2 are optimal for B&B tree decomposition and MPI collectives.
    """
    cpu_count = multiprocessing.cpu_count()
    np_list_env = os.environ.get("NP_LIST")
    if np_list_env:
        parsed = []
        for item in np_list_env.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError:
                raise ValueError(f"Invalid NP_LIST value: {item!r}")
            if value > 0:
                parsed.append(value)
        if not parsed:
            raise ValueError("NP_LIST did not contain any positive integers.")
        return np.array(sorted(set(parsed)), dtype=int)

    np_min = int(os.environ.get("NP_MIN", 8))
    np_max = int(os.environ.get("NP_MAX", cpu_count))

    nps = []
    power = 1
    while power <= np_max:
        if power >= np_min:
            nps.append(power)
        power *= 2

    if not nps:
        nps = [np_max]

    return np.array(nps, dtype=int)


POSSIBLE_NPS = get_possible_nps().tolist()


os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs("outputs", exist_ok=True)
console = Console()

results_rows = []
live_view = None


def build_results_table(rows):
    table = Table(
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
        expand=True,
    )
    table.add_column("Trial", justify="center", style="dim")
    table.add_column("NP", justify="right")
    table.add_column("Level", justify="right")
    table.add_column("Sync", justify="right")
    table.add_column("Timeout", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Cost", justify="right", style="cyan")
    table.add_column("Status", justify="left")

    for row in rows:
        table.add_row(
            row["trial"],
            row["np"],
            row["level"],
            row["sync"],
            row["timeout"],
            row["duration"],
            row["cost"],
            row["status"],
        )
    return table


def update_live_table():
    if live_view is None:
        return
    live_view.update(build_results_table(results_rows))


def objective(trial):
    """
    Optuna objective function to minimize execution time.
    """
    np_val = trial.suggest_categorical("np", POSSIBLE_NPS)
    level = trial.suggest_int("level", LEVEL_MIN, LEVEL_MAX)
    sync_interval = trial.suggest_categorical("sync_interval", SYNC_INTERVALS)

    # Adaptive timeout: use best execution time found so far
    try:
        best_value = trial.study.best_value
        current_timeout = best_value * TIMEOUT_MULTIPLIER
    except ValueError:
        current_timeout = INITIAL_TIMEOUT

    # Add placeholder row for current trial
    row = {
        "trial": str(trial.number),
        "np": str(np_val),
        "level": str(level),
        "sync": str(sync_interval),
        "timeout": f"{current_timeout:.1f}s",
        "duration": "running...",
        "cost": "...",
        "status": Text.from_markup("[yellow]In Progress[/yellow]"),
    }
    results_rows.append(row)
    update_live_table()

    log_path = (
        f"{LOG_DIR}/trial_{trial.number}_np{np_val}_l{level}_s{sync_interval}.log"
    )
    cmd = [
        "mpirun",
        "-n",
        str(np_val),
        BINARY,
        "-h",
        H,
        "-a",
        A,
        "-l",
        str(level),
        "-s",
        str(sync_interval),
    ]

    start = time.time()
    status = ""
    duration_str = ""
    cost_str = "N/A"
    row_index = len(results_rows) - 1

    try:
        with open(log_path, "w") as log:
            subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=current_timeout,
            )
        duration = time.time() - start
        duration_str = f"{duration:.2f}s"
        status = "[green]Done[/green]"

        # Extract cost
        if os.path.exists(log_path):
            with open(log_path) as log:
                content = log.read()
                match = re.search(r"Global best cost:\s*([^\s]+)", content)
                if match:
                    cost_str = match.group(1)

        # Save to CSV
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([np_val, level, sync_interval, f"{duration:.4f}", cost_str])

        # Update table row
        results_rows[row_index]["duration"] = duration_str
        results_rows[row_index]["cost"] = cost_str
        results_rows[row_index]["status"] = Text.from_markup(status)
        update_live_table()

        return duration

    except subprocess.TimeoutExpired:
        # Handle execution timeout: record partial duration and update table status
        duration = time.time() - start
        status = "[red]Timeout[/red]"
        duration_str = f"{duration:.2f}s"
        results_rows[row_index]["duration"] = duration_str
        results_rows[row_index]["status"] = Text.from_markup(status)
        update_live_table()
        return current_timeout * 2
    except subprocess.CalledProcessError as e:
        # Handle cases where the subprocess returns a non-zero exit code
        status = f"[bold red]Failed ({e.returncode})[/bold red]"
        results_rows[row_index]["status"] = Text.from_markup(status)
        update_live_table()
        return current_timeout * 3
    except Exception as e:
        # Catch-all for any other unexpected runtime errors
        status = f"[bold red]Error[/bold red]"
        results_rows[row_index]["status"] = Text.from_markup(status)
        update_live_table()
        return current_timeout * 4


def show_header():
    header_text = Text.from_markup(
        f"""
[bold cyan]EPANET-BB Parameter Optimizer[/bold cyan]
[dim]Optimizing Branch-and-Bound pump scheduling performance[/dim]

[bold]Configuration:[/bold]
• Simulation Hours (H): [green]{H}[/green]
• Max Actuations (A): [green]{A}[/green]
• Binary: [blue]{BINARY}[/blue]
• Initial Timeout: [yellow]{INITIAL_TIMEOUT}s[/yellow]
• Multiplier: [yellow]{TIMEOUT_MULTIPLIER}x[/yellow]
• NP Choices: [magenta]{', '.join(map(str, POSSIBLE_NPS))}[/magenta]
• Level Range: [cyan]{LEVEL_MIN}-{LEVEL_MAX}[/cyan]
• Sync Intervals: [cyan]{', '.join(map(str, SYNC_INTERVALS))}[/cyan]
• Total Configs: [bold yellow]{len(POSSIBLE_NPS) * (LEVEL_MAX - LEVEL_MIN + 1) * len(SYNC_INTERVALS)}[/bold yellow] (exhaustive search)
    """
    )
    console.print(
        Panel(
            header_text, border_style="cyan", title="[bold white]Settings[/bold white]"
        )
    )


def main():
    """
    Main entry point for the optimization study.
    """
    parser = argparse.ArgumentParser(
        description="Optimize B&B parameters using Optuna."
    )
    parser.add_argument(
        "--n-trials", type=int, default=N_TRIALS, help="Number of trials for Optuna."
    )
    args = parser.parse_args()

    if not os.path.exists(BINARY):
        console.print(
            Panel(
                f"[bold red]Binary not found:[/bold red] {BINARY}\n"
                "Build the project or set BINARY to the correct path.",
                border_style="red",
            )
        )
        return

    show_header()

    # Initialize CSV header if file doesn't exist
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["NP", "Level", "SyncInterval", "Time(s)", "Cost"])

    # Quiet Optuna logging
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # Use GridSampler to try each configuration exactly once (stable alternative to BruteForceSampler)
    search_space = {
        "np": POSSIBLE_NPS,
        "level": list(range(LEVEL_MIN, LEVEL_MAX + 1)),
        "sync_interval": SYNC_INTERVALS,
    }
    sampler = optuna.samplers.GridSampler(search_space)
    study = optuna.create_study(direction="minimize", sampler=sampler)

    global live_view
    with Live(
        build_results_table(results_rows),
        console=console,
        refresh_per_second=4,
        vertical_overflow="visible",
    ) as live:
        live_view = live
        try:
            study.optimize(objective, n_trials=args.n_trials)
        except KeyboardInterrupt:
            console.print(
                "\n[bold yellow]Optimization interrupted by user.[/bold yellow]"
            )
        finally:
            live_view = None

    console.print("\n")
    if len(study.trials) > 0:
        try:
            best_p = study.best_params
            best_v = study.best_value

            summary = Group(
                Text.from_markup(f"[bold green]Optimization Complete![/bold green]"),
                Text.from_markup(
                    f"Best Trial: [bold cyan]{study.best_trial.number}[/bold cyan]"
                ),
                Text.from_markup(
                    f"Best Value: [bold yellow]{best_v:.2f}s[/bold yellow]"
                ),
                Text.from_markup(f"Best Params: [magenta]{best_p}[/magenta]"),
            )
            console.print(
                Panel(summary, border_style="green", title="Global Best Result")
            )
        except ValueError:
            console.print(
                Panel("[bold red]No successful trials were completed.[/bold red]")
            )
    else:
        console.print("[bold red]No trials run.[/bold red]")


if __name__ == "__main__":
    main()
