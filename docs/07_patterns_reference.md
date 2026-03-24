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

**Approaches** (selected at system level in Phase 1):

| Option | Description | When To Use |
|--------|-------------|-------------|
| 1. Hot Standby | Standby runs continuously, subscribes to all data. Primary publishes heartbeat. Standby takes over on heartbeat loss via EXCLUSIVE ownership. | Low switchover time (<1s), standby has warm state |
| 2. Cold Standby | Standby process is launched only when primary fails. External monitor detects failure and starts standby. | Resource-constrained, switchover time OK (5-10s) |
| 3. Active-Active | Both processes run and publish. Readers use EXCLUSIVE ownership + strength to pick the primary. If primary stops, reader auto-switches to secondary. | Zero-downtime, reader-side failover |

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

**Approaches:**

| Option | Detection Method | Use When |
|--------|-----------------|----------|
| 1. DDS Liveliness | Built-in DDS liveliness QoS (MANUAL_BY_TOPIC) | Simple presence detection |
| 2. Application Heartbeat | Custom heartbeat topic with health metrics | Need CPU/memory/uptime data |
| 3. Watchdog + Restart | Heartbeat + external monitor that restarts failed process | Self-healing system |

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

**Approaches:**

| Option | Method | Use When |
|--------|--------|----------|
| 1. Ownership-Based | All peers publish with increasing strength; DDS picks highest | Simple, DDS-native |
| 2. Consensus-Based | Peers exchange votes on an election topic; majority wins | Need deterministic leader |

**Option 1 auto-generates:** Election topic (type: LeaderBid with process_id, strength, timestamp), EXCLUSIVE ownership on all shared output topics, strength assignment logic (configurable priority per instance).

### Pattern: Request-Reply

Synchronous request/response communication.

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

### Pattern: Redundant Publisher

Multiple writers for the same topic, reader selects best source.

**Auto-generates:** EXCLUSIVE ownership on output topics, configurable strength per process instance, liveliness monitoring so reader detects when a writer disappears.

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

All I/O — whether auto-generated by a system pattern or manually defined — lives in the same `inputs[]` and `outputs[]` lists. The only difference is the `auto_generated_by` tag:

```yaml
inputs:
  # System pattern I/O (auto-generated)
  - name: heartbeat_input
    topic: HeartbeatTopic
    auto_generated_by: failover.hot_standby    # ← tagged
    ...

  # Custom I/O (user-defined)
  - name: command_input
    topic: CommandTopic
    auto_generated_by: null                     # ← no tag
    ...
```

This means:
- Implementation treats all I/O identically (same codegen pipeline)
- User can modify system pattern I/O (but gets a warning: "This was auto-generated by the Failover pattern. Modifying it may break failover behavior.")
- User can remove a system pattern entirely — removes all I/O tagged with that pattern
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

**Auto-resolve**: Type name contains "Position", "State", "Health", "Telemetry" → Status, option 1. Declared `rate_hz` confirms periodic.

### Pattern: Command
Control messages with optional priority arbitration.

| Option | Ownership | Strength | Use When |
|--------|-----------|----------|----------|
| 1. Single-source | SHARED | N/A | One command source per topic |
| 2. Multi-source | EXCLUSIVE | 10/20/30 | Priority arbitration |

**Auto-resolve**: Type name contains "Command" → Command pattern, option 1. If user mentions "priority" or "override" → option 2.

### Pattern: Parameter
Runtime configuration key-value pairs.

| Option | Reliability | Durability | Use When |
|--------|------------|-----------|----------|
| 1. Standard Parameter | RELIABLE | TRANSIENT_LOCAL | ROS2-style get/set |
| 2. Persistent Parameter | RELIABLE | PERSISTENT | Survives restart |

**Auto-resolve**: Type name contains "Parameter", "Config", "Setting" → Parameter, option 1.

### Pattern: Large Data
Payloads > 64KB requiring transport optimization.

| Option | Transport | Zero-Copy | Use When |
|--------|-----------|-----------|----------|
| 1. SHMEM | SHMEM only | No | Intra-host, lowest latency |
| 2. SHMEM Zero-Copy | SHMEM ref | Yes | Intra-host, no copies |
| 3. UDP | UDP | No | Cross-host, burst transfer |

**Auto-resolve**: Type has `@final @language_binding(FLAT_DATA)` → option 2. Type has `sequence<octet>` with max > 65535 → option 1. User mentions "network" or "UDP" → option 3.

### Pattern → Code Mapping

Each pattern determines what code gets generated:

| Pattern | Writer Code | Reader Code | Special |
|---------|------------|------------|---------|
| Event | `write()` in callback/trigger | `data_available` handler | Liveliness monitoring |
| Status | Periodic `write()` in timer loop | `data_available` handler | Deadline QoS |
| Command | `write()` on-demand | `data_available` handler | Optional ownership strength |
| Parameter | Request/reply via 5-topic set | Full parameter server/client | Utils classes required |
| Large Data | `write()` with pre-allocated buffer | `data_available` with loan | Transport config |
