# Phase 1: System Design

System-level decisions that apply to all processes. These are **modifiable** — changes increment the version and trigger a sweep of existing processes.

This runs after Phase 0 completes (first invocation) or when the user selects "System Design" from the main menu.

```
/rti_dev — System Design

  Project: Wrapper Class, Modern C++ (CMake) [locked]

  1. Default Domain ID? (0-232)
     Default: 0

  2. System Patterns — What architectural behaviors does this system need?

     Select all that apply:
     [ ] Failover              — hot/cold standby with automatic switchover
     [ ] Health Monitoring     — heartbeat publishing + liveliness detection
     [ ] Leader Election       — dynamic primary selection among peers
     [ ] Request-Reply         — synchronous request/response pairs
     [ ] Redundant Publisher   — multiple writers, reader picks best

     Default: none

  For each selected pattern, choose the approach:
  (see System Patterns Catalog for options per pattern)
```

This creates/updates `planning/system_config.yaml`:

```yaml
# planning/system_config.yaml
# System-wide DDS configuration — applies to ALL processes.
# Framework and API are in project.yaml (locked).
# This file is versioned — changes trigger a sweep of existing processes.

system:
  version: 1                     # incremented on every change
  domain_id: 0                   # default domain for all processes
  participant_profile: "DPLibrary::DefaultParticipant"

  system_patterns:                # architectural behaviors for this system
    - pattern: failover
      option: hot_standby         # hot_standby | cold_standby | active_active
    - pattern: health_monitoring
      option: app_heartbeat       # dds_liveliness | app_heartbeat | watchdog_restart

  created: "2026-03-17T10:05:00Z"
  last_modified: "2026-03-17T10:05:00Z"
```

**Key behaviors:**

- **First invocation**: Phase 1 runs immediately after Phase 0. The user must complete it before proceeding.
- **Subsequent invocations**: System config is loaded silently. The main menu shows "System: Wrapper Class, Modern C++ | Failover (Hot Standby), Health Monitoring | domain 0" in the state summary.
- **Changing later**: `/rti_dev system design` or "System Design" from menu re-opens this phase. The version is incremented and a sweep runs (see below).

## System Config Versioning

Every change to `system_config.yaml` increments `version`. Each process design tracks which version it was designed against:

```yaml
# In planning/processes/gps_tracker.yaml
process:
  name: gps_tracker
  system_config_version: 1        # designed against system config v1
```

**When the agent detects a version mismatch** (`process.system_config_version < system.version`):

```
⚠ System config has changed since gps_tracker was designed (v1 → v2).

Changes:
  + Added system pattern: Health Monitoring (Application Heartbeat)

Should gps_tracker participate in Health Monitoring?
  [ ] Yes — publish HealthStatus from this node
  [ ] No — not applicable to this process

This will add health_output I/O to the design.
[Apply / Skip / Review all processes]
```

**Three scenarios when modifying System Design:**

| Change | Impact | Agent behavior |
|--------|--------|---------------|
| **Add** new pattern | Non-breaking | Offer opt-in to all existing processes. Re-run Phase 2 to generate new system IDL/QoS. |
| **Change** approach (e.g., Hot→Cold standby) | Breaking for participants | Warning: "3 processes use Failover. Changing approach requires re-implementing them." List affected processes. |
| **Remove** pattern | Breaking for participants | Warning: "2 processes use Health Monitoring. Removing will delete health I/O from their designs." Require confirmation. |
