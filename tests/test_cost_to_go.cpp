// Tests of the mass-balance cost-to-go bound
// (Supplemental Materials of the article).

#include "BBConfig.h"
#include "BBConstraints.h"
#include "BBSolver.h"
#include "BBStatistics.h"

#include "Core/project.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <vector>

namespace
{

using Epanet::Project;

void require(bool condition, const std::string &message)
{
  if (!condition)
  {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(EXIT_FAILURE);
  }
}

constexpr double INF = BBConstraints::CTG_INFINITY;

// Section 1.5 of the proof, evaluated literally in O(N G^2):
//   T_N[j] = 0 if S_j >= S_fin, +inf otherwise
//   T_n[i] = min_j { c_n max(0, S_{j-1} - S_i + d_n) + T_{n+1}[j] }
// with S_j = j * cell (offsets from S_min) and S_{-1} = S_0.
std::vector<double> brute_force_table(const std::vector<double> &unit_cost,
                                      const std::vector<double> &demand, double cell,
                                      double sfinal_offset, int G)
{
  const int N = static_cast<int>(unit_cost.size());
  std::vector<double> table(static_cast<size_t>(N + 1) * G, INF);
  for (int j = 0; j < G; ++j)
    table[static_cast<size_t>(N) * G + j] = (j * cell >= sfinal_offset - 1e-9) ? 0.0 : INF;
  for (int n = N - 1; n >= 0; --n)
  {
    for (int i = 0; i < G; ++i)
    {
      double best = INF;
      for (int j = 0; j < G; ++j)
      {
        const double next = table[static_cast<size_t>(n + 1) * G + j];
        if (next >= INF) continue;
        const double s_prev = (j > 0 ? j - 1 : 0) * cell;
        const double pumped = std::max(0.0, s_prev - i * cell + demand[n]);
        best = std::min(best, unit_cost[n] * pumped + next);
      }
      table[static_cast<size_t>(n) * G + i] = best;
    }
  }
  return table;
}

void require_tables_match(const std::vector<double> &fast, const std::vector<double> &brute,
                          const std::string &label)
{
  require(fast.size() == brute.size(), label + ": table sizes differ");
  for (size_t k = 0; k < fast.size(); ++k)
  {
    const bool fast_inf = fast[k] >= INF, brute_inf = brute[k] >= INF;
    require(fast_inf == brute_inf, label + ": feasibility differs at entry " + std::to_string(k));
    if (fast_inf) continue;
    require(std::abs(fast[k] - brute[k]) <= 1e-9 * std::max(1.0, std::abs(brute[k])),
            label + ": value differs at entry " + std::to_string(k) + " (" + std::to_string(fast[k]) +
                " vs " + std::to_string(brute[k]) + ")");
  }
}

void require_non_increasing(const std::vector<double> &table, int G, const std::string &label)
{
  const size_t stages = table.size() / G;
  for (size_t n = 0; n < stages; ++n)
    for (int i = 0; i + 1 < G; ++i)
    {
      const double a = table[n * G + i], b = table[n * G + i + 1];
      require(b <= a + 1e-9 * std::max(1.0, std::abs(a)),
              label + ": T_n is not non-increasing in storage at n=" + std::to_string(n) +
                  ", i=" + std::to_string(i));
    }
}

BBConfig bound_config(const char *input_file)
{
  BBConfig config;
  config.inpFile = input_file;
  config.enable_cost_pruning = true;
  config.enable_cost_to_go = true;
  config.enable_global_sync = false;
  config.enable_task_shuffle = false;
  return config;
}

void anytown_parameters_match_the_proof(const char *input_file)
{
  BBConstraints constraints(bound_config(input_file));
  const CostToGoInfo &info = constraints.ctg_info;
  require(info.active && constraints.enable_cost_to_go, "the bound should be active on AnyTown");
  require(info.grid_points == BBConstraints::CTG_DEFAULT_GRID, "the default grid should be unchanged");
  require(info.stages == 48, "24 h at 30 min steps gives 48 stages");
  require(std::abs(info.e_min - 0.34474) < 5e-6, "e_min should match the proof");
  require(std::abs(info.head_star - 50.644) < 5e-4, "H* should match the proof");
  require(std::abs(info.flow_star - 1954.6) < 0.05, "q* should match the proof");
  require(std::abs(info.max_unconstrained_demand - 1594.4) < 0.05, "the unconstrained peak demand should match the proof");
  require(info.source_head + info.head_star < info.min_constrained_head, "Lemma S3 (i) should hold");
  require(info.flow_star > info.max_unconstrained_demand, "Lemma S3 (ii) should hold");
  require(info.root_bound > 0.0, "the root bound should be positive");
  require_non_increasing(constraints.ctg_table, constraints.ctg_grid, "AnyTown default grid");
}

void anytown_table_matches_the_brute_force_formula(const char *input_file)
{
  BBConstraints constraints(bound_config(input_file));
  for (int grid : {2, 41, 201})
  {
    Project project;
    require(project.load(input_file) == 0, "the network should load");
    require(constraints.build_cost_to_go(project.getNetwork(), grid), "the bound should build on a small grid");
    const auto brute = brute_force_table(constraints.ctg_unit_cost, constraints.ctg_demand, constraints.ctg_cell,
                                         constraints.ctg_sfinal_offset, grid);
    const std::string label = "AnyTown G=" + std::to_string(grid);
    require_tables_match(constraints.ctg_table, brute, label);
    require_non_increasing(constraints.ctg_table, grid, label);
  }
}

void synthetic_tables_match_the_brute_force_formula()
{
  // Demands that drain, fill (negative demand), force pumping beyond one
  // step, or make states infeasible; grids small enough to make the
  // rounding of every transition matter.
  std::mt19937 generator(20261114);
  std::uniform_real_distribution<double> demand_dist(-1.5, 4.0), cost_dist(0.0, 3.0);
  for (int trial = 0; trial < 50; ++trial)
  {
    const int G = 2 + trial % 9;
    const int N = 1 + trial % 7;
    const double cell = 0.7 + 0.1 * (trial % 5);
    const double sfinal_offset = cell * (G - 1) * (trial % 4) / 3.0;
    std::vector<double> demand(N), unit_cost(N);
    for (int n = 0; n < N; ++n)
    {
      demand[n] = demand_dist(generator) * cell;
      unit_cost[n] = cost_dist(generator);
    }
    const auto fast = BBConstraints::tabulate_cost_to_go(unit_cost, demand, cell, sfinal_offset, G);
    const auto brute = brute_force_table(unit_cost, demand, cell, sfinal_offset, G);
    const std::string label = "synthetic trial " + std::to_string(trial);
    require_tables_match(fast, brute, label);
    require_non_increasing(fast, G, label);
  }
}

void bound_is_disabled_when_its_assumptions_fail(const char *input_file, const char *strict_input_file)
{
  // Tank limits equal to the operating limits violate assumption A3
  BBConstraints strict(bound_config(strict_input_file));
  require(strict.ctg_info.requested && !strict.ctg_info.active && !strict.enable_cost_to_go,
          "the bound should be disabled when the network tank limits are not relaxed");
  require(strict.ctg_info.status.find("A3") != std::string::npos, "the disabled status should name the assumption");

  BBConfig no_cost = bound_config(input_file);
  no_cost.enable_cost_pruning = false;
  BBConstraints without_cost_pruning(no_cost);
  require(!without_cost_pruning.ctg_info.requested && !without_cost_pruning.enable_cost_to_go,
          "disabling cost pruning should disable the bound");

  BBConfig no_ctg = bound_config(input_file);
  no_ctg.enable_cost_to_go = false;
  BBConstraints without_bound(no_ctg);
  require(!without_bound.enable_cost_to_go, "BB_ENABLE_COST_TO_GO=0 should disable the bound");
}

struct SearchOutcome
{
  double best_cost;
  std::vector<int> best_x;
  std::vector<int> best_y;
  long nodes;
  long cost_prunes;
  long cost_to_go_prunes;
};

// Mirrors populate_tasks at level 1 without shuffling: one root task per
// hour-1 aggregate decision.
SearchOutcome reduced_search(const char *input_file, int h_max, int max_actuations, bool cost_to_go)
{
  BBConfig config = bound_config(input_file);
  config.h_max = h_max;
  config.max_actuations = max_actuations;
  config.level = 1;
  config.enable_cost_to_go = cost_to_go;
  BBConstraints constraints(config);
  require(constraints.enable_cost_to_go == cost_to_go, "the bound should follow the configuration");
  BBStatistics statistics(config);
  for (int pumps = 0; pumps <= constraints.get_num_pumps(); ++pumps)
  {
    BBTask task(pumps, config, constraints);
    task.y[1] = pumps;
    task.h_root = config.level + 1;
    task.tid = 0;
    processTask(task, config, constraints, statistics);
  }
  SearchOutcome outcome{constraints.best_cost_local, constraints.best_x, constraints.best_y, 0, 0, 0};
  for (const auto &[reason, counts] : statistics.data)
    outcome.nodes += std::accumulate(counts.begin(), counts.end(), 0L);
  const auto &cost = statistics.data.at(BBPrune::Reason::COST);
  const auto &cost_to_go_counts = statistics.data.at(BBPrune::Reason::COST_TO_GO);
  outcome.cost_prunes = std::accumulate(cost.begin(), cost.end(), 0L);
  outcome.cost_to_go_prunes = std::accumulate(cost_to_go_counts.begin(), cost_to_go_counts.end(), 0L);
  return outcome;
}

void reduced_search_is_unchanged_by_the_bound(const char *input_file)
{
  long total_cost_to_go_prunes = 0;
  for (const auto &[h_max, actuations] : std::vector<std::pair<int, int>>{{3, 1}, {8, 1}})
  {
    const SearchOutcome off = reduced_search(input_file, h_max, actuations, false);
    const SearchOutcome on = reduced_search(input_file, h_max, actuations, true);
    const std::string label = "h_max=" + std::to_string(h_max) + ", NA=" + std::to_string(actuations);
    require(off.best_cost < std::numeric_limits<double>::max(), label + ": the search should find a schedule");
    require(on.best_cost == off.best_cost, label + ": the bound should not change the best cost");
    require(on.best_y == off.best_y && on.best_x == off.best_x, label + ": the bound should not change the schedule");
    require(on.nodes <= off.nodes, label + ": the bound should not enlarge the search");
    require(off.cost_to_go_prunes == 0, label + ": no COST_TO_GO prune without the bound");
    std::cout << label << ": nodes " << off.nodes << " -> " << on.nodes << ", COST " << off.cost_prunes << " -> "
              << on.cost_prunes << ", COST_TO_GO " << on.cost_to_go_prunes << '\n';
    total_cost_to_go_prunes += on.cost_to_go_prunes;
  }
  require(total_cost_to_go_prunes > 0, "the bound should prune at least one node as COST_TO_GO");
}

} // namespace

int main(int argc, char **argv)
{
  require(argc == 3, "usage: CostToGoTest <network.inp> <strict-tank-limits.inp>");
  anytown_parameters_match_the_proof(argv[1]);
  anytown_table_matches_the_brute_force_formula(argv[1]);
  synthetic_tables_match_the_brute_force_formula();
  bound_is_disabled_when_its_assumptions_fail(argv[1], argv[2]);
  reduced_search_is_unchanged_by_the_bound(argv[1]);
  return EXIT_SUCCESS;
}
