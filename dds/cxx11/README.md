# C++11 DDS Shared Library

CMake configuration for generating C++11 code from IDL files using RTI Connext DDS and building a shared library.

## Overview

The CMakeLists.txt automatically discovers and generates C++11 code from **all IDL files** in `../datamodel/` using rtiddsgen. Generated code is compiled into a shared library (`libdds_utils_datamodel.so`) for use by C++11 applications.

## Generated Files

C++11 files generated in `src/codegen/`:

- **ExampleTypes.cxx/.hpp**: C++11 implementation for Command, Button, Config, Position, State, Image types
- **ExampleTypesPlugin.cxx/.hpp**: RTI DDS type plugins for ExampleTypes
- **FinalFlatImage.cxx/.hpp**: FlatData zero-copy type for high-performance large data
- **FinalFlatImagePlugin.cxx/.hpp**: RTI DDS type plugin for FinalFlatImage
- **DDSDefs.cxx/.hpp**: C++11 constants for topic names and QoS configuration
- **DDSDefsPlugin.cxx/.hpp**: RTI DDS type plugin for DDSDefs

## Building

### Prerequisites

- **RTI Connext DDS 7.3.0** with NDDSHOME environment variable set
- **CMake 3.12+** 
- **C++14** compatible compiler (GCC 7.3.0+ recommended)

**⚠️ Important**: If you cloned this repository, ensure you have the git submodules by cloning with `--recurse-submodules` or running:
```bash
git submodule update --init --recursive
```

### Build Process

```bash
# Set RTI environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Build shared DDS library
cd dds/cxx11 && mkdir -p build && cd build
cmake .. && make -j4
```

### Build Output

```
dds/cxx11/
├── src/
│   ├── codegen/                # Generated C++11 files
│   │   ├── ExampleTypes.cxx/.hpp
│   │   ├── ExampleTypesPlugin.cxx/.hpp
│   │   ├── FinalFlatImage.cxx/.hpp
│   │   ├── FinalFlatImagePlugin.cxx/.hpp
│   │   ├── DDSDefs.cxx/.hpp
│   │   └── DDSDefsPlugin.cxx/.hpp
│   └── utils/                  # Header-only template utilities
│       ├── DDSContext.hpp
│       ├── DDSReaderSetup.hpp
│       └── DDSWriterSetup.hpp
└── build/
    └── lib/
        └── libdds_utils_datamodel.so
```

## Integration with Applications

Generated shared library is used by C++11 applications in `../../apps/cxx11/`. Applications link against this library and include generated headers.

### Library Features

- **Type Safety**: Generated C++11 classes with compile-time type checking
- **Plugin Integration**: RTI DDS type plugins for serialization/deserialization
- **Header-Only Utils**: Template-based DDSContext, DDSReaderSetup, DDSWriterSetup utilities
- **RPATH Configuration**: Proper runtime library path handling

## Automatic Discovery

CMake automatically finds all `*.idl` files in `../datamodel/` using `file(GLOB)`. No manual configuration needed when adding new IDL files.

## Library Usage

```cpp
#include "ExampleTypes.hpp"
#include "FinalFlatImage.hpp"
#include "DDSDefs.hpp"
#include "DDSContext.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"

// Use generated types
example_types::Command cmd;
example_types::Position pos;
```