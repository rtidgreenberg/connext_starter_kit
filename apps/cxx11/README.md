# C++11 DDS Applications

C++11 applications built with RTI Connext DDS, showcasing different DDS communication patterns and integration approaches.

## Table of Contents
- [Available Applications](#available-applications)
- [Creating New C++ DDS Applications](#creating-new-c-dds-applications)
- [Key Integration Patterns](#key-integration-patterns)
- [Build Dependencies](#build-dependencies)
- [Getting Started](#getting-started)

## Available Applications

### [`example_io_app/`](./example_io_app/) - Reference Implementation
Complete reference application demonstrating multiple readers and writers:
- **Multiple Subscribers**: Command, Button, Config readers using AsyncWaitSet
- **GPS Publisher**: Continuous Position data publishing (500ms intervals)
- **Distributed Logging**: RTI Admin Console integration for external log visibility
- **Event-Driven Architecture**: AsyncWaitSet-based message processing

### [`fixed_image_flat_zc/`](./fixed_image_flat_zc/) - High-Performance FlatData
Zero-copy high-throughput demonstration:
- **3 MB Payloads**: Large data transfers at 10 Hz (~30 MB/sec)
- **FlatData Zero Copy**: Direct shared memory access, no serialization
- **Application Acknowledgment**: Ensures data consistency with zero-copy
- **Reliable QoS**: Acknowledgment-based flow control
- **AsyncWaitSet Processing**: Event-driven data handling

### [`command_override/`](./command_override/) - Command Arbitration using Ownership QoS
Advanced DDS ownership and QoS patterns:
- **4-Phase Progressive Publishing**: Sequential writer activation
- **Ownership Strength Control**: Priority-based command arbitration
- **Dynamic QoS Modification**: Runtime ownership strength changes
- **Multi-Writer Coordination**: Same topic, different priorities

### [`large_data_app/`](./large_data_app/) - Shared Memory Large Data Transfer
High-performance transfer of large data using shared memory:
- **~900 KB Images**: 640x480 RGB image data
- **Shared Memory Transport**: Efficient intra-host communication
- **LARGE_DATA_SHMEM QoS**: Optimized profiles for large payloads
- **Publisher and Subscriber**: Combined in single application
- **AsyncWaitSet Processing**: Event-driven data handling

### [`burst_large_data_app/`](./burst_large_data_app/) - High-Rate Burst Traffic
Simulates burst transmission of large data over LAN:
- **Point Cloud Data**: High-rate large payload transmission
- **Strict Reliability**: KEEP_ALL + RELIABLE QoS
- **Configurable Parameters**: Adjustable send rate and burst duration
- **Network Optimized**: Requires increased socket buffer sizes
- **Performance Statistics**: Throughput and acknowledgment metrics

### [`dynamic_partition_qos/`](./dynamic_partition_qos/) - Runtime Partition Management
Dynamic partition modification for environment isolation:
- **Runtime QoS Changes**: Modify partitions without restart
- **Unique Application IDs**: Auto-generated identifiers for tracking
- **Test Isolation**: Separate unit test and production traffic
- **Terminal Input**: Interactive partition switching
- **Self-Ignore Pattern**: Filters own publications using dds::sub::ignore()

## Creating New C++ DDS Applications

### Overview
You can rapidly create new DDS applications using GitHub Copilot 
and the provided build prompt template.  
This process leverages the existing DDS infrastructure and  utilities.   

### Prerequisites

```bash
# Set RTI Connext DDS environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0
source $NDDSHOME/resource/scripts/rtisetenv_<target>.bash

# Build from top-level (automatically builds DDS library and all applications)
cd /path/to/connext_starter_kit
mkdir -p build && cd build
cmake ..
cmake --build .
```

### Step-by-Step Application Creation

#### Step 1: Define New Data Types (Optional)

If you need custom data types beyond existing ones:

```bash
cd ../../dds/datamodel/
# Edit or create new .idl files
```

**Available Example Data Types:**
- `Button` - Button input events
- `Command` - System commands and control
- `Config` - Configuration parameters
- `State` - System state information
- `Position` - GPS/location data
- `Image` - Image data with metadata
- `FinalFlatImage` - High-performance FlatData type

#### Step 2: Add Topic Constants to Definitions (Optional)
If using new data types, add topic name constants:

```cpp
// Edit ../../dds/datamodel/idl/Definitions.idl
module topics {
    const string YOUR_NEW_TOPIC = "YourNewTopic";
    // Add other topic constants as needed
};
```

#### Step 3: Regenerate DDS Code (If new/changed IDL) (Optional)
```bash
cd /path/to/connext_starter_kit/build
cmake --build .
```

#### Step 4: Create Application Using GitHub Copilot

1. **Use Build Prompt**: Open `.github/prompts/build_cxx.prompt.md`

2. **Define Your Application**: Use GitHub Copilot Chat with a command like:
   ```
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with [TYPE using TOPIC NAME] as reader(s) and [TYPE using TOPIC NAME] as writer(s)
   ```
   
   **Example Commands:**
   ```bash
   # Sensor monitoring app
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with Position and State as readers and Command as writer
   
   # Control system app  
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with Button using ButtonTopic as reader and Config, State, Command as writers
   
   # Data collection app
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with Button, Position, State as readers and Image as writer
   ```

3. **Copilot Will**:
  - Generate Application directory structure
  - Generate `CMakeLists.txt` with dependencies
  - Generate `application.hpp` for command-line parsing
  - Generate main application with specified readers/writers
  - Generate DDS Writer/Reader setup and message processing
  - Rebuild DDS Types Library if necessary

#### Step 5: Build and Test

```bash
# The top-level build automatically includes your new app
cd /path/to/connext_starter_kit/build
cmake --build .

# Run using the convenient run script (auto-rebuilds if needed)
cd ..
./apps/cxx11/your_app_name/run.sh

# Or run directly from build
./build/apps/cxx11/your_app_name/your_app_name

# Test the application
./apps/cxx11/your_app_name/run.sh --help
```

### Application Template Structure

When Copilot creates your application, it follows this proven structure:

```
your_new_app_name/
├── CMakeLists.txt           # Build configuration
├── application.hpp          # Command-line parsing utilities  
├── your_new_app_name.cxx    # Main application logic
├── README.md               # Application documentation
└── build/                  # Build directory (created during build)
```

### Key Integration Patterns

All generated applications follow these established patterns:

#### **DDSParticipant Setup**
```cpp
// Centralized DDS participant management
auto dds_participant = std::make_shared<DDSParticipantSetup>(
    domain_id, 
    ASYNC_WAITSET_THREADPOOL_SIZE, 
    qos_file_path, 
    qos_profile, 
    APP_NAME
);
```

#### **Reader/Writer Setup** 
```cpp
// Reader example
auto button_reader = std::make_shared<DDSReaderSetup<example_types::Button>>(
    dds_participant,
    topics::BUTTON_TOPIC,
    qos_profiles::ASSIGNER
);

// Writer example
auto config_writer = std::make_shared<DDSWriterSetup<example_types::Config>>(
    dds_participant,
    topics::CONFIG_TOPIC,
    qos_profiles::ASSIGNER
);
```

#### **Event Processing**
```cpp
// Async event-driven processing for readers
void process_your_data(dds::sub::DataReader<example_types::YourType> reader) {
    auto samples = reader.take();
    for (const auto& sample : samples) {
        if (sample.info().valid()) {
            std::cout << sample.data() << std::endl;
            // Process your data here
        }
    }
}

// Enable async processing with DDSReaderSetup
your_reader->set_data_handler(process_your_data);
your_reader->enable_async();
```

#### **Message Publishing**
```cpp
// Get RTI Logger instance for distributed logging
auto& rti_logger = rti::config::Logger::instance();

// Publishing loop with error handling
while (!application::shutdown_requested) {
    try {
        your_message.field1("value");
        your_message.field2(42);
        your_interface->writer().write(your_message);
        std::cout << "[YOUR_TYPE] Published: " << your_message << std::endl;
    } catch (const std::exception &ex) {
        rti_logger.error(("Failed to publish: " + std::string(ex.what())).c_str());
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
}
```

### Best Practices for New Applications

1. **Follow Naming Conventions**: Use descriptive names that reflect your application's purpose
2. **Use Existing Data Types**: Leverage existing IDL types when possible to maintain interoperability  
3. **Consistent QoS Profiles**: Use `qos_profiles::ASSIGNER` for flexible XML-based QoS configuration
4. **Error Handling**: Include comprehensive exception handling for all DDS operations
5. **Distributed Logging**: Integrate with RTI distributed logger for system-wide monitoring - external visibility of logs over DDS with infrastructure services or your own apps
6. **Signal Handling**: Implement graceful shutdown with Ctrl+C handling
7. **Resource Cleanup**: Properly finalize DomainParticipant factory at exit

### Cross-Language Compatibility

All C++ applications created using this approach are automatically compatible with:
- **Python Applications**: In `../python/` directory
- **Other C++ Applications**: Using the same DDS domain and QoS profiles
- **RTI Tools**: Admin Console, DDSSpy, Monitor, etc.

### Testing Integration

Test your new application with existing apps:

```bash
# Terminal 1: Run your new C++ app
./your_new_app_name

# Terminal 2: Run Python example app  
cd ../../../python/example_io_app
python example_io_app.py

# Terminal 3: Monitor with RTI Admin Console
rtiadminconsole
```

### Troubleshooting

**Common Issues:**
- **Build Errors**: Ensure top-level CMake build is complete (`cmake --build .` in build/)
- **Runtime Errors**: Check NDDSHOME environment variable and architecture setup
- **No Communication**: Verify all applications use same domain ID and QoS profiles
- **Missing Types**: Rebuild from top-level if IDL files change

**Debug Steps:**
```bash
# Check DDS environment
echo $NDDSHOME

# Verify RTI license
ls $NDDSHOME/rti_license.dat

# Test with higher verbosity
./your_new_app_name -v 3

# Check QoS profiles
./your_new_app_name --qos-file ../../../../dds/qos/DDS_QOS_PROFILES.xml
```

## Build Dependencies

All applications automatically link against:
- **RTI Connext DDS 7.3.0+** with distributed logger support
- **DDS Utilities Library**: `libdds_utils_datamodel.so` 
- **Generated Headers**: ExampleTypes.hpp, Definitions.hpp
- **Utility Classes**: DDSParticipantSetup.hpp, DDSReaderSetup.hpp, DDSWriterSetup.hpp

## Getting Started

1. **Try the Example**: Build and run `example_io_app`
2. **Follow the Prompt**: Use `.github/prompts/build_cxx.prompt.md` with GitHub Copilot
3. **Create Your App**: Define readers/writers and let Copilot generate the code
4. **Test Integration**: Verify cross-language communication works
5. **Monitor with RTI Tools**: Use Admin Console to observe system behavior

The combination of GitHub Copilot, structured prompts, and proven utility classes enables rapid development of robust DDS applications with minimal boilerplate code.

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!