#include "Profiler.h"
#include "Console.h"
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <mpi.h>

// Definition of static members
std::stack<Profiler::StackFrame> Profiler::callStack;
std::unordered_map<std::string, std::chrono::microseconds> Profiler::profile;

void Profiler::push(const std::string &name)
{
  callStack.push({name, std::chrono::high_resolution_clock::now()});
}

void Profiler::pop()
{
  auto [name, start_time] = callStack.top();
  auto end_time = std::chrono::high_resolution_clock::now();
  profile[name] += std::chrono::duration_cast<std::chrono::microseconds>(end_time - start_time);
  callStack.pop();
}

const std::unordered_map<std::string, std::chrono::microseconds> &Profiler::getProfile()
{
  return profile;
}

void Profiler::save(const std::string &fn)
{
  int rank;
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);

  if (rank == 0)
  {
    Console::printf(Console::Color::BRIGHT_GREEN, "Save profile to file: %s\n", fn.c_str());
  }

  std::ofstream outfile(fn);
  outfile << "=== Profiling Results (Rank " << rank << ") ===\n";

  if (profile.empty())
  {
    outfile << "No profiling data collected.\n";
    outfile << "=====================\n";
    outfile.close();
    return;
  }

  std::vector<std::pair<std::string, std::chrono::microseconds>> sorted_profile(profile.begin(), profile.end());
  std::sort(sorted_profile.begin(), sorted_profile.end(), [](const auto &a, const auto &b) { return a.second > b.second; });

  auto max_duration = sorted_profile.front().second.count();
  outfile << std::fixed << std::setprecision(2);

  for (const auto &[name, duration] : sorted_profile)
  {
    double ms = duration.count() / 1000.0;
    double percentage = (max_duration > 0) ? (duration.count() * 100.0) / max_duration : 0.0;
    outfile << std::left << std::setw(30) << name << ": " << std::right << std::setw(8) << ms << " ms" << " (" << std::setw(5) << percentage
            << "%)\n";
  }
  outfile << "=====================\n";
  outfile.close();
}
