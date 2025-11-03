# Example I/O Application (Python)

Python implementation of the Example I/O application following the pose_app.py structure as a reference example for middleware setup.

## Purpose

This Python application demonstrates minimal DDS middleware setup:
- **Command/Button/Config Publishing**: Basic message publishing every 2 seconds
- **Position Data Subscription**: Simple async subscriber for Position messages
- **ASSIGNER_QOS Profile**: Uses XML-based QoS configuration
- **Cross-Language Communication**: Seamless interoperability with C++ applications
- **Configuration Management**: External QoS profiles and runtime configuration constants
- **Distributed Logger**: Integrated RTI distributed logging for remote monitoring - external visibility of logs over DDS with infrastructure services or your own apps
- **Error Handling**: Comprehensive exception handling and graceful shutdown
- **Real-time Data Processing**: Event-driven architecture with asyncio
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

# 2. Navigate to python/ directory (contains RTI license file)
cd ../../../apps/python

# 3. Activate virtual environment
source connext_dds_env/bin/activate

# 4. Run the Python application from python/ directory
python example_io_app/example_io_app.py --domain_id 1

# 5. Run with higher verbosity
python example_io_app/example_io_app.py --domain_id 1 --verbosity 2
```

## Usage

**Important**: 
- Run from `apps/python/` directory to ensure RTI license file (`rti_license.dat`) is accessible
- The license file must be present in the current working directory for Python DDS applications

```bash
# From apps/python/ directory:
python example_io_app/example_io_app.py [OPTIONS]

Options:
  -d, --domain_id <int>    DDS domain ID (default: 1)
  -v, --verbosity <int>    Logging verbosity 0-5 (default: 1)
  -q, --qos_file <path>    Path to QoS profiles XML file (default: ../../dds/qos/DDS_QOS_PROFILES.xml)
  -h, --help              Show help message
```

### Verbosity Levels
- **0**: SILENT - No DDS internal logging
- **1**: EXCEPTION - Only exception messages (default)
- **2**: WARNING - Warnings and exceptions  
- **3**: STATUS_LOCAL - Local status information
- **4**: STATUS_REMOTE - Remote participant status
- **5**: STATUS_ALL - Complete DDS status information

### Usage Examples
```bash
# From apps/python/ directory:

# Run with default settings
python example_io_app/example_io_app.py

# Run on custom domain with custom QoS file  
python example_io_app/example_io_app.py --domain_id 5 --qos_file /path/to/custom/qos.xml

# Run with maximum verbosity for debugging
python example_io_app/example_io_app.py --domain_id 1 --verbosity 5
```

## Example Output

```bash
Loading QoS profiles from: ../../dds/qos/DDS_QOS_PROFILES.xml
DomainParticipant created with QoS profile: DPLibrary::DefaultParticipant
DOMAIN ID: 1
RTI Distributed Logger configured for domain 1 with application kind: Example Python IO App
DL Info: : ExampleIOApp initialized with distributed logging enabled
[SUBSCRIBER] RTI Asyncio reader configured for Position data...
[PUBLISHER] RTI Asyncio writers configured for Command, Button, and Config data...
[MAIN] Starting RTI asyncio tasks...
[COMMAND_PUBLISHER] Published Command - ID: cmd_0000
DL Info: : Published Command - id:cmd_0000, type:0
[BUTTON_PUBLISHER] Published Button - ID: btn_1, Count: 0
DL Info: : Published Button - id:btn_1, state:1, count:0
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
- **Generated Python DDS types** (ExampleTypes.py, DDSDefs.py)
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