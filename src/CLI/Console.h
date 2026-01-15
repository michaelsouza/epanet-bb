// src/CLI/ColorStream.h
#pragma once

#include <chrono>
#include <cstdarg> // For variadic functions
#include <ctime>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

class Console
{
public:
  /**
   * @brief Enumeration for different color codes.
   */
  enum class Color
  {
    RESET = 0,
    RED = 31,
    GREEN = 32,
    YELLOW = 33,
    BLUE = 34,
    MAGENTA = 35,
    CYAN = 36,
    WHITE = 37,
    ORANGE = 38,
    BRIGHT_RED = 91,
    BRIGHT_GREEN = 92,
    BRIGHT_YELLOW = 93,
    BRIGHT_BLUE = 94,
    BRIGHT_MAGENTA = 95,
    BRIGHT_CYAN = 96,
    BRIGHT_WHITE = 97
  };

  static bool use_logger;
  static std::string file_name;
  static std::ofstream logger_file;

  static void open(int rank, bool use_file = true, bool verbose = false);

  static void close()
  {
    logger_file.close();
    use_logger = false;
  }

  /**
   * @brief Prints formatted text with the specified color.
   *
   * @param color Color to apply.
   * @param format Format string similar to printf.
   * @param ... Variable arguments corresponding to the format specifiers.
   */
  static void printf(Color color, const char *format, ...);

  static void hline(Color color, size_t length = 10);

  static void title(Color color, const std::string &title);

private:
};

// Function to check error codes and exit if an error occurs
void CHK(int err, const std::string &message);

// Function to display a timer
void show_timer(int mpi_rank, unsigned int niter, int h, int done_loc, int done_all, double cost_best, std::vector<int> &y, std::vector<int> &y_best,
                int is_feasible, std::chrono::high_resolution_clock::time_point tic);

// Function to write a vector to a file
void write_vector(std::ofstream &ofs, const std::vector<int> &vec, const std::string vec_name);

// Function to write a vector to a file
void show_vector(const std::vector<int> &vec, const std::string vec_name);

// Function to show a vector
void show_vector(int *vec, int size, const std::string vec_name);
