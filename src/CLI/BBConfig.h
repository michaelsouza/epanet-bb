// src/CLI/BBConfig.h
#pragma once

#include <stdexcept>
#include <string>

class BBConfig
{
public:
  BBConfig() = default;
  BBConfig(int argc, char *argv[]);

  void show() const;

  std::string inpFile = "networks/any-town.inp";
  int h_max = 24;
  int max_actuations = 3;
  int level = 8;
  int sync_interval = 32768;  // Synchronization interval (every N tasks)
  int verbose = 0;
  int hydraulic_max_trials = 0; // Zero preserves the input-file value.
  double hydraulic_accuracy = 0.0; // Zero preserves the input-file value.

  bool enable_snapshots = true;
  bool enable_cost_pruning = true;
  bool enable_cost_to_go = true; // Mass-balance cost-to-go bound (needs cost pruning)
  bool enable_pump_sorting = true;
  bool enable_task_shuffle = true;
  bool enable_global_sync = true;
  bool enable_timestep_check = false;
  bool enable_exact_disaggregation = true;
  // Switch-count convention (BB_PERIODIC_SWITCH_COUNT):
  //   true  (default): status changes counted around the cycle (wrap-around),
  //                    at most 2 * max_actuations per pump;
  //   false:           single-day count of switch-ons (0 -> 1) between
  //                    consecutive hours, at most max_actuations per pump;
  //                    the first-hour status is free.
  bool periodic_switch_count = true;
  bool enable_search_trace = false;

  /// "periodic" or "single_day".
  const char *switch_count_convention() const noexcept
  {
    return periodic_switch_count ? "periodic" : "single_day";
  }

  /// Per-pump limit of the counted events under the selected convention.
  int max_switch_count_per_pump() const noexcept
  {
    return periodic_switch_count ? 2 * max_actuations : max_actuations;
  }

  /// Throws std::invalid_argument for unsupported option combinations.
  void validate() const
  {
    // The legacy greedy disaggregation counts switch-ons and switch-offs
    // separately and implements neither convention exactly; it is kept only
    // as the historical baseline of the periodic convention.
    if (!periodic_switch_count && !enable_exact_disaggregation)
      throw std::invalid_argument(
          "BB_PERIODIC_SWITCH_COUNT=0 requires exact disaggregation; "
          "do not combine it with BB_ENABLE_EXACT_DISAGGREGATION=0");
  }

  char fn_stats[256];
  char fn_best[256];
  char fn_profile[256];

private:
  void generateFilenames();
};
