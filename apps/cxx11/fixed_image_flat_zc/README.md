# Fixed Image Flat ZC Application

USE CASE: 
Large fixed size data low latency transfer intra-host as well as inter-host.

FlatData is used as an optimization for message transfers between hosts over UDP.   If only sending data within a host can do pure Zero Copy.

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
- **No serialization**: FlatData sends raw memory without serialization step
- **Skips copy steps**: No intermediate buffers on send or receive
- **Endianness requirement**: Sender and receiver must have same byte order (both little-endian or both big-endian)
- **Network efficiency**: Reduced CPU and lower latency compared to traditional serialization

### Performance Characteristics
- **Reduced latency**: Eliminates serialization/deserialization and extra copy operations
- **Lower CPU usage**: No data marshaling or buffer management
- **Efficient for large data**: Ideal for images, video frames, sensor data, and large payloads
- **Predictable performance**: Fixed memory layout provides consistent access patterns

## Data Consistency with Zero-Copy

### Challenge: Direct Memory Access
With zero-copy shared memory (`SHMEM_REF`), readers access the writer's memory directly. This creates a data consistency challenge: the writer could modify or reuse the memory while readers are still accessing it, potentially causing data corruption.

### Solution: Application-Level Acknowledgment
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

**Note:** Without `wait_for_acknowledgments()`, readers might see inconsistent data as the writer modifies shared memory. This is critical for zero-copy scenarios where memory is accessed directly rather than copied.

## Building

```bash
cd build
cmake ..
make
```

## Running

```bash
./fixed_image_flat_zc
```

### Command-line Options

- `-d, --domain <int>`: Domain ID (default: 1)
- `-v, --verbosity <int>`: Verbosity level 0-3 (default: 1)
- `-q, --qos-file <str>`: Path to QoS profile XML file

## Implementation Details

Demonstrates the `@final` FlatData zero-copy loan API pattern:

1. Creates DomainParticipant with AsyncWaitSet support
2. Sets up DataWriter for FinalFlatImage using zero-copy loan API
3. Sets up DataReader for FinalFlatImage with event-driven callbacks
4. Publishes 3 MB FinalFlatImage samples at 10 Hz using direct memory access
5. Receives and processes samples asynchronously without copying

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
