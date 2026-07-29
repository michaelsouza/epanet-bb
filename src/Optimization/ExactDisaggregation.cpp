#include "Optimization/ExactDisaggregation.h"

#include <algorithm>
#include <chrono>
#include <functional>
#include <map>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace
{

constexpr std::size_t no_predecessor = static_cast<std::size_t>(-1);

} // namespace

ExactDisaggregation::ExactDisaggregation(int pump_count, int max_cycles)
    : pump_count_(pump_count), max_switches_(2 * max_cycles)
{
  if (pump_count <= 0)
    throw std::invalid_argument("pump_count must be positive");
  if (max_cycles < 0)
    throw std::invalid_argument("max_cycles must be non-negative");
}

bool ExactDisaggregation::PumpState::operator<(const PumpState &other) const noexcept
{
  if (first_status != other.first_status)
    return first_status < other.first_status;
  if (current_status != other.current_status)
    return current_status < other.current_status;
  return switches < other.switches;
}

bool ExactDisaggregation::PumpState::operator==(const PumpState &other) const noexcept
{
  return first_status == other.first_status &&
         current_status == other.current_status &&
         switches == other.switches;
}

bool ExactDisaggregation::append(int active_pumps)
{
  if (active_pumps < 0 || active_pumps > pump_count_)
    throw std::invalid_argument("active_pumps must be between zero and pump_count");

  const auto started_at = std::chrono::steady_clock::now();
  last_transition_statistics_ = {};
  const auto record_elapsed_time = [&]()
  {
    last_transition_statistics_.elapsed_nanoseconds =
        static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now() - started_at)
                .count());
  };

  if (layers_.empty())
  {
    CanonicalState initial;
    initial.reserve(static_cast<std::size_t>(pump_count_));
    for (int pump = 0; pump < pump_count_; ++pump)
    {
      const int status = pump < active_pumps ? 1 : 0;
      initial.push_back({status, status, 0});
    }
    std::sort(initial.begin(), initial.end());
    layers_.push_back({{std::move(initial), no_predecessor, {}}});
    last_transition_statistics_.candidate_assignments = 1;
    last_transition_statistics_.unique_successors = 1;
    record_elapsed_time();
    return true;
  }

  Layer next_layer;
  std::map<CanonicalState, std::size_t> canonical_nodes;
  const Layer &previous_layer = layers_.back();

  for (std::size_t predecessor = 0; predecessor < previous_layer.size(); ++predecessor)
  {
    ++last_transition_statistics_.source_states;
    const CanonicalState &previous = previous_layer[predecessor].state;
    std::vector<int> next_status(static_cast<std::size_t>(pump_count_), 0);

    std::function<void(int, int)> enumerate = [&](int pump, int remaining_active)
    {
      if (pump == pump_count_)
      {
        if (remaining_active != 0)
          return;

        ++last_transition_statistics_.candidate_assignments;
        std::vector<std::pair<PumpState, std::size_t>> updated;
        updated.reserve(static_cast<std::size_t>(pump_count_));
        for (int position = 0; position < pump_count_; ++position)
        {
          const PumpState &old_state = previous[static_cast<std::size_t>(position)];
          const int status = next_status[static_cast<std::size_t>(position)];
          const int switches = old_state.switches + (old_state.current_status != status);
          if (switches > max_switches_)
          {
            ++last_transition_statistics_.switch_limit_rejections;
            return;
          }
          updated.push_back({{old_state.first_status, status, switches},
                             static_cast<std::size_t>(position)});
        }

        std::sort(updated.begin(), updated.end(),
                  [](const auto &left, const auto &right)
                  {
                    if (left.first == right.first)
                      return left.second < right.second;
                    return left.first < right.first;
                  });

        CanonicalState canonical;
        std::vector<std::size_t> parent_position;
        canonical.reserve(updated.size());
        parent_position.reserve(updated.size());
        for (const auto &entry : updated)
        {
          canonical.push_back(entry.first);
          parent_position.push_back(entry.second);
        }

        if (canonical_nodes.find(canonical) == canonical_nodes.end())
        {
          canonical_nodes.emplace(canonical, next_layer.size());
          next_layer.push_back({std::move(canonical), predecessor,
                                std::move(parent_position)});
          ++last_transition_statistics_.unique_successors;
        }
        else
          ++last_transition_statistics_.duplicate_successors;
        return;
      }

      const int pumps_left = pump_count_ - pump;
      if (remaining_active < 0 || remaining_active > pumps_left)
        return;

      next_status[static_cast<std::size_t>(pump)] = 0;
      enumerate(pump + 1, remaining_active);
      next_status[static_cast<std::size_t>(pump)] = 1;
      enumerate(pump + 1, remaining_active - 1);
    };

    enumerate(0, active_pumps);
  }

  layers_.push_back(std::move(next_layer));
  record_elapsed_time();
  return prefix_feasible();
}

bool ExactDisaggregation::prefix_feasible() const noexcept
{
  return !layers_.empty() && !layers_.back().empty();
}

std::optional<BinarySchedule> ExactDisaggregation::finish_periodic() const
{
  if (!prefix_feasible())
    return std::nullopt;

  const Layer &last_layer = layers_.back();
  std::size_t node_index = no_predecessor;
  for (std::size_t candidate = 0; candidate < last_layer.size(); ++candidate)
  {
    const CanonicalState &state = last_layer[candidate].state;
    const bool closes = std::all_of(
        state.begin(), state.end(),
        [&](const PumpState &pump)
        {
          return pump.switches + (pump.current_status != pump.first_status) <=
                 max_switches_;
        });
    if (closes)
    {
      node_index = candidate;
      break;
    }
  }

  if (node_index == no_predecessor)
    return std::nullopt;

  BinarySchedule witness(
      layers_.size(),
      std::vector<int>(static_cast<std::size_t>(pump_count_), 0));
  std::vector<std::size_t> label_at_position(
      static_cast<std::size_t>(pump_count_));
  std::iota(label_at_position.begin(), label_at_position.end(), 0);

  for (std::size_t layer_index = layers_.size(); layer_index-- > 0;)
  {
    const ReachableNode &node = layers_[layer_index][node_index];
    for (std::size_t position = 0; position < node.state.size(); ++position)
    {
      witness[layer_index][label_at_position[position]] =
          node.state[position].current_status;
    }

    if (layer_index == 0)
      break;

    std::vector<std::size_t> parent_labels(
        static_cast<std::size_t>(pump_count_));
    for (std::size_t child_position = 0;
         child_position < node.parent_position.size(); ++child_position)
    {
      parent_labels[node.parent_position[child_position]] =
          label_at_position[child_position];
    }
    label_at_position = std::move(parent_labels);
    node_index = node.predecessor;
  }

  return witness;
}

const DisaggregationTransitionStatistics &
ExactDisaggregation::last_transition_statistics() const noexcept
{
  return last_transition_statistics_;
}

std::size_t ExactDisaggregation::reachable_state_count() const noexcept
{
  return layers_.empty() ? 0 : layers_.back().size();
}

std::size_t ExactDisaggregation::stored_state_count() const noexcept
{
  return std::accumulate(
      layers_.begin(), layers_.end(), std::size_t{0},
      [](std::size_t total, const Layer &layer)
      {
        return total + layer.size();
      });
}

std::size_t ExactDisaggregation::estimated_state_bytes() const noexcept
{
  std::size_t bytes =
      sizeof(*this) + layers_.capacity() * sizeof(Layer);
  for (const Layer &layer : layers_)
  {
    bytes += layer.capacity() * sizeof(ReachableNode);
    for (const ReachableNode &node : layer)
    {
      bytes += node.state.capacity() * sizeof(PumpState);
      bytes +=
          node.parent_position.capacity() * sizeof(std::size_t);
    }
  }
  return bytes;
}
