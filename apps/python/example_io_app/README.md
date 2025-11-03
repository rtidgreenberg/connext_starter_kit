# Example I/O Application (Python)

Python implementation of the Example I/O application following the pose_app.py structure as a reference example for middleware setup.

## Purpose

This Python application demonstrates minimal DDS middleware setup:
- **Command/Button/Config Publishing**: Basic message publishing every 2 seconds
- **Position Data Subscription**: Simple async subscriber for Position messages
- **ASSIGNER_QOS Profile**: Uses XML-based QoS configuration
- **Distributed Logging**: RTI distributed logger integration
- **Minimal Application Code**: Focus on middleware setup, not application logic

## Application Behavior

**Publishers (3 Writers)**:
- **Command Messages**: Published every 2 seconds with basic command data
- **Button Messages**: Published every 2 seconds with simple button press simulation
- **Config Messages**: Published every 2 seconds with basic configuration parameter

**Subscriber (1 Reader)**:
- **Position Messages**: Async processing of incoming GPS coordinates

## Quick Start

```bash
# 1. Ensure DDS Python bindings are generated
cd ../../../dds/python/build && make

# 2. Run the Python application
cd - && python example_io_app.py --domain_id 1

# 3. Run with higher verbosity
python example_io_app.py --domain_id 1 --verbosity 2
```

## Usage

```bash
python example_io_app.py [OPTIONS]

Options:
  -d, --domain_id <int>    DDS domain ID (default: 1)
  -v, --verbosity <int>    Logging verbosity 0-5 (default: 1)
  -h, --help              Show help message
```

## Example Output

```bash
DomainParticipant created with QoS profile: DPLibrary::DefaultParticipant
DOMAIN ID: 1
RTI Distributed Logger configured for domain 1 with application kind: Example IO Python App-DistLogger
[SUBSCRIBER] RTI Asyncio reader configured for Position data...
[PUBLISHER] RTI Asyncio writers configured for Command, Button, and Config data...
[MAIN] Starting RTI asyncio tasks...
[COMMAND_PUBLISHER] Published Command - ID: cmd_0000
[BUTTON_PUBLISHER] Published Button - ID: btn_1, Count: 0
[CONFIG_PUBLISHER] Published Config - Parameter: update_rate
[MAIN] ExampleIOApp processing loop - iteration 0
```

## Architecture

Following the pose_app.py structure:
- **RTI Asyncio**: Uses `rti.asyncio.run()` for async task management
- **Distributed Logger**: Integrated RTI distributed logging
- **QoS Provider**: XML-based QoS profile loading
- **Minimal Logic**: Simple message creation and publishing
- **Exception Handling**: Basic error handling and graceful shutdown

## Integration with C++ Application

Complements the C++ Example I/O application:
- Python publishes Command/Button/Config → C++ subscribes
- C++ publishes Position → Python subscribes  
- Both use identical IDL types and QoS profiles

## Dependencies

- RTI Connext DDS 7.3.0+ with Python API
- Python 3.6+
- Generated Python DDS types (ExampleTypes.py, DDSDefs.py)
- QoS profile XML file (DDS_QOS_PROFILES.xml)