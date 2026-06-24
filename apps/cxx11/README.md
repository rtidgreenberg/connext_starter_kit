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

### [`parameter_app/`](./parameter_app/) - ROS2-Style Parameter Management
DDS-based parameter server/client using RTI Request-Reply:
- **Server Mode**: Loads parameters from YAML, serves get/set/list requests
- **Client Mode**: Sends parameter requests to a named server node
- **Parameter Events**: Publishes parameter change notifications
- **YAML Configuration**: Load initial parameters from file

### [`foxglove_geojson/`](./foxglove_geojson/) - GeoJSON Map Visualization
Publishes GeoJSON data for Foxglove Studio map panels:
- **GeoJSON Publishing**: Geographic feature data at ~2 Hz
- **Config Subscriber**: Runtime configuration via Config topic
- **Foxglove Compatible**: Uses `foxglove::GeoJSON` OMG IDL schema

### [`foxglove_rawimage/`](./foxglove_rawimage/) - Raw Image Streaming
Publishes raw image data for Foxglove Studio image panels:
- **High-Rate Publishing**: 640x480 RGB images at ~100 Hz
- **~900 KB Payloads**: Uncompressed `rgb8` format
- **Shared Memory**: Uses `LARGE_DATA_SHMEM` QoS for efficient transfer

### [`foxglove_gstreamvideo_app/`](./foxglove_gstreamvideo_app/) - GStreamer H.264 Video
Publishes compressed H.264 video for Foxglove Studio video panels:
- **GStreamer Pipeline**: `videotestsrc` → H.264 encoder → DDS
- **Compressed Video**: Uses `foxglove::CompressedVideo` type
- **Requires GStreamer**: See [README](./foxglove_gstreamvideo_app/README.md) for install instructions

### [`foxglove_pointcloud/`](./foxglove_pointcloud/) - 3D Point Cloud Visualization
Publishes point cloud and frame transform data for Foxglove 3D panels:
- **Point Cloud Data**: Simulated lidar at ~10 Hz
- **Frame Transforms**: Publishes `world` → `lidar` transform
- **Foxglove Compatible**: Uses `foxglove::PointCloud` and `foxglove::FrameTransform` schemas



The combination of GitHub Copilot, structured prompts, and proven utility classes enables rapid development of robust DDS applications with minimal boilerplate code.

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
