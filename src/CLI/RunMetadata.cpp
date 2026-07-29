#include "RunMetadata.h"

#include "BuildMetadata.h"

#include <array>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <thread>

#if defined(__unix__) || defined(__APPLE__)
#include <sys/utsname.h>
#include <unistd.h>
#endif

namespace
{

constexpr std::array<std::uint32_t, 64> constants = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b,
    0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7,
    0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152,
    0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
    0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

std::uint32_t rotate_right(std::uint32_t value, unsigned count)
{
  return (value >> count) | (value << (32 - count));
}

class Sha256
{
public:
  void update(const unsigned char *data, std::size_t size)
  {
    for (std::size_t i = 0; i < size; ++i)
    {
      block_[block_size_++] = data[i];
      if (block_size_ == block_.size())
      {
        transform();
        bit_count_ += 512;
        block_size_ = 0;
      }
    }
  }

  std::string finish()
  {
    bit_count_ += static_cast<std::uint64_t>(block_size_) * 8;
    block_[block_size_++] = 0x80;
    if (block_size_ > 56)
    {
      while (block_size_ < block_.size())
        block_[block_size_++] = 0;
      transform();
      block_size_ = 0;
    }
    while (block_size_ < 56)
      block_[block_size_++] = 0;
    for (int byte = 7; byte >= 0; --byte)
      block_[block_size_++] =
          static_cast<unsigned char>(bit_count_ >> (byte * 8));
    transform();

    std::ostringstream result;
    result << std::hex << std::setfill('0');
    for (std::uint32_t word : state_)
      result << std::setw(8) << word;
    return result.str();
  }

private:
  void transform()
  {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t i = 0; i < 16; ++i)
    {
      words[i] =
          (static_cast<std::uint32_t>(block_[4 * i]) << 24) |
          (static_cast<std::uint32_t>(block_[4 * i + 1]) << 16) |
          (static_cast<std::uint32_t>(block_[4 * i + 2]) << 8) |
          static_cast<std::uint32_t>(block_[4 * i + 3]);
    }
    for (std::size_t i = 16; i < words.size(); ++i)
    {
      const std::uint32_t s0 =
          rotate_right(words[i - 15], 7) ^
          rotate_right(words[i - 15], 18) ^ (words[i - 15] >> 3);
      const std::uint32_t s1 =
          rotate_right(words[i - 2], 17) ^
          rotate_right(words[i - 2], 19) ^ (words[i - 2] >> 10);
      words[i] = words[i - 16] + s0 + words[i - 7] + s1;
    }

    auto work = state_;
    for (std::size_t i = 0; i < words.size(); ++i)
    {
      const std::uint32_t sum1 =
          rotate_right(work[4], 6) ^ rotate_right(work[4], 11) ^
          rotate_right(work[4], 25);
      const std::uint32_t choice =
          (work[4] & work[5]) ^ (~work[4] & work[6]);
      const std::uint32_t temp1 =
          work[7] + sum1 + choice + constants[i] + words[i];
      const std::uint32_t sum0 =
          rotate_right(work[0], 2) ^ rotate_right(work[0], 13) ^
          rotate_right(work[0], 22);
      const std::uint32_t majority =
          (work[0] & work[1]) ^ (work[0] & work[2]) ^
          (work[1] & work[2]);
      const std::uint32_t temp2 = sum0 + majority;

      work[7] = work[6];
      work[6] = work[5];
      work[5] = work[4];
      work[4] = work[3] + temp1;
      work[3] = work[2];
      work[2] = work[1];
      work[1] = work[0];
      work[0] = temp1 + temp2;
    }
    for (std::size_t i = 0; i < state_.size(); ++i)
      state_[i] += work[i];
  }

  std::array<std::uint32_t, 8> state_ = {
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  std::array<unsigned char, 64> block_{};
  std::size_t block_size_ = 0;
  std::uint64_t bit_count_ = 0;
};

std::filesystem::path resolve_running_executable(
    const std::string &invocation)
{
  std::error_code error;
#if defined(__linux__)
  const auto proc_executable =
      std::filesystem::read_symlink("/proc/self/exe", error);
  if (!error && !proc_executable.empty())
    return std::filesystem::weakly_canonical(proc_executable);
#endif

  const std::filesystem::path candidate(invocation);
  if (candidate.is_absolute() || candidate.has_parent_path())
  {
    const auto resolved = std::filesystem::weakly_canonical(candidate, error);
    if (!error && std::filesystem::is_regular_file(resolved))
      return resolved;
  }

  const char *path_environment = std::getenv("PATH");
  if (path_environment != nullptr)
  {
    std::istringstream paths(path_environment);
    std::string directory;
#if defined(_WIN32)
    constexpr char separator = ';';
#else
    constexpr char separator = ':';
#endif
    while (std::getline(paths, directory, separator))
    {
      const auto path_candidate =
          (directory.empty() ? std::filesystem::current_path()
                             : std::filesystem::path(directory)) /
          candidate;
      error.clear();
      const auto resolved =
          std::filesystem::weakly_canonical(path_candidate, error);
      if (!error && std::filesystem::is_regular_file(resolved))
        return resolved;
    }
  }

  throw std::runtime_error(
      "Cannot resolve running executable from invocation: " + invocation);
}

} // namespace

std::string RunMetadata::sha256(const std::string &file_path)
{
  std::ifstream input(file_path, std::ios::binary);
  if (!input)
    throw std::runtime_error("Cannot hash executable: " + file_path);

  Sha256 hash;
  std::array<unsigned char, 65536> buffer{};
  while (input)
  {
    input.read(reinterpret_cast<char *>(buffer.data()), buffer.size());
    hash.update(buffer.data(), static_cast<std::size_t>(input.gcount()));
  }
  return hash.finish();
}

nlohmann::json RunMetadata::capture(
    const std::string &executable_path, int mpi_processes)
{
  const auto resolved = resolve_running_executable(executable_path);
  std::string hostname = "unknown";
  std::string operating_system = "unknown";
#if defined(__unix__) || defined(__APPLE__)
  std::array<char, 256> hostname_buffer{};
  if (gethostname(hostname_buffer.data(), hostname_buffer.size()) == 0)
    hostname = hostname_buffer.data();
  struct utsname system_information
  {
  };
  if (uname(&system_information) == 0)
  {
    operating_system =
        std::string(system_information.sysname) + " " +
        system_information.release + " " + system_information.machine;
  }
#endif

  return {
      {"software",
       {{"git_commit", EPANET_BB_GIT_COMMIT},
        {"git_tree_state_at_configure", EPANET_BB_GIT_TREE_STATE},
        {"executable", resolved.string()},
        {"executable_sha256", sha256(resolved.string())},
        {"compiler",
         {{"id", EPANET_BB_COMPILER_ID},
          {"version", EPANET_BB_COMPILER_VERSION},
          {"base_flags", EPANET_BB_BASE_COMPILER_FLAGS},
          {"effective_compile_options",
           EPANET_BB_EFFECTIVE_COMPILE_OPTIONS},
          {"interprocedural_optimization",
           static_cast<bool>(
               EPANET_BB_INTERPROCEDURAL_OPTIMIZATION)}}},
        {"build_type", EPANET_BB_BUILD_TYPE}}},
      {"hardware",
       {{"hostname", hostname},
        {"operating_system", operating_system},
        {"logical_concurrency", std::thread::hardware_concurrency()}}},
      {"mpi_processes", mpi_processes}};
}
