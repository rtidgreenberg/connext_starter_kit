# Command Override Application

## Overview

The Command Override application is a sophisticated RTI Connext DDS example that demonstrates advanced DDS patterns including progressive publishing, ownership strength control, and programmatic QoS modification. This application showcases how multiple command writers with different ownership strengths can arbitrate control in a distributed system.

## Features

### 🚀 **Core Functionality**
- **4-Phase Progressive Publishing**: Sequential activation of multiple command writers
- **DDS Ownership Strength Control**: Different priority levels for command arbitration
- **Programmatic QoS Modification**: Dynamic ownership strength changes at runtime
- **Asynchronous Event Processing**: Event-driven command processing using AsyncWaitSet
- **Enhanced Command Types**: Semantic command differentiation (START, PAUSE, RESET)

### 🏗️ **Architecture Highlights**
- **1 Command Reader**: Subscribes to all command messages
- **3 Command Writers**: Each with different ownership strengths (10, 20, 30)
- **Same Command ID**: All writers use "COMMAND_CTRL" for unified identification
- **Different Command Types**: Each writer sends distinct command semantics
- **Switch-based Phase Control**: Clean enum-driven state management

## Application Behavior

### Phase 1: Single Writer (10 seconds)
- **Active Writers**: Writer 1 only
- **Command Type**: START
- **Ownership Strength**: 10
- **Behavior**: Only START commands are published and received

### Phase 2: Two Writers (10 seconds)  
- **Active Writers**: Writer 1 + Writer 2
- **Command Types**: START + PAUSE
- **Ownership Strengths**: 10 + 20
- **Behavior**: Writer 2 (strength 20) takes precedence, only PAUSE commands received

### Phase 3: All Writers (10 seconds)
- **Active Writers**: Writer 1 + Writer 2 + Writer 3
- **Command Types**: START + PAUSE + RESET  
- **Ownership Strengths**: 10 + 20 + 30
- **Behavior**: Writer 3 (strength 30) has highest priority, only RESET commands received

### Phase 4: Dynamic QoS (10 seconds)
- **Active Writers**: All 3 writers
- **Command Types**: START + PAUSE + RESET
- **Ownership Strengths**: 50 + 20 + 30 (Writer 1 programmatically changed to 50)
- **Behavior**: Writer 1 now has highest priority (50), START commands win

## Data Model

### Command Structure
```cpp
struct Command {
    @key string command_id;        // "COMMAND_CTRL"
    string destination_id;         // Target destination  
    CommandType command_type;      // START, PAUSE, RESET, STOP, SHUTDOWN
    string message;                // Optional message
    unsigned long timestamp_sec;   // Timestamp
    boolean urgent;                // Priority flag
};
```

### Command Types
- `COMMAND_START`: System start command
- `COMMAND_PAUSE`: System pause command  
- `COMMAND_RESET`: System reset command
- `COMMAND_STOP`: System stop command
- `COMMAND_SHUTDOWN`: System shutdown command

## QoS Configuration

The application uses three ownership strength profiles:
- **CommandStrength10QoS**: Ownership strength 10 (Writer 1)
- **CommandStrength20QoS**: Ownership strength 20 (Writer 2)
- **CommandStrength30QoS**: Ownership strength 30 (Writer 3)

QoS profiles are defined in: `../../../../dds/qos/DDS_QOS_PROFILES.xml`

## Building and Running

### Prerequisites
- RTI Connext DDS 7.3.0 or later
- CMake 3.16 or later
- C++11 compatible compiler

### Build Steps
```bash
cd /home/rti/connext_starter_kit/apps/cxx11/command_override/build
make -j4
```

### Running the Application
```bash
# Basic execution
./command_override

# With custom domain ID
./command_override -d 2

# With custom QoS file
./command_override -q /path/to/qos_profiles.xml

# With verbosity for debugging
./command_override -v 3
```

### Command Line Options
- `-d, --domain <int>`: DDS domain ID (default: 1)
- `-v, --verbosity <int>`: Debug verbosity 0-3 (default: 1)  
- `-q, --qos-file <str>`: Path to QoS profile XML file
- `-h, --help`: Show usage information

## Sample Output

```
Command Override application starting on domain 1
RTI Distributed Logger configured for domain 1
DL Info: : Command Override app is running. Press Ctrl+C to stop.

[PHASE 1 - COMMAND1]
Message Count: 1
------------------------------------
 Command received from: COMMAND_CTRL | Type: START
------------------------------------

[PHASE 2 - COMMAND1&2]  
Message Count: 1
------------------------------------
 Command received from: COMMAND_CTRL | Type: PAUSE
------------------------------------

[PHASE 4 - WRITER1_STRENGTH50]
!!! Writer 1 QoS changed to ownership strength 50 !!!
Message Count: 1
------------------------------------
 Command received from: COMMAND_CTRL | Type: START
------------------------------------
```

## Key DDS Concepts Demonstrated

### 1. **Ownership Strength**
- Multiple writers compete for the same data instance
- Higher ownership strength writers take precedence
- Automatic failover when high-priority writers disconnect

### 2. **Programmatic QoS Changes**
- Dynamic modification of ownership strength at runtime
- Demonstrates QoS policy updates without recreating entities

### 3. **AsyncWaitSet Event Processing**
- Non-blocking, event-driven message processing
- Efficient handling of high-frequency data updates

### 4. **Progressive Publishing Pattern**
- Systematic activation of additional data sources
- Useful for staged system bring-up scenarios

## File Structure

```
command_override/
├── command_override.cxx    # Main application logic
├── application.hpp        # Command line parsing utilities  
├── CMakeLists.txt        # Build configuration
├── README.md             # This file
└── build/                # Build output directory
    └── command_override   # Executable
```

## Dependencies

- **DDS Utilities Library**: `libdds_utils_datamodel.so`
- **RTI Connext DDS Core**: Core DDS functionality
- **RTI Extensions**: AsyncWaitSet and other advanced features
- **Generated Types**: ExampleTypes from IDL compilation

## Troubleshooting

### Common Issues
1. **Build Errors**: Ensure DDS library is built first (`make` in `dds/cxx11/build`)
2. **QoS Profile Not Found**: Check QoS file path and profile names
3. **Domain Connectivity**: Verify domain ID matches between instances
4. **Permission Errors**: Ensure proper file permissions for executable

### Debug Tips
- Use `-v 3` for maximum verbosity
- Check DDS_QOS_PROFILES.xml for profile definitions
- Monitor RTI Admin Console for DDS discovery issues
- Use timeout wrapper for controlled test runs: `timeout 30s ./command_override`

## Related Documentation

- [RTI Connext DDS User's Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/users_manual/index.htm)
- [C++ API Reference](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/api/connext_dds/api_cpp2/index.html)
- [QoS Provider Guide](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/users_manual/index.htm#users_manual/QoS_Provider.htm)
- [Ownership QoS Policy](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/users_manual/index.htm#users_manual/OWNERSHIP_QosPolicy.htm)

---

**Copyright © 2025 Real-Time Innovations, Inc. All rights reserved.**