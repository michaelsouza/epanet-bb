#include "Optimization/ExactDisaggregation.h"

#include <cstdlib>
#include <iostream>
#include <set>
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

// Non-periodic convention: only switch-ons between consecutive periods count.
// The DP must accept exactly the aggregate schedules that have a binary
// realization with at most max_cycles switch-ons per pump (brute force).
void non_periodic_count_matches_brute_force()
{
  for (int pumps = 2; pumps <= 3; ++pumps)
    for (int periods = 4; periods <= 6; ++periods)
      for (int limit = 0; limit <= 2; ++limit)
      {
        std::set<std::vector<int>> feasible;
        const int bits = pumps * periods;
        for (long code = 0; code < (1L << bits); ++code)
        {
          std::vector<int> y(static_cast<std::size_t>(periods), 0);
          bool ok = true;
          for (int pump = 0; pump < pumps && ok; ++pump)
          {
            int switch_ons = 0;
            for (int t = 0; t < periods; ++t)
            {
              const int now = (code >> (pump * periods + t)) & 1;
              const int before =
                  t > 0 ? (code >> (pump * periods + t - 1)) & 1 : now;
              switch_ons += (before == 0 && now == 1);
              y[static_cast<std::size_t>(t)] += now;
            }
            ok = switch_ons <= limit;
          }
          if (ok)
            feasible.insert(y);
        }

        std::vector<int> y(static_cast<std::size_t>(periods), 0);
        while (true)
        {
          ExactDisaggregation disaggregation(pumps, limit, false);
          bool accepted = true;
          for (int value : y)
            accepted = disaggregation.append(value) && accepted;
          const auto witness = disaggregation.finish_periodic();
          accepted = accepted && witness.has_value();
          require(accepted == (feasible.count(y) > 0),
                  "non-periodic DP disagrees with brute force");
          if (accepted)
          {
            for (int pump = 0; pump < pumps; ++pump)
            {
              int switch_ons = 0;
              for (int t = 1; t < periods; ++t)
                switch_ons +=
                    ((*witness)[static_cast<std::size_t>(t - 1)]
                               [static_cast<std::size_t>(pump)] == 0 &&
                     (*witness)[static_cast<std::size_t>(t)]
                               [static_cast<std::size_t>(pump)] == 1);
              require(switch_ons <= limit,
                      "non-periodic witness exceeds the switch-on limit");
            }
            for (int t = 0; t < periods; ++t)
            {
              int active = 0;
              for (int pump = 0; pump < pumps; ++pump)
                active += (*witness)[static_cast<std::size_t>(t)]
                                    [static_cast<std::size_t>(pump)];
              require(active == y[static_cast<std::size_t>(t)],
                      "non-periodic witness does not match the aggregate");
            }
          }
          int position = 0;
          while (position < periods &&
                 y[static_cast<std::size_t>(position)] == pumps)
            y[static_cast<std::size_t>(position++)] = 0;
          if (position == periods)
            break;
          ++y[static_cast<std::size_t>(position)];
        }
      }
}

} // namespace

int main()
{
  feasible_aggregate_schedule_has_a_periodic_binary_witness();
  transition_statistics_expose_canonical_deduplication();
  non_periodic_count_matches_brute_force();
  return EXIT_SUCCESS;
}
