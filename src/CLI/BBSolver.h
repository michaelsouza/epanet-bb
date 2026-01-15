// BBSolver.h
#pragma once

#include "BBConfig.h"
#include "BBConstraints.h"
#include "BBStatistics.h"
#include "Console.h"
#include "Profiler.h"

#include "Core/project.h"
#include "Elements/node.h"
#include "Elements/tank.h"

#include <algorithm>
#include <queue>
#include <stdexcept>
#include <vector>

// Forward declarations
class BBTask;
class BBSolver;

/**
 * @class BBTask
 * @brief Holds all data and state required to process a single branch-and-bound task.
 *
 * This class encapsulates the state of a search sub-problem, including the pump schedules
 * (y and x vectors), hydraulic snapshots, and feasibility status.
 */
class BBTask
{
public:
  int uid;                      ///< Unique identifier for the task.
  int h_root;                   ///< The first hour in the schedule that can be modified by the solver.
  double cost;                  ///< The current cost associated with this task's partial solution.
  std::vector<ProjectData> snapshots; ///< Stores hydraulic states at each hour to allow for fast resets.
  std::vector<int> y;           ///< High-level pump schedule: number of pumps active at each hour.
  std::vector<int> x;           ///< Low-level pump schedule: binary status (on/off) for each pump at each hour.
  int h;                        ///< The current hour being processed in the search.
  bool is_feasible;             ///< Flag indicating if the current partial solution is still feasible.
  int num_pumps;                ///< The total number of pumps in the network.
  Project *p;                   ///< Pointer to the EPANET project object used for simulation.
  int tid;                      ///< The ID of the MPI process (thread) assigned to this task.

  /**
   * @brief Calculates the priority of the task. Currently based on the root hour.
   * @return The priority value.
   */
  double priority() const;
  
  /**
   * @brief Default constructor.
   */
  BBTask();

  /**
   * @brief Constructs a BBTask with a given configuration.
   * @param uid Unique identifier for the task.
   * @param config The branch-and-bound configuration.
   * @param constraints The problem constraints.
   */
  BBTask(int uid, const BBConfig &config, const BBConstraints &constraints);

  /**
   * @brief Comparison operator for ordering tasks in a priority queue.
   * @param other The other task to compare against.
   * @return True if this task has lower priority than the other.
   */
  bool operator<(const BBTask &other) const;

  /**
   * @brief Displays a summary of the task to the console for debugging.
   */
  void show() const;

  /**
   * @brief Displays the y and x vectors for a specific hour.
   * @param h The hour to display.
   * @param all If true, displays the vectors for all hours up to the current one.
   * @param mark If true, marks the current hour with "<<<".
   */
  void show_xy(int h, bool all = false, bool mark = false) const;

  /**
   * @brief Displays the y and x vectors for the current hour.
   * @param all If true, displays the vectors for all hours up to the current one.
   */
  void show_xy(bool all = false) const;
};

/**
 * @class BBPumpController
 * @brief Provides static utility functions for managing pump switching logic.
 *
 * This class contains the logic to translate the high-level pump count (y vector)
 * into a specific pump status configuration (x vector) while respecting
 * actuation constraints.
 */
class BBPumpController
{
public:
  /**
   * @brief Greedily switches off a specified number of pumps.
   * @param[in,out] x_new The pump status vector to modify.
   * @param pumps_sorted A list of pump indices, sorted by switching priority.
   * @param allowed_10 A vector tracking remaining allowed off-switches for each pump.
   * @param[in,out] counter_10 The number of pumps that still need to be switched off.
   * @return True if the requested number of pumps could be switched off, false otherwise.
   */
  static bool switchPumpsOff(int *x_new, const std::vector<int> &pumps_sorted, const std::vector<int> &allowed_10, int &counter_10);

  /**
   * @brief Greedily switches on a specified number of pumps.
   * @param[in,out] x_new The pump status vector to modify.
   * @param pumps_sorted A list of pump indices, sorted by switching priority.
   * @param allowed_01 A vector tracking remaining allowed on-switches for each pump.
   * @param[in,out] counter_01 The number of pumps that still need to be switched on.
   * @return True if the requested number of pumps could be switched on, false otherwise.
   */
  static bool switchPumpsOn(int *x_new, const std::vector<int> &pumps_sorted, const std::vector<int> &allowed_01, int &counter_01);

  /**
   * @brief Calculates the remaining allowed on/off switches for each pump based on historical actuations.
   * @param num_pumps The total number of pumps.
   * @param x The full low-level pump schedule.
   * @param current_h The current hour in the search.
   * @param[out] allowed_01 Vector to be filled with remaining on-switches.
   * @param[out] allowed_10 Vector to be filled with remaining off-switches.
   */
  static void computeAllowedSwitches(int num_pumps, const int *x, int current_h, std::vector<int> &allowed_01, std::vector<int> &allowed_10);

  /**
   * @brief Sorts pumps based on their eligibility for being switched on or off.
   * @param[in,out] pumps_sorted The vector of pump indices to be sorted.
   * @param allowed_01 Vector of remaining on-switches.
   * @param allowed_10 Vector of remaining off-switches.
   * @param switch_on True if sorting for a switch-on operation, false for a switch-off.
   */
  static void sortPumps(std::vector<int> &pumps_sorted, const std::vector<int> &allowed_01, const std::vector<int> &allowed_10, bool switch_on);
};

/**
 * @class BBSolver
 * @brief The main solver engine for the branch-and-bound algorithm.
 *
 * This class orchestrates the process of solving a `BBTask` by branching on possible
 * pump schedules, running hydraulic simulations, and bounding the search space based
 * on feasibility and cost.
 */
class BBSolver
{
public:
  /**
   * @brief Constructs the solver.
   * @param configRef A reference to the global configuration.
   * @param constraintsRef A reference to the problem constraints manager.
   * @param statsRef A reference to the statistics collector.
   */
  BBSolver(BBConfig &configRef, BBConstraints &constraintsRef, BBStatistics &statsRef);

  /**
   * @brief Solves a given branch-and-bound task.
   * @param[in,out] task The task to be solved. The state of the task will be modified during the search.
   */
  void solveTask(BBTask &task);

private:
  int niters;                 ///< Counter for iterations (currently unused).
  BBConfig &config;           ///< Reference to the configuration.
  BBConstraints &constraints; ///< Reference to the constraints manager.
  BBStatistics &stats;        ///< Reference to the statistics collector.

  /**
   * @brief Initializes the simulation and creates hydraulic snapshots for the fixed initial hours.
   * @param[in,out] task The task being processed.
   * @return A prune reason if the initial path is infeasible, otherwise `NONE`.
   */
  BBPrune::Reason initSnapshots(BBTask &task);

  /**
   * @brief Branches the search by finding the next feasible high-level pump schedule (y vector).
   * @param[in,out] task The task being processed.
   */
  void updateY(BBTask &task);

  /**
   * @brief Determines the concrete pump statuses (x vector) based on the high-level schedule (y vector).
   * @param[in,out] task The task being processed.
   */
  void updateX(BBTask &task);

  /**
   * @brief Processes one level (hour) of the search tree: loads a snapshot, updates pumps, and runs the simulation.
   * @param[in,out] task The task being processed.
   * @return A prune reason if the simulation leads to an infeasible state, otherwise `NONE`.
   */
  BBPrune::Reason processLevel(BBTask &task);

  /**
   * @brief Applies the current pump settings (x vector) to the EPANET project.
   * @param task The task being processed.
   * @param full_update If true, updates the pump patterns for all hours up to the current one.
   */
  void updatePumps(BBTask &task, bool full_update);

  /**
   * @brief Wraps the EPANET simulation for a single hour and performs feasibility and cost checks (bounding).
   * @param[in,out] task The task being processed.
   * @return A prune reason if the simulation is infeasible or the cost is too high, otherwise `NONE`.
   */
  BBPrune::Reason epanetSolve(BBTask &task);
};

/**
 * @brief Main entry point for processing a single task.
 * 
 * This function creates a `BBSolver` instance and uses it to solve the given task.
 * It acts as the primary worker function called by each MPI process.
 * 
 * @param[in,out] task The task to be solved.
 * @param config The global configuration.
 * @param constraints The problem constraints manager.
 * @param stats The statistics collector.
 */
void processTask(BBTask &task, BBConfig &config, BBConstraints &constraints, BBStatistics &stats);
