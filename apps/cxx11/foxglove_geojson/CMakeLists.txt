cmake_minimum_required(VERSION 3.12)

project(ExampleIOApplication VERSION 1.0.0 LANGUAGES CXX)

# ============================================================================
# Ensure this is not being built standalone
# ============================================================================
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    message(FATAL_ERROR 
        "The foxglove_geojson cannot be built standalone.\n"
        "Please build from the top-level directory:\n"
        "  cd <path-to-connext_starter_kit>\n"
        "  mkdir -p build && cd build\n"
        "  cmake .. -DCONNEXTDDS_ARCH=x64Linux4gcc7.3.0\n"
        "  cmake --build ."
    )
endif()

# Set standard
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Add the RTI CMake utilities to the module path
list(APPEND CMAKE_MODULE_PATH 
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../resources/rticonnextdds-cmake-utils/cmake/Modules"
)

# Find RTI Connext DDS
find_package(RTIConnextDDS
    "7.3.0"
    REQUIRED
    COMPONENTS
        core
        distributed_logger
)

# Set up directories - use CMAKE_BINARY_DIR for build outputs
set(DDS_BUILD_DIR "${CMAKE_BINARY_DIR}/dds")
set(DDS_LIB_BUILD_DIR "${DDS_BUILD_DIR}/lib")
set(DDS_CODEGEN_DIR "${DDS_BUILD_DIR}/cxx11_gen")
set(DDS_UTILS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../dds/utils/cxx11")

# Create the executable
add_executable(foxglove_geojson
    foxglove_geojson.cxx
    application.hpp
)

# Include directories
target_include_directories(foxglove_geojson 
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${DDS_CODEGEN_DIR}
        ${DDS_UTILS_DIR}
        ${RTIConnextDDS_INCLUDE_DIRS}
)

# Link with libraries - use dds_typesupport target directly
target_link_libraries(foxglove_geojson
    PRIVATE
        dds_typesupport
        RTIConnextDDS::cpp2_api
        RTIConnextDDS::distributed_logger_cpp2
        RTIConnextDDS::metp  # Required for ZeroCopy types used by other apps in library
        dl
        m
        pthread
        rt
)

# Set compiler definitions
target_compile_definitions(foxglove_geojson
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set additional compiler flags
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(foxglove_geojson PRIVATE
        -m64
        -Wall
        -Wextra
        -Wno-unused-parameter
        -no-pie
        -rdynamic
    )
endif()

# Print information
message(STATUS "DDS shared library: dds_typesupport (CMake target)")
message(STATUS "DDS codegen headers: ${DDS_CODEGEN_DIR}")
message(STATUS "DDS utils headers: ${DDS_UTILS_DIR}")

# Set the runtime path to find the shared library
set_target_properties(foxglove_geojson PROPERTIES
    INSTALL_RPATH "${DDS_LIB_BUILD_DIR}"
    BUILD_WITH_INSTALL_RPATH TRUE
)

# Install the executable if desired
install(TARGETS foxglove_geojson
    RUNTIME DESTINATION bin
)