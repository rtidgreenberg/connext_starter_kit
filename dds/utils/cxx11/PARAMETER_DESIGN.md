# DDSParameterSetup Design Document

## Overview

This document describes the DDS Parameter system architecture, following the ROS2 decentralized parameter model where each node owns and manages its own parameters.

## Architecture: Decentralized (ROS2 Style)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   robot_node    │     │   sensor_node   │     │   camera_node   │
│  (params: 5)    │     │  (params: 3)    │     │  (params: 8)    │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ Services:       │     │ Services:       │     │ Services:       │
│ - SetParameters │     │ - SetParameters │     │ - SetParameters │
│ - GetParameters │     │ - GetParameters │     │ - GetParameters │
│ - ListParameters│     │ - ListParameters│     │ - ListParameters│
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   ParameterEvents       │
                    │   (pub/sub broadcast)   │
                    │   All nodes publish,    │
                    │   all nodes can receive │
                    └─────────────────────────┘
```

**Key Characteristics:**
- Each application embeds its own parameter server
- Service name = node name (for Request/Reply routing)
- Three services per node: SetParameters, GetParameters, ListParameters
- ParameterEvents broadcast changes to ALL subscribers
- No single point of failure
- Aligns with DDS distributed nature

## Services

### 1. SetParameters Service
Set one or more parameters on a node.

```
Request:  SetParametersRequest { node_id, parameters[] }
Response: SetParametersResponse { node_id, results[] }
```

### 2. GetParameters Service
Retrieve current values of specific parameters.

```
Request:  GetParametersRequest { node_id, names[] }
Response: GetParametersResponse { node_id, parameters[] }
```

### 3. ListParameters Service
Discover what parameters a node has.

```
Request:  ListParametersRequest { node_id, prefixes[], depth }
Response: ListParametersResponse { node_id, names[] }
```

## Workflow

### Server Mode (Node with Parameters)

```cpp
// Each application that owns parameters runs as a server
DDSParameterSetup params(participant, "my_robot");

// Load initial parameters
params.set_parameters(DDSParameterSetup::load_from_yaml("my_robot_params.yaml"));

// Setup server - handles all three services
params.setup_server();

// Broadcast initial parameters
params.publish_all_as_new();

// Run server loop
params.run();  // Blocks, handles SetParameters/GetParameters/ListParameters
```

### Client Mode (Query/Modify Other Nodes)

```cpp
DDSParameterSetup client(participant, "config_tool");
client.setup_client("target_node");

// Set parameters on target node
auto set_results = client.set_remote_parameters({
    DDSParameterSetup::make_parameter("max_velocity", 2.0),
    DDSParameterSetup::make_parameter("enabled", true)
});

// Get current parameter values from target node
auto params = client.get_remote_parameters({"max_velocity", "enabled"});

// List all parameters on target node
auto names = client.list_remote_parameters();
```

### Event Monitor Mode (Observe All Changes)

```cpp
DDSParameterSetup monitor(participant, "dashboard");
monitor.setup_event_subscriber([](const ParameterEvent& event) {
    std::cout << "Node " << event.node_id() << " changed:" << std::endl;
    for (const auto& p : event.changed_parameters()) {
        std::cout << "  " << p.name() << std::endl;
    }
});
// Receives ParameterEvents from ALL nodes in the system
```

## Use Cases

| Use Case | Actor | Mode | Services Used |
|----------|-------|------|---------------|
| App manages own config | robot_node | Server | Responds to all services |
| Change node's params | CLI tool | Client | SetParameters |
| Read node's params | Diagnostic tool | Client | GetParameters |
| Discover node's params | Config UI | Client | ListParameters |
| Monitor all changes | Dashboard | Event Sub | ParameterEvents topic |
| Backup system params | Backup tool | Client | ListParameters + GetParameters on each node |

## API Reference

### Static Factory Methods

```cpp
// Create parameters of various types (overloaded)
DDSParameterSetup::make_parameter("name", "string_value");
DDSParameterSetup::make_parameter("name", 3.14);           // double
DDSParameterSetup::make_parameter("name", 42);             // int64
DDSParameterSetup::make_parameter("name", true);           // bool
DDSParameterSetup::make_parameter("name", std::vector<double>{1.0, 2.0});

// Load from YAML file
std::vector<Parameter> params = DDSParameterSetup::load_from_yaml("params.yaml");
```

### Server API

```cpp
DDSParameterSetup params(participant, "node_name");

// Parameter storage
params.set_parameter(param);
params.set_parameters(params_vec);
params.delete_parameter("name");
params.has_parameter("name");
params.get_parameter("name");
params.get_all_parameters();
params.list_parameter_names();
params.parameter_count();

// Server setup and run
params.setup_server();                    // Default: accept all
params.setup_server(set_callback);        // Custom SetParameters handler
params.process_requests();                // Non-blocking, call in loop
params.run();                             // Blocking convenience method

// Event publishing
params.publish_event();                   // Pending changes only
params.publish_all_as_new();              // All params as "new"
```

### Client API

```cpp
DDSParameterSetup client(participant, "client_name");
client.setup_client("target_node");

// Remote operations
auto responses = client.set_remote_parameters(params);
auto params = client.get_remote_parameters(names);
auto names = client.list_remote_parameters();
auto names = client.list_remote_parameters(prefixes, depth);
```

### Event Subscriber API

```cpp
DDSParameterSetup monitor(participant, "monitor_name");
monitor.setup_event_subscriber(callback);
```

## IDL Types

```idl
module example_types {
    // Parameter value union (supports all types)
    union ParameterValue switch (ParameterType) { ... };
    
    // Single parameter
    struct Parameter {
        string name;
        ParameterValue value;
    };
    
    // SetParameters service
    struct SetParametersRequest {
        string node_id;
        sequence<Parameter> parameters;
    };
    struct SetParametersResponse {
        string node_id;
        sequence<SetParameterResult> results;
    };
    
    // GetParameters service
    struct GetParametersRequest {
        string node_id;
        sequence<string> names;
    };
    struct GetParametersResponse {
        string node_id;
        sequence<Parameter> parameters;
    };
    
    // ListParameters service
    struct ListParametersRequest {
        string node_id;
        sequence<string> prefixes;  // Filter by prefix (empty = all)
        uint32 depth;               // 0 = unlimited
    };
    struct ListParametersResponse {
        string node_id;
        sequence<string> names;
    };
    
    // ParameterEvent (broadcast)
    struct ParameterEvent {
        string node_id;
        uint64 timestamp_ns;
        sequence<Parameter> new_parameters;
        sequence<Parameter> changed_parameters;
        sequence<Parameter> deleted_parameters;
    };
};
```

## Implementation Status

- [x] Parameter types (IDL)
- [x] ParameterEvent pub/sub
- [x] SetParameters service (IDL + implementation)
- [x] GetParameters service (IDL + implementation)
- [x] ListParameters service (IDL + implementation)
- [x] DDSParameterSetup utility class
- [x] YAML loading
- [x] Default accept-all handler
- [ ] `run()` convenience method
- [ ] TRANSIENT_LOCAL QoS for late joiners
- [ ] Parameter validation callbacks

## YAML Format

```yaml
parameters:
  - name: "robot.max_velocity"
    type: "double"
    value: 1.5
  - name: "robot.enabled"
    type: "bool"
    value: true
  - name: "robot.name"
    type: "string"
    value: "my_robot"
  - name: "sensor.rates"
    type: "double_array"
    value: [10.0, 20.0, 30.0]
```
