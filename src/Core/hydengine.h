/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Distributed under the MIT License (see the LICENSE file for details).
 *
 */

//! \file hydengine.h
//! \brief Describes the HydEngine class.

#ifndef HYDENGINE_H_
#define HYDENGINE_H_

#include <string>

class Network;

#include "Solvers/hydsolver.h"
#include "Solvers/matrixsolver.h"

class HydEngineData {
public:
  int engineState;
  bool halted;
  int rptTime;
  int hydStep;
  int currentTime;
  int timeOfDay;
  double peakKwatts;
  HydSolverData hydSolver;
  MatrixSolverData matrixSolver;
};

//! \class HydEngine
//! \brief Simulates extended period hydraulics.
//!
//! The HydEngine class carries out an extended period hydraulic simulation on
//! a pipe network, calling on its HydSolver object to solve the conservation of
//! mass and energy equations at each time step.

class HydEngine {
public:
  // Constructor/Destructor

  HydEngine();
  ~HydEngine();

  // Public Methods

  void open(Network *nw);
  void init(bool initFlows);
  int solve(int *t);
  void advance(int *tstep);
  void close();

  int getElapsedTime() { return currentTime; }
  double getPeakKwatts() { return peakKwatts; }

  //! Serialize to JSON for HydEngine
  nlohmann::json to_json() const {
    return {{"engineState", static_cast<int>(engineState)},
            {"hydSolver", hydSolver ? hydSolver->to_json() : nullptr},
            {"matrixSolver", matrixSolver ? matrixSolver->to_json() : nullptr},
            {"halted", halted},
            {"rptTime", rptTime},
            {"hydStep", hydStep},
            {"currentTime", currentTime},
            {"timeOfDay", timeOfDay},
            {"peakKwatts", peakKwatts}};
  }

  //! Deserialize from JSON for HydEngine
  void from_json(const nlohmann::json &j) {
    engineState = static_cast<EngineState>(j.at("engineState").get<int>());
    if (!j.at("hydSolver").is_null())
      hydSolver->from_json(j.at("hydSolver"));
    if (!j.at("matrixSolver").is_null())
      matrixSolver->from_json(j.at("matrixSolver"));
    halted = j.at("halted").get<bool>();
    rptTime = j.at("rptTime").get<int>();
    hydStep = j.at("hydStep").get<int>();
    currentTime = j.at("currentTime").get<int>();
    timeOfDay = j.at("timeOfDay").get<int>();
    peakKwatts = j.at("peakKwatts").get<double>();
  }

  void copy_to(HydEngineData &data) const {
    data.engineState = engineState;
    data.halted = halted;
    data.rptTime = rptTime;
    data.hydStep = hydStep;
    data.currentTime = currentTime;
    data.timeOfDay = timeOfDay;
    data.peakKwatts = peakKwatts;
    hydSolver->copy_to(data.hydSolver);
    matrixSolver->copy_to(data.matrixSolver);
  }

  void copy_from(const HydEngineData &data) {
    engineState = static_cast<EngineState>(data.engineState);
    halted = data.halted;
    rptTime = data.rptTime;
    hydStep = data.hydStep;
    currentTime = data.currentTime;
    timeOfDay = data.timeOfDay;
    peakKwatts = data.peakKwatts;
    hydSolver->copy_from(data.hydSolver);
    matrixSolver->copy_from(data.matrixSolver);
  }

private:
  // Engine state

  enum EngineState { CLOSED, OPENED, INITIALIZED };
  EngineState engineState;

  // Engine components

  Network *network;           //!< network being analyzed
  HydSolver *hydSolver;       //!< steady state hydraulic solver
  MatrixSolver *matrixSolver; //!< sparse matrix solver
  //    HydFile*       hydFile;            //!< hydraulics file accessor

  // Engine properties

  bool saveToFile;            //!< true if results saved to file
  bool halted;                //!< true if simulation has been halted
  int startTime;              //!< starting time of day (sec)
  int rptTime;                //!< current reporting time (sec)
  int hydStep;                //!< hydraulic time step (sec)
  int currentTime;            //!< current simulation time (sec)
  int timeOfDay;              //!< current time of day (sec)
  double peakKwatts;          //!< peak energy usage (kwatts)
  std::string timeStepReason; //!< reason for taking next time step

  // Simulation sub-tasks

  void initMatrixSolver();

  int getTimeStep();
  int timeToPatternChange(int tstep);
  int timeToActivateControl(int tstep);
  int timeToCloseTank(int tstep);

  void updateCurrentConditions();
  void updateTanks();
  void updatePatterns();
  void updateEnergyUsage();

  bool isPressureDeficient();
  int resolvePressureDeficiency(int &trials);
  void reportDiagnostics(int statusCode, int trials);
};

#endif
