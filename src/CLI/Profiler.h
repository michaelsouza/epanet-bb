// src/CLI/Profiler.h
#pragma once

#include <chrono>
#include <stack>
#include <string>
#include <unordered_map>
#include <vector>

/**
 * @class Profiler
 * @brief A static utility class for hierarchical performance profiling.
 *
 * This class provides a simple, stack-based profiler to measure the execution time
 * of different scopes within the code. It is not meant to be instantiated.
 * All methods and data are static.
 */
class Profiler
{
public:
  /**
   * @brief Pushes a new named scope onto the profiling stack and records the start time.
   * @param name The name of the scope to profile.
   */
  static void push(const std::string &name);

  /**
   * @brief Pops the current scope from the stack, calculates the duration, and adds it to the total for that scope name.
   */
  static void pop();

  /**
   * @brief Gets a constant reference to the raw profiling data.
   * @return A map where keys are scope names and values are total accumulated durations.
   */
  static const std::unordered_map<std::string, std::chrono::microseconds> &getProfile();

  /**
   * @brief Saves the collected profiling data to a file, sorted by duration in descending order.
   * @param fn The name of the output file.
   */
  static void save(const std::string &fn);

private:
  /**
   * @struct StackFrame
   * @brief Represents a single entry on the profiler's call stack.
   */
  struct StackFrame
  {
    std::string name;                                          ///< The name of the profiled scope.
    std::chrono::high_resolution_clock::time_point start_time; ///< The time point when the scope was entered.
  };

  // Declaration of static members
  static std::stack<StackFrame> callStack;
  static std::unordered_map<std::string, std::chrono::microseconds> profile;

  /**
   * @brief Deleted constructor to prevent instantiation of this utility class.
   */
  Profiler() = delete;

  friend class ProfileScope;
};

/**
 * @class ProfileScope
 * @brief An RAII (Resource Acquisition Is Initialization) helper for easy profiling.
 *
 * Creates a scope-based timer that automatically calls Profiler::push on construction
 * and Profiler::pop on destruction.
 * @example
 * void my_function()
 * {
 *   ProfileScope scope("my_function");
 *   // Code to be profiled...
 * } // Profiler::pop() is automatically called here
 */
class ProfileScope
{
public:
  /**
   * @brief Constructs the scope and starts the timer for the given name.
   * @param name The name of the scope to profile.
   */
  explicit ProfileScope(const std::string &name) : name_(name)
  {
    Profiler::push(name_);
  }

  /**
   * @brief Destructs the scope and stops the timer.
   */
  ~ProfileScope()
  {
    Profiler::pop();
  }

private:
  std::string name_;

  // Prevent copying and assignment
  ProfileScope(const ProfileScope &) = delete;
  ProfileScope &operator=(const ProfileScope &) = delete;
};
