cmake_minimum_required(VERSION 3.14)
project(epanet3-bb LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Dependencies
find_package(MPI REQUIRED)

# Use system nlohmann-json instead of FetchContent for faster builds
find_package(nlohmann_json 3.11.0 QUIET)
if(NOT nlohmann_json_FOUND)
    include(FetchContent)
    FetchContent_Declare(json
        GIT_REPOSITORY https://github.com/nlohmann/json.git
        GIT_TAG v3.11.3
    )
    FetchContent_MakeAvailable(json)
endif()

# Compiler Flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    if(NOT CMAKE_BUILD_TYPE STREQUAL "Debug")
        # Basic optimizations
        add_compile_options(-O3 -march=native -mtune=native -funroll-loops -fomit-frame-pointer)
        
        # Fast math can significantly speed up hydraulic calculations
        add_compile_options(-ffast-math)
        
        # Link-time optimization (LTO / IPO)
        include(CheckIPOSupported)
        check_ipo_supported(RESULT ipo_supported OUTPUT ipo_error)
        if(ipo_supported)
            set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
        else()
            message(WARNING "IPO is not supported: ${ipo_error}")
        endif()

        # Shared library optimizations
        add_compile_options(-fno-semantic-interposition)
    endif()
endif()

# --- EPANET-BB ---

# Source Gathering Helper
function(get_sources_and_lib_srcs DIR CLI_DIR OUT_ALL_SRCS OUT_LIB_SRCS OUT_CLI_SRCS)
    file(GLOB_RECURSE ALL_SRCS "${DIR}/*.cpp")
    file(GLOB CLI_SRCS "${CLI_DIR}/*.cpp")
    
    # Exclude CLI sources from Lib sources
    set(LIB_SRCS ${ALL_SRCS})
    if(CLI_SRCS)
        list(REMOVE_ITEM LIB_SRCS ${CLI_SRCS})
    endif()
    
    set(${OUT_ALL_SRCS} ${ALL_SRCS} PARENT_SCOPE)
    set(${OUT_LIB_SRCS} ${LIB_SRCS} PARENT_SCOPE)
    set(${OUT_CLI_SRCS} ${CLI_SRCS} PARENT_SCOPE)
endfunction()

# --- Main Build ---

# Sources
get_sources_and_lib_srcs("${CMAKE_CURRENT_SOURCE_DIR}/src" "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI" SRCS SRCS_LIB SRCS_CLI)

# Main Library (B&B version)
add_library(epanet3-bb SHARED ${SRCS_LIB})
target_include_directories(epanet3-bb PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI"
    "${CMAKE_CURRENT_SOURCE_DIR}/include" # Assuming include dir if exists, otherwise src is fine
)
target_link_libraries(epanet3-bb PUBLIC MPI::MPI_CXX nlohmann_json::nlohmann_json)

# Executables
set(MAIN_SRC "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI/main.cpp")
set(EVAL_SRC "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI/main-eval.cpp")

# Filter out main files from CLI common sources
set(SRCS_CLI_COMMON ${SRCS_CLI})
list(REMOVE_ITEM SRCS_CLI_COMMON ${MAIN_SRC} ${EVAL_SRC})

# run-epanet3-bb (B&B optimizer)
add_executable(run-epanet3-bb ${MAIN_SRC} ${SRCS_CLI_COMMON})
target_include_directories(run-epanet3-bb PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(run-epanet3-bb PRIVATE epanet3-bb)

# run-epanet3-bb-eval (B&B evaluation mode)
add_executable(run-epanet3-bb-eval ${EVAL_SRC} ${SRCS_CLI_COMMON})
target_include_directories(run-epanet3-bb-eval PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(run-epanet3-bb-eval PRIVATE epanet3-bb)
