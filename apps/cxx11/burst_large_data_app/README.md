# Burst Large Data Applications

This applications simulate a burst of large data (Point Clouds) at a high rate
over a Local Area Network. For this use case, no samples can be lost, so the DW
and the DR use the `BurstLargeDataUdpQoS` profile. This profile applies Strict
Reliability (KEEP_ALL + RELIABLE) and some optimizations for high rate data.

You can test this example over your loopback interface or across the LAN. It's
important that you set up your send/receive socket buffer sizes to a higher
value before you start the applications. Unfortunately, Linux systems do not
use default values that are high enough to support this use case. You can easily
increase the size of your socket buffers with the
[optimize_socket_buffers.sh](../../../tools/optimize_socket_buffers.sh)
script.

## Description

The publisher waits for 1 DR to match before it starts to send the burst. The
data is sent a fixed rate that can be controlled with the `--send-rate` argument
in Hz. The burst duration can be configured with the `--burst-duration` in
seconds.

The publisher will print some statistics once the data is sent and fully
acknowledged by the subscriber.

The subscriber will print a message every 100 samples. I will also print a
warning if data is ever lost.

## Building

The applications are built as part of the top-level project build:

```bash
cd /path/to/connext_starter_kit
mkdir -p build && cd build
cmake ..
cmake --build .
```

This will create two executables in the build directory:

- `./build/apps/cxx11/burst_large_data_app/burst_publisher`
- `./build/apps/cxx11/burst_large_data_app/burst_subscriber`

## Running

### Set up the OS send/receive socket buffer sizes

Simply run this script on both machines (if over LAN) or just the local machine
(if the applications will communicate over loopback):

```sh
sudo /path/to/connext_starter_kit/tools/optimize_socket_buffers.sh
```

### Using Run Scripts

```bash
cd /path/to/connext_starter_kit

# Terminal 1: Start subscriber
./apps/cxx11/burst_large_data_app/run_subscriber.sh

# Terminal 2: Start publisher
./apps/cxx11/burst_large_data_app/run_publisher.sh
```

Or directly from the build directory:

```bash
cd /path/to/connext_starter_kit/build
./apps/cxx11/burst_large_data_app/burst_publisher
./apps/cxx11/burst_large_data_app/burst_subscriber
```
```

### Publisher

Run the publisher:

```bash
./burst_publisher --send-rate 100 --burst-duration 10
```

Expected output:

```bash
DL Info: : Burst publisher app is running. Press Ctrl+C to stop.
Waiting indefinitely for DataReaders to match with the DataWriter...
```

The publisher is configured to wait for a DataReader to match before it starts
sending the data.

### Subscriber

As soon as you start the subscriber, it will start receiving data:

```bash
./burst_subscriber
```

Expected output:

```bash
[Reader] Subscription matched event for topic: PointCloud
  Current count: 1
  Current count change: 1
  Total count: 1
  Total count change: 1
...
DL Info: : Burst subscriber app is running. Press Ctrl+C to stop.
Samples received: 100, size: 512000 B
Samples received: 200, size: 512000 B
```

Ctrl+C the subscriber when the test is over.

## Back to the publisher

Once the burst has been sent, the DW will wait for samples to be acknowledged
and print statistics before exiting. Expected output:

```bash
DL Info: : Published ID: 1000 point clouds
DL Info: : DataReader has confirmed that it has received all the samples.

Burst statistics:
  Samples sent: 1000
  Total duration: 10022 ms (10.022000 seconds)
  Average time per point cloud: 10 ms
  Actual send rate: 99.780483 Hz

DL Info: : Burst publisher application shutting down...
```

## Features

- **FlatData Performance**: Uses `@final` FlatData for maximum performance
- **Asynchronous Processing**: Subscriber uses event-driven processing with AsyncWaitSet
- **Large Data Transfer**: Optimized for 500 KB Point Cloud data transfer

## Notes

- Uses zero-copy FlatData for maximum performance
- Point cloud is filled with a simple buffer in the publisher
- Subscriber uses asynchronous processing by default
- Requires Connext DDS environment variables to be set
- Both applications share the same application.hpp header file

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
