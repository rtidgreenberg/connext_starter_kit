# Example I/O Application

Reference DDS application demonstrating how to quickly create applications using the DDSInterface and DDSContext utility classes. Shows multiple readers and a writer with integrated distributed logging.

## Purpose

This example showcases:
- **DDSInterface Utility**: Easy setup of multiple DDS readers and writers with `ASSIGNER_QOS` profiles
- **DDSContext Management**: Centralized participant and AsyncWaitSet handling with configurable thread pool (5 threads)
- **GPS Simulation Publishing**: Continuous position data publishing demonstrating location-based data patterns
- **Distributed Logger Integration**: System-wide logging accessible via RTI Admin Console with info/error levels
- **Remote Administration**: Verbosity levels can be changed remotely through DDS
- **Event-Driven Architecture**: AsyncWaitSet-based message processing with custom callback functions
- **Error Handling**: Comprehensive exception handling for DDS operations

## Application Behavior

- **Multiple Subscribers**: Command, Button, and Config message readers using AsyncWaitSet with `ASSIGNER_QOS` profile
- **Single Publisher**: Position message writer publishing GPS coordinates every 500ms
  - **Position Publishing**: GPS coordinates (latitude: 37.7749, longitude: -122.4194, altitude: 15m) simulating San Francisco location
- **Error Handling**: Robust exception handling for publishing operations with distributed logger integration
- **Distributed Logging**: Comprehensive status messages sent to RTI distributed logger with info/error levels
- **Remote Monitoring**: Log messages viewable in RTI Admin Console for system-wide visibility

## DDS Interfaces Overview

| Interface Type | Data Type | Topic Name | Processing Method | Description |
|----------------|-----------|------------|-------------------|-------------|
| **Reader** | `example_types::Command` | `Command` | AsyncWaitSet (`process_command_data`) | Receives command messages for application control |
| **Reader** | `example_types::Button` | `Button` | AsyncWaitSet (`process_button_data`) | Processes button input events and state changes |
| **Reader** | `example_types::Config` | `Config` | AsyncWaitSet (`process_config_data`) | Handles configuration parameter updates |
| **Writer** | `example_types::Position` | `Position` | Direct Publishing (500ms) | Publishes GPS coordinates and location data |

All interfaces use the `dds_config::ASSIGNER_QOS` profile (`DataPatternsLibrary::AssignerQoS`) for flexible XML-based QoS configuration per topic.

## Quick Start

```bash
# Set RTI Connext DDS environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# 1. Build DDS utility library
cd ../../../dds/cxx11 && rm -rf build && mkdir build && cd build
cmake .. && make -j4

# 2. Build example application  
cd ../../../apps/cxx11/example_io_app && rm -rf build && mkdir build && cd build
cmake .. && make -j4

# 3. Run with default QoS profiles
./example_io_app
```

## Usage

```bash
./example_io_app [OPTIONS]

Options:
  -d, --domain <int>    Domain ID (default: 1)
  -v, --verbosity <int> RTI verbosity 0-3 (default: 1)  
  -q, --qos-file <str>  QoS profile XML path (default: ../../../../dds/qos/DDS_QOS_PROFILES.xml)
  -h, --help           Show help
```

## Example

```bash
# Run with QoS profiles (recommended)
./example_io_app --qos-file ../../../../dds/qos/DDS_QOS_PROFILES.xml

# Run on different domain with custom verbosity
./example_io_app -d 42 -v 2

# Monitor output showing GPS coordinates
[POSITION] Published ID: Example CXX IO APP, Lat: 37.7749, Lon: -122.419, Alt: 15m
```

## Utility Classes Demonstrated

**DDSContext**: 
- Manages DomainParticipant lifecycle and QoS profiles
- Provides centralized AsyncWaitSet with thread pool
- Integrates RTI distributed logger with domain-specific configuration

**DDSInterface**: 
- Simplifies DataReader/DataWriter creation with consistent error handling and custom QoS profile usage
- Supports both polling and AsyncWaitSet-based event processing with custom callback functions
- Handles QoS profile application, topic management, and proper exception propagation

## QoS Profile Configuration

**ASSIGNER_QOS Profile**:
The application uses the `dds_config::ASSIGNER_QOS` profile (`DataPatternsLibrary::AssignerQoS`), which enables flexible external QoS assignment through XML configuration. This approach provides several benefits:

- **Topic-Specific Configuration**: QoS settings can be assigned per topic name in the XML profile file
- **Runtime Flexibility**: Different topics can have different QoS policies without code changes
- **External Management**: System administrators can tune QoS settings by modifying the XML file without recompiling
- **Scalable Architecture**: New topics can be added with appropriate QoS settings purely through configuration

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

auto dds_context = std::make_shared<DDSContext>(domain_id, ASYNC_WAITSET_THREADPOOL_SIZE, 
                                               qos_file_path, qos_profile, APP_NAME);

// Create multiple readers with ASSIGNER_QOS profile  
auto command_interface = std::make_shared<DDSInterface<example_types::Command>>(
    dds_context, KIND::READER, topics::COMMAND_TOPIC, qos_file_path, dds_config::ASSIGNER_QOS);

// Create position writer for GPS data publishing
auto position_interface = std::make_shared<DDSInterface<example_types::Position>>(
    dds_context, KIND::WRITER, topics::POSITION_TOPIC, qos_file_path, dds_config::ASSIGNER_QOS);

// Enable async processing with custom callbacks
command_interface->enable_async_waitset(process_command_data);

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
    position_interface->writer().write(pos_msg);
} catch (const std::exception &ex) {
    logger.error("Failed to publish position: " + std::string(ex.what()));
}
```

## Application Lifecycle

The application includes proper initialization and cleanup:
- **Startup**: Creates DDSContext with thread pool, initializes all interfaces
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