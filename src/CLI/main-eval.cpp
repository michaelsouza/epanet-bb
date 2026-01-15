// src/CLI/main-eval.cpp
// Evaluates a complete pump schedule (y vector) without branch-and-bound.
// Reads input from JSON file and outputs feasibility and cost.

#include "BBConfig.h"
#include "BBConstraints.h"
#include "BBSolver.h"
#include "Console.h"

#include "Core/project.h"

#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

using Epanet::Project;
using json = nlohmann::json;

struct EvalResult
{
  bool feasible = false;
  double cost = 0.0;
  BBPrune::Reason prune_reason = BBPrune::Reason::NONE;
  int hour_failed = -1;
  std::vector<int> x;
  std::vector<int> y;
};

// Converts y[h] to x[h] using actuation constraints (adapted from BBSolver::updateX)
bool updateX(int h, int h_max, int num_pumps, int max_actuations, std::vector<int> &x, const std::vector<int> &y)
{
  if (h < 1 || h > h_max)
    throw std::runtime_error("Invalid h=" + std::to_string(h) + " out of range [1, " + std::to_string(h_max) + "]");

  const int y_old = y[h - 1];
  const int y_new = y[h];

  const int *x_old = &x[num_pumps * (h - 1)];
  int *x_new = &x[num_pumps * h];

  std::copy(x_old, x_old + num_pumps, x_new);

  if (y_new == y_old)
    return true;

  std::vector<int> allowed_01(num_pumps, max_actuations);
  std::vector<int> allowed_10(num_pumps, max_actuations);

  BBPumpController::computeAllowedSwitches(num_pumps, &x[0], h, allowed_01, allowed_10);

  std::vector<int> pumps_sorted(num_pumps);
  for (int pump_id = 0; pump_id < num_pumps; ++pump_id)
    pumps_sorted[pump_id] = pump_id;

  bool success = true;
  if (y_new > y_old)
  {
    int counter_01 = y_new - y_old;
    BBPumpController::sortPumps(pumps_sorted, allowed_01, allowed_10, true);
    success = BBPumpController::switchPumpsOn(x_new, pumps_sorted, allowed_01, counter_01);
  }
  else
  {
    int counter_10 = y_old - y_new;
    BBPumpController::sortPumps(pumps_sorted, allowed_01, allowed_10, false);
    success = BBPumpController::switchPumpsOff(x_new, pumps_sorted, allowed_10, counter_10);
  }

  return success;
}

EvalResult evaluateSolution(const std::vector<int> &y, int h_max, int max_actuations, const std::string &inpFile,
                            int verbose)
{
  EvalResult result;
  result.y = y;

  // Create a minimal config for BBConstraints
  BBConfig config;
  config.inpFile = inpFile;
  config.h_max = h_max;
  config.max_actuations = max_actuations;
  config.enable_cost_pruning = false;
  config.enable_global_sync = false;
  config.verbose = verbose;

  BBConstraints constraints(config);
  int num_pumps = constraints.get_num_pumps();

  // Initialize x vector (all pumps off at h=0)
  result.x.resize((h_max + 1) * num_pumps, 0);

  // Load EPANET project
  Project p;
  if (p.load(inpFile.c_str()) != 0)
  {
    Console::printf(Console::Color::RED, "Error: Failed to load EPANET input file: %s\n", inpFile.c_str());
    result.prune_reason = BBPrune::Reason::NONE;
    return result;
  }

  // Set simulation duration
  Network *nw = p.getNetwork();
  int t_max = 3600 * h_max;
  nw->options.setOption(Options::TimeOption::TOTAL_DURATION, t_max);

  // Initialize solver
  if (p.initSolver(EN_INITFLOW) != 0)
  {
    Console::printf(Console::Color::RED, "Error: Failed to initialize solver\n");
    return result;
  }

  // Simulate hour by hour
  double cost = 0.0;
  for (int h = 1; h <= h_max; ++h)
  {
    // Convert y[h] to x[h]
    if (!updateX(h, h_max, num_pumps, max_actuations, result.x, y))
    {
      result.prune_reason = BBPrune::Reason::ACTUATIONS;
      result.hour_failed = h;
      if (verbose)
        Console::printf(Console::Color::RED, "Hour %d: INFEASIBLE (actuations constraint violated)\n", h);
      return result;
    }

    // Apply pump settings
    constraints.update_pumps(p, h, result.x, verbose);

    // Run simulation for this hour
    int t_min = 3600 * (h - 1);
    int t_target = 3600 * h;
    int t = 0, dt = 0;

    do
    {
      if (p.runSolver(&t) != 0)
      {
        Console::printf(Console::Color::RED, "Error: runSolver failed at hour %d\n", h);
        return result;
      }
      if (p.advanceSolver(&dt) != 0)
      {
        Console::printf(Console::Color::RED, "Error: advanceSolver failed at hour %d\n", h);
        return result;
      }

      int t_new = t + dt;

      if (verbose)
      {
        Console::printf(Console::Color::CYAN, "Hour %d: t=%d -> t_new=%d (dt=%d)\n", h, t, t_new, dt);
      }

      // Check feasibility
      BBPrune::Reason reason = constraints.check_feasibility(p, dt, h, cost, verbose);
      if (reason != BBPrune::Reason::NONE)
      {
        result.prune_reason = reason;
        result.hour_failed = h;
        result.cost = cost;
        if (verbose)
          Console::printf(Console::Color::RED, "Hour %d: INFEASIBLE (%s)\n", h, BBPrune::labels[reason].c_str());
        return result;
      }

      if (t_new >= t_target)
        break;
    } while (dt > 0);

    if (verbose)
    {
      Console::printf(Console::Color::GREEN, "Hour %d: OK (cost so far: %.2f)\n", h, cost);
    }
  }

  // Check final stability (tank levels must return to initial)
  BBPrune::Reason stability_reason = constraints.check_stability(p, verbose);
  if (stability_reason != BBPrune::Reason::NONE)
  {
    result.prune_reason = stability_reason;
    result.hour_failed = h_max;
    result.cost = cost;
    if (verbose)
      Console::printf(Console::Color::RED, "Stability check: INFEASIBLE\n");
    return result;
  }

  // Success!
  result.feasible = true;
  result.cost = cost;
  result.prune_reason = BBPrune::Reason::NONE;

  if (verbose)
  {
    Console::printf(Console::Color::BRIGHT_GREEN, "\nSolution is FEASIBLE with cost: %.2f\n", cost);
  }

  return result;
}

void printUsage(const char *prog)
{
  std::cerr << "Usage: " << prog << " <input.json> [output.json]\n";
  std::cerr << "\nInput JSON format:\n";
  std::cerr << "{\n";
  std::cerr << "  \"y\": [0, 1, 1, 2, ...],  // pump count per hour (length = h_max + 1)\n";
  std::cerr << "  \"h_max\": 24,             // simulation hours\n";
  std::cerr << "  \"max_actuations\": 1,     // max pump switches\n";
  std::cerr << "  \"inp_file\": \"networks/anytown-24h.inp\",  // optional, default: networks/anytown-24h.inp\n";
  std::cerr << "  \"verbose\": 0             // optional (int, default 0)\n";
  std::cerr << "}\n";
}

int main(int argc, char *argv[])
{
  // MPI init (required by epanet3-bb library)
  MPI_Init(&argc, &argv);

  if (argc < 2)
  {
    printUsage(argv[0]);
    MPI_Finalize();
    return EXIT_FAILURE;
  }

  std::string inputFile = argv[1];
  std::string outputFile = (argc >= 3) ? argv[2] : "";

  // Read input JSON
  std::ifstream ifs(inputFile);
  if (!ifs.is_open())
  {
    std::cerr << "Error: Cannot open input file: " << inputFile << "\n";
    MPI_Finalize();
    return EXIT_FAILURE;
  }

  json input;
  try
  {
    ifs >> input;
  }
  catch (const json::parse_error &e)
  {
    std::cerr << "Error: Failed to parse JSON: " << e.what() << "\n";
    MPI_Finalize();
    return EXIT_FAILURE;
  }

  // Extract parameters
  if (!input.contains("best_y") || !input["best_y"].is_array())
  {
    std::cerr << "Error: Input JSON must contain 'best_y' array\n";
    MPI_Finalize();
    return EXIT_FAILURE;
  }

  std::vector<int> y = input["best_y"].get<std::vector<int>>();
  int h_max = input.value("h_max", 24);
  int max_actuations = input.value("max_actuations", 1);
  std::string inpFile = input.value("inp_file", "networks/anytown.inp");
  
  // Handle verbose as int, but allow bool (true -> 1, false -> 0)
  int verbose = 0;
  if (input.contains("verbose"))
  {
    auto &v = input["verbose"];
    if (v.is_boolean())
    {
      verbose = v.get<bool>() ? 1 : 0;
    }
    else if (v.is_number_integer())
    {
      verbose = v.get<int>();
    }
  }

  // Validate y vector size
  if ((int)y.size() != h_max + 1)
  {
    std::cerr << "Error: y vector size (" << y.size() << ") must be h_max + 1 (" << h_max + 1 << ")\n";
    MPI_Finalize();
    return EXIT_FAILURE;
  }

  // Evaluate solution
  Console::printf(Console::Color::BRIGHT_WHITE, "Evaluating solution from: %s\n", inputFile.c_str());
  Console::printf(Console::Color::BRIGHT_WHITE, "  h_max: %d, max_actuations: %d\n", h_max, max_actuations);
  Console::printf(Console::Color::BRIGHT_WHITE, "  inp_file: %s\n", inpFile.c_str());

  EvalResult result = evaluateSolution(y, h_max, max_actuations, inpFile, verbose);

  // Build output JSON
  json output;
  output["feasible"] = result.feasible;
  output["cost"] = result.cost / 100.0; // convert cents to dollars
  output["prune_reason"] = BBPrune::labels[result.prune_reason];
  output["hour_failed"] = result.hour_failed >= 0 ? json(result.hour_failed) : json(nullptr);
  
  // Output result
  if (outputFile.empty())
  {
    // Print to stdout
    std::cout << output.dump(2) << "\n";
  }
  else
  {
    output["x"] = result.x;
    output["y"] = result.y;
    // Write to file
    std::ofstream ofs(outputFile);
    if (!ofs.is_open())
    {
      std::cerr << "Error: Cannot open output file: " << outputFile << "\n";
      MPI_Finalize();
      return EXIT_FAILURE;
    }
    ofs << output.dump(2) << "\n";
    Console::printf(Console::Color::BRIGHT_GREEN, "Result written to: %s\n", outputFile.c_str());
  }

  // Summary
  Console::printf(Console::Color::BRIGHT_WHITE, "\n=== RESULT ===\n");
  if (result.feasible)
  {
    Console::printf(Console::Color::BRIGHT_GREEN, "FEASIBLE - Cost: $%.2f\n", result.cost / 100.0);
  }
  else
  {
    Console::printf(Console::Color::BRIGHT_RED, "INFEASIBLE - Reason: %s at hour %d\n",
                    BBPrune::labels[result.prune_reason].c_str(), result.hour_failed);
  }

  MPI_Finalize();
  return result.feasible ? EXIT_SUCCESS : EXIT_FAILURE;
}
