# Example I/O Application

Reference DDS application demonstrating DDSReaderSetup, DDSWriterSetup, and DDSContextSetup utility classes with multiple readers, a writer, and distributed logging.

## Table of Contents
- [Features](#features)
- [Application Behavior](#application-behavior)
- [DDS Interfaces](#dds-interfaces)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Utility Classes](#utility-classes)
- [Integration Example](#integration-example)
- [Application Lifecycle](#application-lifecycle)
- [Dependencies](#dependencies)

## Features

- **Reader/Writer Setup**: Easy DDS entity creation with `ASSIGNER_QOS` profiles
- **DDSContextSetup Management**: Centralized participant and AsyncWaitSet handling (Default 5-thread pool)
- **GPS Simulation**: Continuous position data publishing at 500ms intervals
- **Distributed Logger**: System-wide logging via RTI Admin Console with remote verbosity control
- **Event-Driven**: AsyncWaitSet-based message processing with custom callbacks
- **Error Handling**: Comprehensive exception handling

## Application Behavior

- **Subscribers**: Command, Button, Config readers (AsyncWaitSet with `ASSIGNER_QOS`)
- **Publisher**: Position data (GPS coordinates: 37.7749, -122.4194, 15m altitude) every 500ms
- **Distributed Logging**: Info/error messages viewable in RTI Admin Console

## DDS Interfaces

| Type | Data Type | Topic | Processing | Description |
|------|-----------|-------|------------|-------------|
| **Reader** | `example_types::Command` | `Command` | AsyncWaitSet | Command messages for control |
| **Reader** | `example_types::Button` | `Button` | AsyncWaitSet | Button input events |
| **Reader** | `example_types::Config` | `Config` | AsyncWaitSet | Configuration updates |
| **Writer** | `example_types::Position` | `Position` | 500ms intervals | GPS location data |

All interfaces use `dds_config::ASSIGNER_QOS` profile for runtime XML-based QoS re-assignment.

## Quick Start

```bash
# Set environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Build DDS library
cd ../../../dds/cxx11 && mkdir -p build && cd build && cmake .. && make -j4

# Build application
cd ../../../apps/cxx11/example_io_app && mkdir -p build && cd build
cmake .. && make -j4

# Run
./example_io_app
```

## Usage

```bash
./example_io_app [OPTIONS]

Options:
  -d, --domain <int>    Domain ID (default: 1)
  -v, --verbosity <int> RTI verbosity 0-3 (default: 1)
  -q, --qos-file <str>  QoS XML path (default: ../../../../dds/qos/DDS_QOS_PROFILES.xml)
  -h, --help           Show help
```

## Utility Classes

**DDSContextSetup**: 
- Manages DomainParticipant lifecycle and QoS profiles
- Centralized AsyncWaitSet with thread pool
- Integrates RTI distributed logger

**DDSReaderSetup / DDSWriterSetup**: 
- Simplifies DataReader/DataWriter creation
- Supports AsyncWaitSet event processing with callbacks
- Handles QoS profiles, status monitoring, and error propagation

## QoS Configuration

Uses `dds_config::ASSIGNER_QOS` profile enabling:
- **Topic-Specific QoS**: Settings assigned per topic in XML
- **Runtime Flexibility**: Different QoS policies without code changes
- **External Management**: Tune settings via XML without recompiling
- **Scalable Architecture**: Add topics with QoS via configuration

Example XML structure for topic-specific QoS assignment:
```xml
<qos_profile name="AssignerQoS">
    <datareader_qos topic_filter="Command">
        <!-- Command-specific QoS settings -->
    </datareader_qos>
    <datawriter_qos topic_filter="Position">
        <!-- Position-specific QoS settings -->
    </datawriter_qos>
</qos_profile>
```

This pattern allows the same application code to work with different QoS requirements by simply updating the XML configuration file.

## Remote Administration

- **RTI Admin Console**: View distributed log messages in real-time
- **Remote Verbosity Control**: Change logging levels without restart
- **System-wide Visibility**: All applications using distributed logger appear in console
- **Centralized Monitoring**: Track application status across the DDS domain

## Integration Example

```cpp
// Create context with distributed logging and async waitset
const std::string qos_profile = dds_config::DEFAULT_PARTICIPANT_QOS;
const std::string APP_NAME = "Example CXX IO APP";
constexpr int ASYNC_WAITSET_THREADPOOL_SIZE = 5;

auto dds_context = std::make_shared<DDSContextSetup>(domain_id, ASYNC_WAITSET_THREADPOOL_SIZE, 
                                               qos_file_path, qos_profile, APP_NAME);

// Create multiple readers with ASSIGNER_QOS profile  
auto command_reader = std::make_shared<DDSReaderSetup<example_types::Command>>(
    dds_context, topics::COMMAND_TOPIC, qos_file_path, dds_config::ASSIGNER_QOS);

// Create position writer for GPS data publishing
auto position_writer = std::make_shared<DDSWriterSetup<example_types::Position>>(
    dds_context, topics::POSITION_TOPIC, qos_file_path, dds_config::ASSIGNER_QOS);

// Enable async processing with custom callbacks
command_reader->set_data_handler(process_command_data);
command_reader->enable_async();

// Use distributed logger with error handling
auto& logger = dds_context->distributed_logger();
logger.info("Example I/O app is running. Press Ctrl+C to stop.");

// Publish position data with error handling
example_types::Position pos_msg;
pos_msg.source_id(APP_NAME);
try {
    pos_msg.latitude(37.7749);
    pos_msg.longitude(-122.4194);
    pos_msg.altitude(15.0);
    position_writer->writer().write(pos_msg);
} catch (const std::exception &ex) {
    logger.error("Failed to publish position: " + std::string(ex.what()));
}
```

## Application Lifecycle

The application includes proper initialization and cleanup:
- **Startup**: Creates DDSContextSetup with thread pool, initializes all interfaces
- **Runtime**: Publishes Position messages every 500ms while listening for incoming data
- **Shutdown**: Graceful signal handling (Ctrl+C), distributed logger cleanup, DomainParticipant factory finalization

## Dependencies

- RTI Connext DDS 7.3.0+ with distributed logger
- C++14 compiler (tested with GCC 9.4.0)
- CMake 3.12+ for build configuration
- DDS utility library (`libdds_utils_datamodel.so`) built from `../../../dds/cxx11/`
- Generated C++ bindings:
  - `ExampleTypes.hpp/cpp` - Data type definitions
  - `DDSDefs.hpp/cpp` - Configuration constants and topic names
- QoS profiles XML file: `../../../../dds/qos/DDS_QOS_PROFILES.xml`

## Build Process

The application automatically links against the shared DDS utility library and includes the generated codegen headers:

```cmake
# CMakeLists.txt automatically finds:
# - DDS shared library: /path/to/dds/cxx11/build/lib/libdds_utils_datamodel.so  
# - DDS codegen headers: /path/to/dds/cxx11/src/codegen
# - DDS utils headers: /path/to/dds/cxx11/src/utils
```