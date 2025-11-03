# C++11 DDS Applications

This directory contains C++11 applications built with RTI Connext DDS, showcasing different DDS communication patterns and integration approaches.

## Available Applications

### [`example_io_app/`](./example_io_app/) - Reference Implementation
Complete reference application demonstrating multiple readers and writers with:
- **Multiple Subscribers**: Command, Button, Config readers using AsyncWaitSet
- **GPS Publisher**: Continuous Position data publishing (500ms intervals)
- **Distributed Logging**: RTI Admin Console integration - external visibility of logs over DDS with infrastructure services or your own apps
- **Event-Driven Architecture**: AsyncWaitSet-based message processing

## Creating New C++ DDS Applications

### Overview
You can rapidly create new DDS applications using GitHub Copilot and the provided build prompt template. This process leverages the existing DDS infrastructure and utilities.

### Prerequisites
Before creating a new application, ensure your development environment is ready:

```bash
# 1. Set RTI Connext DDS environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# 2. Build DDS utility library (contains generated types and utilities)
cd ../../dds/cxx11 && rm -rf build && mkdir build && cd build
cmake .. && make -j4
```

### Step-by-Step Application Creation

#### Step 1: Define New Data Types (Optional)
If you need custom data types beyond the existing ones, create new IDL definitions:

```bash
cd ../../dds/datamodel/
# Edit or create new .idl files with your custom data structures
# Example: SensorData.idl, ControlCommands.idl, etc.
```

**Existing Data Types Available:**
- `Button` - Button input events and state
- `Command` - System commands and control messages  
- `Config` - Configuration parameters
- `State` - System state information
- `Position` - GPS/location data
- `Image` - Image data with metadata

#### Step 2: Add Topic Constants to DDSDefs
If using new data types, add topic name constants:

```cpp
// Edit ../../dds/datamodel/DDSDefs.idl
module topics {
    const string YOUR_NEW_TOPIC = "YourNewTopic";
    // Add other topic constants as needed
};
```

#### Step 3: Regenerate DDS Code (If IDL Changed)
```bash
cd ../../dds/cxx11 && rm -rf build && mkdir build && cd build
cmake .. && make -j4
```

#### Step 4: Create Application Using GitHub Copilot

1. **Use the Build Prompt**: Open `.github/prompts/build_cxx.prompt.md` in your editor

2. **Define Your Application**: Use GitHub Copilot Chat with a command like:
   ```
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with [READERS] as reader(s) and [WRITERS] as writer(s)
   ```
   
   **Example Commands:**
   ```bash
   # Sensor monitoring app
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with Position and State as readers and Command as writer
   
   # Control system app  
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with Button as reader and Config, State, Command as writers
   
   # Data collection app
   Follow instructions in build_cxx.prompt.md. Create a new cxx app with Button, Position, State as readers and Image as writer
   ```

3. **Copilot Will Generate**:
   - Application directory structure
   - `CMakeLists.txt` with proper dependencies
   - `application.hpp` for command-line parsing
   - Main application file with your specified readers/writers
   - Proper DDS interface setup and message processing

#### Step 5: Build and Test Your Application

```bash
cd your_new_app_name && mkdir build && cd build
cmake .. && make -j4

# Test the application
./your_new_app_name --help
./your_new_app_name
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

#### **DDSContext Setup**
```cpp
// Centralized DDS participant management
auto dds_context = std::make_shared<DDSContext>(
    domain_id, 
    ASYNC_WAITSET_THREADPOOL_SIZE, 
    qos_file_path, 
    qos_profile, 
    APP_NAME
);
```

#### **DDSInterface Creation** 
```cpp
// Reader example
auto button_interface = std::make_shared<DDSInterface<example_types::Button>>(
    dds_context,
    KIND::READER,
    topics::BUTTON_TOPIC,
    qos_file_path,
    dds_config::ASSIGNER_QOS
);

// Writer example
auto config_interface = std::make_shared<DDSInterface<example_types::Config>>(
    dds_context,
    KIND::WRITER, 
    topics::CONFIG_TOPIC,
    qos_file_path,
    dds_config::ASSIGNER_QOS
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

// Enable async processing
your_interface->enable_async_waitset(process_your_data);
```

#### **Message Publishing**
```cpp
// Publishing loop with error handling
while (!application::shutdown_requested) {
    try {
        your_message.field1("value");
        your_message.field2(42);
        your_interface->writer().write(your_message);
        std::cout << "[YOUR_TYPE] Published: " << your_message << std::endl;
    } catch (const std::exception &ex) {
        logger.error("Failed to publish: " + std::string(ex.what()));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
}
```

### Best Practices for New Applications

1. **Follow Naming Conventions**: Use descriptive names that reflect your application's purpose
2. **Use Existing Data Types**: Leverage existing IDL types when possible to maintain interoperability  
3. **Consistent QoS Profiles**: Use `dds_config::ASSIGNER_QOS` for flexible XML-based QoS configuration
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
- **Build Errors**: Ensure DDS utility library is built first (`../../dds/cxx11/build/`)
- **Runtime Errors**: Check NDDSHOME environment variable
- **No Communication**: Verify all applications use same domain ID and QoS profiles
- **Missing Types**: Rebuild DDS utilities after IDL changes

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
- **Generated Headers**: ExampleTypes.hpp, DDSDefs.hpp
- **Utility Classes**: DDSContext.hpp, DDSInterface.hpp

## Getting Started

1. **Try the Example**: Build and run `example_io_app`
2. **Follow the Prompt**: Use `.github/prompts/build_cxx.prompt.md` with GitHub Copilot
3. **Create Your App**: Define readers/writers and let Copilot generate the code
4. **Test Integration**: Verify cross-language communication works
5. **Monitor with RTI Tools**: Use Admin Console to observe system behavior

The combination of GitHub Copilot, structured prompts, and proven utility classes enables rapid development of robust DDS applications with minimal boilerplate code.