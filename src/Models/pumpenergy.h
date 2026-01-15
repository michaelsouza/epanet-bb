/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file pumpenergy.h
//! \brief Describes the PumpEnergy class.

#ifndef PUMPENERGY_H_
#define PUMPENERGY_H_

#include <nlohmann/json.hpp> // Include the JSON library

class Pump;
class Network;

class PumpEnergyData {
public:
  double hrsOnLine;
  double efficiency;
  double kwHrsPerCFS;
  double kwHrs;
  double maxKwatts;
  double totalCost;
  double adjustedTotalCost;
};

//! \class PumpEnergy
//! \brief Accumulates energy usage metrics for a pump.

class PumpEnergy {
public:
  // Constructor
  PumpEnergy();

  // Methods
  void init();
  double updateEnergyUsage(Pump *pump, Network *network, int dt);
  double getCost() { return adjustedTotalCost; }

  // Computed Properties
  double hrsOnLine;         //!< hours pump is online
  double efficiency;        //!< total time wtd. efficiency
  double kwHrsPerCFS;       //!< total kw-hrs per cfs of flow
  double kwHrs;             //!< total kw-hrs consumed
  double maxKwatts;         //!< max. kw consumed
  double totalCost;         //!< total pumping cost
  double adjustedTotalCost; //!< total pumping cost adjusted for efficiency

  //! Serialize to JSON for PumpEnergy
  nlohmann::json to_json() const {
    return {{"hrsOnLine", hrsOnLine},
            {"efficiency", efficiency},
            {"kwHrsPerCFS", kwHrsPerCFS},
            {"kwHrs", kwHrs},
            {"maxKwatts", maxKwatts},
            {"totalCost", totalCost},
            {"adjustedTotalCost", adjustedTotalCost}};
  }

  //! Deserialize from JSON for PumpEnergy
  void from_json(const nlohmann::json &j) {
    hrsOnLine = j.at("hrsOnLine").get<double>();
    efficiency = j.at("efficiency").get<double>();
    kwHrsPerCFS = j.at("kwHrsPerCFS").get<double>();
    kwHrs = j.at("kwHrs").get<double>();
    maxKwatts = j.at("maxKwatts").get<double>();
    totalCost = j.at("totalCost").get<double>();
    adjustedTotalCost = j.at("adjustedTotalCost").get<double>();
  }

  void copy_to(PumpEnergyData &data) const {
    data.hrsOnLine = hrsOnLine;
    data.efficiency = efficiency;
    data.kwHrsPerCFS = kwHrsPerCFS;
    data.kwHrs = kwHrs;
    data.maxKwatts = maxKwatts;
    data.totalCost = totalCost;
    data.adjustedTotalCost = adjustedTotalCost;
  }

  void copy_from(const PumpEnergyData &data) {
    hrsOnLine = data.hrsOnLine;
    efficiency = data.efficiency;
    kwHrsPerCFS = data.kwHrsPerCFS;
    kwHrs = data.kwHrs;
    maxKwatts = data.maxKwatts;
    totalCost = data.totalCost;
    adjustedTotalCost = data.adjustedTotalCost;
  }

private:
  double findCostFactor(Pump *pump, Network *network);
  double findEfficiency(Pump *pump, Network *network);
};

#endif
