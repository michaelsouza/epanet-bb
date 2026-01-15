#ifndef QUALSOURCE_H_
#define QUALSOURCE_H_

#include "Elements/pattern.h"
#include <nlohmann/json.hpp> // Include nlohmann/json for JSON handling

class Node;

//! \class QualSource
//! \brief Externally applied water quality at a source node.
class QualSource {
public:
  enum QualSourceType {
    CONCEN,    //!< concentration of any external inflow
    MASS,      //!< adds a fixed mass inflow to a node
    FLOWPACED, //!< boosts a node's concentration by a fixed amount
    SETPOINT   //!< sets the concentration of water leaving a node
  };

  static const char *SourceTypeWords[];

  QualSource();
  ~QualSource();

  /// Factory method for adding a new source (or modifying an existing one)
  static bool addSource(Node *node, int t, double b, Pattern *p);

  /// Determines quality concen. that source adds to a node's outflow
  void setStrength(Node *node);
  double getQuality(Node *node);

  int type;         //!< source type
  double base;      //!< baseline source quality (mass/L or mass/sec)
  Pattern *pattern; //!< source time pattern
  double strength;  //!< pattern adjusted source quality (mass/ft3 or mass/sec)
  double outflow;   //!< flow rate released from node into network (cfs)
  double quality;   //!< node quality after source is added on (mass/ft3)

  //! Serialize to JSON
  nlohmann::json to_json() const {
    nlohmann::json jsonObj = {{"base", base},
                              {"strength", strength},
                              {"outflow", outflow},
                              {"quality", quality}};

    // Serialize pattern if it exists
    jsonObj["pattern"] = pattern ? pattern->to_json() : nullptr;

    return jsonObj;
  }

  //! Deserialize from JSON
  void from_json(const nlohmann::json &j) {
    base = j.at("base").get<double>();
    strength = j.at("strength").get<double>();
    outflow = j.at("outflow").get<double>();
    quality = j.at("quality").get<double>();

    if (!j.at("pattern").is_null()) {
      pattern->from_json(j.at("pattern"));
    }
  }
};

#endif
