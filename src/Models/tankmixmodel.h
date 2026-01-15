/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file tankmixmodel.h
//! \brief Describes the TankMixModel class.

#ifndef TANKMIXMODEL_H_
#define TANKMIXMODEL_H_

#include "Utilities/segpool.h"
#include <nlohmann/json.hpp>

class Tank;
class QualModel;
class SegPool;

//! \class TankMixModel
//! \brief The model used to compute mixing behavior within a storage tank.

class TankMixModel {
public:
  enum MixingModel {
    MIX1, //!< completely mixed model
    MIX2, //!< two compartment model
    FIFO, //!< first in, first out model
    LIFO  //!< last in, first out model
  };

  static const char *MixingModelWords[];

  // Constructor / Destructor
  TankMixModel();
  ~TankMixModel();

  // Methods
  void init(Tank *tank, SegPool *segPool, double _cTol);
  double findQuality(double vNet, double vIn, double wIn, SegPool *segPool);
  double react(Tank *tank, QualModel *qualModel, double tstep);
  double storedMass();

  // Properties
  int type;         //!< type of mixing model
  double cTol;      //!< concentration tolerance (mass/ft3)
  double fracMixed; //!< mixing zone extent for MIX2 model

  //! Serialize to JSON for TankMixModel
  nlohmann::json to_json() const {
    return {{"cTol", cTol},
            {"fracMixed", fracMixed},
            {"cTank", cTank},
            {"vMixed", vMixed}};
  }

  //! Deserialize from JSON for TankMixModel
  void from_json(const nlohmann::json &j) {
    cTol = j.at("cTol").get<double>();
    fracMixed = j.at("fracMixed").get<double>();
    cTank = j.at("cTank").get<double>();
    vMixed = j.at("vMixed").get<double>();
  }

private:
  // Methods
  double findMIX1Quality(double vNet, double vIn, double wIn);
  double findMIX2Quality(double vNet, double vIn, double wIn);
  double findFIFOQuality(double vNet, double vIn, double wIn, SegPool *segPool);
  double findLIFOQuality(double vNet, double vIn, double wIn, SegPool *segPool);

  // Properties
  double cTank;      //!< internal quality within tank (mass/ft3)
  double vMixed;     //!< mixing zone volume (ft3)
  Segment *firstSeg; //!< first volume segment in tank
  Segment *lastSeg;  //!< last volume segment in tank
};

#endif // TANKMIXING_H_
