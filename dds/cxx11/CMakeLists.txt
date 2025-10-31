cmake_minimum_required(VERSION 3.12)

project(DataModelLibrary VERSION 1.0.0 LANGUAGES CXX)

# Set standard
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Add the RTI CMake utilities to the module path
list(APPEND CMAKE_MODULE_PATH 
    "${CMAKE_CURRENT_SOURCE_DIR}/../../resources/rticonnextdds-cmake-utils/cmake/Modules"
)

# This will look for the ConnextDDS core and API libraries
find_package(RTIConnextDDS
    "7.3.0"
    REQUIRED
    COMPONENTS
        core
)

# Include RTI CodeGen utilities
include(ConnextDdsCodegen)

# Set up directories
set(IDL_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../datamodel")
set(CODEGEN_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src/codegen")
set(UTILS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/src/utils")
set(BUILD_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/build")

# Create output directories
file(MAKE_DIRECTORY ${CODEGEN_OUTPUT_DIR})
file(MAKE_DIRECTORY ${BUILD_OUTPUT_DIR})
file(MAKE_DIRECTORY ${BUILD_OUTPUT_DIR}/lib)

# Automatically find all IDL files in the datamodel directory
file(GLOB IDL_FILES "${IDL_DIR}/*.idl")

# Generate code for each IDL file
set(ALL_GENERATED_SOURCES)
set(ALL_GENERATED_HEADERS)

foreach(IDL_FILE ${IDL_FILES})
    get_filename_component(IDL_BASENAME ${IDL_FILE} NAME_WE)
    
    # Generate C++11 code from IDL
    connextdds_rtiddsgen_run(
        LANG "C++11"
        OUTPUT_DIRECTORY ${CODEGEN_OUTPUT_DIR}
        IDL_FILE ${IDL_FILE}
        VAR ${IDL_BASENAME}
    )
    
    # Add generated sources and headers to our lists
    list(APPEND ALL_GENERATED_SOURCES ${${IDL_BASENAME}_CXX11_SOURCES})
    list(APPEND ALL_GENERATED_HEADERS ${${IDL_BASENAME}_CXX11_HEADERS})
endforeach()

# Create the shared library
add_library(dds_utils_datamodel SHARED
    ${ALL_GENERATED_SOURCES}
)

# Set the output directory for the library
set_target_properties(dds_utils_datamodel PROPERTIES
    OUTPUT_NAME "dds_utils_datamodel"
    LIBRARY_OUTPUT_DIRECTORY ${BUILD_OUTPUT_DIR}/lib
    ARCHIVE_OUTPUT_DIRECTORY ${BUILD_OUTPUT_DIR}/lib
    RUNTIME_OUTPUT_DIRECTORY ${BUILD_OUTPUT_DIR}/lib
)

# Include directories
target_include_directories(dds_utils_datamodel 
    PUBLIC
        ${CODEGEN_OUTPUT_DIR}
        ${UTILS_DIR}
)

# Since utils are header-only templates, make sure they're accessible
# We don't need to add them to sources, but we install them with the library

# Link with RTI Connext DDS libraries
target_link_libraries(dds_utils_datamodel
    PUBLIC
        RTIConnextDDS::cpp2_api
)

# Set compiler definitions if needed
target_compile_definitions(dds_utils_datamodel
    PRIVATE
        RTI_UNIX
        RTI_LINUX
        RTI_64BIT
)

# Set additional compiler flags for RTI Connext DDS
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(dds_utils_datamodel PRIVATE
        -m64
        -Wall
        -Wextra
        -Wno-unused-parameter
    )
endif()

# Print information about generated files (for debugging)
message(STATUS "Generated sources: ${ALL_GENERATED_SOURCES}")
message(STATUS "Generated headers: ${ALL_GENERATED_HEADERS}")
message(STATUS "Library will be built to: ${BUILD_OUTPUT_DIR}/lib")
message(STATUS "Utils directory included: ${UTILS_DIR}")

# Make the library depend on the generated files
# The library will automatically depend on the generated sources since they're included in the target

# Install targets (optional)
install(TARGETS dds_utils_datamodel
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
    RUNTIME DESTINATION bin
)

install(FILES ${ALL_GENERATED_HEADERS}
    DESTINATION include/dds
)

# Install utils headers
file(GLOB UTILS_HEADERS "${UTILS_DIR}/*.hpp" "${UTILS_DIR}/*.h")
install(FILES ${UTILS_HEADERS}
    DESTINATION include/dds/utils
)