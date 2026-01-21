cmake_minimum_required(VERSION 3.12)
project(ConnextStarterKit VERSION 1.0.0 LANGUAGES CXX)

# ============================================================================
# Check if CONNEXTDDS_ARCH is set
# ============================================================================
if(NOT DEFINED CONNEXTDDS_ARCH AND NOT DEFINED ENV{CONNEXTDDS_ARCH})
    message(FATAL_ERROR 
        "========================================================================"
        "\nERROR: CONNEXTDDS_ARCH is not set."
        "\n========================================================================"
        "\nHelper scripts to set the environment are included in the Connext"
        "\ninstallation directory, typically found at:"
        "\n  <install_dir>/resource/scripts/rtisetenv_<target>.bash"
        "\nExamples:"
        "\n  source /opt/rti_connext_dds-7.3.0/resource/scripts/rtisetenv_x64Linux4gcc7.3.0.bash"
        "\nOr set it manually:"
        "\n  export CONNEXTDDS_ARCH=x64Linux4gcc7.3.0"
        "\nOr pass it to cmake:"
        "\n  cmake .. -DCONNEXTDDS_ARCH=x64Linux4gcc7.3.0"
        "\n========================================================================"
    )
endif()

# Get the architecture (from environment or CMake variable)
if(NOT CONNEXTDDS_ARCH)
    set(CONNEXTDDS_ARCH $ENV{CONNEXTDDS_ARCH})
endif()

message(STATUS "========================================================================")
message(STATUS "RTI Connext DDS Target Architecture: ${CONNEXTDDS_ARCH}")
message(STATUS "========================================================================")

# ============================================================================
# Set up CMake configuration
# ============================================================================
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Add folder where FindRTIConnextDDS.cmake file is to CMAKE_MODULE_PATH
list(APPEND CMAKE_MODULE_PATH 
    "${CMAKE_CURRENT_SOURCE_DIR}/resources/rticonnextdds-cmake-utils/cmake/Modules"
)

# ============================================================================
# Find RTI Connext DDS
# ============================================================================
find_package(RTIConnextDDS
    "7.3.0"
    REQUIRED
    COMPONENTS
        core
        distributed_logger
)

# ============================================================================
# Build DDS Types Library
# ============================================================================
add_subdirectory(dds)

# ============================================================================
# Build Example Applications
# ============================================================================
add_subdirectory(apps/cxx11/burst_large_data_app)
add_subdirectory(apps/cxx11/command_override)
add_subdirectory(apps/cxx11/dynamic_partition_qos)
add_subdirectory(apps/cxx11/example_io_app)
add_subdirectory(apps/cxx11/fixed_image_flat_zc)
add_subdirectory(apps/cxx11/large_data_app)

# ============================================================================
# Build Summary
# ============================================================================
message(STATUS "========================================================================")
message(STATUS "Connext Starter Kit Build Configuration")
message(STATUS "========================================================================")
message(STATUS "Type Support Library: Built as dds_typesupport library")
message(STATUS "Example Applications:")
message(STATUS "  - burst_large_data_app (publisher & subscriber)")
message(STATUS "  - command_override")
message(STATUS "  - dynamic_partition_qos")
message(STATUS "  - example_io_app")
message(STATUS "  - fixed_image_flat_zc")
message(STATUS "  - large_data_app")
message(STATUS "========================================================================")
