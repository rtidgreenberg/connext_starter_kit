# DDS Layer Documentation

This directory contains the Data Distribution Service (DDS) layer components for the RTI Connext Starter Kit, providing data models, utility classes, and generated code for cross-language DDS communication.

## Directory Structure

```
dds/
├── README.md               # This file - DDS layer documentation
├── datamodel/              # IDL definitions for data types
│   ├── ExampleTypes.idl    # Main example data structures  
│   └── DDSDefs.idl         # DDS configuration constants and topic names
├── qos/                    # Quality of Service configurations
│   └── DDS_QOS_PROFILES.xml # QoS profiles for all applications
├── cxx11/                  # C++11 DDS utilities and generated code
│   ├── src/
│   │   ├── utils/          # C++ utility classes
│   │   └── codegen/        # Generated C++ types from IDL
│   └── build/              # CMake build output
└── python/                 # Python DDS generated code
    ├── codegen/            # Generated Python types from IDL
    └── build/              # CMake build output
```

---

## 📊 Data Model (IDL Definitions)

### ExampleTypes.idl

Defines the core data structures used across all applications in the starter kit. These types demonstrate common DDS patterns and real-world use cases.

#### Data Types Included:

##### **Command** - Control Messages
```idl
struct Command {
    @key string<32> command_id;        // Unique command identifier
    @key string<32> destination_id;    // Target system identifier  
    CommandType command_type;          // START, STOP, PAUSE, RESET, SHUTDOWN
    string<128> message;               // Command description
    unsigned long timestamp_sec;      // Command timestamp
    boolean urgent;                   // Priority flag
};
```

##### **Position** - Location Data
```idl  
struct Position {
    @key string<32> source_id;        // GPS/location source identifier
    double latitude;                  // Latitude in degrees
    double longitude;                 // Longitude in degrees  
    double altitude;                  // Altitude in meters
    unsigned long timestamp_sec;     // Position timestamp
};
```

##### **Button** - User Input Events
```idl
struct Button {
    @key string<32> source_id;        // Input device identifier
    @key string<32> button_id;        // Specific button identifier
    ButtonState button_state;         // PRESSED, RELEASED, HELD, DOUBLE_CLICK
    unsigned long press_count;        // Total press count
    unsigned long last_press_timestamp_sec; // Last press time
    double hold_duration_sec;         // Hold duration for held buttons
};
```

##### **Config** - Configuration Parameters
```idl
struct Config {
    @key string<32> destination_id;   // Configuration target
    string<64> parameter_name;        // Parameter identifier
    string<128> parameter_value;      // String parameter value
    double numeric_value;             // Numeric parameter value
    boolean enabled;                  // Enable/disable flag
};
```

##### **State** - System Status
```idl
struct State {
    @key string<32> source_id;        // System/component identifier
    SystemState state_value;          // INIT, RUNNING, ERROR, RESTARTING, SHUTTING_DOWN
    string<128> error_message;        // Status description or error details
};
```

##### **Image** - Media Data
```idl
struct Image {
    @key string<32> image_id;         // Image identifier
    unsigned long width;              // Image width in pixels
    unsigned long height;             // Image height in pixels
    string<64> format;                // Image format (RGB, JPEG, etc.)
    sequence<octet, 1024> data;       // Image data bytes
};
```

#### Design Features:
- **@key annotations** for topic instance identification
- **Bounded strings** for deterministic memory usage
- **Enumerations** for type safety (CommandType, ButtonState, SystemState)
- **Mixed data types** (strings, numbers, booleans, sequences)
- **Real-world semantics** suitable for IoT, robotics, and distributed systems

### DDSDefs.idl

Centralizes DDS configuration constants and topic names for consistent usage across all applications.

#### QoS Configuration Constants:
```idl
module dds_config {
    // QoS file location
    const string DEFAULT_QOS_FILE_PATH = "../../../../dds/qos/DDS_QOS_PROFILES.xml";
    
    // Domain Participant Profiles
    const string DEFAULT_PARTICIPANT_QOS = "DPLibrary::DefaultParticipant";
    const string IMAGE_PARTICIPANT_QOS = "DPLibrary::ImageParticipant";
    
    // DataWriter/DataReader Profiles  
    const string ASSIGNER_QOS = "DataPatternsLibrary::AssignerQoS";
    const string EVENT_QOS = "DataPatternsLibrary::EventQoS";
    const string METADATA_QOS = "DataPatternsLibrary::MetadataQoS";
    const string STATUS_QOS = "DataPatternsLibrary::StatusQoS";
    const string LARGE_DATA_QOS = "DataPatternsLibrary::LargeDataQoS";
    
    // Default Domain ID
    const long DEFAULT_DOMAIN_ID = 1;
};
```

#### Topic Name Constants:
```idl
module topics {
    const string COMMAND_TOPIC = "Command";
    const string CONFIG_TOPIC = "Config";  
    const string POSITION_TOPIC = "Position";
    const string STATE_TOPIC = "State";
    const string BUTTON_TOPIC = "Button";
    const string IMAGE_TOPIC = "Image";
};
```

**Benefits:**
- ✅ **Centralized configuration** - Single source of truth for DDS settings
- ✅ **Type safety** - Constants prevent string typos in topic names
- ✅ **Cross-language consistency** - Same constants available in C++ and Python
- ✅ **Easy maintenance** - Change QoS profiles or topic names in one place

---

## 🔧 C++11 Utility Classes

Located in `cxx11/src/utils/`, these classes provide high-level abstractions for DDS operations.

### DDSContext.hpp

**Purpose:** Complete DDS context management with participant lifecycle, distributed logging, and event handling.

#### Key Features:
- **DomainParticipant Management** - Automatic creation, configuration, and cleanup
- **QoS Profile Integration** - Loads QoS from external XML files  
- **Domain Configuration** - DomainParticipant with QoS profiles
- **Distributed Logging** - RTI distributed logger setup and management - external visibility of logs over DDS with infrastructure services or your own apps
- **AsyncWaitSet Management** - Thread pool for event-driven processing
- **Event Handling** - Participant listeners for DDS events
- **Signal Handling** - Graceful shutdown on SIGINT/SIGTERM
- **Thread Safety** - Mutex-protected operations for multi-threading

#### Core Components:
```cpp
class MyParticipantListener : public dds::domain::NoOpDomainParticipantListener {
    // Handles DDS events: deadline missed, incompatible QoS, etc.
};

class DDSContext {
    // Main context class for DDS operations
    // Manages participant, QoS, logging, and cleanup
};
```

#### Usage Pattern:
```cpp
// Create context with domain ID and QoS file
DDSContext context(domain_id, qos_file_path);

// Context automatically handles:
// - DomainParticipant creation
// - QoS profile loading  
// - Distributed logger setup
// - Signal handlers for clean shutdown
```

### DDSInterface.hpp  

**Purpose:** Generic interface for creating and managing DDS DataReaders and DataWriters with topic-based QoS assignment.

#### Key Features:
- **Template-based Design** - Works with any DDS data type
- **Topic-based QoS** - Automatic QoS assignment using `set_topic_*_qos()` methods
- **Writer/Reader Factory** - Simplified creation of DDS entities
- **Resource Management** - Automatic cleanup and lifecycle management
- **Event Callbacks** - Configurable callbacks for data events

#### Core Abstractions:
```cpp
enum class KIND {
    WRITER,     // DataWriter - publishes data
    READER      // DataReader - subscribes to data  
};

template<typename T>
class DDSInterface {
    // Generic interface for DDS operations
    // Handles both DataWriters and DataReaders
};
```

#### Usage Examples:
```cpp
// Create a Position data writer
auto position_writer = DDSInterface<Position>::create(
    context, 
    topics::POSITION_TOPIC,
    dds_config::ASSIGNER_QOS,
    KIND::WRITER
);

// Create a Command data reader  
auto command_reader = DDSInterface<Command>::create(
    context,
    topics::COMMAND_TOPIC, 
    dds_config::ASSIGNER_QOS,
    KIND::READER
);
```

#### Benefits:
- ✅ **Type Safety** - Template-based approach prevents type mismatches
- ✅ **QoS Automation** - Automatic topic-based QoS assignment
- ✅ **Code Reuse** - Same interface for all data types
- ✅ **Error Handling** - Built-in validation and error reporting

---

## 🐍 Python Code Generation

Located in `python/codegen/`, contains auto-generated Python modules from IDL definitions.

### Generated Files:

#### **ExampleTypes.py**
- **Python classes** for all IDL data structures (Command, Position, Button, etc.)
- **Enum mappings** for CommandType, ButtonState, SystemState
- **Type annotations** and dataclass decorators
- **RTI-specific decorators** (@key, field constraints)

#### **DDSDefs.py**  
- **Configuration constants** translated to Python modules
- **Topic name constants** as string literals
- **QoS profile names** for use with QosProvider
- **Default values** for domain IDs and file paths

#### **Generated Structure:**
```python
# ExampleTypes.py
example_types = idl.get_module("example_types")

@idl.struct  
class example_types_Command:
    command_id: str = idl.field(key=True, max_length=32)
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
```

---

## 📋 QoS Configuration

Located in `qos/DDS_QOS_PROFILES.xml`, defines Quality of Service profiles used by all applications.

### Profile Categories:

#### **Domain Participant Profiles** (`DPLibrary`)
- **DefaultParticipant** - General-purpose participant configuration
  - Discovery optimizations for fast endpoint detection
  - Transport settings for UDP and shared memory
  - Socket buffer optimizations for high throughput
  
- **ImageParticipant** - Optimized for large data (images, media)
  - Enhanced transport settings for large messages
  - Shared memory configuration for local communication

#### **DataWriter/DataReader Profiles** (`DataPatternsLibrary`)
- **AssignerQoS** - Topic-based QoS assignment pattern
- **EventQoS** - Event-driven communication patterns  
- **MetadataQoS** - Metadata and configuration data
- **StatusQoS** - Status and health monitoring
- **LargeDataQoS** - Large data transfer optimization

### Usage in Applications:
```cpp
// C++ - Load QoS provider
dds::core::QosProvider qos_provider(qos_file_path);

// Apply participant QoS
auto participant_qos = qos_provider.participant_qos(
    dds_config::DEFAULT_PARTICIPANT_QOS
);

// Apply topic-based writer QoS
auto writer_qos = qos_provider.set_topic_datawriter_qos(
    dds_config::ASSIGNER_QOS, 
    topics::POSITION_TOPIC
);
```

```python  
# Python - Load QoS provider
qos_provider = dds.QosProvider(qos_file_path)

# Apply participant QoS
participant_qos = qos_provider.participant_qos_from_profile(
    dds_config.DEFAULT_PARTICIPANT_QOS
)

# Apply topic-based reader QoS  
reader_qos = qos_provider.set_topic_datareader_qos(
    dds_config.ASSIGNER_QOS,
    topics.COMMAND_TOPIC
)
```

---

## 🔄 Code Generation Workflow

### Overview
The DDS layer uses RTI Code Generator (`rtiddsgen`) to automatically generate type-safe code from IDL definitions.

### Generation Process:

1. **IDL Sources** (`datamodel/`)
   - ExampleTypes.idl → Data type definitions
   - DDSDefs.idl → Configuration constants

2. **C++ Generation** (`cxx11/`)
   ```bash
   cd dds/cxx11/build  
   cmake ..
   make -j4
   ```
   - Generates: ExampleTypes.hpp/cxx, DDSDefs.hpp/cxx
   - Includes: Plugin files for DDS middleware

3. **Python Generation** (`python/`)
   ```bash
   cd dds/python/build
   cmake ..  
   make -j4
   ```
   - Generates: ExampleTypes.py, DDSDefs.py
   - Includes: __init__.py for module structure

### Benefits:
- ✅ **Type Safety** - Compile-time type checking
- ✅ **Cross-Language Consistency** - Identical types in C++ and Python
- ✅ **Automatic Updates** - Regeneration when IDL changes
- ✅ **DDS Integration** - Native DDS serialization support

---

## 🚀 Getting Started

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
    topics.POSITION_TOPIC, 
    example_types.Position
)
```

---

## 📚 Integration with Applications

The DDS layer is designed to support multiple application types and languages:

### **C++ Applications** (`../apps/cxx11/`)
- Include generated headers from `cxx11/src/codegen/`
- Use utility classes from `cxx11/src/utils/`  
- Link against RTI Connext C++ libraries

### **Python Applications** (`../apps/python/`)
- Import generated modules from `python/codegen/`
- Use RTI Connext Python API
- Access same QoS profiles and topic names

### **Cross-Language Communication**
- **Identical Data Types** - Same IDL generates compatible types
- **Shared QoS Profiles** - Both languages use same XML configuration  
- **Consistent Topic Names** - Constants prevent naming mismatches
- **Interoperable Wire Protocol** - RTI DDS ensures compatibility

---

## 🔍 Advanced Features

### Topic-Based QoS Assignment
The DDS layer implements RTI's recommended pattern for QoS management:

```cpp
// Instead of hardcoding QoS per entity type:
auto writer_qos = qos_provider.datawriter_qos("SomeProfile");

// Use topic-based assignment for flexibility:
auto writer_qos = qos_provider.set_topic_datawriter_qos(
    "AssignerProfile",
    "SpecificTopicName"  
);
```

This allows different QoS settings per topic while using the same profile base.

### Distributed Logging Integration  
All utility classes integrate with RTI Distributed Logger:

- **Centralized Logging** - All applications log to same domain
- **Remote Monitoring** - View logs via RTI Admin Console
- **Event Correlation** - Track events across applications
- **Debug Support** - Detailed DDS internal logging available

### Signal Handling
The C++ utilities provide graceful shutdown:

```cpp
// Automatic registration in DDSContext
std::signal(SIGINT, signal_handler);
std::signal(SIGTERM, signal_handler);

// Clean shutdown sequence:
// 1. Stop async operations
// 2. Delete DDS entities  
// 3. Finalize distributed logger
// 4. Exit cleanly
```

---

## 🛠️ Maintenance & Development

### Adding New Data Types:

1. **Define in IDL** (`datamodel/ExampleTypes.idl`)
   ```idl
   struct NewType {
       @key string<32> id;
       // ... fields
   };
   ```

2. **Add Topic Name** (`datamodel/DDSDefs.idl`)
   ```idl
   const string NEW_TYPE_TOPIC = "NewType";
   ```

3. **Regenerate Code**
   ```bash
   # C++
   cd dds/cxx11/build && make -j4
   
   # Python  
   cd dds/python/build && make -j4
   ```

4. **Update Applications** to use new types

### Modifying QoS Profiles:

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