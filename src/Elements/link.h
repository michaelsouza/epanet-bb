#ifndef LINK_H_
#define LINK_H_

#include "Elements/node.h"
#include "Models/pumpenergy.h"

#include <iostream>
#include <nlohmann/json.hpp> // Include the JSON library
#include <string>

class LinkData {
public:
  double flow;
  double hGrad;
  double hLoss;
  double initSetting;
  int initStatus;
  double setting;
  int status;
  double speed;
  double costPerKwh;
  PumpEnergyData pumpEnergy;
};

class Network;
class MemPool;

//! \class Link
//! \brief A conveyance element that connects two nodes together.
class Link : public Element {
public:
  enum LinkType { PIPE, PUMP, VALVE };
  enum LinkStatus { LINK_CLOSED, LINK_OPEN, VALVE_ACTIVE, TEMP_CLOSED };
  enum LinkReaction { BULK, WALL };

  Link(std::string name_);
  virtual ~Link();

  static Link *factory(int type_, std::string name_, MemPool *memPool);

  virtual int type() = 0;
  virtual std::string typeStr() = 0;
  virtual void convertUnits(Network *nw) = 0;
  virtual double convertSetting(Network *nw, double s) { return s; }
  virtual void validate(Network *nw) {}
  virtual bool isReactive() { return false; }

  // Initializes hydraulic settings
  virtual void initialize(bool initFlow);
  virtual void setInitFlow() {}
  virtual void setInitStatus(int s) {}
  virtual void setInitSetting(double s) {}
  virtual void setResistance(Network *nw) {}

  // Retrieves hydraulic variables
  virtual double getVelocity() { return 0.0; }
  virtual double getRe(const double q, const double viscos) { return 0.0; }
  virtual double getResistance() { return 0.0; }
  virtual double getUnitHeadLoss();
  virtual double getSetting(Network *nw) { return setting; }

  // Computes head loss, energy usage, and leakage
  virtual void findHeadLoss(Network *nw, double q) = 0;
  virtual double updateEnergyUsage(Network *nw, int dt) { return 0.0; }
  virtual bool canLeak() { return false; }
  virtual double findLeakage(Network *nw, double h, double &dqdh) {
    return 0.0;
  }

  // Determines special types of links
  virtual bool isPRV() { return false; }
  virtual bool isPSV() { return false; }
  virtual bool isHpPump() { return false; }

  // Used to update and adjust link status/setting
  virtual void updateStatus(double q, double h1, double h2) {}
  virtual bool changeStatus(int newStatus, bool makeChange,
                            const std::string reason, std::ostream &msgLog) {
    return false;
  }
  virtual bool changeSetting(double newSetting, bool makeChange,
                             const std::string reason, std::ostream &msgLog) {
    return false;
  }
  virtual void validateStatus(Network *nw, double qTol) {}
  virtual void applyControlPattern(std::ostream &msgLog) {}
  std::string writeStatusChange(int oldStatus);

  // Used for water quality routing
  virtual double getVolume() { return 0.0; }

  // Properties
  bool rptFlag;       //!< true if results are reported
  Node *fromNode;     //!< pointer to the link's start node
  Node *toNode;       //!< pointer to the link's end node
  int initStatus;     //!< initial Open/Closed status
  double diameter;    //!< link diameter (ft)
  double lossCoeff;   //!< minor head loss coefficient
  double initSetting; //!< initial pump speed or valve setting

  // Computed Variables
  int status;     //!< current status
  double flow;    //!< flow rate (cfs)
  double leakage; //!< leakage rate (cfs)
  double hLoss;   //!< head loss (ft)
  double hGrad;   //!< head loss gradient (ft/cfs)
  double setting; //!< current setting
  double quality; //!< avg. quality concen. (mass/ft3)

  //! Serialize to JSON
  virtual nlohmann::json to_json() const {
    return {{"initStatus", initStatus}, {"initSetting", initSetting},
            {"status", status},         {"flow", flow},
            {"hLoss", hLoss},           {"hGrad", hGrad},
            {"setting", setting}};
  }

  //! Deserialize from JSON
  virtual void from_json(const nlohmann::json &j) {
    initStatus = j.at("initStatus").get<int>();
    initSetting = j.at("initSetting").get<double>();
    status = j.at("status").get<int>();
    flow = j.at("flow").get<double>();
    hLoss = j.at("hLoss").get<double>();
    hGrad = j.at("hGrad").get<double>();
    setting = j.at("setting").get<double>();
  }

  virtual void copy_to(LinkData &data) const {
    data.initStatus = initStatus;
    data.initSetting = initSetting;
    data.status = status;
    data.flow = flow;
    data.hLoss = hLoss;
    data.hGrad = hGrad;
    data.setting = setting;
  }

  virtual void copy_from(const LinkData &data) {
    initStatus = data.initStatus;
    initSetting = data.initSetting;
    status = data.status;
    flow = data.flow;
    hLoss = data.hLoss;
    hGrad = data.hGrad;
    setting = data.setting;
  }
};

#endif
