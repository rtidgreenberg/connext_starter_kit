cmake_minimum_required(VERSION 3.12)

project(PythonDataModel VERSION 1.0.0)

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
set(CODEGEN_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/codegen")

# Create output directory
file(MAKE_DIRECTORY ${CODEGEN_OUTPUT_DIR})

# Automatically find all IDL files in the datamodel directory
file(GLOB IDL_FILES "${IDL_DIR}/*.idl")

# Generate Python code for each IDL file
set(ALL_GENERATED_PYTHON_FILES)

foreach(IDL_FILE ${IDL_FILES})
    get_filename_component(IDL_BASENAME ${IDL_FILE} NAME_WE)
    
    # Generate Python code from IDL
    connextdds_rtiddsgen_run(
        LANG "Python"
        OUTPUT_DIRECTORY ${CODEGEN_OUTPUT_DIR}
        IDL_FILE ${IDL_FILE}
        VAR ${IDL_BASENAME}
    )
    
    # Add generated Python files to our list
    list(APPEND ALL_GENERATED_PYTHON_FILES ${${IDL_BASENAME}_PYTHON_SOURCES})
endforeach()

# Create a custom target that depends on all generated files
# This ensures the Python files are generated when building
add_custom_target(python_codegen ALL
    DEPENDS ${ALL_GENERATED_PYTHON_FILES}
    COMMENT "Generating Python code from IDL files"
)

# Print information about generated files (for debugging)
message(STATUS "IDL files: ${IDL_FILES}")
message(STATUS "Python codegen output directory: ${CODEGEN_OUTPUT_DIR}")
message(STATUS "Generated Python files: ${ALL_GENERATED_PYTHON_FILES}")

# Optional: Install Python files to a specific location
install(FILES ${ALL_GENERATED_PYTHON_FILES}
    DESTINATION lib/python/dds
    COMPONENT python
)

# Create __init__.py file to make it a proper Python package
file(WRITE "${CODEGEN_OUTPUT_DIR}/__init__.py" 
"# RTI Connext DDS Python Generated Code
# Generated from IDL files: PointCloud.idl, Pose.idl, DDSDefs.idl

__version__ = '1.0.0'
__all__ = ['PointCloud', 'Pose', 'DDSDefs']
")