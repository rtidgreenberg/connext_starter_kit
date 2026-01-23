# Example I/O Application (Python)

Python implementation demonstrating minimal DDS middleware setup with RTI Connext.

## Table of Contents
- [Features](#features)
- [Application Behavior](#application-behavior)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Architecture](#architecture)
- [Dependencies](#dependencies)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Features

- **Command/Button/Config Publishing**: Message publishing every 2 seconds
- **Position Subscription**: Async subscriber for Position messages
- **qos_profiles.ASSIGNER Profile**: XML-based QoS configuration
- **Cross-Language Communication**: Interoperability with C++ applications
- **Distributed Logger**: RTI distributed logging for remote monitoring
- **Error Handling**: Comprehensive exception handling and graceful shutdown
- **Event-Driven**: Asyncio-based architecture

## Application Behavior

**Publishers (3 Writers)**:
- Command, Button, Config messages published every 2 seconds

**Subscriber (1 Reader)**:
- Position messages with async processing

## Quick Start

```bash
# Build DDS types (generates Python bindings)
cd /path/to/connext_starter_kit
mkdir -p build && cd build
cmake .. && cmake --build .

# Navigate to python/ directory
cd ../apps/python

# Activate environment
source connext_dds_env/bin/activate

# Run application
python example_io_app/example_io_app.py --domain_id 1
```

## Usage

**Important**: Run from `apps/python/` directory for license file access.

```bash
python example_io_app/example_io_app.py [OPTIONS]

Options:
  -d, --domain_id <int>    DDS domain ID (default: 1)
  -v, --verbosity <int>    Logging verbosity 0-5 (default: 1)
  -q, --qos_file <path>    QoS XML path (default: ../../../dds/qos/DDS_QOS_PROFILES.xml)
  -h, --help              Show help
```
[CONFIG_PUBLISHER] Published Config - Parameter: update_rate
DL Info: : Published Config - parameter:update_rate, value:1.0
[MAIN] ExampleIOApp processing loop - iteration 0
DL Info: : Example IO processing loop - iteration: 0

# When Position data is received from C++ application:
[POSITION_SUBSCRIBER] Position Received:
  Source ID: cxx_app_source
  Latitude: 40.7128
  Longitude: -74.0060
  Altitude: 10.0
  Timestamp: 1698765432
DL Info: : Received Position data - source:cxx_app_source, lat:40.7128, lon:-74.0060, alt:10.0
```

## Architecture

### Core Components
- **RTI Asyncio**: Uses `rti.asyncio.run()` for async task management with `asyncio.gather()`
- **Distributed Logger**: Integrated RTI distributed logging for remote monitoring
- **QoS Provider**: XML-based QoS profile loading with configurable file path
- **Configuration Constants**: Centralized configuration management for easy customization
- **Exception Handling**: Robust error handling and graceful shutdown with proper cleanup

### Configuration Management
The application uses centralized configuration constants:
```python
PUBLISHER_SLEEP_INTERVAL = 2        # Publishing interval (seconds)
MAIN_TASK_SLEEP_INTERVAL = 5        # Status update interval (seconds)
DEFAULT_APP_NAME = "Example Python IO App"
DEFAULT_COMMAND_DESTINATION = "target_system"
DEFAULT_CONFIG_DESTINATION = "config_target"
```

### Task Coordination
- **Publisher Task**: Publishes Command, Button, and Config messages every 2 seconds
- **Subscriber Task**: Asynchronously processes incoming Position data
- **Main Task**: Provides periodic status updates every 5 seconds
- **All tasks run concurrently** using `asyncio.gather()` for proper coordination

## Integration with C++ Application

Designed for cross-language communication with the C++ Example I/O application:
- **Python → C++**: Command, Button, Config messages published by Python, subscribed by C++
- **C++ → Python**: Position messages published by C++, subscribed by Python
- **Identical Data Types**: Both use the same IDL-generated types (ExampleTypes)
- **Shared QoS Profiles**: Both applications use the same XML QoS configuration
- **Compatible Distributed Logging**: Both applications can log to the same RTI distributed logger domain

### Cross-Platform Testing
```bash
# Terminal 1: Start C++ application
cd ../../../../apps/cxx11/example_io_app/build
./example_io_app -d 1 -v 1

# Terminal 2: Start Python application  
cd ../../../../apps/python
source connext_dds_env/bin/activate
export NDDSHOME=/path/to/rti_connext_dds-7.3.0
cd example_io_app
python example_io_app/example_io_app.py --domain_id 1 --verbosity 2
```

## Configuration & Customization

### QoS Profiles
The application loads QoS configurations from an external XML file:
- **Default Location**: `../../dds/qos/DDS_QOS_PROFILES.xml`
- **Configurable**: Use `--qos_file` argument to specify custom QoS file
- **Profiles Used**: 
  - `DPLibrary::DefaultParticipant` for DomainParticipant
  - `DataPatternsLibrary::AssignerQoS` for DataReaders and DataWriters

### Application Constants
Easy to customize via constants at the top of the file:
```python
PUBLISHER_SLEEP_INTERVAL = 2        # Adjust publishing frequency
MAIN_TASK_SLEEP_INTERVAL = 5        # Adjust status update frequency  
DEFAULT_APP_NAME = "Example Python IO App"  # Change application name
DEFAULT_COMMAND_DESTINATION = "target_system"  # Modify command targets
DEFAULT_CONFIG_DESTINATION = "config_target"   # Modify config targets
```

## Dependencies

- **RTI Connext DDS 7.3.0+** with Python API
- **Python 3.6-3.12** (RTI-compatible versions)
- **Generated Python DDS types** (ExampleTypes.py, Definitions.py)
- **QoS profile XML file** (DDS_QOS_PROFILES.xml)
- **Virtual environment** (recommended for RTI API isolation)

## Features Summary

✅ **Configurable QoS File Path** - Custom QoS profiles via command line  
✅ **Centralized Configuration** - Application constants for easy customization  
✅ **Robust Error Handling** - Proper exception handling and graceful shutdown  
✅ **Distributed Logging** - RTI distributed logger integration with detailed logging - external visibility of logs over DDS with infrastructure services or your own apps  
✅ **Cross-Language Compatible** - Works seamlessly with C++ counterpart  
✅ **Flexible Command Line** - Multiple verbosity levels and configuration options  
✅ **Production Ready** - Clean architecture with proper resource management

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!