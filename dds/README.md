# DDS Layer Documentation

Data Distribution Service (DDS) layer for RTI Connext Starter Kit, providing data models, utility classes, and generated code for cross-language DDS communication.

## Directory Structure

```
dds/
├── datamodel/              # IDL definitions
│   ├── ExampleTypes.idl    # Data structures
│   └── DDSDefs.idl         # Configuration constants
├── qos/                    # Quality of Service configs
│   └── DDS_QOS_PROFILES.xml
├── cxx11/                  # C++11 utilities and generated code
│   ├── src/utils/          # Utility classes
│   └── src/codegen/        # Generated C++ types
└── python/                 # Python generated code
    └── codegen/            # Generated Python types
```

## Data Model (IDL Definitions)

### ExampleTypes.idl

Core data structures demonstrating common DDS patterns.

#### Data Types:

**Command** - Control Messages
- `command_id` (key), `destination_id` (key), `command_type`, `message`, `timestamp_sec`, `urgent`
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

### DDSDefs.idl

Centralizes DDS configuration constants and topic names.

**QoS Configuration:**
- `DEFAULT_QOS_FILE_PATH`, `DEFAULT_PARTICIPANT_QOS`, `LARGE_DATA_PARTICIPANT_QOS`
- `ASSIGNER_QOS`, `EVENT_QOS`, `METADATA_QOS`, `STATUS_QOS`
- `LARGE_DATA_SHMEM_QOS`, `LARGE_DATA_SHMEM_ZC_QOS`
- `DEFAULT_DOMAIN_ID`

**Topic Names:**
- `COMMAND_TOPIC`, `CONFIG_TOPIC`, `POSITION_TOPIC`, `STATE_TOPIC`, `BUTTON_TOPIC`, `IMAGE_TOPIC`

Benefits: Centralized configuration, type safety, cross-language consistency.

## C++11 Utility Classes

Located in `cxx11/src/utils/`.

### DDSContextSetup.hpp

Complete DDS context management with participant lifecycle, distributed logging, and event handling.

**Features:**
- DomainParticipant management
- QoS profile integration
- Distributed logging
- AsyncWaitSet with thread pool
- Signal handling for graceful shutdown

### DDSReaderSetup.hpp & DDSWriterSetup.hpp

Template classes for reader/writer setup with status monitoring and event processing.

**Features:**
- Status condition handlers
- AsyncWaitSet integration
- Callback-based event processing
- Topic-based QoS assignment
- Simplified reader/writer creation

## QoS Configuration

Located in `qos/DDS_QOS_PROFILES.xml`.

### Domain Participant Profiles
    destination_id: str = idl.field(key=True, max_length=32)
    # ... other fields
    
# DDSDefs.py  
dds_config = idl.get_module("dds_config")
topics = idl.get_module("topics")

dds_config.DEFAULT_QOS_FILE_PATH = "../../../../dds/qos/DDS_QOS_PROFILES.xml"
topics.COMMAND_TOPIC = "Command"
```

### Code Generation Process:

1. **CMake Integration** - Automated generation via CMake
2. **rtiddsgen Tool** - RTI's IDL-to-Python compiler
3. **Dependency Tracking** - Regeneration when IDL files change
4. **Import Ready** - Generated modules ready for Python import

#### Build Commands:
```bash
cd dds/python/build
cmake ..
make -j4
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
- **LargeDataSHMEMQoS** - Large data with shared memory
- **LargeDataSHMEM_ZCQoS** - Zero-copy transfer mode

## Code Generation

### C++ Generation
```bash
cd dds/cxx11/build
cmake .. && make -j4
```
Generates: `ExampleTypes.hpp/cxx`, `FinalFlatImage.hpp/cxx`, `DDSDefs.hpp/cxx` with plugins

### Python Generation
```bash
cd dds/python/build
cmake .. && make -j4
```
Generates: `ExampleTypes.py`, `DDSDefs.py` with module structure

### Prerequisites
- **RTI Connext DDS 7.3.0+** installed and licensed
- **CMake 3.12+** for build automation
- **C++11 compiler** (GCC, Clang, MSVC)
- **Python 3.6+** with RTI Python API

### Setup Steps:

1. **Set RTI Environment**
   ```bash
   export NDDSHOME=/path/to/rti_connext_dds-7.3.0
   ```

2. **Generate C++ Code**
   ```bash
   cd dds/cxx11/build
   cmake ..
   make -j4
   ```

3. **Generate Python Code**  
   ```bash
   cd dds/python/build
   cmake ..
   make -j4
   ```

4. **Verify Generation**
   ```bash
   # Check C++ headers
   ls dds/cxx11/src/codegen/*.hpp
   
   # Check Python modules
   ls dds/python/codegen/*.py
   ```

### Usage in Applications:

#### C++ Applications:
```cpp
#include "ExampleTypes.hpp"
#include "DDSDefs.hpp"

// Use generated types
example_types::Position position;
position.latitude(40.7128);
position.longitude(-74.0060);

// Use constants
dds::topic::Topic<example_types::Position> topic(
    participant, 
    topics::POSITION_TOPIC
);
```

#### Python Applications:  
```python
from codegen.ExampleTypes import example_types
from codegen.DDSDefs import topics, dds_config

# Use generated types
position = example_types.Position()
position.latitude = 40.7128  
position.longitude = -74.0060

# Use constants
position_topic = dds.Topic(
    participant,
## Getting Started

### Build DDS Libraries

```bash
# Set environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Build C++ library
cd dds/cxx11 && mkdir -p build && cd build
cmake .. && make -j4

# Build Python library
cd ../../python && mkdir -p build && cd build
cmake .. && make -j4
```

### Use in Applications

**C++ Applications:**
```cpp
#include "ExampleTypes.hpp"
#include "DDSDefs.hpp"
#include "DDSContextSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"

auto dds_context = std::make_shared<DDSContextSetup>(domain_id, thread_pool_size, 
                                                      qos_file, qos_profile, app_name);
auto position_writer = std::make_shared<DDSWriterSetup<example_types::Position>>(
    dds_context, topics::POSITION_TOPIC, qos_file, dds_config::ASSIGNER_QOS
);
```

**Python Applications:**
```python
from codegen import example_types, dds_config, topics

writer = dds.DataWriter(
    publisher, 
    topics.POSITION_TOPIC,
    example_types.Position
)
```

## Adding New Data Types

1. Define in `datamodel/ExampleTypes.idl`
2. Add topic name to `datamodel/DDSDefs.idl`
3. Regenerate code: `cd dds/cxx11/build && make -j4`
4. Update applications to use new types

1. **Edit XML** (`qos/DDS_QOS_PROFILES.xml`)
2. **Test Changes** with existing applications
3. **Document Updates** in application README files

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