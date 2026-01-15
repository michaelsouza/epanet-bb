// src/CLI/BBConfig.cpp
#include "BBConfig.h"
#include "Console.h"

#include <mpi.h>
#include <string>
#include <algorithm>

void BBConfig::generateFilenames()
{
  int rank, np;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &np);

  char fn_base[256];
  // Format the base filename with outputs/ directory
  int ret = snprintf(fn_base, sizeof(fn_base), "outputs/run_a_%02d_h_%02d_l_%02d_s_%02d_n_%02d_r_%02d", max_actuations, h_max, level, sync_interval, np, rank);
  if (ret < 0 || static_cast<size_t>(ret) >= sizeof(fn_base))
  {
    throw std::runtime_error("Filename truncation occurred in fn_base!");
  }

  // Format the stats filename
  ret = snprintf(fn_stats, sizeof(fn_stats), "%s_stats.json", fn_base);
  if (ret < 0 || static_cast<size_t>(ret) >= sizeof(fn_stats))
  {
    throw std::runtime_error("Filename truncation occurred in fn_stats!");
  }

  // Format the best filename
  ret = snprintf(fn_best, sizeof(fn_best), "%s_best.json", fn_base);
  if (ret < 0 || static_cast<size_t>(ret) >= sizeof(fn_best))
  {
    throw std::runtime_error("Filename truncation occurred in fn_best!");
  }

  // Format the profile filename
  ret = snprintf(fn_profile, sizeof(fn_profile), "%s_prof.txt", fn_base);
  if (ret < 0 || static_cast<size_t>(ret) >= sizeof(fn_profile))
  {
    throw std::runtime_error("Filename truncation occurred in fn_profile!");
  }
}

BBConfig::BBConfig(int argc, char *argv[])
{
  int rank, np;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &np);

  // Parse command line arguments
  for (int i = 1; i < argc; ++i)
  {
    std::string arg = argv[i];
    if (arg == "-i" || arg == "--input")
      inpFile = argv[++i];
    else if (arg == "-v" || arg == "--verbose")
    {
      if (i + 1 < argc)
      {
        std::string next_arg = argv[i + 1];
        if (!next_arg.empty() && std::all_of(next_arg.begin(), next_arg.end(), ::isdigit))
        {
          verbose = std::stoi(next_arg);
          i++; // consume next arg
        }
        else
        {
          verbose = 1;
        }
      }
      else
      {
        verbose = 1;
      }
    }
    else if (arg == "-h" || arg == "--h_max")
      h_max = std::stoi(argv[++i]);
    else if (arg == "-a" || arg == "--max_actuations")
      max_actuations = std::stoi(argv[++i]);
    else if (arg == "-l" || arg == "--level")
      level = std::stoi(argv[++i]);
    else if (arg == "-s" || arg == "--sync-interval")
      sync_interval = std::stoi(argv[++i]);
  }

  // Parse environment variables
  auto get_env_bool = [](const char* name, bool default_val) -> bool {
    const char* val = std::getenv(name);
    if (!val) return default_val;
    std::string s(val);
    if (s == "0" || s == "false" || s == "FALSE" || s == "off" || s == "OFF") return false;
    return true;
  };

  enable_snapshots = get_env_bool("BB_ENABLE_SNAPSHOTS", true);
  enable_cost_pruning = get_env_bool("BB_ENABLE_COST_PRUNING", true);
  enable_pump_sorting = get_env_bool("BB_ENABLE_PUMP_SORTING", true);
  enable_task_shuffle = get_env_bool("BB_ENABLE_TASK_SHUFFLE", true);
  enable_global_sync = get_env_bool("BB_ENABLE_GLOBAL_SYNC", true);
  enable_timestep_check = get_env_bool("BB_ENABLE_TIMESTEP_CHECK", false);

  // Buffers for filenames
  try
  {
    generateFilenames();
  }
  catch (const std::runtime_error &e)
  {
    throw std::runtime_error(e.what());
  }
}

void BBConfig::show() const
{
  Console::printf(Console::Color::CYAN, "════════════════════════════════════════\n");
  Console::printf(Console::Color::CYAN, "Branch & Bound Configuration:\n");
  Console::printf(Console::Color::WHITE, "  Input file:      %s\n", inpFile.c_str());
  Console::printf(Console::Color::WHITE, "  Max hours:       %d\n", h_max);
  Console::printf(Console::Color::WHITE, "  Max actuations:  %d\n", max_actuations);
  Console::printf(Console::Color::WHITE, "  Level:           %d\n", level);
  Console::printf(Console::Color::WHITE, "  Sync interval:   %d\n", sync_interval);
  Console::printf(Console::Color::WHITE, "  Verbose:         %d\n", verbose);
  Console::printf(Console::Color::WHITE, "  Stats file:      %s\n", fn_stats);
  Console::printf(Console::Color::WHITE, "  Best file:       %s\n", fn_best);
  Console::printf(Console::Color::WHITE, "  Profile file:    %s\n", fn_profile);
  Console::printf(Console::Color::CYAN, "Experimental Toggles:\n");
  Console::printf(Console::Color::WHITE, "  Snapshots:       %s\n", enable_snapshots ? "ON" : "OFF");
  Console::printf(Console::Color::WHITE, "  Cost Pruning:    %s\n", enable_cost_pruning ? "ON" : "OFF");
  Console::printf(Console::Color::WHITE, "  Pump Sorting:    %s\n", enable_pump_sorting ? "ON" : "OFF");
  Console::printf(Console::Color::WHITE, "  Task Shuffle:    %s\n", enable_task_shuffle ? "ON" : "OFF");
  Console::printf(Console::Color::WHITE, "  Global Sync:     %s\n", enable_global_sync ? "ON" : "OFF");
  Console::printf(Console::Color::WHITE, "  Timestep Check:  %s\n", enable_timestep_check ? "ON" : "OFF");
}
