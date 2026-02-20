# Python DDS Applications

Python applications demonstrating RTI Connext DDS capabilities with example data types.

## Quick Start

1. **Get an RTI license** - Visit https://www.rti.com/get-connext

2. **Check your email** - You'll receive an automated email with `rti_license.dat` within minutes

3. **Set the license environment variable:**
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

4. **Run an application:**
   ```bash
   cd apps/python/example_io_app
   ./run.sh --domain_id 1
   ```

That's it! The `run.sh` script automatically handles NDDSHOME detection, virtual environment setup, and dependency installation.

---

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
│   ├── run.sh              # Run script (handles all setup)
│   └── README.md           # Documentation
├── large_data_app/         # Large data transfer demo
│   ├── large_data_app.py   # Main application
│   ├── run.sh              # Run script
│   └── README.md           # Documentation
├── downsampled_reader/     # Time-based filtering demo
│   ├── downsampled_reader.py
│   ├── run.sh              # Run script
│   └── README.md           # Documentation
├── README.md               # This file
├── install.sh              # Installation script (called by run.sh if needed)
└── requirements.txt        # Common dependencies

connext_dds_env/            # Shared virtual environment (at repository root)
```

## Current Applications

### example_io_app

- **Subscribes to:** Position messages
- **Publishes:** Command, Button messages
- **Features:**
  - RTI asyncio framework integration
  - qos_profiles.ASSIGNER profile usage
  - Distributed logger integration
  - Cross-language communication with C++ apps

---

## Detailed Setup

### Prerequisites
- RTI Connext DDS 7.3.0+ installed
- Python 3.8+
- Built DDS Python bindings (from top-level cmake build)
- RTI license file

#### Getting an RTI License

If you don't have an RTI Connext license:

1. Visit https://www.rti.com/get-connext
2. Fill out the form to request a free trial license
3. You'll receive an automated email with the license file (`rti_license.dat`) within a few minutes
4. Either:
   - Set the `RTI_LICENSE_FILE` environment variable:
     ```bash
     export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
     ```
   - Or place the license file at `$NDDSHOME/rti_license.dat`

> **Tip**: Add the `export RTI_LICENSE_FILE=...` line to your `~/.bashrc` or `~/.bash_profile` to make it permanent.

> **Note**: The `run.sh` scripts will automatically check for the license file and provide helpful error messages if not found.

### Installation

Installation is handled automatically by each app's `run.sh` script. For manual installation:

```bash
cd apps/python
./install.sh
```

The install script:
- Auto-detects `NDDSHOME` from `~/rti_connext_dds-*` (uses latest version)
- Creates a shared virtual environment at the repository root (`connext_dds_env/`)
- Installs dependencies from `requirements.txt`
- Triggers DDS Python binding generation if missing

### Run Application

Use the `run.sh` script in each app directory:

```bash
cd example_io_app
./run.sh --domain_id 1 --verbosity 2
```

The run script handles all environment setup automatically, including:
- NDDSHOME detection
- License file validation
- Virtual environment activation
- PYTHONPATH configuration for DDS bindings

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
   ├── run.sh              # Copy from example_io_app/run.sh and update APP_SCRIPT
   └── README.md
   ```

3. **Template**: Copy `run.sh` and main script from `example_io_app/`

4. **Update run.sh**: Change the `APP_SCRIPT` variable to your app's filename

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
- **Publishers**: Send Command and Button data on their respective topics
- **Subscriber**: Receives Position data from remote publishers
- **Cross-Application Communication**: Designed to work with C++ example_io_app application

### Message Types
- **Command Publisher**: `example_types.Command` - System commands with destinations and priorities
- **Button Publisher**: `example_types.Button` - Button press events with state tracking
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

## Setup Notes

**Note**: Each app's `run.sh` script handles all setup automatically:
- Auto-detects NDDSHOME from `~/rti_connext_dds-*`
- Validates license file existence
- Activates/creates the shared virtual environment
- Installs dependencies if missing
- Triggers Python binding generation if needed

**⚠️ Important**: If you cloned this repository, ensure you have the git submodules:
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

The virtual environment is shared across all Python apps and tools, located at the repository root:

```bash
# Activate virtual environment (Linux/macOS)
cd <path-to-connext_starter_kit>
source connext_dds_env/bin/activate

# Deactivate virtual environment
deactivate
```

> **Note**: The `run.sh` scripts handle virtual environment activation automatically.

### RTI Python API Installation

**📚 Official Installation Guide**: [RTI Connext DDS Installation Guide - Python Packages](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/installation_guide/installing.html#installing-python-c-or-ada-packages)

The RTI Python API is installed automatically by `run.sh` or `install.sh`. For manual installation:

```bash
# Activate virtual environment
source connext_dds_env/bin/activate

# Install from requirements.txt (includes RTI API)
pip install -r requirements.txt
```

### Generated Python Modules
The following are automatically created via CMake (from top-level build):
- `dds/build/python_gen/` - Generated Python DDS types

## Running Applications

### Quick Start: Testing example_io_app

**🚀 Fastest way to test:**

```bash
cd apps/python/example_io_app
./run.sh --help
./run.sh --domain_id 1 --verbosity 2
```

The `run.sh` script handles all setup automatically (NDDSHOME detection, license validation, venv activation, PYTHONPATH).

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
# From apps/python/example_io_app/ directory:

# Run with default settings (domain 1, verbosity 1)
./run.sh

# Run on domain 5 with minimal logging
./run.sh --domain_id 5 --verbosity 0

# Run with maximum DDS debugging
./run.sh --domain_id 1 --verbosity 5

# Run with custom QoS file
./run.sh --qos_file /path/to/custom/qos.xml

# Show help
./run.sh --help
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
[PUBLISHER] RTI Asyncio writers configured for Command and Button data...
[MAIN] Starting RTI asyncio tasks...
[COMMAND_PUBLISHER] Published Command - ID: cmd_0000
[BUTTON_PUBLISHER] Published Button - ID: btn_1, Count: 0
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
- **Publisher task**: Publishes Command and Button data at regular intervals
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
cd <path-to-connext_starter_kit>/build/apps/cxx11/example_io_app && ./example_io_app -d 5 -v 1

# Terminal 2 (Python Application on Domain 5)  
cd <path-to-connext_starter_kit>/apps/python
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
cd <path-to-connext_starter_kit>/apps/python
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
cd <path-to-connext_starter_kit>/apps/cxx11/example_io_app
build/example_io_app -d 1 -v 1

# Terminal 2: Start Python application  
cd <path-to-connext_starter_kit>/apps/python
source connext_dds_env/bin/activate
export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
cd example_io_app
python3 example_io_app.py --domain_id 1 --verbosity 2
```

**Expected Results:**
- Python app publishes Command/Button messages every 2 seconds
- Python app receives and displays Position messages from C++ app
- C++ app receives and displays Command/Button messages from Python app
- Both apps show distributed logger messages

## Troubleshooting

### Common Issues

#### **Environment Setup Issues**
1. **NDDSHOME not found**
   ```
   ERROR: Could not find RTI Connext DDS installation.
   ```
   **Solution**: Either set `NDDSHOME` environment variable or ensure RTI Connext DDS is installed at `~/rti_connext_dds-*`:
   ```bash
   export NDDSHOME="$HOME/rti_connext_dds-7.3.0"
   ```

2. **License file not found**
   ```
   ERROR: RTI license file not found.
   ```
   **Solution**: Either set `RTI_LICENSE_FILE` or place license at `$NDDSHOME/rti_license.dat`:
   ```bash
   export RTI_LICENSE_FILE=/path/to/rti_license.dat
   ```

#### **Installation Issues**
1. **Import Error: No module named 'rti.connextdds'**
   ```bash
   # Solution: Run the install script
   cd apps/python
   ./install.sh
   ```

2. **Python bindings not found**
   ```bash
   # Solution: Build from repository root
   cd connext_starter_kit
   mkdir -p build && cd build
   cmake .. && cmake --build .
   ```

#### **Runtime Issues**
1. **Generated files missing**: Run cmake build from repository root
2. **Virtual environment issues**: Delete `connext_dds_env/` and run install.sh again

### Debugging
- Enable verbose logging: `./run.sh --verbosity 5`
- Check QoS profile loading messages
- Monitor subscriber ready messages

## Related Files
- **C++ Companion**: `../cxx11/example_io_app/example_io_app.cxx` - C++ application with similar functionality
- **C++ Headers**: `../cxx11/example_io_app/application.hpp` - C++ DDS application architecture
- **IDL Definitions**: `../../dds/datamodel/idl/` - DDS data type definitions
- **QoS Configuration**: `../../dds/qos/DDS_QOS_PROFILES.xml` - Shared QoS profiles

## Summary

Each Python application has a `run.sh` script that handles all setup automatically:

**Key Commands:**
```bash
# Build DDS bindings (from repository root, run once)
mkdir -p build && cd build && cmake .. && cmake --build .

# Run an application (handles all setup automatically)
cd apps/python/example_io_app
./run.sh --domain_id 1 --verbosity 2
```

## License
Copyright (c) Real-Time Innovations, 2025. All rights reserved.
RTI grants Licensee a license to use, modify, compile, and create derivative works of the software solely for use with RTI Connext DDS.

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!