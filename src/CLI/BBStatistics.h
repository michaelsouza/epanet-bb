// src/CLI/BBStatistics.h
#pragma once

#include "BBConfig.h"
#include "BBConstraints.h"
#include "Elements/tanksaturationintervention.h"
#include "Optimization/ExactDisaggregation.h"

#include <map>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

/**
 * @class BBStatistics
 * @brief Collects, manages, and outputs statistics for a branch-and-bound run.
 *
 * This class tracks events that occur during the search, such as the reasons for pruning
 * at different hours (levels) of the search tree. It also handles serialization of these
 * statistics to a JSON file.
 */
class BBStatistics
{
public:
  struct DisaggregationTransition
  {
    int task_uid;
    int hour;
    int active_pumps;
    std::vector<int> canonical_representative;
    DisaggregationTransitionStatistics statistics;
    std::size_t reachable_states;
    std::size_t stored_states;
    std::size_t estimated_state_bytes;
    std::size_t estimated_resident_state_bytes;
    std::uint64_t copy_nanoseconds;
    bool prefix_feasible;
    bool periodic_witness_available;
  };

  struct DisaggregationSummary
  {
    std::size_t transitions = 0;
    std::size_t source_states = 0;
    std::size_t candidate_assignments = 0;
    std::size_t switch_limit_rejections = 0;
    std::size_t unique_successors = 0;
    std::size_t duplicate_successors = 0;
    std::uint64_t transition_nanoseconds = 0;
    std::uint64_t copy_nanoseconds = 0;
    std::size_t peak_reachable_states = 0;
    std::size_t peak_stored_states = 0;
    std::size_t peak_individual_state_bytes = 0;
    std::size_t peak_estimated_state_bytes = 0;
  };

  struct BranchEvaluation
  {
    int task_uid;
    int hour;
    std::vector<int> aggregate_prefix;
    std::vector<int> canonical_representative;
    BBPrune::Reason reason;
    std::vector<TankSaturationIntervention> tank_saturation_events;
  };

  struct HydraulicNonconvergenceEvent
  {
    int task_uid;
    int logical_rank;
    int hour;
    int simulation_time;
    int solver_status;
  };

  std::map<BBPrune::Reason, std::vector<int>> data; ///< Stores the counts of each prune reason per hour.
  std::map<BBPrune::Reason, std::string> labels;      ///< Maps a prune reason enum to a human-readable string label.
  std::vector<DisaggregationTransition> disaggregation_transitions;
  DisaggregationSummary disaggregation_summary;
  std::vector<BranchEvaluation> branch_evaluations;
  std::vector<HydraulicNonconvergenceEvent>
      hydraulic_nonconvergence_events;
  double duration;                                     ///< The execution duration recorded for a process.

  // Load balance metrics
  size_t tasks_processed;                              ///< Number of tasks actually processed by this rank
  double time_total;                                   ///< Total wall-clock time
  double time_sync;                                    ///< Time spent in MPI synchronizations
  double time_overhead;                                ///< Time spent in loop overhead (not processing or sync)

  // Computed Load Balance Metrics
  double proc_time_min;
  double proc_time_avg;
  double proc_time_max;
  double time_total_max;
  double time_sync_max;
  double load_imbalance_factor;
  double parallel_efficiency;

  /**
   * @brief Constructs a BBStatistics object.
   * @param config The branch-and-bound configuration, used to determine the maximum number of hours.
   */
  BBStatistics(const BBConfig &config);

  /**
   * @brief Destructor for the BBStatistics object.
   */
  ~BBStatistics();

  /**
   * @brief Increments the count for a given prune reason at a specific hour.
   * @note This function is defined inline for performance, as it may be called frequently.
   * @param reason The reason for pruning or the event type to record.
   * @param h The hour at which the event occurred.
   */
  inline void add_stats(BBPrune::Reason reason, int h)
  {
    data[reason][h]++;
  }

  /**
   * @brief Serializes the collected statistics to a JSON file.
   * @param fn The name of the output file.
   */
  void to_json(char *fn) const;
  nlohmann::json to_json_value() const;

  void record_disaggregation_transition(
      int task_uid, int hour, int active_pumps,
      const std::vector<int> &canonical_representative,
      const ExactDisaggregation &disaggregation,
      std::size_t estimated_resident_state_bytes,
      std::uint64_t copy_nanoseconds, bool prefix_feasible,
      bool periodic_witness_available);
  void record_branch_evaluation(
      int task_uid, int hour, const std::vector<int> &aggregate_prefix,
      const std::vector<int> &canonical_representative,
      BBPrune::Reason reason,
      const std::vector<TankSaturationIntervention>
          &tank_saturation_events = {});
  void record_hydraulic_nonconvergence(
      int task_uid, int logical_rank, int hour, int simulation_time,
      int solver_status);
  void set_run_metadata(nlohmann::json metadata);
  void set_hydraulic_configuration(nlohmann::json configuration);
  bool is_conclusive() const noexcept;
  void set_global_conclusive(bool conclusive) noexcept;

  /**
   * @brief Merges statistics from another BBStatistics object into this one.
   * @param other The other BBStatistics object to merge from.
   */
  void merge(const BBStatistics &other);

  /**
   * @brief Displays a summary of the current statistics to the console.
   */
  void show() const;

  /**
   * @brief Computes and displays load balance metrics across all MPI ranks.
   * @param rank The MPI rank of the current process.
   * @param num_procs Total number of MPI processes.
   */
  void compute_load_balance_metrics(int rank, int num_procs);

private:
  bool exact_disaggregation_enabled;
  bool search_trace_enabled;
  nlohmann::json run_configuration;
  nlohmann::json run_metadata;
  nlohmann::json hydraulic_configuration;
  bool globally_conclusive;
};
