# Python DDS Applications

Python applications demonstrating RTI Connext DDS capabilities with example data types.

## Table of Contents
- [Application Structure](#application-structure)
- [Current Applications](#current-applications)
- [Setup](#setup)
- [Installation](#installation)
- [Running Applications](#running-applications)
- [Building DDS Python Bindings](#building-dds-python-bindings)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Application Structure

```
apps/python/
├── example_io_app/         # Example I/O application
│   ├── example_io_app.py   # Main application
│   ├── requirements.txt    # App dependencies
│   └── README.md           # Documentation
├── connext_dds_env/        # Virtual environment
├── README.md               # This file
├── install.sh              # Installation script
├── requirements.txt        # Common dependencies
├── rti_license.dat         # RTI license (REQUIRED)
└── setup.py                # Setup script
```

## Current Applications

### example_io_app

- **Subscribes to:** Position messages
- **Publishes:** Command, Button, Config messages
- **Features:**
  - RTI asyncio framework integration
  - qos_profiles.ASSIGNER profile usage
  - Distributed logger integration
  - Cross-language communication with C++ apps

## Setup

### Prerequisites
- RTI Connext DDS Python API
- Python 3.8+
- Built DDS Python libraries (`../../dds/python/build/`)
- **RTI license file (`rti_license.dat`) in `apps/python/` directory**

> **Important**: Run applications from `apps/python/` directory to ensure license file is accessible.

### Installation

```bash
# Navigate to python apps directory
cd /home/rti/connext_starter_kit/apps/python

# Activate virtual environment
source connext_dds_env/bin/activate

# Set NDDSHOME
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"

# Run installation (installs RTI API and generates DDS bindings)
./install.sh
```

### Run Application

```bash
cd example_io_app
python3 example_io_app.py --domain_id 1 --verbosity 2
```

## Development

### Adding New Applications

1. **Create directory:**
   ```bash
   mkdir apps/python/your_app_name/
   ```

2. **Structure:**
   ```
   your_app_name/
   ├── your_app_name.py
   ├── requirements.txt (optional)
   └── README.md
   ```

3. **Template**: Copy from `example_io_app/example_io_app.py`

- **Directory Names:** Use lowercase with underscores (e.g., `sensor_fusion`, `navigation_control`)
- **Main Files:** Use `{app_name}.py` (e.g., `example_io_app.py`, `sensor_fusion.py`)
- **Class Names:** Use PascalCase ending with "App" (e.g., `ExampleIOApp`, `SensorFusionApp`)

## QoS Configuration

All Python applications use shared QoS profiles from `../../dds/qos/DDS_QOS_PROFILES.xml`:

- **DomainParticipant:** `DPLibrary::DefaultParticipant`
- **DataWriter/DataReader:** `DataPatternsLibrary::AssignerQoS`

The `example_io_app` uses `set_topic_datareader_qos` and `set_topic_datawriter_qos` methods for topic-specific QoS configuration, following RTI best practices.

## Code Organization

The `example_io_app` follows these organizational patterns:

- **Main Class:** Contains the `run()` static method for application logic
- **Data Processors:** Separate async functions for each data type processing (e.g., `process_position_data()`)
- **Publishers:** Separate async functions for data publishing with concurrent tasks
- **RTI Asyncio Integration:** Uses `rti.asyncio.run()` and `asyncio.gather()` for concurrent operations
- **QoS Management:** Uses `set_topic_datareader_qos` and `set_topic_datawriter_qos` methods

## Features

### **Core DDS Functionality**
- **Command Publisher**: Publishes `example_types.Command` data with command types and destinations
- **Button Publisher**: Publishes `example_types.Button` data with button states and press counts
- **Config Publisher**: Publishes `example_types.Config` data with parameter configurations
- **Position Subscriber**: Asynchronously receives and processes `example_types.Position` data
- **RTI Distributed Logger**: Integrated distributed logging for remote monitoring and debugging - external visibility of logs over DDS with infrastructure services or your own apps
- **Command-Line Interface**: Full argument parsing with domain ID and verbosity control
- **Infinite Publisher Loop**: Continuous operation with incrementing data publication
- **Configurable DDS Verbosity**: 6-level logging control for debugging and monitoring
- **Asyncio Integration**: Uses Python asyncio for concurrent publisher/subscriber operations
- **Configuration Constants**: Centralized configuration management with named constants
- **QoS Profile Configuration**: Loads QoS settings from external XML configuration files
- **Detailed Data Processing**: Comprehensive member field printouts for debugging
- **Graceful Shutdown**: Proper KeyboardInterrupt handling for clean application termination

## Architecture

### Data Flow Design
- **Publishers**: Send Command, Button, and Config data on their respective topics
- **Subscriber**: Receives Position data from remote publishers
- **Cross-Application Communication**: Designed to work with C++ example_io_app application

### Message Types
- **Command Publisher**: `example_types.Command` - System commands with destinations and priorities
- **Button Publisher**: `example_types.Button` - Button press events with state tracking
- **Config Publisher**: `example_types.Config` - Configuration parameters with values
- **Position Subscriber**: `example_types.Position` - Geographic position data with timestamps

### Configuration Management
The application uses centralized configuration constants:
```python
# Application timing constants
PUBLISHER_SLEEP_INTERVAL = 2  # seconds for command/button/config publishing
MAIN_TASK_SLEEP_INTERVAL = 5  # seconds

# QoS Configuration
QOS_FILE_PATH = "../../dds/qos/DDS_QOS_PROFILES.xml"
qos_profiles.DEFAULT_PARTICIPANT = "DPLibrary::DefaultParticipant"
qos_profiles.ASSIGNER = "DataPatternsLibrary::AssignerQoS"
```

### QoS Profiles
The application uses QoS profiles from `../../dds/qos/DDS_QOS_PROFILES.xml`:
- **DomainParticipant**: `DPLibrary::DefaultParticipant` 
- **DataWriter/DataReader**: `DataPatternsLibrary::AssignerQoS` (topic-based QoS assignment)

## Prerequisites

- **RTI Connext DDS 7.3.0** or later 
- **Python 3.6-3.12** (RTI Connext DDS 7.3.0 compatible versions)
- **CMake 3.12+** for automatic code generation
- **RTI Connext Python API** (automatically installed by install script)

## Current Setup Status

✅ **Virtual Environment**: `connext_dds_env` is configured and ready  
✅ **RTI Installation**: Compatible with RTI Connext DDS 7.3.0  
✅ **Generated Bindings**: Python DDS types generated from IDL  
✅ **Verified Working**: Application tested and fully functional  

**Note**: The `install.sh` script handles all setup automatically, including RTI API installation and DDS code generation.

**⚠️ Important**: If you cloned this repository, ensure you have the git submodules by cloning with `--recurse-submodules` or running:
```bash
git submodule update --init --recursive
```

### Virtual Environment Benefits

**🐍 Why Use Virtual Environments?**
- **Dependency Isolation**: Prevents conflicts between RTI packages and system Python packages
- **Clean Environment**: Ensures consistent dependencies across different systems
- **Easy Cleanup**: Can be completely removed without affecting system Python
- **Development Safety**: Protects system Python from RTI-specific modifications
- **Version Control**: Allows testing with different RTI or Python versions

### Virtual Environment Management

```bash
# Activate virtual environment (Linux/macOS)
cd /home/rti/connext_starter_kit/apps/python
source connext_dds_env/bin/activate

# Deactivate virtual environment
deactivate
```

### RTI Python API Installation

**📚 Official Installation Guide**: [RTI Connext DDS Installation Guide - Python Packages](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/installation_guide/installing.html#installing-python-c-or-ada-packages)

**Installation Options:**

1. **Manual installation (Recommended):**
   ```bash
   # Set NDDSHOME environment variable first
   export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
   
   # Activate virtual environment
   source connext_dds_env/bin/activate
   
   # Install RTI Python API
   pip install rti.connext==7.3.0
   ```

2. **Using requirements.txt:**
   ```bash
   # Install all dependencies including RTI Connext Python API
   pip install -r requirements.txt
   ```

3. **Using install script (requires NDDSHOME to be set):**
   ```bash
   # Set NDDSHOME first, then run install script
   export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
   ./install.sh
   ```

### Generated Python Modules
The following are automatically created via CMake:
- `../../dds/python/codegen/ExampleTypes.py` (example_types module)
- `../../dds/python/codegen/Definitions.py` (Topic definitions and QoS constants)

## Installation and Usage

### Prerequisites Setup

Before running the application, you need to set up the environment:

```bash
# 1. Set RTI environment variable (required)
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"

# 2. Navigate to python apps directory
cd /home/rti/connext_starter_kit/apps/python

# 3. Activate virtual environment
source connext_dds_env/bin/activate

# 4. Install RTI Python API and generate DDS bindings (first time only)
pip install rti.connext==7.3.0
cd ../../dds/python && rm -rf build && mkdir build && cd build && cmake .. && make -j4
```

### Quick Start: Testing example_io_app

**🚀 Fastest way to test the current application:**

```bash
# Navigate to python apps directory and set up environment
cd /home/rti/connext_starter_kit/apps/python
source connext_dds_env/bin/activate
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"

# If first time setup, run install script
./install.sh

# Navigate to application and run it
cd example_io_app
python3 example_io_app.py --help
python3 example_io_app.py --domain_id 1 --verbosity 2
```

## Application Behavior

### Command-Line Interface
The Python application supports several command-line options for flexible configuration:

```bash
# From apps/python/ directory:
python example_io_app/example_io_app.py --help
usage: example_io_app.py [-h] [-v VERBOSITY] [-d DOMAIN_ID] [-q QOS_FILE]

Example I/O Application - Publishes Command/Button/Config, Subscribes to Position

optional arguments:
  -h, --help            show this help message and exit
  -v VERBOSITY, --verbosity VERBOSITY
                        Logging Verbosity (0-5, default: 1)
  -d DOMAIN_ID, --domain_id DOMAIN_ID
                        Domain ID (default: 1)
  -q QOS_FILE, --qos_file QOS_FILE
                        Path to QoS profiles XML file (default: ../../dds/qos/DDS_QOS_PROFILES.xml)
```

#### Verbosity Levels
The application supports configurable DDS logging verbosity:
- **0**: SILENT - No DDS internal logging
- **1**: EXCEPTION - Only exception messages (default)
- **2**: WARNING - Warnings and exceptions
- **3**: STATUS_LOCAL - Local status information
- **4**: STATUS_REMOTE - Remote participant status
- **5**: STATUS_ALL - Complete DDS status information

#### Usage Examples
```bash
# From apps/python/ directory (where rti_license.dat is located):

# Run with default settings (domain 1, verbosity 1)
python example_io_app/example_io_app.py

# Run on domain 5 with minimal logging
python example_io_app/example_io_app.py --domain_id 5 --verbosity 0

# Run with maximum DDS debugging
python example_io_app/example_io_app.py --domain_id 1 --verbosity 5

# Run with custom QoS file
python example_io_app/example_io_app.py --qos_file /path/to/custom/qos.xml

# Show help
python3 example_io_app.py --help
```

### Distributed Logger Integration
The application includes RTI Distributed Logger functionality for comprehensive logging and remote monitoring:

- **Logger Initialization**: Automatically configured with domain ID and application kind
- **Multi-Level Logging**: Uses Info, Warning, and Error log levels throughout the application
- **Application Lifecycle Logging**: Logs initialization, main loop iterations, and shutdown events
- **Data Publishing Logs**: Records all data publishing events with detailed message information
- **Data Receiving Logs**: Logs incoming data processing with payload details
- **Remote Monitoring**: Log messages are published as DDS topics for remote visualization
- **RTI Tool Integration**: Compatible with RTI Spy and RTI Admin Console for log visualization

### Publisher Tasks
The application publishes three types of data every 2 seconds:
- **Command Publisher**: Publishes command messages with incrementing IDs
- **Button Publisher**: Publishes button press events with state tracking
- **Config Publisher**: Publishes configuration parameters

### Subscriber Task
- **Position Subscriber**: Asynchronously processes incoming Position data
- **Detailed Data Display**: Shows source ID, coordinates, and timestamp information
- Uses RTI asyncio for non-blocking data reception with proper error handling

### Main Application Task
- Provides periodic status updates every 5 seconds
- Monitors overall application health and lifecycle

### Sample Output
```
DomainParticipant created with QoS profile: DPLibrary::DefaultParticipant
DOMAIN ID: 1
RTI Distributed Logger configured for domain 1 with application kind: Example Python IO App-DistLogger
[SUBSCRIBER] RTI Asyncio reader configured for Position data...
[PUBLISHER] RTI Asyncio writers configured for Command, Button, and Config data...
[MAIN] Starting RTI asyncio tasks...
[COMMAND_PUBLISHER] Published Command - ID: cmd_0000
[BUTTON_PUBLISHER] Published Button - ID: btn_1, Count: 0
[CONFIG_PUBLISHER] Published Config - Parameter: update_rate
[MAIN] ExampleIOApp processing loop - iteration 0

# When Position data arrives:
[POSITION_SUBSCRIBER] Position Received:
  Source ID: cxx_app_source
  Latitude: 40.7128
  Longitude: -74.0060
  Altitude: 10.0
  Timestamp: 1698765432
```

## Key Implementation Details

### Asyncio Pattern
The application uses Python's asyncio library with `asyncio.gather()` to run concurrent tasks:
- **Publisher task**: Publishes Command, Button, and Config data at regular intervals
- **Position subscriber task**: Asynchronously processes incoming Position data from external sources  
- **Main application task**: Provides periodic status updates and lifecycle management

### Configuration Constants
All configuration values are centralized as module-level constants for easy customization and maintenance.

### Data Processing Functions
- `process_position_data()`: Implements async data processing for incoming Position messages
- Demonstrates RTI asyncio integration with `async for data in reader.take_data_async()` pattern

## Configuration

### QoS Profiles
The application loads QoS configurations from `../../dds/qos/DDS_QOS_PROFILES.xml`:
- **DefaultParticipant**: Standard participant configuration
- **AssignerQoS**: Topic-specific QoS assignment based on topic names

### Customization
To modify the application behavior:

1. **Publishing Rate**: Modify `PUBLISHER_SLEEP_INTERVAL` (default: 2 seconds)
2. **Status Updates**: Modify `MAIN_TASK_SLEEP_INTERVAL` (default: 5 seconds)
3. **Domain ID**: Change default domain ID in argument parser (default: 1)
4. **QoS Profiles**: Update profile names in Definitions configuration
5. **QoS File Location**: Modify path to QoS XML file as needed

### Cross-Application Communication
This Python application is designed to work with the C++ example_io_app application for comprehensive testing:
- **Python → C++**: Command, Button, Config data from Python publisher to C++ subscriber
- **C++ → Python**: Position data from C++ publisher to Python subscriber
- Both applications can run simultaneously for bidirectional communication testing
- **Distributed Logger Compatibility**: Both applications use RTI Distributed Logger on the same domain for unified monitoring

#### Testing Both Applications Together
```bash
# Terminal 1 (C++ Application on Domain 5)
cd /home/rti/connext_starter_kit/apps/cxx11/example_io_app/build && ./example_io_app -d 5 -v 1

# Terminal 2 (Python Application on Domain 5)  
cd /home/rti/connext_starter_kit/apps/python
source connext_dds_env/bin/activate
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
cd example_io_app
python3 example_io_app.py --domain_id 5 --verbosity 1
```

This setup enables:
- **Cross-Platform Data Exchange**: Command/Button/Config (Python→C++) and Position (C++→Python) message flow
- **Distributed Logging**: Unified log monitoring from both applications via RTI tools
- **QoS Verification**: Tests QoS profile compatibility between Python and C++ implementations
- **Performance Analysis**: Comparative analysis of asyncio vs. traditional DDS patterns

## Setup Verification

### Testing the Application

Test the application step-by-step:

```bash
# 1. Set up environment
cd /home/rti/connext_starter_kit/apps/python
source connext_dds_env/bin/activate
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"

# 2. Ensure setup is complete (run once)
./install.sh

# 3. Test the application
cd example_io_app
python3 example_io_app.py --help
python3 -m py_compile example_io_app.py && echo "✅ Syntax OK"

# 4. Run application (Ctrl+C to stop)
python3 example_io_app.py --domain_id 1 --verbosity 2
```

### Cross-Application Testing

Test with the C++ application for full communication:

```bash
# Terminal 1: Start C++ application
cd /home/rti/connext_starter_kit/apps/cxx11/example_io_app
build/example_io_app -d 1 -v 1

# Terminal 2: Start Python application  
cd /home/rti/connext_starter_kit/apps/python
source connext_dds_env/bin/activate
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
cd example_io_app
python3 example_io_app.py --domain_id 1 --verbosity 2
```

**Expected Results:**
- Python app publishes Command/Button/Config messages every 2 seconds
- Python app receives and displays Position messages from C++ app
- C++ app receives and displays Command/Button/Config messages from Python app
- Both apps show distributed logger messages

## Troubleshooting

### Common Issues

#### **Environment Setup Issues**
1. **Virtual environment not activated**
   ```bash
   # Solution: Always activate before running
   cd /home/rti/connext_starter_kit/apps/python
   source connext_dds_env/bin/activate
   # Verify with:
   which python  # Should point to connext_dds_env/bin/python
   ```

2. **NDDSHOME not set**
   ```bash
   # Solution: Set environment variable before running install script
   export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
   ```

#### **Installation Issues**
1. **Import Error: No module named 'rti.connextdds'**
   ```bash
   # Solution: Run the install script
   ./install.sh
   ```

2. **CMake cache errors**
   ```bash
   # Solution: Clean and regenerate DDS bindings
   cd ../../dds/python && rm -rf build && mkdir build && cd build && cmake .. && make -j4
   ```

#### **Runtime Issues**
1. **DDS Environment**: Ensure RTI Connext DDS environment is properly configured
2. **Generated Files Missing**: Regenerate DDS Python bindings

### Debugging
- Enable verbose logging by setting verbosity level to 5
- Check QoS profile loading messages
- Monitor subscriber ready messages
- Review detailed data printouts from processing functions

## Related Files
- **C++ Companion**: `../cxx11/example_io_app/example_io_app.cxx` - C++ application with similar functionality
- **C++ Headers**: `../cxx11/example_io_app/application.hpp` - C++ DDS application architecture
- **IDL Definitions**: `../../dds/datamodel/ExampleTypes.idl` - DDS data type definitions
- **QoS Configuration**: `../../dds/qos/DDS_QOS_PROFILES.xml` - Shared QoS profiles for both C++ and Python applications

## Summary

This Python folder contains a single, clean implementation:

- **📁 One Application**: `example_io_app` - fully functional DDS application
- **📄 Correct Data Types**: Uses only `example_types` from ExampleTypes.idl (Position, Command, Button, Config)  
- **🔧 Ready Setup**: Virtual environment configured with all dependencies
- **✅ Tested & Working**: All functionality verified and documented
- **🚀 Simple Usage**: Run `./install.sh` once, then use `python3 example_io_app.py`

**Key Commands:**
```bash
# Setup (run once)
cd /home/rti/connext_starter_kit/apps/python
source connext_dds_env/bin/activate
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
./install.sh

# Run application
cd example_io_app  
python3 example_io_app.py --domain_id 1 --verbosity 2
```

## License
Copyright (c) Real-Time Innovations, 2025. All rights reserved.
RTI grants Licensee a license to use, modify, compile, and create derivative works of the software solely for use with RTI Connext DDS.