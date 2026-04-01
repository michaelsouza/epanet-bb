# EPANET-BB: Parallel Branch-and-Bound Pump Scheduling Optimizer

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19363092.svg)](https://doi.org/10.5281/zenodo.19363092)

EPANET-BB is a parallel branch-and-bound solver for exact pump scheduling in water distribution networks, built on top of EPANET 3 and MPI. It targets day-ahead pump scheduling with hydraulic feasibility checks, actuation limits, and energy-cost minimization.

The current repository state is aligned with the submission manuscript in [paper/paper.pdf](/home/michael/gitrepos/epanet-bb/paper/paper.pdf) and the archived software release at [Zenodo](https://doi.org/10.5281/zenodo.19363092).

## Overview

The solver combines:

- Exact optimization with branch-and-bound
- Distributed-memory parallelism with MPI
- Hydraulic feasibility checks through EPANET 3
- Snapshot-based backtracking to avoid repeated full resimulation
- Cooperative pruning using cost bounds and operational constraints

For the modified AnyTown benchmark, the accompanying paper reports:

- 29x to 115x speedup over the earlier sequential exact method of Costa et al. (2016)
- 3.7% lower energy cost than the best published heuristic result in the least constrained case
- A reduction from 85.08 s on 1 MPI process to 3.18 s on 64 MPI processes for the 24 h, `NA_max = 1` scalability case

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

Intel oneAPI build:

```bash
source /opt/intel/oneapi/setvars.sh
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_COMPILER=icpx \
  -DCMAKE_C_COMPILER=icx
cmake --build . -j"$(nproc)"
```

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
- `-v`, `--verbose [level]`: verbose mode

The optimizer creates an `outputs/` directory and writes one set of files per MPI rank. The current filename pattern is:

- `outputs/run_a_<AA>_h_<HH>_l_<LL>_s_<SS>_n_<NP>_r_<RR>_stats.json`
- `outputs/run_a_<AA>_h_<HH>_l_<LL>_s_<SS>_n_<NP>_r_<RR>_best.json`
- `outputs/run_a_<AA>_h_<HH>_l_<LL>_s_<SS>_n_<NP>_r_<RR>_prof.txt`

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

The input must contain a `best_y` array of length `h_max + 1`, with `best_y[0] = 0`.

## Network Files

Example benchmark inputs are stored in [networks/](/home/michael/gitrepos/epanet-bb/networks):

- [networks/any-town.inp](/home/michael/gitrepos/epanet-bb/networks/any-town.inp)

The benchmark relies on time-dependent demand and electricity tariff patterns defined in the EPANET input file.

## Python Analysis Tools

Analysis and figure-generation scripts are stored in [scripts/](/home/michael/gitrepos/epanet-bb/scripts). Notable utilities include:

- `run_experiments.py`
- `run_scalability.py`
- `run_ablation.py`
- `run_tuning.py`
- `plot_network.py`
- `plot_scalability.py`
- `plot_tanks.py`
- `plot_comparison.py`

Python environment setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Research Article

The submission manuscript is in [paper/paper.tex](/home/michael/gitrepos/epanet-bb/paper/paper.tex), with the compiled PDF at [paper/paper.pdf](/home/michael/gitrepos/epanet-bb/paper/paper.pdf).

To compile the manuscript:

```bash
cd paper
make
```

The paper describes the mathematical formulation, parallelization strategy, ablation study, scalability results, and grayscale submission figures currently tracked in this repository.

## Project Structure

```text
epanet-bb/
├── src/            # EPANET 3 source plus branch-and-bound extensions
├── networks/       # Benchmark EPANET input files
├── scripts/        # Experiment and plotting scripts
├── paper/          # Submission manuscript and figures
├── docs/           # Additional notes and supporting material
├── references/     # External reference material
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
  doi = {10.5281/zenodo.19363092},
  url = {https://doi.org/10.5281/zenodo.19363092}
}
```

The companion manuscript is included in [paper/](/home/michael/gitrepos/epanet-bb/paper). If it is published, the README should be updated with the final article citation.

## License

This project is distributed under the MIT License. See [LICENSE](/home/michael/gitrepos/epanet-bb/LICENSE).

## Acknowledgments

This project builds on:

- EPANET 3 and the Open Water Analytics ecosystem
- Costa et al. (2016), for the original exact branch-and-bound formulation
- Cimorelli et al. (2020), for heuristic benchmark comparison
- De Paola et al. (2024), for recent benchmark context

## Disclaimer

This is research software. Results should be validated before operational deployment on new networks. The current implementation assumes:

- a well-posed hydraulic model,
- feasible initial tank conditions, and
- time-dependent tariff information in the network input.
