# Connext Autonomy Templates

Cross-language DDS system/application templates to accelerate development.

## Prerequisites

- **RTI Connext DDS 7.3.0+** installed and licensed
- **C++14 compiler** (GCC 7.3.0+ or equivalent) for C++ apps
- **Python 3.8+** with virtual environment support for Python apps
- **CMake 3.12+** for build configuration
- **Git submodules**: Clone with `--recurse-submodules` or run `git submodule update --init --recursive`

## Quick Start

1. **Set RTI environment:**
   ```bash
   export NDDSHOME=/path/to/rti_connext_dds-7.3.0
   ```

2. **Clone with submodules:**
   ```bash
   git clone --recurse-submodules <repository-url>
   cd connext_starter_kit
   ```

3. **Configure your target environment:**
   Source the helper script for your target architecture:
   ```bash
   source $NDDSHOME/resource/scripts/rtisetenv_<target>.bash
   ```
   
   Examples:
   ```bash
   source $NDDSHOME/resource/scripts/rtisetenv_x64Linux4gcc7.3.0.bash
   source $NDDSHOME/resource/scripts/rtisetenv_x64Win64VS2019.bash
   source $NDDSHOME/resource/scripts/rtisetenv_x64Darwin20clang12.0.0.bash
   ```

4. **Build the project:**
   ```bash
   mkdir -p build && cd build
   cmake ..
   cmake --build .
   ```

5. **For Python apps - set the license file location:**
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```
   
   Get a free trial license at https://www.rti.com/get-connext

## Table of Contents - What Do You Want to Do?

### 🚀 Getting Started
- [I want to generate DDS applications using GitHub Copilot](apps/cxx11/README.md#creating-new-c-dds-applications)
- [I want to learn basic DDS patterns with example apps](apps/cxx11/example_io_app/README.md)
- [I want to understand the system architecture](ARCHITECTURE.md)

### 🎯 Advanced DDS Patterns
- [I want to implement priority-based message control](apps/cxx11/command_override/README.md)
- [I want to transfer large data efficiently with shared memory](apps/cxx11/large_data_app/README.md)
- [I want maximum performance with zero-copy transfer](apps/cxx11/fixed_image_flat_zc/README.md)
- [I want to downsample high-frequency data for GUIs](apps/python/downsampled_reader/README.md)
- [I want to isolate test environments with partitions](apps/cxx11/dynamic_partition_qos/README.md)

### 📊 Data Recording and Analysis
- [I want to record DDS topics for debugging](services/README.md#i-want-to-record-a-selective-group-of-topics)
- [I want to convert recorded data to JSON/CSV](services/README.md#i-want-to-convert-my-recorded-data-to-json-for-post-processing)
- [I want to replay recorded data](services/README.md#i-want-to-replay-my-recorded-data)

### 🔧 Development Tools
- [I want to monitor DDS topics in real-time](tools/README.md)
- [I want to use distributed logging](tools/README.md)

## Documentation

### Core Documentation
- **[System Architecture](ARCHITECTURE.md)** - Technical implementation details and patterns
- **[DDS Layer](dds/README.md)** - Data models, utilities, and QoS profiles
- **[C++ Applications](apps/cxx11/README.md)** - C++ development guide
- **[Python Applications](apps/python/README.md)** - Python setup and development

### Tools and Services
- **[Recording/Replay Services](services/README.md)** - Data capture and playback
- **[Monitoring Tools](tools/README.md)** - Real-time monitoring and debugging

### Reference
- **[GitHub Copilot Prompts](.github/prompts/)** - AI-powered app generation templates
- **[RTI Community](https://community.rti.com/)** - Support and resources
- **[RTI Documentation](https://community.rti.com/static/documentation/)** - Official documentation

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
