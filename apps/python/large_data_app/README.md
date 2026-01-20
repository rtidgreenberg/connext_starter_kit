# Large Data Python Application

Python application demonstrating high-performance transfer of large data (multi-megabyte images) using RTI Connext DDS with shared memory transport.

## Overview

This application publishes and subscribes to Image data (~900 KB per sample) using the `LARGE_DATA_PARTICIPANT` and `LARGE_DATA_SHMEM` QoS profiles optimized for large data transfers.

**Key Features**:
- Large data transfer using Image type (640x480 RGB = ~900 KB)
- Uses `LARGE_DATA_PARTICIPANT` QoS profile (LargeDataSHMEMParticipant)
- Uses `LARGE_DATA_SHMEM` QoS profile for readers/writers
- Shared memory transport for efficient intra-host communication
- Both publisher and subscriber in single application
- RTI Distributed Logger integration (using existing participant)

## Prerequisites

- RTI Connext DDS 7.3.0+ with Python API
- Python 3.6+
- Virtual environment configured (see [apps/python/README.md](../README.md))

## Building

The Python application uses generated DDS types from the `dds/` directory. Ensure types are generated:

```bash
cd ../../../dds/build
cmake .. && make -j4
```

## Running

### Activate Virtual Environment

```bash
cd apps/python
source connext_dds_env/bin/activate
```

### Run Application

```bash
cd large_data_app
python large_data_app.py
```

**Command-line Options**:
```bash
python large_data_app.py -d 1 -q ../../../dds/qos/DDS_QOS_PROFILES.xml -v 2

Options:
  -d, --domain_id    Domain ID (default: 1)
  -q, --qos_file     Path to QoS profiles XML file
  -v, --verbosity    Logging verbosity (0-5, default: 1)
```

### Run Multiple Instances

**Terminal 1 (Publisher/Subscriber)**:
```bash
python large_data_app.py
```

**Terminal 2 (Publisher/Subscriber)**:
```bash
python large_data_app.py
```

Both instances will publish and receive Image data from each other.

## Application Architecture

### Data Flow

```
Publisher → Image (~900 KB) → Shared Memory → Subscriber
    ↓                                           ↓
 1 Hz rate                                  Process Image
```

### QoS Profiles Used

- **Participant**: `LARGE_DATA_PARTICIPANT` (DPLibrary::LargeDataSHMEMParticipant) - Optimized for large data with increased resource limits
- **DataWriter**: `LARGE_DATA_SHMEM` - Reliable, keep-all history, shared memory transport
- **DataReader**: `LARGE_DATA_SHMEM` - Reliable, keep-all history, shared memory transport

### Image Data

```python
Image {
    image_id: "img_000001"      # Unique identifier
    width: 640                  # Pixels
    height: 480                 # Pixels  
    format: "RGB"               # 3 bytes per pixel
    data: [...]                 # ~900 KB payload (921,600 bytes)
}
```

## Expected Output

```
Loading QoS profiles from: ../../../dds/qos/DDS_QOS_PROFILES.xml
DomainParticipant created with QoS profile: DPLibrary::LargeDataSHMEMParticipant
DOMAIN ID: 1
RTI Distributed Logger configured using existing participant
DL Info: : LargeDataApp initialized with distributed logging enabled
[SUBSCRIBER] RTI Asyncio reader configured for Image data (Large Data with SHMEM)...
[PUBLISHER] RTI Asyncio writer configured for Image data (Large Data with SHMEM)...
[MAIN] Starting RTI asyncio tasks...
[IMAGE_PUBLISHER] Published Image - ID: img_000000, Size: 921600 bytes
DL Info: : Published Image - id:img_000000, size:921600 bytes, 640x480
[IMAGE_SUBSCRIBER] Image Received:
  Image ID: img_000000
  Width: 640
  Height: 480
  Format: RGB
  Data Size: 921600 bytes
DL Info: : Received Image data - id:img_000000, size:921600 bytes, 640x480
[MAIN] LargeDataApp processing loop - iteration 0
DL Info: : Large Data processing loop - iteration: 0
```

## Performance Characteristics

- **Data Size**: ~900 KB per sample (640x480x3 = 921,600 bytes)
- **Publishing Rate**: 1 Hz (configurable via `PUBLISHER_SLEEP_INTERVAL`)
- **Transport**: Shared memory (UDPv4 fallback for remote peers)
- **Throughput**: Depends on system, typically >50 MB/sec on modern hardware with shared memory
- **Latency**: Sub-millisecond for intra-host shared memory transfers

## Code Structure

```python
large_data_app/
├── large_data_app.py          # Main application
└── README.md                  # This file
```

**Key Functions**:
- `process_image_data()` - Async coroutine for receiving Image samples
- `publisher_task()` - Async coroutine for publishing Image samples
- `main_task()` - Application heartbeat and monitoring
- `LargeDataApp.run()` - Main application setup and execution

## Customization

### Change Image Size

Edit constants in `large_data_app.py`:
```python
IMAGE_WIDTH = 640    # Change resolution (current: 640x480)
IMAGE_HEIGHT = 480
IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT * 3  # RGB format
```

**Note**: Keep size under MAX_IMAGE_DATA_SIZE (3 MB) defined in ExampleTypes.idl

### Change Publishing Rate

```python
PUBLISHER_SLEEP_INTERVAL = 1  # Change to desired rate in seconds
```

### Use Zero-Copy QoS

Modify to use `LARGE_DATA_SHMEM_ZC` for maximum performance (requires FlatData types):
```python
image_writer_qos = qos_provider.set_topic_datawriter_qos(
    qos_profiles.LARGE_DATA_SHMEM_ZC, topics.IMAGE_TOPIC
)
```

## Troubleshooting

**Issue**: "Shared memory segment allocation failed"  
**Solution**: Increase system shared memory limits or reduce `IMAGE_SIZE`

**Issue**: Low throughput or high latency  
**Solution**: Verify shared memory transport is active (check rtiddsspy output)

**Issue**: Out of memory errors  
**Solution**: Reduce publishing rate or image size, check participant resource limits

## Related Documentation

- **[Python Applications Guide](../README.md)** - Python setup and development
- **[DDS Layer](../../../dds/README.md)** - Data models and QoS profiles
- **[Large Data C++ Example](../../cxx11/fixed_image_flat_zc/README.md)** - Zero-copy FlatData implementation
- **[RTI Shared Memory Transport](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/html_files/RTI_ConnextDDS_CoreLibraries_UsersManual/Content/UsersManual/SHMEM_Transport.htm)**

## Next Steps

- Experiment with different image sizes and publishing rates
- Monitor performance using RTI Admin Console or rtiddsspy
- Compare with C++ zero-copy implementation using FlatData
- Add image processing logic in subscriber callback
