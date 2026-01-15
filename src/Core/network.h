/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file network.h
//! \brief Describes the Network class.

#ifndef NETWORK_H_
#define NETWORK_H_

#include "Core/options.h"
#include "Core/qualbalance.h"
#include "Core/units.h"
#include "Elements/control.h"
#include "Elements/curve.h"
#include "Elements/element.h"
#include "Elements/node.h"
#include "Elements/pattern.h"
#include "Elements/pump.h"
#include "Elements/tank.h"
#include "Models/demandmodel.h"
#include "Models/headlossmodel.h"
#include "Models/leakagemodel.h"
#include "Models/qualmodel.h"
#include "Utilities/graph.h"
#include "Utilities/mempool.h"
#include "Utilities/utilities.h"
#include <ostream>
#include <unordered_map>
#include <vector>

class NetworkData {
public:
  std::vector<NodeData> nodes;
  std::vector<LinkData> links;
  std::vector<int> patterns; // indices of patterns
};

//! \class Network
//! \brief Contains the data elements that describe a pipe network.
//!
//! A Network object contains collections of the individual elements
//! belonging to the pipe network being analyzed by a Project.

class Network {
public:
  Network();
  ~Network();

  // Clears all elements from the network
  void clear();

  // Adds an element to the network
  bool addElement(Element::ElementType eType, int subType, std::string name);

  // Finds element counts by type and index by id name
  int count(Element::ElementType eType);
  int indexOf(Element::ElementType eType, const std::string &name);

  // Gets an analysis option by type
  int option(Options::IndexOption type);
  double option(Options::ValueOption type);
  long option(Options::TimeOption type);
  std::string option(Options::StringOption type);

  // Gets a network element by id name
  Node *node(const std::string &name);
  Link *link(const std::string &name);
  Pattern *pattern(const std::string &name);
  Curve *curve(const std::string &name);
  Control *control(const std::string &name);

  // Gets a network element by index
  Node *node(const int index);
  Link *link(const int index);
  Pattern *pattern(const int index);
  Curve *curve(const int index);
  Control *control(const int index);

  // Creates analysis models
  bool createHeadLossModel();
  bool createDemandModel();
  bool createLeakageModel();
  bool createQualModel();

  // Network graph theory operations
  Graph graph;

  // Unit conversions
  double ucf(Units::Quantity quantity);           // unit conversion factor
  std::string getUnits(Units::Quantity quantity); // unit names
  void convertUnits();

  // Adds/writes network title
  void addTitleLine(std::string line);
  void writeTitle(std::ostream &out);

  // Elements of a network
  std::vector<std::string> title;  //!< descriptive title for the network
  std::vector<Node *> nodes;       //!< collection of node objects
  std::vector<Link *> links;       //!< collection of link objects
  std::vector<Curve *> curves;     //!< collection of data curve objects
  std::vector<Pattern *> patterns; //!< collection of time pattern objects
  std::vector<Control *> controls; //!< collection of control rules
  Units units;                     //!< unit conversion factors
  Options options;                 //!< analysis options
  QualBalance qualBalance;         //!< water quality mass balance
  std::ostringstream msgLog;       //!< status message log.

  // Computational sub-models
  HeadLossModel *headLossModel; //!< pipe head loss model
  DemandModel *demandModel;     //!< nodal demand model
  LeakageModel *leakageModel;   //!< pipe leakage model
  QualModel *qualModel;         //!< water quality model

  //! Serialize to JSON for Network
  nlohmann::json to_json() const {
    nlohmann::json nodesJson = nlohmann::json::array();
    for (const auto *n : nodes) {
      nodesJson.push_back(n ? n->to_json() : nullptr);
    }

    nlohmann::json linksJson = nlohmann::json::array();
    for (const auto *l : links) {
      linksJson.push_back(l ? l->to_json() : nullptr);
    }

    nlohmann::json patternsJson = nlohmann::json::array();
    for (const auto *p : patterns) {
      patternsJson.push_back(p ? p->to_json() : nullptr);
    }

    return {
        {"nodes", nodesJson},
        {"links", linksJson},
        {"patterns", patternsJson},
    };
  }

  //! Deserialize from JSON for Network
  void from_json(const nlohmann::json &j) {
    if (nodes.size() > 0) {
      const auto &nodesJson = j.at("nodes");
      for (size_t i = 0; i < nodesJson.size(); ++i) {
        nodes[i]->from_json(nodesJson[i]);
      }
    }

    if (links.size() > 0) {
      const auto &linksJson = j.at("links");
      for (size_t i = 0; i < linksJson.size(); ++i) {
        links[i]->from_json(linksJson[i]);
      }
    }

    if (patterns.size() > 0) {
      const auto &patternsJson = j.at("patterns");
      for (size_t i = 0; i < patternsJson.size(); ++i) {
        patterns[i]->from_json(patternsJson[i]);
      }
    }
  }

  void copy_to(NetworkData &data) const {
    // resize data vectors to match network size
    if (data.nodes.size() < nodes.size())
      data.nodes.resize(nodes.size());
    if (data.links.size() < links.size())
      data.links.resize(links.size());
    if (data.patterns.size() < patterns.size())
      data.patterns.resize(patterns.size());

    // copy data
    for (size_t i = 0; i < nodes.size(); ++i)
      nodes[i]->copy_to(data.nodes[i]);
    for (size_t i = 0; i < links.size(); ++i)
      links[i]->copy_to(data.links[i]);
    for (size_t i = 0; i < patterns.size(); ++i)
      data.patterns[i] = patterns[i]->currentIdx();
  }

  void copy_from(const NetworkData &data) {
    for (size_t i = 0; i < nodes.size(); ++i)
      nodes[i]->copy_from(data.nodes[i]);
    for (size_t i = 0; i < links.size(); ++i)
      links[i]->copy_from(data.links[i]);
    for (size_t i = 0; i < patterns.size(); ++i)
      patterns[i]->currentIdx() = data.patterns[i];
  }

private:
  // Hash tables that associate an element's ID name with its storage index.
  std::unordered_map<std::string, Element *>
      nodeTable; //!< hash table for node ID names.
  std::unordered_map<std::string, Element *>
      linkTable; //!< hash table for link ID names.
  std::unordered_map<std::string, Element *>
      curveTable; //!< hash table for curve ID names.
  std::unordered_map<std::string, Element *>
      patternTable; //!< hash table for pattern ID names.
  std::unordered_map<std::string, Element *>
      controlTable; //!< hash table for control ID names.
  MemPool memPool;  //!< memory pool for network objects
};

//-----------------------------------------------------------------------------
//    Inline Functions
//-----------------------------------------------------------------------------

// Gets the value of a project option

inline int Network::option(Options::IndexOption type) {
  return options.indexOption(type);
}

inline double Network::option(Options::ValueOption type) {
  return options.valueOption(type);
}

inline long Network::option(Options::TimeOption type) {
  return options.timeOption(type);
}

inline std::string Network::option(Options::StringOption type) {
  return options.stringOption(type);
}

// Gets the unit conversion factor (user units per internal units) for a
// quantity

inline double Network::ucf(Units::Quantity quantity) {
  return units.factor(quantity);
}

// Gets the name of the units for a quantity

inline std::string Network::getUnits(Units::Quantity quantity) {
  return units.name(quantity);
}

inline void Network::addTitleLine(std::string line) { title.push_back(line); }

#endif
