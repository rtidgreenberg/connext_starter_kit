# FinalFlatImage Application

This application demonstrates the use of RTI Connext DDS FlatData API with Zero Copy transfer for high-performance, low-latency image data distribution.

## Overview

The FinalFlatImage application showcases:
- **FlatData with Zero Copy**: Using `@final @language_binding(FLAT_DATA)` with `@transfer_mode(SHMEM_REF)`
- **Intra-host zero-copy**: Within a single host, data is accessed directly in shared memory with **no copies**
- **Inter-host FlatData**: Between hosts, FlatData sends data **without serialization** (requires same endianness)
- **Zero-copy loan API**: Direct memory access for writing and reading samples
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

## Building

```bash
cd build
cmake ..
make
```

## Running

```bash
./flat_image_app
```

### Command-line Options

- `-d, --domain <int>`: Domain ID (default: 1)
- `-v, --verbosity <int>`: Verbosity level 0-3 (default: 1)
- `-q, --qos-file <str>`: Path to QoS profile XML file

## Implementation Details

The application demonstrates the `@final` FlatData zero-copy loan API pattern:

1. Creates a DDS DomainParticipant with AsyncWaitSet support
2. Sets up a DataWriter for FinalFlatImage using the zero-copy loan API
3. Sets up a DataReader for FinalFlatImage with event-driven callbacks
4. Publishes FinalFlatImage samples at 1 Hz using direct memory access
5. Receives and processes FinalFlatImage samples asynchronously without copying

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

// Write transfers ownership - no discard needed
writer.write(*sample);
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
