# Fixed Image Flat ZC Application

USE CASE: 
Large fixed size data low latency transfer intra-host as well as inter-host.

FlatData is used as an optimization for message transfers between hosts over UDP.   
If only sending data within a host can do pure Zero Copy.

## Table of Contents
- [Overview](#overview)
- [FlatData + Zero Copy Benefits](#flatdata--zero-copy-benefits)
- [Data Consistency with Zero-Copy](#data-consistency-with-zero-copy)
- [Building and Running](#building-and-running)
- [Implementation Details](#implementation-details)
- [Type Definition](#type-definition)
- [Considerations for RTI Services](#considerations-for-rti-services)
- [Resources](#resources)

## Overview

This application showcases:
- **FlatData with Zero Copy**: Using `@final @language_binding(FLAT_DATA)` with `@transfer_mode(SHMEM_REF)`
- **High Throughput**: Example: 3 MB payloads at 10 Hz for ~30 MB/second sustained throughput
- **Intra-host zero-copy**: Data accessed directly in shared memory with **no copies**
- **Inter-host FlatData**: Between hosts, data sent **without serialization** (requires same endianness)
- **Zero-copy loan API**: Direct memory access for writing and reading samples
- **Application Acknowledgment**: Uses `wait_for_acknowledgments()` to ensure data consistency with zero-copy shared memory access
- Event-driven data processing with AsyncWaitSet

## FlatData + Zero Copy Benefits

### Intra-Host (Same Machine)
- **True zero-copy**: No copies made within the host - data stays in shared memory
- **Direct memory access**: Reader accesses the exact memory written by the writer
- **Maximum performance**: Eliminates all memory copies and serialization overhead

### Inter-Host (Network)
- **XCDR2 encoding**: FlatData samples use XCDR encoding version 2 (XCDR2) with host platform endianness
- **Application-level serialization**: Data is serialized once at application level when created and stored in that format
- **Fast access**: Setters and getters don't need to change endianness, enabling direct memory access
- **Endianness requirement**: Sender and receiver must have same byte order (both little-endian or both big-endian)
- **Network efficiency**: No additional serialization step during transmission - buffer sent as-is

**Note:** For large data transmission over UDP, increase OS socket buffer sizes to prevent packet loss. See [RTI Perftest OS Tuning Guide](https://community.rti.com/static/documentation/perftest/current/tuning_os.html) for configuration details.

### Performance Characteristics
- **Reduced latency**: Eliminates runtime serialization/deserialization operations
- **Lower CPU usage**: No data marshaling during send/receive
- **Efficient for large data**: Ideal for images, video frames, sensor data, and large payloads
- **Predictable performance**: Fixed XCDR2 memory layout provides consistent access patterns

## Data Consistency with Zero-Copy

### Challenge: Direct Memory Access
With zero-copy shared memory (`SHMEM_REF`), readers access the writer's memory directly. This creates a data consistency challenge: the writer could modify or reuse the memory while readers are still accessing it, potentially causing data corruption.

### Solution 1: Application-Level Acknowledgment
This application uses `wait_for_acknowledgments()` after each write to ensure data consistency:

```cpp
// Write sample to shared memory
writer->write(*sample);

// Wait for all readers to acknowledge receipt
// This ensures readers have finished accessing the shared memory
// before the writer modifies or reuses it
writer->wait_for_acknowledgments(dds::core::Duration(5, 0));
```

**Benefits:**
- **Prevents data corruption**: Writer waits before reusing memory
- **Reliable zero-copy**: Maintains data integrity with direct memory access
- **Flow control**: Naturally throttles writer based on reader processing speed
- **Production-ready pattern**: Recommended practice for zero-copy implementations

**Tradeoff:** Adds latency as writer blocks waiting for acknowledgments

**Note:** Without `wait_for_acknowledgments()`, readers might see inconsistent data as the writer modifies shared memory. This is critical for zero-copy scenarios where memory is accessed directly rather than copied.

### Solution 2: Increase DataWriter Loaned Sample Buffer

Instead of blocking on acknowledgments, increase the writer's loaned sample allocation to prevent buffer overwrites while readers are processing:

```xml
<!-- In DDS_QOS_PROFILES.xml -->
<datawriter_qos>
    <resource_limits>
        <writer_loaned_sample_allocation>
            <initial_count>10</initial_count>
            <max_count>20</max_count>
        </writer_loaned_sample_allocation>
    </resource_limits>
</datawriter_qos>
```

**Benefits:**
- **No blocking**: Writer continues publishing without waiting for acknowledgments
- **Higher throughput**: Eliminates acknowledgment wait time
- **Handles burst traffic**: Buffer accommodates temporary reader slowdowns
- **Flexible sizing**: Tune buffer based on reader processing speed and publishing rate

**Tradeoff:** Increased memory usage (each slot holds 3 MB in this example)

**Sizing Guidance:**
- `initial_count`: Number of pre-allocated loaned samples (e.g., 10 = 30 MB for 3 MB samples)
- `max_count`: Maximum samples before blocking (set higher for burst handling)
- Formula: `buffer_size ≥ (publish_rate × reader_processing_time) + safety_margin`

**When to Use:**
- High-frequency publishing where acknowledgment latency is unacceptable
- Multiple readers with varying processing speeds
- Bursty publishing patterns that need buffering

## Building and Running

### Prerequisites

- RTI Connext DDS 7.3.0+ installed and licensed
- C++14 compiler (GCC 7.3.0+)
- CMake 3.12+
- DDS shared library built from `../../../dds/cxx11/`

### Environment Setup

```bash
# Set RTI Connext DDS environment
export NDDSHOME=/path/to/rti_connext_dds-7.3.0

# Verify DDS library is built
ls ../../../dds/cxx11/build/lib/libdds_utils_datamodel.so
```

### Build

```bash
# Create build directory
mkdir -p build && cd build

# Configure and build
cmake ..
make -j4
```

### Run

```bash
# Run from build directory (for correct QoS file path)
./fixed_image_flat_zc
```

### Command-line Options

```bash
./fixed_image_flat_zc [OPTIONS]

Options:
  -d, --domain <int>    Domain ID (default: 1)
  -v, --verbosity <int> RTI verbosity level 0-3 (default: 1)
  -q, --qos-file <str>  Path to QoS profile XML file
                        (default: ../../../../dds/qos/DDS_QOS_PROFILES.xml)
  -h, --help           Show this help message

Examples:
  ./fixed_image_flat_zc                        # Run with defaults
  ./fixed_image_flat_zc -d 0                   # Use domain 0
  ./fixed_image_flat_zc -v 3                   # Maximum verbosity
  ./fixed_image_flat_zc -d 5 -v 2              # Domain 5, verbosity 2
```

### Expected Output

```
FinalFlatImage application starting on domain 1
DDSContextSetup created with QoS profile: DPLibrary::DefaultParticipant
DataWriter created on topic: FinalFlatImage with QoS profile: DataPatternsLibrary::LargeDataSHMEM_ZCQoS
DataReader created on topic: FinalFlatImage with QoS profile: DataPatternsLibrary::LargeDataSHMEM_ZCQoS
[FINAL_FLAT_IMAGE] Published - ID: 0, Width: 640, Height: 480, Format: 0 (RGB), Data size: 3145728 bytes
[FINAL_FLAT_IMAGE] Received - ID: 0, Width: 640, Height: 480, Format: 0, Data array size: 3145728 bytes
All samples acknowledged by all reliable DataReaders.
...
```

### Performance Monitoring

Watch for these metrics in the output:
- **Publishing rate**: ~10 Hz (samples per second)
- **Acknowledgment status**: "All samples acknowledged" confirms readers processed data
- **Send window size**: Shows maximum unacknowledged samples (default: 40)
- **Sequence numbers**: Track sample flow and potential drops

### Troubleshooting

**Problem:** QoS file not found
```
Solution: Run from the build/ directory, or provide absolute path with -q option
```

**Problem:** Writer blocked waiting for acknowledgments
```
Solution: Increase writer_loaned_sample_allocation in QoS profile (see Solution 2)
```

**Problem:** Domain mismatch - no data flowing
```
Solution: Ensure both publisher and subscriber use same domain ID (-d option)
```

**Problem:** High CPU usage
```
Solution: Verify SHMEM_REF transport is being used (check QoS profile)
```

## Implementation Details

### Zero-Copy Loan API Usage (Writer)

```cpp
// Get a loan from the writer - provides direct access to shared memory
auto writer = final_flat_image_writer->writer();
auto sample = writer->get_loan();

// Access the root and set fields directly (zero-copy)
auto root = sample->root();
root.image_id(count);
root.width(640);
root.height(480);
root.format(0); // 0=RGB

// Populate the fixed-size data array directly
auto data_array = root.data();
for (int i = 0; i < data_size; i++) {
    data_array.set_element(i, static_cast<uint8_t>(i % 256));
}

// Write transfers ownership to DDS
writer->write(*sample);

// CRITICAL: Wait for acknowledgments to ensure data consistency
// Readers access shared memory directly, so we must wait for them
// to finish before modifying or reusing this memory
writer->wait_for_acknowledgments(dds::core::Duration(5, 0));
```

### Zero-Copy Access (Reader)

```cpp
// Access data directly from shared memory
auto root = sample.data().root();
auto image_id = root.image_id();
auto width = root.width();
auto height = root.height();
auto format = root.format();
auto data_array = root.data();
```

## Type Definition

The FinalFlatImage type is defined in `ExampleTypes.idl`:

```idl
@final
@transfer_mode(SHMEM_REF)
@language_binding(FLAT_DATA)
struct FinalFlatImage {
    @key unsigned long image_id;       // Numeric image identifier
    unsigned long width;                // Image width in pixels
    unsigned long height;               // Image height in pixels
    unsigned long format;               // Format code: 0=RGB, 1=RGBA, etc.
    octet data[MAX_IMAGE_DATA_SIZE];   // Fixed-size image data array
};
```

### Key Annotations
- `@final`: Maximum performance - requires only fixed-size types (no strings/sequences)
- `@language_binding(FLAT_DATA)`: Enables FlatData API with direct memory access
- `@transfer_mode(SHMEM_REF)`: Enables zero-copy via shared memory references

### Design Notes
- **@final vs @mutable**: `@final` provides best performance but requires fixed-size types only (primitives, fixed arrays)
- **Endianness**: Inter-host communication requires matching byte order
- **Fixed arrays**: `octet data[1024]` provides predictable memory layout for zero-copy access

## Considerations for RTI Services

### Routing Service and Recording Service Limitations

**Important:** RTI Routing Service and Recording Service only support FlatData/Zero-Copy (`SHMEM_REF`) on the **subscription side**. This has significant implications for system design:

#### Recording Limitations
- Recording Service can **record** FlatData with zero-copy (as a subscriber)
- Recording Service **cannot replay** with zero-copy transfer mode
- **Replay requires**: Regular shared memory (`SHMEM`) with large receive buffers configured

#### Impact on System Configuration
When designing systems that use both FlatData/Zero-Copy and RTI services:

1. **QoS Compatibility**: Publishers must be configured to support both:
   - Zero-copy transfer (`SHMEM_REF`) for direct subscribers
   - Regular shared memory (`SHMEM`) for services that replay data

2. **Receive Buffer Sizing**: Systems using replay must configure appropriately sized receive buffers to handle large data without zero-copy optimization

3. **Architecture Considerations**: 
   - Live data path: Can use zero-copy for maximum performance
   - Replay/routing path: Must account for additional memory overhead
   - Plan QoS profiles to accommodate both modes if services are required

**Reference:** [Routing Service - Support for FlatData and Zero-Copy Transfer](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/services/routing_service/configuration.html#support-for-rti-flatdata-and-zero-copy-transfer-over-shared-memory)

## Resources

### RTI Documentation
- [Sending Large Data](https://community.rti.com/static/documentation/connext-dds/7.3.1/doc/manuals/connext_dds_professional/users_manual/users_manual/SendingLargeData.htm) - Best practices for large data transfer in RTI Connext DDS

### RTI Examples
- [FlatData API Example](https://github.com/rticommunity/rticonnextdds-examples/tree/release/7.1.0/examples/connext_dds/flat_data_api/c%2B%2B11) - Complete FlatData API usage examples
- [FlatData Latency Example](https://github.com/rticommunity/rticonnextdds-examples/tree/release/7.1.0/examples/connext_dds/flat_data_latency/c%2B%2B11) - FlatData performance and latency optimization
- [GStreamer Plugin using Connext with C API](https://github.com/rticommunity/rticonnextdds-usecases/tree/00a42b44469d99e25237b00f4ee22cc508caeee5/VideoData) - GStreamer integration for video data streaming with RTI Connext DDS
