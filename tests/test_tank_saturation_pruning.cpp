#include "BBConfig.h"
#include "BBConstraints.h"
#include "Core/project.h"
#include "epanet3.h"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

void require(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(EXIT_FAILURE);
  }
}

void saturation_intervention_has_a_dedicated_prune_reason(
    const char *input_file, TankSaturationInterventionType expected_type) {
  BBConfig config;
  config.inpFile = input_file;
  config.enable_cost_pruning = false;
  config.enable_global_sync = false;
  config.enable_timestep_check = false;

  BBConstraints constraints(config);
  Epanet::Project project;
  require(project.load(input_file) == 0, "the filling network should load");
  require(project.initSolver(EN_INITFLOW) == 0,
          "the filling network hydraulics should initialize");

  int time = 0;
  int step = 0;
  require(project.runSolver(&time) == 0,
          "the network should solve before reaching the boundary");
  require(project.advanceSolver(&step) == 0,
          "the network should advance to the boundary");
  require(project.runSolver(&time) == 0,
          "the network should solve at the boundary");
  require(!project.tankSaturationEvents().empty(),
          "the hydraulic solve should expose a boundary intervention");
  require(project.tankSaturationEvents().front().type == expected_type,
          "the hydraulic solve should expose the expected boundary cause");
  require(project.advanceSolver(&step) == 0,
          "the network should advance after the intervention");

  double cost = 0.0;
  const auto reason =
      constraints.check_feasibility(project, step, 1, cost, 0);
  require(reason == BBPrune::Reason::TANK_SATURATION,
          "the search should prune with the dedicated saturation reason");
  require(BBPrune::labels.at(reason) == "TANK_SATURATION",
          "statistics should expose the saturation reason by name");
}

} // namespace

int main(int argc, char **argv) {
  require(argc == 3,
          "usage: TankSaturationPruneTest <filling-network.inp> "
          "<draining-network.inp>");
  saturation_intervention_has_a_dedicated_prune_reason(
      argv[1],
      TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM);
  saturation_intervention_has_a_dedicated_prune_reason(
      argv[2],
      TankSaturationInterventionType::BLOCKED_OUTFLOW_AT_MINIMUM);
  return EXIT_SUCCESS;
}
