# RTI Connext DDS Starter Kit

A comprehensive starter kit demonstrating cross-language DDS applications with RTI Connext DDS 7.3.0. This repository provides complete examples of C++ and Python applications communicating through DDS with shared data models, utility classes, and best practices.

## 🚀 Quick Start

### Prerequisites

- **RTI Connext DDS 7.3.0+** installed and licensed
- **RTI License File** (`rti_license.dat`) - required for Python applications
- **C++14 compiler** (GCC 9.4.0+ or equivalent)
- **Python 3.8+** with virtual environment support
- **CMake 3.12+** for build configuration

### Environment Setup

```bash
# Set RTI Connext DDS environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Clone repository with submodules
git clone --recurse-submodules <repository-url>
cd connext_starter_kit

# If already cloned without --recurse-submodules, initialize submodules:
# git submodule update --init --recursive

# The rticonnextdds-cmake-utils submodule is REQUIRED for building

# IMPORTANT: Copy RTI license file for Python applications
cp /path/to/your/rti_license.dat apps/python/
```

### Build and Run

```bash
# 1. Build DDS shared libraries and bindings
cd dds/cxx11 && mkdir build && cd build
cmake .. && make -j4

cd ../../python && mkdir build && cd build  
cmake .. && make -j4

# 2. Build and run C++ application
cd ../../../apps/cxx11/example_io_app && mkdir build && cd build
cmake .. && make -j4
./example_io_app

# 3. In separate terminal - Setup and run Python application
cd apps/python
# Ensure RTI license file is present in the python/ directory
ls rti_license.dat  # Should exist - copy if missing
python -m venv connext_dds_env
source connext_dds_env/bin/activate
pip install -r requirements.txt
# Run from python/ directory so license file is found
python example_io_app/example_io_app.py
```

## 📁 Repository Structure

```
connext_starter_kit/
├── README.md                        # This file - project overview and setup
├── .github/prompts/                 # GitHub Copilot prompt templates
│   └── build_cxx.prompt.md         # C++ application generation instructions
├── apps/                            # Application implementations
│   ├── cxx11/                       # C++ applications with AI generation support
│   │   ├── README.md                # C++ app creation guide with GitHub Copilot
│   │   └── example_io_app/          # Reference C++ I/O demonstration application
│   └── python/                      # Python applications
│       ├── rti_license.dat          # RTI license file (REQUIRED - copy here)
│       └── example_io_app/          # Python I/O demonstration application  
├── dds/                             # DDS data models and utilities
│   ├── README.md                    # DDS layer documentation
│   ├── datamodel/                   # IDL data type definitions
│   ├── cxx11/                       # C++ utilities and code generation
│   ├── python/                      # Python code generation
│   └── qos/                         # Quality of Service profiles
└── resources/                       # External dependencies and utilities
    └── rticonnextdds-cmake-utils/   # Git submodule: RTI CMake utilities
```

## 🎯 What's Included

### **Multi-Language DDS Applications**
- **C++ Application**: Reference implementation with multiple readers/writers and AsyncWaitSet processing
- **Python Application**: Asyncio-based application for rapid development and integration
- **Cross-Language Communication**: Applications communicate seamlessly via DDS topics
- **AI-Powered Generation**: Create new C++ apps using GitHub Copilot and structured prompts

### **Comprehensive Data Model**
- **6 IDL Data Types**: Command, Button, Config, Position, State, Image with complete examples
- **Configuration Constants**: Centralized QoS profiles, domain settings, and topic names
- **Automatic Code Generation**: CMake-driven rtiddsgen integration for both languages

### **Production-Ready Utilities**
- **DDSContext Class**: Centralized DomainParticipant and AsyncWaitSet management
- **DDSInterface Class**: Simplified DataReader/DataWriter creation with error handling
- **Distributed Logging**: RTI Admin Console integration for system-wide monitoring - external visibility of logs over DDS with infrastructure services or your own apps
- **QoS Profile Management**: Flexible XML-based configuration with ASSIGNER_QOS patterns
- **RTI CMake Integration**: Git submodule with official RTI CMake utilities for seamless builds

### **Best Practices Demonstration**
- **Error Handling**: Comprehensive exception handling and logging
- **Resource Management**: Proper DDS entity lifecycle and cleanup
- **Event-Driven Architecture**: AsyncWaitSet and asyncio processing patterns
- **Configuration Management**: External QoS profiles and runtime parameters

## 🏗️ Architecture Overview

### **DDS Communication Flow**
```
┌─────────────────┐    DDS Topics    ┌─────────────────┐
│  C++ App        │◄────────────────►│  Python App     │
│                 │                  │                 │  
│ • Position Pub  │─────Position────►│ • Position Sub  │
│ • Command Sub   │◄─────Command─────│ • Command Pub   │
│ • Button Sub    │◄─────Button──────│ • Button Pub    │
│ • Config Sub    │◄─────Config──────│ • Config Pub    │
└─────────────────┘                  └─────────────────┘
         │                                     │
         └─────────► RTI Admin Console ◄──────┘
                   (Distributed Logging)
```

### **Data Types and Topics**
| Data Type | Topic Name | Description | Publishers | Subscribers |
|-----------|------------|-------------|------------|-------------|
| `Command` | `Command` | Application commands and control | Python | C++ |
| `Button` | `Button` | Button press events and states | Python | C++ |
| `Config` | `Config` | Configuration parameters | Python | C++ |  
| `Position` | `Position` | GPS coordinates and location data | C++ | Python |
| `State` | `State` | Application state information | - | - |
| `Image` | `Image` | Large binary data and metadata | - | - |

## 🛠️ Development Workflow

### **Creating New Applications with GitHub Copilot**

This starter kit includes AI-powered application generation using GitHub Copilot and structured prompts:

#### **C++ Applications**
Use the build prompt template to rapidly create new DDS applications:

```bash
# 1. Open the build prompt in your editor
code .github/prompts/build_cxx.prompt.md

# 2. Use GitHub Copilot Chat with commands like:
# "Follow instructions in build_cxx.prompt.md. Create a new cxx app with [READERS] as reader(s) and [WRITERS] as writer(s)"

# Examples:
# - Sensor app: "...with Position and State as readers and Command as writer"  
# - Control app: "...with Button as reader and Config, State, Command as writers"
# - Monitor app: "...with Button, Position, State as readers and Image as writer"
```

**Copilot automatically generates:**
- Complete application directory structure
- CMakeLists.txt with proper RTI integration  
- Command-line parsing utilities (application.hpp)
- Main application with your specified DDS interfaces
- Event-driven processing and message publishing loops
- Comprehensive README documentation

**GitHub Copilot Integration**: Applications can be created entirely using the structured prompt process with commands like:
```
Follow instructions in build_cxx.prompt.md. Create a new cxx app with [READERS] as reader and [WRITERS] as writers
```

#### **Key Benefits**
- **Rapid Development**: Complete applications in minutes vs hours
- **Consistent Patterns**: All generated apps follow proven DDS best practices  
- **Error-Free Integration**: Automatic proper field access and API usage
- **Documentation Included**: Generated READMEs with usage examples
- **Cross-Language Compatible**: Works immediately with existing Python apps

See **[C++ Application Creation Guide](apps/cxx11/README.md)** for detailed step-by-step instructions.

### **Adding New Data Types**
1. Define new type in `dds/datamodel/*.idl`
2. Add topic constants to `DDSDefs.idl`
3. Rebuild DDS bindings: `cd dds/{cxx11,python}/build && make`
4. Implement in applications

### **Configuring QoS Profiles**
1. Edit `dds/qos/DDS_QOS_PROFILES.xml`
2. Use topic filters for type-specific QoS settings  
3. Applications automatically pick up changes without recompilation

### **Extending Applications**
- **C++**: Add new DDSInterface instances and AsyncWaitSet callbacks
- **Python**: Add new asyncio tasks and data handlers

## 📊 Performance Characteristics

### **C++ Application**
- **Publishing Rate**: 2 Hz (Position data every 500ms)
- **Processing Model**: AsyncWaitSet with 5-thread pool
- **Memory Usage**: Minimal overhead with efficient DDS native types
- **Latency**: Sub-millisecond for local communication

### **Python Application**  
- **Publishing Rate**: 1 Hz (Command, Button, Config data every 1000ms)
- **Processing Model**: asyncio event loop with concurrent tasks
- **Integration**: Easy integration with ML/AI frameworks and web services
- **Flexibility**: Rapid prototyping and configuration changes

## 🔧 Troubleshooting

### **Common Build Issues**
```bash
# RTI environment not set
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Missing git submodules (CMake will fail without RTI CMake utilities)
git submodule update --init --recursive

# Missing build directories  
mkdir -p dds/{cxx11,python}/build apps/cxx11/example_io_app/build

# Python virtual environment
python -m venv connext_dds_env && source connext_dds_env/bin/activate
```

### **Runtime Issues**
- **QoS File Not Found**: Check relative paths from build directories
- **Domain ID Mismatch**: Ensure both applications use same domain (default: 1)
- **License Issues**: 
  - **Python Apps**: Copy `rti_license.dat` to `apps/python/` directory and run Python apps from this directory
  - **C++ Apps**: Use system-wide license from NDDSHOME installation
  - Verify RTI Connext DDS license is valid and not expired
  - License file must be in current working directory for Python DDS applications

### **Monitoring and Debugging**
- **RTI Admin Console**: Monitor distributed logs and DDS communication
- **Verbosity Levels**: Use `-v 0-3` to control debug output
- **Network Issues**: Check firewall settings for UDP multicast (port 7400+)

## 📚 Documentation

- **[DDS Layer Documentation](dds/README.md)** - Data models, utilities, and code generation
- **[C++ Application Guide](apps/cxx11/example_io_app/README.md)** - Native application details
- **[Python Application Guide](apps/python/README.md)** - Python implementation and setup  
- **[Python App Specifics](apps/python/example_io_app/README.md)** - Detailed Python application features

## 📄 License

This project is licensed under the RTI Software License Agreement. See RTI Connext DDS documentation for terms and conditions.

## 🆘 Support

- **RTI Community Portal**: https://community.rti.com/
- **RTI Documentation**: https://community.rti.com/static/documentation/
- **RTI Support**: Contact RTI support for licensed users

---

**RTI Connext DDS Starter Kit** - Accelerating DDS development with cross-language examples and best practices.
