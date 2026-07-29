cmake_minimum_required(VERSION 3.14)
project(epanet3-bb LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

execute_process(
    COMMAND git rev-parse HEAD
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    OUTPUT_VARIABLE EPANET_BB_GIT_COMMIT
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
)
if(NOT EPANET_BB_GIT_COMMIT)
    set(EPANET_BB_GIT_COMMIT "unknown")
endif()
execute_process(
    COMMAND git status --porcelain
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    OUTPUT_VARIABLE EPANET_BB_GIT_STATUS
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
)
if(EPANET_BB_GIT_STATUS)
    set(EPANET_BB_GIT_TREE_STATE "dirty")
else()
    set(EPANET_BB_GIT_TREE_STATE "clean")
endif()
string(TOUPPER "${CMAKE_BUILD_TYPE}" EPANET_BB_BUILD_TYPE_UPPER)
set(EPANET_BB_BASE_COMPILER_FLAGS
    "${CMAKE_CXX_FLAGS} ${CMAKE_CXX_FLAGS_${EPANET_BB_BUILD_TYPE_UPPER}}")

include(CTest)

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

get_directory_property(
    EPANET_BB_EFFECTIVE_COMPILE_OPTIONS COMPILE_OPTIONS
)
string(JOIN " " EPANET_BB_EFFECTIVE_COMPILE_OPTIONS
    ${EPANET_BB_EFFECTIVE_COMPILE_OPTIONS}
)
if(CMAKE_INTERPROCEDURAL_OPTIMIZATION)
    set(EPANET_BB_INTERPROCEDURAL_OPTIMIZATION 1)
else()
    set(EPANET_BB_INTERPROCEDURAL_OPTIMIZATION 0)
endif()
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI/BuildMetadata.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/BuildMetadata.h"
    @ONLY
)

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

set(EXACT_DISAGGREGATION_SRC
    "${CMAKE_CURRENT_SOURCE_DIR}/src/Optimization/ExactDisaggregation.cpp"
)
list(REMOVE_ITEM SRCS_LIB ${EXACT_DISAGGREGATION_SRC})

add_library(exact-disaggregation STATIC ${EXACT_DISAGGREGATION_SRC})
target_include_directories(exact-disaggregation PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
)

# Main Library (B&B version)
add_library(epanet3-bb SHARED ${SRCS_LIB})
target_include_directories(epanet3-bb PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI"
    "${CMAKE_CURRENT_SOURCE_DIR}/include" # Assuming include dir if exists, otherwise src is fine
    "${CMAKE_CURRENT_BINARY_DIR}/generated"
)
target_link_libraries(epanet3-bb PUBLIC
    exact-disaggregation
    MPI::MPI_CXX
    nlohmann_json::nlohmann_json
)

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

if(BUILD_TESTING)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)

    add_executable(ExactDisaggregationTest
        tests/test_exact_disaggregation.cpp
    )
    target_include_directories(ExactDisaggregationTest PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(ExactDisaggregationTest PRIVATE exact-disaggregation)
    add_test(NAME ExactDisaggregationTest COMMAND ExactDisaggregationTest)

    add_executable(ExactDisaggregationQuery
        tests/exact_disaggregation_query.cpp
    )
    target_include_directories(ExactDisaggregationQuery PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(ExactDisaggregationQuery PRIVATE
        exact-disaggregation
        nlohmann_json::nlohmann_json
    )

    add_test(
        NAME ExactDisaggregationOracle
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/oracles/exhaustive_disaggregation.py"
            "$<TARGET_FILE:ExactDisaggregationQuery>"
    )

    add_executable(TankSaturationTest
        tests/test_tank_saturation.cpp
    )
    target_include_directories(TankSaturationTest PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(TankSaturationTest PRIVATE epanet3-bb)
    add_test(
        NAME TankSaturationTest
        COMMAND
            TankSaturationTest
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/data/tank_filling_to_maximum.inp"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/data/tank_draining_to_minimum.inp"
    )

    add_executable(TankSaturationPruneTest
        tests/test_tank_saturation_pruning.cpp
        src/CLI/BBConstraints.cpp
        src/CLI/Console.cpp
        src/CLI/Profiler.cpp
    )
    target_include_directories(TankSaturationPruneTest PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI"
    )
    target_link_libraries(TankSaturationPruneTest PRIVATE epanet3-bb)
    add_test(
        NAME TankSaturationPruneTest
        COMMAND
            TankSaturationPruneTest
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/data/tank_filling_to_maximum.inp"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/data/tank_draining_to_minimum.inp"
    )

    add_executable(IntegratedSearchTest
        tests/test_integrated_search.cpp
        src/CLI/BBConstraints.cpp
        src/CLI/BBSolver.cpp
        src/CLI/BBStatistics.cpp
        src/CLI/Console.cpp
        src/CLI/Profiler.cpp
        src/CLI/RunMetadata.cpp
    )
    target_include_directories(IntegratedSearchTest PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/CLI"
    )
    target_link_libraries(IntegratedSearchTest PRIVATE epanet3-bb)
    add_test(
        NAME IntegratedSearchTest
        COMMAND
            IntegratedSearchTest
            "${CMAKE_CURRENT_SOURCE_DIR}/networks/any-town.inp"
            "${CMAKE_CURRENT_BINARY_DIR}/phase3-integrated-search.json"
    )

    add_test(
        NAME FixedScheduleEvaluatorTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_fixed_schedule_evaluator.py"
            $<TARGET_FILE:run-epanet3-bb-eval>
            "${CMAKE_CURRENT_SOURCE_DIR}/networks/any-town.inp"
            "${CMAKE_CURRENT_SOURCE_DIR}/experiments/results/final-cases-anytown-24h-summary.json"
            "${CMAKE_CURRENT_SOURCE_DIR}/experiments/comparison-schedules/run_Cimorelli2020_a_01.json"
            /usr/bin/mpiexec
    )

    add_test(
        NAME ComparisonScheduleEvaluationTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_evaluate_comparison_schedules.py"
            $<TARGET_FILE:run-epanet3-bb-eval>
            /usr/bin/mpiexec
    )

    add_test(
        NAME AccuracySensitivityRunnerTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_accuracy_sensitivity.py"
    )

    add_test(
        NAME TuningRunnerTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_run_tuning.py"
    )

    add_test(
        NAME PythonDependencyAuditTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/scripts/validate_python_environment.py"
            --audit-only
    )

    add_test(
        NAME PortableExperimentRunnerTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_run_experiments.py"
    )

    add_test(
        NAME ReproducibleCampaignRunnerTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_run_campaign.py"
    )

    add_test(
        NAME ManuscriptRebuildTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_rebuild_manuscript.py"
    )

    add_test(
        NAME AggregateOutputsTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_agg_outputs.py"
    )

    add_test(
        NAME AblationSummaryTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_summarize_ablation.py"
    )

    add_test(
        NAME ScalabilitySummaryTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_summarize_scalability.py"
    )

    add_test(
        NAME FinalCasesSummaryTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_summarize_final_cases.py"
    )

    add_test(
        NAME ManuscriptArtifactPreparationTest
        COMMAND
            ${Python3_EXECUTABLE}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_prepare_manuscript_artifacts.py"
    )
endif()
