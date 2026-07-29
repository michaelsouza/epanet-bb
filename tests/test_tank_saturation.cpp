#include "Core/project.h"
#include "Elements/tank.h"

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

void reaches_maximum_before_reporting_blocked_inflow(const char *input_file) {
  Epanet::Project project;
  require(project.load(input_file) == 0, "the filling network should load");
  require(project.initSolver(true) == 0,
          "the filling network solver should initialize");

  int time = 0;
  int step = 0;
  require(project.runSolver(&time) == 0,
          "hydraulics before reaching the maximum should solve");
  require(project.tankSaturationEvents().empty(),
          "flow toward a tank below its maximum should not be an intervention");

  require(project.advanceSolver(&step) == 0,
          "the simulation should advance to the tank boundary");
  require(step > 0, "the tank should take a positive time to reach its boundary");
  require(project.tankSaturationEvents().empty(),
          "exact arrival at the maximum should remain admissible");

  require(project.runSolver(&time) == 0,
          "hydraulics at the maximum should solve by closing the inflow");
  const auto events = project.tankSaturationEvents();
  require(events.size() == 1,
          "one saturation intervention should be reported at the maximum");
  require(events.front().tank_name == "TANK",
          "the intervention should identify the affected tank");
  require(events.front().type ==
              TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM,
          "the intervention should identify blocked inflow at the maximum");
}

void reaches_minimum_before_reporting_blocked_outflow(const char *input_file) {
  Epanet::Project project;
  require(project.load(input_file) == 0, "the draining network should load");
  require(project.initSolver(true) == 0,
          "the draining network solver should initialize");

  int time = 0;
  int step = 0;
  require(project.runSolver(&time) == 0,
          "hydraulics before reaching the minimum should solve");
  require(project.tankSaturationEvents().empty(),
          "flow away from a tank above its minimum should not be an intervention");

  require(project.advanceSolver(&step) == 0,
          "the simulation should advance to the lower tank boundary");
  require(step > 0, "the tank should take a positive time to reach its boundary");
  require(project.tankSaturationEvents().empty(),
          "exact arrival at the minimum should remain admissible");

  require(project.runSolver(&time) == 0,
          "hydraulics at the minimum should solve by closing the outflow");
  const auto events = project.tankSaturationEvents();
  require(events.size() == 1,
          "one saturation intervention should be reported at the minimum");
  require(events.front().tank_name == "TANK",
          "the intervention should identify the affected tank");
  require(events.front().type ==
              TankSaturationInterventionType::BLOCKED_OUTFLOW_AT_MINIMUM,
          "the intervention should identify blocked outflow at the minimum");
}

void snapshot_restores_the_latest_intervention(const char *input_file) {
  Epanet::Project project;
  require(project.load(input_file) == 0, "the snapshot network should load");
  require(project.initSolver(true) == 0,
          "the snapshot network solver should initialize");

  int time = 0;
  int step = 0;
  require(project.runSolver(&time) == 0,
          "the snapshot network should solve before its boundary");
  require(project.advanceSolver(&step) == 0,
          "the snapshot network should advance to its boundary");
  require(project.runSolver(&time) == 0,
          "the snapshot network should solve at its boundary");
  require(!project.tankSaturationEvents().empty(),
          "the boundary solve should report an intervention");

  ProjectData snapshot;
  project.copy_to(snapshot);

  require(project.initSolver(true) == 0,
          "reinitializing the solver should clear runtime events");
  require(project.tankSaturationEvents().empty(),
          "the reinitialized project should not retain an old intervention");
  project.copy_from(snapshot);

  const auto restored = project.tankSaturationEvents();
  require(restored.size() == 1,
          "restoring a snapshot should restore its intervention state");
  require(restored.front().type ==
              TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM,
          "the restored snapshot should preserve the intervention cause");
}

void a_new_status_pass_replaces_transient_interventions() {
  Tank tank("TANK");
  tank.fixedGrade = true;
  tank.minHead = 0.0;
  tank.maxHead = 10.0;
  tank.head = tank.maxHead;

  tank.beginSaturationEvaluation();
  require(tank.isClosed(-1.0),
          "the first status pass should detect prohibited inflow");
  require(tank.getSaturationIntervention() ==
              TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM,
          "the first status pass should retain its intervention");

  tank.beginSaturationEvaluation();
  require(!tank.isClosed(1.0),
          "the next status pass should allow outflow from a full tank");
  require(tank.getSaturationIntervention() ==
              TankSaturationInterventionType::NONE,
          "the next status pass should replace a transient intervention");
}

void invalid_serialized_interventions_are_ignored() {
  require(tankSaturationInterventionTypeFromInt(-1) ==
              TankSaturationInterventionType::NONE,
          "negative serialized intervention values should be ignored");
  require(tankSaturationInterventionTypeFromInt(99) ==
              TankSaturationInterventionType::NONE,
          "unknown serialized intervention values should be ignored");
}

} // namespace

int main(int argc, char **argv) {
  require(argc == 3,
          "usage: TankSaturationTest <filling-network.inp> "
          "<draining-network.inp>");
  reaches_maximum_before_reporting_blocked_inflow(argv[1]);
  reaches_minimum_before_reporting_blocked_outflow(argv[2]);
  snapshot_restores_the_latest_intervention(argv[1]);
  a_new_status_pass_replaces_transient_interventions();
  invalid_serialized_interventions_are_ignored();
  return EXIT_SUCCESS;
}
