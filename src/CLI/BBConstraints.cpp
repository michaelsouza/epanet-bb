// BBConstraints.cpp
// This file contains the implementation of the BBConstraints class, which is responsible for managing
// and evaluating constraints in a branch-and-bound optimization process for water distribution networks.
// It includes methods for synchronizing best costs across MPI processes, checking pressures, levels,
// and stability of nodes and tanks, updating pump speed patterns, and calculating the total cost of
// pump operations.

#include "BBConstraints.h"
#include "BBConfig.h"
#include "Profiler.h"

#include "Elements/pattern.h"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mpi.h>
#include <sstream>
#include <thread>
#include <vector>

// Static map of prune reasons to labels
std::map<BBPrune::Reason, std::string> BBPrune::labels = {
    {BBPrune::NONE, "NONE"}, {BBPrune::PRESSURES, "PRESSURES"},   {BBPrune::LEVELS, "LEVELS"},    {BBPrune::STABILITY, "STABILITY"},
    {BBPrune::COST, "COST"}, {BBPrune::ACTUATIONS, "ACTUATIONS"}, {BBPrune::TIMESTEP, "TIMESTEP"}};


// Constructor
BBConstraints::BBConstraints(const BBConfig &config)
{
  // Initialize nodes and tanks with placeholder IDs
  nodes = {{"55", 0}, {"90", 0}, {"170", 0}};
  tanks = {{"65", 0}, {"165", 0}, {"265", 0}};
  pumps = {{"111", 0}, {"222", 0}, {"333", 0}};
  best_cost_local = std::numeric_limits<double>::max();

  // Retrieve node and tank IDs from the input file
  get_network_data(config.inpFile);

  best_cost_global = std::numeric_limits<double>::max();
  best_cost_local = std::numeric_limits<double>::max();
  sync_buffer_send = std::numeric_limits<double>::max();
  sync_buffer_recv = std::numeric_limits<double>::max();
  request_nonblocking = MPI_REQUEST_NULL;

  enable_cost_pruning = config.enable_cost_pruning;
  enable_global_sync = config.enable_global_sync;
  enable_timestep_check = config.enable_timestep_check;
}

void BBConstraints::poll_sync()
{
  if (!enable_global_sync) return;

  // Non-blocking check if the outstanding synchronization request has finished
  if (request_nonblocking != MPI_REQUEST_NULL)
  {
    int flag = 0;
    MPI_Test(&request_nonblocking, &flag, MPI_STATUS_IGNORE);
    if (flag)
    {
      best_cost_global = sync_buffer_recv;
      request_nonblocking = MPI_REQUEST_NULL;
    }
  }
}

void BBConstraints::sync_best()
{
  ProfileScope scope("sync_best");

  if (!enable_global_sync) return;

  // We are at a synchronized point in the code. Everyone calls this.
  // If a request is still active from a previous sync point, we MUST wait for it
  // to ensure all processes participate in the next collective call in the same order.
  if (request_nonblocking != MPI_REQUEST_NULL)
  {
    MPI_Wait(&request_nonblocking, MPI_STATUS_IGNORE);
    best_cost_global = sync_buffer_recv;
    request_nonblocking = MPI_REQUEST_NULL;
  }

  // Start a new synchronized non-blocking reduce
  sync_buffer_send = best_cost_local;
  MPI_Iallreduce(&sync_buffer_send, &sync_buffer_recv, 1, MPI_DOUBLE, MPI_MIN, MPI_COMM_WORLD, &request_nonblocking);
}

// Destructor
BBConstraints::~BBConstraints()
{
  if (request_nonblocking != MPI_REQUEST_NULL)
  {
    MPI_Wait(&request_nonblocking, MPI_STATUS_IGNORE);
  }
}

void BBConstraints::update_best(double cost, std::vector<int> x, std::vector<int> y)
{
  best_cost_local = std::min(best_cost_local, cost);
  best_x = x;
  best_y = y;
}

// Function to display the constraints
void BBConstraints::show() const
{
  // Print horizontal line separator
  Console::hline(Console::Color::BRIGHT_WHITE);

  // Print header
  Console::printf(Console::Color::BRIGHT_WHITE, "BBConstraints\n");

  // Print list of node IDs
  Console::printf(Console::Color::BRIGHT_WHITE, "Nodes: [ ");
  for (const auto &node : nodes)
    Console::printf(Console::Color::BRIGHT_WHITE, "%s ", node.first.c_str());
  Console::printf(Console::Color::BRIGHT_WHITE, "]\n");

  // Print list of tank IDs
  Console::printf(Console::Color::BRIGHT_WHITE, "Tanks: [ ");
  for (const auto &tank : tanks)
    Console::printf(Console::Color::BRIGHT_WHITE, "%s ", tank.first.c_str());
  Console::printf(Console::Color::BRIGHT_WHITE, "]\n");

  // Print list of pump IDs
  Console::printf(Console::Color::BRIGHT_WHITE, "Pumps: [ ");
  for (const auto &pump : pumps)
    Console::printf(Console::Color::BRIGHT_WHITE, "%s ", pump.first.c_str());
  Console::printf(Console::Color::BRIGHT_WHITE, "]\n");
}

void BBConstraints::get_network_data(std::string inpFile)
{
  Project p;
  CHK(p.load(inpFile.c_str()), "BBConstraints::get_network_elements_indices: Load project");

  Network *nw = p.getNetwork();

  // Get the user-defined Hydraulic timestep
  hyd_timestep = nw->option(Options::HYD_STEP);

  // Find node IDs
  for (auto &node : nodes)
  {
    const std::string &node_name = node.first;
    node.second = nw->indexOf(Element::NODE, node_name);
  }

  // Find tank IDs
  for (auto &tank : tanks)
  {
    const std::string &tank_name = tank.first;
    tank.second = nw->indexOf(Element::NODE, tank_name);
  }

  // Find pump IDs
  for (auto &pump : pumps)
  {
    const std::string &pump_name = pump.first;
    pump.second = nw->indexOf(Element::LINK, pump_name);
  }
}

// Function to display pressure status
void BBConstraints::show_pressures(bool is_feasible, const std::string &node_name, double pressure, double threshold)
{
  if (!is_feasible)
    Console::printf(Console::Color::RED, "  \u274C node[%3s]: %.2f < %.2f\n", node_name.c_str(), pressure, threshold);
  else
    Console::printf(Console::Color::GREEN, "  \u2705 node[%3s]: %.2f >= %.2f\n", node_name.c_str(), pressure, threshold);
}

void BBConstraints::show_best() const
{
  Console::printf(Console::Color::BRIGHT_WHITE, "💰 COST: local=%s, global=%s\n", fmt_cost(best_cost_local).c_str(),
                  fmt_cost(best_cost_global).c_str());
  Console::printf(Console::Color::BRIGHT_WHITE, "  X: [ ");
  for (const auto &x : best_x)
    Console::printf(Console::Color::BRIGHT_WHITE, "%d ", x);
  Console::printf(Console::Color::BRIGHT_WHITE, "]\n");
  Console::printf(Console::Color::BRIGHT_WHITE, "  Y: [ ");
  for (const auto &y : best_y)
    Console::printf(Console::Color::BRIGHT_WHITE, "%d ", y);
  Console::printf(Console::Color::BRIGHT_WHITE, "]\n");
}

// Function to display tank level status
void BBConstraints::show_levels(bool is_feasible, const std::string &tank_name, double level, double level_min, double level_max)
{
  if (!is_feasible)
    Console::printf(Console::Color::RED, "  \u274C tank[%3s]: %.3f not in [%.3f, %.3f]\n", tank_name.c_str(), level, level_min, level_max);
  else
    Console::printf(Console::Color::GREEN, "  \u2705 tank[%3s]: %.3f in [%.3f, %.3f]\n", tank_name.c_str(), level, level_min, level_max);
}

// Function to display stability status
void BBConstraints::show_stability(bool is_feasible, const std::string &tank_name, double level, double initial_level)
{
  if (!is_feasible)
    Console::printf(Console::Color::RED, "  \u274C tank[%3s]: %.2f < %.2f\n", tank_name.c_str(), level, initial_level);
  else
    Console::printf(Console::Color::GREEN, "  \u2705 tank[%3s]: %.2f >= %.2f\n", tank_name.c_str(), level, initial_level);
}

// Function to check node pressures
bool BBConstraints::check_pressures(Project &p, int verbose)
{
  if (verbose)
  {
    Console::printf(Console::Color::BRIGHT_WHITE, "\nChecking pressures: [ ");
    for (const auto &node : nodes)
    {
      Console::printf(Console::Color::BRIGHT_CYAN, "%s ", node.first.c_str());
    }
    Console::printf(Console::Color::BRIGHT_WHITE, "]\n");
  }

  std::map<std::string, double> thresholds = {{"55", 42}, {"90", 51}, {"170", 30}};
  bool all_ok = true;

  for (const auto &node : nodes)
  {
    const std::string &node_name = node.first;
    const int &node_index = node.second;
    double pressure;

    // Retrieve node pressure
    CHK(EN_getNodeValue(node_index, EN_PRESSURE, &pressure, &p), "Get node pressure");

    // Check if pressure meets the threshold
    bool is_feasible = pressure >= thresholds[node_name];
    if (!is_feasible)
    {
      all_ok = false;
    }

    // Display pressure status
    if (verbose) show_pressures(is_feasible, node_name, pressure, thresholds[node_name]);
  }

  return all_ok;
}

// Function to check tank levels
bool BBConstraints::check_levels(Project &p, int verbose)
{
  if (verbose)
  {
    Console::printf(Console::Color::BRIGHT_WHITE, "\nChecking levels: [ ");
    for (const auto &tank : tanks)
      Console::printf(Console::Color::BRIGHT_CYAN, "%s ", tank.first.c_str());
    Console::printf(Console::Color::BRIGHT_WHITE, "]\n");
  }

  const double level_min = 66.53;
  const double level_max = 71.53;
  bool all_ok = true;

  for (const auto &tank : tanks)
  {
    const std::string &tank_name = tank.first;
    const int &tank_index = tank.second;
    double level;

    // Retrieve tank level
    CHK(EN_getNodeValue(tank_index, EN_HEAD, &level, &p), "Get tank level");

    // Check if level is within acceptable range
    bool is_feasible = (level >= level_min) && (level <= level_max);
    if (!is_feasible)
    {
      all_ok = false;
    }

    // Display level status
    if (verbose) show_levels(is_feasible, tank_name, level, level_min, level_max);
  }

  return all_ok;
}

// Function to check tank stability
BBPrune::Reason BBConstraints::check_stability(Project &p, int verbose)
{
  if (verbose)
  {
    Console::printf(Console::Color::BRIGHT_WHITE, "\nChecking stability: [ ");
    for (const auto &tank : tanks)
      Console::printf(Console::Color::BRIGHT_CYAN, "%s ", tank.first.c_str());
    Console::printf(Console::Color::BRIGHT_WHITE, "]\n");
  }

  const double initial_level = 66.93;
  bool all_ok = true;

  for (const auto &tank : tanks)
  {
    const std::string &tank_name = tank.first;
    const int &tank_index = tank.second;
    double level;

    // Retrieve tank level
    CHK(EN_getNodeValue(tank_index, EN_HEAD, &level, &p), "Get tank level");

    // Check if level meets the initial stability condition
    bool is_feasible = level >= initial_level;
    if (!is_feasible)
    {
      all_ok = false;
    }

    // Display stability status
    if (verbose) show_stability(is_feasible, tank_name, level, initial_level);
  }

  return all_ok ? BBPrune::Reason::NONE : BBPrune::Reason::STABILITY;
}

// Function to check the cost
bool BBConstraints::check_cost(Project &p, double &cost, int verbose)
{
  cost = calc_cost(p);
  if (!enable_cost_pruning) return true; // Always feasible if cost pruning is disabled

  bool is_feasible = cost < std::min(best_cost_local, best_cost_global);
  if (verbose)
  {
    Console::printf(Console::Color::BRIGHT_WHITE, "\nChecking cost:\n");
    if (is_feasible)
    {
      if (best_cost_local > 999999999)
        Console::printf(Console::Color::GREEN, "  \u2705 cost=%.2f < cost_max=inf\n", cost);
      else
        Console::printf(Console::Color::GREEN, "  \u2705 cost=%.2f < cost_max=%.2f\n", cost, best_cost_local);
    }
    else if (best_cost_local > 999999999)
      Console::printf(Console::Color::RED, "  \u274C cost=%.2f >= cost_max=inf\n", cost);
    else
      Console::printf(Console::Color::RED, "  \u274C cost=%.2f >= cost_max=%.2f\n", cost, best_cost_local);
  }
  return is_feasible;
}

// Function to calculate the total cost of pump operations
double BBConstraints::calc_cost(Project &p) const
{
  Network *nw = p.getNetwork();
  double cost = 0.0;
  for (const auto &pump : pumps)
  {
    Pump *pump_link = (Pump *)nw->link(pump.second);
    cost += pump_link->pumpEnergy.adjustedTotalCost;
  }
  return cost;
}

// Function to update pump speed patterns
void BBConstraints::update_pumps(Project &p, const int h, const std::vector<int> &x, int verbose)
{
  ProfileScope scope("update_pumps");
  (void)verbose;

  // Update pump speed patterns based on vector x
  int j = 0;
  const size_t num_pumps = get_num_pumps();
  for (int i = 1; i <= h; i++)
  {
    const int *xi = &x[num_pumps * i];
    j = 0; // Reset index of the pump pattern
    for (auto &pump : pumps)
    {
      const auto &pump_name = pump.first;
      const auto &pump_index = pump.second;
      Pump *pump_link = (Pump *)p.getNetwork()->link(pump_index);
      FixedPattern *pattern = dynamic_cast<FixedPattern *>(pump_link->speedPattern);
      if (!pattern)
      {
        Console::printf(Console::Color::RED, "  Error: Pump %s does not have a FixedPattern speed pattern.\n", pump_name.c_str());
        continue;
      }

      // Retrieve new speed factor
      double factor_new = static_cast<double>(xi[j++]);
      // Retrieve old speed factor
      const int factor_id = i - 1; // pattern index is 0-based
      // Update speed factor
      pattern->setFactor(factor_id, factor_new);
    }
  }
}

bool BBConstraints::check_timestep(int dt, int verbose)
{
  bool is_feasible = (0 == dt) || (dt == hyd_timestep);
  if (verbose)
  {   
    Console::printf(Console::Color::BRIGHT_WHITE, "\nChecking timestep: %d\n", dt);
    if (is_feasible)
    {
      Console::printf(Console::Color::GREEN, "  \u2705 timestep=%d \u2208 {0 or hyd_timestep=%d}\n", dt, hyd_timestep);
    }
    else
    {
      Console::printf(Console::Color::RED, "  \u274C timestep=%d \u2209 {0, hyd_timestep=%d}\n", dt, hyd_timestep);
    }
  }

  return is_feasible;
}

BBPrune::Reason BBConstraints::check_feasibility(Project &p, int dt, const int h, double &cost, int verbose)
{
  ProfileScope scope("check_feasibility");
  poll_sync();
  (void)h;
  if (!check_levels(p, verbose)) return BBPrune::Reason::LEVELS;
  if (enable_timestep_check && !check_timestep(dt, verbose)) return BBPrune::Reason::TIMESTEP;
  if (!check_cost(p, cost, verbose)) return BBPrune::Reason::COST;
  if (!check_pressures(p, verbose)) return BBPrune::Reason::PRESSURES;
  return BBPrune::Reason::NONE;
}

void BBConstraints::to_json(char *fn) const
{
  int rank;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);

  if (rank == 0)
  {
    Console::printf(Console::Color::BRIGHT_GREEN, "💾 Writing best solution to file: %s\n", fn);
  }

  nlohmann::json j;
  j["best_cost"] = best_cost_local / 100.0; // convert from cents to dollars
  j["best_x"] = best_x;
  j["best_y"] = best_y;
  std::ofstream f(fn);
  f << j.dump(2);
}
