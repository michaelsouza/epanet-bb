#include "BBSolver.h"
#include "Core/project.h"
#include "Elements/pattern.h"
#include "Elements/pump.h"

#include <chrono>

// --- BBTask Implementation ---

double BBTask::priority() const
{
  return h_root;
}

BBTask::BBTask() = default;

BBTask::BBTask(int uid, const BBConfig &config, const BBConstraints &constraints)
{
  h_root = 1;
  y.resize(config.h_max + 1, 0);
  num_pumps = constraints.get_num_pumps();
  this->uid = uid;
  h = 0;
  tid = 0;
  p = nullptr;
  cost = std::numeric_limits<double>::max();
  is_feasible = true;
  hydraulic_nonconvergence = false;
}

bool BBTask::operator<(const BBTask &other) const
{
  return priority() > other.priority(); // Higher priority comes first
}

void BBTask::show() const
{
  Console::printf(Console::Color::BRIGHT_YELLOW, "uid=%d, h_root=%d\n", uid, h_root);
  // Assuming show_vector is a global or static utility function.
  // If not, this part might need adjustment. For now, let's comment it out
  // as its definition is not visible.
  // show_vector(y, "y");
}

void BBTask::show_xy(int h, bool all, bool mark) const
{
  if (!all) // show only for the current hour
  {
    Console::printf(Console::Color::BRIGHT_YELLOW, "TID[%d]: h=%d, y=%d, x=[ ", tid, h, y[h]);
    for (int j = 0; j < num_pumps; ++j)
    {
      Console::printf(Console::Color::BRIGHT_YELLOW, "%d ", x[h * num_pumps + j]);
    }
    Console::printf(Console::Color::BRIGHT_YELLOW, "]%s\n", mark ? "<<<" : "");
  }
  else // show for all hours
  {
    for (int i = 1; i <= (y.size() - 1); ++i)
      show_xy(i, false, i == h);
  }
}

void BBTask::show_xy(bool all) const
{
  show_xy(h, all);
}

// --- BBPumpController Implementation ---

bool BBPumpController::switchPumpsOff(int *x_new, const std::vector<int> &pumps_sorted, const std::vector<int> &allowed_10, int &counter_10)
{
  // Iterate through pumps in priority order
  for (int pump_id : pumps_sorted)
  {
    // Stop if we've already switched off enough pumps
    if (counter_10 <= 0) break;

    // Check if this pump is currently on
    if (x_new[pump_id] == 1)
    {
      // Verify if this pump can be switched off (has remaining 1->0 actuations allowed)
      if (allowed_10[pump_id] <= 0) return false;

      // Switch pump off and decrement the counter
      x_new[pump_id] = 0;
      --counter_10;
    }
  }

  // Return true only if we successfully switched off all required pumps
  return (counter_10 == 0);
}

bool BBPumpController::switchPumpsOn(int *x_new, const std::vector<int> &pumps_sorted, const std::vector<int> &allowed_01, int &counter_01)
{
  for (int pump_id : pumps_sorted)
  {
    if (counter_01 <= 0) break;
    if (x_new[pump_id] == 0)
    {
      if (allowed_01[pump_id] <= 0) return false;
      x_new[pump_id] = 1;
      --counter_01;
    }
  }
  return (counter_01 == 0);
}

void BBPumpController::computeAllowedSwitches(int num_pumps, const int *x, int current_h, std::vector<int> &allowed_01, std::vector<int> &allowed_10)
{
  for (int pump_id = 0; pump_id < num_pumps; ++pump_id)
  {
    for (int i = 2; i < current_h; ++i)
    {
      int x_old = x[pump_id + num_pumps * (i - 1)];
      int x_new = x[pump_id + num_pumps * i];
      if (x_old < x_new)
        --allowed_01[pump_id]; // 0 -> 1
      else if (x_old > x_new)
        --allowed_10[pump_id]; // 1 -> 0
    }
  }
}

void BBPumpController::sortPumps(std::vector<int> &pumps_sorted, const std::vector<int> &allowed_01, const std::vector<int> &allowed_10,
                                 bool switch_on)
{
  if (switch_on)
  {
    std::sort(pumps_sorted.begin(), pumps_sorted.end(),
              [&allowed_01, &allowed_10](int a, int b)
              {
                if (allowed_01[a] != allowed_01[b]) return allowed_01[a] > allowed_01[b];
                return allowed_10[a] > allowed_10[b];
              });
  }
  else
  {
    std::sort(pumps_sorted.begin(), pumps_sorted.end(),
              [&allowed_01, &allowed_10](int a, int b)
              {
                if (allowed_10[a] != allowed_10[b]) return allowed_10[a] > allowed_10[b];
                return allowed_01[a] > allowed_01[b];
              });
  }
}

// --- BBSolver Implementation ---

BBSolver::BBSolver(BBConfig &configRef, BBConstraints &constraintsRef, BBStatistics &statsRef)
    : config(configRef), constraints(constraintsRef), stats(statsRef)
{
}

namespace
{

std::size_t estimate_resident_disaggregation_bytes(
    const std::vector<std::optional<ExactDisaggregation>> &snapshots)
{
  std::size_t bytes =
      sizeof(snapshots) +
      snapshots.capacity() *
          sizeof(std::optional<ExactDisaggregation>);
  for (const auto &snapshot : snapshots)
  {
    if (!snapshot.has_value())
      continue;
    const std::size_t object_bytes = snapshot->estimated_state_bytes();
    bytes += object_bytes - sizeof(ExactDisaggregation);
  }
  return bytes;
}

} // namespace

void BBSolver::solveTask(BBTask &task)
{
  Project p;
  task.p = &p;
  task.cost = std::numeric_limits<double>::max();
  task.x.resize((config.h_max + 1) * task.num_pumps, 0);
  task.disaggregation_snapshots.clear();
  task.disaggregation_snapshots.resize(
      static_cast<std::size_t>(config.h_max + 1));
  if (config.enable_exact_disaggregation)
  {
    task.disaggregation_snapshots[0].emplace(
        task.num_pumps, config.max_actuations);
  }
  task.periodic_witness.reset();
  task.is_feasible = true;
  task.hydraulic_nonconvergence = false;

  BBPrune::Reason prune_reason = initSnapshots(task);
  if (task.hydraulic_nonconvergence)
    return;
  if (prune_reason != BBPrune::Reason::NONE)
  {
    if (config.verbose > 1) stats.show();
    return;
  }

  while (true)
  {
    updateY(task);
    if (!task.is_feasible) break;

    updateX(task);
    if (!task.is_feasible)
    {
      stats.add_stats(BBPrune::Reason::ACTUATIONS, task.h);      
      stats.record_branch_evaluation(
          task.uid, task.h,
          std::vector<int>(task.y.begin(), task.y.begin() + task.h + 1),
          std::vector<int>(
              task.x.begin() + task.h * task.num_pumps,
              task.x.begin() + (task.h + 1) * task.num_pumps),
          BBPrune::Reason::ACTUATIONS);
      continue;
    }
    
    if (config.verbose > 0)
    {
      Console::hline(Console::Color::BRIGHT_YELLOW, 20);
      Console::printf(Console::Color::BRIGHT_YELLOW, "TID[%d]: solveTask: h=%d\n", task.tid, task.h);
      task.show_xy(true);
    }

    const BBPrune::Reason reason = processLevel(task);
    if (task.hydraulic_nonconvergence)
      break;
    stats.add_stats(reason, task.h);
    stats.record_branch_evaluation(
        task.uid, task.h,
        std::vector<int>(task.y.begin(), task.y.begin() + task.h + 1),
        std::vector<int>(
            task.x.begin() + task.h * task.num_pumps,
            task.x.begin() + (task.h + 1) * task.num_pumps),
        reason, task.p->tankSaturationEvents());
    if (config.verbose > 1) stats.show();
  }
}

BBPrune::Reason BBSolver::initSnapshots(BBTask &task)
{
  if (config.verbose)
  {
    Console::hline(Console::Color::BRIGHT_YELLOW, 20);
    Console::printf(Console::Color::BRIGHT_YELLOW, "TID[%d]: initSnapshots: task.uid=%d, task.h_root=%d\n", task.tid, task.uid, task.h_root);
  }

  Project &p = *(task.p);
  p.load(config.inpFile.c_str());
  Network *nw = p.getNetwork();
  int t_max = 3600 * config.h_max;
  nw->options.setOption(Options::TimeOption::TOTAL_DURATION, t_max);
  if (config.hydraulic_max_trials > 0)
  {
    nw->options.setOption(
        Options::IndexOption::MAX_TRIALS, config.hydraulic_max_trials);
  }
  if (config.hydraulic_accuracy > 0.0)
  {
    nw->options.setOption(
        Options::ValueOption::RELATIVE_ACCURACY,
        config.hydraulic_accuracy);
  }
  stats.set_hydraulic_configuration(
      {{"relative_accuracy",
        nw->option(Options::ValueOption::RELATIVE_ACCURACY)},
       {"relative_accuracy_origin",
        config.hydraulic_accuracy > 0.0 ? "command_line" : "input_file"},
       {"max_trials", nw->option(Options::IndexOption::MAX_TRIALS)},
       {"if_unbalanced", nw->option(Options::IndexOption::IF_UNBALANCED)},
       {"hydraulic_timestep_seconds",
        nw->option(Options::TimeOption::HYD_STEP)}});
  p.initSolver(EN_INITFLOW);

  for (int i = 1; i < task.h_root; ++i)
  {
    task.h = i;
    updateX(task);
    if (!task.is_feasible) return BBPrune::Reason::ACTUATIONS;
    updatePumps(task, false);
  }

  task.snapshots.resize(config.h_max + 1);
  p.copy_to(task.snapshots[0]);

  int t, dt, t_new;
  task.h = 0;
  BBPrune::Reason prune_reason = BBPrune::Reason::NONE;
  do
  {
    if (!runHydraulicSolve(task, &t))
      return BBPrune::Reason::NONE;
    CHK(p.advanceSolver(&dt), "Advance solver");
    t_new = t + dt;

    if (config.verbose)
    {
      Console::printf(Console::Color::MAGENTA, "\nTID[%d]: t_new=%d, t_max=%d, t=%d, dt=%d\n", task.tid, t_new, t_max, t, dt);
      if (config.verbose)
      {
        task.show_xy(task.h + 1);
      }
    }

    prune_reason = constraints.check_feasibility(p, dt, task.h, task.cost, config.verbose);
    if (prune_reason != BBPrune::Reason::NONE)
    {
      stats.add_stats(prune_reason, task.h + 1);
      return prune_reason;
    }

    if (t_new % 3600 == 0)
    {
      ProfileScope scope("initSnapshots");
      task.h = t_new / 3600;
      p.copy_to(task.snapshots[task.h]);
      stats.add_stats(prune_reason, task.h);
    }
  } while (task.h < (task.h_root - 1));

  return prune_reason;
}

void BBSolver::updateY(BBTask &task)
{
  if (task.h > config.h_max) throw std::runtime_error("task.h > config.h_max");

  if (task.is_feasible)
  {
    if (task.h < config.h_max)
    {
      task.y[++task.h] = 0;
      task.is_feasible = true;
      return;
    }
    if (task.y[task.h] < task.num_pumps)
    {
      task.y[task.h]++;
      task.is_feasible = true;
      return;
    }
    --task.h;
    task.is_feasible = false;
    updateY(task);
    return;
  }
  else
  {
    if (task.h == task.h_root)
    {
      if (task.y[task.h] < task.num_pumps)
      {
        task.y[task.h]++;
        task.is_feasible = true;
        return;
      }
      task.is_feasible = false;
      return;
    }
    if (task.h <= config.h_max)
    {
      if (task.y[task.h] == task.num_pumps)
      {
        --task.h;
        updateY(task);
        return;
      }
      task.y[task.h]++;
      task.is_feasible = true;
      return;
    }
  }
}

void BBSolver::updateX(BBTask &task)
{
  if (task.h < 1 || task.h > config.h_max)
    throw std::runtime_error("Invalid task.h=" + std::to_string(task.h) + " out of range [1, config.h_max=" + std::to_string(config.h_max) + "]");

  const int &y_old = task.y[task.h - 1];
  const int &y_new = task.y[task.h];

  const int *x_old = &task.x[task.num_pumps * (task.h - 1)];
  int *x_new = &task.x[task.num_pumps * task.h];

  if (config.enable_exact_disaggregation)
  {
    const auto copied_at = std::chrono::steady_clock::now();
    if (!task.disaggregation_snapshots[task.h - 1].has_value())
      throw std::runtime_error(
          "Missing exact disaggregation snapshot for parent level");
    ExactDisaggregation disaggregation =
        *task.disaggregation_snapshots[task.h - 1];
    const auto copied = std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now() - copied_at)
                            .count();

    const bool prefix_feasible = disaggregation.append(y_new);
    task.is_feasible = prefix_feasible;
    task.periodic_witness.reset();
    if (task.is_feasible && task.h == config.h_max)
    {
      task.periodic_witness = disaggregation.finish_periodic();
      task.is_feasible = task.periodic_witness.has_value();
    }

    std::fill(x_new, x_new + task.num_pumps, 0);
    std::fill(x_new, x_new + y_new, 1);
    const std::size_t resident_with_working_copy =
        estimate_resident_disaggregation_bytes(
            task.disaggregation_snapshots) +
        disaggregation.estimated_state_bytes();
    task.disaggregation_snapshots[task.h] = std::move(disaggregation);
    const std::size_t resident_after_transition =
        estimate_resident_disaggregation_bytes(
            task.disaggregation_snapshots);
    const std::size_t peak_resident_state_bytes =
        std::max(resident_with_working_copy, resident_after_transition);
    stats.record_disaggregation_transition(
        task.uid, task.h, y_new,
        std::vector<int>(x_new, x_new + task.num_pumps),
        *task.disaggregation_snapshots[task.h],
        peak_resident_state_bytes,
        static_cast<std::uint64_t>(copied), prefix_feasible,
        task.periodic_witness.has_value());
    return;
  }

  std::copy(x_old, x_old + task.num_pumps, x_new);

  if (y_new == y_old)
  {
    task.is_feasible = true;
    return;
  }

  std::vector<int> allowed_01(task.num_pumps, config.max_actuations);
  std::vector<int> allowed_10(task.num_pumps, config.max_actuations);

  BBPumpController::computeAllowedSwitches(task.num_pumps, &task.x[0], task.h, allowed_01, allowed_10);

  std::vector<int> pumps_sorted(task.num_pumps);
  for (int pump_id = 0; pump_id < task.num_pumps; ++pump_id)
    pumps_sorted[pump_id] = pump_id;

  task.is_feasible = true;
  if (y_new > y_old)
  {
    int counter_01 = y_new - y_old;
    if (config.enable_pump_sorting) BBPumpController::sortPumps(pumps_sorted, allowed_01, allowed_10, true);
    task.is_feasible = BBPumpController::switchPumpsOn(x_new, pumps_sorted, allowed_01, counter_01);
  }
  else
  {
    int counter_10 = y_old - y_new;
    if (config.enable_pump_sorting) BBPumpController::sortPumps(pumps_sorted, allowed_01, allowed_10, false);
    task.is_feasible = BBPumpController::switchPumpsOff(x_new, pumps_sorted, allowed_10, counter_10);
  }

  if (!task.is_feasible)
  {
    // We have reached the maximum number of actuations for this hour.
    if (config.verbose > 0)
    {
      Console::printf(Console::Color::RED, "\u274C updateX: h=%d, y_old=%d, y_new=%d\n", task.h, y_old, y_new, config.max_actuations);
    }
    return;
  }
}

BBPrune::Reason BBSolver::processLevel(BBTask &task)
{
  if (config.verbose)
  {
    Console::hline(Console::Color::BRIGHT_YELLOW, 20);
    Console::printf(Console::Color::BRIGHT_YELLOW, "TID[%d]: processLevel: h=%d\n", task.tid, task.h);
  }

  task.p->copy_from(task.snapshots[task.h - 1]);

  // If snapshots are disabled, we need to re-simulate from t=0 to h-1
  // This destroys the performance benefit of snapshots, allowing us to measure it.
  if (!config.enable_snapshots)
  {
      Project &p = *(task.p);
      int t_current = 0;
      int t_target_start = (task.h - 1) * 3600;
      
      // Reset solver to t=0
      // Note: We need to close and re-init to be safe, or just rely on the fact 
      // that this project object is reused. 
      // Actually, since we essentially want to simulate "what if we didn't have the snapshot",
      // we must ensure the solver is in the state it would be at t=0.
      // But wait, the task.p is already at some state. copy_from RESTORES it.
      // If we don't copy_from, we are at the state left by the previous sibling or parent... 
      // actually, without copy_from, the project state is undefined/dirty from previous DFS steps.
      // So we MUST restore a "known good" state. The only other known good state is t=0 (from initSnapshots[0]).
      
      p.copy_from(task.snapshots[0]); // Restore t=0 state
      
      // Now roll forward to h-1
      // We must apply all past controls! 
      // task.x contains the full schedule up to h (and beyond).
      // We need to re-apply pumps for 1..h-1 and simulate.
      
      int t = 0, dt = 0;
      // We are at t=0.
      for (int step_h = 1; step_h < task.h; ++step_h) 
      {
           // Apply controls for step_h
           constraints.update_pumps(p, step_h, task.x, false);
           
           // Simulate one hour
           int t_end_hour = step_h * 3600;
           do {
               if (!runHydraulicSolve(task, &t))
                   return BBPrune::Reason::NONE;
               if(p.advanceSolver(&dt) > 0) break;
               if (!constraints.check_tank_saturation(p, config.verbose))
               {
                   task.is_feasible = false;
                   return BBPrune::Reason::TANK_SATURATION;
               }
               // t += dt; // advanced by advanceSolver? No, standard EPANET usage: step(t, &dt).
               // wrapper: runSolver gets current T. advanceSolver moves it.
           } while (t + dt < t_end_hour && dt > 0);
           
           // After loop, we should be at t_end_hour.
      }
      
      // Now we are at t = (h-1)*3600, same as what copy_from(snapshot[h-1]) would give us.
      // Ready to proceed with the rest of the function.
  }

  updatePumps(task, false);
  BBPrune::Reason prune_reason = epanetSolve(task);

  if (task.is_feasible)
  {
    ProfileScope scope("processLevel");
    task.p->copy_to(task.snapshots[task.h]);
  }

  return prune_reason;
}

void BBSolver::updatePumps(BBTask &task, bool full_update)
{
  Project &p = *(task.p);
  if (full_update)
  {
    for (int i = 0; i <= task.h; ++i)
      constraints.update_pumps(p, i, task.x, config.verbose);
  }
  else
  {
    constraints.update_pumps(p, task.h, task.x, config.verbose);
  }
}

BBPrune::Reason BBSolver::epanetSolve(BBTask &task)
{
  ProfileScope scope("epanetSolve");

  const int t_min = 3600 * (task.h - 1);
  const int t_max = 3600 * task.h;
  BBPrune::Reason prune_reason = BBPrune::Reason::NONE;
  Project &p = *(task.p);

  int t = 0, dt = 0, t_new = t_min;
  do
  {
    if (!runHydraulicSolve(task, &t))
      return BBPrune::Reason::NONE;
    CHK(p.advanceSolver(&dt), "Advance solver");

    t_new = t + dt;

    if (config.verbose)
    {
      int h = std::min(t_new / 3600 + 1, task.h);
      Console::printf(Console::Color::MAGENTA, "\nSimulation: t_min=%d <= t_new=%d <= t_max=%d, dt=%d\n", t_min, t_new, t_max, dt);
      task.show_xy(h);
    }

    prune_reason = constraints.check_feasibility(p, dt, task.h, task.cost, config.verbose);

    task.is_feasible = (prune_reason == BBPrune::Reason::NONE);
    if (!task.is_feasible)
    {
      if (prune_reason == BBPrune::Reason::COST) task.y[task.h] = task.num_pumps;
      return prune_reason;
    }

    if (t_new == t_max && task.h != config.h_max) break;
  } while (dt > 0);

  if (task.is_feasible && task.h == config.h_max)
  {
    prune_reason = constraints.check_stability(p, config.verbose);
    if (prune_reason != BBPrune::Reason::NONE) return prune_reason;

    if (task.is_feasible)
    {
      if (config.verbose)
      {
        char fmt_cost_ub[100];
        if (constraints.best_cost_local == std::numeric_limits<double>::max())
          snprintf(fmt_cost_ub, sizeof(fmt_cost_ub), "inf");
        else
          snprintf(fmt_cost_ub, sizeof(fmt_cost_ub), "%.2f", constraints.best_cost_local);
        Console::printf(Console::Color::BRIGHT_GREEN, "TID[%d]: cost update: 💰 cost=%.2f, cost_ub=%s\n", task.tid, task.cost, fmt_cost_ub);
      }
      std::vector<int> witness_x(task.x.size(), 0);
      if (config.enable_exact_disaggregation &&
          task.periodic_witness.has_value())
      {
        for (std::size_t period = 0;
             period < task.periodic_witness->size(); ++period)
        {
          std::copy(
              task.periodic_witness->at(period).begin(),
              task.periodic_witness->at(period).end(),
              witness_x.begin() +
                  static_cast<std::ptrdiff_t>(
                      (period + 1) * task.num_pumps));
        }
      }
      else
      {
        witness_x = task.x;
      }
      constraints.update_best(
          task.cost, std::move(witness_x), task.y, task.x);
    }
  }

  return prune_reason;
}

bool BBSolver::runHydraulicSolve(BBTask &task, int *simulation_time)
{
  const int result = task.p->runSolver(simulation_time);
  const int solver_status = task.p->lastHydraulicStatus();
  if (solver_status == HydSolver::FAILED_NO_CONVERGENCE)
  {
    task.hydraulic_nonconvergence = true;
    task.is_feasible = false;
    stats.record_hydraulic_nonconvergence(
        task.uid, task.tid, task.h, *simulation_time, solver_status);
    return false;
  }
  CHK(result, "Run solver");
  return true;
}

// --- Free Function Implementation ---

void processTask(BBTask &task, BBConfig &config, BBConstraints &constraints, BBStatistics &stats)
{
  ProfileScope scope("processTask");
  BBSolver solver(config, constraints, stats);
  solver.solveTask(task);
}
