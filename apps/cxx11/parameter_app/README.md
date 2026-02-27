# Parameter Application

ROS2-style parameter management over DDS using keyed topics and content filtered topics.

## Data Model

Parameters use a **union type** for flexible values, similar to ROS2's `rcl_interfaces/msg/ParameterValue`:

```idl
union ParameterValue switch (ParameterType) {
    case PARAMETER_BOOL:      boolean bool_value;
    case PARAMETER_INTEGER:   long long integer_value;
    case PARAMETER_DOUBLE:    double double_value;
    case PARAMETER_STRING:    string<256> string_value;
    case PARAMETER_BOOL_ARRAY:    sequence<boolean, 64> bool_array_value;
    case PARAMETER_INTEGER_ARRAY: sequence<long long, 64> integer_array_value;
    case PARAMETER_DOUBLE_ARRAY:  sequence<double, 64> double_array_value;
    case PARAMETER_STRING_ARRAY:  sequence<string<256>, 64> string_array_value;
    // ...
};

struct Parameter {
    string<256> name;
    ParameterValue value;
};
```

**Sequences** allow batch operations—setting, getting, or listing multiple parameters in a single message:

```idl
struct SetParametersRequest {
    @key string<32> node_id;
    uint64 request_id;
    sequence<Parameter, 64> parameters;  // Up to 64 parameters per request
};
```

## Scalability: Keys and Content Filtered Topics

### Keyed Topics for Instance Isolation

All parameter types use `@key node_id` to create **DDS instances** per node:

- Single `ParameterEvents` topic serves unlimited nodes (O(1) topic count)
- Each `node_id` is a separate instance, not a separate topic
- Adding nodes incurs zero discovery overhead

### Content Filtered Topics for Directed Configuration

Servers use CFT to receive only requests addressed to them:

```cpp
dds::topic::Filter filter("node_id = %0", { "'robot1'" });
_request_cft = ContentFilteredTopic<SetParametersRequest>(_topic, "robot1_CFT", filter);
```

**Benefits:**
- Filtering at middleware level, not application
- Reduced network traffic (writer-side filtering when supported)
- Multiple servers share one topic without cross-talk

## Decoupled Startup: Transient Local Durability

`ParameterQoS` uses **TRANSIENT_LOCAL** durability—late-joining applications receive the last published parameters automatically:

```
Server publishes params → [time passes] → Client starts → Client receives params
```

**No synchronization required.** Configuration can be published before target applications start.

| QoS Policy | Setting | Purpose |
|------------|---------|---------|
| Durability | TRANSIENT_LOCAL | Late joiners receive cached values |
| Reliability | RELIABLE | Guaranteed delivery |
| History | KEEP_LAST(1) | Only most recent state |

## Usage

```bash
./run.sh [OPTIONS]

Options:
  -s, --server               Run as parameter server
  -n, --node-name    <str>   Server name (default: parameter_server)
  -t, --target       <str>   Target server for client requests
  -p, --params-file  <str>   YAML parameters file
  -d, --domain       <int>   Domain ID (default: 1)
```

### Example

```bash
# Terminal 1: Start server
./run.sh --server --node-name robot1

# Terminal 2: Start client (can start later—receives params via durability)
./run.sh --target robot1
```

## YAML Format

```yaml
parameters:
  - name: "robot.max_velocity"
    type: "double"
    value: 1.5
  - name: "robot.name"
    type: "string"
    value: "my_robot"
```

## Dependencies

- RTI Connext DDS 7.3.0+
- yaml-cpp (auto-downloaded by CMake if not installed)
