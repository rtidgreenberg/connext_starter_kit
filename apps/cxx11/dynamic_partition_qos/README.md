# Dynamic Partition QoS Application

## Overview

This C++ application demonstrates **runtime modification of Domain Participant Partitions** using the [PARTITION QoSPolicy](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm) in RTI Connext DDS for **test environment isolation and dynamic message traffic segmentation**.  
Each instance generates a unique Application ID (App-XXXX) and can dynamically change Domain Participant partitions at runtime, enabling sophisticated testing scenarios including unit test isolation, failover testing, and multi-instance communication verification.

The application both publishes and subscribes to the `Command` topic while accepting user input from the terminal to change partition names on-the-fly. This allows you to spin up multiple instances and test partition-based communication isolation, verify failover scenarios, and validate message routing in distributed systems.

## What are Domain Participant Partitions?

The [PARTITION QoSPolicy](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm) provides a way to control which DDS entities will match and communicate with each other. Partitions create logical "visibility planes" within a DDS domain - only entities with matching partitions can communicate, even if they're on the same topic and domain.

**Domain Participant partitions** are particularly useful in large, WAN, distributed systems because DomainParticipants without matching partitions will not exchange information about their DataWriters and DataReaders. While Simple Participant Discovery still occurs, **Simple Endpoint Discovery is eliminated** for DomainParticipants that do not have a matching partition. This reduces network, CPU, and memory utilization by preventing unnecessary endpoint discovery traffic.

**Key characteristics:**
- Partition names are strings (e.g., "SensorData", "ControlCommands", "Diagnostics")
- An entity can belong to multiple partitions simultaneously (up to 64 partitions, 256 characters total)
- Empty string ("") is the default partition
- **PARTITION QoSPolicy is mutable** - can be changed at runtime without recreating entities
- Partition names are case-sensitive
- Supports pattern matching with regular expressions (POSIX fnmatch format)
- Applies to DomainParticipants, Publishers, and Subscribers (this app modifies DomainParticipant partitions)

**Common use cases:**
- **Test environment isolation**: Isolate unit test traffic dynamically at runtime
- **Failover scenario testing**: Verify backup systems activate on correct partitions
- **Multi-tenant systems**: Isolate data streams for different customers/users
- **Development/Production separation**: Route test traffic separately from live data
- **Geographic separation**: "US_East", "EU_West", etc.
- **Dynamic access control**: Add/remove entities from data streams
- **CI/CD pipeline isolation**: Prevent test jobs from interfering with each other

## Features

- **Unique Application ID**: Each instance generates a random 4-digit ID (e.g., App-3847) for easy identification
- **Publishes Command messages** at 2-second intervals with timestamps and App ID
- **Subscribes to Command messages** with event-driven async processing
- **Ignores own publications**: Uses `dds::sub::ignore()` API to prevent receiving loopback messages
- **Accepts terminal input** for partition names during runtime (no restart required)
- **Validates and applies partition QoS** dynamically to the DomainParticipant
- **Supports multiple partitions** simultaneously (comma-separated input)
- **Real-time partition display**: Shows current partition(s) with App ID every 2 seconds
- **Uses Distributed Logger** for status messages and debugging

## Building the Application

### Prerequisites

- RTI Connext DDS 7.3.0+
- CMake 3.12+
- C++14 compiler
- DDS types already generated (Command type)

### Build Steps

```bash
cd apps/cxx11/dynamic_partition_qos
mkdir -p build && cd build
cmake ..
make -j4
```

The executable will be created at: `build/dynamic_partition_qos`

## Running the Application

### Basic Usage

```bash
cd apps/cxx11/dynamic_partition_qos/build
./dynamic_partition_qos
```

**Optional arguments:**
```bash
./dynamic_partition_qos -d <domain_id> -q <qos_file_path> -v <verbosity>
```

- `-d, --domain`: DDS Domain ID (default: 0)
- `-q, --qos`: Path to QoS XML file
- `-v, --verbosity`: Connext logging verbosity (0-5)
- `-h, --help`: Show help message

### Interactive Commands

Once running, the application displays its unique App ID and prompts for partition input:

```
Dynamic Partition QoS application starting on domain 0
Application ID: 3847
Using QoS file: ../../../../dds/qos/DDS_QOS_PROFILES.xml

------------------ APP ID:3847 PARTITION: (default/empty) -----------------------
Enter partition name(s) (comma-separated for multiple, or 'q'/'exit' to quit):
```

**Examples:**

1. **Single partition:**
   ```
   TestEnv1
   ```

2. **Multiple partitions:**
   ```
   Production,US_East,HighPriority
   ```

3. **Reset to default (empty) partition:**
   ```
   (press Enter with empty input)
   ```

4. **Exit:**
   ```
   q
   or
   exit
   ```

## Test Scenarios and Use Cases

### Primary Use Case: Test Environment Isolation

Partitions are essential for **isolating message traffic in test environments**. This application enables you to:

1. **Run multiple test instances simultaneously** without interference
2. **Verify partition-based segmentation** by toggling partitions and observing message flow
3. **Test failover scenarios** by moving instances between partitions
4. **Validate unit test isolation** in CI/CD pipelines
5. **Debug communication issues** by monitoring which instances communicate

### Scenario 1: Unit Test Isolation

**Problem**: Multiple unit tests running in parallel interfere with each other's DDS traffic.

**Solution**: Assign each test to a unique partition:

```bash
# Terminal 1 - Unit Test A
./dynamic_partition_qos -d 0
Application ID: 1234
> UnitTest_A

# Terminal 2 - Unit Test B  
./dynamic_partition_qos -d 0
Application ID: 5678
> UnitTest_B

# Terminal 3 - Integration Test
./dynamic_partition_qos -d 0
Application ID: 9101
> IntegrationTest
```

**Result**: Each test instance only sees messages from its own partition. App-1234 and App-5678 cannot interfere with each other.

### Scenario 2: Failover Testing

**Problem**: Need to verify backup systems activate and communicate on the correct partition.

**Solution**: Simulate primary failure by changing partitions:

```bash
# Terminal 1 - Primary System
./dynamic_partition_qos -d 0
Application ID: 2001
> Production,Primary

# Terminal 2 - Backup System (standby)
./dynamic_partition_qos -d 0  
Application ID: 2002
> Standby

# Simulate primary failure - move backup to production
# In Terminal 2, type:
> Production,Backup
```

**Verification**: 
- Before failover: App-2001 communicates on Production, App-2002 sees no traffic
- After failover: App-2002 now receives Production traffic
- Use App IDs in messages to verify which instance is active

### Scenario 3: Multi-Instance Communication Testing

**Problem**: Need to verify which instances can communicate and test partition segmentation.

**Solution**: Spin up multiple instances and dynamically toggle partitions:

```bash
# Terminal 1 - App-3001
./dynamic_partition_qos -d 0
> PartitionA

# Terminal 2 - App-3002  
./dynamic_partition_qos -d 0
> PartitionB

# Terminal 3 - App-3003
./dynamic_partition_qos -d 0
> PartitionA,PartitionB
```

**Verification**:
- App-3001 receives messages from: App-3001 (own), App-3003
- App-3002 receives messages from: App-3002 (own), App-3003  
- App-3003 receives messages from: All instances
- Change partitions in real-time to verify segmentation

**Example test sequence:**
```bash
# In Terminal 1, verify isolation:
> PartitionA           # Should see App-3003 messages
> PartitionC           # Should see NO other messages (isolated)
> PartitionA,PartitionB # Should see App-3002 AND App-3003 messages
```

### Scenario 4: Geographic Distribution Testing

Test geographic routing without physical separation:

```bash
# Terminal 1 - East Coast Simulator
./dynamic_partition_qos -d 0
Application ID: 4001
> US_East,Production

# Terminal 2 - West Coast Simulator
./dynamic_partition_qos -d 0
Application ID: 4002  
> US_West,Production

# Terminal 3 - Global Monitor
./dynamic_partition_qos -d 0
Application ID: 4003
> US_East,US_West,Production
```

**Result**: App-4003 sees all traffic, while App-4001 and App-4002 are isolated from each other but both in Production.

### Scenario 5: CI/CD Pipeline Isolation

**Problem**: Multiple CI/CD jobs running simultaneously on the same build server interfere.

**Solution**: Use environment variables with partition configuration:

```bash
# Job 1
export TEST_PARTITION="CI_Job_${BUILD_ID}_1"
./dynamic_partition_qos -d 0
> ${TEST_PARTITION}

# Job 2  
export TEST_PARTITION="CI_Job_${BUILD_ID}_2"
./dynamic_partition_qos -d 0
> ${TEST_PARTITION}
```

**Note**: See "Partition QoS Configuration" section below for XML-based configuration with environment variables.

## Partition QoS Configuration

### Runtime Modification (This Application)

This application demonstrates **runtime Domain Participant partition changes** via terminal input. The PARTITION QoSPolicy is mutable and can be modified at any time:

```cpp
// Get current participant QoS
auto participant_qos = dds_context->participant().qos();

// Update partition policy
participant_qos << dds::core::policy::Partition(partitions);

// Apply the new QoS
dds_context->participant().qos(participant_qos);
```

### XML-Based Configuration with Environment Variables

For **initialization-time** configuration (when creating DomainParticipant, Publisher, or Subscriber), you can combine XML QoS profiles with environment variables. This is ideal for CI/CD pipelines and automated testing.

**Note**: The PARTITION QoSPolicy applies to DomainParticipants, Publishers, and Subscribers. This application modifies **DomainParticipant** partitions, which affects discovery. Publisher/Subscriber partitions affect endpoint matching only.

**Example QoS XML** (`dds/qos/DDS_QOS_PROFILES.xml`):

```xml
<qos_profile name="TestEnvironmentProfile">
    <participant_qos>
        <partition>
            <name>
                <!-- Use environment variable for partition -->
                <element>$(TEST_PARTITION)</element>
            </name>
        </partition>
    </participant_qos>
    
    <datareader_qos>
        <partition>
            <name>
                <element>$(TEST_PARTITION)</element>
            </name>
        </partition>
    </datareader_qos>
    
    <datawriter_qos>
        <partition>
            <name>
                <element>$(TEST_PARTITION)</element>
            </name>
        </partition>
    </datawriter_qos>
</qos_profile>
```

**Usage with environment variables:**

```bash
# Set partition via environment variable
export TEST_PARTITION="UnitTest_A"

# Run application (would need profile parameter support)
./dynamic_partition_qos -d 0

# Or in CI/CD:
TEST_PARTITION="CI_${BUILD_ID}_Job1" ./dynamic_partition_qos -d 0
```

**Multiple partitions in XML:**

```xml
<partition>
    <name>
        <element>$(PRIMARY_PARTITION)</element>
        <element>$(SECONDARY_PARTITION)</element>
        <element>Production</element>
    </name>
</partition>
```

```bash
export PRIMARY_PARTITION="US_East"
export SECONDARY_PARTITION="HighPriority"
./dynamic_partition_qos -d 0
```

### Combining Both Approaches

**Best Practice**: Use XML/environment variables for **initial configuration**, then use **runtime modification** (this app) for **dynamic testing**:

1. Start with environment-based partition: `TEST_PARTITION="InitialState"`
2. Run automated tests
3. Use terminal input to switch partitions for failover testing
4. Verify communication changes without restarting

This provides maximum flexibility for both automated and manual testing scenarios.

### Partition Matching Rules

According to the [PARTITION QoSPolicy documentation](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm), a DataWriter will communicate with a DataReader if:

1. They belong to DomainParticipants with the same domain ID, domain tag, and **at least one matching DomainParticipant partition**
2. They have matching Topics (same name and compatible data type)
3. The QoS offered by the DataWriter is compatible with the QoS requested by the DataReader
4. The application has not used ignore_participant(), ignore_datareader(), or ignore_datawriter() APIs
5. The Publisher and Subscriber must have at least one matching partition name

**Important**: Partition matching is done by string pattern matching and partition names are **case-sensitive**.

## Code Architecture

### Key Components

1. **Application ID Generation**: Unique random 4-digit ID for instance identification
2. **DDSContextSetup**: Manages DomainParticipant lifecycle and partition QoS
3. **DDSReaderSetup**: Subscribes to Command topic with async event-driven processing
4. **DDSWriterSetup**: Publishes Command messages with App ID in message payload
5. **Input Thread**: Handles terminal input for dynamic partition changes
6. **Ignore API**: Uses `dds::sub::ignore()` to prevent receiving own publications

### Message Flow

```
1. App-XXXX starts → Generates unique ID → Creates DDS entities
2. App-XXXX publishes → "From APP ID: XXXX" → Command topic
3. Other instances receive → Display "MESSAGE RECEIVED: From APP ID: XXXX"
4. User changes partition → Partition QoS updated → Communication topology changes
5. Real-time feedback → Shows current partition + App ID every 2 seconds
```

## Important Notes

### Mutable QoS Policy

The [PARTITION QoSPolicy](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm) **can be modified at any time** (it is mutable). This makes it ideal for:
- Dynamic test environment switching
- Failover scenarios
- Runtime access control changes
- Temporary separation groups

This application demonstrates Domain Participant partition modification, which is particularly powerful because it affects endpoint discovery - DomainParticipants without matching partitions don't exchange endpoint information, reducing network traffic and resource usage.

### Performance Considerations

- **Domain Participant partitions eliminate Simple Endpoint Discovery** - participants still discover each other (Simple Participant Discovery), but don't exchange DataWriter/DataReader information when partitions don't match
- **Domain Participant partition changes** affect endpoint discovery - participants will unmatch/match based on new partitions
- Changing partitions does **not** require recreating DataReaders/DataWriters
- Partition matching is efficient and happens automatically
- The mechanism is relatively lightweight compared to creating/deleting entities
- **DomainParticipant partition changes**: When unmatching, local participant notifies remote participants; matching may take time (depends on announcement period)
- **Publisher/Subscriber partition changes**: Immediate local unmatch; remote entities unmatch upon receiving endpoint announcements
- Partition information is propagated via discovery traffic (DomainParticipant partitions via participant discovery, Publisher/Subscriber partitions via endpoint discovery)

## Testing and Verification

### Multi-Instance Testing Setup

**Recommended approach** for verifying partition segmentation:

```bash
# Terminal 1 - Instance A (App-1234)
cd apps/cxx11/dynamic_partition_qos/build
./dynamic_partition_qos -d 0
> TestPartitionA

# Terminal 2 - Instance B (App-5678)
cd apps/cxx11/dynamic_partition_qos/build
./dynamic_partition_qos -d 0
> TestPartitionB

# Terminal 3 - Instance C (App-9012) - Bridge
cd apps/cxx11/dynamic_partition_qos/build
./dynamic_partition_qos -d 0
> TestPartitionA,TestPartitionB

# Terminal 4 - RTI Admin Console (optional)
$NDDSHOME/bin/rtiadminconsole -domain 0
```

**What you'll observe:**
- Terminal 1 (App-1234): Receives messages from App-9012 only (bridge instance)
- Terminal 2 (App-5678): Receives messages from App-9012 only (bridge instance)
- Terminal 3 (App-9012): Receives messages from ALL instances
- Admin Console: Shows partition membership and matching status

**Dynamic test sequence:**
```bash
# In Terminal 1, switch to partition B:
> TestPartitionB
# Now App-1234 and App-5678 can communicate directly

# In Terminal 3, remove bridge:
> TestPartitionC
# Now App-1234 and App-5678 are isolated again

# Verify isolation by checking message output
```

### Verification Checklist

When testing partition isolation:

✅ **App ID displayed** in startup output (e.g., "Application ID: 3847")  
✅ **Current partition shown** every 2 seconds with App ID  
✅ **Messages received** show sender's App ID: "MESSAGE RECEIVED: From APP ID: XXXX"  
✅ **No loopback** - Instance does NOT receive its own messages  
✅ **Partition change** takes effect immediately (next publish cycle)  
✅ **Communication stops** when instances are on different partitions  
✅ **Communication resumes** when partitions match again  



## References

### Official RTI Documentation

- **[PARTITION QoSPolicy](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm)** - Primary reference for partition behavior
- [Domain Participant Partitions](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/Creating_ParticipantPartitions.htm) - Isolating DomainParticipants and Endpoints
- [Partition Changes](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm#PARTITION_QosPolicy_1991854096_PartitionChanges) - Behavior when changing partitions at runtime
- [Pattern Matching for Partition Names](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm#PARTITION_QosPolicy_1991854096_PatternMatchingForPARTITIONNames) - Using regular expressions
- [Modern C++ API - QoS Policies](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/connext_dds/api_cpp2/group__DDSQosModule.html)
- [Restricting Communication - Ignoring Entities](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/Restricting_Communication_Ignoring_Entit.htm)
- [QoS Profiles with Environment Variables](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/XMLConfiguration.htm)

## Key Takeaways

### For Test Engineers

✅ **Partition QoS enables test environment isolation** without separate DDS domains  
✅ **Multiple test instances can run simultaneously** on the same machine/domain  
✅ **Dynamic partition changes allow failover testing** without restarting applications  
✅ **App IDs provide clear instance identification** in logs and messages  
✅ **Ignore API prevents loopback** - critical for realistic testing  

### For Developers

✅ **PARTITION QoSPolicy is MUTABLE** - can be modified at any time  
✅ **DomainParticipant partitions eliminate Simple Endpoint Discovery** - participants still discover each other but don't exchange DataWriter/DataReader information if partitions don't match  
✅ **Publisher/Subscriber partitions affect endpoint matching** - independent of DomainParticipant partitions  
✅ **XML + environment variables enable CI/CD integration**  
✅ **Empty partition ("") is the default** - all entities communicate  
✅ **Partition matching is case-sensitive** and supports regular expressions (POSIX fnmatch)  
✅ **Resource limits**: Max 64 partitions, 256 characters total across all names  
✅ **Partition changes are lightweight** compared to entity creation/deletion  

### Best Practices

1. **Use unique App IDs** or instance names for tracking in distributed systems
2. **Combine XML configuration with runtime changes** for maximum flexibility
3. **Test partition isolation** before deploying segmentation strategies
4. **Use partitions for test isolation** instead of separate domains (simpler, more efficient)
5. **Document partition naming conventions** in team standards (e.g., `${Environment}_${Region}_${Service}`)

## Learning Outcomes

By studying this example, you will learn:

1. ✅ How to modify Domain Participant Partitions at runtime using the PARTITION QoSPolicy
2. ✅ How to use partitions for test environment isolation
3. ✅ The difference between DomainParticipant partitions (eliminates Simple Endpoint Discovery) and Publisher/Subscriber partitions (affects endpoint matching only)
4. ✅ How to test communication segmentation with multiple instances
5. ✅ How to implement failover scenario testing with partition changes
6. ✅ Understanding mutable QoS policies and runtime modification
7. ✅ How to prevent receiving own publications with `dds::sub::ignore()`
8. ✅ How to combine XML QoS profiles with environment variables
9. ✅ Partition matching rules and pattern matching with regular expressions
10. ✅ CI/CD integration patterns for DDS-based testing
11. ✅ Performance implications: DomainParticipants still discover each other but skip endpoint discovery when partitions don't match
