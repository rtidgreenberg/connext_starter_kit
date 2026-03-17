# DDS Process Builder — Phased Implementation Plan

Roadmap for building the complete `/rti_dev` workflow infrastructure on this repo. Each phase produces testable artifacts and can be validated independently before proceeding.

## Current State (Baseline)

**Already exists in repo:**

| Artifact | Path | Status |
|----------|------|--------|
| Architecture doc | `DDS_PROCESS_BUILDER.md` | Complete |
| Copilot instructions | `.github/copilot-instructions.md` | Minimal — needs update |
| Orchestrator prompt | `.github/prompts/rti_dev.prompt.md` | Basic — needs full rewrite |
| Framework selector prompt | `.github/prompts/framework_selector.prompt.md` | Exists |
| Wrapper classes prompt | `.github/prompts/wrapper_classes.prompt.md` | Exists |
| Build C++ prompt | `.github/prompts/build_cxx.prompt.md` | Exists |
| Example IDL types | `dds/datamodel/idl/ExampleTypes.idl` | Complete |
| Definitions IDL | `dds/datamodel/idl/Definitions.idl` | Complete |
| QoS profiles XML | `dds/qos/DDS_QOS_PROFILES.xml` | Complete (1073 lines) |
| Wrapper headers | `dds/utils/cxx11/DDS*.hpp` | Complete (7 files) |
| Example C++ apps | `apps/cxx11/*/` | Multiple working examples |
| Example Python apps | `apps/python/*/` | Multiple working examples |
| XML app creation script | `scripts/xml_app_creation.sh` | Exists |

**Needs to be created:**

| Category | Artifacts | Count |
|----------|-----------|-------|
| Directory structure | `planning/`, `system_templates/`, `tests/helpers/` | 3 trees |
| Planning YAMLs | `project.yaml`, `system_config.yaml`, example process YAMLs | 4-5 files |
| System templates | Scaffold files, QoS fragments, blueprints | ~25 files |
| Implementation scripts | scaffold.sh, run_rtiddsgen.sh, assemble_qos.sh, generate_tests.sh, build.sh, run_tests.sh | 6 files |
| Sub-prompt files | datamodel.prompt.md, patterns.prompt.md, builder.prompt.md, tester.prompt.md | 4 files |
| System patterns IDL | system_patterns.idl template | 1 file |
| Updated prompts | rti_dev.prompt.md (full rewrite), copilot-instructions.md (update) | 2 files |

---

## Phase 1: Directory Structure & Planning Artifacts

**Goal:** Establish the `planning/` directory with YAML schemas and example configs. After this phase, the Phase 0 → Phase 1 state detection loop works.

### 1.1 Create directory tree

```
planning/
├── IMPLEMENTATION_PLAN.md          ← this file
├── processes/                      ← per-process design YAMLs go here
│   └── .gitkeep
├── project.yaml.example            ← annotated example (not live config)
└── system_config.yaml.example      ← annotated example (not live config)
```

### 1.2 Create `planning/project.yaml.example`

Annotated example showing all fields, derived values, and validation rules per the schema in DDS_PROCESS_BUILDER.md § Phase 0. Covers all 5 API choices with derived field mappings.

### 1.3 Create `planning/system_config.yaml.example`

Annotated example showing domain_id, system_patterns with approach options, versioning semantics. References the System Patterns Catalog.

### 1.4 Create `planning/processes/gps_tracker.yaml.example`

Complete PROCESS_DESIGN.yaml example following the full schema from DDS_PROCESS_BUILDER.md: process identity, system pattern opt-in, inputs/outputs with types and patterns, tests, decisions. This is the reference artifact for all process designs.

### 1.5 Create `planning/processes/command_controller.yaml.example`

Second example showing type reuse (references same `gps_types.idl`), Command pattern option 2 (multi-source with EXCLUSIVE ownership), and standby role for failover.

**Validation:** `/rti_dev` state detection can check for `planning/project.yaml` and route correctly. Example YAMLs serve as schema documentation.

---

## Phase 2: System Templates — Scaffolds

**Goal:** Create the `system_templates/` tree with scaffold starter files for both frameworks. These are the read-only templates that `scaffold.sh` copies into `apps/<api>/<process>/`.

### 2.1 Wrapper Class scaffold

```
system_templates/wrapper_class/scaffold/
├── CMakeLists.txt.template         ← parameterized: {{PROCESS_NAME}}, {{IDL_TYPES}}
├── application.hpp.template        ← signal handling, config struct
├── app_main.cxx.template           ← DDS infrastructure skeleton
└── run.sh.template                 ← launch script with --domain, --qos-file args
```

### 2.2 XML App Creation scaffold

```
system_templates/xml_app_creation/scaffold/
├── CMakeLists.txt.template
├── APP_CONFIG.xml.template         ← participant, readers, writers from design
├── USER_QOS_PROFILES.xml.template  ← process-specific QoS overlay
├── app_main.cxx.template           ← minimal: load XML config, register callbacks
├── callbacks.hpp.template          ← callback declarations
└── callbacks.cxx.template          ← callback implementations (logic layer)
```

### 2.3 Python scaffold

```
system_templates/python/scaffold/
├── requirements.txt.template
├── app_main.py.template
├── {{process_name}}_logic.py.template
└── run.sh.template
```

**Validation:** Templates can be inspected for correctness. Parameter placeholders (`{{PROCESS_NAME}}`, etc.) are documented.

---

## Phase 3: System Templates — QoS Fragments

**Goal:** Create per-pattern QoS XML fragments that `assemble_qos.sh` merges into `DDS_QOS_PROFILES.xml`. Extracted from the existing comprehensive QoS XML.

### 3.1 Data pattern QoS fragments

```
system_templates/qos_templates/
├── event_qos.xml                   ← RELIABLE, KEEP_ALL, Liveliness
├── status_qos.xml                  ← BEST_EFFORT, KEEP_LAST 1, Deadline
├── command_qos.xml                 ← RELIABLE, KEEP_ALL (shared ownership)
├── command_exclusive_qos.xml       ← RELIABLE + EXCLUSIVE ownership + strength
├── parameter_qos.xml               ← RELIABLE, TRANSIENT_LOCAL
├── large_data_shmem_qos.xml        ← SHMEM transport, large buffer
├── large_data_shmem_zc_qos.xml     ← SHMEM zero-copy (FLAT_DATA)
├── large_data_udp_qos.xml          ← UDP burst, flow controllers
└── assigner_qos.xml                ← Assigner pattern (existing)
```

### 3.2 System pattern QoS fragments

```
system_templates/qos_templates/
├── heartbeat_qos.xml               ← RELIABLE, Deadline 2s, Liveliness 3s, EXCLUSIVE
├── health_monitor_qos.xml          ← RELIABLE, Deadline, status metrics
├── leader_election_qos.xml         ← EXCLUSIVE ownership for election
└── request_reply_qos.xml           ← RELIABLE, KEEP_ALL for req/rep topics
```

**Validation:** Each fragment is well-formed XML. Profile names match those referenced in `Definitions.idl` and the patterns catalog.

---

## Phase 4: System Templates — Blueprints

**Goal:** Create code blueprint templates per data pattern × API. These are the reference implementations that `builder.prompt.md` uses during Step 4 (app code generation).

### 4.1 C++11 blueprints (one per data pattern)

```
system_templates/blueprints/
├── event/cxx11/
│   ├── reader_callback.cxx.template    ← data_available + liveliness_changed
│   ├── writer_trigger.cxx.template     ← on-demand write
│   └── README.md                       ← pattern description + QoS rationale
├── status/cxx11/
│   ├── reader_callback.cxx.template    ← data_available handler
│   ├── writer_periodic.cxx.template    ← timer loop at rate_hz
│   └── README.md
├── command/cxx11/
│   ├── reader_callback.cxx.template    ← command handler with dispatch
│   ├── writer_ondemand.cxx.template    ← command issuer
│   └── README.md
├── parameter/cxx11/
│   ├── parameter_server.cxx.template   ← DDSParameterSetup usage
│   ├── parameter_client.cxx.template   ← DDSClientParameterSetup usage
│   └── README.md
└── large_data/cxx11/
    ├── reader_callback.cxx.template    ← large payload handler
    ├── writer_burst.cxx.template       ← burst writer with pre-allocation
    └── README.md
```

### 4.2 Python blueprints (abbreviated — same structure)

```
system_templates/blueprints/
├── event/python/
│   ├── reader_callback.py.template
│   └── writer_trigger.py.template
├── status/python/
│   ├── reader_callback.py.template
│   └── writer_periodic.py.template
└── ... (command, parameter, large_data)
```

**Validation:** Each blueprint compiles conceptually against the wrapper headers. README describes when/how it's used.

---

## Phase 5: System Patterns IDL Template

**Goal:** Create the system-level IDL that Phase 2 (System Implementation) generates based on selected system patterns.

### 5.1 System patterns IDL

```
system_templates/system_patterns.idl.template
```

Contains all possible system pattern types (gated by pattern selection):
- `ProcessRole` enum (failover)
- `HeartbeatStatus` struct (failover)
- `ProcessState` enum (health monitoring)
- `HealthStatus` struct (health monitoring)
- `LeaderBid` struct (leader election)
- `ServiceRequest`/`ServiceReply` struct templates (request-reply)

The scaffold script copies only the sections relevant to the selected patterns.

**Validation:** IDL compiles with `rtiddsgen -ppDisable` validation.

---

## Phase 6: Implementation Scripts

**Goal:** Create the 6 shell scripts that automate Phase 4 (Process Implementation). Each is idempotent, accepts standard args, and returns documented exit codes.

### 6.1 `scripts/scaffold.sh`

Reads `project.yaml` + `system_config.yaml`, copies templates from `system_templates/`, substitutes parameters, creates `apps/<api>/<process>/` directory.

### 6.2 `scripts/run_rtiddsgen.sh`

Reads `project.yaml` for API → maps to `-language` flag. Runs `rtiddsgen -replace` on specified IDL files. Output to `dds/build/<api>_gen/`.

### 6.3 `scripts/assemble_qos.sh`

Reads process design YAML for `qos_profile` references, copies matching fragments from `system_templates/qos_templates/`, merges into `dds/qos/DDS_QOS_PROFILES.xml` (no duplicates).

### 6.4 `scripts/generate_tests.sh`

Reads `tests.unit[]` and `tests.integration[]` from process design YAML. Generates pytest files from templates. Creates `conftest.py` if missing.

### 6.5 `scripts/build.sh`

Dispatches to `cmake`, `pip`, or `maven` based on project API. Runs build for specified process.

### 6.6 `scripts/run_tests.sh`

Runs `pytest` for the specified process. Captures JUnit XML results to `tests/test_results/`.

**Validation:** Each script has `--help` output, validates required args, returns correct exit codes. Can be run with `--dry-run` to show what would be done.

---

## Phase 7: Sub-Prompt Files

**Goal:** Create the 4 specialized prompt files that `/rti_dev` loads contextually during planning and implementation.

### 7.1 `.github/prompts/datamodel.prompt.md`

Type definition specialist. Handles the mandatory type gate (Step 2b): Define New / Select Existing, field-by-field walkthrough, IDL preview, MCP tool instructions for type repos.

### 7.2 `.github/prompts/patterns.prompt.md`

Pattern & QoS selection specialist. Auto-resolve rules, pattern catalog with options, QoS profile mapping, callback assignment.

### 7.3 `.github/prompts/builder.prompt.md`

Code generation specialist. Clean architecture rules (main.cxx vs logic layer), framework-specific generation, CMake template, anti-pattern enforcement.

### 7.4 `.github/prompts/tester.prompt.md`

Test generation specialist. Auto-proposal logic per I/O pattern, pytest fixtures, integration test subprocess management, domain isolation.

**Validation:** Each prompt follows the schema from DDS_PROCESS_BUILDER.md § Sub-Prompt Architecture. MCP tool references are correct.

---

## Phase 8: Orchestrator Prompt Rewrite

**Goal:** Replace the current basic `rti_dev.prompt.md` with the full five-phase orchestrator from DDS_PROCESS_BUILDER.md § Prompt File Reference.

### 8.1 Rewrite `.github/prompts/rti_dev.prompt.md`

Full implementation of:
- State detection (scan `planning/`, `apps/`, `tests/`, `dds/`)
- Phase 0 routing (project init)
- Phase 1 routing (system design)
- Phase 2 automation (system implementation)
- Level 1 menu (Design / Implement / System Design / Done)
- Level 2a (process picker + modify sub-menu)
- Level 2b (implement picker)
- Sub-prompt dispatch for Steps 2b, 2c, 3
- Direct request handling (natural language bypass)

### 8.2 Update `.github/copilot-instructions.md`

Replace the minimal current version with the full version from DDS_PROCESS_BUILDER.md that describes all 5 phases and points to `/rti_dev`.

**Validation:** Invoke `/rti_dev` on a fresh workspace → should detect no project.yaml → offer framework selection. Invoke after creating project.yaml → should route to system design.

---

## Phase 9: Test Infrastructure

**Goal:** Create test helpers and conftest templates that `generate_tests.sh` uses.

### 9.1 Test helpers

```
tests/
├── helpers/
│   ├── process_launcher.py         ← subprocess management for integration tests
│   ├── dds_fixtures.py             ← shared DDS participant/reader/writer fixtures
│   └── assertion_utils.py          ← wait_for_data, verify_rate, verify_fields
├── conftest.py.template            ← pytest conftest with domain isolation (domain_id=100)
└── test_results/
    └── .gitkeep
```

**Validation:** Helper modules import cleanly. Conftest template produces valid pytest configuration.

---

## Execution Order & Dependencies

```
Phase 1: Planning artifacts          ← no dependencies (start here)
    │
Phase 2: Scaffold templates          ← no dependencies (parallel with 1)
    │
Phase 3: QoS fragments               ← no dependencies (parallel with 1, 2)
    │
Phase 4: Blueprint templates         ← depends on Phase 2 (uses scaffold structure)
    │
Phase 5: System patterns IDL         ← depends on Phase 3 (references QoS profiles)
    │
Phase 6: Implementation scripts      ← depends on Phases 2, 3, 5 (reads templates)
    │
Phase 7: Sub-prompt files            ← depends on Phases 3, 4 (references patterns, blueprints)
    │
Phase 8: Orchestrator rewrite        ← depends on Phase 7 (dispatches to sub-prompts)
    │
Phase 9: Test infrastructure         ← depends on Phase 6 (generate_tests.sh uses templates)
```

**Phases 1–3 can run in parallel.** Phases 4–5 can run in parallel after 2–3. Phases 6–9 are sequential.

---

## Artifact Summary

| Phase | Files Created | Lines (est.) |
|-------|--------------|-------------|
| 1. Planning | 4 YAML examples + .gitkeep | ~300 |
| 2. Scaffolds | 13 template files (3 frameworks) | ~500 |
| 3. QoS fragments | 12 XML fragments | ~600 |
| 4. Blueprints | 12 code templates + 5 READMEs | ~800 |
| 5. System IDL | 1 template IDL | ~80 |
| 6. Scripts | 6 shell scripts | ~600 |
| 7. Sub-prompts | 4 prompt files | ~800 |
| 8. Orchestrator | 2 updated prompts | ~400 |
| 9. Tests | 4 Python files + template | ~300 |
| **Total** | **~60 files** | **~4,400 lines** |
