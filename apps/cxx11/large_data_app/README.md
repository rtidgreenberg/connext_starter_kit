# Large Data C++ Application

C++ application demonstrating high-performance transfer of large data (~900 KB images) using RTI Connext DDS with shared memory transport.

## Overview

This application publishes and subscribes to Image data using the `LARGE_DATA_PARTICIPANT` and `LARGE_DATA_SHMEM` QoS profiles optimized for large data transfers with shared memory.

**Key Features**:
- Large data transfer using Image type (640x480 RGB = ~900 KB)
- Uses `LARGE_DATA_PARTICIPANT` QoS profile (DPLibrary::LargeDataSHMEMParticipant)
- Uses `LARGE_DATA_SHMEM` QoS profile for readers/writers
- Shared memory transport for efficient intra-host communication
- Both publisher and subscriber in single application
- Event-driven async reader with `AsyncWaitSet`
- RTI Distributed Logger integration

## Prerequisites

- RTI Connext DDS 7.3.0+
- CMake 3.12+
- C++14 compiler (GCC 7.3.0+)
- DDS types generated (see Building section)

## Building

### Generate DDS Types

```bash
cd ../../../dds/build
cmake .. && make -j4
```

### Build Application

```bash
cd apps/cxx11/large_data_app
mkdir -p build && cd build
cmake ..
make -j4
```

## Running

### From Build Directory

```bash
cd build
./large_data_app
```

### Command-line Options

```bash
./large_data_app [OPTIONS]

Options:
  -d, --domain <ID>       Domain ID (default: 1)
  -v, --verbosity <LEVEL> Logging verbosity (default: 1)
  -q, --qos-file <PATH>   QoS XML path (default: ../../../../dds/qos/DDS_QOS_PROFILES.xml)
  -h, --help             Show help
```

### Run Multiple Instances

**Terminal 1**:
```bash
cd build
./large_data_app
```

**Terminal 2**:
```bash
cd build
./large_data_app
```

Both instances will publish and receive Image data from each other.

## Application Architecture

### Data Flow

```
Publisher → Image (~900 KB) → Shared Memory → AsyncWaitSet → Subscriber Callback
    ↓                                                              ↓
 1 Hz rate                                                  Process Image
```

### QoS Profiles Used

- **Participant**: `LARGE_DATA_PARTICIPANT` (DPLibrary::LargeDataSHMEMParticipant)
  - Optimized for large data with increased resource limits
  - 3 MB message_size_max for shared memory transport
- **DataWriter**: `LARGE_DATA_SHMEM` - Reliable, keep-all history, shared memory transport
- **DataReader**: `LARGE_DATA_SHMEM` - Reliable, keep-all history, shared memory transport

### Image Data

```cpp
Image {
    image_id: "img_000001"      // Unique identifier
    width: 640                  // Pixels
    height: 480                 // Pixels  
    format: "RGB"               // 3 bytes per pixel
    data: std::vector<uint8_t>  // ~900 KB payload (921,600 bytes)
}
```

## Expected Output

```
Large Data application starting on domain 1
Using QoS file: ../../../../dds/qos/DDS_QOS_PROFILES.xml
Using QoS profile: DPLibrary::LargeDataSHMEMParticipant
DL Info: : Large Data app is running. Press Ctrl+C to stop.
DL Info: : Subscribing to Image messages with LARGE_DATA_SHMEM QoS...
DL Info: : Publishing Image messages with LARGE_DATA_SHMEM QoS...
[IMAGE_PUBLISHER] Published Image - ID: img_000000, Size: 921600 bytes (640x480)
DL Info: : Published Image - id:img_000000, size:921600 bytes, 640x480
[IMAGE_SUBSCRIBER] Image Received:
  Image ID: img_000000
  Width: 640
  Height: 480
  Format: RGB
  Data Size: 921600 bytes
  Topic: Image
```

## Performance Characteristics

- **Data Size**: ~900 KB per sample (640x480x3 = 921,600 bytes)
- **Publishing Rate**: 1 Hz (configurable)
- **Transport**: Shared memory (UDPv4 fallback for remote peers)
- **Throughput**: Typically >50 MB/sec on modern hardware with shared memory
- **Latency**: Sub-millisecond for intra-host shared memory transfers
- **Processing**: Event-driven async callbacks (no polling overhead)

## Code Structure

```
large_data_app/
├── large_data_app.cxx     # Main application
├── application.hpp        # Command-line parsing and signal handling
├── CMakeLists.txt        # Build configuration
├── README.md             # This file
└── build/                # Build directory (created during build)
    └── large_data_app    # Executable
```

**Key Components**:
- `process_image_data()` - Callback function for received Image samples
- `run()` - Main application logic with publisher loop
- `DDSContextSetup` - Participant and AsyncWaitSet management
- `DDSReaderSetup<Image>` - Event-driven Image subscriber
- `DDSWriterSetup<Image>` - Image publisher

## Customization

### Change Image Size

Edit constants in `large_data_app.cxx`:
```cpp
constexpr uint32_t IMAGE_WIDTH = 640;   // Change resolution
constexpr uint32_t IMAGE_HEIGHT = 480;
constexpr uint32_t IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT * 3;
```

**Note**: Keep size under MAX_IMAGE_DATA_SIZE (3 MB) defined in ExampleTypes.idl

### Change Publishing Rate

Modify sleep duration:
```cpp
std::this_thread::sleep_for(std::chrono::seconds(1));  // Change to desired rate
```

### Use Zero-Copy QoS

For maximum performance with FlatData types (requires FinalFlatImage):
```cpp
auto image_writer = std::make_shared<DDSWriterSetup<example_types::FinalFlatImage>>(
    dds_context,
    topics::FINAL_FLAT_IMAGE_TOPIC,
    qos_file_path,
    qos_profiles::LARGE_DATA_SHMEM_ZC);
```

See [fixed_image_flat_zc](../fixed_image_flat_zc/README.md) for zero-copy implementation.

## Troubleshooting

**Issue**: "Shared memory segment allocation failed"  
**Solution**: Increase system shared memory limits or reduce IMAGE_SIZE

**Issue**: Compilation errors about missing headers  
**Solution**: Ensure DDS types are generated: `cd ../../../dds/build && make -j4`

**Issue**: Runtime error "cannot open shared object file"  
**Solution**: Check RPATH is set correctly or run from build directory

**Issue**: Low throughput or high latency  
**Solution**: Verify shared memory transport is active (check with rtiddsspy)

**Issue**: "incompatible shared memory segment" errors  
**Solution**: Clean old shared memory segments: `rm -rf /dev/shm/rti*`

## Related Documentation

- **[C++ Applications Guide](../README.md)** - C++ development setup
- **[DDS Layer](../../../dds/README.md)** - Data models and QoS profiles
- **[Zero-Copy Large Data](../fixed_image_flat_zc/README.md)** - FlatData zero-copy implementation
- **[Python Large Data App](../../python/large_data_app/README.md)** - Python equivalent
- **[RTI Shared Memory Transport](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/html_files/RTI_ConnextDDS_CoreLibraries_UsersManual/Content/UsersManual/SHMEM_Transport.htm)**

## Next Steps

- Experiment with different image sizes and publishing rates
- Monitor performance using RTI Admin Console or rtiddsspy
- Compare with zero-copy FlatData implementation
- Add image processing logic in subscriber callback
- Test cross-language communication with Python large_data_app
