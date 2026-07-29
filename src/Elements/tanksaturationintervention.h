#ifndef TANKSATURATIONINTERVENTION_H_
#define TANKSATURATIONINTERVENTION_H_

#include <string>

enum class TankSaturationInterventionType {
  NONE,
  BLOCKED_INFLOW_AT_MAXIMUM,
  BLOCKED_OUTFLOW_AT_MINIMUM
};

inline TankSaturationInterventionType
tankSaturationInterventionTypeFromInt(int value) {
  switch (value) {
  case static_cast<int>(
      TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM):
    return TankSaturationInterventionType::BLOCKED_INFLOW_AT_MAXIMUM;
  case static_cast<int>(
      TankSaturationInterventionType::BLOCKED_OUTFLOW_AT_MINIMUM):
    return TankSaturationInterventionType::BLOCKED_OUTFLOW_AT_MINIMUM;
  default:
    return TankSaturationInterventionType::NONE;
  }
}

struct TankSaturationIntervention {
  std::string tank_name;
  TankSaturationInterventionType type;
};

#endif
