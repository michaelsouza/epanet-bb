# epanet-bb: Parallel Branch-and-Bound Pump Scheduling Optimizer

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19363091.svg)](https://doi.org/10.5281/zenodo.19363091)

`epanet-bb` is an open-source fork of the
[Open Water Analytics EPANET repository](https://github.com/OpenWaterAnalytics/EPANET).
It combines a distributed-memory Branch-and-Bound solver with a customized,
embedded EPANET hydraulic engine to optimize day-ahead pump schedules subject
to hydraulic, operational, and energy-cost constraints.

The repository includes the precomputed data used to reconstruct the tables
and figures of the accompanying article. Versioned releases are archived in the
[project Zenodo record](https://doi.org/10.5281/zenodo.19363091).

## Requirements and build

The project requires a C++17 compiler, CMake 3.14 or later, MPI, and
`nlohmann/json` 3.11 or later. On Ubuntu or Debian, install the dependencies
with:

```bash
sudo apt install build-essential cmake libopenmpi-dev openmpi-bin nlohmann-json3-dev
```

Configure and build the executables with:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
```

This produces `build/run-epanet3-bb`, the optimizer, and
`build/run-epanet3-bb-eval`, the fixed-schedule evaluator.

## Optimize a schedule

The following command optimizes a 24-hour schedule for the included AnyTown
Modified network using 16 MPI processes:

```bash
mpirun -n 16 build/run-epanet3-bb \
  -i networks/any-town.inp \
  -h 24 \
  -a 1 \
  -l 9
```

Here, `-h` sets the scheduling horizon, `-a` limits pump actuations, and `-l`
sets the static task-decomposition depth. Additional options control the bound
synchronization interval (`-s`), hydraulic iteration limit
(`--hydraulic-max-trials`), hydraulic accuracy (`--hydraulic-accuracy`), and
verbosity (`-v`).

### Feasibility protocol

The tank limits declared in `networks/any-town.inp` (61.53 to 75.53 m) are
deliberately wider than the operating limits, so the hydraulic engine never
clamps a tank level. The operating tank limits (66.53 to 71.53 m) and the
minimum junction pressures are checked by the optimizer and by
`run-epanet3-bb-eval` after every hydraulic step (see
`src/CLI/BBConstraints.cpp`); a schedule that violates them at any step is
infeasible.

### Cost-to-go bound

Besides the accumulated cost, the optimizer prunes a node when its accumulated
cost plus a lower bound on the cost still to be paid reaches the incumbent. The
bound merges the tanks into one store, charges every pumped cubic metre at the
smallest energy per unit volume of the pump curve, and solves the resulting
relaxation once per run by dynamic programming over a storage grid. Statement,
proof and the conditions it needs are in
the Supplemental Materials of the article; the implementation is
`BBConstraints::build_cost_to_go`. The conditions of Lemma S3 are checked from
the network data at start-up; if one fails, the bound is disabled with a
warning. Statistics count these prunes as `COST_TO_GO`, separately from
`COST`. Set `BB_ENABLE_COST_TO_GO=0` to disable the bound
(`BB_ENABLE_COST_PRUNING=0` disables both cost tests).

### Switch-count convention

By default `-a NA` limits each pump to `NA` periodic cycles: status changes
are counted around the 24 h cycle, including the transition from the last hour
back to the first, at most `2*NA` per pump. Set `BB_PERIODIC_SWITCH_COUNT=0`
to count instead only switch-ons (off to on) between consecutive hours of a
single day, at most `NA` per pump, with a free first-hour status (the
convention of Cimorelli et al., 2020). The single-day count requires the exact
disaggregation and is rejected together with
`BB_ENABLE_EXACT_DISAGGREGATION=0`. The configuration banner, the statistics
JSON (`switch_count_convention`, `max_switch_count_per_pump`) and the
best-solution JSON record the convention in use.

### Outputs

Each MPI rank writes statistics, best-solution, and profiling files under
`outputs/`. The statistics JSON reports whether the search was conclusive and
records the effective execution and hydraulic configuration. The best-solution
JSON contains the aggregate schedule, its hydraulically simulated canonical
representative, and the reconstructed binary schedule, which respects the
selected switch-count convention.

## Reproducibility

### Python environment

Create the supported Python environment with:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Rebuild the manuscript

The versioned [reproducibility inventory](experiments/reproducibility.json)
separates experiment execution from manuscript reconstruction. Rebuild the
declared manuscript products from the checked-in data, without running MPI,
with:

```bash
.venv/bin/python scripts/rebuild_manuscript.py \
  --output-dir build/reproduced-manuscript
```

### Plan and run experiments

Inspect an experiment subset before execution with:

```bash
.venv/bin/python scripts/run_campaign.py \
  --dry-run --np 64 --select scalability
```

`--select scalability` and `--select ablation` choose the corresponding
campaign subsets. `--select final-cases` runs the three final cases
(`NA` = 1, 2, 3) under the periodic switch count and
`--select final-cases-single-day` repeats them with
`BB_PERIODIC_SWITCH_COUNT=0`.

Actual campaign execution requires `--select <subset>` or `--all`. The
`--profile smoke` option validates orchestration only and must not be used as
performance evidence. High-rank experiments require a compatible HPC system
with explicitly allocated resources.

The roles of supporting components are summarized in the
[scripts guide](scripts/README.md).

## Evaluate a fixed schedule

`run-epanet3-bb-eval` evaluates a complete aggregate schedule stored in JSON:

```json
{
  "best_y": [
    0, 1, 1, 1, 2, 1, 1, 1,
    1, 1, 1, 1, 2, 2, 2, 1,
    1, 1, 1, 1, 0, 0, 1, 0, 0
  ],
  "h_max": 24,
  "max_actuations": 1,
  "inp_file": "networks/any-town.inp"
}
```

```bash
build/run-epanet3-bb-eval input.json output.json
```

Set `schedule_mode` to `binary` and provide `best_x` to evaluate specified
pump identities instead of reconstructing them from `best_y`. The optional
`switch_count_convention` field selects `periodic` (default) or `single_day`
limits, as described for the optimizer; the output reports both
`periodic_switch_counts` and `single_day_switch_on_counts` whenever the binary
schedule is known before simulation.

## Citation

If you use this software, please cite the archived release:

```bibtex
@software{souza2026epanetbb,
  author = {
    Rocha, J{\'e}ssica Gomes Melo da and
    Muritiba, Albert Einstein Fernandes and
    Ara{\'u}jo, Asc{\^a}nio Dias and
    Lavor, Carlile Campos and
    Souza, Michael
  },
  title = {EPANET-BB: Parallel Branch-and-Bound Pump Scheduling Optimizer},
  year = {2026},
  doi = {10.5281/zenodo.19363091},
  url = {https://doi.org/10.5281/zenodo.19363091}
}
```

## License

This project is distributed under the [MIT License](LICENSE) and builds on
EPANET and the Open Water Analytics ecosystem. It is research software;
results should be validated before operational deployment on new networks.
