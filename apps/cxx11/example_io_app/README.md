# Example I/O Application

Reference DDS application demonstrating how to quickly create applications using the DDSInterface and DDSContext utility classes. Shows multiple readers and a writer with integrated distributed logging.

## Purpose

This example showcases:
- **DDSInterface Utility**: Easy setup of multiple DDS readers and writers
- **DDSContext Management**: Centralized participant and AsyncWaitSet handling  
- **Distributed Logger Integration**: System-wide logging accessible via RTI Admin Console
- **Remote Administration**: Verbosity levels can be changed remotely through DDS
- **Event-Driven Architecture**: AsyncWaitSet-based message processing

## Application Behavior

- **Multiple Subscribers**: Command, Button, and Config message readers using AsyncWaitSet
- **Single Publisher**: Position message writer with GPS simulation
- **Distributed Logging**: Status messages sent to RTI distributed logger
- **Remote Monitoring**: Log messages viewable in RTI Admin Console

## Quick Start

```bash
# 1. Build DDS utility library
cd ../../../dds/cxx11/build && make

# 2. Build example application  
cd - && mkdir -p build && cd build
cmake .. && make

# 3. Run with distributed logging
./example_io_app --qos-file ../../../../dds/qos/DDS_QOS_PROFILES.xml
```

## Usage

```bash
./example_io_app [OPTIONS]

Options:
  -d, --domain <int>    Domain ID (default: 1)
  -v, --verbosity <int> RTI verbosity 0-3 (default: 1)
  -q, --qos-file <str>  QoS profile XML path
  -h, --help           Show help
```

## Example

```bash
# Run with QoS profiles
./example_io_app --qos-file ../../../../dds/qos/DDS_QOS_PROFILES.xml

# Run on different domain
./example_io_app -d 42
```

## Utility Classes Demonstrated

**DDSContext**: 
- Manages DomainParticipant lifecycle and QoS profiles
- Provides centralized AsyncWaitSet with thread pool
- Integrates RTI distributed logger with domain-specific configuration

**DDSInterface**: 
- Simplifies DataReader/DataWriter creation with consistent error handling
- Supports both polling and AsyncWaitSet-based event processing
- Handles QoS profile application and topic management

## Remote Administration

- **RTI Admin Console**: View distributed log messages in real-time
- **Remote Verbosity Control**: Change logging levels without restart
- **System-wide Visibility**: All applications using distributed logger appear in console
- **Centralized Monitoring**: Track application status across the DDS domain

## Integration Example

```cpp
// Create context with distributed logging
auto dds_context = std::make_shared<DDSContext>(domain_id, thread_pool_size, 
                                               qos_file, qos_profile, app_name);

// Create multiple readers easily
auto cmd_interface = std::make_shared<DDSInterface<Command>>(
    dds_context, KIND::READER, topics::COMMAND_TOPIC, qos_file, qos_profile);

// Enable async processing
cmd_interface->enable_async_waitset(process_command_data);

// Use distributed logger
auto& logger = dds_context->distributed_logger();
logger.info("Application started");
```

## Dependencies

- RTI Connext DDS 7.3.0+ with distributed logger
- C++14 compiler  
- DDS utility library (DDSContext, DDSInterface classes)