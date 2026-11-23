// src/CLI/BBConstraints.h
#pragma once

#include "BBConfig.h"
#include "Console.h"

#include "Core/network.h"
#include "Core/project.h"
#include "Elements/pump.h"
#include "epanet3.h"

#include <map>
#include <mpi.h>
#include <nlohmann/json.hpp>
#include <queue>
#include <string>

using Epanet::Project;

class BBPrune
{
public:
  enum Reason
  {
    NONE,
    PRESSURES,
    LEVELS,
    STABILITY,
    COST,
    ACTUATIONS,
    TIMESTEP,
    TANK_SATURATION,
    COST_TO_GO ///< Accumulated cost plus the cost-to-go bound reaches the incumbent
  };

  static std::map<Reason, std::string> labels;
};

/**
 * @brief Operating limits of the AnyTown case study.
 *
 * Single definition shared by the feasibility checks and by the cost-to-go
 * bound (whose validity depends on exactly these limits).
 */
struct BBOperatingLimits
{
  static constexpr double tank_level_min = 66.53;   ///< Minimum tank head (m)
  static constexpr double tank_level_max = 71.53;   ///< Maximum tank head (m)
  static constexpr double tank_level_final = 66.93; ///< Minimum final tank head (m)

  /// Minimum pressure (m) at each pressure-constrained junction, by node ID
  static const std::map<std::string, double> &pressure_thresholds();
};

/**
 * @brief Parameters and status of the mass-balance cost-to-go bound.
 *
 * See the Supplemental Materials of the article for the statement and
 * proof. Values are in network units (m, m3/h, kWh) and costs in the
 * simulator's currency unit (cents for AnyTown).
 */
struct CostToGoInfo
{
  bool requested = false;     ///< Bound requested by the configuration
  bool active = false;        ///< Bound built and valid for this network
  std::string status;         ///< Reason when inactive, "active" otherwise
  double e_min = 0.0;         ///< Smallest energy per unit volume (kWh/m3)
  double head_star = 0.0;     ///< H* (m), largest over the pumps
  double flow_star = 0.0;     ///< q* (m3/h), smallest over the pumps
  double source_head = 0.0;   ///< Reservoir head h_res (m)
  double min_constrained_head = 0.0; ///< Lowest head implied by level/pressure limits (m)
  double max_unconstrained_demand = 0.0; ///< \bar D (m3/h)
  double root_bound = 0.0;    ///< T_0 at the initial storage
  int grid_points = 0;        ///< Storage grid size G
  int stages = 0;             ///< Hydraulic steps N

  nlohmann::json to_json() const;
};

/**
 * @brief Class to handle constraint checking for branch and bound optimization
 */
class BBConstraints
{
public:
  std::map<std::string, int> nodes; ///< Map of node names to indices
  std::map<std::string, int> tanks; ///< Map of tank names to indices
  std::map<std::string, int> pumps; ///< Map of pump names to indices
  std::string inpFile;              ///< Path to input file
  double best_cost_local;           ///< Local best cost
  double best_cost_global;          ///< Global best cost
  std::vector<int> best_x;          ///< Reconstructed binary witness
  std::vector<int> best_canonical_x; ///< Canonical statuses simulated hydraulically
  std::vector<int> best_y;          ///< Best aggregate pump schedule
  
  bool enable_cost_pruning;
  bool enable_cost_to_go;           ///< Cost-to-go bound in use (requested and valid)
  int h_max = 24;                   ///< Scheduling horizon (hours)
  std::string switch_count_convention = "periodic"; ///< "periodic" or "single_day"
  int max_switch_count_per_pump = 0; ///< Limit under switch_count_convention

  /// Default number of storage grid points of the cost-to-go table
  static constexpr int CTG_DEFAULT_GRID = 20001;
  /// Factor applied to the unit energy cost of the relaxation. It absorbs the
  /// hydraulic convergence tolerance (Remark S2 of the proof): the simulated
  /// mass balance and pump heads hold only up to the solver tolerance.
  static constexpr double CTG_COST_SAFETY = 0.999;
  /// Table value of infeasible states (F = +infinity)
  static constexpr double CTG_INFINITY = 1e300;

  CostToGoInfo ctg_info;            ///< Parameters and status of the bound
  int ctg_stages = 0;               ///< Hydraulic steps in the horizon (N)
  int ctg_grid = 0;                 ///< Storage grid points (G)
  double ctg_smin = 0.0;            ///< Aggregate storage at the minimum level (m3)
  double ctg_cell = 0.0;            ///< Storage grid spacing delta (m3)
  double ctg_sfinal_offset = 0.0;   ///< S_fin - S_min (m3)
  double ctg_area = 0.0;            ///< Tank area (m2), identical tanks
  std::vector<double> ctg_demand;   ///< d_n: demand volume of step n (m3)
  std::vector<double> ctg_unit_cost; ///< Safety * price_n * e_min (cost per m3)
  std::vector<double> ctg_table;    ///< T_n[i] at index n * G + i

  /**
   * @brief Builds the cost-to-go table for the network, after checking the
   *        conditions of Lemma S3. Disables the bound (with a warning on rank 0)
   *        when a condition fails.
   * @return true if the bound is active
   */
  bool build_cost_to_go(Network *nw, int grid_points = CTG_DEFAULT_GRID);

  /**
   * @brief Backward recursion of Section 1.5 of the proof, O(N G).
   * @param unit_cost Cost per m3 pumped in each step
   * @param demand Demand volume of each step (m3)
   * @param cell Grid spacing delta (m3); S_j = j * delta relative to S_min
   * @param sfinal_offset S_fin - S_min (m3)
   * @param grid_points Number of grid points G
   * @return Table with T_n[i] at index n * G + i, n = 0..N
   */
  static std::vector<double> tabulate_cost_to_go(const std::vector<double> &unit_cost,
                                                 const std::vector<double> &demand, double cell,
                                                 double sfinal_offset, int grid_points);

  /// T_n at aggregate storage S (m3); 0 when the bound is inactive, n is out
  /// of range or the state is infeasible in the relaxation
  double lookup_cost_to_go(int n, double storage) const;

  /// Lower bound on the cost still to be paid from time t (0 when unknown)
  double cost_to_go(Project &p, int t) const;
  bool enable_global_sync;
  bool enable_timestep_check;
  
  int hyd_timestep;                 ///< User-defined hydraulic timestep
  double sync_buffer_send;          ///< Send buffer for non-blocking synchronization
  double sync_buffer_recv;          ///< Receive buffer for non-blocking synchronization
  MPI_Request request_nonblocking;

  /**
   * @brief Synchronizes the best solution found among all processes
   */
  void sync_best();

  /**
   * @brief Non-collective check for finished synchronization requests
   */
  void poll_sync();

  /**
   * @brief Constructs constraints checker for the given input file
   * @param inpFile Path to the EPANET input file
   */
  BBConstraints(const BBConfig &config);
  ~BBConstraints();

  /**
   * @brief Verifies that node pressures meet minimum requirements
   * @param verbose If true, prints detailed constraint violation info
   * @return true if all pressure constraints are satisfied
   */
  bool check_pressures(Project &p, int verbose = 0);

  /**
   * @brief Verifies if the simulation timestep is complete (dt == hyd_timestep)
   * @param verbose If true, prints detailed constraint violation info
   * @return true if all tank level constraints are satisfied
   */
  bool check_timestep(int dt, int verbose = 0);

  /**
   * @brief Verifies that tank levels are within bounds
   * @param verbose If true, prints detailed constraint violation info
   * @return true if all tank level constraints are satisfied
   */
  bool check_levels(Project &p, int verbose = 0);

  /**
   * @brief Detects corrective flow blocking at a tank boundary
   * @param verbose If true, prints the tank and intervention cause
   * @return true if no saturation intervention occurred in the latest solve
   */
  bool check_tank_saturation(const Project &p, int verbose = 0);

  /**
   * @brief Verifies that final tank levels match initial levels
   * @param verbose If true, prints detailed constraint violation info
   * @return true if all tanks return to initial levels
   */
  BBPrune::Reason check_stability(Project &p, int verbose = 0);

  /**
   * @brief Compares the accumulated cost, and the accumulated cost plus the
   *        cost-to-go bound at time t, with the incumbent
   * @param cost Output: accumulated cost
   * @param verbose If true, prints detailed constraint violation info
   * @param t Simulation time (s) of the state; the bound is skipped if t < 0
   * @return NONE, COST (accumulated cost alone reaches the incumbent) or
   *         COST_TO_GO (only the bound does)
   */
  BBPrune::Reason check_cost(Project &p, double &cost, int verbose = 0, int t = -1);

  /**
   * @brief Checks if the current state of the network is feasible
   * @param p Project containing the network
   * @param dt Time step
   * @param h Current time period
   * @param cost Cost of the current state
   * @return PruneType of the reason for pruning
   */
  BBPrune::Reason check_feasibility(Project &p, int dt, const int h, double &cost, int verbose, int t = -1);

  /**
   * @brief Loads node and tank IDs from input file
   * @param inpFile Path to the EPANET input file
   */
  void get_network_data(std::string inpFile);

  /**
   * @brief Calculates total pump operation cost
   * @return Total operational cost
   */
  double calc_cost(Project &p) const;

  /**
   * @brief Gets number of nodes in network
   * @return Number of nodes
   */
  int get_num_nodes() const
  {
    return (int)nodes.size();
  }

  /**
   * @brief Gets number of tanks in network
   * @return Number of tanks
   */
  int get_num_tanks() const
  {
    return (int)tanks.size();
  }

  /**
   * @brief Gets number of pumps in network
   * @return Number of pumps
   */
  int get_num_pumps() const
  {
    return (int)pumps.size();
  }

  /**
   * @brief Displays constraint information
   */
  void show() const;

  std::string fmt_cost(double cost) const
  {
    char fmt[256];
    if (cost > 999999999)
      sprintf(fmt, "INFINITY");
    else
      sprintf(fmt, "%.2f", cost);
    return fmt;
  }
  /**
   * @brief Displays the best solution found
   */
  void show_best() const;

  /**
   * @brief Updates pump statuses for the initial time period until the current time period
   * @param p Project containing the network
   * @param h Current time period
   * @param x Vector of pump statuses (0/1)
   * @param verbose If true, prints status updates
   */
  void update_pumps(Project &p, const int h, const std::vector<int> &x, int verbose);

  /**
   * @brief Updates the best solution found
   * @param cost Cost of the new solution
   * @param x Pump statuses of the new solution
   * @param y Pump speed patterns of the new solution
   */
  void update_best(double cost, std::vector<int> x, std::vector<int> y,
                   std::vector<int> canonical_x = {});

  /**
   * @brief Writes the best solution to a JSON file
   * @param fn Path to the output file
   */
  void to_json(char *fn, bool search_conclusive = true) const;
  nlohmann::json to_json_value(bool search_conclusive = true) const;

private:
  /**
   * @brief Helper to display pressure constraint status
   * @param is_feasible Whether constraint is satisfied
   * @param node_name Name of node being checked
   * @param pressure Current pressure at node
   * @param threshold Minimum required pressure
   */
  void show_pressures(bool is_feasible, const std::string &node_name, double pressure, double threshold);

  /**
   * @brief Helper to display tank level constraint status
   * @param is_feasible Whether constraint is satisfied
   * @param tank_name Name of tank being checked
   * @param level Current tank level
   * @param level_min Minimum allowed level
   * @param level_max Maximum allowed level
   */
  void show_levels(bool is_feasible, const std::string &tank_name, double level, double level_min, double level_max);

  /**
   * @brief Helper to display tank stability constraint status
   * @param is_feasible Whether constraint is satisfied
   * @param tank_name Name of tank being checked
   * @param level Final tank level
   * @param initial_level Initial tank level
   */
  void show_stability(bool is_feasible, const std::string &tank_name, double level, double initial_level);
};
