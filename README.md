# epanet-bb: Parallel Branch-and-Bound Pump Scheduling Optimizer

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19363091.svg)](https://doi.org/10.5281/zenodo.19363091)

`epanet-bb` is an open-source fork of the [Open Water Analytics EPANET repository](https://github.com/OpenWaterAnalytics/EPANET). It couples a parallel branch-and-bound solver for exact pump scheduling with a customized EPANET hydraulic engine and MPI. The software targets day-ahead pump scheduling with hydraulic feasibility checks, actuation limits, and energy-cost minimization. The embedded engine is identified by the `epanet-bb` revision and its effective hydraulic configuration; it is not presented as an external or official release named “EPANET 3” or “EPANET 3.0”.

The repository includes the submission manuscript in
[`paper/paper.pdf`](paper/paper.pdf). Versioned releases are archived under the
[project Zenodo record](https://doi.org/10.5281/zenodo.19363091).

## Overview

The solver combines:

- Exact optimization with branch-and-bound
- Distributed-memory parallelism with MPI
- Hydraulic feasibility checks through the customized EPANET engine embedded in `epanet-bb`
- Snapshot-based backtracking to avoid repeated full resimulation
- Cooperative pruning using cost bounds and operational constraints
- Exact periodic disaggregation of aggregate pump-count schedules
- Explicit rejection of tank-boundary interventions

The accompanying paper evaluates the contribution of exact disaggregation,
hydraulic snapshots, pruning and parallel execution on the AnyTown Modified
benchmark. The reported guarantees and performance results are limited to the
discrete model, hydraulic configuration and experiments described there.

## Requirements

- C++17 compiler
- CMake 3.14+
- MPI implementation such as OpenMPI or MPICH
- `nlohmann/json` 3.11+

### Installing Dependencies

Ubuntu/Debian:

```bash
sudo apt install build-essential cmake libopenmpi-dev openmpi-bin nlohmann-json3-dev
```

Fedora/RHEL:

```bash
sudo dnf install gcc-c++ cmake openmpi-devel json-devel
module load mpi/openmpi
```

## Building

Standard build:

```bash
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j"$(nproc)"
```

This produces:

- `build/libepanet3-bb.so`
- `build/run-epanet3-bb`
- `build/run-epanet3-bb-eval`

## Usage

### Optimization Run

Example:

```bash
mpirun -n 16 build/run-epanet3-bb \
  -i networks/any-town.inp \
  -h 24 \
  -a 1 \
  -l 9
```

Main arguments:

- `-i`, `--input`: EPANET input file
- `-h`, `--h_max`: simulation horizon in hours
- `-a`, `--max_actuations`: maximum number of pump actuations
- `-l`, `--level`: task decomposition depth
- `-s`, `--sync-interval`: bound synchronization interval
- `--hydraulic-max-trials`: override the input file's hydraulic iteration limit
- `--hydraulic-accuracy`: override the input file's relative hydraulic accuracy
- `-v`, `--verbose [level]`: verbose mode

The default search branches on the number of active interchangeable pumps,
uses a fixed canonical binary representative for each hydraulic simulation,
and carries every reachable actuation class with the DFS snapshot. At a
complete horizon it reconstructs a periodic binary witness. Set
`BB_ENABLE_SEARCH_TRACE=1` for a reduced diagnostic run that records each
aggregate prefix, canonical representative, exact-disaggregation transition,
prune reason, and tank-saturation event. Detailed tracing can produce large
files and is therefore disabled by default.

The optimizer creates an `outputs/` directory and writes one set of files per MPI rank. The current filename pattern is:

- `outputs/run_a_<AA>_h_<HH>_l_<LL>_s_<SS>_n_<NP>_r_<RR>_stats.json`
- `outputs/run_a_<AA>_h_<HH>_l_<LL>_s_<SS>_n_<NP>_r_<RR>_best.json`
- `outputs/run_a_<AA>_h_<HH>_l_<LL>_s_<SS>_n_<NP>_r_<RR>_prof.txt`

The statistics JSON identifies whether the search was conclusive and records
the effective hydraulic configuration, executable SHA-256, configured Git
state, base compiler flags, effective directory compile options, IPO state,
hardware, and MPI process count. The executable is resolved from the running
process, including invocations through `PATH`. The disaggregation summary
separates the largest individual state from the estimated peak resident
footprint, which includes the snapshot vector, all retained exact states, and
the transition working copy but excludes allocator overhead. A hydraulic
nonconvergence event records its task and logical rank, makes the global
search status inconclusive, and is never counted as a feasibility prune. In
the best solution JSON, `best_canonical_x` is the schedule simulated
hydraulically, while `best_x` is the exact periodic binary witness
reconstructed for the same aggregate schedule `best_y`.

### Portable final-case runner

`scripts/run_experiments.py` runs the selected actuation cases in isolated
working directories. Paths are resolved from the repository rather than the
calling directory, and the output directory must not already exist. Inspect
the complete plan without creating files:

```bash
.venv/bin/python scripts/run_experiments.py \
  --dry-run \
  --np 4 \
  --hours 3 \
  --actuations 1 \
  --level 1 \
  --sync-interval 32 \
  --output-dir build/experiments/portable-smoke
```

Remove `--dry-run` to execute the plan. `--np` has precedence; when it is
absent, the runner uses `SLURM_NTASKS`, `PBS_NP`, `LSB_DJOB_NUMPROC` or
`NSLOTS`, in that order. Without an explicit value or a detected allocation,
the conservative fallback is one rank. A requested value larger than a
detected allocation is rejected. `execution-plan.json` records the effective
paths, process count, its source and every MPI command, while
`execution-results.json` records completion, return codes, durations and log
paths.

### Evaluating a Fixed Schedule

`run-epanet3-bb-eval` evaluates a complete schedule from a JSON file rather than directly from an `.inp` file.

Example input:

```json
{
  "best_y": [0, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 1, 1, 1, 1, 1, 0, 0, 1, 0, 0],
  "h_max": 24,
  "max_actuations": 1,
  "inp_file": "networks/any-town.inp",
  "verbose": 1
}
```

Run it with:

```bash
build/run-epanet3-bb-eval input.json output.json
```

The input must contain a `best_y` array of length `h_max + 1`. The default
`schedule_mode` is `aggregate`, which reconstructs a binary witness from those
counts. Set `schedule_mode` to `binary` and provide `best_x` to replay the
specific published pump identities. Binary mode verifies that `best_x` and
`best_y` agree and enforces at most `2 * max_actuations` transitions per pump,
over optimized hours 1--24, including periodic closure from hour 24 to hour 1.
The row-zero status is a hydraulic initial-state placeholder and is not
counted as an operational transition.

## Network Files

Example benchmark inputs are stored in [`networks/`](networks):

- [`networks/any-town.inp`](networks/any-town.inp)

The benchmark relies on time-dependent demand and electricity tariff patterns defined in the EPANET input file.

## Python Analysis Tools

Analysis and figure-generation scripts are stored in [`scripts/`](scripts).
Notable utilities include:

- `run_campaign.py`
- `rebuild_manuscript.py`
- `run_experiments.py`
- `run_scalability.py`
- `run_ablation.py`
- `run_tuning.py`
- `summarize_ablation.py`
- `summarize_scalability.py`
- `summarize_final_cases.py`
- `run_accuracy_sensitivity.py`
- `summarize_accuracy_sensitivity.py`
- `audit_accuracy_sensitivity.py`
- `prepare_manuscript_artifacts.py`
- `evaluate_comparison_schedules.py`
- `plot_network.py`
- `plot_scalability.py`
- `plot_tanks.py`
- `plot_comparison.py`

The versioned inventory in
[`experiments/reproducibility.json`](experiments/reproducibility.json)
separates the MPI campaign from reconstruction of manuscript products. Inspect
the complete campaign or a selected subset without creating files:

```bash
.venv/bin/python scripts/run_campaign.py --dry-run --np 64
.venv/bin/python scripts/run_campaign.py \
  --dry-run --np 64 --select scalability
```

Actual execution requires an explicit `--select` or `--all`. The bounded
profile below validates the orchestration but must not be used as performance
evidence:

```bash
.venv/bin/python scripts/run_campaign.py \
  --profile smoke --select final-cases --np 1 \
  --output-dir build/experiments/campaign-smoke
```

Repeating a compatible invocation with `--resume` skips completed work. The
`tuning`, `final-cases`, `scalability`, and `ablation` subsets require MPI;
high-rank final runs belong on a compatible HPC system with explicitly
allocated resources.
`run_scalability.py` and `run_ablation.py` remain as compatibility shortcuts
that select their corresponding subsets.

The declared graphical products and comparison CSV can instead be rebuilt
without MPI from checked-in precomputed data:

```bash
.venv/bin/python scripts/rebuild_manuscript.py \
  --output-dir build/reproduced-manuscript
```

The rebuild manifest maps the final data tables, LaTeX fragments, Figures 1–9
and `comparison_table.csv` to their inputs and commands. It reconstructs 38
products from the checked-in precomputed results without invoking MPI.

The final tuning, ablation, scalability and hydraulic-accuracy configurations
and their precomputed summaries are checked in under [`experiments/`](experiments).
The supported Python environment can be created and checked with:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/validate_python_environment.py \
  --output-dir build/python-environment-smoke
```

## Research Article

The submission manuscript is in [`paper/paper.tex`](paper/paper.tex), with the
compiled PDF at [`paper/paper.pdf`](paper/paper.pdf).

To compile the manuscript:

```bash
cd paper
make
```

The paper describes the mathematical formulation, parallelization strategy, ablation study, scalability results, and grayscale submission figures currently tracked in this repository.

## Project Structure

```text
epanet-bb/
├── src/            # Customized EPANET engine plus branch-and-bound extensions
├── networks/       # Benchmark EPANET input files
├── scripts/        # Experiment and plotting scripts
├── paper/          # Submission manuscript and figures
├── docs/           # Additional notes and supporting material
├── README.md
├── CMakeLists.txt
└── requirements.txt
```

## Citation

If you use this software, please cite the archived release:

```bibtex
@software{souza2026epanetbb,
  author = {Rocha, J{\'e}ssica Gomes Melo da and Muritiba, Albert Einstein Fernandes and Ara{\'u}jo, Asc{\^a}nio Dias and Lavor, Carlile Campos and Souza, Michael Ferreira de},
  title = {EPANET-BB: Parallel Branch-and-Bound Pump Scheduling Optimizer},
  year = {2026},
  doi = {10.5281/zenodo.19363091},
  url = {https://doi.org/10.5281/zenodo.19363091}
}
```

The companion manuscript is included in [`paper/`](paper). If it is published,
the README should be updated with the final article citation.

## License

This project is distributed under the MIT License. See [`LICENSE`](LICENSE).

## Acknowledgments

This project builds on:

- EPANET and the Open Water Analytics ecosystem
- Costa et al. (2016), for the original exact branch-and-bound formulation
- Cimorelli et al. (2020), for heuristic benchmark comparison
- De Paola et al. (2024), for recent benchmark context

## Disclaimer

This is research software. Results should be validated before operational deployment on new networks. The current implementation assumes:

- a well-posed hydraulic model,
- feasible initial tank conditions, and
- time-dependent tariff information in the network input.
