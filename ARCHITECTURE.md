# System Architecture

Technical implementation details, data types, and architectural patterns for the Flexible Autonomous System Toolkit.

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Data Types and Topics](#data-types-and-topics)
- [Utility Classes](#utility-classes)
- [Data Model Design](#data-model-design)
- [Quality of Service (QoS)](#quality-of-service-qos)
- [Cross-Language Communication](#cross-language-communication)
- [Build System](#build-system)

## Architecture Overview

The toolkit uses a layered architecture separating data definitions, utilities, and applications:

```
┌─────────────────────────────────────────────────┐
│         Applications (apps/)                    │
│  ┌───────────────────┐ ┌───────────────────┐    │
│  │    C++ Apps       │ │   Python Apps     │    │
│  │ example_io        │ │ example_io        │    │
│  │ command_override  │ │ large_data        │    │
│  │ fixed_image_flat  │ │ downsampled_reader│    │
│  │ large_data        │ │                   │    │
│  │ burst_large_data  │ │                   │    │
│  │ dynamic_partition │ │                   │    │
│  └───────────────────┘ └───────────────────┘    │
└─────────────────────────────────────────────────┘
                    │
                    │ Uses DDS APIs
                    ▼
┌─────────────────────────────────────────────────┐
│         DDS Layer (dds/)                        │
│  ┌──────────────┐  ┌────────────────────┐       │
│  │  Data Model  │  │     Utilities      │       │
│  │  (IDL files) │  │ DDSParticipantSetup│       │
│  │              │  │ DDSWriterSetup     │       │
│  │              │  │ DDSReaderSetup     │       │
│  └──────────────┘  └────────────────────┘       │
│  ┌──────────────┐  ┌──────────────┐             │
│  │  QoS XML     │  │  Generated   │             │
│  │  Profiles    │  │  Code (C++/  │             │
│  │              │  │  Python)     │             │
│  └──────────────┘  └──────────────┘             │
│  ┌───────────────────────────────────────────┐  │
│  │        RTI Connext DDS Middleware         │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### Key Architectural Principles

1. **Separation of Concerns**: Data models, utilities, and applications are independent
2. **Language Agnostic**: IDL-based data models enable C++/Python interoperability
3. **QoS-Driven**: XML-based Quality of Service for runtime configuration
4. **Zero-Copy Capable**: FlatData types for high-performance data transfer
5. **Event-Driven**: AsyncWaitSet (C++) and asyncio (Python) for efficient processing

## Data Types and Topics

### Standard Data Types

| Data Type | Topic | Size | Description | Use Case |
|-----------|-------|------|-------------|----------|
| `Command` | `Command` | ~100 bytes | Control commands (START, PAUSE, RESET) | System control |
| `Button` | `Button` | ~50 bytes | Button events (UP, DOWN, LEFT, RIGHT) | User input |
| `Config` | `Config` | ~200 bytes | Configuration parameters | Settings management |
| `Position` | `Position` | ~150 bytes | GPS coordinates (lat/lon/alt) | Location tracking |
| `State` | `State` | ~100 bytes | System state enumeration | State monitoring |
| `Image` | `Image` | Variable | Binary image data | Standard imaging |

### High-Performance Data Types

| Data Type | Topic | Size | Description | Use Case |
|-----------|-------|------|-------------|----------|
| `FinalFlatImage` | `FinalFlatImage` | 3 MB fixed | Zero-copy flat data | Large data @ 10 Hz |
| `FinalFlatPointCloud` | `FinalFlatPointCloud` | 500 KB fixed | Zero-copy flat data | Point cloud data |

**FlatData Characteristics:**
- **XCDR2 Encoding**: Uses XCDR encoding version 2 with host platform endianness
- **Application-Level Serialization**: Data serialized once at creation time
- **Zero-Copy Capable**: Eliminates serialization overhead for intra-host communication
- **Fixed Size**: Optimized for consistent memory allocation patterns


## Utility Classes

### DDSParticipantSetup
**Purpose**: Centralized DomainParticipant and AsyncWaitSet management

**Features:**
- DomainParticipant initialization with QoS
- AsyncWaitSet creation for event-driven processing
- Distributed logger configuration
- Graceful shutdown handling

**Usage:**
```cpp
auto dds_participant = std::make_shared<DDSParticipantSetup>(
    domain_id, thread_pool_size, qos_file_path, qos_profile, app_name);

// Access managed resources
dds::domain::DomainParticipant& participant = dds_participant->participant();
rti::core::cond::AsyncWaitSet& aws = dds_participant->async_waitset();
const std::string& qos_path = dds_participant->qos_file_path();
```

### DDSReaderSetup
**Purpose**: Template class for DataReader creation with event-driven callback processing

**Features:**
- Creates DataReader with topic and QoS from DDSParticipantSetup's stored QoS file path
- Supports status callbacks: `data_available`, `subscription_matched`, `liveliness_changed`, `requested_deadline_missed`, `requested_incompatible_qos`, `sample_lost`, `sample_rejected`
- Registers status conditions with centralized AsyncWaitSet for asynchronous processing

### DDSWriterSetup
**Purpose**: Template class for DataWriter creation with event-driven callback processing

**Features:**
- Creates DataWriter with topic and QoS from DDSParticipantSetup's stored QoS file path
- Supports status callbacks: `publication_matched`, `liveliness_lost`, `offered_deadline_missed`, `offered_incompatible_qos`
- Registers status conditions with centralized AsyncWaitSet for asynchronous processing


## Data Model Design

### IDL Organization

```
dds/datamodel/idl/
├── ExampleTypes.idl    # Business data types (Command, Button, Config, Position, etc.)
└── Definitions.idl     # Configuration constants (QoS profiles, domains, topics)
```

**Definitions.idl modules:**
- `qos_profiles` - QoS profile name constants
- `domains` - Domain ID constants  
- `topics` - Topic name constants


## Quality of Service (QoS)

### QoS Profiles

Defined in `dds/qos/DDS_QOS_PROFILES.xml`:

**EventQoS:**
- **Reliability**: RELIABLE (guaranteed delivery)
- **History**: KEEP_ALL (no samples lost)
- **Liveliness**: AUTOMATIC (4s writer, 10s reader)
- **Use Case**: Button presses, alerts, aperiodic critical events
- **Pattern**: Strictly reliable communication with liveliness detection

**MetadataQoS:**
- **Reliability**: RELIABLE
- **Durability**: TRANSIENT_LOCAL (late-joiners receive last value)
- **History**: KEEP_LAST 1
- **Use Case**: Configuration data that late-joiners need
- **Pattern**: State pattern - last value always available

**StatusQoS:**
- **Reliability**: BEST_EFFORT (low latency, no retransmission)
- **History**: KEEP_LAST 1
- **Deadline**: 4s writer, 10s reader (missed deadline detection)
- **Use Case**: Periodic sensor data (Position), high-frequency updates
- **Pattern**: Real-time status updates where newest data matters most

**LargeDataSHMEMQoS:**
- **Reliability**: BEST_EFFORT
- **History**: KEEP_LAST 1
- **Transport**: SHMEM only (pinned for large message_size_max)
- **Resource Limits**: initial_samples = 2 (conserve memory)
- **Use Case**: Large data (>65KB) over shared memory without zero-copy
- **Pattern**: Low-latency large transfers, intra-host only

**LargeDataSHMEM_ZCQoS:**
- **Reliability**: RELIABLE with APPLICATION_AUTO_ACKNOWLEDGMENT_MODE
- **History**: KEEP_LAST 1 (implicit from base)
- **Transport**: SHMEM with zero-copy (reference passing)
- **Writer Loaned Samples**: 32 initial (prevents premature sample reuse)
- **Reliability Protocol**: HIGH_RATE optimization
- **Use Case**: Zero-copy large data with data consistency guarantees
- **Pattern**: High-performance zero-copy with acknowledgment-based consistency

**CommandStrength10/20/30QoS:**
- **Base**: EventQoS (inherits RELIABLE, KEEP_ALL, liveliness)
- **Ownership**: EXCLUSIVE with strengths 10, 20, 30
- **Use Case**: Priority-based command arbitration (Auto → Obstacle Override → Manual)
- **Pattern**: Multi-source command with priority override

**AssignerQoS:**
- **Purpose**: Centralized QoS assignment by topic pattern
- **Assignments**:
  - `LargeData*` → LargeDataSHMEMQoS
  - `Position*` → StatusQoS
  - `Config*` → MetadataQoS
  - `Button*` → EventQoS
  - `Command*` → EventQoS
- **Benefit**: Change QoS without recompilation

### QoS Selection Guidelines

| Data Characteristic | Recommended Profile | Key Reason |
|---------------------|---------------------|------------|
| Aperiodic critical events (button press) | EventQoS | KEEP_ALL ensures no events lost |
| Periodic sensor data (Position) | StatusQoS | BEST_EFFORT for low latency, Deadline for monitoring |
| Configuration/settings | MetadataQoS | TRANSIENT_LOCAL for late-joiners |
| Large data (>65KB), low latency | LargeDataSHMEMQoS | SHMEM-only, BEST_EFFORT |
| Large data with zero-copy | LargeDataSHMEM_ZCQoS | Zero-copy + application ack for consistency |
| Multi-source commands with priority | CommandStrength*QoS | EXCLUSIVE ownership for arbitration |

### Using AssignerQoS

Applications can reference "AssignerQoS" instead of specific profiles. The topic pattern matching automatically assigns the correct underlying profile:

```cpp
// This will use StatusQoS because topic name matches "Position*"
auto writer = std::make_shared<DDSWriterSetup<Position>>(dds_participant, "Position", "AssignerQoS");

// This will use EventQoS because topic name matches "Button*"
auto reader = std::make_shared<DDSReaderSetup<Button>>(dds_participant, "Button", "AssignerQoS");
```

This allows QoS changes in XML without application recompilation.

## Cross-Language Communication

### Type Compatibility

RTI Connext DDS ensures wire-protocol compatibility between C++ and Python:

```
┌─────────────┐         DDS Domain          ┌─────────────┐
│   C++ App   │◄──────────────────────────► │ Python App  │
│             │                             │             │
│ Write:      │                             │ Read:       │
│  Position   ├────────────────────────────►│  Position   │
│             │                             │             │
│ Read:       │                             │ Write:      │
│  Command    │◄────────────────────────────┤  Command    │
└─────────────┘                             └─────────────┘
```

**Key Points:**
- Same IDL definitions generate compatible C++ and Python code
- QoS profiles apply regardless of publisher language
- Data serialization/deserialization handled by RTI middleware
- No manual marshaling required

### Language-Specific APIs

**C++11 (Modern, Type-Safe):**
```cpp
auto samples = reader.read();
for (const auto& sample : samples) {
    if (sample.info().valid()) {
        const Position& pos = sample.data();
    }
}
```

**Python (Asyncio-Based):**
```python
async for data in reader.take_data_async():
    print(f"Position: {data.latitude}, {data.longitude}")
```

## Build System

### CMake Structure

```
connext_starter_kit/
├── CMakeLists.txt              # Top-level CMake (builds dds/ and apps/)
├── dds/
│   ├── CMakeLists.txt          # Generates C++/Python from IDL, builds Types Library
│   └── build/
│       ├── cxx11_gen/          # Generated C++ code
│       └── python_gen/         # Generated Python code
├── apps/
│   ├── cxx11/
│   │   ├── example_io_app/
│   │   │   └── CMakeLists.txt  # Links to Types Library
│   │   ├── command_override/
│   │   │   └── CMakeLists.txt
│   │   ├── fixed_image_flat_zc/
│   │   │   └── CMakeLists.txt
│   │   ├── large_data_app/
│   │   │   └── CMakeLists.txt
│   │   ├── burst_large_data_app/
│   │   │   └── CMakeLists.txt
│   │   └── dynamic_partition_qos/
│   │       └── CMakeLists.txt
│   └── python/
│       └── (Python apps - no CMake required)
└── resources/
    └── rticonnextdds-cmake-utils/  # Git submodule (REQUIRED)
```

### Code Generation Flow

```
IDL Files (dds/datamodel/*.idl)
        │
        │ rtiddsgen (via CMake)
        ▼
Generated C++/Python Code
        │
        │ Compile/Install
        ▼
Shared Libraries / Python Modules
        │
        │ Link/Import
        ▼
Applications
```

### Build Dependencies

1. **RTI Connext DDS 7.3.0**: Core middleware ($NDDSHOME must be set)
2. **rticonnextdds-cmake-utils**: CMake helper functions (git submodule)
3. **C++14 Compiler**: GCC 7.3.0+ or equivalent
4. **CMake 3.12+**: Build configuration
5. **Python 3.8+**: For Python applications

### Build Order

```bash
# 1. Build from top-level (generates code from IDL, builds DDS library and apps)
cd build && cmake .. && make -j4

# Or build individual components:
# 1. Build DDS shared library (generates C++/Python code from IDL)
cd dds/build && cmake .. && make -j4

# 2. Build applications (links to DDS library)
cd apps/cxx11/example_io_app/build && cmake .. && make -j4
```

**Important**: Applications depend on the DDS shared library, so the DDS layer must be built first.
