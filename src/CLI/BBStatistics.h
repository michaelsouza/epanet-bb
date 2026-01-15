// src/CLI/BBStatistics.h
#pragma once

#include "BBConfig.h"
#include "BBConstraints.h"

#include <map>
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
  std::map<BBPrune::Reason, std::vector<int>> data; ///< Stores the counts of each prune reason per hour.
  std::map<BBPrune::Reason, std::string> labels;      ///< Maps a prune reason enum to a human-readable string label.
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
};
