#pragma once

#include <nlohmann/json.hpp>
#include <string>

class RunMetadata
{
public:
  static nlohmann::json capture(
      const std::string &executable_path, int mpi_processes);
  static std::string sha256(const std::string &file_path);
};
