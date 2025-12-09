# Unified DDS Type Support Generation

This directory contains a unified CMake build system that generates type support for multiple languages from a single configuration.

## Quick Start

```bash
# Build everything (C++, Python, XML)
cd dds
mkdir -p build && cd build
cmake ..
make -j4
```

## Generated Output Structure

```
dds/
├── CMakeLists.txt           # Main unified build file
├── datamodel/               # Data model definitions & generated code
│   ├── idl/                # Source IDL files
│   │   ├── ExampleTypes.idl
│   │   ├── Definitions.idl
│   │   └── *.idl
│   ├── cxx11_gen/          # C++ generated type support
│   ├── python_gen/         # Python generated type support
│   └── xml_gen/            # XML representations
├── utils/                   # Reusable utility code
│   └── cxx11/              # C++ utility classes (header-only)
├── qos/                     # QoS profiles
└── build/                   # Build artifacts
    └── lib/                # Shared libraries
```

## Build Options

Configure generation using CMake options:

| Option | Default | Description |
|--------|---------|-------------|
| `GENERATE_CXX11_TYPES` | ON | Generate C++11 type support code |
| `GENERATE_PYTHON_TYPES` | ON | Generate Python type support code |
| `GENERATE_XML_TYPES` | **ON** | Generate XML type representations (enabled by default) |
| `GENERATE_DEFINITIONS` | **ON** | Generate DDS Definitions (header-only constants for topics/QoS) |
| `BUILD_CXX_TYPES_LIBRARY` | ON | Build C++ type support shared library |

**Notes**: 
- C++ utility classes (`DDSContextSetup`, `DDSReaderSetup`, `DDSWriterSetup`) are header-only and always available.
- `Definitions.idl` contains only constants (topics, QoS names) and generates header-only code, not compiled into the library.

### Examples

**Build everything (default):**
```bash
cmake ..
make -j4
```

**Disable XML generation:**
```bash
cmake -DGENERATE_XML_TYPES=OFF ..
make -j4
```

**Python only (no C++ library):**
```bash
cmake -DGENERATE_CXX11_TYPES=OFF -DBUILD_CXX_TYPES_LIBRARY=OFF ..
make -j4
```

**C++ only with XML documentation:**
```bash
cmake -DGENERATE_PYTHON_TYPES=OFF -DGENERATE_XML_TYPES=ON ..
make -j4
```

## Build Targets

| Target | Description |
|--------|-------------|
| `all` | Build all configured targets |
| `dds_typesupport` | C++ type support shared library (if enabled) |
| `python_typesupport` | Python code generation (if enabled) |
| `xml_conversion` | XML generation (if enabled) |

## Output Artifacts

### C++ Type Support
- **Type Support Library**: `build/lib/libdds_typesupport.so` (shared library)
- **Generated Type Headers**: `datamodel/cxx11_gen/*.hpp`
- **Utility Headers**: `utils/cxx11/*.hpp` (header-only, always available)

### Python Package
- **Module**: `datamodel/python_gen/*.py`
- **Package**: `datamodel/python_gen/__init__.py`

### XML Documentation
- **XML files**: `datamodel/xml_gen/*.xml`

## Using Generated Code

### C++ Applications

C++ applications now link against the new unified build libraries:

```cmake
# In your application's CMakeLists.txt
set(DDS_BUILD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../dds/build")
set(DDS_LIB_BUILD_DIR "${DDS_BUILD_DIR}/lib")

find_library(DDS_TYPESUPPORT_LIB 
    NAMES dds_typesupport
    PATHS ${DDS_LIB_BUILD_DIR}
    NO_DEFAULT_PATH
    REQUIRED
)

target_link_libraries(my_app PRIVATE ${DDS_TYPESUPPORT_LIB})
```

Or include generated code directly:
```cmake
target_include_directories(my_app PRIVATE
    ${CMAKE_SOURCE_DIR}/../dds/datamodel/cxx11_gen
    ${CMAKE_SOURCE_DIR}/../dds/utils/cxx11
)
```

### Python Applications

Add generated code to Python path:

```python
import sys
sys.path.insert(0, '/path/to/dds/datamodel')

from python_gen import ExampleTypes
from python_gen import Definitions
from python_gen.Definitions import topics, qos_profiles, domains
```

## XML Files

XML files in `datamodel/xml_gen/` provide:
- **Documentation**: Human-readable type definitions
- **Debugging**: Inspect type structure and annotations
- **Integration**: Use with tools that accept XML type definitions
- **Validation**: Verify IDL conversion correctness

### Viewing XML

```bash
# View generated XML for a type
cat xml/codegen/ExampleTypes.xml

# Pretty print with xmllint
xmllint --format xml/codegen/ExampleTypes.xml
```

## Migration from Legacy Build

The legacy separate builds (`cxx11/CMakeLists.txt`, `python/CMakeLists.txt`) still exist but the unified build is now the recommended approach. Both use the same output directories.

### Key Benefits of Unified Build

| Aspect | Legacy Build | Unified Build |
|--------|-------------|---------------|
| Build Commands | 2 separate builds | 1 single build |
| Output Locations | Same directories | Same directories |
| XML Support | ❌ Not available | ✅ Available (default ON) |
| Configuration | Separate configs | One unified config |

### Migration

Simply use the top-level build instead of individual builds:

**Before:**
```bash
cd dds/cxx11/build && cmake .. && make
cd dds/python/build && cmake .. && make
```

**After:**
```bash
cd dds/build && cmake .. && make -j4
```

## Troubleshooting

**CMake can't find RTI Connext DDS:**
```bash
export NDDSHOME=/path/to/rti_connext_dds-7.3.0
```

**Git submodule missing:**
```bash
git submodule update --init --recursive
```

**Regenerate all code:**
```bash
rm -rf build cxx11/src/codegen/* python/codegen/* xml/codegen/*
mkdir build && cd build
cmake .. && make -j4
```

**Check what will be generated:**
```bash
cd build
cmake .. 2>&1 | grep "Configured.*generation"
```

## Benefits

✅ **Single source of truth** - One CMakeLists.txt for all languages  
✅ **XML by default** - Automatic documentation generation  
✅ **Proper dependencies** - CMake tracks when to regenerate  
✅ **Flexible configuration** - Enable/disable languages as needed  
✅ **Clean organization** - All generated code in one place  
✅ **Easy maintenance** - Update once, applies to all languages  

## See Also

- [DDS Layer Documentation](README.md) - Overall DDS layer overview
- [ARCHITECTURE.md](../ARCHITECTURE.md) - System architecture details
- [C++ Applications](../apps/cxx11/README.md) - Using generated C++ code
- [Python Applications](../apps/python/README.md) - Using generated Python code
