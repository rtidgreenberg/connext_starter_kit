cmake_minimum_required(VERSION 3.12)
project(DDSTypeSupport VERSION 1.0.0 LANGUAGES CXX)

# ============================================================================
# Ensure this is not being built standalone
# ============================================================================
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    message(FATAL_ERROR 
        "The DDS types library cannot be built standalone.\n"
        "Please build from the top-level directory:\n"
        "  cd /home/rti/connext_starter_kit\n"
        "  mkdir -p build && cd build\n"
        "  cmake .. -DCONNEXTDDS_ARCH=x64Linux4gcc7.3.0\n"
        "  cmake --build ."
    )
endif()

# ============================================================================
# Configuration Options
# ============================================================================
option(GENERATE_CXX11_TYPES "Generate C++11 type support" ON)
option(GENERATE_PYTHON_TYPES "Generate Python type support" ON)
option(GENERATE_XML_TYPES "Generate XML type representations" ON)
option(GENERATE_DEFINITIONS "Generate DDS Definitions (header-only constants)" ON)
option(BUILD_CXX_TYPES_LIBRARY "Build C++ type support shared library" ON)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ============================================================================
# Setup Paths
# ============================================================================
list(APPEND CMAKE_MODULE_PATH 
    "${CMAKE_CURRENT_SOURCE_DIR}/../resources/rticonnextdds-cmake-utils/cmake/Modules"
)

# Directories
set(IDL_DIR "${CMAKE_CURRENT_SOURCE_DIR}/datamodel/idl")
set(CXX11_OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/cxx11_gen")
set(PYTHON_OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/python_gen")
set(XML_OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/xml_gen")
set(UTILS_CXX_DIR "${CMAKE_CURRENT_SOURCE_DIR}/utils/cxx11")

# Create output directories in build folder
file(MAKE_DIRECTORY ${CXX11_OUTPUT_DIR})
file(MAKE_DIRECTORY ${PYTHON_OUTPUT_DIR})
file(MAKE_DIRECTORY ${XML_OUTPUT_DIR})

# ============================================================================
# Find RTI Connext DDS
# ============================================================================
find_package(RTIConnextDDS "7.3.0" REQUIRED COMPONENTS core)
include(ConnextDdsCodegen)

# ============================================================================
# Discover IDL Files
# ============================================================================
file(GLOB ALL_IDL_FILES "${IDL_DIR}/*.idl")

# Separate Definitions.idl from type support IDL files
set(DEFINITIONS_IDL "${IDL_DIR}/Definitions.idl")
set(TYPE_SUPPORT_IDL_FILES)

foreach(IDL_FILE ${ALL_IDL_FILES})
    get_filename_component(IDL_NAME ${IDL_FILE} NAME)
    if(NOT IDL_NAME STREQUAL "Definitions.idl")
        list(APPEND TYPE_SUPPORT_IDL_FILES ${IDL_FILE})
    endif()
endforeach()

message(STATUS "Found type support IDL files: ${TYPE_SUPPORT_IDL_FILES}")
if(EXISTS ${DEFINITIONS_IDL})
    message(STATUS "Found definitions IDL: ${DEFINITIONS_IDL}")
endif()

# ============================================================================
# Initialize Collections
# ============================================================================
set(ALL_CXX11_SOURCES)
set(ALL_CXX11_HEADERS)
set(ALL_PYTHON_FILES)
set(ALL_XML_FILES)
set(ALL_CODEGEN_TIMESTAMPS)

# ============================================================================
# Generate Type Support for Each IDL File (excluding Definitions)
# ============================================================================
foreach(IDL_FILE ${TYPE_SUPPORT_IDL_FILES})
    get_filename_component(IDL_BASENAME ${IDL_FILE} NAME_WE)
    
    # ------------------------------------------------------------------------
    # C++11 Code Generation
    # ------------------------------------------------------------------------
    if(GENERATE_CXX11_TYPES)
        connextdds_rtiddsgen_run(
            LANG "C++11"
            OUTPUT_DIRECTORY ${CXX11_OUTPUT_DIR}
            IDL_FILE ${IDL_FILE}
            VAR ${IDL_BASENAME}_cxx
        )
        
        list(APPEND ALL_CXX11_SOURCES ${${IDL_BASENAME}_cxx_CXX11_SOURCES})
        list(APPEND ALL_CXX11_HEADERS ${${IDL_BASENAME}_cxx_CXX11_HEADERS})
        
        message(STATUS "Configured C++11 generation for: ${IDL_BASENAME}")
    endif()
    
    # ------------------------------------------------------------------------
    # Python Code Generation
    # ------------------------------------------------------------------------
    if(GENERATE_PYTHON_TYPES)
        connextdds_rtiddsgen_run(
            LANG "Python"
            OUTPUT_DIRECTORY ${PYTHON_OUTPUT_DIR}
            IDL_FILE ${IDL_FILE}
            VAR ${IDL_BASENAME}_py
        )
        
        list(APPEND ALL_PYTHON_FILES ${${IDL_BASENAME}_py_PYTHON_SOURCES})
        
        message(STATUS "Configured Python generation for: ${IDL_BASENAME}")
    endif()
    
    # ------------------------------------------------------------------------
    # XML Conversion (for documentation/debugging)
    # ------------------------------------------------------------------------
    if(GENERATE_XML_TYPES)
        set(XML_OUTPUT "${XML_OUTPUT_DIR}/${IDL_BASENAME}.xml")
        
        add_custom_command(
            OUTPUT ${XML_OUTPUT}
            COMMAND ${RTICODEGEN}
                -language C++11
                -convertToXml
                -d ${XML_OUTPUT_DIR}
                ${IDL_FILE}
            DEPENDS ${IDL_FILE}
            COMMENT "Converting ${IDL_BASENAME}.idl to XML"
        )
        
        list(APPEND ALL_XML_FILES ${XML_OUTPUT})
        message(STATUS "Configured XML generation for: ${IDL_BASENAME}")
    endif()
    
endforeach()

# ============================================================================
# Generate DDS Definitions (Header-Only Constants)
# ============================================================================
if(GENERATE_DEFINITIONS AND EXISTS ${DEFINITIONS_IDL})
    set(DEFINITIONS_BASENAME "Definitions")
    
    # C++11 Header Generation (header-only, no library compilation)
    if(GENERATE_CXX11_TYPES)
        connextdds_rtiddsgen_run(
            LANG "C++11"
            OUTPUT_DIRECTORY ${CXX11_OUTPUT_DIR}
            IDL_FILE ${DEFINITIONS_IDL}
            VAR definitions_cxx
        )
        
        # Create a custom target to ensure C++ Definitions files are generated
        add_custom_target(cxx_definitions ALL
            DEPENDS ${definitions_cxx_CXX11_HEADERS} ${definitions_cxx_CXX11_SOURCES}
            COMMENT "Generating C++ Definitions headers"
        )
        
        message(STATUS "Configured C++11 definitions generation (header-only)")
    endif()
    
    # Python Generation
    if(GENERATE_PYTHON_TYPES)
        connextdds_rtiddsgen_run(
            LANG "Python"
            OUTPUT_DIRECTORY ${PYTHON_OUTPUT_DIR}
            IDL_FILE ${DEFINITIONS_IDL}
            VAR definitions_python
        )
        list(APPEND ALL_PYTHON_FILES ${definitions_python_PYTHON_SOURCES})
        message(STATUS "Configured Python definitions generation")
    endif()
    
    # XML Generation
    if(GENERATE_XML_TYPES)
        set(DEFINITIONS_XML_OUTPUT "${XML_OUTPUT_DIR}/${DEFINITIONS_BASENAME}.xml")
        add_custom_command(
            OUTPUT ${DEFINITIONS_XML_OUTPUT}
            COMMAND ${RTICODEGEN}
                -language C++11
                -convertToXml
                -d ${XML_OUTPUT_DIR}
                ${DEFINITIONS_IDL}
            DEPENDS ${DEFINITIONS_IDL}
            COMMENT "Converting ${DEFINITIONS_BASENAME}.idl to XML"
        )
        list(APPEND ALL_XML_FILES ${DEFINITIONS_XML_OUTPUT})
        message(STATUS "Configured XML definitions generation")
    endif()
endif()

# ============================================================================
# Create Custom Targets
# ============================================================================

# Python codegen target
if(GENERATE_PYTHON_TYPES)
    add_custom_target(python_typesupport ALL
        DEPENDS ${ALL_PYTHON_FILES}
        COMMENT "Generating Python type support"
    )
    
    # Create Python package __init__.py
    file(WRITE "${PYTHON_OUTPUT_DIR}/__init__.py" 
        "# RTI Connext DDS Python Type Support\n"
        "# Auto-generated from IDL files\n"
    )
endif()

# XML conversion target
if(GENERATE_XML_TYPES)
    add_custom_target(xml_conversion ALL
        DEPENDS ${ALL_XML_FILES}
        COMMENT "Converting IDL to XML"
    )
endif()

# ============================================================================
# Build C++ Shared Library
# ============================================================================
if(BUILD_CXX_TYPES_LIBRARY AND GENERATE_CXX11_TYPES)
    
    add_library(dds_typesupport SHARED ${ALL_CXX11_SOURCES})
    
    # Set library properties
    set_target_properties(dds_typesupport PROPERTIES
        VERSION ${PROJECT_VERSION}
        SOVERSION 1
        OUTPUT_NAME "dds_typesupport"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/lib"
        ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/lib"
    )
    
    # Include directories
    target_include_directories(dds_typesupport 
        PUBLIC
            $<BUILD_INTERFACE:${CXX11_OUTPUT_DIR}>
            $<BUILD_INTERFACE:${UTILS_CXX_DIR}>
            $<INSTALL_INTERFACE:include>
    )
    
    # Link RTI Connext DDS
    target_link_libraries(dds_typesupport
        PUBLIC RTIConnextDDS::cpp2_api
    )
    
    # Compiler settings
    if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
        target_compile_options(dds_typesupport PRIVATE
            -Wall -Wextra -Wno-unused-parameter
        )
    endif()
    
    # Platform-specific definitions
    if(UNIX)
        target_compile_definitions(dds_typesupport PRIVATE
            RTI_UNIX RTI_LINUX RTI_64BIT
        )
    endif()
    
    message(STATUS "Configured C++ shared library: dds_typesupport")
    
endif()

# ============================================================================
# Summary
# ============================================================================
message(STATUS "")
message(STATUS "=== DDS Type Support Configuration ===")
message(STATUS "Generate C++11 Types:    ${GENERATE_CXX11_TYPES}")
message(STATUS "Generate Python Types:   ${GENERATE_PYTHON_TYPES}")
message(STATUS "Generate XML Types:      ${GENERATE_XML_TYPES}")
message(STATUS "Generate Definitions:    ${GENERATE_DEFINITIONS}")
message(STATUS "Build C++ Library:       ${BUILD_CXX_TYPES_LIBRARY}")
message(STATUS "IDL Source Dir:          ${IDL_DIR}")
if(GENERATE_CXX11_TYPES)
    message(STATUS "C++ Output Dir:          ${CXX11_OUTPUT_DIR}")
    message(STATUS "C++ Utils Dir:           ${UTILS_CXX_DIR} (header-only)")
endif()
if(GENERATE_PYTHON_TYPES)
    message(STATUS "Python Output Dir:       ${PYTHON_OUTPUT_DIR}")
endif()
if(GENERATE_XML_TYPES)
    message(STATUS "XML Output Dir:          ${XML_OUTPUT_DIR}")
endif()
message(STATUS "Type Support IDL Files:  ${TYPE_SUPPORT_IDL_FILES}")
if(GENERATE_DEFINITIONS AND EXISTS ${DEFINITIONS_IDL})
    message(STATUS "Definitions IDL:         ${DEFINITIONS_IDL} (header-only)")
endif()
message(STATUS "======================================")
message(STATUS "")
