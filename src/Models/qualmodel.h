/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file qualmodel.h
//! \brief Describes the QualModel class.

#ifndef QUALMODEL_H_
#define QUALMODEL_H_

#include "Elements/node.h"
#include <string>
#include <vector>

class Network;
class Pipe;
class Tank;

//! \class QualModel
//! \brief The interface for a water quality analysis model.
//!
//! QualModel is an abstract class from which a concrete water
//! quality analysis model is derived. Three such models are
//! currently available - Chemical, Trace, and Age.

class QualModel {
public:
  enum QualModelType {
    NOQUAL, // no quality model
    AGE,    // water age
    TRACE,  // source tracing
    CHEM
  }; // chemical constituent

  QualModel(int _type);
  virtual ~QualModel() = 0;

  static QualModel *factory(const std::string model);

  virtual bool isReactive() { return false; }

  virtual void init(Network *nw) {}

  virtual void findMassTransCoeff(Pipe *pipe) {}

  virtual double pipeReact(Pipe *pipe, double c, double tstep) { return c; }

  virtual double tankReact(Tank *tank, double c, double tstep) { return c; }

  virtual double findTracerAdded(Node *node, double qIn) { return 0.0; }

  //! Serialize to JSON for QualModel
  virtual nlohmann::json to_json() const { return {}; }

  //! Deserialize from JSON for QualModel
  virtual void from_json(const nlohmann::json &j) {}

  int type;
};

//-----------------------------------------------------------------------------
//! \class ChemModel
//! \brief Reactive chemical model.
//-----------------------------------------------------------------------------

class ChemModel : public QualModel {
public:
  ChemModel();
  bool isReactive() { return reactive; }
  void init(Network *nw);
  void findMassTransCoeff(Pipe *pipe);
  double pipeReact(Pipe *pipe, double c, double tstep);
  double tankReact(Tank *tank, double c, double tstep);

  //! Serialize to JSON for ChemModel
  nlohmann::json to_json() const override {
    nlohmann::json jsonObj = QualModel::to_json();
    jsonObj.merge_patch({{"reactive", reactive},
                         {"diffus", diffus},
                         {"viscos", viscos},
                         {"Sc", Sc},
                         {"pipeOrder", pipeOrder},
                         {"tankOrder", tankOrder},
                         {"wallOrder", wallOrder},
                         {"massTransCoeff", massTransCoeff},
                         {"pipeUcf", pipeUcf},
                         {"tankUcf", tankUcf},
                         {"wallUcf", wallUcf},
                         {"cLimit", cLimit}});
    return jsonObj;
  }

  //! Deserialize from JSON for ChemModel
  void from_json(const nlohmann::json &j) override {
    QualModel::from_json(j);
    reactive = j.at("reactive").get<bool>();
    diffus = j.at("diffus").get<double>();
    viscos = j.at("viscos").get<double>();
    Sc = j.at("Sc").get<double>();
    pipeOrder = j.at("pipeOrder").get<double>();
    tankOrder = j.at("tankOrder").get<double>();
    wallOrder = j.at("wallOrder").get<double>();
    massTransCoeff = j.at("massTransCoeff").get<double>();
    pipeUcf = j.at("pipeUcf").get<double>();
    tankUcf = j.at("tankUcf").get<double>();
    wallUcf = j.at("wallUcf").get<double>();
    cLimit = j.at("cLimit").get<double>();
  }

private:
  bool reactive;         // true if chemical is reactive
  double diffus;         // chemical's diffusuivity (ft2/sec)
  double viscos;         // water kin. viscosity (ft2/sec)
  double Sc;             // Schmidt number
  double pipeOrder;      // pipe bulk fluid reaction order
  double tankOrder;      // tank bulk fluid reaction order
  double wallOrder;      // pipe wall reaction order
  double massTransCoeff; // a pipe's mass transfer coeff. (ft/sec)
  double pipeUcf;        // volume conversion factor for pipes
  double tankUcf;        // volume conversion factor for tanks
  double wallUcf; // wall reaction coefficient conversion factor for pipes
  double cLimit;  // min/max concentration limit (mass/ft3)

  bool setReactive(Network *nw);
  double findBulkRate(double kb, double order, double c);
  double findWallRate(double kw, double d, double order, double c);
};

//-----------------------------------------------------------------------------
//! \class TraceModel
//! \brief Source tracing model.
//-----------------------------------------------------------------------------

class TraceModel : public QualModel {
public:
  TraceModel() : QualModel(TRACE) {}
  void init(Network *nw);
  double findTracerAdded(Node *node, double qIn);

  //! Serialize to JSON for TraceModel
  nlohmann::json to_json() const override {
    nlohmann::json jsonObj = QualModel::to_json();
    jsonObj.merge_patch(
        {{"traceNode", traceNode ? traceNode->to_json() : nullptr}});
    return jsonObj;
  }

  //! Deserialize from JSON for TraceModel
  void from_json(const nlohmann::json &j) override {
    QualModel::from_json(j);
    if (!j.at("traceNode").is_null()) {
      traceNode->from_json(j.at("traceNode"));
    }
  }

private:
  Node *traceNode;
};

//-----------------------------------------------------------------------------
//! \class AgeModel
//! \brief Water age model.
//-----------------------------------------------------------------------------

class AgeModel : public QualModel {
public:
  AgeModel() : QualModel(AGE) {}
  bool isReactive() { return true; }
  double pipeReact(Pipe *pipe, double age, double tstep);
  double tankReact(Tank *tank, double age, double tstep);

  //! Serialize to JSON for AgeModel
  nlohmann::json to_json() const override { return QualModel::to_json(); }

  //! Deserialize from JSON for AgeModel
  void from_json(const nlohmann::json &j) override { QualModel::from_json(j); }
};

#endif
