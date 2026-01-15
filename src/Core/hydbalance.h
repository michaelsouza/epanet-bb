/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file hydbalance.h
//! \brief Describes the HydBalance class.

#ifndef HYDBALANCE_H_
#define HYDBALANCE_H_

#include <nlohmann/json.hpp> // Include nlohmann/json header
#include <string>
#include <vector>

class Network;

class HydBalanceData {
public:
  double maxFlowErr;
  double maxHeadErr;
  double maxFlowChange;
  double totalFlowChange;
  int maxHeadErrLink;
  int maxFlowErrNode;
  int maxFlowChangeLink;
};

//! \class HydBalance
//! \brief Computes the degree to which a network solution is unbalanced.
//!
//! The HydBalance class determines the error in satisfying the head loss
//! equation across each link and the flow continuity equation at each node
//! of the network for an incremental change in nodal heads and link flows.

struct HydBalance {
  double maxFlowErr;      //!< max. flow error (cfs)
  double maxHeadErr;      //!< max. head loss error (ft)
  double maxFlowChange;   //!< max. flow change (cfs)
  double totalFlowChange; //!< (summed flow changes) / (summed flows)

  int maxHeadErrLink;    //!< link with max. head loss error
  int maxFlowErrNode;    //!< node with max. flow error
  int maxFlowChangeLink; //!< link with max. flow change

  double evaluate(double lamda, double dH[], double dQ[], double xQ[],
                  Network *nw);
  double findHeadErrorNorm(double lamda, double dH[], double dQ[], double xQ[],
                           Network *nw);
  double findFlowErrorNorm(double xQ[], Network *nw);

  //! Serialize to JSON for HydBalance
  nlohmann::json to_json() const {
    return {{"maxFlowErr", maxFlowErr},
            {"maxHeadErr", maxHeadErr},
            {"maxFlowChange", maxFlowChange},
            {"totalFlowChange", totalFlowChange},
            {"maxHeadErrLink", maxHeadErrLink},
            {"maxFlowErrNode", maxFlowErrNode},
            {"maxFlowChangeLink", maxFlowChangeLink}};
  }

  //! Deserialize from JSON for HydBalance
  void from_json(const nlohmann::json &j) {
    maxFlowErr = j.at("maxFlowErr").get<double>();
    maxHeadErr = j.at("maxHeadErr").get<double>();
    maxFlowChange = j.at("maxFlowChange").get<double>();
    totalFlowChange = j.at("totalFlowChange").get<double>();
    maxHeadErrLink = j.at("maxHeadErrLink").get<int>();
    maxFlowErrNode = j.at("maxFlowErrNode").get<int>();
    maxFlowChangeLink = j.at("maxFlowChangeLink").get<int>();
  }

  void copy_to(HydBalanceData &data) const {
    data.maxFlowErr = maxFlowErr;
    data.maxHeadErr = maxHeadErr;
    data.maxFlowChange = maxFlowChange;
    data.totalFlowChange = totalFlowChange;
    data.maxHeadErrLink = maxHeadErrLink;
    data.maxFlowErrNode = maxFlowErrNode;
    data.maxFlowChangeLink = maxFlowChangeLink;
  }

  void copy_from(const HydBalanceData &data) {
    maxFlowErr = data.maxFlowErr;
    maxHeadErr = data.maxHeadErr;
    maxFlowChange = data.maxFlowChange;
    totalFlowChange = data.totalFlowChange;
    maxHeadErrLink = data.maxHeadErrLink;
    maxFlowErrNode = data.maxFlowErrNode;
    maxFlowChangeLink = data.maxFlowChangeLink;
  }
};

#endif
