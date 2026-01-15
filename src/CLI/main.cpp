// src/CLI/main.cpp

#include "BBConfig.h"
#include "BBSolver.h"
#include "BBStatistics.h"
#include "Profiler.h"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <functional>
#include <mpi.h>
#include <random>
#include <string>
#include <vector>

void debug_tasks(std::vector<BBTask> &tasks, BBConfig &config, const BBConstraints &constraints)
{
  int rank;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  // Debug: Replace all tasks with a single hardcoded task for testing
  // Uncomment and modify the y vector values as needed
  if (rank == 0)
  {
    Console::printf(Console::Color::BRIGHT_MAGENTA, "DEBUG_TASK: Replacing tasks with hardcoded task\n");
  }

  int num_pumps = constraints.get_num_pumps();
  BBTask debug_task;
  
  int case_id = 0;
  if( case_id == 0 ){
    // Hardcode: max_actuations = 1, level = 21, De Paola et. al (2025)
    config.max_actuations = 1;
    config.level = 21;
    debug_task.y.resize(config.h_max + 1, 0);
    debug_task.y[1] = 1;
    debug_task.y[2] = 1;
    debug_task.y[3] = 1;
    debug_task.y[4] = 2;
    debug_task.y[5] = 1;
    debug_task.y[6] = 1;
    debug_task.y[7] = 1;
    debug_task.y[8] = 1;
    debug_task.y[9] = 1;
    debug_task.y[10] = 1;
    debug_task.y[11] = 1;
    debug_task.y[12] = 2;
    debug_task.y[13] = 2;
    debug_task.y[14] = 2;
    debug_task.y[15] = 1;
    debug_task.y[16] = 1;
    debug_task.y[17] = 1;
    debug_task.y[18] = 1;
    debug_task.y[19] = 1;
    debug_task.y[20] = 0;
    debug_task.y[21] = 0;
    debug_task.y[22] = 1;
  }
  else if ( case_id == 1 ){
    // Hardcode: max_actuations = 2, level = 21, De Paola et. al (2025)
    config.max_actuations = 2;
    config.level = 21;
    debug_task.y.resize(config.h_max + 1, 0);
    debug_task.y[1] = 1;
    debug_task.y[2] = 2;
    debug_task.y[3] = 2;
    debug_task.y[4] = 1;
    debug_task.y[5] = 1;
    debug_task.y[6] = 1;
    debug_task.y[7] = 1;
    debug_task.y[8] = 1;
    debug_task.y[9] = 0;
    debug_task.y[10] = 0;
    debug_task.y[11] = 2;
    debug_task.y[12] = 2;
    debug_task.y[13] = 2;
    debug_task.y[14] = 2;
    debug_task.y[15] = 2;
    debug_task.y[16] = 1;
    debug_task.y[17] = 1;
    debug_task.y[18] = 1;
    debug_task.y[19] = 0;
    debug_task.y[20] = 0;
    debug_task.y[21] = 0;
  }
  
  // Add more as needed up to config.h_max
  int level = config.level;
  debug_task.h_root = level + 1;
  debug_task.num_pumps = num_pumps;
  debug_task.uid = 0;
  debug_task.tid = 0; // Assign to rank 0
  
  tasks.clear();
  tasks.push_back(std::move(debug_task));

  if (rank == 0)
  {
    Console::printf(Console::Color::BRIGHT_MAGENTA, "DEBUG_TASK: y = [");
    for (int h = 1; h <= level; h++)
    {
      Console::printf(Console::Color::BRIGHT_MAGENTA, "%d%s", tasks[0].y[h], h < level ? ", " : "");
    }
    Console::printf(Console::Color::BRIGHT_MAGENTA, "]\n");
  }
}

void populate_tasks(std::vector<BBTask> &tasks, const BBConfig &config, const BBConstraints &constraints)
{
  int rank, num_procs;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &num_procs);

  int level = std::max(std::min(config.h_max - 2, config.level), 1);
  std::vector<int> y(config.h_max + 1, 0);

  int num_pumps = constraints.get_num_pumps();

  // Helper function to recursively generate all possible y vectors
  std::function<void(int)> generate_combinations = [&](int pos)
  {
    if (pos > level)
    {
      // Create and configure the task
      BBTask task;
      task.y = y;
      task.h_root = level + 1;
      task.num_pumps = num_pumps;
      tasks.push_back(std::move(task));
      return;
    }

    // Generate combinations for y[pos] in range [0, num_pumps]
    for (int pump_state = 0; pump_state <= num_pumps; ++pump_state)
    {
      y[pos] = pump_state;
      generate_combinations(pos + 1);
    }
  };

  // Start generating combinations from the first position
  generate_combinations(1); // Start at index 1 to skip y[0] (root level)

  // Shuffle tasks with a fixed seed in order to get a consistent order in all processes
  // This aiming to reduce unbalance among the processes
  if (config.enable_task_shuffle)
  {
    std::shuffle(tasks.begin(), tasks.end(), std::default_random_engine(12345));
  }

  for (size_t uid = 0; uid < tasks.size(); uid++)
  {
    // set the uid
    tasks[uid].uid = uid;
    tasks[uid].tid = uid % num_procs;
  }

  if (rank == 0)
  {
    if (config.level != level)
      Console::printf(Console::Color::BRIGHT_RED, "Warning: Changing user defined level from %d to %d\n", config.level,
                      level);
    Console::printf(Console::Color::BRIGHT_YELLOW, "Generated %d tasks\n", tasks.size());
  }
}

void show_global_best(const BBConstraints &constraints)
{
  int rank;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);

  // Reduce local best costs across ranks and print final global best on rank 0
  double local_best = constraints.best_cost_local;
  double global_best = 0.0;
  MPI_Allreduce(&local_best, &global_best, 1, MPI_DOUBLE, MPI_MIN, MPI_COMM_WORLD);

  if (rank == 0)
  {
    Console::printf(Console::Color::BRIGHT_GREEN, "Global best cost: %s\n", constraints.fmt_cost(global_best).c_str());
  }
}

int main(int argc, char *argv[])
{
  MPI_Init(&argc, &argv);
  int rank, num_procs;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Comm_size(MPI_COMM_WORLD, &num_procs);

  {
    ProfileScope scope("main");

    // Parse config
    BBConfig config(argc, argv);
    BBConstraints constraints(config);
    BBStatistics stats(config);

    if (rank == 0)
    {
      config.show();
      std::filesystem::create_directories("outputs");
    }
    MPI_Barrier(MPI_COMM_WORLD);

    // Convert queue to vector for parallel processing
    std::vector<BBTask> tasks;
    populate_tasks(tasks, config, constraints);

    // DEBUG
    // debug_tasks(tasks, config, constraints); 

    // Separate timers for different activities
    double time_processing = 0.0; // Pure computation time
    double time_sync = 0.0;       // MPI synchronization time
    size_t tasks_processed = 0;   // Counter for actual work done

    auto tic_total = std::chrono::high_resolution_clock::now();

    for (size_t i = 0; i < tasks.size(); i++)
    {
      // Periodic stable synchronization (called by ALL ranks for consistency)
      if (i % config.sync_interval == 0)
      {
        auto tic_sync = std::chrono::high_resolution_clock::now();
        constraints.sync_best();
        auto toc_sync = std::chrono::high_resolution_clock::now();
        time_sync += std::chrono::duration_cast<std::chrono::microseconds>(toc_sync - tic_sync).count() / 1e6;
      }

      // Skip tasks that are not assigned to this process
      if (tasks[i].tid != rank)
        continue;

      // Process the task - measure only actual computation
      auto tic_task = std::chrono::high_resolution_clock::now();
      processTask(tasks[i], config, constraints, stats);
      auto toc_task = std::chrono::high_resolution_clock::now();
      time_processing += std::chrono::duration_cast<std::chrono::microseconds>(toc_task - tic_task).count() / 1e6;
      tasks_processed++;
    }

    auto toc_total = std::chrono::high_resolution_clock::now();
    auto duration_total = std::chrono::duration_cast<std::chrono::microseconds>(toc_total - tic_total);
    double time_total = duration_total.count() / 1e6;
    double time_overhead = time_total - time_processing - time_sync;

    // Store metrics in stats object
    stats.duration = time_processing; // Store only pure computation time
    stats.tasks_processed = tasks_processed;
    stats.time_total = time_total;
    stats.time_sync = time_sync;
    stats.time_overhead = time_overhead;

    Console::printf(
        Console::Color::BRIGHT_YELLOW,
        "Proc %02d: tasks=%zu, time(proc=%.3fs, sync=%.3fs, overhead=%.3fs, total=%.3fs), cost(local=%s, global=%s)\n",
        rank, tasks_processed, time_processing, time_sync, time_overhead, time_total,
        constraints.fmt_cost(constraints.best_cost_local).c_str(),
        constraints.fmt_cost(constraints.best_cost_global).c_str());
    fflush(stdout);

    // Final sync to ensure global best is consistent before writing files
    constraints.sync_best();
    MPI_Barrier(MPI_COMM_WORLD);

    stats.to_json(config.fn_stats);
    constraints.to_json(config.fn_best);
    Profiler::save(config.fn_profile);

    show_global_best(constraints);
  }

  MPI_Finalize();
  return EXIT_SUCCESS;
}
