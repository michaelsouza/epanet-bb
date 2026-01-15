/* EPANET 3
 *
 * Copyright (c) 2016 Open Water Analytics
 * Licensed under the terms of the MIT License (see the LICENSE file for
 * details).
 *
 */

//! \file element.h
//! \brief Describes the Element class.

#ifndef ELEMENT_H_
#define ELEMENT_H_

#include <nlohmann/json.hpp> // Include the JSON library
#include <string>
#include <vector>

//! \class Element
//! \brief Abstract parent class for all pipe network components.

class Element {
public:
  enum ElementType { NODE, LINK, PATTERN, CURVE, CONTROL };

  Element(std::string name_);
  virtual ~Element() = 0;

  std::string name; //!< element's ID name
  int index;        //!< index in array of elements

  //! Serialize to JSON for Element
  virtual nlohmann::json to_json() const = 0;

  //! Deserialize from JSON for Element
  virtual void from_json(const nlohmann::json &j) = 0;

private:
  // Elements can't be copied or tested for equality
  Element(const Element &e);
  Element &operator=(const Element &e);
};

#endif
