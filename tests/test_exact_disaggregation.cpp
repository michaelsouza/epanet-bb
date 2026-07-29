#include "Optimization/ExactDisaggregation.h"

#include <cstdlib>
#include <iostream>
#include <vector>

namespace
{

void require(bool condition, const char *message)
{
  if (!condition)
  {
    std::cerr << message << '\n';
    std::exit(EXIT_FAILURE);
  }
}

void feasible_aggregate_schedule_has_a_periodic_binary_witness()
{
  ExactDisaggregation disaggregation(3, 1);

  require(disaggregation.append(1), "period 1 should have a reachable disaggregation");
  require(disaggregation.append(2), "period 2 should have a reachable disaggregation");
  require(disaggregation.append(1), "period 3 should have a reachable disaggregation");

  const auto witness = disaggregation.finish_periodic();
  require(witness.has_value(), "aggregate schedule (1, 2, 1) should have a periodic binary witness");
  require(witness->size() == 3, "witness should contain three periods");

  for (std::size_t period = 0; period < witness->size(); ++period)
  {
    int active_pumps = 0;
    for (int status : witness->at(period))
    {
      require(status == 0 || status == 1, "pump status should be binary");
      active_pumps += status;
    }
    require(active_pumps == std::vector<int>{1, 2, 1}.at(period),
            "witness should reproduce the aggregate schedule");
  }

  for (std::size_t pump = 0; pump < 3; ++pump)
  {
    int switches = 0;
    for (std::size_t period = 0; period < witness->size(); ++period)
    {
      const std::size_t previous = (period + witness->size() - 1) % witness->size();
      switches += witness->at(previous).at(pump) != witness->at(period).at(pump);
    }
    require(switches <= 2, "each pump should respect one complete periodic cycle");
  }
}

void transition_statistics_expose_canonical_deduplication()
{
  ExactDisaggregation disaggregation(3, 1);
  require(disaggregation.append(0), "all pumps off should initialize a reachable state");
  require(disaggregation.append(1), "one active pump should have a reachable state");

  const auto &statistics = disaggregation.last_transition_statistics();
  require(statistics.source_states == 1, "transition should process one canonical source state");
  require(statistics.candidate_assignments == 3, "transition should generate three labeled assignments");
  require(statistics.switch_limit_rejections == 0, "transition should not exceed the switch limit");
  require(statistics.unique_successors == 1, "interchangeable assignments should produce one canonical successor");
  require(statistics.duplicate_successors == 2, "two assignments should be removed by canonical deduplication");
  require(disaggregation.reachable_state_count() == 1, "one canonical state should remain reachable");
  require(disaggregation.stored_state_count() == 2, "initial and current layers should each store one state");
}

} // namespace

int main()
{
  feasible_aggregate_schedule_has_a_periodic_binary_witness();
  transition_statistics_expose_canonical_deduplication();
  return EXIT_SUCCESS;
}
