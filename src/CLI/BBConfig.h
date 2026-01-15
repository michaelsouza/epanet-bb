// src/CLI/BBConfig.h
#pragma once

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

  bool enable_snapshots = true;
  bool enable_cost_pruning = true;
  bool enable_pump_sorting = true;
  bool enable_task_shuffle = true;
  bool enable_global_sync = true;
  bool enable_timestep_check = false;

  char fn_stats[256];
  char fn_best[256];
  char fn_profile[256];

private:
  void generateFilenames();
};
