# Flexible Autonomy System Toolkit

A project template demonstrating cross-language DDS applications with RTI Connext DDS 7.3.0. Includes C++ and Python applications communicating through DDS with shared data models, utility classes, and best practices.

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

## What's Included

### Multi-Language DDS Applications
- **C++ Applications**: Reference implementations with AsyncWaitSet processing
- **Python Applications**: Asyncio-based for rapid development
- **Cross-Language Communication**: Seamless DDS topic communication
- **AI-Powered Generation**: Create C++ apps using GitHub Copilot

### Data Model
- **6 IDL Data Types**: Command, Button, Config, Position, State, Image
- **FlatData Zero-Copy**: High-performance large data transfers
- **Configuration Constants**: Centralized QoS profiles and topic names
- **Automatic Code Generation**: CMake-driven rtiddsgen integration

### Utility Classes
- **DDSContext**: Centralized DomainParticipant and AsyncWaitSet management
- **DDSReaderSetup/WriterSetup**: Simplified DataReader/DataWriter creation with status monitoring
- **Distributed Logging**: RTI Admin Console integration for external log visibility
- **QoS Profile Management**: Flexible XML-based configuration

## Architecture Overview

### Data Types and Topics
| Data Type | Topic | Description | Example Publishers | Example Subscribers |
|-----------|-------|-------------|-------------------|---------------------|
| `Command` | `Command` | Control commands | Python | C++ |
| `Button` | `Button` | Button events | Python | C++ |
| `Config` | `Config` | Configuration | Python | C++ |
| `Position` | `Position` | GPS location | C++ | Python |
| `State` | `State` | System state | - | - |
| `Image` | `Image` | Binary data | - | - |
| `FinalFlatImage` | - | Large data (3 MB @ 10 Hz) | fixed_image_flat_zc | fixed_image_flat_zc |

## Development Workflow

### Creating C++ Applications with GitHub Copilot

Use build prompt templates to rapidly create DDS applications:

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

```bash
# Open build prompt
code .github/prompts/build_cxx.prompt.md

# Use GitHub Copilot Chat
"Follow instructions in build_cxx.prompt.md. Create a new cxx app with Position and State as readers and Command as writer"
```

See **[C++ Application Creation Guide](apps/cxx11/README.md)** for details.

### Adding New Data Types
1. Define in `dds/datamodel/*.idl`
2. Add topic to `DDSDefs.idl`
3. Rebuild: `cd dds/cxx11/build && make -j4`

### Configuring QoS
1. Edit `dds/qos/DDS_QOS_PROFILES.xml`
2. Applications automatically pick up changes (no recompilation)

## Troubleshooting

### Build Issues
```bash
# Set RTI environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Initialize submodules (required for CMake)
git submodule update --init --recursive

# Create build directories
mkdir -p dds/cxx11/build dds/python/build
```

### Runtime Issues
- **QoS File Not Found**: Check relative paths from build directory
- **Domain Mismatch**: Ensure same domain ID (default: 1)
- **Python License**: Copy `rti_license.dat` to `apps/python/` and run from that directory
- **Monitoring**: Use RTI Admin Console for distributed logs

## Documentation

- **[DDS Layer](dds/README.md)** - Data models and utilities
- **[C++ Apps](apps/cxx11/README.md)** - C++ application guide
- **[Python Apps](apps/python/README.md)** - Python setup and apps

## Support

- **RTI Community**: https://community.rti.com/
- **RTI Documentation**: https://community.rti.com/static/documentation/
