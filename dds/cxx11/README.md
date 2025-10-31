# C++11 DDS Shared Library

This directory contains the CMake configuration for generating C++11 code and building a shared library from IDL files using RTI Connext DDS.

## Overview

The CMakeLists.txt in this directory automatically discovers and generates C++11 code from **all IDL files** located in `../datamodel/` using the RTI Code Generator (rtiddsgen). The generated code is compiled into a shared library (`libdds_utils_datamodel.so`) that can be used by C++11 applications.

## Generated Files

The following C++11 files are generated in the `src/codegen/` directory:

- **PointCloud.cxx/.hpp**: C++11 implementation for sensor_msgs::PointCloudWithNormals message type
- **PointCloudPlugin.cxx/.hpp**: RTI DDS type plugin for PointCloud
- **Pose.cxx/.hpp**: C++11 implementation for geometry_msgs::Pose message type  
- **PosePlugin.cxx/.hpp**: RTI DDS type plugin for Pose
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
# Set RTI environment (adjust path to your RTI installation)
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Build the shared DDS library
mkdir -p dds/cxx11/build
cd dds/cxx11/build
cmake ..
make
```

### Build Output

```
dds/cxx11/
├── CMakeLists.txt              # This build configuration
├── src/
│   ├── codegen/                # Generated C++11 files
│   │   ├── PointCloud.cxx/.hpp # PointCloud message implementation
│   │   ├── PointCloudPlugin.cxx/.hpp # PointCloud DDS plugin
│   │   ├── Pose.cxx/.hpp       # Pose message implementation
│   │   ├── PosePlugin.cxx/.hpp # Pose DDS plugin
│   │   ├── DDSDefs.cxx/.hpp   # Topic names and QoS constants
│   │   └── DDSDefsPlugin.cxx/.hpp # DDSDefs DDS plugin
│   └── utils/                  # Header-only template utilities
│       ├── DDSContext.hpp     # DDSContext resource manager
│       └── DDSInterface.hpp   # DDSInterface<T> template
└── build/                      # CMake build artifacts
    └── lib/                    # Shared library output
        └── libdds_utils_datamodel.so # Final shared library
```

## Integration with Applications

The generated shared library is used by C++11 applications in the `../../apps/cxx11_app/` directory. Applications link against this library and include the generated headers to work with DDS message types.

### Library Features

- **Type Safety**: Generated C++11 classes with compile-time type checking
- **Plugin Integration**: RTI DDS type plugins for serialization/deserialization
- **Header-Only Utils**: Template-based DDSContext and DDSInterface utilities
- **RPATH Configuration**: Proper runtime library path handling

## Automatic Discovery and Regeneration

The CMake configuration provides several automation features:

### **Automatic IDL Discovery**
- Uses `file(GLOB)` to automatically find all `*.idl` files in `../datamodel/`
- No manual configuration needed when adding new IDL files
- Simply add a new `.idl` file to the datamodel directory and rebuild


## Library Usage

Applications can link against the shared library and use the generated types:

```cpp
#include "PointCloud.hpp"
#include "Pose.hpp"
#include "DDSDefs.hpp"
#include "DDSContext.hpp"
#include "DDSInterface.hpp"

// Use generated message types
sensor_msgs::PointCloudWithNormals pointcloud;
geometry_msgs::Pose pose;

// Use generated topic constants
std::string topic_name = topics::POINTCLOUD_NORMALS_TOPIC;

// Use utility templates
auto dds_context = std::make_shared<DDSContext>(domain_id);
auto interface = std::make_shared<DDSInterface<sensor_msgs::PointCloudWithNormals>>(
    dds_context, INTERFACE_KIND::READER, topic_name);
```