# DDS Process Builder — Architecture

Five-phase system for designing and building RTI Connext DDS applications: **Init → Design System → Build Baseline → Design Process → Build Process.** Invoked as `/rti_dev` in VS Code Copilot Chat.


## High-Level Overview

The DDS Process Builder is a guided, agent-driven workflow for designing and implementing RTI Connext DDS applications. It runs as `/rti_dev` inside VS Code Copilot Chat and walks the user through every decision — from selecting a framework to publishing data on the wire.

### What it does

A user describes what their DDS processes should do in plain English. The workflow translates that into concrete artifacts: IDL type definitions, QoS XML profiles, application source code (C++, Python, Java, or C), build files, and integration tests. Every generated artifact traces back to a design decision stored in YAML.

### How it works

The workflow is split into **five phases** that execute in order. The first three run once to establish a project foundation; the last two repeat for each DDS process the user wants to build.

1. **Project Initialization** — The user picks a framework (Wrapper Class or XML App Creation) and an API language. These choices are **permanent** — they determine the scaffold templates, code generator flags, and build system used for every process in the project.

2. **System Design** — The user sets a domain ID and selects system-level architectural patterns (failover, health monitoring, leader election, etc.) along with their implementation approach. These choices are **versioned** — changing them later triggers a reconciliation sweep across all existing process designs.

3. **System Implementation** — Scripts automatically create the baseline: directory structure, system-level IDL (e.g., heartbeat types), QoS profiles for system patterns, and the top-level build file. No user interaction required.

4. **Process Design** — An interactive loop where the user names a process, selects transports, opts into system patterns, defines inputs/outputs (each with a topic, data type, data pattern, and QoS profile), and specifies tests. Data types are written directly to `.idl` files during this phase. The result is a `PROCESS_DESIGN.yaml` — a complete, machine-readable specification.

5. **Process Implementation** — Fully automated. The agent reads the design YAML and runs a sequence of scripts: scaffold the app directory, run `rtiddsgen` on the IDL files, assemble QoS XML, generate application code (the only AI-driven step), generate tests, build, and run tests. If tests fail, the user returns to design to fix.

### Key mechanics

- **Three decision scopes**: Project-level decisions are locked. System-level decisions are versioned and trigger sweeps. Process-level decisions are freely editable per process.
- **IDL-first type design**: Types are defined as actual IDL and written to `.idl` files during design — not embedded in YAML. During implementation, `rtiddsgen` generates code directly from these files.
- **Scripts for determinism**: Six shell scripts handle all mechanical steps (scaffold, rtiddsgen, QoS assembly, test generation, build, test execution). They are idempotent and produce identical output for identical input.
- **Sub-prompts for expertise**: Four specialized prompt files handle type definition, pattern/QoS selection, code generation, and test generation. Each is loaded on demand by the orchestrator.
- **MCP for knowledge**: Three MCP servers provide RTI documentation, starter kit examples, and community type libraries. Sub-prompts query these before making recommendations.
- **Design ↔ Implementation loop**: The user can design one process and implement it immediately, batch-design several and implement all at once, or iterate between design and implementation until tests pass.

---


## Table of Contents

- [Overview](#overview)
- [Rules](#rules)
- [The Five Phases](#the-five-phases)
- [Phase 0: Project Initialization](#phase-0-project-initialization)
- [Phase 1: System Design](#phase-1-system-design)
- [Phase 2: System Implementation](#phase-2-system-implementation)
- [/rti_dev Prompt](#rti_dev-prompt)
- [Phase 3: Process Design](#phase-3-process-design)
  - [Planning Loop](#planning-loop)
  - [Step 1: Process Identity](#step-1-process-identity)
  - [Step 2: Inputs & Outputs](#step-2-inputs--outputs)
  - [Step 3: Tests](#step-3-tests)
  - [Step 4: Review](#step-4-review)
- [PROCESS_DESIGN.yaml](#process_designyaml)
- [Phase 4: Process Implementation](#phase-4-process-implementation)
  - [Implementation Steps](#implementation-steps)
  - [Type Reuse Across Processes](#type-reuse-across-processes)
  - [Build & Test](#build--test)
- [System Patterns Catalog](#system-patterns-catalog)
- [Data Patterns Reference](#data-patterns-reference)
- [Decision Points](#decision-points)
- [Sub-Prompt Architecture](#sub-prompt-architecture)
- [Repository Structure](#repository-structure)
- [Iterative Workflow](#iterative-workflow)
- [Prompt File Reference](#prompt-file-reference)

---

## Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                            /rti_dev                                    │
│                                                                        │
│  PHASE 0: PROJECT INIT (one-time, irreversible)                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Framework: Wrapper Class / XML App Creation    🔒 LOCKED        │  │
│  │  API: Modern C++ / Python / Java / C / Both     🔒 LOCKED        │  │
│  │  → planning/project.yaml                                         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                         │
│                              ▼                                         │
│  PHASE 1: SYSTEM DESIGN (modifiable, versioned)                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Domain ID, System Patterns + approaches                         │  │
│  │  → planning/system_config.yaml (version: N)                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                         │
│                              ▼                                         │
│  PHASE 2: SYSTEM IMPLEMENTATION (baseline scaffold)                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  system_patterns.idl, SystemPatternsQoS.xml, dir structure       │  │
│  │  Top-level CMake/pip, rtiddsgen for system types                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                         │
│              ┌───────────────┴────────────────┐                        │
│              ▼                                ▼                        │
│  PHASE 3: PROCESS DESIGN         PHASE 4: PROCESS IMPLEMENTATION       │
│  ┌──────────────────────────┐    ┌──────────────────────────────┐      │
│  │ Name, transports         │    │ Write process IDL            │      │
│  │ Opt-in to system patterns│───►│ rtiddsgen process types      │      │
│  │ Define I/O + types       │    │ App code (main + logic)      │      │
│  │ Define tests             │    │ QoS assembly                 │      │
│  │ Review                   │    │ Tests, build, run            │      │
│  └──────────┬───────────────┘    └──────────────┬───────────────┘      │
│             │                                   │                      │
│             └── Plan another ───────────────────┘                      │
│                                                                        │
│  ◄── "Back to System Design" (version++, triggers sweep) ────────────► │
│  ◄── "Back to Project Init" → ⚠ "Requires full regeneration" ──────►   │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Five phases, three scopes:**

| Phase | Scope | Reversible? | Output |
|-------|-------|-------------|--------|
| **0. Project Init** | Framework + API | **No** — locked after scaffold | `planning/project.yaml` |
| **1. System Design** | Domain ID, system patterns + approaches | Yes — version-tracked | `planning/system_config.yaml` |
| **2. System Implementation** | Baseline IDL, QoS, directory scaffold | Re-runnable (idempotent) | `dds/`, top-level build files |
| **3. Process Design** | Per-process I/O, types, tests, pattern opt-in | Yes — per process | `planning/processes/<name>.yaml` |
| **4. Process Implementation** | Per-process code, build, test | Re-runnable | `apps/`, tests |

**Typical flows:**

- **Init → System Design → System Impl → Design one → Implement one → Design next → Implement next** (incremental)
- **Init → System Design → System Impl → Design several → Implement all** (batch design, then build)
- **Design one → Implement → modify design → re-implement** (iterate on one process)
- **Implement → test fails → return to design → fix → re-implement** (fix forward)
- **Back to System Design → add Health Monitoring → sweep existing processes** (evolve system)

**Phase 0** runs once and is locked. **Phase 1 + 2** establish the system baseline. **Phases 3 + 4** iterate per process.

**Process Design** is interactive — the user defines I/O one at a time, picks patterns and QoS, specifies tests, and can loop back. The output is a `PROCESS_DESIGN.yaml`.

**Process Implementation** is automated — `/rti_dev` reads the design and generates everything: IDL, QoS XML, app code, tests. Then builds and runs.

One `/rti_dev` prompt handles all phases. The user is never locked into a phase.

---

## Rules

All rules that govern the system. Sub-prompts, implementation scripts, and the orchestrator all follow these rules. This is the canonical reference — if a rule appears here but contradicts something elsewhere, this section wins.

A concise version of these rules is also loaded via `.github/copilot-instructions.md` on every invocation.

### IDL / Data Type Rules

| ID | Rule | Severity |
|----|------|----------|
| IDL-1 | Every struct MUST have at least one `@key` field (instance identity) | **MUST** |
| IDL-2 | All strings MUST be bounded: `string<N>` not `string` | **MUST** |
| IDL-3 | All sequences MUST be bounded: `sequence<T, N>` not `sequence<T>` | **MUST** |
| IDL-4 | Use enums for finite value sets (commands, states, modes) | SHOULD |
| IDL-5 | Use `@final` annotation for FlatData/zero-copy types ONLY | **MUST NOT** misuse |
| IDL-6 | Use `@nested` for types that are fields of other types, not standalone topics | SHOULD |
| IDL-7 | Types are written directly to `.idl` files during design (not embedded in YAML) | **MUST** |
| IDL-8 | Types already in workspace IDL are referenced, NOT re-declared | **MUST NOT** duplicate |

### Naming Conventions

| ID | Rule | Example |
|----|------|---------|
| NAME-1 | Module names = `snake_case` | `gps_types`, `system_patterns` |
| NAME-2 | Struct/enum names = `PascalCase` | `Position`, `CommandAction` |
| NAME-3 | Field names = `snake_case` | `device_id`, `cpu_percent` |
| NAME-4 | Process names = valid C identifier (no spaces, starts with letter) | `gps_tracker` |
| NAME-5 | Topic names = `PascalCase` + "Topic" suffix | `PositionTopic`, `CommandTopic` |
| NAME-6 | Unit test files = `test_<io_name>.py` | `test_position_publish.py` |
| NAME-7 | Integration test files = `test_<process_name>_e2e.py` | `test_gps_tracker_e2e.py` |

### Architecture Rules (Clean Separation)

| ID | Rule | Severity |
|----|------|----------|
| ARCH-1 | Every generated process MUST produce two layers: infrastructure (`main.cxx`) and business logic (`_logic.hpp`/`_logic.cxx`) | **MUST** |
| ARCH-2 | `main.cxx` is the ONLY file that includes DDS headers | **MUST** |
| ARCH-3 | Logic files include ONLY IDL-generated type headers and standard library | **MUST** |
| ARCH-4 | Logic layer must be directly unit-testable without DDS runtime | **MUST** |
| ARCH-5 | NEVER include DDS headers (`<dds/dds.hpp>`, `DDSReaderSetup.hpp`) in logic files | **NEVER** |
| ARCH-6 | NEVER pass DDS types (`LoanedSample<T>`) to business logic — extract `.data()` first | **NEVER** |
| ARCH-7 | NEVER put QoS, participant, or entity configuration in logic files | **NEVER** |
| ARCH-8 | NEVER put business rules (conditionals, state machines, processing) in `main.cxx` | **NEVER** |
| ARCH-9 | NEVER instantiate DDS entities inside callback handlers | **NEVER** |

### Workflow Rules

| ID | Rule | Severity |
|----|------|----------|
| WF-1 | Phase 0 (Project Init) MUST complete before any other phase | **MUST** |
| WF-2 | Framework and API are project-wide and locked — NEVER ask per process or per system design | **NEVER** |
| WF-3 | Transports are per-process — always ask in Step 1 | **MUST** |
| WF-4 | Type definition (Step 2b) is a mandatory gate — I/O CANNOT proceed until type is confirmed | **MUST** |
| WF-5 | The "Define New / Select Existing" choice MUST be presented for every I/O | **MUST** |
| WF-6 | Changing framework or API triggers destructive warning: "Requires full project regeneration" | **MUST** warn |
| WF-7 | User is NEVER locked into a phase — mode switching is always available | **NEVER** lock |
| WF-8 | After implementation (pass or fail), menu ALWAYS offers "Plan a New Process" and "Modify" | **ALWAYS** |
| WF-9 | System pattern I/O MUST be shown to user for review before confirming | **MUST** |
| WF-10 | All decisions MUST be recorded in the `decisions:` section of PROCESS_DESIGN.yaml | **MUST** |
| WF-11 | System pattern approach is system-wide — NEVER mix approaches across processes | **NEVER** |
| WF-12 | `system_config_version` mismatch triggers sweep — agent MUST offer opt-in for new patterns | **MUST** |
| WF-13 | System patterns are selected at system level (Phase 1), opted-in per process (Phase 3 Step 1d) | **MUST** |

### Schema Validation Rules

| ID | Field | Rule |
|----|-------|------|
| SCHEMA-1 | `process.name` | Required. Valid C identifier. |
| SCHEMA-2 | `process.transports` | Required. At least one of: SHMEM, UDP, TCP. |
| SCHEMA-3 | `inputs[]` or `outputs[]` | At least one I/O required. |
| SCHEMA-4 | `*.pattern` | Required. One of: `event`, `status`, `command`, `parameter`, `large_data`. |
| SCHEMA-5 | `*.qos_profile` | Required. Must resolve to a profile in generated QoS XML. |
| SCHEMA-6 | `idl_files` | Required if process introduces new types. List of `.idl` file paths created during design. |
| SCHEMA-7 | `tests.unit` | Required. At least one unit test per I/O. |
| SCHEMA-8 | `*.auto_generated_by` | Do not remove — tags system pattern I/O. |
| SCHEMA-9 | `process.system_config_version` | Required. Must match or be checked against current system config version. |
| SCHEMA-10 | `process.system_patterns[].role` | Required for opted-in patterns. Approach inherited from system config. |

### Implementation Rules

| ID | Rule | Severity |
|----|------|----------|
| IMPL-1 | Implementation is fully automatic — no user interaction after "Implement Now" | **MUST** |
| IMPL-2 | Scripts run in order (Steps 1→7), stopping on first non-zero exit code | **MUST** |
| IMPL-3 | Step 4 (app code generation) is the ONLY agent-driven step — all others are scripts | **MUST** |
| IMPL-4 | All scripts are idempotent — re-running skips existing files (use `--force` to overwrite) | **MUST** |
| IMPL-5 | `rtiddsgen` always uses `-replace` flag | **MUST** |
| IMPL-6 | `system_templates/` is read-only — NEVER modify template files | **NEVER** |

### Code Convention Rules

| ID | Rule |
|----|------|
| CODE-1 | Use `application.hpp` for signal handling and app config struct |
| CODE-2 | Process command-line args: `--domain`, `--qos-file`, `--verbose` |
| CODE-3 | Return codes: 0 = success, 1 = error |
| CODE-4 | Always call `participant.finalize()` before exit |
| CODE-5 | CMake minimum version: 3.11 |
| CODE-6 | Source files in CMakeLists.txt: `main.cxx`, `<process_name>_logic.cxx` |

### Test Rules

| ID | Rule |
|----|------|
| TEST-1 | Use isolated domain (`domain_id=100`) in test fixtures |
| TEST-2 | Timeout: 10s max per unit test |
| TEST-3 | Cleanup: dispose all DDS entities in fixture teardown |
| TEST-4 | Integration tests: wait 5s for discovery before asserting |
| TEST-5 | At least one integration (end-to-end) test per process (recommended) |

### MCP / Tool Usage Rules

| ID | Rule | Severity |
|----|------|----------|
| MCP-1 | Before defining any type: (1) query `github-types-repo`, (2) query `rti-docs-rag`, (3) scan workspace IDL, (4) scan other process YAMLs | **MUST** |
| MCP-2 | `/rti_dev` does NOT query MCP directly — loads the appropriate sub-prompt which contains MCP instructions | **MUST** |
| MCP-3 | The user NEVER needs to know sub-prompts exist — `/rti_dev` is the only visible prompt | **NEVER** expose |

### Auto-Resolve Rules (Pattern Selection)

| Trigger | Pattern | Option |
|---------|---------|--------|
| Type name contains "Button", "Alert", "Event" | Event | 1 (Standard) |
| Type name contains "Position", "State", "Health", "Telemetry" | Status | 1 (Standard) |
| Declared `rate_hz` in description | Status | Confirms periodic |
| Type name contains "Command" | Command | 1 (Single-source) |
| User mentions "priority" or "override" | Command | 2 (Multi-source) |
| Type name contains "Parameter", "Config", "Setting" | Parameter | 1 (Standard) |
| Type has `@final @language_binding(FLAT_DATA)` | Large Data | 2 (Zero-Copy) |
| Type has `sequence<octet>` with max > 65535 | Large Data | 1 (SHMEM) |
| User mentions "network" or "UDP" | Large Data | 3 (UDP) |

---

## Phase 0: Project Initialization

**One-time, irreversible.** These choices determine the entire project file structure, build system, code templates, and wrapper classes. Once scaffolded, changing them requires regenerating the entire project.

This runs on first `/rti_dev` invocation when no `planning/project.yaml` exists.

```
/rti_dev — Welcome! Let's initialize your DDS project.

⚠ These choices are PERMANENT. They determine the project's
  file structure, build system, and code templates. Changing
  later requires regenerating the entire project.

1. Framework — How should DDS endpoints be created?

    1. Wrapper Class     — entities created in code via DDSParticipantSetup,
       DDSReaderSetup<T>, DDSWriterSetup<T>. Full code control.
    2. XML App Creation  — entities defined in XML config files.
       App code is minimal — just callbacks.

    Default: 1 (Wrapper Class)

2. API — Which Connext API for application code?

    1. Modern C++ (C++11)     — CMake project, rtiddsgen -language C++11
    2. Python                 — pip/venv installer, rtiddsgen -language python
    3. Java                   — Maven/Gradle project, rtiddsgen -language java
    4. C                      — CMake project, rtiddsgen -language C
    5. Modern C++ + Python    — C++ primary + Python secondary (both build systems)

    Default: 1 (Modern C++)

Confirm? These cannot be changed without regenerating the project.
[Confirm / Change]
```

This creates `planning/project.yaml`:

```yaml
# planning/project.yaml
# LOCKED — changing requires full project regeneration.
# Created on first /rti_dev invocation.

project:
  framework: wrapper_class        # wrapper_class | xml_app_creation
  api: modern_cpp                 # modern_cpp | python | java | c | modern_cpp_python
  locked: true
  created: "2026-03-17T10:00:00Z"

  # Derived from api choice — read-only, not user-editable
  rtiddsgen_language: C++11       # rtiddsgen -language flag
  build_system: cmake             # cmake | pip | maven | cmake+pip
  test_framework: gtest           # gtest | pytest | junit
  app_dir: apps/cxx11             # where app code goes
```

**Derived fields by API:**

| API | `rtiddsgen_language` | `build_system` | `test_framework` | `app_dir` |
|-----|---------------------|----------------|-------------------|-----------|
| Modern C++ | `C++11` | `cmake` | `gtest` | `apps/cxx11` |
| Python | `python` | `pip` | `pytest` | `apps/python` |
| Java | `java` | `maven` | `junit` | `apps/java` |
| C | `C` | `cmake` | `gtest` | `apps/c` |
| Modern C++ + Python | `C++11` + `python` | `cmake+pip` | `gtest+pytest` | `apps/cxx11` + `apps/python` |

**Re-entry guard:**

If the user says `/rti_dev project init` after the project is already initialized:

```
⚠ Project is already initialized:
  Framework: Wrapper Class
  API: Modern C++ (CMake)

  These choices are LOCKED. Changing them requires:
  1. Deleting all generated code in apps/ and dds/
  2. Re-scaffolding all processes
  3. Re-implementing all process code

  Are you sure? [Yes, regenerate everything / Cancel]
```

---

## Phase 1: System Design

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

### System Config Versioning

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

---

## Phase 2: System Implementation

Generates the **system baseline** — shared artifacts that all processes build on. This runs after Phase 1 completes, or again whenever system config changes.

**Reads both config files:**
- `planning/project.yaml` → determines scaffold templates, build system, rtiddsgen flags
- `planning/system_config.yaml` → determines which system pattern IDL/QoS to generate

**What it generates:**

```
dds/
  datamodel/idl/
    system_patterns.idl           ← HeartbeatStatus, HealthStatus, LeaderBid, etc.
    Definitions.idl               ← System-level topic constants
  qos/
    DDS_QOS_PROFILES.xml          ← Base profiles
    SystemPatternsQoS.xml         ← HeartbeatQoS, HealthMonitorQoS, etc.
  utils/cxx11/                    ← Wrapper headers (if wrapper_class framework)
  build/
    cxx11_gen/                    ← rtiddsgen output for system-level types

apps/
  cxx11/                          ← Directory structure per API choice
    (empty — process apps go here later)

CMakeLists.txt                    ← Top-level build file (or pyproject.toml, pom.xml)
```

**Scripts called (in order):**

```bash
# Step 1: Scaffold directory structure + build system
scripts/scaffold.sh --project planning/project.yaml \
                     --system-config planning/system_config.yaml \
                     --system-only

# Step 2: Run rtiddsgen on system-level types
#   (system_patterns.idl was written by scaffold.sh in Step 1)
scripts/run_rtiddsgen.sh --project planning/project.yaml \
                          --idl-dir dds/datamodel/idl/ \
                          --idl-file system_patterns.idl

# Step 3: Generate system-level QoS XML
scripts/assemble_qos.sh --system \
                          --system-config planning/system_config.yaml \
                          --templates system_templates/qos_templates/ \
                          --output dds/qos/
```

**Key behaviors:**
- **Idempotent**: re-running skips existing files unless `--force` is used
- **Additive for new patterns**: adding a system pattern generates new IDL/QoS without disturbing existing files
- **Process-specific IDL is NOT generated here** — that happens in Phase 4
- The agent runs this automatically after Phase 1 — no user interaction needed

---

## The Five Phases

| Aspect | Phase 0: Project Init | Phase 1: System Design | Phase 2: System Impl | Phase 3: Process Design | Phase 4: Process Impl |
|--------|----------------------|----------------------|---------------------|------------------------|---------------------|
| **Scope** | Framework + API | Domain ID, system patterns | Baseline scaffold | Per-process I/O, types | Per-process code |
| **Mode** | Interactive (2 questions) | Interactive | Automated | Interactive | Automated |
| **Reversible** | **No** — locked | Yes — versioned | Re-runnable | Yes — per process | Re-runnable |
| **Output** | `project.yaml` | `system_config.yaml` | `dds/`, build files | `PROCESS_DESIGN.yaml` | `apps/`, tests |
| **Requires** | Nothing (fresh start) | `project.yaml` | Both config files | System baseline | Valid design YAML |

**Phase transitions:**

- Phase 0 → Phase 1 → Phase 2 are sequential on first invocation (then Phase 0 is locked)
- Phases 3 → 4 iterate per process (design one, implement one, repeat)
- "Back to System Design" → Phase 1 (version++, sweep existing processes, re-run Phase 2)
- "Back to Project Init" → Phase 0 (⚠ requires full project regeneration)

```
          ┌───────────────┐                     ┌─────────────────┐
          │               │  "Implement"        │                 │
  ┌──────►│ PHASE 3:      │────────────────────►│ PHASE 4:        │
  │       │ PROCESS DESIGN│                     │ PROCESS IMPL    │
  │       │               │◄────────────────────│                 │
  │       │ (per process  │ "Back to design"    │ (per process    │
  │       │  at a time)   │ build/test failure  │  at a time)     │
  │       └───────────────┘                     └────────┬────────┘
  │              │                                       │
  │              │ "Save and exit"                       │ ✓ All pass
  │              ▼                                       ▼
  │       planning/processes/<name>.yaml          Implemented + tested
  │                                                      │
  └──── "Plan new process" / "Modify <name>" ────────────┘
```

**Key point:** After Phase 4 completes (pass or fail), the menu always offers "Plan a New Process" and "Modify <existing>" alongside "Done." The user is never locked out of any phase.

---

## /rti_dev Prompt

`/rti_dev` is a VS Code custom prompt defined in `.github/prompts/rti_dev.prompt.md`. It is the single entry point for all DDS development.

### Invoking

```
/rti_dev                          → scans state, shows Level 1 menu
/rti_dev design                   → jumps straight to Level 2a (process picker)
/rti_dev design gps_tracker       → jumps to modify sub-menu for gps_tracker
/rti_dev new process              → jumps straight to Step 1 (new process)
/rti_dev add an input for GPS     → adds I/O to current/specified design
/rti_dev implement                → jumps to Level 2b (implement picker)
/rti_dev implement all            → implements all ready designs
/rti_dev show design              → prints current PROCESS_DESIGN.yaml
```

The user can jump to any level directly, or just type `/rti_dev` to get the guided interactive menu.

### What It Does on Every Invocation

```
1. Scan workspace:
   a. Check planning/project.yaml — project initialized?
   b. Check planning/system_config.yaml — system design done?
   c. Check planning/processes/*.yaml — any design files?
   d. Check apps/ — any implemented processes?
   e. Check dds/datamodel/idl/ — any existing types?
   f. Check tests/ — any test results?

2. If no project.yaml exists:
   → Run Phase 0 (Project Init) — ask framework + API.
   → Then run Phase 1 (System Design) — domain ID + system patterns.
   → Then run Phase 2 (System Implementation) — generate baseline.
   → Then show main menu.

3. If project.yaml exists but no system_config.yaml:
   → Run Phase 1 + Phase 2, then show menu.

4. Determine available actions:
   a. No designs exist → "Plan a New Process" [only option]
   b. Design exists, not implemented → "Continue Planning" or "Implement"
   c. Design exists, implemented → "Plan New Process", "Modify Design", "Re-implement"
   d. Test failures → "Fix Design" or "Re-implement"
   e. system_config_version mismatch → offer sweep

5. Present menu with state summary (including project + system config)

6. Execute selected action
```

### Interactive Menu

The menu uses a **two-level interaction**. First, the agent shows the state summary and asks for a top-level action. Then, if the user picks "Design Mode", the agent shows a process picker list.

#### Level 1: Top-Level Action

Always presented first. Options adapt to state:

```
/rti_dev — DDS Process Builder

Project: Wrapper Class | Modern C++ (CMake) [locked]
System: Failover (Hot Standby), Health Monitoring | domain 0 | v2

Current State:
  ✓ gps_tracker: implemented, tests pass
  📋 command_controller: designed, NOT yet implemented
  ⚠ health_monitor: implemented, 1 test failing

What would you like to do?

  1. 🛠 Design Mode       — create or modify a process design
  2. 🚀 Implement          — build from designs
  3. 🏗️  System Design      — modify system patterns, domain ID
  4. ✅ Done
```

If there are no designs yet, only "Design Mode" is shown (Implement is grayed out). If all designs are already implemented with passing tests, "Done" is recommended.

"System Design" re-enters Phase 1. If system patterns change, the version increments and a sweep runs across all existing process designs.

Note: Project Init (framework/API) is not shown in the menu — it's locked. The user can force re-init with `/rti_dev project init` (with a destructive warning).

#### Level 2a: Design Mode → Process Picker

When the user selects "Design Mode", the agent shows **a numbered list of existing processes plus "Add New"**:

```
Design Mode — which process?

  Existing processes:
    1. gps_tracker          ✓ implemented     — modify design → re-implement
    2. command_controller   📋 designed        — continue editing design
    3. health_monitor       ⚠ test failing    — fix design

  Or:
    4. ➕ Add New Process    — start a fresh design

  Select a number:
```

The user picks a number. For existing processes, the agent loads the YAML and enters planning at the relevant step. For "Add New", it starts Step 1.

**After selecting an existing process, the agent shows what can be changed:**

```
Modifying: command_controller

  Current design:
    Framework: Wrapper Class (C++11)
    Inputs:  command_input → CommandTopic [Command, EventQoS]
    Outputs: (none)
    Tests:   1 unit, 1 integration

  What would you like to change?

    1. Add an Input           — subscribe to another topic
    2. Add an Output          — publish to another topic
    3. Modify an I/O          — change pattern, QoS, type
    4. Opt-in System Pattern  — opt-in to system-level patterns (from system config)
    5. Modify Process Settings — transports, domain
    6. Modify Tests           — add/remove/change tests
    7. Review Full Design     — see everything, then implement
    8. ← Back to Process List
```

#### Level 2b: Implement → Process Picker

When the user selects "Implement", the agent shows which processes are ready:

```
Implement — which process?

  Ready to implement:
    1. command_controller    📋 designed, not yet implemented

  Ready to re-implement (design modified):
    2. health_monitor        ⚠ test failing — design was updated

  Already up-to-date (no changes needed):
    • gps_tracker            ✓ tests pass

  Or:
    3. 🔄 Implement ALL ready — build 1 + 2 sequentially

  Select a number:
```

#### Full Interaction Flow Example

```
User: /rti_dev

  [Level 1]
  Agent shows state + top-level menu
  User: "1" (Design Mode)

  [Level 2a — Process Picker]
  Agent: "Which process? 1. gps_tracker  2. command_controller  3. ➕ Add New"
  User: "3" (Add New)

  [Planning Phase — Step 1→2→3→4]
  Agent walks through planning steps...
  Step 4 review:
    User: "Save and go back"

  [Level 2a — Process Picker (refreshed)]
  Agent: "Which process? 1. gps_tracker  2. command_controller  3. sensor_reader (new)  4. ➕ Add New"
  User: "2" (command_controller)

  [Modify sub-menu]
  Agent: "What to change? 1. Add Input  2. Add Output  ..."
  User: "1" (Add Input)
  ... adds input, reviews ...
  User: "← Back to Process List"

  [Level 2a — Process Picker]
  User: "← Back" (returns to Level 1)

  [Level 1]
  User: "2" (Implement)

  [Level 2b — Implement Picker]
  Agent: "1. command_controller  2. sensor_reader  3. Implement ALL"
  User: "3" (Implement ALL)

  [Implementation runs for both...]
  Agent: "✓ command_controller built + tests pass"
  Agent: "✓ sensor_reader built + tests pass"

  [Level 1 — auto-return]
  Agent shows updated state, user picks next action or Done.
```

---

## Phase 3: Process Design

### Planning Loop

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

### Step 1: Process Identity

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

When the user opts in to a system pattern, the agent **auto-generates the required I/O, types, and application logic** for that pattern using the approach from system config. The user then reviews and can modify. See [System Patterns Catalog](#system-patterns-catalog) for what each pattern adds.

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

### Step 2: Inputs & Outputs

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

#### Per-I/O sub-loop

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

### Step 3: Tests

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

### Step 4: Review

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

---

## Phase 4: Process Implementation

When the user selects "Implement Now", the agent reads `PROCESS_DESIGN.yaml` and executes these steps **automatically** with no user interaction required.

### Implementation Steps

Each step is backed by an **executable script** in `scripts/`. The agent calls scripts with arguments derived from the design YAML, project config, and system config — no interpretation needed for the mechanical parts.

```
Script inventory (scripts/):
  scaffold.sh          — copy template files, generate build system
  run_rtiddsgen.sh     — run rtiddsgen with correct API flags
  assemble_qos.sh      — merge QoS XML fragments for referenced profiles
  generate_tests.sh    — scaffold test files from design YAML
  build.sh             — cmake/pip/maven build
  run_tests.sh         — run tests, report results
```

```
Step 1: SCAFFOLD PROJECT
  Script: scripts/scaffold.sh \
            --project planning/project.yaml \
            --process <process_name> \
            --system-config planning/system_config.yaml

  What it does:
    - Reads project.yaml for api, framework
    - Copies system_templates/<framework>/scaffold/ → apps/<api_dir>/<process_name>/
    - Generates build file from template:
        modern_cpp / c  → CMakeLists.txt (links rtiddsgen output, QoS path, wrapper headers)
        python          → requirements.txt + pyproject.toml
        java            → pom.xml with RTI Connext dependency
        modern_cpp_python → both CMakeLists.txt and pyproject.toml
    - If wrapper_class: copies wrapper headers → dds/utils/cxx11/ (idempotent)
    - Idempotent: skips if scaffold already exists (use --force to overwrite)

  Exit codes: 0 = success, 1 = missing template, 2 = invalid api/framework

Step 2: RUN RTIDDSGEN
  Script: scripts/run_rtiddsgen.sh \
            --project planning/project.yaml \
            --idl-dir dds/datamodel/idl/ \
            [--idl-file <specific_module>.idl]

  What it does:
    - IDL files already exist (written during Phase 3 design)
    - Reads project.yaml for api → maps to rtiddsgen -language flag:
        modern_cpp       → -language C++11  → dds/build/cxx11_gen/
        python           → -language python → dds/build/python_gen/
        java             → -language java   → dds/build/java_gen/
        c                → -language C      → dds/build/c_gen/
        modern_cpp_python → runs BOTH C++11 and python
    - If --idl-file given: runs on that file only
    - If not: runs on all .idl files in --idl-dir
    - Uses -replace flag (always overwrites generated code)
    - Validates: rtiddsgen exit code == 0

  Exit codes: 0 = success, 1 = rtiddsgen not found, 2 = generation failed

Step 3: ASSEMBLE QoS XML
  Script: scripts/assemble_qos.sh \
            --design planning/processes/<process_name>.yaml \
            --templates system_templates/qos_templates/ \
            --output dds/qos/DDS_QOS_PROFILES.xml

  What it does:
    - Reads all qos_profile references from inputs[] and outputs[]
    - For each unique profile: copies the matching XML fragment from qos_templates/
    - Merges fragments into a single DDS_QOS_PROFILES.xml
    - If output file already exists: merges new profiles (no duplicates)
    - Sets transport configs based on process.transports

  Exit codes: 0 = success, 1 = missing template, 2 = merge conflict

Step 4: GENERATE APPLICATION CODE
  (Agent-driven — uses builder.prompt.md sub-prompt)
  This step is NOT fully scripted because app logic varies per process.
  The agent reads the design YAML and generates code using blueprints/ as reference.
  See builder.prompt.md for the generation rules.

  Output files (clean architecture separation):
    main.cxx                     — DDS infrastructure only (participant, readers, writers)
    <process_name>_logic.hpp     — Business logic declarations (no DDS includes)
    <process_name>_logic.cxx     — Business logic implementation (callback handlers, processing)

  Rule: main.cxx is the ONLY file that includes DDS headers.
  Logic files include only IDL-generated type headers and standard library.

Step 5: GENERATE TESTS
  Script: scripts/generate_tests.sh \
            --design planning/processes/<process_name>.yaml \
            --system-config planning/system_config.yaml \
            --output-dir tests/

  What it does:
    - Reads tests.unit[] and tests.integration[] from design YAML
    - Generates conftest.py (if not exists): fixtures, domain isolation, cleanup
    - For each unit test: generates test_<name>.py from test templates
    - For each integration test: generates test_<name>.py with process launcher
    - Idempotent: skips existing test files (use --force to overwrite)

  Exit codes: 0 = success, 1 = no tests defined, 2 = template error

Step 6: BUILD
  Script: scripts/build.sh \
            --project planning/project.yaml \
            --process <process_name>

  What it does:
    - modern_cpp / c:
        mkdir -p build && cd build && cmake .. && cmake --build .
    - python:
        pip install -e apps/python/<process_name>/
    - java:
        cd apps/java/<process_name> && mvn compile
    - Validates: exit code == 0, no compile errors

  Exit codes: 0 = success, 1 = build failed

Step 7: RUN TESTS
  Script: scripts/run_tests.sh \
            --process <process_name> \
            --test-dir tests/

  What it does:
    - python -m pytest test_<process_name>*.py -v --tb=short
    - Captures output to tests/test_results/<process_name>_results.xml (JUnit format)
    - Reports: pass/fail per test, with failure details

  Exit codes: 0 = all pass, 1 = failures, 2 = errors
```

### Agent's Role During Implementation

The agent's job is to:
1. Parse the design YAML to extract script arguments
2. Call scripts in order (Steps 1→7), stopping on failure
3. **Step 4 is the only agent-driven step** — app code generation requires
   understanding the I/O logic, callbacks, and patterns. The agent uses
   `builder.prompt.md` + blueprints as reference.
4. Report results back to the user after each step

### Implementation Output

After implementation, these files exist:

```
For process "gps_tracker" with Wrapper Class framework:

  dds/
  ├── datamodel/idl/
  │   ├── gps_types.idl            # Created during design (Phase 3 Step 2b)
  │   └── Definitions.idl           # Topic constants, updated during design
  ├── qos/
  │   └── DDS_QOS_PROFILES.xml      # EventQoS + StatusQoS profiles
  ├── utils/cxx11/
  │   ├── DDSParticipantSetup.hpp
  │   ├── DDSReaderSetup.hpp
  │   └── DDSWriterSetup.hpp
  └── build/
      └── cxx11_gen/                # rtiddsgen output

  apps/cxx11/gps_tracker/
  ├── CMakeLists.txt
  ├── application.hpp
  ├── main.cxx                     # DDS infrastructure: participant, readers, writers
  ├── gps_tracker_logic.hpp        # Business logic: pure functions, no DDS includes
  ├── gps_tracker_logic.cxx        # Business logic: callback handlers, processing
  ├── run.sh
  └── README.md

  tests/
  ├── conftest.py
  ├── test_position_publish.py
  ├── test_command_receive.py
  └── test_gps_tracker_e2e.py
```

### Type Reuse Across Processes

When the user designs a second process that uses types from the first:

```
Planning process: command_controller

  Define an output:
    Topic: CommandTopic
    Type: ?

  Type "Command" already exists (defined by gps_tracker):
    struct Command {
      @key string<64> device_id;
      CommandAction action;
      float value;
    };

  Reuse this type? [Yes / Define new]
  → User selects: Yes

  Result: command_controller.yaml lists dds/datamodel/idl/gps_types.idl
          in its idl_files (same file, no duplication).
          No new IDL is written — the type already exists on disk.
```

**How it works technically**:
- During design (Phase 3 Step 2b), the agent writes `.idl` files directly to `dds/datamodel/idl/`
- Each `PROCESS_DESIGN.yaml` lists `idl_files:` referencing the paths it depends on
- Reused types already exist as `.idl` files — the design just adds the file path to `idl_files:`
- The planning agent scans existing `.idl` files + other design files to offer reuse
- No extraction step is needed during implementation — IDL files are the source of truth

### Build & Test

**Build** uses the project's existing CMake structure:
```bash
# From workspace root
mkdir -p build && cd build
cmake ..
cmake --build .
```

The top-level `CMakeLists.txt` discovers all apps via `add_subdirectory()`. Each implemented process gets added automatically.

**Tests** use pytest with generated Python type support:
```bash
# Run all tests
cd tests && python -m pytest -v

# Run tests for one process
python -m pytest test_gps_tracker*.py -v

# Run only unit tests
python -m pytest -k "not e2e" -v
```

**When tests fail**, the agent reports the failure and recommends returning to planning:
```
Test Results:
  ✓ test_position_publish     PASSED
  ✗ test_command_receive       FAILED
    AssertionError: No data received within 5s timeout
    Likely cause: QoS mismatch or callback not wired

  ✓ test_gps_tracker_e2e      PASSED

  1 failure. Recommended: review command_input QoS settings.
  Return to planning to fix? [Yes / No]
```

---

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

---

## Decision Points

All decisions during planning, listed with auto-resolve rules:

**Project-level decisions** (one-time, locked, stored in `project.yaml`):

| ID | Phase | Prompt | Options | Default | Auto-Resolve | Reversible? |
|----|-------|--------|---------|---------|-------------|-------------|
| `project.framework` | 0 | How to create DDS endpoints? | Wrapper Class / XML App | Wrapper Class | User says "XML" → XML; "wrapper" or "code" → Wrapper | **No** |
| `project.api` | 0 | Which Connext API? | Modern C++ / Python / Java / C / Both | Modern C++ | User says "python" → Python; "java" → Java | **No** |

**System-level decisions** (modifiable, versioned, stored in `system_config.yaml`):

| ID | Phase | Prompt | Options | Default | Auto-Resolve |
|----|-------|--------|---------|---------|-------------|
| `system.domain_id` | 1 | Default domain ID? | 0-232 | 0 | — |
| `system.system_pattern` | 1 | System-level behaviors? | None / Failover / Health / Leader / ReqReply / Redundant | None | User mentions "failover", "standby" → Failover |
| `system.system_pattern_option` | 1 | Which approach per pattern? | Varies per pattern | Option 1 | — (always ask, multiple valid approaches) |

**Process-level decisions** (per process, stored in `PROCESS_DESIGN.yaml`):

| ID | Step | Prompt | Options | Default | Auto-Resolve |
|----|------|--------|---------|---------|-------------|
| `plan.domain_id` | 1b | Override domain ID? | null (inherit) / 0-232 | null | — (inherit unless specified) |
| `plan.transports` | 1c | Which transports? | SHMEM+UDP / SHMEM / UDP / TCP / Custom | SHMEM+UDP | User says "network" or "remote" → UDP; "same host" → SHMEM |
| `plan.system_pattern_optin` | 1d | Participate in system pattern? | Yes / No per pattern | No | — (always ask for each available pattern) |
| `plan.system_pattern_role` | 1d | What role for this process? | Varies per pattern (PRIMARY/STANDBY, publisher/monitor) | — | — (always ask) |
| `plan.system_pattern_io` | 1d | Accept auto-generated I/O? | Accept / Modify / Remove | Accept | — (always show for review) |
| `plan.pattern.<topic>` | 2 | Pattern for topic? | Event/Status/Command/Parameter/LargeData | Inferred from type | See auto-resolve per pattern |
| `plan.pattern_option.<topic>` | 2 | Which option within pattern? | Varies per pattern | Option 1 | See auto-resolve per pattern |
| `plan.tests` | 3 | Accept proposed tests? | Accept / Add / Remove / Modify | Accept | — (always ask) |

**Decision persistence**: All decisions are recorded in the `decisions:` section of `PROCESS_DESIGN.yaml`. If the user re-enters planning for the same process, prior decisions are loaded and shown as defaults.

---

## Repository Structure

This section defines the **template repo** — the workflow infrastructure artifacts that ship in the repository. Everything listed here is checked in and maintained as reusable tooling. Generated output (planning configs, application code, IDL, tests, build artifacts) is produced by executing the workflow and is NOT part of the template.

### Prompt Infrastructure

```
.github/
├── copilot-instructions.md               # Workspace-level rules, points to /rti_dev
└── prompts/
    ├── rti_dev.prompt.md                 # /rti_dev — orchestrator prompt definition
    ├── build_cxx.prompt.md               # Sub-prompt: C++ build rules
    ├── datamodel.prompt.md               # Sub-prompt: type definitions, IDL design
    ├── patterns.prompt.md                # Sub-prompt: data pattern + QoS selection
    ├── builder.prompt.md                 # Sub-prompt: code gen, scaffold, CMake
    └── tester.prompt.md                  # Sub-prompt: test gen, pytest
```

### MCP Configuration

```
mcp.json                                  # MCP server endpoints (rti-docs-rag,
                                           #   github-starter-kit, github-types-repo)
```

### Implementation Scripts

```
scripts/
├── scaffold.sh                           # Phase 4 Step 1: copy templates, gen build files
├── run_rtiddsgen.sh                      # Phase 4 Step 2: rtiddsgen with API-correct flags
├── assemble_qos.sh                       # Phase 4 Step 3: merge QoS XML fragments
├── generate_tests.sh                     # Phase 4 Step 5: scaffold test files
├── build.sh                              # Phase 4 Step 6: cmake / pip / maven build
└── run_tests.sh                          # Phase 4 Step 7: run tests, report results
```

### System Templates (read-only scaffolds)

```
system_templates/
├── wrapper_class/                        # Framework: Wrapper Class
│   ├── scaffold/                         #   Starter files copied into apps/<api>/<process>/
│   │   ├── CMakeLists.txt
│   │   ├── application.hpp
│   │   ├── app_main.cxx
│   │   └── run.sh
│   └── wrapper_headers/                  #   Reusable DDS wrapper headers → dds/utils/
│       ├── DDSParticipantSetup.hpp
│       ├── DDSReaderSetup.hpp
│       ├── DDSWriterSetup.hpp
│       └── DDSParameter*.hpp
│
├── xml_app_creation/                     # Framework: XML App Creation
│   ├── scaffold/                         #   Starter files copied into apps/<api>/<process>/
│   │   ├── CMakeLists.txt
│   │   ├── APP_CONFIG.xml
│   │   ├── USER_QOS_PROFILES.xml
│   │   ├── app_main.cxx
│   │   ├── callbacks.hpp
│   │   └── callbacks.cxx
│   └── examples/                         #   Reference examples
│
├── python/                               # Framework: Python scaffold
│   └── scaffold/
│
├── qos_templates/                        # Per-pattern QoS XML fragments
│   ├── event_qos.xml
│   ├── status_qos.xml
│   ├── command_qos.xml
│   ├── parameter_qos.xml
│   ├── large_data_shmem_qos.xml
│   └── assigner_qos.xml
│
└── blueprints/                           # Code templates per data pattern × API
    ├── event/cxx11/
    ├── status/cxx11/
    ├── command/cxx11/
    ├── parameter/cxx11/
    └── large_data/cxx11/
```

### Architecture Document

```
DDS_PROCESS_BUILDER.md                    # This file — canonical workflow reference
```

### What Gets Generated (NOT part of the template)

When a user executes the workflow, the following directories are created as output:

| Directory | Created By | Contents |
|---|---|---|
| `planning/` | Phases 0–3 | `project.yaml`, `system_config.yaml`, `processes/*.yaml` |
| `dds/datamodel/idl/` | Phase 2 + 3 | System IDL (Phase 2), per-process IDL (Phase 3 design) |
| `dds/qos/` | Phase 4 Step 3 | Assembled `DDS_QOS_PROFILES.xml` |
| `dds/utils/` | Phase 4 Step 1 | Copied wrapper headers (Wrapper Class framework) |
| `dds/build/` | Phase 4 Step 2 | rtiddsgen output (`cxx11_gen/`, `python_gen/`) |
| `apps/<api>/` | Phase 4 Step 1 | Scaffolded process directories + generated code |
| `tests/` | Phase 4 Step 5 | Generated test files, conftest, helpers |
| `build/` | Phase 4 Step 6 | Build output (cmake, pip, maven) |
| `CMakeLists.txt` | Phase 4 Step 1 | Top-level build file |

These directories should be in `.gitignore` for the template repo, or committed separately when the template is instantiated into a project.

---

## Iterative Workflow

### Typical Session: First Process (Fresh Workspace)

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
  → scaffold.sh, run_rtiddsgen.sh --system, assemble_qos.sh --system
  → system_patterns.idl (written by scaffold.sh), SystemPatternsQoS.xml, directory structure created

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

### Adding a Second Process (Incremental)

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

### Design Multiple, Implement Later (Batch)

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

### Return to Design After Implementation

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

### Modifying via Direct Command

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

### Fixing a Test Failure

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

---

## Sub-Prompt Architecture

`/rti_dev` is the only agent the user talks to. But when the user's action requires specialized knowledge (type definitions, pattern/QoS selection, code generation, testing), `/rti_dev` loads a **sub-prompt prompt file** — a focused instruction set with specific MCP tool bindings.

### Why Sub-Prompts

| Without sub-prompts | With sub-prompts |
|-------------------|-----------------|
| One massive instruction file (~500 lines) | Orchestrator ~150 lines + 4 focused modules ~100 lines each |
| Agent may lose focus on IDL rules when generating code | Each module has only the rules it needs |
| All MCP tools listed generically | Each module knows exactly which MCP to query and when |
| Pattern selection mixed with type syntax | Separated: type syntax in one, pattern logic in another |

### The Sub-Prompts

```
/rti_dev (orchestrator)
  │
  ├── 📐 datamodel.prompt.md    — type definitions, IDL syntax, field annotations
  │     MCP: rti-docs-rag (IDL syntax), github-types-repo (reference types)
  │
  ├── 🔀 patterns.prompt.md     — pattern selection, QoS profiles, transport config
  │     MCP: rti-docs-rag (QoS docs), github-starter-kit (existing QoS XML)
  │
  ├── 🏗 builder.prompt.md      — code generation, scaffold, CMake, rtiddsgen
  │     MCP: github-starter-kit (reference apps, wrapper classes, examples)
  │
  └── 🧪 tester.prompt.md       — test generation, pytest, DDS test utilities
  │     MCP: github-starter-kit (existing test patterns)
  │
  └── 📚 DDS_PROCESS_BUILDER.md — full reference (this doc), loaded as context
```

### When Each Sub-Prompt Is Triggered

```
User invokes /rti_dev
  │
  ├─ Level 1 → Level 2a → "Add New Process"
  │   └─ Step 1 (Process Identity)     → /rti_dev handles directly (no sub-prompt)
  │   └─ Step 2 (Define I/O)
  │       ├─ Step 2b "Data type gate"   → loads datamodel.prompt.md (Define New)
  │       │                                or scans existing types (Select Existing)
  │       ├─ Step 2c "Pattern & QoS"    → loads patterns.prompt.md
  │       └─ "Set callbacks"            → /rti_dev handles directly
  │   └─ Step 3 (Tests)                → loads tester.prompt.md
  │   └─ Step 4 (Review)               → /rti_dev handles directly
  │
  ├─ Level 1 → Level 2b → "Implement"
  │   └─ Steps 1-3 (scaffold, IDL, rtiddsgen)  → loads builder.prompt.md
  │   └─ Step 4 (QoS XML)                      → loads patterns.prompt.md
  │   └─ Step 5 (app code)                     → loads builder.prompt.md
  │   └─ Steps 6-8 (tests, build, run)         → loads tester.prompt.md
  │
  ├─ Level 2a → Modify sub-menu
  │   └─ "Add Input/Output"            → datamodel + patterns sub-prompts
  │   └─ "Modify I/O"                  → patterns sub-prompt
  │   └─ "Modify Process Settings"      → /rti_dev handles directly
  │   └─ "Modify Tests"                → tester sub-prompt
```

### Sub-Prompt Files

Each sub-prompt is a `.github/prompts/*.prompt.md` file. The `/rti_dev` agent loads them contextually — the user never needs to know they exist.

#### `.github/prompts/datamodel.prompt.md`

```markdown
# Data Modeling Sub-Prompt

You are defining DDS data types in IDL. You are invoked as a **mandatory gate** for every I/O:
the user must either define a new type or select an existing one before the I/O can proceed.

## MCP Tools — Use These First

Before defining any type:
1. Query `github-types-repo` for existing types that match the user's description
2. Query `rti-docs-rag` for IDL syntax if using annotations or complex types
3. Scan `dds/datamodel/idl/*.idl` for types already defined in this workspace
4. Scan `planning/processes/*.yaml` for types defined by other processes

## Entry Gate — Present This Choice Every Time

```
Data type for "<TopicName>"?

  1. 🆕 Define New Type
  2. 📂 Select Existing Type
```

If no existing types match, skip directly to "Define New Type."

### Option 1 — Define New Type

Walk through the full type definition:
1. Type name (PascalCase)
2. Module/namespace (snake_case)
3. Fields one at a time — name, type, annotations
4. Supporting types first (enums, nested structs)
5. Show complete IDL preview with module wrapper
6. Ask: "[Confirm / Edit field / Add field]"

### Option 2 — Select Existing Type

Scan all sources (workspace IDL files, other process designs, session types).
Present a numbered list:

```
Available types:
  1. module::TypeName — field1, field2, ...  (used by: process_name)
  2. ...
Select [1-N]:
```

Show the full struct definition, then ask: "Use this type? [Yes / No, define new instead]"

## Type Definition Rules

- Every struct MUST have at least one `@key` field (instance identity)
- All strings MUST be bounded: `string<N>` not `string`
- All sequences MUST be bounded: `sequence<T, N>` not `sequence<T>`
- Use enums for finite value sets (commands, states, modes)
- Use `@final` annotation for FlatData/zero-copy types only
- Use `@nested` for types that are fields of other types, not standalone topics
- Module names = lowercase with underscores (e.g., `gps_types`)
- Struct names = PascalCase (e.g., `Position`, `CommandAction`)
- Field names = snake_case (e.g., `device_id`, `cpu_percent`)

## Field Type Quick Reference

| User Says | IDL Type | Notes |
|-----------|----------|-------|
| "string", "name", "id" | `string<64>` | Default bound 64, ask if larger needed |
| "number", "count", "integer" | `int32` | Use `uint32` if always positive |
| "decimal", "float", "temperature" | `float` | Use `double` for lat/lon precision |
| "true/false", "flag", "enabled" | `boolean` | |
| "timestamp", "time" | `uint64` | Epoch nanoseconds |
| "image", "payload", "binary" | `sequence<octet, N>` | Ask for max size |
| "list of X" | `sequence<X, N>` | Ask for max count |

## Walkthrough Format

For each type, present:
1. The proposed IDL definition in a code block (with module wrapper)
2. Which fields are `@key` and why
3. Whether it's a new type or reuses an existing one
4. Ask: "Does this look right? [Confirm / Edit / Add field]"

## On Completion

Return the following to /rti_dev:
- Complete type definition in **IDL syntax** (with module wrapper)
- Module name
- List of types defined (struct names, enum names)
- Which fields are `@key` and why
- Whether this is a new type or reuse of existing
- Source of reuse if applicable (which process/file)

/rti_dev then **writes the IDL directly to `dds/datamodel/idl/<module>.idl`**
during design (Phase 3 Step 2b). The PROCESS_DESIGN.yaml records a file
path reference in `idl_files:`, not the IDL content itself.
During implementation, `rtiddsgen` generates code from those `.idl` files
for the selected API (C++11, Python, etc.).
```

#### `.github/prompts/patterns.prompt.md`

```markdown
# Pattern & QoS Sub-Prompt

You are selecting data patterns and QoS profiles for DDS topics.

## MCP Tools — Use These First

1. Query `rti-docs-rag` for QoS policy documentation when user asks
   about reliability, durability, deadline, ownership, or transport
2. Query `github-starter-kit` for existing QoS XML profiles in the project
   (`dds/qos/DDS_QOS_PROFILES.xml`) to check what's already defined

## Pattern Catalog

Present the user with the matching pattern and its options.
Auto-resolve when possible (see auto-resolve rules below).

### Event (aperiodic, cannot be lost)
| Option | Reliability | History | Liveliness | Use When |
|--------|------------|---------|------------|----------|
| 1. Standard | RELIABLE | KEEP_ALL | AUTOMATIC 4s/10s | Alerts, button presses |
| 2. Command Override | RELIABLE+EXCLUSIVE | KEEP_ALL | AUTOMATIC | Multi-source arbitration |
| 3. Lightweight | RELIABLE | KEEP_LAST 1 | None | Frequent, only latest matters |

Auto-resolve: type name has "Button", "Alert", "Event" → Event.1

### Status (periodic telemetry)
| Option | Reliability | History | Deadline | Use When |
|--------|------------|---------|----------|----------|
| 1. Standard | BEST_EFFORT | KEEP_LAST 1 | 4s/10s | Position, health |
| 2. Downsampled | BEST_EFFORT | KEEP_LAST 1 | + TIME_BASED_FILTER | Reader at lower rate |
| 3. Reliable | RELIABLE | KEEP_LAST 1 | Deadline | Every update matters |

Auto-resolve: type name has "Position", "State", "Health" → Status.1
Rate declared → confirms periodic/status.

### Command (control messages)
| Option | Ownership | Strength | Use When |
|--------|-----------|----------|----------|
| 1. Single-source | SHARED | N/A | One commander |
| 2. Multi-source | EXCLUSIVE | 10/20/30 | Priority arbitration |

Auto-resolve: type name has "Command" → Command.1
User mentions "priority" or "override" → Command.2

### Parameter (runtime config)
| Option | Reliability | Durability | Use When |
|--------|------------|-----------|----------|
| 1. Standard | RELIABLE | TRANSIENT_LOCAL | Get/set config |
| 2. Persistent | RELIABLE | PERSISTENT | Survives restart |

Auto-resolve: type name has "Parameter", "Config", "Setting" → Parameter.1

### Large Data (>64KB)
| Option | Transport | Zero-Copy | Use When |
|--------|-----------|-----------|----------|
| 1. SHMEM | SHMEM only | No | Intra-host |
| 2. SHMEM ZC | SHMEM ref | Yes | Intra-host, zero copies |
| 3. UDP | UDP | No | Cross-host |

Auto-resolve: `@final @language_binding(FLAT_DATA)` → LargeData.2
`sequence<octet>` max>65535 → LargeData.1

## Presentation Format

1. State the auto-resolved pattern and option (if applicable)
2. Show the pattern table for the relevant pattern
3. Ask: "Use [auto-resolved option]? Or pick a different option."
4. Confirm the QoS profile name that maps to the selection

## On Completion

Return to /rti_dev:
- pattern: event|status|command|parameter|large_data
- pattern_option: 1|2|3
- qos_profile: "DataPatternsLibrary::XXX"
- callbacks: [list based on pattern]
- rate_hz: (if status pattern)
```

#### `.github/prompts/builder.prompt.md`

```markdown
# Builder Sub-Prompt

You generate DDS application code and project scaffolding.

## MCP Tools — Use These First

1. Query `github-starter-kit` for existing app implementations to use
   as reference (especially `apps/cxx11/example_io_app/`)
2. Check `dds/utils/cxx11/` for available wrapper class headers
3. Check `system_templates/` for scaffold files

## Clean Architecture: Separate DDS Infrastructure from Business Logic

Every generated process MUST produce **two layers**:

```
apps/<api_dir>/<process_name>/
  ├── main.cxx                     # DDS INFRASTRUCTURE: participant, readers, writers
  ├── <process_name>_logic.hpp     # BUSINESS LOGIC: pure functions, no DDS includes
  └── <process_name>_logic.cxx     # BUSINESS LOGIC: callback handlers, processing
```

### Infrastructure layer (`main.cxx`)
- Creates DDSParticipantSetup, readers, writers
- Wires DDS callbacks to logic layer functions
- Handles signal trapping, main loop, shutdown
- This is the ONLY file that includes DDS headers

### Logic layer (`<process_name>_logic.hpp/.cxx`)
- Contains callback handler implementations
- Receives plain IDL-generated structs as parameters (NOT DDS samples)
- Returns plain IDL structs or void
- Has NO DDS includes — only `#include "<TypeName>.hpp"` (IDL-generated types)
- Directly unit-testable without DDS runtime

### Example separation

```cpp
// gps_tracker_logic.hpp — PURE BUSINESS LOGIC
#pragma once
#include "gps_types/Command.hpp"    // IDL-generated type only
#include "gps_types/Position.hpp"

namespace gps_tracker {

  // Called when a Command is received — no DDS types in signature
  void on_command_received(const gps_types::Command& cmd);

  // Called at 2Hz to produce the next Position — returns data to publish
  gps_types::Position generate_position();

} // namespace
```

```cpp
// main.cxx — DDS INFRASTRUCTURE
#include "DDSParticipantSetup.hpp"
#include "DDSReaderSetup.hpp"
#include "DDSWriterSetup.hpp"
#include "gps_tracker_logic.hpp"

int main() {
  DDSParticipantSetup participant(...);

  auto cmd_reader = DDSReaderSetup<gps_types::Command>(...);
  cmd_reader.on_data_available([](const gps_types::Command& cmd) {
    gps_tracker::on_command_received(cmd);  // delegate to logic
  });

  auto pos_writer = DDSWriterSetup<gps_types::Position>(...);
  // Main loop: call logic, publish result
  while (running) {
    pos_writer.write(gps_tracker::generate_position());
    sleep(500ms);
  }
}
```

## Anti-Pattern Rules — NEVER Do These

1. **NEVER include DDS headers in logic files**
   - No `#include <dds/dds.hpp>`, no `#include "DDSReaderSetup.hpp"`
   - Logic files include ONLY IDL-generated type headers and standard library

2. **NEVER pass DDS types to business logic**
   - Callbacks receive `const Type&`, NOT `dds::sub::LoanedSample<Type>`
   - The infrastructure layer extracts `.data()` before calling logic

3. **NEVER put QoS, participant, or entity configuration in logic files**
   - All DDS configuration belongs in `main.cxx` or XML
   - Logic functions are DDS-unaware

4. **NEVER put business rules in main.cxx**
   - `main.cxx` is pure wiring: create entities, connect callbacks, run loop
   - All conditional logic, state machines, processing → logic files

5. **NEVER instantiate DDS entities inside callback handlers**
   - Readers/writers are created in `main.cxx` and passed by reference if needed

## Framework: Wrapper Class (C++11)

When generating app code using the Wrapper Class framework:

### Required includes and setup (in main.cxx only)
- `DDSParticipantSetup.hpp` — creates participant + AsyncWaitSet
- `DDSReaderSetup<T>.hpp` — template reader with callbacks
- `DDSWriterSetup<T>.hpp` — template writer with write methods
- Include generated type support: `<TypeName>.hpp`

### Code structure
1. `main.cxx`: Create `DDSParticipantSetup` with domain_id, QoS file path
2. `main.cxx`: For each input — create `DDSReaderSetup<Type>`, wire callback to logic function
3. `main.cxx`: For each output — create `DDSWriterSetup<Type>`, call logic in publish loop
4. `<name>_logic.hpp`: Declare handler functions for each callback + publish generators
5. `<name>_logic.cxx`: Implement business logic (state, processing, transforms)

### Code conventions (from existing apps)
- Use `application.hpp` for signal handling and app config struct
- Process command-line args: `--domain`, `--qos-file`, `--verbose`
- Return codes: 0 = success, 1 = error
- Always call `participant.finalize()` before exit

## Framework: XML App Creation

When generating XML App config:
- `<domain_participant>` with domain_id and participant QoS profile
- `<data_reader>` per input with topic, type, QoS profile ref
- `<data_writer>` per output with topic, type, QoS profile ref
- Minimal app code: just callbacks and main loop
- Same logic separation applies: `callbacks.cxx` has NO DDS includes

## CMakeLists.txt

Use the pattern from existing apps:
- `cmake_minimum_required(VERSION 3.11)`
- `project(<process_name>)`
- Source files: `main.cxx`, `<process_name>_logic.cxx`
- Link to `dds_typesupport` library
- Include wrapper headers from `dds/utils/cxx11/`

## On Completion

Return to /rti_dev:
- List of files created/modified
- Build command to use
- Confirm logic/infrastructure separation is correct
- Any warnings (missing dependencies, etc.)
```

#### `.github/prompts/tester.prompt.md`

```markdown
# Tester Sub-Prompt

You generate and run DDS integration tests using pytest.

## MCP Tools — Use These First

1. Query `github-starter-kit` for existing test patterns
   (check `services/recording_service_gui/test/` for pytest examples)
2. Check `tests/conftest.py` for existing fixtures

## Test Generation Rules

### Unit Tests (one per I/O)
- Use Python type support (generated by rtiddsgen)
- Create DDS participant in test fixture with isolated domain (domain_id=100)
- For outputs: create writer, write sample, create reader, verify receipt
- For inputs: create writer (simulating source), write sample, verify callback logic
- Timeout: 10s max per test
- Cleanup: dispose all entities in fixture teardown

### Integration Tests (one per process)
- Launch the compiled process as a subprocess
- Wait for discovery (5s default)
- Publish test stimuli (commands, etc.)
- Subscribe to expected outputs and verify
- Stop process, verify clean shutdown
- Use `helpers/process_launcher.py` for subprocess management

### Fixture Template
```python
@pytest.fixture
def dds_participant():
    participant = dds.DomainParticipant(domain_id=100)
    yield participant
    participant.close()
```

### Test Naming
- Unit: `test_<io_name>` (e.g., `test_position_publish`)
- Integration: `test_<process_name>_e2e` (e.g., `test_gps_tracker_e2e`)

## Auto-Proposal Logic

For each I/O in the design, propose:
| I/O | Pattern | Test |
|-----|---------|------|
| Any input | Any | write → verify callback |
| Any output | Any | create writer → publish → verify via reader |
| Output | Status | verify deadline not missed at declared rate |
| Input | Command | send command → verify process acts on it |
| Output | Large Data | verify payload size, throughput |
| Any process | Any | launch → verify I/O end-to-end |

## On Completion

Return to /rti_dev:
- List of test files generated
- pytest command to run them
- Expected pass/fail status
```

### How /rti_dev Loads Sub-Prompts

In the `/rti_dev` prompt file, the instructions reference sub-prompts like this:

```
### Step 2: Define I/O

For each I/O the user describes, walk through the **mandatory 3-step sub-loop**:

1. **Step 2a — Topic name & direction** — /rti_dev handles directly.

2. **Step 2b — Data type (mandatory gate)** — Load `.github/prompts/datamodel.prompt.md`
   and follow its instructions. The sub-prompt will:
   - Present the "Define New / Select Existing" choice
   - If Define New: walk through type name, module, fields, annotations, IDL preview
   - If Select Existing: scan workspace IDL + other process designs, present numbered list
   - Query github-types-repo for reference types
   - Query rti-docs-rag for IDL syntax if needed
   - The I/O CANNOT proceed until a type is confirmed

3. **Step 2c — Pattern & QoS** — Load `.github/prompts/patterns.prompt.md`
   and follow its instructions to select the data pattern and QoS.
   - This will auto-resolve the pattern from the type name
   - This will query rti-docs-rag for QoS documentation if needed
   - This will present options to the user via ask_questions

4. **Callbacks and rate** — Set automatically from the selected pattern.
```

### Interaction Example with Sub-Prompts

```
User: /rti_dev → Design Mode → ➕ Add New → "gps_tracker"
→ Step 1: name, domain ID, transports, system pattern opt-in (handled by /rti_dev directly)
→ Step 2: "It subscribes to Commands and publishes Position at 2Hz"

  /rti_dev parses: 2 I/O items — 1 input (Command), 1 output (Position)

  ── Starting I/O #1: input "CommandTopic" ──

  Step 2a: topic = "CommandTopic", direction = input

  Step 2b (type gate):
  ── datamodel.prompt.md activated ──

  Agent: "Data type for CommandTopic?
    1. 🆕 Define New Type
    2. 📂 Select Existing Type"

  (Agent scans workspace — no existing Command type found)
  User: "1 — Define New"

  Agent queries github-types-repo: "Command type IDL reference"
  Agent queries rti-docs-rag: "@key annotation usage"

  Agent: "Here's the proposed Command type:

    module gps_types {
      enum CommandAction { START, STOP, RESET, CALIBRATE };

      struct Command {
        @key string<64> device_id;
        CommandAction action;
        float value;
      };
    };

    @key: device_id (one instance per device)
  Does this look right? [Confirm / Edit / Add field]"

  User: "Confirm"

  Step 2c (pattern):
  ── patterns.prompt.md activated ──

  Agent: auto-resolves → Command pattern (type name = "Command")

  Agent: "Pattern auto-selected: Command

    Option 1: Single-source (SHARED ownership)     ← default
    Option 2: Multi-source (EXCLUSIVE, strength 10/20/30)

    Use option 1? [Yes / Pick option 2]"

  User: "Yes"

  Agent: Sets qos_profile = "DataPatternsLibrary::EventQoS",
         callbacks = [data_available, liveliness_changed]

  ── I/O #1 complete ──

  ── Starting I/O #2: output "PositionTopic" ──

  Step 2a: topic = "PositionTopic", direction = output

  Step 2b (type gate):
  ── datamodel.prompt.md activated ──

  Agent: "Data type for PositionTopic?
    1. 🆕 Define New Type
    2. 📂 Select Existing Type"

  User: "1 — Define New"

  Agent: "Define the type:
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

    [Confirm / Edit / Add field]"

  User: "Confirm"

  Step 2c (pattern):
  ── patterns.prompt.md activated ──

  Agent: auto-resolves → Status pattern (periodic data at 2Hz)
  Agent: "Status option: 1a (Standard) — BEST_EFFORT, Deadline 4s/10s"
  User: "Yes"
  Agent: Sets qos_profile = "DataPatternsLibrary::StatusQoS",
         rate_hz = 2, callbacks = [publication_matched]

  ── I/O #2 complete ──

  ── back to /rti_dev ──

  Agent: "2 I/O defined. Add more?
          [Add Input / Add Output / Done with I/O]"
  User: "Done"

→ Step 3: Tests

  ── tester.prompt.md activated ──
  Agent proposes tests based on I/O...
  ── back to /rti_dev ──

→ Step 4: Review (handled by /rti_dev)
```

---

## Prompt File Reference

### `.github/prompts/rti_dev.prompt.md`

````markdown
---
description: "DDS Process Builder — five-phase system for designing and
  building DDS processes. Scans workspace state, guides through design
  decisions, generates code, builds, and runs tests."
tools: ["file_search", "read_file", "list_dir", "grep_search",
        "run_in_terminal", "ask_questions", "semantic_search",
        "create_file", "replace_string_in_file",
        "multi_replace_string_in_file"]
---

# /rti_dev — DDS Process Builder

You are a DDS process builder. You help users design and implement
RTI Connext DDS applications through five phases:
Phase 0 (Project Init, locked) → Phase 1 (System Design, versioned) →
Phase 2 (System Impl) → Phase 3 (Process Design) → Phase 4 (Process Impl).

## On Every Invocation

1. Scan workspace state:
   - `planning/project.yaml` — project initialized?
   - `planning/system_config.yaml` — system design done?
   - `planning/processes/*.yaml` — list all design files
   - `apps/cxx11/` and `apps/python/` — list implemented apps
   - `tests/test_results/` — check for pass/fail
   - `dds/datamodel/idl/` — list existing types

2. If no project.yaml exists:
   → Run Phase 0 (Project Init): ask framework + API.
     Save to `planning/project.yaml` (locked). Then continue to Phase 1.

3. If no system_config.yaml exists:
   → Run Phase 1 (System Design): ask domain ID + system patterns.
     Save to `planning/system_config.yaml`. Then run Phase 2. Then show menu.

4. Check for system_config_version mismatches across process designs.
   If any process is behind the current version, flag it.

5. Build state summary:
   - For each design file: is it implemented? Are tests passing? Version mismatch?
   - Any processes designed but not implemented?
   - Any test failures?

6. Present **Level 1 menu** via `ask_questions`:
   - Show project + system config summary in header
   - "🛠 Design Mode" → go to Level 2a (process picker)
   - "🚀 Implement" → go to Level 2b (implement picker)
   - "🏗️ System Design" → re-enter Phase 1 (version++)
   - "✅ Done" → print final state summary

7. Level 2a (Design Mode): Present process picker via `ask_questions`:
   - List each existing process with status (✓/📋/⚠)
   - "➕ Add New Process" as the last option
   - User picks a process → load its YAML, show modify sub-menu
   - User picks "Add New" → start Phase 3 Step 1
   - "← Back" returns to Level 1

8. Level 2b (Implement): Present implement picker via `ask_questions`:
   - List processes that are unimplemented or have modified designs
   - "🔄 Implement ALL" as an option if more than one is ready
   - User picks one → run Phase 4 for that process
   - "← Back" returns to Level 1

9. After every action completes, return to the appropriate level:
   - After implementation → Level 1 (re-scan, show updated state)
   - After modifying a process → Level 2a (process picker, refreshed)
   - After adding a new process → Level 2a (process picker, refreshed)
   - User stays in the loop until they select "Done" at Level 1.

## Phase 3: Process Design

Follow these steps in order:

### Step 1: Process Identity
Ask for: process name, optional domain ID override, transport selection,
and system pattern opt-in (only patterns from system_config.yaml are offered).
Framework and API come from `planning/project.yaml` — do not ask per process.
Transports are per-process (SHMEM+UDP / SHMEM / UDP / TCP / Custom).
Free text for name. Domain ID defaults to system config value.

For system pattern opt-in: show only patterns in system_config.yaml,
ask for role per pattern (e.g., PRIMARY/STANDBY). The approach is inherited
from system config — do not ask again.

Write initial `planning/processes/<name>.yaml` with `system_config_version`.

### Step 2: Define I/O

For each I/O the user describes, walk through the **mandatory 3-step sub-loop**:

1. **Step 2a — Topic name & direction** — Resolve directly from user description.

2. **Step 2b — Data type (mandatory gate)** — Load `.github/prompts/datamodel.prompt.md`.
   Present the "Define New / Select Existing" choice. The I/O CANNOT proceed
   until a type is confirmed:
   - Define New: walk through type name, module, fields, annotations, IDL preview
   - Select Existing: scan workspace IDL + `planning/processes/*.yaml`, present list
   - Query github-types-repo for reference types
   - Query rti-docs-rag for IDL syntax if needed

3. **Step 2c — Pattern & QoS** — Load `.github/prompts/patterns.prompt.md`.
   Auto-resolve pattern from type name, present options via `ask_questions`,
   set QoS profile, callbacks, rate_hz.

After each I/O: "Add more I/O? [Add Input / Add Output / Done with I/O]"

Update the YAML after each I/O addition.

### Step 3: Tests

Load and follow `.github/prompts/tester.prompt.md`.
Based on inputs[] and outputs[], auto-propose tests.
Present to user: "Accept / Add / Remove / Modify"

Update YAML with tests section.

### Step 4: Review
Print complete design summary (readable format, not raw YAML).
Present options:
- Implement Now → proceed to Phase 4
- Add More I/O → return to Step 2
- Modify → jump to relevant step
- Save and Plan Another → save YAML, immediately start Step 1 for a new process
- Save and Exit → save YAML, return to main menu

The "Save and Plan Another" option is key for batch design workflows where
the user wants to design multiple processes before implementing any.

## Phase 4: Process Implementation

Read `planning/processes/<name>.yaml` and execute via **scripts**.
Read `planning/project.yaml` for framework/API.

Call scripts in order, stopping on first non-zero exit code:

```bash
# Step 1: Scaffold
scripts/scaffold.sh --project planning/project.yaml --process "$NAME" \
  --system-config planning/system_config.yaml

# Step 2: Run rtiddsgen (IDL files already exist from Phase 3 design)
scripts/run_rtiddsgen.sh --project planning/project.yaml --idl-dir dds/datamodel/idl/

# Step 3: Assemble QoS XML
scripts/assemble_qos.sh --design "planning/processes/${NAME}.yaml" \
  --templates system_templates/qos_templates/ --output dds/qos/DDS_QOS_PROFILES.xml

# Step 4: Generate app code (AGENT-DRIVEN — not a script)
#   Load builder.prompt.md, use blueprints/<pattern>/ as reference
#   This is the only step that requires AI-generated code

# Step 5: Generate tests
scripts/generate_tests.sh --design "planning/processes/${NAME}.yaml" \
  --system-config planning/system_config.yaml --output-dir tests/

# Step 6: Build
scripts/build.sh --project planning/project.yaml --process "$NAME"

# Step 7: Run tests
scripts/run_tests.sh --process "$NAME" --test-dir tests/
```

If user selects "Implement ALL", run the above sequence for each
unimplemented design file sequentially, stopping on first failure.

After implementation, return to main menu.

## Handling Direct Requests

If user says "/rti_dev add a Button input to gps_tracker":
1. Load gps_tracker.yaml
2. Go directly to Step 2 (I/O)
3. Add the Button input
4. Update YAML
5. Offer: "Re-implement now? [Yes / No]"

## MCP Tools

MCP tools are scoped to sub-prompts. /rti_dev does not query MCP directly —
it loads the appropriate sub-prompt prompt, which contains the MCP instructions.

| Sub-Prompt | MCP Tool | What It Queries |
|-----------|----------|----------------|
| datamodel | `rti-docs-rag` | IDL syntax, annotations, bounded types |
| datamodel | `github-types-repo` | Reference IDL templates per pattern |
| patterns  | `rti-docs-rag` | QoS policies, transport config, profiles |
| patterns  | `github-starter-kit` | Existing QoS XML in the project |
| builder   | `github-starter-kit` | Reference apps, wrapper classes, CMake |
| tester    | `github-starter-kit` | Existing test patterns, pytest fixtures |
````

### `.github/copilot-instructions.md`

```markdown
# Connext DDS Development

Type `/rti_dev` in Copilot Chat to plan and build DDS processes.

The builder guides you through five phases:
0. **Project Init** — framework + API (locked, one-time)
1. **System Design** — domain ID, system patterns (versioned)
2. **System Implementation** — baseline scaffold, system IDL/QoS
3. **Process Design** — per-process I/O, types, pattern opt-in, tests
4. **Process Implementation** — auto-generates code, QoS, tests, builds & runs

See `DDS_PROCESS_BUILDER.md` for full documentation.
```
