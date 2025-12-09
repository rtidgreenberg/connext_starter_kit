# RTI Services Configuration

Configuration files for RTI Recording Service - capture, replay, and analyze DDS data flows without modifying applications.

## Use Cases

### Use Case 1: Dynamic Topic Recording with Filtering

**Objective**: Auto-discover and record all application topics while filtering out RTI internal topics.

**Configuration**:
See Session name `RecordAllbutRTI` in `recording_service_config.xml` for details

**Running**:
```bash
cd services
./start_record.sh
```


### Use Case 2: Recording Topics with External XML Type Definitions

**Objective**: 
Record topics from external DDS applications (e.g., ROS2, third-party systems)  
using XML type definitions when data type has not been propagated in discovery  
(Default for most open source DDS).

**Scenario**: Recording the `Button` topic using an external XML type definition instead of the generated IDL.

**Configuration**:
See Session name `RegisteredTypeOnly` in `recording_service_config.xml` for details


**What Gets Recorded**:
- ✅ Application topics: `Button`

**Running**:
```bash
cd services
./start_record.sh
```


## Prerequisites

- RTI Connext DDS 7.3.0+ with Recording Service
- Set `NDDSHOME` environment variable

## Resources

- [RTI Recording Service Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/recording_service/)
- [RTI Replay Service Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/replay_service/)

