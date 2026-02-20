# Parameter Application

ROS2-style parameter management over DDS using pure pub/sub with keyed topics and content filtered topics.

## Architecture: Keyed Topics vs ROS2 Per-Node Topics

This implementation uses a fundamentally different architecture than ROS2 for significant performance gains:

### ROS2 Approach (Per-Node Topics)
```
┌─────────────────────────────────────────────────────────────────────┐
│  ROS2: Creates N topics per node × M services = exponential growth │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  /robot1/parameter_events          /robot2/parameter_events         │
│  /robot1/set_parameters            /robot2/set_parameters           │
│  /robot1/get_parameters            /robot2/get_parameters           │
│  /robot1/list_parameters           /robot2/list_parameters          │
│         ⋮                                  ⋮                         │
│                                                                      │
│  10 nodes × 4 services = 40 separate DDS topics                     │
│  → Massive discovery overhead, slow startup                          │
└─────────────────────────────────────────────────────────────────────┘
```

### DDS Keyed Topic Approach (This Implementation)
```
┌─────────────────────────────────────────────────────────────────────┐
│  DDS: Global topics with @key node_id for instance isolation        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│                    ParameterEvents (single topic)                    │
│                    ┌──────────────────────────────┐                  │
│                    │ @key node_id = "robot1" ──────┼─► Instance 1    │
│                    │ @key node_id = "robot2" ──────┼─► Instance 2    │
│                    │ @key node_id = "robot3" ──────┼─► Instance 3    │
│                    └──────────────────────────────┘                  │
│                                                                      │
│  10 nodes = still just 7 topics, same as 1 node!                     │
│  → O(1) discovery overhead, instant startup                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Performance Impact

| Metric | ROS2 (N nodes) | DDS Keyed Topics | Improvement |
|--------|---------------|------------------|-------------|
| **Topic Count** | 4N topics | 7 topics | O(N) → O(1) |
| **DataWriters** | 4N writers | 7 writers | O(N) → O(1) |
| **DataReaders** | 4N readers | 7 readers | O(N) → O(1) |
| **Discovery Time** | Grows with nodes | Constant | 10x+ faster |
| **Memory Overhead** | Per-topic buffers × N | Single topic buffers | ~N× reduction |
| **Network Discovery** | N² announcements | Minimal | Massive reduction |

### Discovery Impact: Entity Proliferation

In DDS, **every DataWriter and DataReader is a discoverable entity**. During startup, each entity must:
1. Announce itself to all other participants
2. Receive announcements from all other entities
3. Match compatible writers/readers
4. Exchange QoS information

```
┌─────────────────────────────────────────────────────────────────────┐
│  ROS2: Each topic creates unique DDS entities                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  /robot1/parameter_events  →  1 DataWriter + N DataReaders          │
│  /robot1/set_parameters    →  1 DataWriter + 1 DataReader (service) │
│  /robot1/get_parameters    →  1 DataWriter + 1 DataReader (service) │
│  /robot1/list_parameters   →  1 DataWriter + 1 DataReader (service) │
│                                                                      │
│  Per node: ~8 entities just for parameters                           │
│  10 nodes: 80 entities × 80 = 6,400 discovery interactions!         │
│                                                                      │
│  Discovery scales as O(N²) - each entity must discover all others   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  DDS Keyed Topics: Fixed entity count regardless of nodes           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ParameterEvents         →  1 Writer/node, 1 Reader/client          │
│  SetParametersRequest    →  1 Writer/client, 1 Reader/server (CFT)  │
│  SetParametersResponse   →  1 Writer/server, 1 Reader/client        │
│  ... (same pattern for Get/List)                                    │
│                                                                      │
│  Per node: ~7 entities (writers for responses, readers for requests)│
│  10 nodes: 70 entities × 70 = 4,900 interactions                    │
│  But only 7 TOPICS to match = much faster discovery!                │
│                                                                      │
│  Key insight: Instances (node_id) are DATA, not DDS entities        │
│  Adding a new node = just a new instance, zero discovery overhead   │
└─────────────────────────────────────────────────────────────────────┘
```

### System-Wide Scaling Example

| Nodes | ROS2 Entities | ROS2 Discovery | DDS Entities | DDS Discovery |
|-------|--------------|----------------|--------------|---------------|
| 1 | 8 | 64 | 7 | 49 |
| 10 | 80 | 6,400 | 70 | 4,900 |
| 50 | 400 | 160,000 | 350 | 122,500 |
| 100 | 800 | 640,000 | 700 | 490,000 |

**But the real win**: With keyed topics, adding a node doesn't require ANY existing nodes to re-discover.
A new `node_id` is just a new **instance** on existing topics - it's pure data, handled entirely in user space.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Adding robot51 to a 50-node system                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ROS2:                           DDS Keyed Topics:                   │
│  ─────                           ──────────────────                  │
│  4 new topics created            0 new topics                        │
│  8 new entities                  7 new entities (same topic)         │
│  All 400 existing entities       Existing entities unchanged         │
│  must re-match                   New node uses existing topics       │
│                                                                      │
│  Startup time: seconds           Startup time: milliseconds          │
└─────────────────────────────────────────────────────────────────────┘
```

### Central Monitor / Config Server Scenario

A common pattern is a **central health monitor** or **configuration server** that needs to observe or control parameters across all nodes in the system.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Central monitor watching 50 robot nodes                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ROS2 Architecture:                                                  │
│  ──────────────────                                                  │
│  Monitor must create SEPARATE readers for each node's topics:        │
│                                                                      │
│    /robot1/parameter_events  →  1 DataReader                         │
│    /robot2/parameter_events  →  1 DataReader                         │
│    /robot3/parameter_events  →  1 DataReader                         │
│    ...                                                               │
│    /robot50/parameter_events →  1 DataReader                         │
│                                                                      │
│  50 DataReaders just to watch parameter events!                      │
│  50 more DataWriters to SET parameters on each node!                 │
│  = 100 DDS entities for ONE central monitor                          │
│                                                                      │
│  Each entity adds to discovery traffic system-wide.                  │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  DDS Keyed Topics Architecture:                                      │
│  ──────────────────────────────                                      │
│  Monitor creates ONE reader per topic type:                          │
│                                                                      │
│    ParameterEvents topic     →  1 DataReader (all 50 node instances) │
│    SetParametersRequest      →  1 DataWriter (any node via node_id)  │
│    GetParametersRequest      →  1 DataWriter                         │
│    ListParametersRequest     →  1 DataWriter                         │
│    ...responses...           →  3 DataReaders                        │
│                                                                      │
│  = 7 DDS entities total for the central monitor                      │
│                                                                      │
│  node_id is just a FIELD in the data, not a topic discriminator.    │
│  Adding robot51? Zero new entities on the monitor.                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

| Scenario | ROS2 Monitor Entities | DDS Monitor Entities |
|----------|----------------------|---------------------|
| Watch 10 nodes | 10 readers | 1 reader |
| Watch 50 nodes | 50 readers | 1 reader |
| Watch 100 nodes | 100 readers | 1 reader |
| Configure 100 nodes | 100 writers | 1 writer |

**Key insight**: In ROS2, the **topic name contains the node identity**, forcing per-node entities. In DDS, the **key field contains the node identity**, allowing a single topic to carry all instances.

## Content Filtered Topics (CFT)

The server uses **Content Filtered Topics** to receive only requests addressed to it:

```cpp
// Server creates CFT with SQL-like filter on node_id
dds::topic::Filter filter("node_id = %0", { "'robot1'" });

_list_request_cft = ContentFilteredTopic<ListParametersRequest>(
    _list_request_topic,
    "robot1_ListRequest_CFT", 
    filter);
```

### CFT Benefits

| Without CFT | With CFT |
|-------------|----------|
| All servers receive all requests | Each server receives only its requests |
| App-level filtering (CPU waste) | Middleware-level filtering (efficient) |
| Unnecessary network traffic | Filtered at source (writer-side) |
| Manual filtering in handler | Automatic, zero application code |

```
┌─────────────────────────────────────────────────────────────────────┐
│                   CFT Filter at Middleware Level                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Client writes:                    Servers with CFT:                 │
│  ┌──────────────────────┐                                           │
│  │ node_id: "robot1"    │───────►  robot1 CFT ✓ receives            │
│  │ request: ListParams  │          robot2 CFT ✗ filtered out        │
│  └──────────────────────┘          robot3 CFT ✗ filtered out        │
│                                                                      │
│  Filtering happens in DDS middleware, not in application!           │
└─────────────────────────────────────────────────────────────────────┘
```

## Features

- **Keyed Topics**: `@key node_id` creates DDS instances per node
- **Content Filtered Topics**: Server-side filtering at middleware level
- **YAML Parameter Loading**: Load parameters from YAML configuration files
- **Parameter Events**: Publish/subscribe to parameter change events  
- **Request/Reply over Pub/Sub**: Set/Get/List parameters using correlated pub/sub
- **Server/Client Modes**: Run as parameter server or client
- **Late-Joiner Support**: Applications receive parameters even if they start after configuration is published

## Key Feature: Late-Joiner Support with ParameterQoS

The parameter system uses **ParameterQoS** with **TRANSIENT_LOCAL durability**. This means:

> **Late-joining applications automatically receive the last published parameters - no synchronization required!**

### How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TIME →                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Server starts    Server publishes     Client starts    Client      │
│  with params      ParameterEvent       (late joiner)    receives    │
│       │                 │                    │          params!     │
│       ▼                 ▼                    ▼             │        │
│   ════════════════════════════════════════════════════════▼════     │
│                                                                      │
│   With TRANSIENT_LOCAL durability, the middleware                   │
│   delivers the last published sample to late joiners                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### QoS Configuration

The `ParameterQoS` profile in `dds/qos/DDS_QOS_PROFILES.xml`:

| QoS Policy | Setting | Purpose |
|------------|---------|---------|
| **Durability** | TRANSIENT_LOCAL | Late joiners receive last published value |
| **Reliability** | RELIABLE | Guaranteed delivery of parameter updates |
| **History** | KEEP_LAST(1) | Only the most recent parameter state matters |

Topic filters in `AssignerQoS` automatically apply `ParameterQoS` to all Parameter* and SetParameters* topics.

### Example: Late-Joiner Scenario

```bash
# Terminal 1: Start server first
./run.sh --server --node-name robot1
# Output: [SERVER] Loaded 7 parameters from apps/cxx11/parameter_app/params.yaml

# Wait 30 seconds...

# Terminal 2: Start client (late joiner)
./run.sh --target robot1
# Output: [PARAM_EVENT] From node: robot1
#         NEW: robot.max_velocity
#         NEW: robot.max_acceleration
#         NEW: robot.name
#         ...
# The client receives all parameters even though it started late!
```

## Usage

```bash
./run.sh [OPTIONS]

Options:
  -d, --domain       <int>   Domain ID (default: 1)
  -v, --verbosity    <int>   RTI verbosity 0-5 (default: 1)
  -q, --qos-file     <str>   QoS XML path (default: dds/qos/DDS_QOS_PROFILES.xml)
  -p, --params-file  <str>   YAML parameters file (default: apps/cxx11/parameter_app/params.yaml)
  -n, --node-name    <str>   Unique name for this server (default: parameter_server)
  -t, --target       <str>   Server name to send requests to (default: parameter_server)
  -s, --server               Run as parameter server
  -h, --help                 Show help
```

## Modes

### Server Mode
Loads parameters from YAML and responds to SetParametersRequest:
```bash
./run.sh --server --node-name my_robot
```

### Client Mode
Sends SetParametersRequest to a specific server:
```bash
./run.sh --target my_robot
```

## Running Multiple Instances

You can run multiple parameter servers with unique names and target them individually:

```bash
# Terminal 1: Start robot1 server
./run.sh --server --node-name robot1

# Terminal 2: Start robot2 server  
./run.sh --server --node-name robot2

# Terminal 3: Client targets robot1 only
./run.sh --target robot1
# Request goes to robot1, response comes from robot1

# Terminal 4: Client targets robot2 only
./run.sh --target robot2
# Request goes to robot2, response comes from robot2
```

**Note:** ParameterEvent broadcasts are received from ALL servers (pub/sub fanout), but request topics use CFT filtering so each server only processes requests where `node_id` matches its name.

## DDS Topics & Keyed Types

All topics use `@key node_id` for instance isolation:

| Topic | Type | Key | Description |
|-------|------|-----|-------------|
| `ParameterEvents` | `ParameterEvent` | `node_id` | Parameter change notifications |
| `SetParametersRequest` | `SetParametersRequest` | `node_id` | Request to set parameters |
| `SetParametersResponse` | `SetParametersResponse` | `node_id` | Response to set request |
| `GetParametersRequest` | `GetParametersRequest` | `node_id` | Request to get parameters |
| `GetParametersResponse` | `GetParametersResponse` | `node_id` | Response with parameter values |
| `ListParametersRequest` | `ListParametersRequest` | `node_id` | Request to list parameters |
| `ListParametersResponse` | `ListParametersResponse` | `node_id` | Response with parameter names |

### IDL Type Definition (Keyed)

```idl
struct SetParametersRequest {
    @key string<32> node_id;                    // Key for instance isolation
    uint64 request_id;                          // Correlation ID
    sequence<Parameter, 64> parameters;         // Parameters to set
};
```

The `@key node_id` annotation means:
- Each unique `node_id` creates a separate **DDS instance**
- Instances are tracked independently (lifecycle, history)
- Content filters can efficiently match on key fields

## YAML Format

```yaml
parameters:
  - name: "robot.max_velocity"
    type: "double"
    value: 1.5
  - name: "robot.name"
    type: "string"
    value: "my_robot"
  - name: "robot.enabled"
    type: "bool"
    value: true
  - name: "robot.wheel_count"
    type: "integer"
    value: 4
```

## Example

Terminal 1 - Start server:
```bash
./run.sh --server --node-name robot1
# Output:
# [SERVER] Loaded 7 parameters from apps/cxx11/parameter_app/params.yaml
# (server is now running, handling requests asynchronously)
```

Terminal 2 - Start client:
```bash
./run.sh --target robot1
# Output:
# [PARAM_EVENT] From node: robot1
#   NEW: robot.max_velocity
#   NEW: robot.max_acceleration
#   ...
#
# === LIST PARAMETERS ===
# [LIST] Found 7 parameters on robot1:
#   - robot.enabled
#   - robot.max_velocity
#   ...
#
# === GET PARAMETERS ===
# [GET] Retrieved 7 parameters:
#   robot.enabled = bool
#   robot.max_velocity = double
#   ...
#
# === SET PARAMETERS ===
# [SET] Response from: robot1
#   Result[0]: SUCCESS
#   ...
```

## Dependencies

- RTI Connext DDS 7.3.0+
- yaml-cpp library (for YAML parameter file parsing)

### Installing yaml-cpp

**Option 1: Use the install script (recommended)**
```bash
./apps/cxx11/parameter_app/install.sh
```

The script auto-detects your OS and installs yaml-cpp using the appropriate package manager:
- Ubuntu/Debian: `apt-get install libyaml-cpp-dev`
- Fedora: `dnf install yaml-cpp-devel`
- CentOS/RHEL: `yum install yaml-cpp-devel`
- Arch: `pacman -S yaml-cpp`
- macOS: `brew install yaml-cpp`

**Option 2: Automatic download (no action needed)**

If yaml-cpp is not found on your system, CMake will automatically download and build it from GitHub using FetchContent. This happens transparently during the build process.

**Option 3: Manual installation**
```bash
# Ubuntu/Debian
sudo apt-get install libyaml-cpp-dev

# macOS
brew install yaml-cpp
```

## Implementation Details

### Server: Pure DDS API with Content Filtered Topics

The server (`DDSServerParameterSetup`) uses pure DDS API:

```cpp
// 1. Create base topic
_list_request_topic = dds::topic::Topic<ListParametersRequest>(
    participant, "ListParametersRequest");

// 2. Create Content Filtered Topic for this node
std::vector<std::string> filter_params = { "'" + node_name + "'" };
dds::topic::Filter filter("node_id = %0", filter_params);

_list_request_cft = dds::topic::ContentFilteredTopic<ListParametersRequest>(
    _list_request_topic,
    node_name + "_ListRequest_CFT",
    filter);

// 3. Create reader on CFT (only receives matching requests)
_list_request_reader = dds::sub::DataReader<ListParametersRequest>(
    subscriber, _list_request_cft, qos);

// 4. Attach ReadCondition to AsyncWaitSet for async processing
_list_read_condition = dds::sub::cond::ReadCondition(
    _list_request_reader, 
    dds::sub::status::DataState(SampleState::not_read(), ...));
    
_list_read_condition->handler([this](Condition) { 
    handle_list_requests(); 
});

async_waitset.attach_condition(_list_read_condition);
```

### Client: Correlated Request/Response over Pub/Sub

The client (`DDSClientParameterSetup`) uses request_id correlation:

```cpp
// Send request with unique ID
uint64_t req_id = _next_request_id++;
request.node_id(target_node);
request.request_id(req_id);
_list_request_writer->writer().write(request);

// Poll for response matching request_id and node_id
while (not_timed_out) {
    auto samples = _list_response_reader->reader().take();
    for (const auto& sample : samples) {
        if (sample.data().request_id() == req_id &&
            sample.data().node_id() == target_node) {
            return sample.data();  // Found our response
        }
    }
    sleep(10ms);
}
```

### Why Not Request/Reply API?

This implementation uses simple pub/sub instead of RTI's Request/Reply API because:

1. **Simpler Discovery**: All endpoints created upfront, no dynamic requester creation
2. **Multiple Targets**: Single client can target any server without endpoint recreation
3. **CFT Compatibility**: Content filters work naturally with standard readers
4. **Transparency**: Easy to monitor with Admin Console, rtispy, etc.
