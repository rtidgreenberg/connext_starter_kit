cmake_minimum_required(VERSION 3.12)

project(ExampleIOApplication VERSION 1.0.0 LANGUAGES CXX)

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
set(DDS_LIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../dds/cxx11")
set(DDS_LIB_BUILD_DIR "${DDS_LIB_DIR}/build/lib")
set(DDS_CODEGEN_DIR "${DDS_LIB_DIR}/src/codegen")
set(DDS_UTILS_DIR "${DDS_LIB_DIR}/src/utils")

# Find the shared library
find_library(DDS_UTILS_DATAMODEL_LIB 
    NAMES dds_utils_datamodel
    PATHS ${DDS_LIB_BUILD_DIR}
    NO_DEFAULT_PATH
    REQUIRED
)

# Create the executable
add_executable(example_io_app
    example_io_app.cxx
    application.hpp
)

# Include directories
target_include_directories(example_io_app 
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${DDS_CODEGEN_DIR}
        ${DDS_UTILS_DIR}
        ${RTIConnextDDS_INCLUDE_DIRS}
)

# Link with libraries
target_link_libraries(example_io_app
    PRIVATE
        ${DDS_UTILS_DATAMODEL_LIB}
        RTIConnextDDS::cpp2_api
        RTIConnextDDS::distributed_logger_cpp2
        dl
        m
        pthread
        rt
)

# Set compiler definitions
target_compile_definitions(example_io_app
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set additional compiler flags
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(example_io_app PRIVATE
        -m64
        -Wall
        -Wextra
        -Wno-unused-parameter
        -no-pie
        -rdynamic
    )
endif()

# Print information
message(STATUS "DDS shared library: ${DDS_UTILS_DATAMODEL_LIB}")
message(STATUS "DDS codegen headers: ${DDS_CODEGEN_DIR}")
message(STATUS "DDS utils headers: ${DDS_UTILS_DIR}")

# Set the runtime path to find the shared library
set_target_properties(example_io_app PROPERTIES
    INSTALL_RPATH "${DDS_LIB_BUILD_DIR}"
    BUILD_WITH_INSTALL_RPATH TRUE
)

# Install the executable if desired
install(TARGETS example_io_app
    RUNTIME DESTINATION bin
)