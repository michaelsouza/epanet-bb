/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file ggasolver.h
//! \brief Describes the GGASolver class.

#ifndef GGASOLVER_H_
#define GGASOLVER_H_

#include "Core/hydbalance.h"
#include "Solvers/hydsolver.h"
#include "Utilities/utilities.h"

#include <string>
#include <vector>
class HydSolver;

//! \class GGASolver
//! \brief A hydraulic solver based on Todini's Global Gradient Algorithm.

class GGASolver : public HydSolver {
public:
  GGASolver(Network *nw, MatrixSolver *ms);
  ~GGASolver();
  int solve(double tstep, int &trials);

  //! Serialize to JSON for GGASolver
  nlohmann::json to_json() const override {
    nlohmann::json jsonObj = HydSolver::to_json();
    jsonObj.merge_patch(
        {{"matrixSolver", matrixSolver ? matrixSolver->to_json() : nullptr},
         {"hLossEvalCount", hLossEvalCount},
         {"stepSizing", stepSizing},
         {"trialsLimit", trialsLimit},
         {"reportTrials", reportTrials},
         {"headErrLimit", headErrLimit},
         {"flowErrLimit", flowErrLimit},
         {"flowChangeLimit", flowChangeLimit},
         {"flowRatioLimit", flowRatioLimit},
         {"tstep", tstep},
         {"theta", theta},
         {"errorNorm", errorNorm},
         {"oldErrorNorm", oldErrorNorm},
         {"hydBalance", hydBalance.to_json()},
         {"dH", dH},
         {"dQ", dQ},
         {"xQ", xQ}});
    return jsonObj;
  }

  //! Deserialize from JSON for GGASolver
  void from_json(const nlohmann::json &j) override {
    HydSolver::from_json(j);
    if (matrixSolver)
      matrixSolver->from_json(j.at("matrixSolver"));
    hLossEvalCount = j.at("hLossEvalCount").get<int>();
    stepSizing = j.at("stepSizing").get<int>();
    trialsLimit = j.at("trialsLimit").get<int>();
    reportTrials = j.at("reportTrials").get<bool>();
    headErrLimit = j.at("headErrLimit").get<double>();
    flowErrLimit = j.at("flowErrLimit").get<double>();
    flowChangeLimit = j.at("flowChangeLimit").get<double>();
    flowRatioLimit = j.at("flowRatioLimit").get<double>();
    tstep = j.at("tstep").get<double>();
    theta = j.at("theta").get<double>();
    errorNorm = j.at("errorNorm").get<double>();
    oldErrorNorm = j.at("oldErrorNorm").get<double>();
    hydBalance.from_json(j.at("hydBalance"));
    dH = j.at("dH").get<std::vector<double>>();
    dQ = j.at("dQ").get<std::vector<double>>();
    xQ = j.at("xQ").get<std::vector<double>>();
  }

  void copy_to(HydSolverData &data) const override {
    data.hLossEvalCount = hLossEvalCount;
    data.stepSizing = stepSizing;
    data.trialsLimit = trialsLimit;
    data.reportTrials = reportTrials;
    data.headErrLimit = headErrLimit;
    data.flowErrLimit = flowErrLimit;
    data.flowChangeLimit = flowChangeLimit;
    data.flowRatioLimit = flowRatioLimit;
    data.tstep = tstep;
    data.theta = theta;
    data.errorNorm = errorNorm;
    data.oldErrorNorm = oldErrorNorm;
    hydBalance.copy_to(data.hydBalance);
    data.dH = dH;
    data.dQ = dQ;
    data.xQ = xQ;
  }

  void copy_from(const HydSolverData &data) override {
    hLossEvalCount = data.hLossEvalCount;
    stepSizing = data.stepSizing;
    trialsLimit = data.trialsLimit;
    reportTrials = data.reportTrials;
    headErrLimit = data.headErrLimit;
    flowErrLimit = data.flowErrLimit;
    flowChangeLimit = data.flowChangeLimit;
    flowRatioLimit = data.flowRatioLimit;
    tstep = data.tstep;
    theta = data.theta;
    errorNorm = data.errorNorm;
    oldErrorNorm = data.oldErrorNorm;
    hydBalance.copy_from(data.hydBalance);
    dH = data.dH;
    dQ = data.dQ;
    xQ = data.xQ;
  }

private:
  int nodeCount;      // number of network nodes
  int linkCount;      // number of network links
  int hLossEvalCount; // number of head loss evaluations
  int stepSizing;     // Newton step sizing method

  int trialsLimit;        // limit on number of trials
  bool reportTrials;      // report summary of each trial
  double headErrLimit;    // allowable head error (ft)
  double flowErrLimit;    // allowable flow error (cfs)
  double flowChangeLimit; // allowable flow change (cfs)
  double flowRatioLimit;  // allowable total flow change / total flow
  double tstep;           // time step (sec)
  double theta;           // time weighting constant

  double errorNorm;      // solution error norm
  double oldErrorNorm;   // previous error norm
  HydBalance hydBalance; // hydraulic balance results

  std::vector<double> dH; // head change at each node (ft)
  std::vector<double> dQ; // flow change in each link (cfs)
  std::vector<double> xQ; // node flow imbalances (cfs)

  // Functions that assemble linear equation coefficients
  void setFixedGradeNodes();
  void setMatrixCoeffs();
  void setLinkCoeffs();
  void setNodeCoeffs();
  void setValveCoeffs();

  // Functions that update the hydraulic solution
  int findHeadChanges();
  void findFlowChanges();
  double findStepSize(int trials);
  void updateSolution(double lamda);

  // Functions that check for convergence
  void setConvergenceLimits();
  double findErrorNorm(double lamda);
  bool hasConverged();
  bool linksChangedStatus();
  void reportTrial(int trials, double lamda);
};

#endif
