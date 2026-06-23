# Iterative Workflow

## Typical Session: First Process (Fresh Workspace)

```
/rti_dev

State: No project initialized. Fresh workspace.

  [Phase 0: Project Init]
  Agent: "Let's initialize your DDS project.
          ⚠ These choices are PERMANENT.
          1. Framework? [Wrapper Class / XML App]
          2. API? [Modern C++ / Python / Java / C / Both]"
  User: "Wrapper Class, Modern C++"
  → Saves planning/project.yaml (locked)

  [Phase 1: System Design]
  Agent: "System Design.
          1. Default Domain ID? (0-232)
          2. System Patterns?
             [ ] Failover  [ ] Health  [ ] Leader  [ ] Req-Reply  [ ] Redundant"
  User: "Domain 0, Failover (Hot Standby), Health Monitoring (App Heartbeat)"
  → Saves planning/system_config.yaml (version: 1)

  [Phase 2: System Implementation]
  Agent: "Generating system baseline..."
  → Agent reads system_manifest.yaml, creates directories, generates system IDL/QoS, runs rtiddsgen
  → system_patterns.idl, SystemPatternsQoS.xml, directory structure created

  [Level 1]
  1. 🛠 Design Mode    [only option — nothing to implement yet]
  2. ✅ Done

User: 1 (Design Mode)

  [Level 2a — Process Picker]
  (no existing processes)
  1. ➕ Add New Process

User: 1 (Add New)
→ Step 1: "gps_tracker", domain 0, SHMEM+UDP
→ Step 1d: "Participate in Failover? → PRIMARY. Health Monitoring? → Yes"
           Agent auto-generates heartbeat + health I/O, user accepts.
→ Step 2: "subscribes to Command, publishes Position at 2Hz"
           Agent defines types, auto-selects patterns
→ Step 3: Agent proposes 2 unit + 1 integration test. User accepts.
→ Step 4: Review. User says "Implement Now"

→ Phase 4 runs: scaffold, write IDL, rtiddsgen, app code, QoS, tests, build, run tests
→ All pass. ✓

  [Level 1 — auto-return]
  1. 🛠 Design Mode
  2. 🚀 Implement        (nothing pending)
  3. 🏗️  System Design
  4. ✅ Done              [recommended]
```

## Adding a Second Process (Incremental)

```
/rti_dev

Project: Wrapper Class | Modern C++ [locked]
System: Failover (Hot Standby), Health Monitoring | domain 0 | v1
State: ✓ gps_tracker implemented, tests pass

  [Level 1]
  1. 🛠 Design Mode
  2. 🚀 Implement       (nothing pending)
  3. 🏗️  System Design
  4. ✅ Done             [recommended]

User: 1 (Design Mode)

  [Level 2a — Process Picker]
  1. gps_tracker          ✓ implemented    — modify design
  2. ➕ Add New Process

User: 2 (Add New)
→ Step 1: "command_controller", SHMEM+UDP, domain 0, opt-in: Failover (STANDBY)
→ Step 2: "publishes Command messages with priority arbitration"
           Agent: "Type Command already exists. Reuse? [Yes]"
           User picks Command pattern option 2 (multi-source)
→ Step 3: Tests proposed. User accepts.
→ Step 4: "Implement Now"

→ Implementation: scaffold copied, IDL already has Command type (skipped),
   generates command_controller.cxx with ownership strengths,
   merges new QoS profiles into existing XML,
   generates tests, builds, runs
→ All pass. ✓

  [Level 1 — auto-return]
  1. 🛠 Design Mode
  2. 🚀 Implement       (nothing pending)
  3. ✅ Done             [recommended]
```

## Design Multiple, Implement Later (Batch)

The user can stay in planning mode to design several processes before implementing any of them:

```
/rti_dev

State: Fresh workspace.
User: 1 (Design Mode) → 1 (➕ Add New)

→ Plans gps_tracker (Step 1–4)
→ Step 4 review:
    1. Implement Now
    2. Add More I/O
    3. Save and Plan Another Process    ← user picks this
    4. Save and Exit

User: 3 (Save and Plan Another)
→ gps_tracker.yaml saved to planning/processes/
→ Returns to Level 2a (process picker, refreshed):

  [Level 2a — Process Picker]
  1. gps_tracker       📋 designed       — continue editing
  2. ➕ Add New Process

User: 2 (➕ Add New)
→ Plans command_controller (Step 1–4)
→ Step 4 review: User picks "Save and Plan Another"
→ Returns to Level 2a:

  [Level 2a — Process Picker]
  1. gps_tracker          📋 designed
  2. command_controller   📋 designed
  3. ➕ Add New Process

User: 3 (➕ Add New)
→ Plans health_monitor (Step 1–4)
→ Step 4 review: User picks "Save and Exit"
→ Returns to Level 1:

  [Level 1]
  1. 🛠 Design Mode
  2. 🚀 Implement          ← 3 designs ready
  3. ✅ Done

User: 2 (Implement)

  [Level 2b — Implement Picker]
  1. gps_tracker          📋 ready
  2. command_controller   📋 ready
  3. health_monitor       📋 ready
  4. 🔄 Implement ALL

User: 4 (Implement ALL)
→ Implements gps_tracker → ✓
→ Implements command_controller → ✓
→ Implements health_monitor → ✓
→ All 3 processes built and tested.

  [Level 1 — auto-return]
  1. 🛠 Design Mode
  2. 🚀 Implement       (nothing pending)
  3. ✅ Done             [recommended]
```

## Return to Design After Implementation

After implementing processes, the user can always go back to design mode to add I/O, modify types, or add entirely new processes:

```
/rti_dev

State: ✓ gps_tracker implemented
       ✓ command_controller implemented

User: 1 (Design Mode)

  [Level 2a — Process Picker]
  1. gps_tracker          ✓ implemented    — modify design
  2. command_controller   ✓ implemented    — modify design
  3. ➕ Add New Process

User: 1 (gps_tracker)

  [Modify sub-menu]
  What to change?
    1. Add an Input
    2. Add an Output         ← user picks this
    3. Modify an I/O
    4. Modify Process Settings
    5. Modify Tests
    6. Review Full Design
    7. ← Back to Process List

User: 2 (Add an Output)
→ Adds HealthStatus output (new type, Status pattern, 1Hz)
→ Proposes test_health_status_publish
→ Review updated design
    User: "← Back to Process List"

  [Level 2a — Process Picker (refreshed)]
  1. gps_tracker          ⚠ design modified  — needs re-implementation
  2. command_controller   ✓ implemented
  3. ➕ Add New Process

User: 3 (➕ Add New)
→ Plans dashboard_reader (Step 1–4)
    - Subscribes to PositionTopic, HealthStatusTopic (reuses existing types)
    - No outputs (read-only process)
→ Step 4: "Save and Exit"

  [Level 1 — auto-return]
  1. 🛠 Design Mode
  2. 🚀 Implement          ← 2 processes need implementation
  3. ✅ Done

User: 2 (Implement)

  [Level 2b — Implement Picker]
  1. gps_tracker       ⚠ design modified — re-implement
  2. dashboard_reader  📋 designed — first build
  3. 🔄 Implement ALL

User: 3 (Implement ALL)
→ Re-implements gps_tracker (adds new writer, new test)
→ Implements dashboard_reader (new scaffold, reuses types)
→ Builds, runs all tests
→ All pass. ✓
```

## Modifying via Direct Command

The user can also skip the menus with a direct request:

```
/rti_dev modify gps_tracker — add a HealthStatus output at 1Hz

→ Agent loads planning/processes/gps_tracker.yaml
→ Jumps straight to Step 2 (I/O):
   - Defines new type: HealthStatus { @key device_id, cpu_percent, memory_mb, uptime_s }
   - Pattern: Status, option 1
   - Rate: 1Hz
→ Step 3: Agent proposes new test: test_health_status_publish
→ Step 4: Review updated design

  What would you like to do?
    1. Implement Now
    2. Add More I/O
    3. ← Back to Process List

User: 1 (Implement Now)
→ Re-implements gps_tracker, rebuilds, re-runs all tests
→ All pass. ✓
```

## Fixing a Test Failure

```
/rti_dev

State: ✓ gps_tracker: implemented, tests pass
       ⚠ command_controller: implemented, 1 TEST FAILING
           test_command_priority: FAILED (ownership strength mismatch)

  [Level 1]
  1. 🛠 Design Mode
  2. 🚀 Implement
  3. ✅ Done

User: 1 (Design Mode)

  [Level 2a — Process Picker]
  1. gps_tracker          ✓ implemented
  2. command_controller   ⚠ 1 test failing    [recommended — needs fix]
  3. ➕ Add New Process

User: 2 (command_controller)

  [Modify sub-menu]
  ⚠ Test failure: test_command_priority
    "Expected manual_writer (strength 30) to override auto_writer
     (strength 10), but received auto_writer sample.
     Likely cause: ownership strength not set in QoS XML."

  What to change?
    1. Fix QoS / Pattern    — adjust ownership strength  [recommended]
    2. Add an Input
    3. Add an Output
    4. Modify Tests
    5. Review Full Design
    6. ← Back to Process List

User: 1 (Fix QoS)
→ Agent shows current Command I/O with pattern_option
→ User adjusts ownership strength config
→ Review updated design
    User: "Implement Now"

→ Re-implements command_controller, rebuilds, re-runs tests
→ All pass. ✓

  [Level 1 — auto-return]
  1. 🛠 Design Mode
  2. 🚀 Implement       (nothing pending)
  3. ✅ Done             [recommended]
```
