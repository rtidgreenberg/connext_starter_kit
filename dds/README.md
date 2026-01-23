# DDS Layer Documentation

Data Distribution Service (DDS) layer for RTI Connext Starter Kit, providing data models, utility classes, and generated code for cross-language DDS communication.

## Table of Contents
- [Directory Structure](#directory-structure)
- [Data Model (IDL Definitions)](#data-model-idl-definitions)
- [Utility Classes (C++)](#utility-classes-c)
- [Quality of Service (QoS) Profiles](#quality-of-service-qos-profiles)
- [Generated Code](#generated-code)
- [Building](#building)
- [Use in Applications](#use-in-applications)

## Directory Structure

```
dds/
├── CMakeLists.txt          # Unified build configuration
├── README.md               # This file
├── datamodel/              # IDL definitions
│   └── idl/                # Source IDL files
│       ├── ExampleTypes.idl    # Data structures
│       └── Definitions.idl     # Configuration constants (QoS, domains, topics)
├── qos/                    # Quality of Service configurations
│   └── DDS_QOS_PROFILES.xml
└── utils/                  # Utility classes
    └── cxx11/              # C++11 utility classes (header-only)
        ├── DDSParticipantSetup.hpp # DDS participant management
        ├── DDSReaderSetup.hpp      # Template reader interface
        └── DDSWriterSetup.hpp      # Template writer interface

Note: The top-level build directory (../../build/) is where the CMake build system 
generates all DDS types, builds the DDS library, and compiles application binaries:

```

## Data Model (IDL Definitions)

### ExampleTypes.idl

Core data structures demonstrating common DDS patterns.

#### Data Types:

**Command** - Control Messages
- `command_id` (key), `destination_id`, `command_type`, `message`, `urgent`
- Types: START, STOP, PAUSE, RESET, SHUTDOWN

**Position** - Location Data
- `source_id` (key), `latitude`, `longitude`, `altitude`, `timestamp_sec`

**Button** - User Input Events
- `source_id` (key), `button_id` (key), `button_state`, `press_count`, `last_press_timestamp_sec`, `hold_duration_sec`
- States: PRESSED, RELEASED, HELD, DOUBLE_CLICK

**Config** - Configuration Parameters
- `destination_id` (key), `parameter_name`, `parameter_value`, `numeric_value`, `enabled`

**State** - System Status
- `source_id` (key), `state_value`, `error_message`
- States: INIT, RUNNING, ERROR, RESTARTING, SHUTTING_DOWN

**Image** - Media Data
- `image_id` (key), `width`, `height`, `format`, `data` (sequence<octet, 1024>)

**FinalFlatImage** - High-Performance Large Data
- `@final @language_binding(FLAT_DATA)` with `@transfer_mode(SHMEM_REF)`
- Zero-copy 3 MB payload for high-throughput applications

### Definitions.idl

Centralizes DDS configuration constants organized into three modules: `qos_profiles`, `domains`, and `topics`.

**Module: qos_profiles** - QoS Profile Names:
- Domain Participant: `DEFAULT_PARTICIPANT`, `LARGE_DATA_PARTICIPANT`
- Data Patterns: `ASSIGNER`, `EVENT`, `METADATA`, `STATUS`
- Command Override: `COMMAND_STRENGTH_10`, `COMMAND_STRENGTH_20`, `COMMAND_STRENGTH_30`
- Large Data: `LARGE_DATA_SHMEM`, `LARGE_DATA_SHMEM_ZC`

**Module: domains** - Domain IDs:
- `DEFAULT_DOMAIN_ID = 1`
- `TEST_DOMAIN_ID = 100`

**Module: topics** - Topic Names:
- `COMMAND_TOPIC`, `CONFIG_TOPIC`, `POSITION_TOPIC`, `STATE_TOPIC`, `BUTTON_TOPIC`, `IMAGE_TOPIC`, `FINAL_FLAT_IMAGE_TOPIC`

Benefits: Centralized configuration, namespace safety (avoids conflicts with DDS library), type safety, cross-language consistency.

## C++11 Utility Classes

Header-only template classes located in `utils/cxx11/` for simplified DDS application development.

### DDSParticipantSetup

Manages the core DDS infrastructure for applications (in `DDSParticipantSetup.hpp`).

**Manages:**
- **DomainParticipant**: Application's connection to a DDS domain with configurable QoS profile
- **AsyncWaitSet**: Centralized event dispatcher with configurable thread pool for asynchronous processing of all DDS status events
- **QoS File Path**: Stores XML QoS configuration path for reuse by DDSReaderSetup/DDSWriterSetup

**Constructor Parameters:**
- `domain_id` - DDS domain ID
- `thread_pool_size` - AsyncWaitSet thread pool size (default: 5)
- `participant_qos_file` - Path to XML QoS file
- `participant_qos_profile` - QoS profile name for participant
- `app_name` - Application name for participant entity naming

**Public Methods:**
- `participant()` - Returns reference to DomainParticipant
- `async_waitset()` - Returns reference to AsyncWaitSet
- `qos_file_path()` - Returns stored QoS file path

### DDSReaderSetup

Template class for DataReader creation with event-driven callback processing (in `DDSReaderSetup.hpp`).

**Features:**
- Creates DataReader with topic and QoS from DDSParticipantSetup's stored QoS file path
- Supports status callbacks: `data_available`, `subscription_matched`, `liveliness_changed`, `requested_deadline_missed`, `requested_incompatible_qos`, `sample_lost`, `sample_rejected`
- Registers status conditions with centralized AsyncWaitSet for asynchronous processing

**Constructor Parameters:**
- `p_setup` - Shared pointer to DDSParticipantSetup (provides participant, AsyncWaitSet, and QoS file path)
- `topic_name` - Topic name string
- `qos_profile` - QoS profile name (optional)

### DDSWriterSetup

Template class for DataWriter creation with event-driven callback processing (in `DDSWriterSetup.hpp`).

**Features:**
- Creates DataWriter with topic and QoS from DDSParticipantSetup's stored QoS file path
- Supports status callbacks: `publication_matched`, `liveliness_lost`, `offered_deadline_missed`, `offered_incompatible_qos`
- Registers status conditions with centralized AsyncWaitSet for asynchronous processing

**Constructor Parameters:**
- `p_setup` - Shared pointer to DDSParticipantSetup (provides participant, AsyncWaitSet, and QoS file path)
- `topic_name` - Topic name string
- `qos_profile` - QoS profile name (optional)

## QoS Configuration

Located in `qos/DDS_QOS_PROFILES.xml`.

### Domain Participant Profiles
- **DefaultParticipant** - General-purpose configuration
- **LargeDataParticipant** - Optimized for large data transfers

### DataWriter/DataReader Profiles
- **AssignerQoS** - Topic-based QoS assignment
- **EventQoS** - Event-driven communication
- **MetadataQoS** - Metadata and configuration
- **StatusQoS** - Status and health monitoring
- **CommandStrength10QoS/20QoS/30QoS** - Command override with ownership strength
- **LargeDataSHMEMQoS** - Large data with shared memory
- **LargeDataSHMEM_ZCQoS** - Zero-copy transfer mode

Profile names are centralized in `Definitions.idl` (qos_profiles module) for cross-language consistency.

## Building

### Prerequisites
- **RTI Connext DDS 7.3.0+** installed and licensed
- **CMake 3.12+** for build automation
- **C++14 compiler** (GCC 7.3+, Clang, MSVC)
- **Python 3.6+** with RTI Connext Python API (for Python generation)

### Quick Start

```bash
# Set RTI environment variable and architecture
export NDDSHOME=/path/to/rti_connext_dds-7.3.0
source $NDDSHOME/resource/scripts/rtisetenv_<target>.bash

# Build from top-level (automatically builds all type support)
cd /path/to/connext_starter_kit
mkdir -p build && cd build
cmake ..
cmake --build .

# Verify generated files (from workspace root)
ls build/dds/cxx11_gen/*.hpp
ls build/dds/python_gen/*.py
ls build/dds/xml_gen/*.xml
```

This generates all type support files automatically:
- **C++**: `ExampleTypes.hpp/cxx`, `Definitions.hpp/cxx` with plugins → `build/lib/libdds_typesupport.so`
- **Python**: `ExampleTypes.py`, `Definitions.py` with module structure  
- **XML**: `ExampleTypes.xml`, `Definitions.xml` for documentation

### CMake Build Options
- `GENERATE_CXX11_TYPES` (default: ON) - Generate C++11 type support
- `GENERATE_PYTHON_TYPES` (default: ON) - Generate Python type support
- `GENERATE_XML_TYPES` (default: ON) - Generate XML representations
- `GENERATE_DEFINITIONS` (default: ON) - Generate Definitions constants (header-only)
- `BUILD_CXX_TYPES_LIBRARY` (default: ON) - Build C++ type support shared library


## Use in Applications

### C++ Applications

Include the generated types and utility classes:

```cpp
#include "ExampleTypes.hpp"
#include "Definitions.hpp"
#include "DDSParticipantSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"

// Create DDS participant with QoS profile
auto dds_participant = std::make_shared<DDSParticipantSetup>(
    domains::DEFAULT_DOMAIN_ID, 
    thread_pool_size, 
    qos_file, 
    qos_profiles::DEFAULT_PARTICIPANT, 
    app_name);

// Create writer with topic and QoS profile
auto position_writer = std::make_shared<DDSWriterSetup<example_types::Position>>(
    dds_participant, 
    topics::POSITION_TOPIC, 
    qos_profiles::ASSIGNER
);
```

### Python Applications

Import generated modules and use constants:

```python
import rti.connextdds as dds
from python_gen import ExampleTypes
from python_gen.Definitions import topics, qos_profiles, domains

# Load QoS provider
qos_provider = dds.QosProvider("path/to/DDS_QOS_PROFILES.xml")

# Create participant with QoS profile
participant = dds.DomainParticipant(
    domains.DEFAULT_DOMAIN_ID,
    qos_provider.participant_qos_from_profile(qos_profiles.DEFAULT_PARTICIPANT)
)

# Create topic
topic = dds.Topic(participant, topics.POSITION_TOPIC, ExampleTypes.Position)

# Create writer with QoS profile
writer = dds.DataWriter(
    publisher, 
    topic,
    qos_provider.datawriter_qos_from_profile(qos_profiles.ASSIGNER)
)
```

## Adding New Data Types

1. Define in `datamodel/idl/ExampleTypes.idl`
2. Add topic name to `datamodel/idl/Definitions.idl` (topics module)
3. Regenerate from top-level: `cd /path/to/connext_starter_kit/build && cmake --build . --target cxx_definitions`
4. Update applications to use new types (reference via `topics::YOUR_TOPIC`)

## Modifying QoS Profiles

1. **Edit XML** (`qos/DDS_QOS_PROFILES.xml`)
2. **Add profile name** to `datamodel/idl/Definitions.idl` (qos_profiles module) if needed
3. **Rebuild from top-level**: `cd /path/to/connext_starter_kit/build && cmake --build .`
4. **Test Changes** with existing applications
5. **Document Updates** in application README files

### Best Practices:
- ✅ **Use @key annotations** for topic instances
- ✅ **Bound string lengths** for deterministic memory
- ✅ **Version IDL carefully** - changes affect wire compatibility
- ✅ **Test cross-language** - verify C++ ↔ Python communication
- ✅ **Document changes** - update README files when adding types

---

## 📖 Related Documentation

- **Application READMEs**: `../apps/cxx11/README.md`, `../apps/python/README.md`
- **RTI Documentation**: [RTI Connext DDS User Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/html_files/RTI_ConnextDDS_CoreLibraries_UsersManual/)
- **IDL Specification**: [OMG IDL 4.2](https://www.omg.org/spec/IDL/4.2/)
- **QoS Guide**: [RTI Connext DDS QoS Reference](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/html_files/RTI_ConnextDDS_CoreLibraries_QoS_Reference_Guide/)

---

## 📊 Summary

The DDS layer provides a **complete foundation** for building distributed applications with RTI Connext DDS:

| Component | Purpose | Languages | Features |
|-----------|---------|-----------|----------|
| **DataModel** | IDL type definitions | IDL | 6 example types, enums, bounded strings |
| **C++ Utils** | High-level DDS abstractions | C++11 | Context management, generic interface |
| **Python CodeGen** | Generated Python modules | Python | Type-safe classes, constants |  
| **QoS Profiles** | DDS quality configuration | XML | Participant & endpoint profiles |

**Key Benefits:**
- 🚀 **Rapid Development** - Pre-built types and utilities
- 🔄 **Cross-Language** - C++ and Python interoperability  
- 📏 **Best Practices** - RTI-recommended patterns
- 🛡️ **Type Safety** - Generated code prevents errors
- ⚙️ **Configurable** - External QoS and topic management

This foundation enables developers to focus on application logic while leveraging robust, production-ready DDS infrastructure.

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!