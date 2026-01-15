/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file tank.h
//! \brief Describes the Tank class.

#ifndef TANK_H_
#define TANK_H_

#include "Elements/curve.h"
#include "Elements/node.h"
#include "Models/tankmixmodel.h"

#include <string>

//! \class Tank
//! \brief A fixed head Node with storage volume.
//!
//! The fixed head for the tank varies from one time period to the next
//! depending on the filling or withdrawal rate.

class Tank : public Node {
public:
  // Constructor/Destructor
  Tank(std::string name);
  //~Tank() {}

  // Overridden virtual methods
  int type() { return Node::TANK; }
  void validate(Network *nw);
  void convertUnits(Network *nw);
  void initialize(Network *nw);
  bool isReactive() { return bulkCoeff != 0.0; }
  bool isFull() { return head >= maxHead; }
  bool isEmpty() { return head <= minHead; }
  bool isClosed(double flow);

  // Tank-specific methods
  double getVolume() { return volume; }
  double findVolume(double aHead);
  double findHead(double aVolume);
  void setFixedGrade();
  void updateVolume(int tstep);
  void updateArea();
  int timeToVolume(double aVolume);

  // Properties
  double initHead;          //!< initial water elevation (ft)
  double minHead;           //!< minimum water elevation (ft)
  double maxHead;           //!< maximum water elevation (ft)
  double diameter;          //!< nominal diameter (ft)
  double minVolume;         //!< minimum volume (ft3)
  double bulkCoeff;         //!< water quality reaction coeff. (per day)
  Curve *volCurve;          //!< volume v. water depth curve
  TankMixModel mixingModel; //!< mixing model used

  double maxVolume;   //!< maximum volume (ft3)
  double volume;      //!< current volume in tank (ft3)
  double area;        //!< current surface area of tank (ft2)
  double ucfLength;   //!< units conversion factor for length
  double pastHead;    //!< water elev. in previous time period (ft)
  double pastVolume;  //!< volume in previous time period (ft3)
  double pastOutflow; //!< outflow in previous time period (cfs)

  //! Serialize to JSON for Tank
  nlohmann::json to_json() const override {
    nlohmann::json jsonObj = Node::to_json();
    jsonObj.merge_patch({{"initHead", initHead},
                         {"minHead", minHead},
                         {"maxHead", maxHead},
                         {"diameter", diameter},
                         {"minVolume", minVolume},
                         {"bulkCoeff", bulkCoeff},
                         {"maxVolume", maxVolume},
                         {"volume", volume},
                         {"area", area},
                         {"ucfLength", ucfLength},
                         {"pastHead", pastHead},
                         {"pastVolume", pastVolume},
                         {"pastOutflow", pastOutflow}});
    return jsonObj;
  }

  //! Deserialize from JSON for Tank
  void from_json(const nlohmann::json &j) override {
    Node::from_json(j);
    initHead = j.at("initHead").get<double>();
    minHead = j.at("minHead").get<double>();
    maxHead = j.at("maxHead").get<double>();
    diameter = j.at("diameter").get<double>();
    minVolume = j.at("minVolume").get<double>();
    bulkCoeff = j.at("bulkCoeff").get<double>();
    maxVolume = j.at("maxVolume").get<double>();
    volume = j.at("volume").get<double>();
    area = j.at("area").get<double>();
    ucfLength = j.at("ucfLength").get<double>();
    pastHead = j.at("pastHead").get<double>();
    pastVolume = j.at("pastVolume").get<double>();
    pastOutflow = j.at("pastOutflow").get<double>();
  }

  virtual void copy_to(NodeData &data) const override {
    Node::copy_to(data);
    data.initHead = initHead;
    data.minHead = minHead;
    data.maxHead = maxHead;
    data.diameter = diameter;
    data.minVolume = minVolume;
    data.bulkCoeff = bulkCoeff;
    data.maxVolume = maxVolume;
    data.volume = volume;
    data.area = area;
    data.ucfLength = ucfLength;
    data.pastHead = pastHead;
    data.pastVolume = pastVolume;
    data.pastOutflow = pastOutflow;
  }

  void copy_from(const NodeData &data) override {
    Node::copy_from(data);
    initHead = data.initHead;
    minHead = data.minHead;
    maxHead = data.maxHead;
    diameter = data.diameter;
    minVolume = data.minVolume;
    bulkCoeff = data.bulkCoeff;
    maxVolume = data.maxVolume;
    volume = data.volume;
    area = data.area;
    ucfLength = data.ucfLength;
    pastHead = data.pastHead;
    pastVolume = data.pastVolume;
    pastOutflow = data.pastOutflow;
  }
};

#endif
