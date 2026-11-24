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
#include "Elements/curve.h"
#include "Elements/junction.h"
#include "Elements/reservoir.h"
#include "Elements/tank.h"
#include "Core/constants.h"

#include <cmath>

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
    {BBPrune::COST, "COST"}, {BBPrune::ACTUATIONS, "ACTUATIONS"}, {BBPrune::TIMESTEP, "TIMESTEP"},
    {BBPrune::TANK_SATURATION, "TANK_SATURATION"}, {BBPrune::COST_TO_GO, "COST_TO_GO"}};

const std::map<std::string, double> &BBOperatingLimits::pressure_thresholds()
{
  static const std::map<std::string, double> thresholds = {{"55", 42.0}, {"90", 51.0}, {"170", 30.0}};
  return thresholds;
}

nlohmann::json CostToGoInfo::to_json() const
{
  return {{"requested", requested},
          {"active", active},
          {"status", status},
          {"e_min_kwh_per_m3", e_min},
          {"head_star_m", head_star},
          {"flow_star_m3h", flow_star},
          {"source_head_m", source_head},
          {"min_constrained_head_m", min_constrained_head},
          {"max_unconstrained_demand_m3h", max_unconstrained_demand},
          {"root_bound", root_bound},
          {"grid_points", grid_points},
          {"stages", stages},
          {"cost_safety_factor", BBConstraints::CTG_COST_SAFETY}};
}

namespace
{
bool is_rank_zero()
{
  int initialized = 0;
  MPI_Initialized(&initialized);
  if (!initialized) return true;
  int rank = 0;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  return rank == 0;
}
} // namespace

// Constructor
BBConstraints::BBConstraints(const BBConfig &config)
{
  // Initialize nodes and tanks with placeholder IDs
  for (const auto &threshold : BBOperatingLimits::pressure_thresholds())
    nodes[threshold.first] = 0;
  tanks = {{"65", 0}, {"165", 0}, {"265", 0}};
  pumps = {{"111", 0}, {"222", 0}, {"333", 0}};
  best_cost_local = std::numeric_limits<double>::max();

  enable_cost_pruning = config.enable_cost_pruning;
  enable_global_sync = config.enable_global_sync;
  enable_timestep_check = config.enable_timestep_check;
  h_max = config.h_max;
  switch_count_convention = config.switch_count_convention();
  max_switch_count_per_pump = config.max_switch_count_per_pump();

  // The bound refines the cost test, so it needs cost pruning. It becomes
  // active only after build_cost_to_go has validated it for the network.
  enable_cost_to_go = false;
  ctg_info.requested = config.enable_cost_pruning && config.enable_cost_to_go;
  if (!config.enable_cost_to_go)
    ctg_info.status = "disabled (BB_ENABLE_COST_TO_GO=0)";
  else if (!config.enable_cost_pruning)
    ctg_info.status = "disabled (cost pruning off)";

  // Retrieve node and tank IDs from the input file
  get_network_data(config.inpFile);

  best_cost_global = std::numeric_limits<double>::max();
  best_cost_local = std::numeric_limits<double>::max();
  sync_buffer_send = std::numeric_limits<double>::max();
  sync_buffer_recv = std::numeric_limits<double>::max();
  request_nonblocking = MPI_REQUEST_NULL;
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

void BBConstraints::update_best(double cost, std::vector<int> x,
                                std::vector<int> y,
                                std::vector<int> canonical_x)
{
  if (cost >= best_cost_local)
    return;
  best_cost_local = cost;
  best_x = std::move(x);
  best_y = std::move(y);
  best_canonical_x = std::move(canonical_x);
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

  if (ctg_info.requested) build_cost_to_go(nw);
}

// Cost-to-go lower bound.
//
// Statement and proof: Supplemental Materials of the article.
//
// Relaxation: the identical cylindrical tanks are merged into one store S
// (m3). Over hydraulic step n the pumped volume v_n >= 0 satisfies the mass
// balance S_{n+1} = S_n + v_n - d_n (Lemma S1), where d_n is the
// schedule-independent demand volume. The level limits give
// S_min <= S_n <= S_max and the final-level condition S_N >= S_fin. Each
// pumped m3 costs at least price_n * e_min (Corollary S1, which needs the head
// floor of Lemma S3). F_n(S) is the optimal value of this relaxation, a lower
// bound on the cost still to be paid by any feasible completion (Theorem S1).
// The table T_n of Section 1.5 is a lower bound on F_n (Proposition S1).
bool BBConstraints::build_cost_to_go(Network *nw, int grid_points)
{
  using L = BBOperatingLimits;
  enable_cost_to_go = false;
  ctg_table.clear();
  ctg_info.requested = true;
  ctg_info.active = false;
  ctg_info.grid_points = grid_points;

  const auto disable = [this](const std::string &why)
  {
    ctg_info.status = "disabled (" + why + ")";
    if (is_rank_zero())
      Console::printf(Console::Color::BRIGHT_RED, "Warning: cost-to-go bound disabled: %s\n", why.c_str());
    return false;
  };

  // --- Model assumptions that can be read from the input data
  if (grid_points < 2) return disable("storage grid needs at least two points");
  if (hyd_timestep <= 0 || (h_max * 3600) % hyd_timestep != 0)
    return disable("horizon is not a multiple of the hydraulic step");
  if (nw->option(Options::FLOW_UNITS) != Options::CMH)
    return disable("flow units must be CMH (volumes in m3)");
  if (nw->option(Options::DEMAND_MODEL) != "FIXED") return disable("demand model is not FIXED (A1)");
  if (nw->option(Options::LEAKAGE_MODEL) != "NONE") return disable("pipe leakage is modelled (A2)");

  const double ucf_len = nw->ucf(Units::LENGTH);
  const double ucf_flow = nw->ucf(Units::FLOW);
  const double ucf_pres = nw->ucf(Units::PRESSURE);

  // --- Tanks: identical cylinders whose network limits lie strictly outside
  //     the operating limits, so EPANET never clamps a level (A3)
  if (tanks.empty()) return disable("no tanks");
  ctg_area = 0.0;
  double initial_head_sum = 0.0;
  for (const auto &[name, index] : tanks)
  {
    Tank *tank = index >= 0 ? dynamic_cast<Tank *>(nw->node(index)) : nullptr;
    if (!tank) return disable("tank " + name + " not found");
    if (tank->volCurve) return disable("tank " + name + " has a volume curve");
    const double area = tank->area * ucf_len * ucf_len;
    if (ctg_area == 0.0) ctg_area = area;
    if (std::abs(area - ctg_area) > 1e-9 * ctg_area) return disable("tanks have different areas");
    if (!(tank->minHead * ucf_len < L::tank_level_min && tank->maxHead * ucf_len > L::tank_level_max))
      return disable("network limits of tank " + name + " are not outside the operating limits (A3)");
    initial_head_sum += tank->initHead * ucf_len;
  }

  // --- Junctions: no emitters (A2); heads implied by the pressure constraints
  double min_constrained_head = L::tank_level_min;
  for (const auto &[name, index] : nodes)
  {
    Junction *junc = index >= 0 ? dynamic_cast<Junction *>(nw->node(index)) : nullptr;
    if (!junc) return disable("pressure-constrained junction " + name + " not found");
    const double head = junc->elev * ucf_len + L::pressure_thresholds().at(name) / ucf_pres * ucf_len;
    min_constrained_head = std::min(min_constrained_head, head);
  }
  for (Node *node : nw->nodes)
  {
    Junction *junc = dynamic_cast<Junction *>(node);
    if (junc && junc->hasEmitter()) return disable("junction " + junc->name + " has an emitter (A2)");
  }

  // --- Pumps: smallest energy per unit volume (Lemma S2) and head floor
  //     H*, q* of Lemma S3. Energy uses the formula of
  //     PumpEnergy::updateEnergyUsage: e(q) = kappa * H(q) / eta(q).
  const double kappa = nw->option(Options::SPEC_GRAVITY) / 8.814 * KWperHP / ucf_len / ucf_flow;
  struct PumpCurveData
  {
    Pump *pump;
    double q_last;   // last breakpoint q_K (m3/h)
    double eta_last; // eta(q_K), fraction
  };
  std::vector<PumpCurveData> pump_data;
  double source_head = -std::numeric_limits<double>::max();
  double e_min = std::numeric_limits<double>::max();
  for (const auto &[name, index] : pumps)
  {
    Pump *pump = index >= 0 ? dynamic_cast<Pump *>(nw->link(index)) : nullptr;
    if (!pump) return disable("pump " + name + " not found");
    // Same classification as PumpCurve::setupCurve, which runs only when the
    // solver is initialized
    Curve *hc = pump->pumpCurve.curve;
    if (!hc || pump->pumpCurve.horsepower > 0.0 || hc->size() == 1 || (hc->size() == 3 && hc->x(0) == 0.0))
      return disable("pump " + name + " does not have a piecewise-linear (custom) curve");
    Reservoir *source = dynamic_cast<Reservoir *>(pump->fromNode);
    if (!source) return disable("pump " + name + " does not draw from a reservoir (A2)");
    double head_factor = 1.0;
    if (source->headPattern)
      for (int k = 0; k < source->headPattern->size(); ++k)
        head_factor = std::max(head_factor, source->headPattern->factor(k));
    source_head = std::max(source_head, source->elev * head_factor * ucf_len);

    Curve *ec = pump->efficCurve;
    const auto eta = [&](double q)
    {
      if (!ec) return nw->option(Options::PUMP_EFFICIENCY) / 100.0;
      return std::max(1.0, std::min(100.0, ec->getYofX(q))) / 100.0;
    };
    const auto head = [&](double q)
    {
      double slope, intercept;
      hc->findSegment(q, slope, intercept);
      return intercept + slope * q;
    };
    std::vector<double> breakpoints;
    for (int k = 0; k < hc->size(); ++k) breakpoints.push_back(hc->x(k));
    if (ec)
      for (int k = 0; k < ec->size(); ++k) breakpoints.push_back(ec->x(k));
    double q_last = 0.0;
    for (double q : breakpoints)
    {
      q_last = std::max(q_last, q);
      if (q > 0.0) e_min = std::min(e_min, kappa * head(q) / eta(q));
    }
    pump_data.push_back({pump, q_last, eta(q_last)});
  }
  // A reservoir must connect to the network only through the pump station (A2)
  for (Link *link : nw->links)
  {
    if (link->type() == Link::PUMP) continue;
    if (dynamic_cast<Reservoir *>(link->fromNode) || dynamic_cast<Reservoir *>(link->toNode))
      return disable("link " + link->name + " connects a reservoir without a pump (A2)");
  }

  // Lemma S3: beyond q_K the efficiency stays at eta(q_K) and the head follows
  // the last curve segment, so e(q) >= e_min iff H(q) >= H* = e_min eta(q_K) / kappa.
  double head_star = 0.0, flow_star = std::numeric_limits<double>::max();
  for (const auto &data : pump_data)
  {
    double slope, intercept;
    data.pump->pumpCurve.curve->findSegment(data.q_last + 1.0, slope, intercept);
    if (slope >= 0.0) return disable("pump curve of " + data.pump->name + " does not decrease");
    const double h_star = e_min * data.eta_last / kappa;
    head_star = std::max(head_star, h_star);
    flow_star = std::min(flow_star, (h_star - intercept) / slope);
  }

  // --- Demand volume and energy price per hydraulic step. Patterns are
  //     evaluated as in HydEngine (init, then advance to each step time).
  ctg_stages = h_max * 3600 / hyd_timestep;
  ctg_demand.assign(ctg_stages, 0.0);
  ctg_unit_cost.assign(ctg_stages, 0.0);
  const double hrs = hyd_timestep / 3600.0;
  const double multiplier = nw->option(Options::DEMAND_MULTIPLIER);
  const int demand_pattern = nw->option(Options::DEMAND_PATTERN);
  const int price_pattern = nw->option(Options::ENERGY_PRICE_PATTERN);
  for (Pattern *pattern : nw->patterns)
    pattern->init(nw->option(Options::PATTERN_STEP), nw->option(Options::PATTERN_START));
  double max_unconstrained_demand = 0.0;
  for (int n = 0; n <= ctg_stages; ++n)
  {
    const int t = n * hyd_timestep;
    for (Pattern *pattern : nw->patterns) pattern->advance(t);
    const double global_factor = demand_pattern >= 0 ? nw->pattern(demand_pattern)->currentFactor() : 1.0;
    double total_demand = 0.0, unconstrained_demand = 0.0;
    for (Node *node : nw->nodes)
    {
      Junction *junc = dynamic_cast<Junction *>(node);
      if (!junc) continue;
      double demand = 0.0;
      for (Demand &dem : junc->demands) demand += dem.getFullDemand(multiplier, global_factor) * ucf_flow;
      total_demand += demand;
      if (!nodes.count(junc->name)) unconstrained_demand += std::max(0.0, demand);
    }
    max_unconstrained_demand = std::max(max_unconstrained_demand, unconstrained_demand);
    if (n == ctg_stages) break;

    double price = std::numeric_limits<double>::max();
    for (const auto &data : pump_data)
    {
      // Same rule as PumpEnergy::findCostFactor
      const double per_kwh = data.pump->costPerKwh > 0.0 ? data.pump->costPerKwh : nw->option(Options::ENERGY_PRICE);
      double factor = price_pattern >= 0 ? nw->pattern(price_pattern)->currentFactor() : 1.0;
      if (data.pump->costPattern) factor = data.pump->costPattern->currentFactor();
      price = std::min(price, per_kwh * factor);
    }
    ctg_demand[n] = total_demand * hrs;
    ctg_unit_cost[n] = CTG_COST_SAFETY * price * e_min;
  }

  ctg_info.e_min = e_min;
  ctg_info.head_star = head_star;
  ctg_info.flow_star = flow_star;
  ctg_info.source_head = source_head;
  ctg_info.min_constrained_head = min_constrained_head;
  ctg_info.max_unconstrained_demand = max_unconstrained_demand;
  ctg_info.stages = ctg_stages;

  // --- Conditions of Lemma S3
  // (i) h_res + H* below the minimum tank level and every constrained head
  if (!(source_head + head_star < min_constrained_head))
    return disable("Lemma S3 (i) fails: h_res + H* = " + std::to_string(source_head + head_star) +
                   " m is not below " + std::to_string(min_constrained_head) + " m");
  // (ii) q* above the peak demand of the junctions without a pressure constraint
  if (!(flow_star > max_unconstrained_demand))
    return disable("Lemma S3 (ii) fails: q* = " + std::to_string(flow_star) + " m3/h is not above " +
                   std::to_string(max_unconstrained_demand) + " m3/h");

  // --- Storage grid and table
  const int num_tanks = static_cast<int>(tanks.size());
  ctg_grid = grid_points;
  ctg_smin = num_tanks * ctg_area * L::tank_level_min;
  ctg_cell = num_tanks * ctg_area * (L::tank_level_max - L::tank_level_min) / (ctg_grid - 1);
  ctg_sfinal_offset = num_tanks * ctg_area * (L::tank_level_final - L::tank_level_min);
  ctg_table = tabulate_cost_to_go(ctg_unit_cost, ctg_demand, ctg_cell, ctg_sfinal_offset, ctg_grid);

  enable_cost_to_go = true;
  ctg_info.active = true;
  ctg_info.status = "active";
  ctg_info.root_bound = lookup_cost_to_go(0, ctg_area * initial_head_sum);

  if (is_rank_zero())
    Console::printf(Console::Color::BRIGHT_WHITE,
                    "Cost-to-go bound: active, e_min=%.5f kWh/m3, H*=%.3f m, q*=%.1f m3/h, root bound=%.2f\n",
                    e_min, head_star, flow_star, ctg_info.root_bound / 100.0);
  return true;
}

std::vector<double> BBConstraints::tabulate_cost_to_go(const std::vector<double> &unit_cost,
                                                       const std::vector<double> &demand, double cell,
                                                       double sfinal_offset, int grid_points)
{
  // Storage offsets relative to S_min: S_j = j * cell, with S_{-1} = S_0.
  //   T_N[j] = 0 if S_j >= S_fin, +inf otherwise
  //   T_n[i] = min_j { c_n max(0, S_{j-1} - S_i + d_n) + T_{n+1}[j] }
  // Targets j with S_{j-1} <= s0 = S_i - d_n are reached without pumping
  // (prefix minimum of T_{n+1}); the others cost c_n (S_{j-1} - s0) (suffix
  // minimum of c_n S_{j-1} + T_{n+1}[j]). O(N G) overall.
  const int stages = static_cast<int>(unit_cost.size());
  const int G = grid_points;
  std::vector<double> table(static_cast<size_t>(stages + 1) * G, 0.0);
  double *last = &table[static_cast<size_t>(stages) * G];
  for (int j = 0; j < G; ++j)
    last[j] = (j * cell >= sfinal_offset - 1e-9) ? 0.0 : CTG_INFINITY;

  std::vector<double> suffix(G + 1), prefix(G);
  for (int n = stages - 1; n >= 0; --n)
  {
    const double *next = &table[static_cast<size_t>(n + 1) * G];
    double *cur = &table[static_cast<size_t>(n) * G];
    const double c = unit_cost[n];
    suffix[G] = CTG_INFINITY;
    for (int j = G - 1; j >= 0; --j)
    {
      const double s_prev = (j > 0 ? j - 1 : 0) * cell;
      suffix[j] = std::min(suffix[j + 1], next[j] >= CTG_INFINITY ? CTG_INFINITY : c * s_prev + next[j]);
    }
    for (int j = 0; j < G; ++j)
      prefix[j] = j == 0 ? next[0] : std::min(prefix[j - 1], next[j]);
    for (int i = 0; i < G; ++i)
    {
      const double s0 = i * cell - demand[n];
      // Number of targets reachable without pumping: j = 0 .. floor(s0 / cell) + 1
      int free_targets = 0;
      if (s0 >= 0.0)
        free_targets = static_cast<int>(std::min<double>(G, std::floor(s0 / cell) + 2.0));
      double best = free_targets > 0 ? prefix[free_targets - 1] : CTG_INFINITY;
      if (free_targets < G && suffix[free_targets] < CTG_INFINITY)
        best = std::min(best, suffix[free_targets] - c * s0);
      cur[i] = best;
    }
  }
  return table;
}

double BBConstraints::lookup_cost_to_go(int n, double storage) const
{
  if (!enable_cost_to_go || n < 0 || n >= ctg_stages) return 0.0;
  // T_n at the smallest grid point not below the storage (F_n is non-increasing)
  int i = static_cast<int>(std::ceil((storage - ctg_smin) / ctg_cell));
  i = std::max(0, std::min(ctg_grid - 1, i));
  const double f = ctg_table[static_cast<size_t>(n) * ctg_grid + i];
  return f >= CTG_INFINITY ? 0.0 : f;
}

double BBConstraints::cost_to_go(Project &p, int t) const
{
  if (!enable_cost_to_go || t < 0 || t % hyd_timestep != 0) return 0.0;
  double sum_levels = 0.0;
  for (const auto &tank : tanks)
  {
    double level;
    EN_getNodeValue(tank.second, EN_HEAD, &level, &p);
    sum_levels += level;
  }
  return lookup_cost_to_go(t / hyd_timestep, ctg_area * sum_levels);
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

  const auto &thresholds = BBOperatingLimits::pressure_thresholds();
  bool all_ok = true;

  for (const auto &node : nodes)
  {
    const std::string &node_name = node.first;
    const int &node_index = node.second;
    double pressure;

    // Retrieve node pressure
    CHK(EN_getNodeValue(node_index, EN_PRESSURE, &pressure, &p), "Get node pressure");

    // Check if pressure meets the threshold
    const double threshold = thresholds.at(node_name);
    bool is_feasible = pressure >= threshold;
    if (!is_feasible)
    {
      all_ok = false;
    }

    // Display pressure status
    if (verbose) show_pressures(is_feasible, node_name, pressure, threshold);
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

  // Operating limits. They are stricter than the tank limits declared in
  // networks/any-town.inp (61.53/75.53 m), so EPANET never clamps a level and
  // every excursion is detected here.
  const double level_min = BBOperatingLimits::tank_level_min;
  const double level_max = BBOperatingLimits::tank_level_max;
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

bool BBConstraints::check_tank_saturation(const Project &p, int verbose)
{
  const auto events = p.tankSaturationEvents();
  if (verbose && !events.empty())
  {
    Console::printf(Console::Color::BRIGHT_WHITE,
                    "\nChecking tank saturation interventions:\n");
    for (const auto &event : events)
    {
      const char *cause =
          event.type ==
                  TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM
              ? "blocked inflow at maximum"
              : "blocked outflow at minimum";
      Console::printf(Console::Color::RED, "  \u274C tank[%s]: %s\n",
                      event.tank_name.c_str(), cause);
    }
  }
  return events.empty();
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

  const double initial_level = BBOperatingLimits::tank_level_final;
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
BBPrune::Reason BBConstraints::check_cost(Project &p, double &cost, int verbose, int t)
{
  cost = calc_cost(p);
  if (!enable_cost_pruning) return BBPrune::Reason::NONE; // Always feasible if cost pruning is disabled

  const double incumbent = std::min(best_cost_local, best_cost_global);
  BBPrune::Reason reason = BBPrune::Reason::NONE;
  double bound = 0.0;
  if (cost >= incumbent)
    reason = BBPrune::Reason::COST;
  else if (enable_cost_to_go && incumbent < std::numeric_limits<double>::max())
  {
    bound = cost_to_go(p, t);
    if (cost + bound >= incumbent) reason = BBPrune::Reason::COST_TO_GO;
  }
  if (verbose)
  {
    Console::printf(Console::Color::BRIGHT_WHITE, "\nChecking cost:\n");
    const std::string cost_max = fmt_cost(incumbent);
    if (reason == BBPrune::Reason::NONE)
      Console::printf(Console::Color::GREEN, "  \u2705 cost=%.2f + cost_to_go=%.2f < cost_max=%s\n", cost, bound,
                      cost_max.c_str());
    else if (reason == BBPrune::Reason::COST)
      Console::printf(Console::Color::RED, "  \u274C cost=%.2f >= cost_max=%s\n", cost, cost_max.c_str());
    else
      Console::printf(Console::Color::RED, "  \u274C cost=%.2f + cost_to_go=%.2f >= cost_max=%s\n", cost, bound,
                      cost_max.c_str());
  }
  return reason;
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

BBPrune::Reason BBConstraints::check_feasibility(Project &p, int dt, const int h, double &cost, int verbose, int t)
{
  ProfileScope scope("check_feasibility");
  poll_sync();
  (void)h;
  if (!check_tank_saturation(p, verbose)) return BBPrune::Reason::TANK_SATURATION;
  if (!check_levels(p, verbose)) return BBPrune::Reason::LEVELS;
  if (enable_timestep_check && !check_timestep(dt, verbose)) return BBPrune::Reason::TIMESTEP;
  const BBPrune::Reason cost_reason = check_cost(p, cost, verbose, t);
  if (cost_reason != BBPrune::Reason::NONE) return cost_reason;
  if (!check_pressures(p, verbose)) return BBPrune::Reason::PRESSURES;
  return BBPrune::Reason::NONE;
}

void BBConstraints::to_json(char *fn, bool search_conclusive) const
{
  int rank;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);

  if (rank == 0)
  {
    Console::printf(Console::Color::BRIGHT_GREEN, "💾 Writing best solution to file: %s\n", fn);
  }

  const nlohmann::json j = to_json_value(search_conclusive);
  std::ofstream f(fn);
  f << j.dump(2);
}

nlohmann::json BBConstraints::to_json_value(
    bool search_conclusive) const
{
  nlohmann::json j;
  j["best_cost"] = best_cost_local / 100.0; // convert from cents to dollars
  j["best_x"] = best_x;
  j["best_canonical_x"] = best_canonical_x;
  j["best_y"] = best_y;
  j["search_status"] = search_conclusive
                           ? "CONCLUSIVE"
                           : "INCONCLUSIVE_HYDRAULIC_NONCONVERGENCE";
  j["switch_count_convention"] = switch_count_convention;
  j["max_switch_count_per_pump"] = max_switch_count_per_pump;
  return j;
}
