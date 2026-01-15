// src/CLI/ColorStream.cpp

#include "Console.h"
#include "Profiler.h"

#include <cstdio> // For vsnprintf
#include <memory> // For std::unique_ptr
#include <vector> // For dynamic buffer

bool Console::use_logger = false;
std::string Console::file_name;
std::ofstream Console::logger_file;

void Console::open(int rank, bool use_logger, bool verbose)
{
  Console::use_logger = use_logger;
  if (!use_logger) return;

  file_name = "logger_RANK_" + std::to_string(rank) + ".log";

  logger_file.open(file_name);
  if (!logger_file.is_open())
  {
    std::cerr << "Failed to open file: " << file_name << std::endl;
    exit(EXIT_FAILURE);
  }
  if (verbose) std::cout << "Logging to " << file_name << std::endl;
}

void Console::printf(Color color, const char *format, ...)
{
  // Initialize a variable argument list
  va_list args1;
  va_start(args1, format);

  // Copy args1 to args2 for measuring the required buffer size
  va_list args2;
  va_copy(args2, args1);

  // Determine the size needed for the formatted string
  int length = vsnprintf(nullptr, 0, format, args1);
  va_end(args1);

  if (length < 0)
  {
    // Handle encoding errors
    std::cerr << "Error formatting string." << std::endl;
    va_end(args2);
    return;
  }

  // Allocate buffer of the required size
  std::unique_ptr<char[]> buffer(new char[length + 1]);

  // Format the string
  vsnprintf(buffer.get(), length + 1, format, args2);
  va_end(args2);

  // Create the colored string
  if (color != Color::RESET)
  {
    std::cout << "\033[" << static_cast<int>(color) << "m" << buffer.get() << "\033[0m";
  }
  else
  {
    std::cout << buffer.get();
  }
  std::cout.flush();

  if (use_logger)
  {
    logger_file << buffer.get();
    logger_file.flush();
  }
}

void Console::hline(Color color, size_t length)
{
  // Create buffer for the line
  std::string buffer;
  buffer.reserve(length + 1);
  for (size_t i = 0; i < length; i++)
  {
    buffer += "\u2550";
  }
  buffer += "\n";

  // Output to console with color
  if (color != Color::RESET)
  {
    std::cout << "\033[" << static_cast<int>(color) << "m" << buffer << "\033[0m";
  }
  else
  {
    std::cout << buffer;
  }

  // Write to file if enabled
  if (use_logger)
  {
    logger_file << buffer;
    logger_file.flush();
  }
}

void Console::title(Color color, const std::string &title)
{
  Console::printf(color, "%s  ", title.c_str());
  Console::hline(color);
}

// Implementation of CHK function
void CHK(int err, const std::string &message)
{
  if (err != 0)
  {
    std::cerr << "ERR: " << message << " " << err << std::endl;
    exit(1);
  }
}

// Implementation of show_timer
void show_timer(int mpi_rank, unsigned int niter, int h, int done_loc, int done_all, double cost, std::vector<int> &y, std::vector<int> &y_best,
                int is_feasible, std::chrono::high_resolution_clock::time_point tic)
{
  ProfileScope scope("show_timer");

  // Only show the timer every `interval` iterations
  if (mpi_rank == 0)
  {
    auto toc = std::chrono::high_resolution_clock::now();
    double eta_secs = std::chrono::duration_cast<std::chrono::duration<double>>(toc - tic).count();
    double avg_time_per_iter_ms = eta_secs / niter * 1000;

    // Print timer
    std::cout << "\r"; // Move to the beginning of the line
    Console::printf(Console::Color::BRIGHT_BLUE, "⏱  Iter: ");
    Console::printf(Console::Color::BRIGHT_YELLOW, "%d", niter);
    Console::printf(Console::Color::BRIGHT_BLUE, " | Time: ");
    Console::printf(Console::Color::BRIGHT_CYAN, "%.2f secs", eta_secs);
    Console::printf(Console::Color::BRIGHT_BLUE, " | Avg: ");
    Console::printf(Console::Color::BRIGHT_CYAN, "%.2f ms", avg_time_per_iter_ms);

    // Print stats
    Console::printf(Console::Color::BRIGHT_BLUE, "\nRank[%d] done_loc=%d, done_all=%d, is_feasible=%d\n", mpi_rank, done_loc, done_all, is_feasible);
    Console::printf(Console::Color::BRIGHT_BLUE, "Rank[%d]: cost_best: %.2f\n", mpi_rank, cost / 100.0 ); // convert from cents to dollars
    show_vector(y_best, "Rank[" + std::to_string(mpi_rank) + "]: y_best");
    show_vector(y, "Rank[" + std::to_string(mpi_rank) + "]:     y");
  }
}

// Implementation of write_vector
void write_vector(std::ofstream &ofs, const std::vector<int> &vec, const std::string vec_name)
{
  ofs << vec_name << ": [";
  for (size_t i = 0; i < vec.size(); ++i)
  {
    ofs << vec[i];
    if (i != vec.size() - 1)
    {
      ofs << ", ";
    }
  }
  ofs << "]";
}

// Function to show a vector
void show_vector(const std::vector<int> &vec, const std::string vec_name)
{
  Console::printf(Console::Color::BRIGHT_BLUE, "%s: [ ", vec_name.c_str());
  for (size_t i = 0; i < vec.size(); ++i)
  {
    Console::printf(Console::Color::BRIGHT_CYAN, "%d ", vec[i]);
  }
  Console::printf(Console::Color::BRIGHT_BLUE, "]\n");
}

// Function to show a vector
void show_vector(int *vec, int size, const std::string vec_name)
{
  Console::printf(Console::Color::BRIGHT_BLUE, "%s: [ ", vec_name.c_str());
  for (int i = 0; i < size; ++i)
  {
    Console::printf(Console::Color::BRIGHT_CYAN, "%d ", vec[i]);
  }
  Console::printf(Console::Color::BRIGHT_BLUE, "]\n");
}
