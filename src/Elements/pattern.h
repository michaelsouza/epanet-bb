/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file pattern.h
//! \brief Describes the Pattern class and its subclasses.

#ifndef PATTERN_H_
#define PATTERN_H_

#include "Elements/element.h"
#include "Utilities/utilities.h"

#include <iostream>
#include <string>
#include <vector>

class MemPool;

//! \class Pattern
//! \brief A set of multiplier factors associated with points in time.
//!
//! Time patterns are multipliers used to adjust nodal demands,
//! pump/valve settings, or water quality source inputs over time.
//! Pattern is an abstract class from which the FixedPattern and
//! VariablePattern classes are derived.

class Pattern : public Element {
public:
  enum PatternType { FIXED_PATTERN, VARIABLE_PATTERN };

  // Constructor/Destructor
  Pattern(std::string name_, int type_);
  virtual ~Pattern();

  // Pattern factory
  static Pattern *factory(int type_, std::string name_, MemPool *memPool);

  // Methods
  void setTimeInterval(int t) { interval = t; }
  void addFactor(double f) { factors.push_back(f); }
  int timeInterval() { return interval; }
  int size() { return factors.size(); }
  double factor(int i) { return factors[i]; }
  double currentFactor();
  int &currentIdx() { return currentIndex; }
  virtual void init(int intrvl, int tstart) = 0;
  virtual int nextTime(int t) = 0;
  virtual void advance(int t) = 0;
  void show() {
    std::cout << "Pattern: " << name << std::endl;
    std::cout << "  type: " << type << std::endl;
    std::cout << "  factors(" << size() << "): [";
    for (int i = 0; i < size(); i++) {
      std::cout << " " << factor(i);
    }
    std::cout << " ]" << std::endl;
  };

  // Properties
  int type; //!< type of time pattern

  //! Serialize to JSON for Pattern
  nlohmann::json to_json() const override {
    return {{"currentIndex", currentIndex}};
  }

  //! Deserialize from JSON for Pattern
  void from_json(const nlohmann::json &j) override {
    currentIndex = j.at("currentIndex").get<int>();
  }

protected:
  std::vector<double> factors; //!< sequence of multiplier factors
  int currentIndex;            //!< index of current pattern interval
  int interval;                //!< fixed time interval (sec)
};

//------------------------------------------------------------------------------

//! \class FixedPattern
//! \brief A Pattern where factors change at fixed time intervals.
//! \note A fixed pattern wraps around once time exceeds the period
//!       associated with the last multiplier factor supplied.

class FixedPattern : public Pattern {
public:
  // Constructor/Destructor
  FixedPattern(std::string name_);
  ~FixedPattern();

  // Methods
  void init(int intrvl, int tstart);
  int nextTime(int t);
  void advance(int t);
  void setFactor(int idx, double f) { factors[idx] = f; }

private:
  int startTime; //!< offset from time 0 when the pattern begins (sec)
};

//------------------------------------------------------------------------------

//! \class VariablePattern
//! \brief A Pattern where factors change at varying time intervals.
//! \note When time exceeds the last time interval of a variable pattern
//!       the multiplier factor remains constant at its last value.

class VariablePattern : public Pattern {
public:
  // Constructor/Destructor
  VariablePattern(std::string name_);
  ~VariablePattern();

  // Methods
  void addTime(int t) { times.push_back(t); }
  int time(int i) { return times[i]; }
  void init(int intrvl, int tstart);
  int nextTime(int t);
  void advance(int t);

  //! Serialize to JSON for VariablePattern
  nlohmann::json to_json() const override {
    nlohmann::json jsonObj = Pattern::to_json();
    jsonObj["times"] = times;
    return jsonObj;
  }

  //! Deserialize from JSON for VariablePattern
  void from_json(const nlohmann::json &j) override {
    Pattern::from_json(j);
    times = j.at("times").get<std::vector<int>>();
  }

private:
  std::vector<int> times; //!< times (sec) at which factors change
};

#endif
