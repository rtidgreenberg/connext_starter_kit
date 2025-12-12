# Flexible Autonomous System Toolkit

Cross-language DDS system/application templates to accellerate development.

## Choose your adventure
- [🎯 Use Cases and Examples](#-use-cases-and-examples)
- [📚 Documentation](#-documentation)
- [🛠️ Getting Started](#️-getting-started)
- [Support](#support)

## 🎯 Use Cases and Examples

### 1. Generate Prototype C++ Applications with GitHub Copilot
**Use Case**: Rapidly create new DDS applications using AI-powered code generation

- **📖 Guide**: [C++ Application Creation with Copilot](apps/cxx11/README.md)
- **🎯 What You'll Learn**:
  - Use structured prompts to generate complete DDS applications
  - Specify readers and writers for custom data flows
  - Automatically generate CMakeLists.txt and project structure
  - Create event-driven applications with AsyncWaitSet

**Example**: Generate a sensor monitoring app with Position/State readers and Command writer
```
"Follow instructions in build_cxx.prompt.md. Create a new cxx app with Position and State as readers and Command as writer"
```

### 2. Basic I/O Application (Reference Implementation)
**Use Case**: Learn fundamental DDS patterns and cross-language communication

- **📖 C++ Guide**: [example_io_app C++](apps/cxx11/example_io_app/README.md)
- **📖 Python Guide**: [example_io_app Python](apps/python/example_io_app/README.md)
- **🎯 What You'll Learn**:
  - Set up DomainParticipant and AsyncWaitSet/asyncio
  - Create DataReaders and DataWriters with QoS profiles
  - Handle incoming messages with event-driven callbacks
  - Communicate between C++ and Python applications

**Key Features**: 3 writers (Command, Button, Config), 1 reader (Position), distributed logging

### 3. Command Override with Ownership Strength
**Use Case**: Priority-based message arbitration with dynamic QoS changes

- **📖 Guide**: [command_override](apps/cxx11/command_override/README.md)
- **🎯 What You'll Learn**:
  - Configure EXCLUSIVE ownership for priority control
  - Use ownership strength to determine message authority
  - Modify QoS programmatically at runtime
  - Handle multiple competing publishers

**Key Features**: 3 writers with different strengths (10, 20, 30), dynamic QoS modification, 4-phase demonstration

### 4. Large Data SHMEM Transfer between C++ and Python
**Use Case**: Efficient transfer of large data (~900 KB images) using shared memory transport in C++ and Python

- **📖 C++ Guide**: [large_data_app C++](apps/cxx11/large_data_app/README.md)
- **📖 Python Guide**: [large_data_app Python](apps/python/large_data_app/README.md)
- **🎯 What You'll Learn**:
  - Configure large data participant and QoS profiles (LARGE_DATA_SHMEM)
  - Use shared memory transport for efficient intra-host data transfer
  - Handle large payloads with Image data type
  - Cross-language large data communication (C++ ↔ Python over SHMEM)

**Key Features**: 640x480 RGB images (~900 KB), shared memory transport (C++ & Python), 1 Hz publishing, distributed logging

### 5. Large Data Zero-Copy Transfer
**Use Case**: Maximum performance transfer of large data (3 MB images @ 10 Hz) with zero-copy

- **📖 Guide**: [fixed_image_flat_zc](apps/cxx11/fixed_image_flat_zc/README.md)
- **🎯 What You'll Learn**:
  - Use FlatData types for zero-copy communication
  - Configure shared memory transport for maximum performance
  - Handle data consistency with loaned samples
  - Monitor throughput and latency

**Key Features**: 3 MB fixed-size images, XCDR2 encoding, zero-copy intra-host, ~18.6 MB/sec throughput

### 6. Time-Based Filtering and Status Listeners
**Use Case**: Subscribe to high-frequency data at a reduced rate for GUI displays and monitoring dashboards, with comprehensive DDS event awareness

- **📖 Guide**: [downsampled_reader](apps/python/downsampled_reader/README.md)
- **🎯 What You'll Learn**:
  - Apply time-based filtering with STATUS1HZ_QOS profile
  - Implement status listeners for real-time DDS event monitoring
  - Use `on_subscription_matched`, `on_liveliness_changed`, and `on_requested_deadline_missed` callbacks
  - Reduce CPU load for GUI applications without affecting other subscribers
  - Configure independent data rates for different readers on same topic
  - Build proactive monitoring and automated failover systems

**Key Features**: 1Hz downsampling with TIME_BASED_FILTER, BEST_EFFORT QoS for periodic data, reader-side filtering (keyed data), status listener callbacks for publisher health monitoring

### 7. Dynamic Test Environment Isolation with Domain Participant Partitions
**Use Case**: Isolate message traffic in test environments, CI/CD pipelines, and multi-instance testing scenarios using runtime partition changes

- **📖 Guide**: [dynamic_partition_qos](apps/cxx11/dynamic_partition_qos/README.md)
- **🎯 What You'll Learn**:
  - Modify Domain Participant Partitions at runtime using the PARTITION QoSPolicy
  - Isolate unit tests, integration tests, and CI/CD jobs without separate domains
  - Test failover scenarios by dynamically switching partitions
  - Verify partition-based communication segmentation with multiple instances
  - Combine XML QoS profiles with environment variables for automated testing
  - Understand how DomainParticipant partitions eliminate Simple Endpoint Discovery

**Key Features**: Unique App IDs for instance tracking, runtime partition changes via terminal input, ignores own publications, supports multiple partitions simultaneously, comprehensive test scenarios for unit test isolation and failover testing

### 8. System Architecture and Best Practices
**Use Case**: Understand the architectural patterns and design decisions

- **📖 Guide**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **🎯 What You'll Learn**:
  - Layered architecture (apps → DDS → middleware)
  - Data type design patterns (simple, complex, FlatData)
  - QoS profile selection guidelines
  - Cross-language communication mechanics
  - Build system organization

**Key Topics**: Utility classes, topic-application matrix, QoS profiles, CMake structure

## 📚 Documentation

### Getting Started
- **[System Architecture](ARCHITECTURE.md)** - Technical implementation details and patterns
- **[DDS Layer](dds/README.md)** - Data models, utilities, and QoS profiles
- **[C++ Applications](apps/cxx11/README.md)** - C++ development guide
- **[Python Applications](apps/python/README.md)** - Python setup and development

### Application Guides
- **[example_io_app (C++)](apps/cxx11/example_io_app/README.md)** - Basic DDS patterns
- **[example_io_app (Python)](apps/python/example_io_app/README.md)** - Python implementation
- **[command_override](apps/cxx11/command_override/README.md)** - Ownership control
- **[large_data_app (C++)](apps/cxx11/large_data_app/README.md)** - Large data with shared memory
- **[large_data_app (Python)](apps/python/large_data_app/README.md)** - Python large data shared memory transfer
- **[fixed_image_flat_zc](apps/cxx11/fixed_image_flat_zc/README.md)** - Zero-copy large data
- **[downsampled_reader](apps/python/downsampled_reader/README.md)** - Time-based filtering for GUI/monitoring
- **[dynamic_partition_qos](apps/cxx11/dynamic_partition_qos/README.md)** - Test environment isolation with Domain Participant Partitions

### Reference
- **[GitHub Copilot Prompts](.github/prompts/)** - AI-powered app generation templates

## 🛠️ Getting Started

### Prerequisites

- **RTI Connext DDS 7.3.0+** installed and licensed
- **C++14 compiler** (GCC 7.3.0+ or equivalent) for C++ apps
- **Python 3.8+** with virtual environment support for Python apps
- **CMake 3.12+** for build configuration
- **Git submodules**: Clone with `--recurse-submodules` or run `git submodule update --init --recursive`

### Quick Setup

```bash
# 1. Set RTI environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# 2. Clone with submodules
git clone --recurse-submodules <repository-url>
cd connext_starter_kit

# 3. For Python apps - copy RTI license file
cp /path/to/your/rti_license.dat apps/python/

# 4. Build DDS layer (required first)
cd dds/cxx11 && mkdir -p build && cd build
cmake .. && make -j4

# 5. Choose your path:
#    - Generate new app with Copilot: See apps/cxx11/README.md
#    - Build example_io_app: See apps/cxx11/example_io_app/README.md
#    - Build command_override: See apps/cxx11/command_override/README.md
#    - Build dynamic_partition_qos: See apps/cxx11/dynamic_partition_qos/README.md
#    - Build fixed_image_flat_zc: See apps/cxx11/fixed_image_flat_zc/README.md
#    - Build Python apps: See apps/python/README.md
```

### Next Steps

1. **Read [ARCHITECTURE.md](ARCHITECTURE.md)** to understand the system design
2. **Choose a use case** from the list above based on your needs
3. **Follow the specific guide** for detailed build and run instructions
4. **Explore [DDS Layer documentation](dds/README.md)** to understand data models and utilities

## Support

- **RTI Community**: https://community.rti.com/
- **RTI Documentation**: https://community.rti.com/static/documentation/
