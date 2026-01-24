# Downsampled Reader Application

A Python application demonstrating **time-based filtering** and **status listeners** for receiving downsampled data at a reduced rate (1Hz) from a topic that may be published at a higher frequency, with comprehensive awareness of DDS events.

## Quick Start

1. **Get an RTI license** - Visit https://www.rti.com/get-connext

2. **Check your email** - You'll receive an automated email with `rti_license.dat` within minutes

3. **Set the license environment variable:**
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

4. **Run the application:**
   ```bash
   ./run.sh --domain_id 1
   ```

---

## Overview

This application showcases common DDS patterns where:
- **High-frequency data** is published on a topic (e.g., sensor data at 10Hz, 100Hz, or faster)
- **Multiple subscribers** can receive the same data at different rates based on their needs
- **GUI/monitoring applications** subscribe with time-based filtering to reduce CPU load and network bandwidth
- **Control systems** subscribe without filtering to receive every sample for real-time processing
- **Status listeners** provide real-time awareness of publisher health, connectivity, and data flow

### Key Benefits

1. **Independent Reader Filtering**: Each DataReader can apply its own time-based filter without affecting other readers
2. **Bandwidth Optimization**: Reduces data rate for remote monitoring, dashboards, or logging applications
3. **CPU Efficiency**: GUI applications avoid processing high-frequency updates that exceed display refresh rates
4. **Same Topic, Different Rates**: Multiple applications can share the same topic with different QoS settings
5. **DDS Event Awareness**: Status listeners detect publisher connection, disconnection, liveliness changes, and deadline misses

## Use Case: GUI Subscribing to Downsampled Data

### Scenario

Consider a robotic system publishing **Position** data at 50Hz for precise control, but a monitoring GUI that only needs updates at 1Hz:

```
┌─────────────────────────────────┐
│   Robotic Control System        │
│   (Position Publisher)          │
│                                 │
│   Publishing at 50Hz            │
└────────────┬────────────────────┘
             │ DDS Position Topic
             │
       ┌─────┴──────────────────┐
       │                        │
       ↓                        ↓
┌──────────────────┐   ┌──────────────────────┐
│  Control Loop    │   │  Monitoring GUI      │
│  (Full Rate)     │   │  (Downsampled)       │
│                  │   │                      │
│  Receives 50Hz   │   │  Status1HzQoS        │
│  No filter       │   │  Receives 1Hz        │
│  Real-time       │   │  Time-based filter   │
│  control         │   │  Efficient display   │
└──────────────────┘   └──────────────────────┘
```

### Why This Pattern Matters

- **Real-time systems** need every sample for accurate control and state estimation
- **GUIs** cannot update faster than ~60Hz (display refresh) and would waste CPU processing high-frequency data
- **Remote monitoring** over limited bandwidth benefits from reduced data rates
- **Logging systems** may only need periodic snapshots rather than every sample

## How It Works

### Time-Based Filter QoS

The `Status1HzQoS` profile includes a **time-based filter** that limits the rate at which samples are delivered to the DataReader:

```xml
<qos_profile name="Status1HzQoS" base_name="DataPatternsLibrary::StatusQoS">
  <datareader_qos>
    <time_based_filter>
      <minimum_separation>
        <sec>1</sec>
        <nanosec>0</nanosec>
      </minimum_separation>
    </time_based_filter>
  </datareader_qos>
</qos_profile>
```

#### Where Filtering Occurs

**In This Application (Reader-Side Filtering)**:

Since the Position data type has a **@key** field (`source_id`), filtering occurs **on the DataReader side** after samples are received:

1. The DataWriter publishes Position samples at its configured rate
2. All samples are transmitted over the network to subscribing DataReaders
3. The DataReader's TIME_BASED_FILTER (1Hz) filters samples in the middleware
4. Only samples meeting the 1-second minimum_separation are delivered to the application

**Result**: The 1Hz downsampling reduces CPU load in the application, but all samples still traverse the network.

**Writer-Side Filtering Optimization (Not Applicable Here)**:

Writer-side filtering only occurs when ALL of these conditions are met:
- **BEST_EFFORT** reliability (✅ this app has it)
- **Unkeyed data type** (❌ Position has `@key source_id`)
- **Infinite liveliness lease duration** (✅ default for StatusQoS)

Since Position is a keyed type, the optimization doesn't apply. For writer-side filtering, you would need an unkeyed data type.

**Key Points**:
- The DataWriter publishes at its normal rate in application code
- Filtering happens **on the reader side** for keyed data types like Position
- Each DataReader can apply different TIME_BASED_FILTER values independently
- The filtering happens efficiently in the DDS middleware, not in application code
- Application CPU is saved, but network bandwidth is not reduced

### Status Listeners for DDS Event Awareness

This application demonstrates proper use of **DataReader listeners** to monitor DDS communication events in real-time:

#### Implemented Listener Callbacks

1. **`on_subscription_matched`**: Notifies when publishers connect or disconnect
   - Triggers when a compatible DataWriter is discovered on the network
   - Provides current count of matched publishers
   - Useful for detecting new data sources or lost connections

2. **`on_liveliness_changed`**: Monitors publisher health and availability
   - Detects when a publisher becomes alive or loses liveliness
   - Tracks which publishers are actively maintaining their liveliness contract
   - Critical for failover scenarios and redundant publisher detection

3. **`on_requested_deadline_missed`**: Alerts when data is not received within expected timeframe
   - Triggers if no samples received within the deadline period (10 seconds for StatusQoS)
   - Indicates publisher stopped sending, network issues, or system problems
   - Enables proactive alerting before data staleness becomes critical

#### Listener Implementation Pattern

```python
# Define custom listener by inheriting from DataReaderListener
class PositionReaderListener(dds.DataReaderListener):
    def on_subscription_matched(self, reader, status):
        # Handle publisher connection/disconnection
        pass
    
    def on_liveliness_changed(self, reader, status):
        # Handle publisher liveliness changes
        pass
    
    def on_requested_deadline_missed(self, reader, status):
        # Handle deadline violations
        pass

# Create reader and set listener with specific status mask
position_reader = dds.DataReader(participant.implicit_subscriber, topic, qos)
listener = PositionReaderListener()
position_reader.set_listener(
    listener,
    dds.StatusMask.SUBSCRIPTION_MATCHED |
    dds.StatusMask.LIVELINESS_CHANGED |
    dds.StatusMask.REQUESTED_DEADLINE_MISSED
)
```

#### Benefits of Status Listeners

- **Proactive Monitoring**: Detect issues before they impact application functionality
- **Automated Failover**: React to publisher failures and switch to backup sources
- **System Health Dashboard**: Build monitoring UIs showing real-time connection status
- **Diagnostics**: Log events for troubleshooting network or configuration issues
- **Quality of Service**: Verify that QoS contracts (deadline, liveliness) are being met

## Building and Running

### Prerequisites

1. Python 3.8 or later
2. RTI Connext DDS 7.3.0 or later
3. Python virtual environment with RTI Connext Python API

### Setup

```bash
cd apps/python
source connext_dds_env/bin/activate
```

### Running the Application

```bash
cd apps/python/downsampled_reader

# Basic usage (domain 1, default settings)
python downsampled_reader.py

# Specify domain ID
python downsampled_reader.py -d 0

# Enable debug verbosity
python downsampled_reader.py -v 3

# Full options
python downsampled_reader.py --domain_id 1 --verbosity 1 --qos_file ../../../dds/qos/DDS_QOS_PROFILES.xml
```

### Command-Line Options

- `-d, --domain_id`: DDS Domain ID (default: 1)
- `-v, --verbosity`: Logging verbosity level (0=SILENT, 1=EXCEPTION, 2=WARNING, 3=STATUS_ALL)
- `-q, --qos_file`: Path to QoS profiles XML file (default: ../../../dds/qos/DDS_QOS_PROFILES.xml)

## Testing the Downsampling Pattern

### Option 1: Use C++ example_io_app as High-Rate Publisher

Run the example_io_app which publishes Position data continuously:

```bash
# Terminal 1: Start C++ publisher (publishes Position continuously)
cd apps/cxx11/example_io_app/build
./example_io_app -d 1

# Terminal 2: Start downsampled reader (receives at 1Hz max)
cd apps/python/downsampled_reader
python downsampled_reader.py -d 1
```

**Expected Behavior**:
- The C++ application publishes Position samples at its configured rate
- The downsampled_reader receives Position updates at a maximum of 1Hz
- Each received sample shows the timestamp when it was published
- With BEST_EFFORT QoS, some samples may be dropped if network is congested (this is expected for periodic data)

### Option 2: Python example_io_app

```bash
# Terminal 1: Start Python publisher
cd apps/python/example_io_app
python example_io_app.py -d 1

# Terminal 2: Start downsampled reader
cd apps/python/downsampled_reader
python downsampled_reader.py -d 1
```

### Observing the Downsampling

When running, you'll see output like:

```
[POSITION_SUBSCRIBER] Position Received:
  Source ID: Example C++ IO App
  Latitude: 37.7749
  Longitude: -122.4194
  Altitude: 15.0
  Timestamp: 1733876543
```

Even if the publisher sends samples every 100ms (10Hz), the downsampled_reader will only print once per second.

## Real-World Applications

### 1. Robot Fleet Monitoring Dashboard
- **Robots**: Publish telemetry at 100Hz for control systems
- **Dashboard**: Subscribes with 1Hz filter to display fleet status
- **Benefit**: Dashboard remains responsive, doesn't bog down with unnecessary updates

### 2. Sensor Data Logging
- **High-Speed Sensors**: Publish measurements at 1kHz
- **Logger Application**: Subscribes with 10Hz filter to record periodic snapshots
- **Benefit**: Reduces storage requirements while capturing trends

### 3. Remote Site Visualization
- **On-Site Controllers**: Exchange data at 50Hz over local network
- **Remote Operator**: Connects over VPN with 2Hz filter
- **Benefit**: Works over limited bandwidth connections

### 4. Multi-Rate Control Systems
- **Inner Loop**: Subscribes to IMU data at 1kHz for stabilization
- **Outer Loop**: Subscribes to same IMU data at 10Hz for navigation
- **Benefit**: Each control loop gets data at its required rate

## Architecture

```
Publisher Rate: Variable (Fast)
     │
     ├─→ DataWriter publishes samples
     │
     ↓
DDS Topic (e.g., POSITION_TOPIC)
     │
     ├─→ Reader 1 (No filter)     → Receives all samples
     │
     └─→ Reader 2 (1Hz filter)    → Receives max 1 sample/sec
                                     (this application)
```

## QoS Configuration

### Participant QoS
- Uses `DEFAULT_PARTICIPANT` from `DataPatternsLibrary`
- Standard reliability and discovery settings

### DataReader QoS
- Profile: `DataPatternsLibrary::Status1HzQoS`
- Base: `StatusQoS` (BEST_EFFORT, KEEP_LAST_1)
- **Time-Based Filter**: 1-second minimum separation

### Why BEST_EFFORT + KEEP_LAST_1?
- **BEST_EFFORT**: Optimized for periodic sensor/status data where latest value matters most, not every historical sample
- **KEEP_LAST_1**: Only stores the most recent sample, minimal memory footprint
- **Use Case**: Designed for high-frequency periodic data (sensors, telemetry) where occasional loss is acceptable

## Files

- **QoS Profiles**: `../../../dds/qos/DDS_QOS_PROFILES.xml`
- **Topic Definitions**: `../../../dds/datamodel/python_gen/Definitions.py`
- **Data Types**: `../../../dds/datamodel/python_gen/ExampleTypes.py`

## Integration with Distributed Logger

The application uses RTI Distributed Logger for diagnostics:
- **Application Kind**: `Downsampled Position Reader-DistLogger`
- **Participant-Based**: Shares DDS participant with application
- **Log Level**: Configurable via verbosity argument

## Performance Considerations

### CPU Usage
- Time-based filtering happens in middleware, not application code
- Application thread only wakes when a sample passes the filter
- Minimal CPU overhead compared to receiving and discarding samples

### Network Bandwidth
- **Position is a keyed data type**: Filtering happens at DataReader, all samples are transmitted over the network
- Network bandwidth is NOT reduced by time-based filtering in this application
- Modify your type to be unkeyed if Bandwidth impact is a higher priority.

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!

