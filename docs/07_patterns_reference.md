# Patterns Reference

## System Patterns Catalog

System patterns are **higher-level architectural behaviors** that compose multiple data patterns, types, and application logic into a reusable solution. Unlike data patterns (which configure one topic), system patterns define entire subsystems.

**System patterns are declared at the system level** (Phase 1: System Design) and **opted into per-process** (Phase 3: Process Design, Step 1d). The approach (e.g., Hot Standby vs Cold Standby) is decided once at the system level — all participating processes use the same approach, ensuring consistency.

When a process opts into a system pattern, it **auto-generates**:
- Required types (added to `types[]` in the design)
- Required I/O (added to `inputs[]` and `outputs[]`)
- Required application logic (callback implementations, monitoring loops)
- Required tests (added to `tests`)
- QoS configuration (specific profiles for the pattern's topics)

The user reviews all auto-generated I/O and can modify anything.

### Pattern: Failover

Automatic switchover between a primary and standby process.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Automatic high-availability; DDS-native ownership handles switchover; no external orchestrator needed | Adds heartbeat I/O overhead; standby process consumes resources; adds complexity to every participating process |

**Approaches** (selected at system level in Phase 1):

| Option | Description | When To Use |
|--------|-------------|-------------|
| 1. Hot Standby | Standby runs continuously, subscribes to all data. Primary publishes heartbeat. Standby takes over on heartbeat loss via EXCLUSIVE ownership. | Low switchover time (<1s), standby has warm state |
| 2. Cold Standby | Standby process is launched only when primary fails. External monitor detects failure and starts standby. | Resource-constrained, switchover time OK (5-10s) |
| 3. Active-Active | Both processes run and publish. Readers use EXCLUSIVE ownership + strength to pick the primary. If primary stops, reader auto-switches to secondary. | Zero-downtime, reader-side failover |

**Approach Pros & Cons:**

| Approach | Pros | Cons |
|----------|------|------|
| **Hot Standby** | Fastest switchover (<1s); standby has warm state; simple heartbeat-based detection | Standby consumes full resources; must keep standby state synchronized; heartbeat adds I/O |
| **Cold Standby** | Minimal resource usage when healthy; no standby synchronization needed | Slow switchover (5-10s); requires external launcher; cold start means no cached state |
| **Active-Active** | Zero switchover gap; DDS handles failover at reader level; no monitoring logic needed | Both processes publish continuously (double bandwidth); only works with EXCLUSIVE ownership topics |

**Option 1 (Hot Standby) auto-generates:**

```yaml
# Auto-added types — written to dds/datamodel/idl/system_patterns.idl during Phase 2
# Contains: ProcessRole (enum), HeartbeatStatus (struct)

# Auto-added I/O
outputs:
  - name: heartbeat_output
    topic: HeartbeatTopic
    type: system_patterns::HeartbeatStatus
    pattern: status
    pattern_option: 3          # Reliable Status with Deadline
    qos_profile: "SystemPatternsLibrary::HeartbeatQoS"
    rate_hz: 1
    callbacks: [publication_matched]
    auto_generated_by: failover.hot_standby

inputs:
  - name: heartbeat_input
    topic: HeartbeatTopic
    type: system_patterns::HeartbeatStatus
    pattern: status
    pattern_option: 3
    qos_profile: "SystemPatternsLibrary::HeartbeatQoS"
    callbacks: [data_available, liveliness_changed, requested_deadline_missed]
    auto_generated_by: failover.hot_standby

# Auto-added application logic markers
application_logic:
  - name: failover_monitor
    trigger: requested_deadline_missed on heartbeat_input
    action: "Promote self from STANDBY to PRIMARY. Start publishing on all outputs. Update heartbeat role."
    auto_generated_by: failover.hot_standby

  - name: ownership_switch
    trigger: role change to PRIMARY
    action: "Set EXCLUSIVE ownership strength to 100 on all outputs"
    auto_generated_by: failover.hot_standby

# Auto-added QoS
qos_additions:
  - profile: "SystemPatternsLibrary::HeartbeatQoS"
    settings:
      reliability: RELIABLE
      history: KEEP_LAST 1
      deadline: { period: 2s }
      liveliness: { kind: MANUAL_BY_TOPIC, lease_duration: 3s }
      ownership: EXCLUSIVE

# Auto-added tests
tests:
  unit:
    - name: test_heartbeat_publish
      verifies: heartbeat_output
      description: "Verify heartbeat published at 1Hz with correct role"
      checks: [data_received, field_values_correct, deadline_not_missed]
      auto_generated_by: failover.hot_standby
  integration:
    - name: test_failover_switchover
      description: "Launch primary + standby, kill primary, verify standby takes over"
      steps:
        - launch: { process: gps_tracker, args: "--role PRIMARY" }
        - launch: { process: gps_tracker, args: "--role STANDBY" }
        - wait: 5s
        - verify: { topic: HeartbeatTopic, field: role, value: PRIMARY }
        - kill: { process: gps_tracker, role: PRIMARY }
        - wait: 5s
        - verify: { topic: HeartbeatTopic, field: role, value: PRIMARY, from: standby }
      auto_generated_by: failover.hot_standby
```

**Option 3 (Active-Active) auto-generates:**

Similar to Hot Standby but:
- Both processes publish on all output topics (not just heartbeat)
- Uses EXCLUSIVE ownership + strength on every output
- Primary strength = 100, secondary strength = 50
- No switchover logic needed — DDS ownership handles it at the reader
- Test: kill primary → verify reader receives from secondary without gap

### Pattern: Health Monitoring

Periodic heartbeat publishing + failure detection.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Detects process/node failures early; enables automated recovery; provides system observability | Heartbeat traffic on the bus; false positives if deadlines too tight; must tune lease/deadline durations |

**Approaches:**

| Option | Detection Method | Use When |
|--------|-----------------|----------|
| 1. DDS Liveliness | Built-in DDS liveliness QoS (MANUAL_BY_TOPIC) | Simple presence detection |
| 2. Application Heartbeat | Custom heartbeat topic with health metrics | Need CPU/memory/uptime data |
| 3. Watchdog + Restart | Heartbeat + external monitor that restarts failed process | Self-healing system |

**Approach Pros & Cons:**

| Approach | Pros | Cons |
|----------|------|------|
| **DDS Liveliness** | Zero additional topics; built into DDS QoS; minimal configuration | Binary alive/dead only; no health metrics; limited to DDS-level detection |
| **Application Heartbeat** | Rich health data (CPU, memory, uptime); custom metrics; application-level visibility | Extra topic + type to maintain; must implement publishing logic; more data on the bus |
| **Watchdog + Restart** | Self-healing system; automatic process recovery; combines monitoring with action | Requires external watchdog process; restart logic adds complexity; cold restart loses state |

**Option 2 (Application Heartbeat) auto-generates:**

```yaml
# Auto-added types — written to dds/datamodel/idl/system_patterns.idl during Phase 2
# Contains: ProcessState (enum), HealthStatus (struct)

outputs:
  - name: health_output
    topic: HealthStatusTopic
    type: system_patterns::HealthStatus
    pattern: status
    pattern_option: 3          # Reliable Status with Deadline
    qos_profile: "SystemPatternsLibrary::HealthMonitorQoS"
    rate_hz: 1
    callbacks: [publication_matched]
    auto_generated_by: health_monitoring.app_heartbeat
```

### Pattern: Leader Election

Dynamic selection of a primary process among N peers.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Dynamic leader without external coordinator; DDS ownership makes it simple; handles N-way redundancy | Election protocol adds startup latency; split-brain risk if network partitions; consensus variant more complex |

**Approaches:**

| Option | Method | Use When |
|--------|--------|----------|
| 1. Ownership-Based | All peers publish with increasing strength; DDS picks highest | Simple, DDS-native |
| 2. Consensus-Based | Peers exchange votes on an election topic; majority wins | Need deterministic leader |

**Approach Pros & Cons:**

| Approach | Pros | Cons |
|----------|------|------|
| **Ownership-Based** | Simple; DDS-native; no custom protocol; instant leader selection via ownership strength | Static priority (pre-assigned); no peer agreement; highest-strength always wins regardless of state |
| **Consensus-Based** | Democratic; peers agree on leader; can factor in runtime state/capability | Complex vote protocol; election rounds add latency; must handle split-brain and tie-breaking |

**Option 1 auto-generates:** Election topic (type: LeaderBid with process_id, strength, timestamp), EXCLUSIVE ownership on all shared output topics, strength assignment logic (configurable priority per instance).

### Pattern: Request-Reply

Synchronous request/response communication.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Synchronous RPC over DDS; correlation tracking built-in; works across languages | Higher latency than pub/sub; requires timeout handling; not suitable for high-frequency calls |

**Auto-generates:**

```yaml
# Auto-added types — agent creates dds/datamodel/idl/<service>_types.idl during design
# Contains: ReplyStatus (enum), <Service>Request (struct), <Service>Reply (struct)
# The user defines the payload fields during the type design gate (Step 2b).

inputs:
  - name: <service>_request_input
    topic: <Service>RequestTopic
    type: <Service>Request
    pattern: event             # Reliable, KEEP_ALL
    qos_profile: "DataPatternsLibrary::EventQoS"

outputs:
  - name: <service>_reply_output
    topic: <Service>ReplyTopic
    type: <Service>Reply
    pattern: event
    qos_profile: "DataPatternsLibrary::EventQoS"

application_logic:
  - name: request_handler
    trigger: data_available on <service>_request_input
    action: "Process request, generate reply, publish on reply topic"
  - name: correlation
    trigger: always
    action: "Match reply.request_id to request.request_id for correlation"
```

### Pattern: Parameter Service

Runtime configuration management via a ROS2-style parameter server/client architecture. A parameter server process hosts named parameters (key-value pairs with typed values) and publishes change events. Client processes can get, set, and list parameters remotely. This is a **system-level decision** because the parameter types, topics, and QoS must be consistent across all participating processes.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Runtime reconfiguration without restart; centralized config management; event-driven change notification | 7-topic overhead per server/client pair; adds system complexity; must handle parameter validation |

**Approaches** (selected at system level in Phase 1):

| Option | Method | When To Use |
|--------|--------|-------------|
| 1. Standard | RELIABLE + TRANSIENT_LOCAL. Clients get current values on discovery. 7-topic set (Events, Get/Set/List request+response). | Most common — runtime reconfiguration |
| 2. Persistent | RELIABLE + PERSISTENT. Parameters survive process restart via durable writer. | Parameters must persist across restarts |

**Approach Pros & Cons:**

| Approach | Pros | Cons |
|----------|------|------|
| **Standard** | Late-joiners get current values; simpler setup; no persistence infrastructure | Parameters lost on full system restart; no disk-backed durability |
| **Persistent** | Parameters survive process and system restarts; durable storage | Requires persistence service or durable writer configuration; more complex setup; storage management |

**Roles** (assigned per-process in Phase 3 Step 1d):

| Role | Behavior |
|------|----------|
| `parameter_server` | Hosts parameter values, responds to get/set/list requests, publishes ParameterEvent on changes. Uses `DDSServerParameterSetup` wrapper. |
| `parameter_client` | Sends get/set/list requests, receives responses, subscribes to ParameterEvent. Uses `DDSClientParameterSetup` wrapper. |

**Auto-generates (for `parameter_server` role):**

```yaml
# Auto-added types — from dds/datamodel/idl/ (pre-existing parameter types)
# Contains: ParameterType (enum), ParameterValue (union), Parameter (struct),
#           ParameterEvent, SetParametersRequest/Response,
#           GetParametersRequest/Response, ListParametersRequest/Response

# Auto-added I/O
outputs:
  - name: parameter_events_output
    topic: ParameterEvents
    type: example_types::ParameterEvent
    pattern: parameter
    pattern_option: 1
    qos_profile: "DataPatternsLibrary::ParameterQoS"
    callbacks: [publication_matched]
    auto_generated_by: parameter_service.standard

inputs:
  - name: set_parameters_request_input
    topic: SetParametersRequest
    type: example_types::SetParametersRequest
    pattern: event
    qos_profile: "DataPatternsLibrary::EventQoS"
    callbacks: [data_available]
    auto_generated_by: parameter_service.standard

  - name: get_parameters_request_input
    topic: GetParametersRequest
    type: example_types::GetParametersRequest
    pattern: event
    qos_profile: "DataPatternsLibrary::EventQoS"
    callbacks: [data_available]
    auto_generated_by: parameter_service.standard

outputs:
  - name: set_parameters_response_output
    topic: SetParametersResponse
    type: example_types::SetParametersResponse
    pattern: event
    qos_profile: "DataPatternsLibrary::EventQoS"
    auto_generated_by: parameter_service.standard

  - name: get_parameters_response_output
    topic: GetParametersResponse
    type: example_types::GetParametersResponse
    pattern: event
    qos_profile: "DataPatternsLibrary::EventQoS"
    auto_generated_by: parameter_service.standard

# Application logic
application_logic:
  - name: parameter_server_handler
    trigger: data_available on set/get/list request inputs
    action: "Process request via DDSServerParameterSetup, publish response + event"
    auto_generated_by: parameter_service.standard

# Tests
tests:
  unit:
    - name: test_parameter_set_get
      description: "Set a parameter, get it back, verify value matches"
      auto_generated_by: parameter_service.standard
  integration:
    - name: test_parameter_service_e2e
      description: "Launch server, client sets param, verify event published and get returns new value"
      auto_generated_by: parameter_service.standard
```

**Auto-generates (for `parameter_client` role):**

The inverse — request outputs and response/event inputs. Uses `DDSClientParameterSetup` wrapper. The 7-topic set is the same; only the direction flips.

**Wrapper class integration:**

The parameter service uses dedicated wrapper classes that encapsulate the 7-topic complexity:
- `DDSServerParameterSetup` — creates all server-side entities from a single constructor call
- `DDSClientParameterSetup` — creates all client-side entities from a single constructor call
- `DDSParameterUtils` — shared utilities (make_parameter, load_from_yaml, etc.)

These wrappers already exist in `dds/utils/cxx11/` and handle entity creation, Content Filtered Topics, and async processing internally.

### Pattern: Command Arbitration

Multiple command sources write to the same command topic, and readers automatically receive from the highest-priority source via EXCLUSIVE ownership. This is a **system-level decision** because strength assignment and failover behavior must be consistent across all participating processes.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Deterministic priority among command sources; automatic failover to secondary; DDS-native via ownership | Only works for single-topic commands; strength must be pre-planned; dynamic priority adds state management |

**Approaches** (selected at system level in Phase 1):

| Option | Method | When To Use |
|--------|--------|-------------|
| 1. Priority-Based | EXCLUSIVE ownership with pre-assigned strengths per role. Primary source wins. If primary stops, reader auto-switches to secondary. | Most common — deterministic priority order among known command sources |
| 2. Dynamic Priority | EXCLUSIVE ownership with runtime-adjustable strength. Processes can raise/lower their priority based on conditions. | Adaptive systems where command authority changes based on state |

**Approach Pros & Cons:**

| Approach | Pros | Cons |
|----------|------|------|
| **Priority-Based** | Deterministic; simple to reason about; no runtime state changes; predictable failover order | Inflexible — priority can't adapt to conditions; requires upfront planning of all command sources |
| **Dynamic Priority** | Adapts to runtime conditions; processes can claim/release authority; flexible | More complex state management; risk of priority oscillation; must handle concurrent strength changes |

**Roles** (assigned per-process in Phase 3 Step 1d):

| Role | Ownership Strength | Behavior |
|------|-------------------|----------|
| `command_primary` | 100 | Preferred command source. Readers receive from this process when it's alive. |
| `command_secondary` | 50 | Fallback command source. Readers receive from this process only when primary is unavailable. |

**How it works at process design time:**

Unlike Failover or Health Monitoring, Command Arbitration does NOT auto-generate new topics or types. Instead, it **modifies the QoS of user-defined command I/O** at Step 2c:

- When a process with `role: command_primary` adds a command output (Step 2) → the agent auto-sets:
  - `pattern_option: 2` (Multi-source EXCLUSIVE)
  - `qos_profile: "DataPatternsLibrary::CommandPrimaryQoS"` (EXCLUSIVE, strength 100)
  - Liveliness monitoring on corresponding inputs
- When a process with `role: command_secondary` adds a command output → same, but:
  - `qos_profile: "DataPatternsLibrary::CommandSecondaryQoS"` (EXCLUSIVE, strength 50)

**Auto-applied QoS on opt-in:**

```yaml
# For command_primary role:
qos_additions:
  - profile: "DataPatternsLibrary::CommandPrimaryQoS"
    settings:
      reliability: RELIABLE
      history: KEEP_ALL
      ownership: EXCLUSIVE
      ownership_strength: 100
      liveliness: { kind: AUTOMATIC, lease_duration: 4s/10s }

# For command_secondary role:
qos_additions:
  - profile: "DataPatternsLibrary::CommandSecondaryQoS"
    settings:
      reliability: RELIABLE
      history: KEEP_ALL
      ownership: EXCLUSIVE
      ownership_strength: 50
      liveliness: { kind: AUTOMATIC, lease_duration: 4s/10s }
```

**Auto-generated tests:**

```yaml
tests:
  integration:
    - name: test_command_arbitration
      description: "Launch primary + secondary command sources. Verify reader receives from primary only. Kill primary. Verify reader switches to secondary."
      steps:
        - launch: { process: "{{command_primary_process}}", name: "primary" }
        - launch: { process: "{{command_secondary_process}}", name: "secondary" }
        - wait_for_discovery: 5s
        - verify: { topic: "{{command_topic}}", received: true, from: primary }
        - kill: { process: primary }
        - wait: 3s
        - verify: { topic: "{{command_topic}}", received: true, from: secondary }
      auto_generated_by: command_arbitration.priority_based
```

### Pattern: Sensor Redundancy

Multiple sensor/telemetry sources publish the same status topic, and readers automatically receive from the highest-priority (primary) source. If the primary sensor process fails, readers seamlessly switch to the secondary source. Uses the same EXCLUSIVE ownership mechanism as Command Arbitration but applied to periodic sensor/status data.

**Pattern Pros & Cons:**

| Pros | Cons |
|------|------|
| Seamless sensor failover; reader automatically switches sources; no application logic needed | Only works with EXCLUSIVE ownership topics; strength assignment is static (unless dynamic); adds ownership QoS constraints |

**Approaches** (selected at system level in Phase 1):

| Option | Method | When To Use |
|--------|--------|-------------|
| 1. Exclusive Failover | EXCLUSIVE ownership with pre-assigned strengths. Primary sensor wins. Reader auto-switches on primary failure. | Redundant sensors for the same measurement (e.g., two GPS receivers) |
| 2. Best-Quality Selection | EXCLUSIVE ownership with strength derived from data quality metrics (e.g., GPS accuracy, signal strength). Highest quality wins dynamically. | Sensors with varying quality — select the best source at runtime |

**Approach Pros & Cons:**

| Approach | Pros | Cons |
|----------|------|------|
| **Exclusive Failover** | Simple; deterministic primary/backup order; DDS handles switch automatically; no quality assessment needed | Always uses primary regardless of data quality; static assignment can't adapt to degraded sensors |
| **Best-Quality Selection** | Automatically selects best sensor based on real data quality; adapts to degradation | Must define and compute quality metrics; strength changes add complexity; quality assessment logic per-sensor |

**Roles** (assigned per-process in Phase 3 Step 1d):

| Role | Ownership Strength | Behavior |
|------|-------------------|----------|
| `sensor_primary` | 100 | Primary sensor source. Readers receive from this process when it's alive. |
| `sensor_secondary` | 50 | Fallback sensor source. Readers receive from this process only when primary is unavailable. |

**How it works at process design time:**

Like Command Arbitration, Sensor Redundancy modifies the QoS of user-defined sensor/status I/O rather than generating new topics:

- When a process with `role: sensor_primary` adds a status output → the agent auto-sets:
  - EXCLUSIVE ownership with strength 100
  - `qos_profile: "DataPatternsLibrary::StatusPrimaryQoS"`
  - Deadline + liveliness monitoring for failover detection
- When a process with `role: sensor_secondary` adds a status output → same, but:
  - `qos_profile: "DataPatternsLibrary::StatusSecondaryQoS"` (strength 50)

**Auto-applied QoS on opt-in:**

```yaml
# For sensor_primary role:
qos_additions:
  - profile: "DataPatternsLibrary::StatusPrimaryQoS"
    settings:
      reliability: BEST_EFFORT
      history: KEEP_LAST 1
      ownership: EXCLUSIVE
      ownership_strength: 100
      deadline: { period: 4s/10s }
      liveliness: { kind: AUTOMATIC, lease_duration: 4s/10s }

# For sensor_secondary role:
qos_additions:
  - profile: "DataPatternsLibrary::StatusSecondaryQoS"
    settings:
      reliability: BEST_EFFORT
      history: KEEP_LAST 1
      ownership: EXCLUSIVE
      ownership_strength: 50
      deadline: { period: 4s/10s }
      liveliness: { kind: AUTOMATIC, lease_duration: 4s/10s }
```

**Auto-generated tests:**

```yaml
tests:
  integration:
    - name: test_sensor_failover
      description: "Launch primary + secondary sensor sources. Verify reader receives from primary. Kill primary. Verify reader switches to secondary."
      steps:
        - launch: { process: "{{sensor_primary_process}}", name: "primary" }
        - launch: { process: "{{sensor_secondary_process}}", name: "secondary" }
        - wait_for_discovery: 5s
        - verify: { topic: "{{sensor_topic}}", received: true, from: primary }
        - kill: { process: primary }
        - wait: 3s
        - verify: { topic: "{{sensor_topic}}", received: true, from: secondary }
      auto_generated_by: sensor_redundancy.exclusive_failover
```

### How System Patterns Interact with the Planning Flow

**Phase 1 (System Design):** User selects which patterns the system uses and which approach per pattern. Stored in `system_config.yaml`.

**Phase 2 (System Implementation):** System-level types (HeartbeatStatus, HealthStatus, etc.) and QoS profiles are generated as shared baseline artifacts.

**Phase 3 (Process Design, Step 1d):** Per-process opt-in with role assignment:

```
Step 1d: User opts into "Failover" with role "PRIMARY"
            │
            ▼
    Agent auto-generates (using Hot Standby approach from system config):
      ✦ HeartbeatStatus type
      ✦ ProcessRole enum
      ✦ heartbeat_output (Status.3, 1Hz)
      ✦ heartbeat_input (Status.3, deadline monitoring)
      ✦ failover_monitor application logic
      ✦ ownership_switch application logic
      ✦ HeartbeatQoS profile
      ✦ test_heartbeat_publish (unit)
      ✦ test_failover_switchover (integration)
            │
            ▼
    Agent presents auto-generated I/O:
      "Failover (Hot Standby) adds the following to your design:

        TYPES (already generated as system baseline):
          enum ProcessRole { PRIMARY, STANDBY }
          struct HeartbeatStatus { @key process_id, role, sequence_num, timestamp }

        AUTO-ADDED I/O (for role: PRIMARY):
          ↓ heartbeat_input  ← HeartbeatTopic  [Status.3, HeartbeatQoS]
          ↑ heartbeat_output → HeartbeatTopic  [Status.3, HeartbeatQoS, 1Hz]

        APPLICATION LOGIC:
          • failover_monitor: on deadline miss → promote to PRIMARY
          • ownership_switch: on role change → set ownership strength

        TESTS:
          • test_heartbeat_publish (unit)
          • test_failover_switchover (integration)

        Accept these additions? [Accept / Modify / Remove pattern]"
            │
            ▼
    User confirms → Agent adds to YAML, continues to Step 2
    (User's custom I/O is added on top of the system pattern I/O)
```

### System Pattern I/O vs Custom I/O

All I/O — whether auto-generated by a system pattern or manually defined — lives in the same `inputs[]` and `outputs[]` lists. Two tags distinguish system pattern involvement:

- **`auto_generated_by`** — I/O-generating patterns (Failover, Health Monitoring) add entirely new I/O entries with this tag.
- **`auto_applied_by`** — QoS-modifying patterns (Command Arbitration, Sensor Redundancy) modify the QoS of user-defined I/O and tag it.

```yaml
inputs:
  # System pattern I/O (auto-generated by I/O-generating pattern)
  - name: heartbeat_input
    topic: HeartbeatTopic
    auto_generated_by: failover.hot_standby    # ← new I/O created by pattern
    ...

outputs:
  # Custom I/O with QoS auto-applied by QoS-modifying pattern
  - name: command_output
    topic: CommandTopic
    pattern_option: 2                           # ← auto-set by pattern
    qos_profile: "DataPatternsLibrary::CommandSecondaryQoS"
    auto_applied_by: command_arbitration.priority_based  # ← QoS modified by pattern
    ...

  # Pure custom I/O (no system pattern involvement)
  - name: position_output
    topic: PositionTopic
    ...                                         # ← no tags
```

This means:
- Implementation treats all I/O identically (same codegen pipeline)
- User can modify system pattern I/O (but gets a warning: "This was auto-generated by the Failover pattern. Modifying it may break failover behavior.")
- User can modify QoS-applied I/O (but gets a warning: "This QoS was set by Command Arbitration. Changing ownership or strength may break command priority behavior.")
- User can remove a system pattern entirely — removes all I/O tagged with that pattern, or reverts QoS modifications
- Tests for system pattern I/O are auto-generated alongside custom I/O tests

### Combining System Patterns

A process can opt into multiple system patterns. They compose additively. Since both approaches are defined at the system level, the overlap detection happens once during Phase 2 (System Implementation):

```
System-level patterns: [failover.hot_standby, health_monitoring.app_heartbeat]

  Failover adds:        heartbeat_input, heartbeat_output, ProcessRole, HeartbeatStatus
  Health Monitoring adds: health_output, HealthStatus, ProcessState

  Overlap detection (during Phase 2):
  Agent: "Failover already adds a HeartbeatStatus topic.
          Health Monitoring can extend it with cpu/memory fields,
          or use a separate HealthStatusTopic.
          Which approach? [Extend HeartbeatStatus / Separate topic]"
```

---

## Data Patterns Reference

Data patterns determine QoS, callbacks, and code structure **per individual I/O**. They are the building blocks that system patterns compose.

### Pattern: Event
Aperiodic critical data that cannot be lost.

| Option | Reliability | History | Liveliness | Use When |
|--------|------------|---------|------------|----------|
| 1. Standard Event | RELIABLE | KEEP_ALL | AUTOMATIC 4s/10s | Button presses, alerts |
| 2. Command Override | RELIABLE + EXCLUSIVE | KEEP_ALL | AUTOMATIC | Multi-source arbitration |
| 3. Lightweight Event | RELIABLE | KEEP_LAST 1 | None | Frequent events, only latest |

**Auto-resolve**: Type name contains "Button", "Alert", "Event" → Event pattern, option 1.

### Pattern: Status
Periodic sensor/telemetry data.

| Option | Reliability | History | Deadline | Use When |
|--------|------------|---------|----------|----------|
| 1. Standard Status | BEST_EFFORT | KEEP_LAST 1 | 4s/10s | Periodic position, health |
| 2. Downsampled | BEST_EFFORT | KEEP_LAST 1 | + TIME_BASED_FILTER | Reader at lower rate |
| 3. Reliable Status | RELIABLE | KEEP_LAST 1 | Deadline | Every update matters |

**Auto-resolve**: Type name contains "Position", "State", "Health", "Telemetry" → Status, option 1. Declared `rate_hz` confirms periodic. If subscriber declares `downsample_hz` < publisher's `rate_hz` (or user says "at lower rate", "downsampled", "1 Hz from a 10 Hz") → Status, option 2 (Downsampled). The agent auto-sets `downsample_hz` on the input and applies `TIME_BASED_FILTER` with `minimum_separation` = 1/downsample_hz.

### Pattern: Command
Control messages with optional priority arbitration.

| Option | Ownership | Strength | Use When |
|--------|-----------|----------|----------|
| 1. Single-source | SHARED | N/A | One command source per topic |
| 2. Multi-source | EXCLUSIVE | Role-based | Priority arbitration (**requires Command Arbitration system pattern**) |

**Auto-resolve**: Type name contains "Command" → Command pattern, option 1. If Command Arbitration system pattern is active and process has `command_primary` or `command_secondary` role → option 2 with role-based strength (auto-applied, user does not choose). If user mentions "priority" or "override" but Command Arbitration is not enabled → agent warns: "Multi-source command arbitration requires the Command Arbitration system pattern. Add it in System Design first."

> **Rule:** Command option 2 (multi-source) is NOT available as a standalone per-I/O choice. It requires the Command Arbitration system pattern to be declared at the system level. This ensures strength assignment and failover behavior are coordinated across all participating processes.

### Pattern: Parameter
Runtime configuration key-value pairs. **Requires the Parameter Service system pattern** — the 7-topic infrastructure and wrapper classes are system-level.

| Option | Reliability | Durability | Use When |
|--------|------------|-----------|----------|
| 1. Standard Parameter | RELIABLE | TRANSIENT_LOCAL | ROS2-style get/set |
| 2. Persistent Parameter | RELIABLE | PERSISTENT | Survives restart |

**Auto-resolve**: Type name contains "Parameter", "Config", "Setting" → Parameter, option 1 — but only if the Parameter Service system pattern is active. If not, agent warns: "Enable Parameter Service in System Design first."

> **Rule:** The parameter data pattern is NOT available as a standalone per-I/O choice. It requires the Parameter Service system pattern because the 7-topic set (Events, Get/Set/List request+response) and `DDSServerParameterSetup`/`DDSClientParameterSetup` wrappers are shared system infrastructure. When a process opts in as `parameter_server` or `parameter_client`, the I/O is auto-generated.

### Pattern: Large Data
Payloads > 64KB requiring transport optimization.

| Option | Transport | Zero-Copy | Use When |
|--------|-----------|-----------|----------|
| 1. SHMEM | SHMEM only | No | Intra-host, lowest latency |
| 2. SHMEM Zero-Copy | SHMEM ref | Yes | Intra-host, no copies |
| 3. UDP | UDP | No | Cross-host, burst transfer |

**Auto-resolve**: Type has `@final @language_binding(FLAT_DATA)` → option 2. Type has `sequence<octet>` with max > 65535 → option 1. User mentions "network" or "UDP" → option 3.

#### Language Constraints (Large Data)

Zero-Copy (Option 2) uses FlatData annotations (`@language_binding(FLAT_DATA)`, `@transfer_mode(SHMEM_REF)`) which have cross-language implications:

| Constraint | Rule | Behavior |
|-----------|------|----------|
| **FlatData is C++ only** | Zero-Copy (Option 2) requires the FlatData builder/loan API, which is available only in the Modern C++ API. Python and Java do **not** support FlatData write APIs. | If process `language` is Python or Java, Option 2 is **not available**. |
| **Python subscribers to FlatData topics** | A Python subscriber **can** read from a FlatData topic. DDS handles XCDR2 deserialization transparently — the Python reader sees a normal sample. However, the subscriber must use standard SHMEM QoS (Option 1), not zero-copy QoS. | Python readers use `LargeDataSHMEMParticipant` QoS profile — no FlatData-specific reader configuration needed. |
| **Auto-downgrade rule** | If auto-resolve detects `@language_binding(FLAT_DATA)` on a type AND the process language is Python (or Java): (1) force Option 1 (SHMEM) instead of Option 2, (2) emit a warning: "FlatData zero-copy is not available in Python. Using SHMEM transport instead. The Python reader will receive data via standard DDS deserialization.", (3) record the downgrade in `decisions:`. | The agent applies this rule during Pattern & QoS resolution (Step 2c of Process Design). |
| **Mixed-language topic** | When a C++ publisher uses FlatData (Option 2) and a Python subscriber reads the same topic: the C++ writer uses `LargeDataSHMEMParticipant` participant QoS + `LargeDataSHMEM_ZCQoS` data writer QoS with FlatData builder API; the Python reader uses `LargeDataSHMEMParticipant` participant QoS + `LargeDataSHMEMQoS` data reader QoS and standard `data_available` handler. Both work on the same topic — XCDR2 encoding is interoperable. | No special configuration needed beyond correct per-process QoS profile selection. |

### Pattern → Code Mapping

Each pattern determines what code gets generated:

| Pattern | Writer Code | Reader Code | Special |
|---------|------------|------------|---------|
| Event | `write()` in callback/trigger | `data_available` handler | Liveliness monitoring |
| Status | Periodic `write()` in timer loop | `data_available` handler | Deadline QoS |
| Command | `write()` on-demand | `data_available` handler | Optional ownership strength |
| Parameter | Request/reply via 5-topic set | Full parameter server/client | Utils classes required |
| Large Data | `write()` with pre-allocated buffer | `data_available` with loan | Transport config |
