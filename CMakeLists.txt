# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
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
        "\n  source /opt/rti.com/rti_connext_dds-7.7.0/resource/scripts/rtisetenv_x64Linux4gcc8.5.0.bash"
        "\nOr set it manually:"
        "\n  export CONNEXTDDS_ARCH=x64Linux4gcc8.5.0"
        "\nOr pass it to cmake:"
        "\n  cmake .. -DCONNEXTDDS_ARCH=x64Linux4gcc8.5.0"
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
set(CONNEXTDDS_VERSION "7.7.0" CACHE STRING "RTI Connext DDS version")
find_package(RTIConnextDDS
    "${CONNEXTDDS_VERSION}"
    REQUIRED
    COMPONENTS
        core
        distributed_logger
)

# ============================================================================
# Build DDS Types Library
# ============================================================================
add_subdirectory(dds)

if(NOT GENERATE_CXX11_TYPES OR NOT GENERATE_DEFINITIONS OR NOT BUILD_CXX_TYPES_LIBRARY)
    message(FATAL_ERROR
        "C++ applications require GENERATE_CXX11_TYPES, GENERATE_DEFINITIONS, "
        "and BUILD_CXX_TYPES_LIBRARY to be ON."
    )
endif()

# ============================================================================
# Build Example Applications
# ============================================================================
add_subdirectory(apps/cxx11/burst_large_data_app)
add_subdirectory(apps/cxx11/command_override)
add_subdirectory(apps/cxx11/dynamic_partition_qos)
add_subdirectory(apps/cxx11/example_io_app)
add_subdirectory(apps/cxx11/fixed_image_flat_zc)
add_subdirectory(apps/cxx11/incompatible_qos_listener)
add_subdirectory(apps/cxx11/large_data_app)
add_subdirectory(apps/cxx11/parameter_app)
add_subdirectory(apps/cxx11/foxglove_geojson)
add_subdirectory(apps/cxx11/foxglove_rawimage)
add_subdirectory(apps/cxx11/foxglove_gstreamvideo_app)
add_subdirectory(apps/cxx11/foxglove_pointcloud)

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
message(STATUS "  - incompatible_qos_listener")
message(STATUS "  - foxglove_geojson")
message(STATUS "  - foxglove_gstreamvideo_app")
message(STATUS "  - foxglove_pointcloud")
message(STATUS "  - foxglove_rawimage")
message(STATUS "  - large_data_app")
message(STATUS "  - parameter_app")
message(STATUS "========================================================================")
