cmake_minimum_required(VERSION 3.12)

project(CommandControlApplication VERSION 1.0.0 LANGUAGES CXX)

# ============================================================================
# Ensure this is not being built standalone
# ============================================================================
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    message(FATAL_ERROR 
        "The command_override app cannot be built standalone.\n"
        "Please build from the top-level directory:\n"
        "  cd /home/rti/connext_starter_kit\n"
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

# Set up directories
set(DDS_BUILD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../dds/build")
set(DDS_LIB_BUILD_DIR "${DDS_BUILD_DIR}/lib")
set(DDS_CODEGEN_DIR "${DDS_BUILD_DIR}/cxx11_gen")
set(DDS_UTILS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../dds/utils/cxx11")

# Find the shared libraries
find_library(DDS_TYPESUPPORT_LIB 
    NAMES dds_typesupport
    PATHS ${DDS_LIB_BUILD_DIR}
    NO_DEFAULT_PATH
    REQUIRED
)

# Create the executable
add_executable(command_override
    command_override.cxx
    application.hpp
)

# Include directories
target_include_directories(command_override 
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${DDS_CODEGEN_DIR}
        ${DDS_UTILS_DIR}
        ${RTIConnextDDS_INCLUDE_DIRS}
)

# Link with libraries
target_link_libraries(command_override
    PRIVATE
        ${DDS_TYPESUPPORT_LIB}
        RTIConnextDDS::cpp2_api
        RTIConnextDDS::distributed_logger_cpp2
        RTIConnextDDS::metp  # Required for ZeroCopy types used by other apps in library
        dl
        m
        pthread
        rt
)

# Set compiler definitions
target_compile_definitions(command_override
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set additional compiler flags
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(command_override PRIVATE
        -m64
        -Wall
        -Wextra
        -Wno-unused-parameter
        -no-pie
        -rdynamic
    )
endif()

# Print information
message(STATUS "DDS shared library: ${DDS_TYPESUPPORT_LIB}")
message(STATUS "DDS codegen headers: ${DDS_CODEGEN_DIR}")
message(STATUS "DDS utils headers: ${DDS_UTILS_DIR}")

# Set the runtime path to find the shared library
set_target_properties(command_override PROPERTIES
    INSTALL_RPATH "${DDS_LIB_BUILD_DIR}"
    BUILD_WITH_INSTALL_RPATH TRUE
)

# Install the executable if desired
install(TARGETS command_override
    RUNTIME DESTINATION bin
)