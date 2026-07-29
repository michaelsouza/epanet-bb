#include "BBStatistics.h"
#include "Console.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <mpi.h>
#include <nlohmann/json.hpp>
#include <numeric>
#include <vector>

BBStatistics::BBStatistics(const BBConfig &config)
{
    exact_disaggregation_enabled = config.enable_exact_disaggregation;
    search_trace_enabled = config.enable_search_trace;
    globally_conclusive = true;
    run_configuration = {
        {"input_file", config.inpFile},
        {"horizon_hours", config.h_max},
        {"max_cycles_per_pump", config.max_actuations},
        {"task_decomposition_level", config.level},
        {"sync_interval", config.sync_interval},
        {"snapshots", config.enable_snapshots},
        {"cost_pruning", config.enable_cost_pruning},
        {"exact_disaggregation", config.enable_exact_disaggregation},
        {"search_trace", config.enable_search_trace},
        {"hydraulic_max_trials_override",
         config.hydraulic_max_trials > 0
             ? nlohmann::json(config.hydraulic_max_trials)
             : nlohmann::json(nullptr)},
        {"hydraulic_accuracy_override",
         config.hydraulic_accuracy > 0.0
             ? nlohmann::json(config.hydraulic_accuracy)
             : nlohmann::json(nullptr)}};
    // Copy labels
    labels = BBPrune::labels;

    for (const auto &[_reason, _label] : labels)
    {
      data[_reason] = std::vector<int>(config.h_max + 1, 0);
    }
    duration = 0.0;
    tasks_processed = 0;
    time_total = 0.0;
    time_sync = 0.0;
    time_overhead = 0.0;

    proc_time_min = 0.0;
    proc_time_avg = 0.0;
    proc_time_max = 0.0;
    time_total_max = 0.0;
    time_sync_max = 0.0;
    load_imbalance_factor = 0.0;
    parallel_efficiency = 0.0;
}

BBStatistics::~BBStatistics()
{
}

void BBStatistics::to_json(char *fn) const
{
    // Console::printf(Console::Color::BRIGHT_GREEN, "Saving statistics to file: %s\n", fn);
    
    const nlohmann::json j = to_json_value();
    std::ofstream f(fn);
    f << j.dump(2);
}

nlohmann::json BBStatistics::to_json_value() const
{
    nlohmann::json j;
    for (const auto &[_reason, _counts] : data)
    {
      j[labels.at(_reason)] = _counts;
    }
    j["duration"] = duration;
    j["tasks_processed"] = tasks_processed;
    j["time_total"] = time_total;
    j["time_sync"] = time_sync;
    j["time_overhead"] = time_overhead;

    // Load balance metrics
    j["proc_time_min"] = proc_time_min;
    j["proc_time_avg"] = proc_time_avg;
    j["proc_time_max"] = proc_time_max;
    j["time_total_max"] = time_total_max;
    j["time_sync_max"] = time_sync_max;
    j["load_imbalance_factor"] = load_imbalance_factor;
    j["parallel_efficiency"] = parallel_efficiency;
    j["metadata"] = run_metadata;
    j["metadata"]["configuration"] = run_configuration;
    j["metadata"]["hydraulic"] = hydraulic_configuration;

    j["search"] = {
        {"method", exact_disaggregation_enabled
                       ? "EXACT_PERIODIC_DISAGGREGATION"
                       : "LEGACY_GREEDY_DISAGGREGATION"},
        {"trace_enabled", search_trace_enabled},
        {"status", is_conclusive()
                       ? "CONCLUSIVE"
                       : "INCONCLUSIVE_HYDRAULIC_NONCONVERGENCE"}};
    j["disaggregation_summary"] = {
        {"transitions", disaggregation_summary.transitions},
        {"source_states", disaggregation_summary.source_states},
        {"candidate_assignments",
         disaggregation_summary.candidate_assignments},
        {"switch_limit_rejections",
         disaggregation_summary.switch_limit_rejections},
        {"unique_successors",
         disaggregation_summary.unique_successors},
        {"duplicate_successors",
         disaggregation_summary.duplicate_successors},
        {"transition_nanoseconds",
         disaggregation_summary.transition_nanoseconds},
        {"copy_nanoseconds", disaggregation_summary.copy_nanoseconds},
        {"peak_reachable_states",
         disaggregation_summary.peak_reachable_states},
        {"peak_stored_states",
         disaggregation_summary.peak_stored_states},
        {"peak_individual_state_bytes",
         disaggregation_summary.peak_individual_state_bytes},
        {"peak_estimated_state_bytes",
         disaggregation_summary.peak_estimated_state_bytes},
        {"state_memory_estimate_scope",
         "snapshot vector, all resident exact states, and transition working "
         "copy; allocator overhead excluded"}};
    j["disaggregation_transitions"] = nlohmann::json::array();
    for (const auto &transition : disaggregation_transitions)
    {
      const auto &counts = transition.statistics;
      j["disaggregation_transitions"].push_back(
          {{"task_uid", transition.task_uid},
           {"hour", transition.hour},
           {"active_pumps", transition.active_pumps},
           {"canonical_representative",
            transition.canonical_representative},
           {"source_states", counts.source_states},
           {"candidate_assignments", counts.candidate_assignments},
           {"switch_limit_rejections", counts.switch_limit_rejections},
           {"unique_successors", counts.unique_successors},
           {"duplicate_successors", counts.duplicate_successors},
           {"transition_nanoseconds", counts.elapsed_nanoseconds},
           {"copy_nanoseconds", transition.copy_nanoseconds},
           {"reachable_states", transition.reachable_states},
           {"stored_states", transition.stored_states},
           {"estimated_state_bytes",
            transition.estimated_state_bytes},
           {"estimated_resident_state_bytes",
            transition.estimated_resident_state_bytes},
           {"prefix_feasible", transition.prefix_feasible},
           {"periodic_witness_available",
            transition.periodic_witness_available}});
    }
    j["branch_evaluations"] = nlohmann::json::array();
    for (const auto &evaluation : branch_evaluations)
    {
      nlohmann::json events = nlohmann::json::array();
      for (const auto &event : evaluation.tank_saturation_events)
      {
        events.push_back(
            {{"tank", event.tank_name},
             {"intervention",
              event.type ==
                      TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM
                  ? "BLOCKED_INFLOW_AT_MAXIMUM"
                  : "BLOCKED_OUTFLOW_AT_MINIMUM"}});
      }
      j["branch_evaluations"].push_back(
          {{"task_uid", evaluation.task_uid},
           {"hour", evaluation.hour},
           {"aggregate_prefix", evaluation.aggregate_prefix},
           {"canonical_representative",
            evaluation.canonical_representative},
           {"reason", labels.at(evaluation.reason)},
           {"tank_saturation_events", std::move(events)}});
    }
    j["hydraulic_nonconvergence_events"] = nlohmann::json::array();
    for (const auto &event : hydraulic_nonconvergence_events)
    {
      j["hydraulic_nonconvergence_events"].push_back(
          {{"task_uid", event.task_uid},
           {"logical_rank", event.logical_rank},
           {"hour", event.hour},
           {"simulation_time", event.simulation_time},
           {"solver_status", event.solver_status},
           {"classification", "HYDRAULIC_NONCONVERGENCE"}});
    }
    return j;
}

void BBStatistics::record_disaggregation_transition(
    int task_uid, int hour, int active_pumps,
    const std::vector<int> &canonical_representative,
    const ExactDisaggregation &disaggregation,
    std::size_t estimated_resident_state_bytes,
    std::uint64_t copy_nanoseconds, bool prefix_feasible,
    bool periodic_witness_available)
{
  const auto &transition = disaggregation.last_transition_statistics();
  ++disaggregation_summary.transitions;
  disaggregation_summary.source_states += transition.source_states;
  disaggregation_summary.candidate_assignments +=
      transition.candidate_assignments;
  disaggregation_summary.switch_limit_rejections +=
      transition.switch_limit_rejections;
  disaggregation_summary.unique_successors +=
      transition.unique_successors;
  disaggregation_summary.duplicate_successors +=
      transition.duplicate_successors;
  disaggregation_summary.transition_nanoseconds +=
      transition.elapsed_nanoseconds;
  disaggregation_summary.copy_nanoseconds += copy_nanoseconds;
  disaggregation_summary.peak_reachable_states = std::max(
      disaggregation_summary.peak_reachable_states,
      disaggregation.reachable_state_count());
  disaggregation_summary.peak_stored_states = std::max(
      disaggregation_summary.peak_stored_states,
      disaggregation.stored_state_count());
  disaggregation_summary.peak_individual_state_bytes = std::max(
      disaggregation_summary.peak_individual_state_bytes,
      disaggregation.estimated_state_bytes());
  disaggregation_summary.peak_estimated_state_bytes = std::max(
      disaggregation_summary.peak_estimated_state_bytes,
      estimated_resident_state_bytes);

  if (!search_trace_enabled)
    return;
  disaggregation_transitions.push_back(
      {task_uid,
       hour,
       active_pumps,
       canonical_representative,
       disaggregation.last_transition_statistics(),
       disaggregation.reachable_state_count(),
       disaggregation.stored_state_count(),
       disaggregation.estimated_state_bytes(),
       estimated_resident_state_bytes,
       copy_nanoseconds,
       prefix_feasible,
       periodic_witness_available});
}

void BBStatistics::record_branch_evaluation(
    int task_uid, int hour, const std::vector<int> &aggregate_prefix,
    const std::vector<int> &canonical_representative,
    BBPrune::Reason reason,
    const std::vector<TankSaturationIntervention> &tank_saturation_events)
{
  if (!search_trace_enabled)
    return;
  branch_evaluations.push_back(
      {task_uid, hour, aggregate_prefix, canonical_representative, reason,
       tank_saturation_events});
}

void BBStatistics::record_hydraulic_nonconvergence(
    int task_uid, int logical_rank, int hour, int simulation_time,
    int solver_status)
{
  hydraulic_nonconvergence_events.push_back(
      {task_uid, logical_rank, hour, simulation_time, solver_status});
}

void BBStatistics::set_run_metadata(nlohmann::json metadata)
{
  run_metadata = std::move(metadata);
}

void BBStatistics::set_hydraulic_configuration(
    nlohmann::json configuration)
{
  hydraulic_configuration = std::move(configuration);
}

bool BBStatistics::is_conclusive() const noexcept
{
  return globally_conclusive &&
         hydraulic_nonconvergence_events.empty();
}

void BBStatistics::set_global_conclusive(bool conclusive) noexcept
{
  globally_conclusive = conclusive;
}

void BBStatistics::merge(const BBStatistics &other)
{
    for (const auto &[reason, counts] : other.data)
    {
      // sum counts
      for (size_t h = 0; h < counts.size(); ++h)
      {
        data[reason][h] += counts[h];
      }
    }

    disaggregation_summary.transitions +=
        other.disaggregation_summary.transitions;
    disaggregation_summary.source_states +=
        other.disaggregation_summary.source_states;
    disaggregation_summary.candidate_assignments +=
        other.disaggregation_summary.candidate_assignments;
    disaggregation_summary.switch_limit_rejections +=
        other.disaggregation_summary.switch_limit_rejections;
    disaggregation_summary.unique_successors +=
        other.disaggregation_summary.unique_successors;
    disaggregation_summary.duplicate_successors +=
        other.disaggregation_summary.duplicate_successors;
    disaggregation_summary.transition_nanoseconds +=
        other.disaggregation_summary.transition_nanoseconds;
    disaggregation_summary.copy_nanoseconds +=
        other.disaggregation_summary.copy_nanoseconds;
    disaggregation_summary.peak_reachable_states = std::max(
        disaggregation_summary.peak_reachable_states,
        other.disaggregation_summary.peak_reachable_states);
    disaggregation_summary.peak_stored_states = std::max(
        disaggregation_summary.peak_stored_states,
        other.disaggregation_summary.peak_stored_states);
    disaggregation_summary.peak_individual_state_bytes = std::max(
        disaggregation_summary.peak_individual_state_bytes,
        other.disaggregation_summary.peak_individual_state_bytes);
    disaggregation_summary.peak_estimated_state_bytes = std::max(
        disaggregation_summary.peak_estimated_state_bytes,
        other.disaggregation_summary.peak_estimated_state_bytes);

    disaggregation_transitions.insert(
        disaggregation_transitions.end(),
        other.disaggregation_transitions.begin(),
        other.disaggregation_transitions.end());
    branch_evaluations.insert(
        branch_evaluations.end(), other.branch_evaluations.begin(),
        other.branch_evaluations.end());
    hydraulic_nonconvergence_events.insert(
        hydraulic_nonconvergence_events.end(),
        other.hydraulic_nonconvergence_events.begin(),
        other.hydraulic_nonconvergence_events.end());
    globally_conclusive =
        globally_conclusive && other.globally_conclusive;
}

void BBStatistics::show() const
{
    int rank;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);

    Console::hline(Console::Color::BRIGHT_YELLOW, 20);
    Console::printf(Console::Color::BRIGHT_YELLOW, "TID[%d]: Statistics\n", rank);
    Console::printf(Console::Color::BRIGHT_YELLOW, "Duration: %.3f seconds\n", duration);
    for (const auto &[type, counts] : data)
    {
      Console::printf(Console::Color::CYAN, "%10s: [", labels.at(type).c_str());
      for (size_t i = 0; i < counts.size(); ++i)
      {
        Console::printf(Console::Color::CYAN, "%d, ", counts[i]);
      }
      Console::printf(Console::Color::CYAN, "]\n");
    }
}

void BBStatistics::compute_load_balance_metrics(int rank, int num_procs)
{
    // Gather processing times from all ranks
    std::vector<double> all_times_proc(num_procs);
    std::vector<double> all_times_total(num_procs);
    std::vector<double> all_times_sync(num_procs);
    std::vector<size_t> all_tasks(num_procs);

    MPI_Gather(&duration, 1, MPI_DOUBLE, all_times_proc.data(), 1, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    MPI_Gather(&time_total, 1, MPI_DOUBLE, all_times_total.data(), 1, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    MPI_Gather(&time_sync, 1, MPI_DOUBLE, all_times_sync.data(), 1, MPI_DOUBLE, 0, MPI_COMM_WORLD);
    MPI_Gather(&tasks_processed, 1, MPI_UNSIGNED_LONG, all_tasks.data(), 1, MPI_UNSIGNED_LONG, 0, MPI_COMM_WORLD);

    if (rank == 0)
    {
      // Calculate statistics for processing time
      double time_min = *std::min_element(all_times_proc.begin(), all_times_proc.end());
      double time_max = *std::max_element(all_times_proc.begin(), all_times_proc.end());
      double time_avg = std::accumulate(all_times_proc.begin(), all_times_proc.end(), 0.0) / num_procs;

      double variance = 0.0;
      for (int i = 0; i < num_procs; i++)
      {
        variance += std::pow(all_times_proc[i] - time_avg, 2);
      }
      double time_std = std::sqrt(variance / num_procs);

      // Calculate load imbalance metrics
      double imbalance = (time_max - time_avg) / time_avg * 100.0;
      double eff = time_avg / time_max * 100.0;

      // Calculate max times for total and sync
      double total_max = *std::max_element(all_times_total.begin(), all_times_total.end());
      double sync_max = *std::max_element(all_times_sync.begin(), all_times_sync.end());

      // Store in members
      this->proc_time_min = time_min;
      this->proc_time_avg = time_avg;
      this->proc_time_max = time_max;
      this->time_total_max = total_max;
      this->time_sync_max = sync_max;
      this->load_imbalance_factor = imbalance;
      this->parallel_efficiency = eff;

      // Calculate task distribution
      size_t total_tasks = std::accumulate(all_tasks.begin(), all_tasks.end(), 0UL);

      // Print results
      Console::printf(Console::Color::BRIGHT_CYAN, "\n════════════════════════════════════════\n");
      Console::printf(Console::Color::BRIGHT_CYAN, "Load Balance Analysis\n");
      Console::printf(Console::Color::BRIGHT_CYAN, "════════════════════════════════════════\n");

      Console::printf(Console::Color::WHITE, "Processing Time (min/avg/max): %.3f / %.3f / %.3f seconds\n",
                      time_min, time_avg, time_max);
      Console::printf(Console::Color::WHITE, "Std deviation: %.3f seconds (%.1f%%)\n",
                      time_std, time_std / time_avg * 100.0);
      Console::printf(Console::Color::WHITE, "Load Imbalance Factor: %.2f%%\n", load_imbalance_factor);
      Console::printf(Console::Color::WHITE, "Parallel Efficiency: %.2f%%\n", parallel_efficiency);

      // Diagnosis
      if (load_imbalance_factor < 5.0)
      {
        Console::printf(Console::Color::BRIGHT_GREEN, "✓ Excellent load balance\n");
      }
      else if (load_imbalance_factor < 15.0)
      {
        Console::printf(Console::Color::BRIGHT_YELLOW, "○ Acceptable load balance\n");
      }
      else if (load_imbalance_factor < 30.0)
      {
        Console::printf(Console::Color::BRIGHT_RED, "△ Poor load balance - consider improvements\n");
      }
      else
      {
        Console::printf(Console::Color::BRIGHT_RED, "✗ Critical imbalance - requires changes\n");
      }

      // Detailed breakdown per process
      Console::printf(Console::Color::BRIGHT_CYAN, "\nPer-Process Breakdown:\n");
      Console::printf(Console::Color::WHITE, "Proc | Tasks  |  Proc(s) |  Sync(s) | Total(s) | s/task  | vs avg\n");
      Console::printf(Console::Color::WHITE, "-----+--------+----------+----------+----------+---------+--------\n");

      for (int i = 0; i < num_procs; i++)
      {
        double avg_time_per_task = all_times_proc[i] / all_tasks[i];
        double deviation = (all_times_proc[i] - time_avg) / time_avg * 100.0;
        Console::printf(Console::Color::WHITE,
                        " %02d  | %6lu | %8.3f | %8.3f | %8.3f | %7.4f | %+6.1f%%\n",
                        i, all_tasks[i], all_times_proc[i], all_times_sync[i], all_times_total[i],
                        avg_time_per_task, deviation);
      }
      Console::printf(Console::Color::BRIGHT_CYAN, "════════════════════════════════════════\n\n");
    }
}
