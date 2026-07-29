#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

using BinarySchedule = std::vector<std::vector<int>>;

struct DisaggregationTransitionStatistics
{
  std::size_t source_states = 0;
  std::size_t candidate_assignments = 0;
  std::size_t switch_limit_rejections = 0;
  std::size_t unique_successors = 0;
  std::size_t duplicate_successors = 0;
  std::uint64_t elapsed_nanoseconds = 0;
};

class ExactDisaggregation
{
public:
  ExactDisaggregation(int pump_count, int max_cycles);

  bool append(int active_pumps);
  bool prefix_feasible() const noexcept;
  std::optional<BinarySchedule> finish_periodic() const;
  const DisaggregationTransitionStatistics &last_transition_statistics() const noexcept;
  std::size_t reachable_state_count() const noexcept;
  std::size_t stored_state_count() const noexcept;
  std::size_t estimated_state_bytes() const noexcept;

private:
  struct PumpState
  {
    int first_status;
    int current_status;
    int switches;

    bool operator<(const PumpState &other) const noexcept;
    bool operator==(const PumpState &other) const noexcept;
  };

  using CanonicalState = std::vector<PumpState>;

  struct ReachableNode
  {
    CanonicalState state;
    std::size_t predecessor;
    std::vector<std::size_t> parent_position;
  };

  using Layer = std::vector<ReachableNode>;

  int pump_count_;
  int max_switches_;
  std::vector<Layer> layers_;
  DisaggregationTransitionStatistics last_transition_statistics_;
};
