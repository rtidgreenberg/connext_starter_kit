# Connext Starter Kit

Cross-language DDS system/application templates to accelerate development.

## Prerequisites

- **RTI Connext DDS 7.7.0** [installed and licensed](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/installation_guide/index.html) for C++ apps, DDS type support, and command-line services
- **RTI Connext DDS Python API** for Python apps and Python GUI/tools. Launchers can install the public PyPI package with an RTI license file, or use an activated wheel from an RTI Connext installation.
- **C++14 compiler** (the Ubuntu 24.04 container provides GCC 13) for C++ apps
- **Python 3.10+** with virtual environment support for Python apps and tools. The Docker workflow uses Python 3.12.
- **CMake 3.12+** for build configuration
- **Git submodules**: Clone with `--recurse-submodules` or run `git submodule update --init --recursive`

## Quick Start

1. **Clone with submodules:**
   ```bash
   git clone --recurse-submodules <repository-url>
   cd connext_starter_kit
   ```

2. **Build and enter the supported container:**
   ```bash
   export RTI_LICENSE_HOST_PATH="${RTI_LICENSE_HOST_PATH:-$HOME/rti_license.dat}"
   test -r "$RTI_LICENSE_HOST_PATH"
   mkdir -p shared
   install -m 600 "$RTI_LICENSE_HOST_PATH" shared/rti_license.dat
   docker compose -f docker-compose.connext-7.7.yml build
   docker compose -f docker-compose.connext-7.7.yml run --rm connext
   ```

3. **Or configure a native Connext installation:**
   ```bash
   export NDDSHOME=/path/to/rti_connext_dds-7.7.0
   ```

4. **Configure your target environment:**
   Source the helper script for your target architecture:
   ```bash
   source $NDDSHOME/resource/scripts/rtisetenv_x64Linux4gcc8.5.0.bash
   ```
   
   The supported container workflow above provides the tested Ubuntu 24.04 environment.

5. **Build the project:**
   ```bash
   mkdir -p build && cd build
   cmake ..
   cmake --build .
   ```

5. **For Python apps and tools - select a Python API source:**
   ```bash
   # Public PyPI package: requires an RTI license file.
   export RTI_PYTHON_SOURCE=pypi
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

   Or use an activated wheel from a Professional installation, with no
   separate license-file configuration:
   ```bash
   export RTI_PYTHON_SOURCE=activated-wheel
   export RTI_PYTHON_WHEEL=/path/to/rti_connext_activated-<version>-cp<python>-<platform>.whl
   ```

   With `RTI_PYTHON_SOURCE=auto` (the default), Python launchers reuse a
   compatible installed package, then prefer an explicitly supplied or
   `NDDSHOME`-bundled activated wheel. Interactive launchers prompt when no
   source is available; unattended runs must set one of the variables above.
   
   Get a free trial license at https://www.rti.com/get-connext

## Container Runtime Testing

Run runtime tests in the provided Ubuntu 24.04 Connext 7.7.0 container. It
installs the Connext Debian packages from RTI's official APT repository and
`rti.connext==7.7.0` from PyPI. Do not use a host virtual environment for
runtime validation that loads RTI libraries or services.

Initialize the repository submodule before building:

```bash
git submodule update --init --recursive
```

Copy the host license file into the ignored `shared/` bind-mount directory.
The container reads it as `/shared/rti_license.dat`:

```bash
export RTI_LICENSE_HOST_PATH="${RTI_LICENSE_HOST_PATH:-$HOME/rti_license.dat}"
test -r "$RTI_LICENSE_HOST_PATH"
mkdir -p shared
install -m 600 "$RTI_LICENSE_HOST_PATH" shared/rti_license.dat
docker compose -f docker-compose.connext-7.7.yml build
docker compose -f docker-compose.connext-7.7.yml run --rm connext
```

The repository is mounted read-only at `/workspace`. Copy it to `/tmp` for
builds and tests that create repository-relative artifacts. Run the C++ build
and RTI Doctor unit suite with:

```bash
docker compose -f docker-compose.connext-7.7.yml run --rm connext \
   bash -lc 'cp -a /workspace/. /tmp/connext-workspace && \
   cd /tmp/connext-workspace && \
   cmake -S . -B /tmp/connext-build \
      -DCONNEXTDDS_VERSION=7.7.0 \
      -DCONNEXTDDS_ARCH=x64Linux4gcc8.5.0 \
      -DCONNEXTDDS_CXX11_STANDARD=DDS_PSM_Cxx && \
   cmake --build /tmp/connext-build -j"$(nproc)" && \
   ./tools/rti_doctor/run_tests.sh unit'
```

Use the same form for live tests, for example:

```bash
docker compose -f docker-compose.connext-7.7.yml run --rm connext \
   ./tools/rti_doctor/run_tests.sh live
```

## Table of Contents - What Do You Want to Do?

### 🚀 Getting Started
- [I want to learn basic DDS patterns with example apps](apps/cxx11/example_io_app/README.md)
- [I want to understand the system architecture](ARCHITECTURE.md)

### 🎯 Advanced DDS Patterns
- [I want to implement priority-based message control](apps/cxx11/command_override/README.md)
- [I want to transfer large data efficiently with shared memory](apps/cxx11/large_data_app/README.md)
- [I want maximum performance with zero-copy transfer](apps/cxx11/fixed_image_flat_zc/README.md)
- [I want to send high-rate burst traffic over LAN](apps/cxx11/burst_large_data_app/README.md)
- [I want to downsample high-frequency data for GUIs](apps/python/downsampled_reader/README.md)
- [I want to isolate test environments with partitions](apps/cxx11/dynamic_partition_qos/README.md)
- [I want ROS2-style parameter management over DDS](apps/cxx11/parameter_app/README.md)

### 📡 Foxglove Visualization
- [I want to publish GeoJSON map data to Foxglove](apps/cxx11/foxglove_geojson/README.md)
- [I want to stream raw images to Foxglove](apps/cxx11/foxglove_rawimage/README.md)
- [I want to stream H.264 video to Foxglove via GStreamer](apps/cxx11/foxglove_gstreamvideo_app/README.md)
- [I want to visualize 3D point clouds in Foxglove](apps/cxx11/foxglove_pointcloud/README.md)

### 📊 Data Recording and Analysis
- [I want to record DDS topics for debugging](services/README.md#i-want-to-record-a-selective-group-of-topics)
- [I want to convert recorded data to JSON/CSV](services/README.md#i-want-to-convert-my-recorded-data-to-json-for-post-processing)
- [I want to replay recorded data](services/README.md#i-want-to-replay-my-recorded-data)
- [I want to record/replay as well as tag items of interest using a Python GUI tool](services/README.md#i-want-to-control-recording-and-replay-services-with-a-gui)

### 🔧 Development Tools
- [I want to monitor DDS topics in real-time](tools/README.md)
- [I want to generate plotter visuals that can dynamically subscribe to data](tools/README.md#rti_view)
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
- **[RTI Community](https://community.rti.com/)** - Support and resources
- **[RTI Documentation](https://community.rti.com/static/documentation/)** - Official documentation

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
