# Tools

This directory contains utility tools for RTI Connext DDS development and debugging.

## Quick Start

1. **Get an RTI license** - Visit https://www.rti.com/get-connext

2. **Check your email** - You'll receive an automated email with `rti_license.dat` within minutes

3. **Set the license environment variable:**
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

4. **Run RTI Spy:**
   ```bash
   ./run_rtispy.sh --domain 1
   ```

That's it! The run script automatically handles NDDSHOME detection, virtual environment setup, and dependency installation.

---

## optimize_socket_buffers.sh

Optimizes Linux socket buffer sizes for better DDS network performance. Useful for large data transfers or high-throughput scenarios.

```bash
sudo ./optimize_socket_buffers.sh
```

This sets `rmem_max` and `wmem_max` to 10 MB for improved UDP performance.

---

## rtispy.py

### Dependencies
- RTI Python API
- Textual

### Manual Installation

Installation is handled automatically by `run_rtispy.sh`. For manual installation:

```bash
cd tools
./install.sh
```

The script will:
- Auto-detect `NDDSHOME` from `~/rti_connext_dds-*`
- Create a shared virtual environment at the repository root (`connext_dds_env/`)
- Install RTI Connext Python API (version 7.3.0)
- Install Textual UI framework
- Verify all installations

### Overview

RTI Spy is a powerful Python-based monitoring tool for RTI Connext DDS applications that can be deployed without requiring a separate license. It uses DDS builtin topics to discover participants, DataReaders, and DataWriters in a domain, and can subscribe to any topic using **DynamicData** without requiring compile-time generated code.

> **Note on Licensing**: The license-managed RTI Python libraries from PyPI require a license file. However, if you have a commercial version of RTI Connext installed, you can use `rti.connext.activated` from the [commercial Python packages](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/installation_guide/installing.html#installing-commercial-python-c-or-ada-packages) in your activated Connext installation to deploy RTI Spy without needing a separate license file.

**Key Features:**
- **Discovery-Based Operation**: Uses builtin topics (DCPSParticipant, DCPSSubscription, DCPSPublication) to discover all participants and endpoints
- **No Generated Code Required**: Subscribes to any topic using DynamicData with types discovered at runtime
- **QoS Extraction**: Captures and matches QoS policies (Reliability, Durability, Ownership, Partitions, etc.) from discovered endpoints
- **Distributed Logger Integration**: Monitor logs, view state, and remotely change filter levels
- **Terminal UI**: Navigate using keyboard for headless/SSH use cases

### Usage:

#### Using the Run Script (Recommended)
```bash
./run_rtispy.sh --domain 1
```

#### Manual Execution
```bash
source ../connext_dds_env/bin/activate
export NDDSHOME=~/rti_connext_dds-7.3.0  # or your installation path
export RTI_LICENSE_FILE=$NDDSHOME/rti_license.dat
python rtispy.py --domain 1
```

#### Command-line Options
- `--domain` or `-d`: Specify the DDS domain ID (default: 1)
- `--interval` or `-i`: Set the refresh interval in seconds (default: 10)

#### Example
```bash
./run_rtispy.sh --domain 5 --interval 5
```

---

## How RTI Spy Works

### Discovery Process

RTI Spy creates a DomainParticipant and attaches listeners to builtin topic readers to automatically discover all endpoints in the domain:

```python
# Builtin topics provide discovery information
participant.publication_reader.set_listener(PublicationListener(), ...)
participant.subscription_reader.set_listener(SubscriptionListener(), ...)
```

When DataWriters and DataReaders are discovered:
- **Topic name and type** are extracted from builtin topic data
- **DynamicType** is captured for runtime type support  
- **QoS policies** (Reliability, Durability, Ownership, Partitions, etc.) are stored
- **Participant association** links endpoints to their owning participants

### DynamicData Subscription

When you select a Writer endpoint to monitor, RTI Spy:

1. Creates a `dds.DynamicData.Topic` using the discovered type
2. Configures reader QoS to match or be compatible with writer QoS
3. Places subscriber in matching partitions if needed
4. Creates a `dds.DynamicData.DataReader` - no code generation required

### Distributed Logger Features

RTI Spy provides full integration with RTI Distributed Logger:

- **Log Message Monitoring**: Subscribes to `rti/distlog` topic with ContentFilteredTopic to view logs from selected participant
- **State Monitoring**: Subscribes to `rti/distlog/administration/state` with TRANSIENT_LOCAL durability to receive current filter level
- **Remote Filter Control**: Sends commands using DynamicData request-reply pattern to change log levels without restarting applications

**Filter Level Control** demonstrates complete DynamicData usage:
```python
# Get command type from discovered endpoint
request_type = request_endpoint.type
command_request = dds.DynamicData(request_type)

# Set nested struct fields using dot notation
command_request["targetHostAndAppId.rtps_host_id"] = target_host
command_request["command.filterLevel"] = filter_level

# Wait for discovery before sending
while request_writer.publication_matched_status.current_count == 0:
    await asyncio.sleep(0.1)

request_writer.write(command_request)
```

### User Interface

- **Main Screen**: Lists discovered participants, press Enter to view endpoints, L for distributed logger
- **Endpoint List**: Shows DataReaders/DataWriters, press Enter to subscribe to Writers
- **Topic Monitor**: Displays samples with source IP/port/domain
- **Distributed Logger Dialog**: Four panels showing log messages, state, filter control, and debug info

### Key DDS Concepts Demonstrated

- **QoS Matching**: Reader-drives-matching principle (reader requests equal or less strict QoS)
- **Partitions**: Logical communication channels that must match for endpoints to communicate
- **Discovery Synchronization**: Waiting for publication_matched_status and subscription_matched_status
- **Builtin Topics**: DCPSParticipant, DCPSPublication, DCPSSubscription for automatic discovery
- **DynamicData**: Runtime type support without code generation
- **ContentFilteredTopics**: SQL-like filtering to reduce network traffic

For more details on DDS concepts and implementation, explore the code with inline comments marked with `# DDS:`.

---

## Support

For questions about RTI Connext DDS:
- RTI Community Forums: https://community.rti.com
- RTI Documentation: https://community.rti.com/documentation

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
