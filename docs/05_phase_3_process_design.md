# Phase 3: Process Design

## Planning Loop

Planning follows a fixed sequence for new processes, but the user can jump to any step for modifications:

```
┌─────────────────────────────────────────────────────────────────┐
│  PLANNING LOOP                                                   │
│                                                                  │
│  New Process:                                                    │
│    Step 1: Process Identity (name, transport, domain)            │
│    Step 1d: System Pattern Opt-In (from system-level patterns)   │
│            → auto-generates types, I/O, logic, tests             │
│    Step 2: Define I/O (custom inputs + outputs, one at a time)   │
│    Step 3: Define Tests (auto-proposed from all I/O)             │
│    Step 4: Review complete design                                │
│                                                                  │
│  After Step 4:                                                   │
│    → "Add more I/O"              — returns to Step 2            │
│    → "Opt-in to system pattern"  — returns to Step 1d           │
│    → "Modify something"          — jump to any step             │
│    → "Ready to implement"        — proceed to Phase 4           │
│    → "Save and plan another"     — save YAML, start new process │
│    → "Save and exit"             — saves YAML, come back later  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Step 1: Process Identity

With project and system config already set, Step 1 only asks for process-specific settings:

**1a. Process name** (free text):
```
What should this process be called?
> gps_tracker
```

**1b. Domain ID override** (optional):
```
Domain ID? (system default: 0)
  Press Enter to use system default, or enter a different ID.
```

**1c. Transport selection** (per-process):
```
How does this process communicate?

  1. SHMEM + UDP     — co-located + optional remote (most common)
  2. SHMEM only      — all readers/writers on same host
  3. UDP only        — distributed, network-only
  4. TCP             — firewall-friendly, WAN-capable
  5. Custom          — specify transports manually

  Default: 1 (SHMEM + UDP)
```

**1d. System Pattern Opt-In** (from system-level patterns only):

Only patterns declared in `system_config.yaml` are offered — the user does NOT see the full catalog. The approach (e.g., Hot Standby) is already decided at the system level.

```
Your system uses: Failover (Hot Standby), Health Monitoring (App Heartbeat)

Does this process participate?
  [ ] Failover        → Role: PRIMARY / STANDBY
  [ ] Health Monitoring → publishes HealthStatus from this node
```

If no system patterns are configured, this step is skipped entirely.

When the user opts in to a system pattern, the agent **auto-generates the required I/O, types, and application logic** for that pattern using the approach from system config. The user then reviews and can modify. See [System Patterns Catalog](07_patterns_reference.md#system-patterns-catalog) for what each pattern adds.

After Step 1, the design has:

```yaml
process:
  name: gps_tracker
  description: ""  # filled in during review
  domain_id: null               # null = inherit from system_config
  transports: [SHMEM, UDP]      # per-process transport selection
  system_config_version: 1      # tracks which system config version this was designed against
  system_patterns:              # opt-in to system-level patterns (with role, not approach)
    - pattern: failover
      role: primary             # role assigned per-process (primary / standby)
    - pattern: health_monitoring
      role: publisher           # this node publishes health data
```

Framework and API are inherited from `planning/project.yaml` — not stored per-process.
System pattern **approaches** are inherited from `planning/system_config.yaml` — only **roles** are per-process.
Transports are per-process because different processes may run on different hosts.

If system patterns were opted into, the agent immediately generates the required I/O entries (types, topics, patterns, QoS, callbacks) and presents them: "These I/O were auto-added by the Failover pattern. Review and confirm."

## Step 2: Inputs & Outputs

This is the core of planning. The user describes what the process reads and writes.

Each I/O walks through a **mandatory 3-step sub-loop**: (1) Name & direction → (2) **Data type** → (3) Pattern & QoS. The data type step is a hard gate — the I/O cannot proceed until a type is defined or selected.

**Entry — natural language or structured**:

The user can describe I/O naturally:
```
Describe what this process reads and writes:
> It subscribes to Command messages and publishes Position at 2Hz
```

Or add one at a time:
```
Add an input or output?

  1. Add Input (subscription)
  2. Add Output (publication)
  3. Done with I/O
```

---

### Per-I/O sub-loop

For each I/O, the agent walks through three steps in order:

**Step 2a — Topic name & direction**

| Field | How Determined |
|-------|---------------|
| **Topic name** | User provides or inferred from description |
| **Direction** | Input = subscribe, Output = publish |

**Step 2b — Data type (mandatory gate)**

Before pattern or QoS can be set, the type must be resolved. The agent presents a choice:

```
Data type for "PositionTopic"?

  1. 🆕 Define New Type
  2. 📂 Select Existing Type

```

**Option 1 — Define New Type**:

The datamodel sub-prompt walks through the full type definition:

```
Define the type for PositionTopic:

  Type name: Position
  Module (namespace): gps_types

  Fields:
    1. device_id : string<64>    @key
    2. latitude  : double
    3. longitude : double
    4. altitude  : float
    5. timestamp : uint64

  Add another field? [yes/no]

  Annotations:
    - @key on device_id (instances per device)

  IDL preview:
    module gps_types {
      @final
      struct Position {
        @key string<64> device_id;
        double latitude;
        double longitude;
        float altitude;
        uint64 timestamp;
      };
    };

  [Confirm / Edit field / Add field]
```

On confirmation, the agent **immediately writes the `.idl` file**:
- Creates/updates `dds/datamodel/idl/gps_types.idl` with the confirmed IDL
- If the module file already exists, merges the new type into it (no duplicates)
- Updates `dds/datamodel/idl/Definitions.idl` with topic constants
- The PROCESS_DESIGN.yaml records a **reference** to the file path, not the IDL content

If the type requires supporting types (enums, nested structs), those are defined first:

```
The Command type needs a CommandAction enum. Define it now:

  enum CommandAction { START, STOP, RESET, CALIBRATE };

  [Confirm / Edit]
```

**Option 2 — Select Existing Type**:

The agent scans all known types from:
- `dds/datamodel/idl/*.idl` (already in workspace)
- Types defined in other process designs (`planning/processes/*.yaml`)
- Types defined earlier in this session

```
Available types:

  1. gps_types::Command        — device_id, action, value  (used by: gps_controller)
  2. gps_types::Position       — device_id, lat, lon, alt  (used by: gps_tracker)
  3. image_types::ImageFrame   — sensor_id, data, width    (used by: camera_feeder)
  4. system::Heartbeat         — source_id, counter        (auto-generated)

Select type [1-4]: 2

  struct Position {
    @key string<64> device_id;
    double latitude;
    double longitude;
    float altitude;
    uint64 timestamp;
  };

  Use this type? [Yes / No, define a new one instead]
```

If no existing types exist, the agent skips directly to "Define New Type."

**Step 2c — Pattern & QoS**

Once the type is locked in, the agent resolves pattern and QoS:

```
What data pattern for the Position output?

  1. Status (periodic)  — BEST_EFFORT, KEEP_LAST 1, Deadline
     → For periodic telemetry. Loss OK. Deadline detects writer failure.
  2. Event (aperiodic)  — RELIABLE, KEEP_ALL, Liveliness
     → For critical data that cannot be lost.
  3. Large Data         — SHMEM/ZC transport-optimized
     → For payloads > 64KB.

  Auto-selected: 1 (Status) — periodic data at 2Hz

  Status option:
    1a. Standard Status — BEST_EFFORT, Deadline 4s/10s
    1b. Downsampled     — adds TIME_BASED_FILTER
    1c. Reliable Status — RELIABLE, Deadline

  Default: 1a (Standard Status)
```

| Field | How Determined |
|-------|---------------|
| **Pattern** | Auto-inferred from type name / user description, or asked |
| **Pattern option** | Asked if multiple options, else default |
| **QoS profile** | Derived from pattern selection |
| **Rate (outputs)** | Asked if status/periodic pattern |
| **Callbacks** | Auto-set based on pattern |

---

After defining all I/O, the design has:

```yaml
idl_files:
  - dds/datamodel/idl/gps_types.idl       # Created during design — contains Command, Position

inputs:
  - name: command_input
    topic: CommandTopic
    type: gps_types::Command
    pattern: command
    pattern_option: 1
    qos_profile: "DataPatternsLibrary::EventQoS"
    callbacks: [data_available, liveliness_changed]

outputs:
  - name: position_output
    topic: PositionTopic
    type: gps_types::Position
    pattern: status
    pattern_option: 1
    qos_profile: "DataPatternsLibrary::StatusQoS"
    rate_hz: 2
    callbacks: [publication_matched]
```

## Step 3: Tests

Tests are **auto-proposed** from the I/O definitions. The user reviews and can add/modify/remove.

**Auto-proposal logic**:

| I/O Type | Pattern | Auto-Generated Tests |
|----------|---------|---------------------|
| Any input | Any | Unit: write to topic → verify callback fires |
| Any output | Any | Unit: create writer → publish → verify via reader |
| Output | Status | Unit: verify deadline not missed at declared rate |
| Input | Command | Integration: send command → verify process acts on it |
| Output | Large Data | Unit: verify payload size, throughput |
| Any | Any | Integration: launch process → verify I/O end-to-end |

**Presentation**:

```
Tests (auto-proposed from your I/O definitions):

  Unit Tests:
    ✓ test_position_publish
      Verify Position data is published correctly
      Checks: data_received, field_values_correct, deadline_not_missed

    ✓ test_command_receive
      Verify Command data is received and callback fires
      Checks: data_received, liveliness_detected

  Integration Tests:
    ✓ test_gps_tracker_e2e
      Launch gps_tracker, send Command(START), wait 3s,
      verify Position published at >= 1Hz
      Checks: process_starts, data_flows_end_to_end

  [Accept all / Add a test / Remove a test / Modify a test]
```

After this step, the design has:

```yaml
tests:
  unit:
    - name: test_position_publish
      verifies: position_output
      description: "Create writer, publish Position, verify via reader"
      checks: [data_received, field_values_correct, deadline_not_missed]

    - name: test_command_receive
      verifies: command_input
      description: "Create writer, send Command, verify callback fires"
      checks: [data_received, liveliness_detected]

  integration:
    - name: test_gps_tracker_e2e
      description: "Launch gps_tracker, send Command, verify Position output"
      steps:
        - launch: gps_tracker
        - wait_for_discovery: 5s
        - publish: { topic: CommandTopic, data: { action: START } }
        - wait: 3s
        - verify: { topic: PositionTopic, received: true, min_rate_hz: 1 }
        - stop: gps_tracker
```

## Step 4: Review

The agent presents the complete `PROCESS_DESIGN.yaml` and asks:

```
═══════════════════════════════════════════════════
  PROCESS DESIGN: gps_tracker
═══════════════════════════════════════════════════

  Framework:  Wrapper Class (C++11)       ← from project config (locked)
  API:        Modern C++                  ← from project config (locked)
  Domain:     0                           ← from system config
  Patterns:   Failover (PRIMARY), Health  ← system-level, opted-in
  Transports: SHMEM + UDP                 ← per-process

  TYPES:
    enum CommandAction { START, STOP, RESET, CALIBRATE }
    struct Command { @key device_id, action, value }
    struct Position { @key device_id, latitude, longitude, altitude, timestamp }

  INPUTS (subscribes to):
    command_input → CommandTopic [Command pattern, EventQoS]

  OUTPUTS (publishes):
    position_output → PositionTopic [Status pattern, StatusQoS, 2Hz]

  TESTS:
    Unit: test_position_publish, test_command_receive
    Integration: test_gps_tracker_e2e

═══════════════════════════════════════════════════

  What would you like to do?

    1. Implement Now              — generate code, build, and test
    2. Add More I/O               — return to Step 2
    3. Opt-in System Pattern      — opt-in to patterns from system config
    4. Modify Process Settings    — change domain ID, system patterns
    5. Modify a Type              — edit fields, annotations
    6. Modify Tests               — add/remove/change tests
    7. Save and Plan Another      — save this design, start a new process
    8. Save and Exit              — save design, come back later

  Recommended: 1 (design is complete)
```

---

## PROCESS_DESIGN.yaml

This is the **single source of truth** — the complete specification of one DDS process. Planning writes it; implementation reads it.

### Complete Schema

```yaml
# planning/processes/gps_tracker.yaml
# Generated by /rti_dev Phase 3: Process Design
# Last modified: 2026-03-17T14:30:00Z
# Project config: planning/project.yaml (Wrapper Class, Modern C++)
# System config: planning/system_config.yaml (v1, Failover + Health Monitoring)

process:
  name: gps_tracker
  description: "Reads GPS coordinates from sensor, publishes position.
                Receives command messages to control tracking."
  domain_id: null                 # null = inherit from system_config (0)
  transports: [SHMEM, UDP]        # per-process transport selection
  system_config_version: 1        # tracks which system config version this was designed against
  system_patterns:                # opted-in system-level behaviors (role is per-process, approach from system config)
    - pattern: failover
      role: primary               # primary | standby (approach: hot_standby inherited from system config)
    - pattern: health_monitoring
      role: publisher             # this node publishes health data

# IDL files created during design (the source of truth for data modeling).
# The agent writes actual .idl files to dds/datamodel/idl/ during Phase 3 Step 2b.
# During implementation, rtiddsgen generates code from these files for the selected API.
idl_files:
  - dds/datamodel/idl/gps_types.idl       # Contains: CommandAction, Command, Position

# What this process subscribes to
inputs:
  - name: command_input           # internal name (used in code variable names)
    topic: CommandTopic           # DDS topic name
    type: gps_types::Command      # fully qualified type
    pattern: command              # event | status | command | parameter | large_data
    pattern_option: 1             # option within pattern (see Data Patterns)
    qos_profile: "DataPatternsLibrary::EventQoS"
    callbacks:
      - data_available
      - liveliness_changed

# What this process publishes
outputs:
  - name: position_output
    topic: PositionTopic
    type: gps_types::Position
    pattern: status
    pattern_option: 1
    qos_profile: "DataPatternsLibrary::StatusQoS"
    rate_hz: 2                    # publish rate (for status/periodic patterns)
    callbacks:
      - publication_matched

# Tests to generate and run
tests:
  unit:
    - name: test_position_publish
      verifies: position_output
      description: "Create writer, publish Position, verify via reader"
      checks:
        - data_received
        - field_values_correct
        - deadline_not_missed

    - name: test_command_receive
      verifies: command_input
      description: "Create writer, send Command, verify callback fires"
      checks:
        - data_received
        - liveliness_detected

  integration:
    - name: test_gps_tracker_e2e
      description: "Launch process, send Command, verify Position output"
      steps:
        - launch: gps_tracker
        - wait_for_discovery: 5s
        - publish:
            topic: CommandTopic
            data: { action: START, device_id: "test_device" }
        - wait: 3s
        - verify:
            topic: PositionTopic
            received: true
            min_rate_hz: 1
            fields: { device_id: "test_device" }
        - stop: gps_tracker

# Decisions made during planning (for traceability / re-planning)
decisions:
  - id: plan.transports
    selected: [SHMEM, UDP]
    rationale: "Default — co-located + optional remote"
    timestamp: "2026-03-17T14:30:00Z"
  - id: plan.system_pattern_optin.failover
    selected: "primary"
    rationale: "User opted in as primary node"
    timestamp: "2026-03-17T14:30:05Z"
  - id: plan.pattern.CommandTopic
    selected: "command.1"
    rationale: "Auto-resolved: type name contains 'Command'"
    timestamp: "2026-03-17T14:30:10Z"
  - id: plan.pattern.PositionTopic
    selected: "status.1"
    rationale: "User confirmed: periodic data at 2Hz"
    timestamp: "2026-03-17T14:30:15Z"
```

### Schema Rules

| Field | Required | Validation |
|-------|----------|------------|
| `process.name` | Yes | Valid C identifier (no spaces, starts with letter) |
| `process.domain_id` | No | null = inherit from system_config; or 0-232 |
| `process.transports` | Yes | At least one of: SHMEM, UDP, TCP |
| `process.system_config_version` | Yes | Integer >= 1; must match or be reconciled with current system config |
| `process.system_patterns` | No | Each must reference a pattern from system_config + a valid role |
| `idl_files` | Yes (if new types) | List of `.idl` file paths created during design. Files must exist in workspace. |
| `inputs[]` or `outputs[]` | At least one | Process must have at least one I/O |
| `*.pattern` | Yes | One of: `event`, `status`, `command`, `parameter`, `large_data` |
| `*.qos_profile` | Yes | Must resolve to a profile in generated QoS XML |
| `tests.unit` | Yes | At least one unit test per I/O |
| `tests.integration` | Recommended | At least one end-to-end test |
| `*.auto_generated_by` | No | Tag for I/O added by system patterns (do not remove) |
