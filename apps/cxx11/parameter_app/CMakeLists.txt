cmake_minimum_required(VERSION 3.12)

project(ParameterApplication VERSION 1.0.0 LANGUAGES CXX)

# ============================================================================
# Ensure this is not being built standalone
# ============================================================================
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    message(FATAL_ERROR 
        "The parameter_app cannot be built standalone.\n"
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
        messaging_api
)

# ============================================================================
# Find yaml-cpp (with automatic fallback to FetchContent)
# ============================================================================
# Try system installation first via pkg-config
find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
    pkg_check_modules(YAML_CPP QUIET yaml-cpp)
endif()

# If not found, try find_package (for CMake-installed yaml-cpp)
if(NOT YAML_CPP_FOUND)
    find_package(yaml-cpp QUIET CONFIG)
    if(yaml-cpp_FOUND)
        set(YAML_CPP_FOUND TRUE)
        set(YAML_CPP_LIBRARIES yaml-cpp::yaml-cpp)
        message(STATUS "Found yaml-cpp via CMake config")
    endif()
endif()

# If still not found, use FetchContent to download and build
if(NOT YAML_CPP_FOUND)
    message(STATUS "yaml-cpp not found on system, fetching from GitHub...")
    include(FetchContent)
    
    FetchContent_Declare(
        yaml-cpp
        GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
        GIT_TAG 0.8.0
        GIT_SHALLOW TRUE
    )
    
    # Configure yaml-cpp build options
    set(YAML_CPP_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_BUILD_CONTRIB OFF CACHE BOOL "" FORCE)
    set(YAML_CPP_INSTALL OFF CACHE BOOL "" FORCE)
    
    FetchContent_MakeAvailable(yaml-cpp)
    
    set(YAML_CPP_LIBRARIES yaml-cpp::yaml-cpp)
    set(YAML_CPP_INCLUDE_DIRS "")  # Handled by target
    message(STATUS "yaml-cpp fetched and will be built from source")
else()
    message(STATUS "Found yaml-cpp: ${YAML_CPP_LIBRARIES}")
endif()

# Set up directories - use CMAKE_BINARY_DIR for build outputs
set(DDS_BUILD_DIR "${CMAKE_BINARY_DIR}/dds")
set(DDS_LIB_BUILD_DIR "${DDS_BUILD_DIR}/lib")
set(DDS_CODEGEN_DIR "${DDS_BUILD_DIR}/cxx11_gen")
set(DDS_UTILS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../dds/utils/cxx11")

# Create the executable
add_executable(parameter_app
    parameter_app.cxx
    application.hpp
)

# Include directories
target_include_directories(parameter_app 
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${DDS_CODEGEN_DIR}
        ${DDS_UTILS_DIR}
        ${RTIConnextDDS_INCLUDE_DIRS}
        ${YAML_CPP_INCLUDE_DIRS}
)

# Link with libraries - use dds_typesupport target directly
target_link_libraries(parameter_app
    PRIVATE
        dds_typesupport
        RTIConnextDDS::cpp2_api
        RTIConnextDDS::distributed_logger_cpp2
        RTIConnextDDS::messaging_cpp2_api
        RTIConnextDDS::metp
        ${YAML_CPP_LIBRARIES}
        dl
        m
        pthread
        rt
)

# Set compiler definitions
target_compile_definitions(parameter_app
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set additional compiler flags
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(parameter_app PRIVATE
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
message(STATUS "YAML-CPP libraries: ${YAML_CPP_LIBRARIES}")

# Set the runtime path to find the shared library
set_target_properties(parameter_app PROPERTIES
    INSTALL_RPATH "${DDS_LIB_BUILD_DIR}"
    BUILD_WITH_INSTALL_RPATH TRUE
)
