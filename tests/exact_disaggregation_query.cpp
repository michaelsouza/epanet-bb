#include "Optimization/ExactDisaggregation.h"

#include <nlohmann/json.hpp>

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char *argv[])
{
  if (argc != 3)
  {
    std::cerr << "usage: ExactDisaggregationQuery PUMP_COUNT MAX_CYCLES\n";
    return EXIT_FAILURE;
  }

  try
  {
    const int pump_count = std::stoi(argv[1]);
    const int max_cycles = std::stoi(argv[2]);
    std::string line;
    while (std::getline(std::cin, line))
    {
      if (line.empty())
        continue;

      const auto aggregate_schedule =
          nlohmann::json::parse(line).get<std::vector<int>>();
      ExactDisaggregation disaggregation(pump_count, max_cycles);
      for (int active_pumps : aggregate_schedule)
        disaggregation.append(active_pumps);

      const auto witness = disaggregation.finish_periodic();
      nlohmann::json response;
      response["feasible"] = witness.has_value();
      response["witness"] =
          witness.has_value() ? nlohmann::json(*witness) : nlohmann::json(nullptr);
      std::cout << response.dump() << '\n';
    }
  }
  catch (const std::exception &error)
  {
    std::cerr << error.what() << '\n';
    return EXIT_FAILURE;
  }

  return EXIT_SUCCESS;
}
