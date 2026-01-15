# EPANET-BB: Branch-and-Bound Pump Scheduling Optimizer

A parallel branch-and-bound optimizer for pump scheduling in water distribution networks, built on EPANET 3. This implementation uses MPI for distributed computing and achieves significant performance improvements over existing methods through exact optimization with effective pruning strategies.

## Overview

EPANET-BB extends the EPANET 3 computational engine with a parallel branch-and-bound algorithm to find optimal pump operation schedules that minimize energy costs while maintaining hydraulic constraints (tank levels, pressures, etc.). The implementation features:

- **Exact optimization** - Finds provably optimal solutions through exhaustive search with pruning
- **Parallel execution** - MPI-based task parallelism across multiple processors
- **Multi-criteria pruning** - Actuation constraints, cost bounds, and hydraulic feasibility checks
- **Efficient backtracking** - Lightweight state snapshots for rapid exploration

This work builds upon Costa et al. (2016) and demonstrates 29-115× speedup over sequential implementations while achieving 1.8-3.6% cost reductions compared to genetic algorithm approaches.

## Requirements

- C++17 compiler (GCC 9+, Clang 10+, or Intel icpx)
- MPI implementation (OpenMPI, MPICH, or Intel MPI)
- CMake 3.14 or newer
- nlohmann/json library (3.11.0+)

### Installing Dependencies

**Ubuntu/Debian:**
```bash
sudo apt install build-essential cmake libopenmpi-dev openmpi-bin nlohmann-json3-dev
```

**Fedora/RHEL:**
```bash
sudo dnf install gcc-c++ cmake openmpi-devel json-devel
module load mpi/openmpi
```

## Building

### Standard Build (GCC/Clang)

```bash
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

This produces:
- `build/libepanet3-bb.so` - Shared library with BB extensions
- `build/run-epanet3-bb` - MPI-enabled optimizer executable
- `build/run-epanet3-bb-eval` - Single-process evaluation tool

### Intel Compiler Build

For optimized performance with Intel CPUs:

```bash
source /opt/intel/oneapi/setvars.sh
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_COMPILER=icpx \
  -DCMAKE_C_COMPILER=icx
cmake --build . -j$(nproc)
```

### Clean Build

```bash
rm -rf build
```

## Usage

### Basic Optimization

```bash
mpirun -n 8 build/run-epanet3-bb \
  -i networks/any-town.inp \
  -h 24 \
  -a 1 \
  -l 9
```

**Command-line Arguments:**
- `-i <path>` - Input network file (.inp format)
- `-h <hours>` - Simulation horizon in hours (default: 24)
- `-a <actuations>` - Maximum pump actuations per schedule (default: 3)
- `-l <level>` - Branch-and-bound tree depth for task generation (default: 5)
- `-v` - Enable verbose output

**Example: 24-hour optimization with 1 actuation limit**
```bash
# Use 16 MPI processes, tree level 9 for fine-grained parallelism
mpirun -n 16 build/run-epanet3-bb -i networks/any-town.inp -h 24 -a 1 -l 9
```

The optimizer will:
1. Generate initial tasks by enumerating pump schedules up to depth `level`
2. Distribute tasks across MPI processes
3. Explore the search space with pruning (actuation, cost bound, pressure violations)
4. Output the best solution found with total energy cost
5. Save statistics to `outputs/stats_h<H>_a<A>_l<L>.json`

### Solution Evaluation

To evaluate a specific pump schedule without optimization:

```bash
build/run-epanet3-bb-eval networks/any-town.inp
```

This prints per-pump energy costs and validates hydraulic feasibility.

## Network Files

Input networks use standard EPANET `.inp` format. Example networks are in the `networks/` directory:
- `networks/any-town.inp` - Reference network from literature

EPANET-BB requires time-dependent electricity pricing patterns defined in the network file (see EPANET documentation for pattern syntax).

## Output Files

Results are saved to the `outputs/` directory:

- `stats_h<H>_a<A>_l<L>.json` - Optimization statistics (nodes explored, time, pruning breakdown)
- `best_h<H>_a<A>_l<L>.json` - Best solution found (pump schedule, cost, constraint satisfaction)
- `profile_h<H>_a<A>_l<L>.json` - Performance profiling data

## Python Analysis Tools

The `scripts/` directory contains analysis utilities:

- `run_tuning.py` - Parameter tuning experiments
- `run_scalability.py` - Parallel scaling tests
- `plot_*.py` - Visualization scripts for results
- `agg_outputs.py` - Aggregate statistics from multiple runs

**Setup Python environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Algorithm Description

The branch-and-bound algorithm operates on two schedule representations:

- **y-vector** (high-level): Number of pumps active at each hour `[0, 1, 2, ...]`
- **x-vector** (low-level): Binary on/off status for each pump `[[1,0,0], [0,1,0], ...]`

The solver:
1. Generates initial tasks by enumerating y-vectors up to depth `level`
2. Each task explores remaining hours by branching on possible pump activations
3. Prunes infeasible branches using:
   - **Actuation constraints** - Rejects schedules exceeding max pump switches
   - **Cost bounds** - Eliminates branches with cost > current best
   - **Hydraulic feasibility** - Checks tank levels and pressure requirements via EPANET simulation
4. Uses hydraulic snapshots for efficient state restoration during backtracking
5. Synchronizes best solution across MPI processes periodically

Computational performance is dominated by hydraulic simulations (90%+ of runtime), making pruning effectiveness critical.

## Performance

Representative timings on AMD EPYC 7543 (2.8 GHz, 32 cores):

| Problem Size | Processes | Time    | Speedup |
|--------------|-----------|---------|---------|
| NA_max = 1   | 1         | 3.69 s  | 1×      |
| NA_max = 1   | 128       | 0.138 s | 26.7×   |
| NA_max = 2   | 1         | 493 s   | 1×      |
| NA_max = 2   | 128       | 10.0 s  | 49.3×   |

Pruning eliminates 60-72% of explored nodes. See article for detailed analysis.

## Citation

If you use this software in your research, please cite:

```bibtex
@article{souza2025epanetbb,
  title={Scalable Exact Pump Scheduling in Water Distribution Networks via Parallel Branch-and-Bound with Snapshot Persistence},
  author={Souza, Michael and Gomes, J{\'e}ssica and Muritiba, Albert Einstein Fernandes and Ara{\'u}jo, Asc{\^a}nio Dias},
  journal={[Journal Name]},
  year={2025},
  note={Manuscript in preparation}
}
```

## Research Article

The mathematical formulation, algorithm design, and experimental results are described in detail in `article/article.tex`. Compile with:

```bash
cd article
pdflatex article.tex
bibtex article
pdflatex article.tex
pdflatex article.tex
```

## Project Structure

```
epanet-bb/
├── src/
│   ├── CLI/           # Branch-and-bound implementation
│   │   ├── main.cpp       # MPI coordinator and task distribution
│   │   ├── BBSolver.cpp   # Core B&B algorithm
│   │   ├── BBConfig.cpp   # Configuration parsing
│   │   ├── BBConstraints.cpp  # Constraint management and best solution tracking
│   │   └── BBStatistics.cpp   # Performance metrics
│   ├── Core/          # EPANET project management
│   ├── Elements/      # Network components (nodes, links)
│   ├── Models/        # Hydraulic/quality models
│   ├── Solvers/       # Equation solvers
│   ├── Input/         # Input file parsing
│   ├── Output/        # Results reporting
│   └── Utilities/     # Helper functions
├── networks/          # Test network files
├── scripts/           # Python analysis tools
├── article/           # Research manuscript
└── CMakeLists.txt     # Build configuration
```

## License

MIT License - See LICENSE file for details.

## Acknowledgments

This work builds upon:
- EPANET 3 by the Open Water Analytics community
- Costa et al. (2016) - Original sequential branch-and-bound formulation
- Cimorelli et al. (2020) - Genetic algorithm benchmarks
- De Paola et al. (2025) - Digital harmony search comparisons

## Contact

For questions or issues, please open a GitHub issue or contact the authors.

## Disclaimer

This is research software under active development. While thoroughly tested on benchmark problems, it should be validated on new networks before production use. The optimizer assumes:
- Well-posed hydraulic models (convergent simulations)
- Feasible initial conditions (tanks within bounds at t=0)
- Time-dependent electricity pricing patterns defined in the network file
