cmake_minimum_required(VERSION 3.12)

project(LargeDataApplication VERSION 1.0.0 LANGUAGES CXX)

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

# Create the executables
add_executable(burst_publisher
    burst_publisher.cxx
    application.hpp
)

add_executable(burst_subscriber
    burst_subscriber.cxx
    application.hpp
)

# Include directories for burst_publisher
target_include_directories(burst_publisher 
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${DDS_CODEGEN_DIR}
        ${DDS_UTILS_DIR}
        ${RTIConnextDDS_INCLUDE_DIRS}
)

# Include directories for burst_subscriber
target_include_directories(burst_subscriber 
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${DDS_CODEGEN_DIR}
        ${DDS_UTILS_DIR}
        ${RTIConnextDDS_INCLUDE_DIRS}
)

# Link with libraries for burst_publisher
target_link_libraries(burst_publisher
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

# Link with libraries for burst_subscriber
target_link_libraries(burst_subscriber
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

# Set compiler definitions for burst_publisher
target_compile_definitions(burst_publisher
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set compiler definitions for burst_subscriber
target_compile_definitions(burst_subscriber
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set additional compiler flags for burst_publisher
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(burst_publisher PRIVATE
        -m64
        -Wall
        -Wextra
        -Wno-unused-parameter
        -no-pie
        -rdynamic
    )
endif()

# Set additional compiler flags for burst_subscriber
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(burst_subscriber PRIVATE
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
set_target_properties(burst_publisher PROPERTIES
    INSTALL_RPATH "${DDS_LIB_BUILD_DIR}"
    BUILD_WITH_INSTALL_RPATH TRUE
)

set_target_properties(burst_subscriber PROPERTIES
    INSTALL_RPATH "${DDS_LIB_BUILD_DIR}"
    BUILD_WITH_INSTALL_RPATH TRUE
)

# Install the executables if desired
install(TARGETS burst_publisher burst_subscriber
    RUNTIME DESTINATION bin
)
