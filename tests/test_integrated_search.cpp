#include "BBConfig.h"
#include "BBConstraints.h"
#include "BBSolver.h"
#include "BBStatistics.h"
#include "RunMetadata.h"

#include "Core/options.h"
#include "Core/project.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>
#include <string>

namespace
{

using Epanet::Project;

void require(bool condition, const char *message)
{
  if (!condition)
  {
    std::cerr << message << '\n';
    std::exit(EXIT_FAILURE);
  }
}

struct HydraulicOutcome
{
  std::vector<double> signature;
  double cost;
};

HydraulicOutcome evaluate_binary_schedule(
    const BBConfig &config, BBConstraints &constraints,
    const std::vector<int> &schedule)
{
  Project project;
  require(project.load(config.inpFile.c_str()) == 0,
          "the equivalence network should load");
  project.getNetwork()->options.setOption(
      Options::TimeOption::TOTAL_DURATION, config.h_max * 3600);
  require(project.initSolver(EN_INITFLOW) == 0,
          "the equivalence solver should initialize");
  constraints.update_pumps(project, config.h_max, schedule, 0);

  HydraulicOutcome outcome;
  int time = 0;
  int step = 0;
  do
  {
    require(project.runSolver(&time) == HydSolver::SUCCESSFUL,
            "the equivalence schedule should converge");
    require(project.tankSaturationEvents().empty(),
            "the accepted schedule should not require tank intervention");
    for (const Node *node : project.getNetwork()->nodes)
      outcome.signature.push_back(node->head);
    double total_pump_flow = 0.0;
    for (const auto &[name, index] : constraints.pumps)
    {
      (void)name;
      total_pump_flow += project.getNetwork()->link(index)->flow;
    }
    outcome.signature.push_back(total_pump_flow);
    require(project.advanceSolver(&step) == 0,
            "the equivalence schedule should advance");
  } while (step > 0);
  outcome.cost = constraints.calc_cost(project);
  return outcome;
}

void short_search_uses_exact_disaggregation_and_a_canonical_representative(
    const char *input_file, const char *executable,
    const char *artifact_file)
{
  BBConfig config;
  config.inpFile = input_file;
  config.h_max = 3;
  config.max_actuations = 1;
  config.level = 1;
  config.enable_cost_pruning = false;
  config.enable_global_sync = false;
  config.enable_task_shuffle = false;
  config.enable_exact_disaggregation = true;
  config.enable_search_trace = true;

  BBConstraints constraints(config);
  BBStatistics statistics(config);
  statistics.set_run_metadata(RunMetadata::capture(executable, 1));
  BBTask task(0, config, constraints);
  task.h_root = 1;
  task.tid = 0;

  processTask(task, config, constraints, statistics);

  const auto output = statistics.to_json_value();
  require(output.at("search").at("method") == "EXACT_PERIODIC_DISAGGREGATION",
          "the search metadata should identify exact periodic disaggregation");
  require(!output.at("disaggregation_transitions").empty(),
          "the search should trace exact disaggregation transitions");
  require(output.at("disaggregation_summary").at("transitions") > 0,
          "the search should aggregate disaggregation work");
  require(output.at("disaggregation_summary")
              .at("peak_estimated_state_bytes") > 0,
          "the integration should measure the branch-state footprint");
  std::size_t maximum_individual_state_bytes = 0;
  std::size_t multilevel_path_lower_bound = 0;
  const auto &transitions = output.at("disaggregation_transitions");
  for (std::size_t index = 0; index < transitions.size(); ++index)
  {
    maximum_individual_state_bytes = std::max(
        maximum_individual_state_bytes,
        transitions.at(index).at("estimated_state_bytes").get<std::size_t>());
    if (index >= 2 &&
        transitions.at(index - 2).at("hour") == 1 &&
        transitions.at(index - 1).at("hour") == 2 &&
        transitions.at(index).at("hour") == 3)
    {
      multilevel_path_lower_bound = std::max(
          multilevel_path_lower_bound,
          transitions.at(index - 2)
                  .at("estimated_state_bytes")
                  .get<std::size_t>() +
              transitions.at(index - 1)
                  .at("estimated_state_bytes")
                  .get<std::size_t>() +
              transitions.at(index)
                  .at("estimated_state_bytes")
                  .get<std::size_t>());
    }
  }
  require(multilevel_path_lower_bound > 0,
          "the integration should exercise a three-level exact-state path");
  require(
      output.at("disaggregation_summary")
              .at("peak_individual_state_bytes") ==
          maximum_individual_state_bytes,
      "the summary should retain the largest individual snapshot estimate");
  require(
      output.at("disaggregation_summary")
              .at("peak_estimated_state_bytes")
              .get<std::size_t>() >= multilevel_path_lower_bound,
      "the peak estimate should include simultaneously resident DFS states");

  bool saw_periodic_witness = false;
  for (const auto &transition : output.at("disaggregation_transitions"))
  {
    const int active_pumps = transition.at("active_pumps").get<int>();
    const auto canonical =
        transition.at("canonical_representative").get<std::vector<int>>();
    require(canonical.size() == 3,
            "the canonical representative should include every pump");
    require(std::accumulate(canonical.begin(), canonical.end(), 0) ==
                active_pumps,
            "the canonical representative should realize the aggregate decision");
    for (std::size_t pump = 0; pump < canonical.size(); ++pump)
    {
      require(canonical.at(pump) ==
                  (pump < static_cast<std::size_t>(active_pumps) ? 1 : 0),
              "the hydraulic representative should be the fixed canonical mapping");
    }
    saw_periodic_witness =
        saw_periodic_witness ||
        transition.at("periodic_witness_available").get<bool>();
  }
  require(saw_periodic_witness,
          "at least one complete aggregate schedule should expose a periodic witness");

  const auto metadata = output.at("metadata");
  require(metadata.at("software").at("executable_sha256")
                  .get<std::string>()
                  .size() == 64,
          "the executable should be identified by a SHA-256 digest");
  require(!metadata.at("software").at("git_commit").get<std::string>().empty(),
          "the configured Git commit should be recorded");
  require(!metadata.at("software")
               .at("compiler")
               .at("id")
               .get<std::string>()
               .empty(),
          "the compiler should be recorded");
  require(metadata.at("software")
              .at("compiler")
              .contains("effective_compile_options"),
          "the effective directory compile options should be recorded");
  if (metadata.at("software").at("build_type") == "Release")
  {
    require(metadata.at("software")
                .at("compiler")
                .at("effective_compile_options")
                .get<std::string>()
                .find("-ffast-math") != std::string::npos,
            "Release metadata should include numerically relevant options");
    require(metadata.at("software")
                .at("compiler")
                .at("interprocedural_optimization")
                .get<bool>(),
            "Release metadata should record enabled IPO");
  }
  require(metadata.at("mpi_processes") == 1,
          "the effective process count should be recorded");
  require(metadata.at("configuration").at("horizon_hours") == 3,
          "the search configuration should be recorded");
  require(std::abs(
              metadata.at("hydraulic")
                      .at("relative_accuracy")
                      .get<double>() -
              0.0001) < 1.0e-12,
          "the effective hydraulic accuracy should be recorded");
  require(metadata.at("hydraulic").at("relative_accuracy_origin") ==
              "input_file",
          "the source of the hydraulic accuracy should be recorded");

  bool saw_saturation_prune = false;
  for (const auto &evaluation : output.at("branch_evaluations"))
  {
    if (evaluation.at("reason") == "TANK_SATURATION")
    {
      saw_saturation_prune = true;
      require(!evaluation.at("tank_saturation_events").empty(),
              "a saturation prune should retain its causal tank event");
    }
  }
  require(saw_saturation_prune,
          "the reduced integrated search should exercise saturation pruning");

  require(!constraints.best_y.empty(),
          "the reduced search should produce a complete aggregate schedule");
  require(constraints.best_x.size() == constraints.best_y.size() * 3,
          "the best result should expose a padded binary witness");
  for (std::size_t hour = 1; hour < constraints.best_y.size(); ++hour)
  {
    const auto begin =
        constraints.best_x.begin() + static_cast<std::ptrdiff_t>(hour * 3);
    require(std::accumulate(begin, begin + 3, 0) ==
                constraints.best_y.at(hour),
            "the reconstructed witness should realize every aggregate period");
  }
  for (std::size_t pump = 0; pump < 3; ++pump)
  {
    int switches = 0;
    for (std::size_t hour = 1; hour < constraints.best_y.size(); ++hour)
    {
      const std::size_t previous =
          hour == 1 ? constraints.best_y.size() - 1 : hour - 1;
      switches +=
          constraints.best_x.at(previous * 3 + pump) !=
          constraints.best_x.at(hour * 3 + pump);
    }
    require(switches <= 2,
            "the reconstructed witness should respect one periodic cycle");
  }

  const HydraulicOutcome canonical = evaluate_binary_schedule(
      config, constraints, constraints.best_canonical_x);
  const HydraulicOutcome witness = evaluate_binary_schedule(
      config, constraints, constraints.best_x);
  require(canonical.signature.size() == witness.signature.size(),
          "the paired hydraulic traces should have the same shape");
  double maximum_hydraulic_difference = 0.0;
  for (std::size_t value = 0; value < canonical.signature.size(); ++value)
  {
    const double difference =
        std::abs(canonical.signature[value] -
                 witness.signature[value]);
    maximum_hydraulic_difference =
        std::max(maximum_hydraulic_difference, difference);
    require(difference < 1.0e-9,
            "canonical and reconstructed schedules should be hydraulically equivalent");
  }
  const double cost_difference = std::abs(canonical.cost - witness.cost);
  require(cost_difference < 1.0e-9,
          "canonical and reconstructed schedules should have equal energy cost");
  require(std::abs(constraints.best_cost_local - canonical.cost) < 1.0e-9,
          "the incumbent cost and stored schedules should describe the same result");

  nlohmann::json artifact = output;
  artifact["solution"] = constraints.to_json_value();
  artifact["representative_witness_equivalence"] = {
      {"maximum_hydraulic_difference", maximum_hydraulic_difference},
      {"cost_difference", cost_difference},
      {"tolerance", 1.0e-9}};
  std::ofstream file(artifact_file);
  file << artifact.dump(2);
}

void hydraulic_nonconvergence_marks_the_search_inconclusive_without_pruning(
    const char *input_file, const char *executable)
{
  BBConfig config;
  config.inpFile = input_file;
  config.h_max = 1;
  config.max_actuations = 1;
  config.enable_cost_pruning = false;
  config.enable_global_sync = false;
  config.enable_search_trace = true;
  config.hydraulic_max_trials = 1;
  config.hydraulic_accuracy = 0.001;

  BBConstraints constraints(config);
  BBStatistics statistics(config);
  statistics.set_run_metadata(RunMetadata::capture(executable, 1));
  BBTask task(1, config, constraints);
  task.h_root = 1;
  task.tid = 0;

  processTask(task, config, constraints, statistics);

  const auto output = statistics.to_json_value();
  require(output.at("search").at("status") ==
              "INCONCLUSIVE_HYDRAULIC_NONCONVERGENCE",
          "a nonconvergent hydraulic solve should make the search inconclusive");
  require(!output.at("hydraulic_nonconvergence_events").empty(),
          "the first nonconvergent step should be traceable");
  require(output.at("hydraulic_nonconvergence_events")
              .front()
              .at("logical_rank") == task.tid,
          "a nonconvergence event should identify its logical rank");
  require(std::abs(
              output.at("metadata")
                      .at("hydraulic")
                      .at("relative_accuracy")
                      .get<double>() -
              0.001) < 1.0e-12,
          "a requested hydraulic accuracy should become effective");
  require(output.at("metadata")
              .at("hydraulic")
              .at("relative_accuracy_origin") == "command_line",
          "an overridden hydraulic accuracy should retain its origin");
  int prune_count = 0;
  for (const auto &[reason, counts] : statistics.data)
  {
    if (reason == BBPrune::Reason::NONE)
      continue;
    prune_count += std::accumulate(counts.begin(), counts.end(), 0);
  }
  require(prune_count == 0,
          "hydraulic nonconvergence must not be counted as a prune");
}

void metadata_resolves_the_running_executable_when_invoked_through_path(
    const char *executable)
{
  const std::filesystem::path executable_path(executable);
  const auto direct = RunMetadata::capture(executable_path.string(), 1);
  const auto through_path =
      RunMetadata::capture(executable_path.filename().string(), 1);
  require(
      through_path.at("software").at("executable_sha256") ==
          direct.at("software").at("executable_sha256"),
      "metadata should hash the running executable when argv[0] is a PATH name");
}

void statistics_merge_preserves_integrated_search_evidence()
{
  BBConfig config;
  config.h_max = 1;
  config.enable_exact_disaggregation = true;
  config.enable_search_trace = true;
  BBStatistics aggregate(config);
  BBStatistics partial(config);

  ExactDisaggregation disaggregation(3, 1);
  require(disaggregation.append(2),
          "the merge fixture should have a feasible transition");
  partial.record_disaggregation_transition(
      7, 1, 2, {1, 1, 0}, disaggregation, 211, 11, true, true);
  partial.record_hydraulic_nonconvergence(7, 3, 1, 3600, -1);
  partial.add_stats(BBPrune::Reason::TANK_SATURATION, 1);

  aggregate.merge(partial);

  require(aggregate.disaggregation_summary.transitions == 1,
          "merge should preserve disaggregation totals");
  require(aggregate.disaggregation_summary.copy_nanoseconds == 11,
          "merge should preserve disaggregation copy time");
  require(
      aggregate.disaggregation_summary.peak_estimated_state_bytes == 211,
      "merge should preserve the resident-state peak");
  require(aggregate.disaggregation_transitions.size() == 1,
          "merge should preserve detailed transitions");
  require(aggregate.hydraulic_nonconvergence_events.size() == 1,
          "merge should preserve nonconvergence evidence");
  require(!aggregate.is_conclusive(),
          "merged nonconvergence should make the aggregate inconclusive");
  require(
      aggregate.data.at(BBPrune::Reason::TANK_SATURATION).at(1) == 1,
      "merge should continue to aggregate prune counts");
}

} // namespace

int main(int argc, char **argv)
{
  require(
      argc == 3,
      "usage: IntegratedSearchTest <network.inp> <artifact.json>");
  short_search_uses_exact_disaggregation_and_a_canonical_representative(
      argv[1], argv[0], argv[2]);
  hydraulic_nonconvergence_marks_the_search_inconclusive_without_pruning(
      argv[1], argv[0]);
  metadata_resolves_the_running_executable_when_invoked_through_path(argv[0]);
  statistics_merge_preserves_integrated_search_evidence();
  return EXIT_SUCCESS;
}
