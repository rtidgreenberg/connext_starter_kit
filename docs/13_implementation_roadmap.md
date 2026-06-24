# Implementation Roadmap

Phased build plan for the RTI Rapid Prototyping — from empty template slots to a fully operational `the workflow` workflow backed by an internal MCP server. Each phase produces testable deliverables. Phases are ordered by dependency; independent phases can run in parallel.

---

## Current State (Baseline Audit)

### Exists and Complete

| Artifact | Path | Notes |
|----------|------|-------|
| Architecture docs | `RTI_RAPID_PROTOTYPING.md` + `docs/01-12` | 12 split docs + summary |
| Workflow entrypoint | Removed prompt file | Historical orchestrator prompt was removed from `.github/prompts/` |
| Framework selector prompt | `.github/prompts/framework_selector.prompt.md` | Exists |
| Wrapper classes prompt | `.github/prompts/wrapper_classes.prompt.md` | Exists |
| C++ build guidance | `apps/cxx11/README.md` | Guidance consolidated into repository docs |
| Copilot instructions | `.github/copilot-instructions.md` | Minimal routing — needs update |
| Wrapper class headers | `dds/utils/cxx11/DDS*.hpp` | 7 complete headers |
| Example IDL types | `dds/datamodel/idl/*.idl` | ExampleTypes.idl, Definitions.idl |
| QoS profiles | `dds/qos/DDS_QOS_PROFILES.xml` | 1073 lines, complete |
| C++ example apps | `apps/cxx11/*/` | Multiple working examples |
| Python example apps | `apps/python/*/` | Multiple working examples |
| Planning examples | `planning/*.yaml.example` | project.yaml.example, system_config.yaml.example |
| Process design examples | `planning/processes/*.yaml.example` | gps_tracker, command_controller |

### Exists but Empty (structure only, `.gitkeep`)

| Artifact | Path | Needs |
|----------|------|-------|
| Blueprint dirs | `system_templates/blueprints/{event,status,command,parameter,large_data}/{cxx11,python}/` | Template code files |
| QoS templates dir | `system_templates/qos_templates/` | Per-pattern QoS XML fragments |
| System pattern dirs | `system_templates/system_patterns/{failover,health_monitoring,leader_election,request_reply,parameter_service,command_arbitration,sensor_redundancy}/` | IDL templates, QoS fragments, logic snippets (I/O-generating patterns); QoS rules + README (QoS-modifying patterns) |

### Exists and Populated (scaffold templates)

| Artifact | Path | Files |
|----------|------|-------|
| Wrapper class scaffold | `system_templates/wrapper_class/scaffold/` | CMakeLists, app_main, application.hpp, process_logic .hpp/.cxx, run.sh (all `.template`) |
| XML app creation scaffold | `system_templates/xml_app_creation/scaffold/` | CMakeLists, app_main, callbacks .hpp/.cxx, DomainLibrary.xml, ParticipantLibrary.xml, run.sh |
| Python scaffold | `system_templates/python/scaffold/` | app_main.py, process_logic.py, requirements.txt, run.sh |

### Missing Entirely

| Category | What's Needed |
|----------|---------------|
| Manifest files | `system_templates/wrapper_class/manifest.yaml`, `xml_app_creation/manifest.yaml`, `python/manifest.yaml`, `system_manifest.yaml`, `reference_manifest.yaml` |
| Sub-prompt files | `datamodel.prompt.md`, `patterns.prompt.md`, `builder.prompt.md`, `tester.prompt.md` |
| Test infrastructure | `tests/helpers/`, `tests/conftest.py.template`, `tests/test_results/` |
| MCP server config | `.vscode/mcp.json` or equivalent |
| System patterns IDL template | `system_templates/system_patterns/system_patterns.idl.template` |

---

## Phase R0: Schema Fixes (Dry-Run Blockers)

**Goal:** Fix design-level gaps discovered during use-case dry runs ([docs/14](docs/14_use_case_dry_run.md)). These are schema and documentation changes that must land before any implementation phase — they alter the contract that manifests, prompts, and blueprints build against.

**Depends on:** Nothing (start here, blocks R1/R6/R7)

**Source:** [Use-Case Dry Runs & Gap Analysis](docs/14_use_case_dry_run.md) — Gap IDs referenced below.

### Tasks

| # | Task | Artifact | Description | Dry-Run Gap |
|---|------|----------|-------------|-------------|
| R0.1 | Add `participant_qos_profile` to PROCESS_DESIGN schema | `docs/05_phase_3_process_design.md` | Add optional field `process.participant_qos_profile` (string). When absent, auto-derive from transport + largest data size: SHMEM + data > 64 KB → `DPLibrary::LargeDataSHMEMParticipant`; SHMEM + FlatData → same; UDP + large data → `LargeDataUDPParticipant`; otherwise → `DefaultParticipant`. Add derivation rule to `docs/08_decision_points.md`. Update both `.yaml.example` files in `planning/processes/`. | R3-4 (HIGH) |
| R0.2 | Add per-process `language` field for multi-language projects | `docs/05_phase_3_process_design.md` | Add optional field `process.language` (enum: `modern_cpp`, `python`, `java`, `c`). Required when `project.api` is `modern_cpp_python`. When `project.api` is single-language, inherited and omitted. Update schema, examples, and `docs/02_phase_0_project_init.md` derived-fields table. | F0-1 (HIGH) |
| R0.3 | Add `qos_modifiers` / `downsample_hz` to I/O schema | `docs/05_phase_3_process_design.md` | Add optional field `downsample_hz` on input entries (shorthand for TIME_BASED_FILTER `minimum_separation`). Alternatively, add `qos_modifiers: [{type: time_based_filter, minimum_separation_ms: N}]` list. This enables "Large Data at 1 Hz from a 10 Hz publisher" without a new QoS profile. Update pattern auto-resolve rules in `docs/07_patterns_reference.md` to detect when a subscriber rate differs from the publisher rate. | F3-3 (HIGH), F3-4 |
| R0.4 | Add manifest routing table (framework × api) | `docs/09_repository_structure.md` | Document which manifest file is selected for each `(framework, api)` combination: `(wrapper_class, modern_cpp)` → `wrapper_class/manifest.yaml`; `(wrapper_class, python)` → `python/manifest.yaml`; `(xml_app_creation, modern_cpp)` → `xml_app_creation/manifest.yaml`; etc. The orchestrator uses this routing table in Phase 4 Step 1. | R0-2 (MEDIUM) |
| R0.5 | Document Python import path rules | `docs/01_rules.md` | Add new rules PYTHON-1 through PYTHON-3: (1) `sys.path.insert` convention for locating generated types, (2) import statement mapping: IDL file `ExampleTypes.idl` with module `example_types` → `from python_gen.ExampleTypes import example_types`, (3) build-time vs pre-built path resolution (`dds/datamodel/` vs `build/dds/python_gen/`). | R4-3 (MEDIUM) |
| R0.6 | Document FlatData cross-language constraints | `docs/07_patterns_reference.md` | Add "Language Constraints" section to Large Data pattern: (1) Zero-Copy (Option 2) is C++ only; Python/Java fall back to Option 1 (SHMEM). (2) Python subscribers to FlatData topics use standard SHMEM QoS — DDS handles XCDR2 deserialization transparently. (3) Annotate auto-resolve rule: if selected type has `@language_binding(FLAT_DATA)` and process language is Python → force option 1, warn user. | F3-2 (HIGH), F3-5 |
| R0.7 | Clarify QoS fragment vs monolithic strategy | `docs/04_phase_2_system_impl.md`, `docs/09_repository_structure.md` | Document that `DDS_QOS_PROFILES.xml` is the source of truth. QoS fragments in `qos_templates/` serve as agent reference material (the building blocks that comprise the monolith). Phase 4 Step 3 (QoS Assembly) becomes "verify the needed profile exists in QoS XML; if not, warn user." Fragments are not assembled at runtime — they exist for documentation, indexing by MCP, and for users who want to understand individual pattern QoS. | R4-5 (LOW) |

### Deliverables
- Updated schema docs (docs/01, 02, 04, 05, 07, 08, 09)
- Updated planning YAML examples
- All downstream phases (R1, R4, R6, R7) build against the corrected schema

### Validation
- `participant_qos_profile` auto-derive rule produces correct profile for all 3 Large Data pattern options
- `gps_tracker.yaml.example` and `command_controller.yaml.example` pass schema validation with new fields
- Python import rules are consistent with existing `apps/python/large_data_app/large_data_app.py`
- FlatData constraint triggers correctly: FlatData type + Python → auto-downgrade to Option 1 with warning

---

## Phase R1: Planning Artifacts & Manifest Files

**Goal:** Manifest-driven scaffold is the core mechanic. Create the manifest YAML files that tell the agent what to create, where to source it, and where to write it. Validate that the planning YAML examples match the current architecture docs.

**Depends on:** R0 (schemas must be finalized before manifests encode them)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R1.1 | Create wrapper class manifest | `system_templates/wrapper_class/manifest.yaml` | Map each scaffold template → `filename`, `destination`, `source`, `template` path. Include `build_integration` for top-level CMakeLists. Declare `framework: wrapper_class, api: modern_cpp` per R0.4 routing table. Follow schema from [docs/09](docs/09_repository_structure.md). |
| R1.2 | Create XML app creation manifest | `system_templates/xml_app_creation/manifest.yaml` | Same structure for XML App Creation scaffold files. Include XML library files. |
| R1.3 | Create Python manifest | `system_templates/python/manifest.yaml` | Same structure for Python scaffold. `pip` build integration instead of CMake. |
| R1.4 | Create system manifest | `system_templates/system_manifest.yaml` | Phase 2 baseline: directories to create, files to verify, system IDL/QoS to generate. Follow schema from [docs/04](docs/04_phase_2_system_impl.md). |
| R1.5 | Create reference manifest | `system_templates/reference_manifest.yaml` | Phase 0 bootstrap: maps empty template slots (blueprints, qos_templates, system_patterns) to GitHub source repos. |
| R1.6 | Validate planning YAMLs | `planning/*.yaml.example` | Verify `project.yaml.example` and `system_config.yaml.example` match current schemas in [docs/02](docs/02_phase_0_project_init.md) and [docs/03](docs/03_phase_1_system_design.md). Update if needed. |
| R1.7 | Validate process design YAMLs | `planning/processes/*.yaml.example` | Verify `gps_tracker.yaml.example` and `command_controller.yaml.example` match current PROCESS_DESIGN.yaml schema in [docs/05](docs/05_phase_3_process_design.md). Must include new fields from R0: `participant_qos_profile`, `language` (if multi-lang), `downsample_hz` (on at least one example input). Update if needed. |
| R1.8 | Add manifest routing logic | In each `manifest.yaml` | Each manifest must declare its `framework` + `api` applicability so the agent can select the correct manifest per the routing table from R0.4. E.g., `python/manifest.yaml` declares `framework: wrapper_class, api: python`. |

### Deliverables
- 5 manifest YAML files
- 4 validated example YAMLs
- Agent can `read_file(manifest.yaml)` and understand exactly what to create

### Validation
- Each manifest is valid YAML
- Every `template` path in a manifest points to an existing `.template` file
- Every `destination` uses valid `{{VARIABLE}}` tokens documented in the schema

---

## Phase R2: QoS Fragment Templates

**Goal:** Populate the empty `qos_templates/` directory with per-pattern QoS XML fragments. These are the building blocks that get assembled into `dds/qos/` during Phase 2 and Phase 4.

**Depends on:** Nothing (parallel with R1)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R2.1 | Create Event QoS fragment | `system_templates/qos_templates/event_qos.xml.fragment` | RELIABLE, KEEP_ALL, Liveliness AUTOMATIC 4s/10s. Profile name: `DataPatternsLibrary::EventQoS` |
| R2.2 | Create Status QoS fragment | `system_templates/qos_templates/status_qos.xml.fragment` | BEST_EFFORT, KEEP_LAST 1, Deadline 4s/10s. Profile name: `DataPatternsLibrary::StatusQoS` |
| R2.3 | Create Command QoS fragment | `system_templates/qos_templates/command_qos.xml.fragment` | RELIABLE, KEEP_ALL, SHARED ownership. Profile name: `DataPatternsLibrary::CommandQoS` |
| R2.4 | Create Command Exclusive QoS | `system_templates/qos_templates/command_exclusive_qos.xml.fragment` | RELIABLE, EXCLUSIVE ownership, strength-based. Profile name: `DataPatternsLibrary::CommandExclusiveQoS` |
| R2.5 | Create Parameter QoS fragment | `system_templates/qos_templates/parameter_qos.xml.fragment` | RELIABLE, TRANSIENT_LOCAL. Profile name: `DataPatternsLibrary::ParameterQoS` |
| R2.6 | Create Large Data SHMEM QoS | `system_templates/qos_templates/large_data_shmem_qos.xml.fragment` | SHMEM transport only, large buffers. |
| R2.7 | Create Large Data SHMEM ZC QoS | `system_templates/qos_templates/large_data_shmem_zc_qos.xml.fragment` | SHMEM zero-copy (FLAT_DATA). |
| R2.8 | Create Large Data UDP QoS | `system_templates/qos_templates/large_data_udp_qos.xml.fragment` | UDP with flow controllers. |
| R2.9 | Create Heartbeat QoS fragment | `system_templates/qos_templates/heartbeat_qos.xml.fragment` | RELIABLE, Deadline 2s, Liveliness 3s, EXCLUSIVE ownership. |
| R2.10 | Create Health Monitor QoS | `system_templates/qos_templates/health_monitor_qos.xml.fragment` | RELIABLE, Deadline, status metrics. |
| R2.11 | Create Leader Election QoS | `system_templates/qos_templates/leader_election_qos.xml.fragment` | EXCLUSIVE ownership for leader election. |
| R2.12 | Create Request-Reply QoS | `system_templates/qos_templates/request_reply_qos.xml.fragment` | RELIABLE, KEEP_ALL for request/reply topics. |

### Deliverables
- 12 QoS XML fragment files
- Each is standalone valid XML with unique profile names

### Validation
- `xmllint --noout` passes on each fragment
- No duplicate profile names across fragments
- Profile names match references in [docs/07](docs/07_patterns_reference.md) pattern tables

---

## Phase R3: System Patterns IDL & Implementation Templates

**Goal:** Populate the empty `system_patterns/` directories. System patterns fall into two categories:

- **I/O-generating patterns** (Failover, Health Monitoring, Leader Election, Request-Reply): need IDL templates, logic snippets, and QoS fragment references.
- **QoS-modifying patterns** (Command Arbitration, Sensor Redundancy): need only a README documenting QoS rules and role-to-strength mapping. They modify user-defined I/O rather than generating new topics.

**Depends on:** R2 (references QoS profile names)

### Tasks

| # | Task | Artifact(s) | Description |
|---|------|-------------|-------------|
| R3.1 | Create system patterns IDL template | `system_templates/system_patterns/system_patterns.idl.template` | Combined IDL with all I/O-generating pattern types: `ProcessRole` enum, `HeartbeatStatus`, `HealthStatus`, `LeaderBid`, `ServiceRequest`/`ServiceReply`, `ParameterType`/`ParameterValue`/`Parameter`/`ParameterEvent`/`SetParametersRequest`/`SetParametersResponse`/`GetParametersRequest`/`GetParametersResponse`. Gated by `{{PATTERN_*}}` conditionals. Does NOT include Command Arbitration or Sensor Redundancy (they don't add types). |
| R3.2 | Create failover pattern files | `system_templates/system_patterns/failover/` | `heartbeat_writer.cxx.snippet` (PRIMARY publishes heartbeat), `heartbeat_reader.cxx.snippet` (STANDBY monitors liveliness), `README.md` (pattern description, QoS rationale, opt-in behavior). |
| R3.3 | Create health monitoring files | `system_templates/system_patterns/health_monitoring/` | `health_publisher.cxx.snippet` (publish ProcessHealth at 1Hz), `health_subscriber.cxx.snippet` (monitor all processes), `README.md`. |
| R3.4 | Create leader election files | `system_templates/system_patterns/leader_election/` | `leader_bid_writer.cxx.snippet`, `leader_monitor.cxx.snippet`, `README.md`. |
| R3.5 | Create request-reply files | `system_templates/system_patterns/request_reply/` | `service_server.cxx.snippet`, `service_client.cxx.snippet`, `README.md`. |
| R3.6 | Create command arbitration files | `system_templates/system_patterns/command_arbitration/` | `README.md` only — documents QoS-modifying behavior: role→strength mapping (`command_primary`=100, `command_secondary`=50), EXCLUSIVE ownership rules, auto-applied QoS profiles (`CommandPrimaryQoS`, `CommandSecondaryQoS`), integration test template. No IDL or code snippets needed. |
| R3.7 | Create sensor redundancy files | `system_templates/system_patterns/sensor_redundancy/` | `README.md` only — documents QoS-modifying behavior: role→strength mapping (`sensor_primary`=100, `sensor_secondary`=50), EXCLUSIVE ownership on status outputs, auto-applied QoS profiles (`StatusPrimaryQoS`, `StatusSecondaryQoS`), integration test template. No IDL or code snippets needed. |
| R3.8 | Create parameter service files | `system_templates/system_patterns/parameter_service/` | `parameter_server.cxx.snippet` (DDSServerParameterSetup wrapper), `parameter_client.cxx.snippet` (DDSClientParameterSetup wrapper), `README.md` (7-topic set, server/client roles, integration with existing DDSParameterSetup wrappers in `dds/utils/cxx11/`). I/O-generating pattern. |

### Deliverables
- 1 combined system IDL template (I/O-generating patterns only)
- 5 I/O-generating pattern directories with snippets + READMEs (~16 files)
- 2 QoS-modifying pattern directories with README only (~2 files)
- Total: 7 pattern directories, ~18 files

### Validation
- IDL template compiles with `rtiddsgen -ppDisable` when all conditionals are enabled
- Each snippet references correct QoS profile names from R2
- README describes when/how the pattern is opt-in per [docs/07](docs/07_patterns_reference.md)
- QoS-modifying pattern READMEs document role→strength→profile mapping

---

## Phase R4: Blueprint Code Templates

**Goal:** Populate the empty `blueprints/` directories with per-pattern code templates. These are the reference implementations the builder sub-prompt uses during Phase 4 Step 4 (app code generation).

**Depends on:** R1 (manifest references blueprint paths), scaffold templates exist

### Tasks

| # | Task | Artifact(s) | Description |
|---|------|-------------|-------------|
| R4.1 | Event pattern — C++11 | `system_templates/blueprints/event/cxx11/` | `reader_callback.cxx.template` (data_available + liveliness_changed), `writer_trigger.cxx.template` (on-demand write), `README.md` |
| R4.2 | Event pattern — Python | `system_templates/blueprints/event/python/` | `reader_callback.py.template`, `writer_trigger.py.template` |
| R4.3 | Status pattern — C++11 | `system_templates/blueprints/status/cxx11/` | `reader_callback.cxx.template`, `writer_periodic.cxx.template` (timer loop at `{{RATE_HZ}}`), `README.md` |
| R4.4 | Status pattern — Python | `system_templates/blueprints/status/python/` | `reader_callback.py.template`, `writer_periodic.py.template` |
| R4.5 | Command pattern — C++11 | `system_templates/blueprints/command/cxx11/` | `reader_callback.cxx.template` (command dispatch), `writer_ondemand.cxx.template`, `README.md` |
| R4.6 | Command pattern — Python | `system_templates/blueprints/command/python/` | `reader_callback.py.template`, `writer_ondemand.py.template` |
| R4.7 | Parameter pattern — C++11 | `system_templates/blueprints/parameter/cxx11/` | `parameter_server.cxx.template` (DDSParameterSetup), `parameter_client.cxx.template` (DDSClientParameterSetup), `README.md` |
| R4.8 | Parameter pattern — Python | `system_templates/blueprints/parameter/python/` | `parameter_server.py.template`, `parameter_client.py.template` |
| R4.9 | Large Data pattern — C++11 | `system_templates/blueprints/large_data/cxx11/` | `reader_callback.cxx.template` (large payload handler), `writer_burst.cxx.template` (pre-allocated burst), `README.md` |
| R4.10 | Large Data pattern — Python | `system_templates/blueprints/large_data/python/` | `reader_callback.py.template`, `writer_burst.py.template` |
| R4.11 | Large Data Zero-Copy — C++11 | `system_templates/blueprints/large_data_zc/cxx11/` | `reader_flat.cxx.template` (FlatData sample handling), `writer_flat.cxx.template` (get_loan + builder pattern + finish + write), `README.md` explaining FlatData API differences. Extract from `apps/cxx11/fixed_image_flat_zc/`. **C++ only** — no Python equivalent (see R0.6). |
| R4.12 | Large Data Downsampled — Python | `system_templates/blueprints/large_data_downsampled/python/` | `reader_downsampled.py.template` (async reader with TIME_BASED_FILTER QoS applied). Extract from `apps/python/downsampled_reader/`. Shows `downsample_hz` (R0.3) in action. |
| R4.13 | Large Data Downsampled — C++11 | `system_templates/blueprints/large_data_downsampled/cxx11/` | `reader_downsampled.cxx.template` (TIME_BASED_FILTER via QoS on reader). |

### Deliverables
- 13 blueprint directories populated (~33 template files + 7 READMEs)
- Each template uses `{{VARIABLE}}` tokens matching manifest schema
- FlatData blueprint uses builder/loan API, not standard write()

### Validation
- C++ templates compile conceptually against wrapper headers in `dds/utils/cxx11/`
- Python templates follow the same logic separation (main vs logic module)
- Each blueprint's README maps to the pattern table in [docs/07](docs/07_patterns_reference.md)

---

## Phase R5: Test Infrastructure

**Goal:** Create the test helpers, conftest template, and directory structure so that generated tests can run.

**Depends on:** Nothing (parallel with R1-R4)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R5.1 | Create test directory structure | `tests/`, `tests/helpers/`, `tests/test_results/` | Directories + `.gitkeep` |
| R5.2 | Create process launcher helper | `tests/helpers/process_launcher.py` | Subprocess management for integration tests: start process, wait for discovery, send signal, capture output, cleanup. |
| R5.3 | Create DDS fixtures helper | `tests/helpers/dds_fixtures.py` | Shared pytest fixtures: `dds_participant(domain_id=100)`, `dds_reader(topic, type)`, `dds_writer(topic, type)` |
| R5.4 | Create assertion utilities | `tests/helpers/assertion_utils.py` | `wait_for_data(reader, timeout)`, `verify_rate(reader, expected_hz, tolerance)`, `verify_fields(sample, expected)` |
| R5.5 | Create conftest template | `tests/conftest.py.template` | Pytest conftest with domain isolation, auto-discovery of type support, parametrized fixtures |
| R5.6 | Create unit test template | `system_templates/test_templates/test_unit.py.template` | Per-I/O unit test template: create writer/reader, write sample, verify receipt. Uses `{{TOPIC_NAME}}`, `{{TYPE_MODULE}}`, `{{TYPE_NAME}}` |
| R5.7 | Create integration test template | `system_templates/test_templates/test_integration.py.template` | Per-process e2e test: launch subprocess, publish stimuli, subscribe to outputs, verify, shutdown |

### Deliverables
- 3 helper Python modules
- 2 test templates
- 1 conftest template
- Test directory structure

### Validation
- Helper modules import without errors in the connext_dds_env virtualenv
- Templates produce valid pytest files when variables are substituted

---

## Phase R6: Sub-Prompt Files

**Goal:** Create the 4 specialized sub-prompts that `the workflow` loads contextually. These are the "expertise modules" for type definition, pattern selection, code generation, and testing.

**Depends on:** R2 (patterns.prompt.md references QoS profiles), R4 (builder.prompt.md references blueprints)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R6.1 | Create datamodel sub-prompt | `.github/prompts/datamodel.prompt.md` | Type definition specialist. Mandatory type gate (Define New / Select Existing), field-by-field walkthrough, IDL preview. MCP tools: `ask_connext_question`, `search_type_library`. Full spec in [docs/11](docs/11_sub_prompts.md) § datamodel. |
| R6.2 | Create patterns sub-prompt | `.github/prompts/patterns.prompt.md` | Pattern & QoS specialist. Auto-resolve rules, pattern catalog with numbered options, QoS profile mapping, callback assignment. **Must include:** (1) IDL annotation detection: scan type for `@language_binding(FLAT_DATA)` / `@transfer_mode(SHMEM_REF)` to auto-select Large Data option 2 (ZC), (2) cross-language constraint from R0.6: FlatData + Python → force option 1 with warning, (3) `participant_qos_profile` auto-derivation (transport + max data size), (4) `downsample_hz` detection: if subscriber rate < publisher rate → apply TIME_BASED_FILTER modifier. MCP tools: `ask_connext_question`, `search_reference_code`. Full spec in [docs/11](docs/11_sub_prompts.md) § patterns. |
| R6.3 | Create builder sub-prompt | `.github/prompts/builder.prompt.md` | Code generation specialist. Clean architecture enforcement (main.cxx vs logic layer), anti-pattern rules, framework-specific generation, CMake integration. **Must include:** (1) Python import generation rules from R0.5 (IDL module → `from python_gen.X import y`), (2) FlatData detection: if type has `@language_binding(FLAT_DATA)` → use `large_data_zc` blueprint + builder/loan API instead of standard write, (3) `participant_qos_profile` selection from R0.1 auto-derive rules, (4) `downsample_hz` → TIME_BASED_FILTER code injection on reader QoS. MCP tool: `search_reference_code`. Full spec in [docs/11](docs/11_sub_prompts.md) § builder. |
| R6.4 | Create tester sub-prompt | `.github/prompts/tester.prompt.md` | Test generation specialist. Auto-proposal per I/O pattern, pytest fixture usage, integration test subprocess pattern, domain isolation. MCP tool: `search_reference_code`. Full spec in [docs/11](docs/11_sub_prompts.md) § tester. |

### Deliverables
- 4 `.prompt.md` files in `.github/prompts/`
- Each with YAML frontmatter (`mode: agent`, `description`, `tools` list)

### Validation
- Each prompt loads correctly when referenced by `the workflow`
- MCP tool names match the `rti-connext-mcp` server tool names
- Rules match the spec in [docs/11](docs/11_sub_prompts.md)

---

## Phase R7: Orchestrator Prompt Rewrite

**Goal:** Replace the current basic `the workflow entrypoint` (120 lines, framework selector only) with the full five-phase orchestrator. Update `copilot-instructions.md` to match.

**Depends on:** R6 (dispatches to sub-prompts), R1 (reads manifests)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R7.1 | Rewrite the workflow entrypoint | Removed prompt file | Full orchestrator: state detection scan, Phase 0 routing (framework + API + bootstrap), Phase 1 routing (system design), Phase 2 automation (system implementation via manifest), Level 1 menu (Design / Implement / System Design / Done), Level 2a (process picker + modify sub-menu), Level 2b (implement picker), sub-prompt dispatch, direct request handling. Follow spec in [docs/12](docs/12_orchestrator_prompt.md). |
| R7.2 | Update copilot-instructions.md | `.github/copilot-instructions.md` | Update to describe all 5 phases. Point to `the workflow`. Reference `RTI_RAPID_PROTOTYPING.md` and `docs/` for details. |
| R7.3 | Wire sub-prompt loading | In `the workflow entrypoint` | Add explicit instructions for when to load each sub-prompt file (Step 2b → datamodel, Step 2c → patterns, Phase 4 Step 4 → builder, Phase 4 Step 5/7 → tester). |
| R7.4 | Add direct request parsing | In `the workflow entrypoint` | Handle natural language shortcuts: "the workflow add a Button input to gps_tracker" → load YAML → jump to Step 2 → add I/O → offer re-implement. |
| R7.5 | Add phase review & knowledge capture step | In `the workflow entrypoint` + `.github/prompts/phase_review.prompt.md` | At the end of every implementation phase (after Phase 4 completes for a process or batch), the orchestrator automatically triggers a review step. The review: (1) scans `/memories/session/` for design decisions, API observations, workarounds, and QoS reasoning captured during implementation, (2) flags concerns from memory + generated code (QoS tuning, tradeoffs, cross-language issues, fragile assumptions), (3) writes a structured review entry to `knowledge/reviews/<process_name>_<timestamp>.md` with sections: Design Decisions, Concerns, Discoveries, Workarounds, (4) stages `knowledge/` + all generated files and commits with message `[workflow] Phase 4 complete: <process_name> — review captured`, (5) pushes to current branch. **During implementation**, the agent writes observations to session memory in real time — the review step harvests these notes rather than reconstructing reasoning after the fact. The `phase_review.prompt.md` sub-prompt defines the review template and categorization rules. This is a **mandatory, automatic** step — not user-triggered. |

### Deliverables
- Complete orchestrator prompt (~300-400 lines)
- Updated copilot-instructions.md
- `phase_review.prompt.md` sub-prompt for review template & rules
- `knowledge/` directory structure (`knowledge/reviews/`, `knowledge/.gitkeep`)

### Validation
- `the workflow` on fresh workspace → detects no project.yaml → starts Phase 0
- `the workflow` with project.yaml only → starts Phase 1
- `the workflow` with both configs → shows Level 1 menu with correct state summary
- `the workflow design` → jumps to Level 2a
- `the workflow implement` → jumps to Level 2b
- After any process implementation completes → review entry auto-created in `knowledge/reviews/`
- Review commit appears in git log with `[workflow]` prefix

---

## Phase R8: End-to-End Integration Testing

**Goal:** Walk through the complete workflow from scratch and fix issues. This is the first time all artifacts work together.

**Depends on:** R1-R7 (everything)

### Tasks

| # | Task | Description |
|---|------|-------------|
| R8.1 | Fresh workspace test | Invoke `the workflow` on clean workspace. Walk through Phase 0 (pick Wrapper Class + C++11) → Phase 1 (domain 0, failover + health monitoring) → Phase 2 (verify baseline generated). Verify `knowledge/` directory created. |
| R8.2 | Single process design test | Design `gps_tracker`: 1 input (CommandTopic, Command pattern), 1 output (PositionTopic, Status at 2Hz). Verify PROCESS_DESIGN.yaml matches schema. Verify IDL written to `dds/datamodel/idl/gps_types.idl`. |
| R8.3 | Single process implementation test | Implement `gps_tracker`. Verify: scaffold created at correct `destination` paths, rtiddsgen runs, QoS assembled, app code has clean architecture (main.cxx vs logic), tests generated, build succeeds, tests run. **Verify phase review auto-triggers:** `knowledge/reviews/gps_tracker_<ts>.md` created, git commit with `[workflow]` prefix, push succeeds. |
| R8.4 | Second process with type reuse | Design `command_controller` that reuses `gps_types::Command`. Verify type gate correctly offers "Select Existing". Implement and verify shared type support. |
| R8.5 | System design change + sweep | Go back to System Design, add Leader Election. Verify version increments, sweep flags existing processes, re-implementation works. |
| R8.6 | Batch design + implement all | Design 2 processes without implementing. Then "Implement ALL". Verify sequential execution, both pass. |
| R8.7 | Fix broken tests | Intentionally break a test. Return to design, fix, re-implement. Verify the iterate loop works. |
| R8.8 | **Dry-run UC1: Python large data SHMEM** | Walk through the full use case from [docs/14](docs/14_use_case_dry_run.md) UC1: Wrapper Class + Python API → no system patterns → design `large_data_camera` with Image type (Select Existing) → Large Data Option 1 (SHMEM) → verify `participant_qos_profile` auto-derived to `LargeDataSHMEMParticipant` → implement → verify Python imports follow R0.5 rules → verify generated code matches `apps/python/large_data_app/` quality → build and run. |
| R8.9 | **Dry-run UC2: C++ zero-copy + Python viewer** | Walk through [docs/14](docs/14_use_case_dry_run.md) UC2: Wrapper Class + `modern_cpp_python` API → design `image_publisher` (C++, FlatData zero-copy at 10 Hz) + `image_viewer` (Python, downsampled at 1 Hz from same topic) → verify FlatData constraint auto-downgrades Python to Option 1 → verify `downsample_hz: 1` produces TIME_BASED_FILTER QoS → verify FlatData blueprint used for C++ (builder/loan pattern) → implement both → cross-language pub/sub works. |
| R8.10 | **DDSWriterSetup FlatData support** | Verify whether `DDSWriterSetup<T>` supports FlatData `get_loan()` / builder pattern. If not, either: (a) add `get_loan()` method to `DDSWriterSetup`, or (b) add `DDSFlatDataWriterSetup<T>` variant in `dds/utils/cxx11/`, or (c) document that FlatData apps bypass the wrapper and use raw DDS API. The builder prompt (R6.3) must know which path to take. |

### Deliverables
- Working end-to-end workflow
- Bug fixes from integration testing
- Verified Phase 0→1→2→3→4 pipeline
- Both README use cases from [docs/14](docs/14_use_case_dry_run.md) pass end-to-end
- FlatData wrapper class decision documented and implemented (R8.10)

### Validation
- All 10 test scenarios complete without manual intervention (beyond user choices)
- Generated code compiles and runs
- Generated tests pass
- R8.8: Python large data app publishes/receives 900 KB images over SHMEM
- R8.9: C++ FlatData publisher + Python downsampled subscriber interoperate
- R8.10: FlatData code generation path confirmed and documented
- Phase review auto-triggers after every implementation, producing `knowledge/reviews/` entries and auto-commits

---

## Phase R9: Internal MCP Server — Build & Deploy

**Goal:** Build and deploy the `rti-connext-mcp` internal MCP server with its 3 core tools. This is the knowledge backbone — sub-prompts query it instead of relying on agent context alone.

**Depends on:** R8 (need working workflow to test MCP integration)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R9.1 | Design MCP server architecture | `mcp-server/README.md` | Choose runtime (Node.js or Python). Define tool schemas (input/output JSON). Define RAG index strategy (what gets indexed, chunk size, embedding model). |
| R9.2 | Implement `ask_connext_question` tool | `mcp-server/tools/ask_connext_question.{ts,py}` | RAG over RTI documentation. Input: `question` (string). Output: relevant doc chunks with source references. Index: RTI Connext user manuals, API docs, IDL reference, transport config guides. |
| R9.3 | Implement `search_reference_code` tool | `mcp-server/tools/search_reference_code.{ts,py}` | Search local reference code in this repo. Input: `query` (string), `scope` (optional: "apps", "wrappers", "qos", "templates", "tests"). Output: matching code snippets with file paths. Index: `apps/`, `dds/utils/`, `dds/qos/`, `system_templates/`, `tests/`. |
| R9.4 | Implement `search_type_library` tool | `mcp-server/tools/search_type_library.{ts,py}` | Search reference IDL type definitions. Input: `pattern` (string, e.g. "Command", "Status", "Health"). Output: matching IDL struct definitions with module, fields, annotations. Index: `dds/datamodel/idl/`, `system_templates/system_patterns/`, community type libraries. |
| R9.5 | Build RAG indexing pipeline | `mcp-server/indexer/` | Script to build/rebuild the vector index. Sources: RTI docs (local copy or fetched), workspace code, IDL files. Output: persistent index in `mcp-server/data/`. |
| R9.6 | Create MCP server entry point | `mcp-server/server.{ts,py}` | MCP protocol handler: register tools, handle `tools/call` requests, return structured responses. |
| R9.7 | Create VS Code MCP config | `.vscode/mcp.json` | Register `rti-connext-mcp` server with VS Code. Point to server entry point. Configure stdio transport. |
| R9.8 | Create MCP server tests | `mcp-server/tests/` | Unit tests for each tool. Verify: correct responses for known queries, graceful handling of empty results, index rebuild works. |

### Deliverables
- Complete MCP server with 3 tools
- RAG index pipeline
- VS Code MCP configuration
- Test suite

### Validation
- `ask_connext_question("What is the @key annotation?")` returns relevant IDL documentation
- `search_reference_code("DDSParticipantSetup")` returns wrapper header content
- `search_type_library("Command")` returns Command struct IDL definitions
- Server starts and responds via MCP protocol in VS Code

---

## Phase R10: MCP Tool Expansion

**Goal:** Add the "future tools" documented in the architecture — `validate_idl`, `check_qos_conflicts`, `validate_process_design`, `list_workspace_types`. These move validation logic from sub-prompt instructions into deterministic server-side checks.

**Depends on:** R9 (MCP server exists)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R10.1 | Implement `validate_idl` tool | `mcp-server/tools/validate_idl.{ts,py}` | Validate IDL files against rules: bounded strings (`string<N>`), `@key` present, naming conventions (PascalCase structs, snake_case fields, lowercase modules). Input: IDL file path or content. Output: list of violations with line numbers. |
| R10.2 | Implement `check_qos_conflicts` tool | `mcp-server/tools/check_qos_conflicts.{ts,py}` | Detect incompatible QoS combinations: BEST_EFFORT writer + RELIABLE reader, mismatched deadlines, conflicting ownership. Input: reader QoS profile + writer QoS profile. Output: list of conflicts with explanations. |
| R10.3 | Implement `validate_process_design` tool | `mcp-server/tools/validate_process_design.{ts,py}` | Validate PROCESS_DESIGN.yaml against the schema in [docs/05](docs/05_phase_3_process_design.md). Input: YAML file path. Output: schema violations, missing required fields, invalid references. |
| R10.4 | Implement `list_workspace_types` tool | `mcp-server/tools/list_workspace_types.{ts,py}` | Return all IDL types in workspace with metadata. Input: none (scans workspace). Output: list of `{module, type_name, key_fields, used_by_processes[], file_path}`. |
| R10.5 | Wire validation tools into sub-prompts | Update `.github/prompts/*.prompt.md` | datamodel.prompt.md calls `validate_idl` after type definition. patterns.prompt.md calls `check_qos_conflicts` after pairing reader/writer profiles. |
| R10.6 | Wire design validation into orchestrator | Update `the workflow entrypoint` | Phase 3 Step 4 (Review) calls `validate_process_design` before saving. Phase 3 Step 2b calls `list_workspace_types` for the "Select Existing" flow. |

### Deliverables
- 4 new MCP tools
- Updated sub-prompts and orchestrator to use them
- Tests for each tool

### Validation
- `validate_idl` catches: unbounded string, missing @key, wrong naming
- `check_qos_conflicts` catches: reliability mismatch, deadline mismatch
- `validate_process_design` catches: missing required fields, invalid pattern names
- `list_workspace_types` returns correct inventory after IDL changes

---

## Phase R11: Migrate Agent Tool Calls to MCP Server

**Goal:** Move operations currently done via VS Code agent tools (`run_in_terminal`, `create_file`, `read_file`) into deterministic MCP server tools. This makes the workflow reproducible, testable, and independent of the agent's tool implementation.

**Depends on:** R9-R10 (MCP server with validation tools)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R11.1 | Implement `scaffold_process` tool | `mcp-server/tools/scaffold_process.{ts,py}` | Reads manifest YAML + design YAML → creates all scaffold files with variable substitution → returns list of created files. Replaces agent's manual read-template → substitute → create_file loop. |
| R11.2 | Implement `run_rtiddsgen` tool | `mcp-server/tools/run_rtiddsgen.{ts,py}` | Runs rtiddsgen with correct flags from project.yaml. Input: IDL file path(s). Output: generated file list + stdout/stderr. Replaces agent's manual `run_in_terminal(rtiddsgen ...)`. |
| R11.3 | Implement `assemble_qos` tool | `mcp-server/tools/assemble_qos.{ts,py}` | Reads design YAML for QoS profile refs → copies/merges QoS fragment files → updates registry. Input: process name. Output: list of QoS files created/updated. |
| R11.4 | Implement `build_process` tool | `mcp-server/tools/build_process.{ts,py}` | Runs cmake/pip/maven based on project.yaml. Input: process name, config (Debug/Release). Output: build stdout/stderr + success/failure. |
| R11.5 | Implement `run_tests` tool | `mcp-server/tools/run_tests.{ts,py}` | Runs pytest for a process. Input: process name, test type (unit/integration/all). Output: test results (pass/fail per test, stdout, JUnit XML path). |
| R11.6 | Implement `generate_tests` tool | `mcp-server/tools/generate_tests.{ts,py}` | Reads design YAML → generates pytest files from templates. Input: process name. Output: list of test files created. |
| R11.7 | Update orchestrator for MCP tools | Update `the workflow entrypoint` | Phase 4 steps 1-3, 5-7 now call MCP tools instead of manual agent sequences. Step 4 (app code) remains agent-driven (creative work). |
| R11.8 | Update sub-prompts for MCP tools | Update `.github/prompts/builder.prompt.md`, `tester.prompt.md` | builder calls `scaffold_process`, `run_rtiddsgen`, `build_process`. tester calls `generate_tests`, `run_tests`. |

### Deliverables
- 6 new MCP server tools (scaffold, rtiddsgen, assemble_qos, build, run_tests, generate_tests)
- Updated orchestrator and sub-prompts
- Only Phase 4 Step 4 (app code generation) remains as agent-driven creative work

### Validation
- `scaffold_process("gps_tracker")` creates all expected files matching manifest
- `run_rtiddsgen("dds/datamodel/idl/gps_types.idl")` generates type support
- `build_process("gps_tracker", "Debug")` compiles successfully
- `run_tests("gps_tracker", "all")` returns structured test results
- Full end-to-end workflow works with MCP tools instead of manual agent steps

---

## Phase R12: Bootstrap & Self-Hosting

**Goal:** Implement the Phase 0 bootstrap that fetches reference content from GitHub into local template slots, and the MCP re-indexing that follows. After this phase, the system is fully self-contained.

**Depends on:** R9-R11 (MCP server with all tools)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R12.1 | Implement `bootstrap_references` tool | `mcp-server/tools/bootstrap_references.{ts,py}` | Reads `reference_manifest.yaml`. For each empty template slot, fetches content from the configured GitHub source (using GitHub API, not MCP). Writes to local `system_templates/` paths. Tracks what was fetched (checksum, timestamp). |
| R12.2 | Implement `rebuild_index` tool | `mcp-server/tools/rebuild_index.{ts,py}` | Triggers a full re-index of the RAG pipeline. Called after bootstrap or when workspace content changes significantly. Input: optional scope (all, code, docs, types). Output: index stats (documents indexed, chunks created). |
| R12.3 | Wire bootstrap into Phase 0 | Update `the workflow entrypoint` | After framework selection, before creating project.yaml: call `bootstrap_references` → then `rebuild_index`. Show progress to user. |
| R12.4 | Add bootstrap re-entry guard | In `the workflow entrypoint` | If `reference_manifest.yaml` shows all slots filled (checksums present), skip bootstrap. Offer "Re-bootstrap?" only if user explicitly requests or manifest version changes. |
| R12.5 | Create bootstrap test | `mcp-server/tests/test_bootstrap.py` | Mock GitHub API. Verify: correct files fetched, written to correct paths, manifest updated with checksums, re-index triggered. |

### Deliverables
- Bootstrap tool + re-index tool
- Self-contained system (no GitHub access needed after Phase 0)
- Updated orchestrator with bootstrap integration

### Validation
- Fresh workspace: `the workflow` → Phase 0 → bootstrap fetches reference content → indexes it
- Second invocation: bootstrap skips (all slots filled)
- `search_reference_code` returns results from bootstrapped content
- `search_type_library` returns results from bootstrapped type libraries

---

## Execution Order & Dependencies

```
R0: Schema Fixes ─────────────────┐  (blocks R1, R6, R7)
                                  │
                                  ▼
R1: Manifests ─────────────────┐  │
R2: QoS Fragments ─────────┐  │  │
R5: Test Infrastructure ──┐ │  │  │
                          │ │  │  │
R3: System Patterns ◄─────┼─┘  │  │  (R3 depends on R2)
R4: Blueprints ◄──────────┼────┘  │  (R4 depends on R1, R0)
                          │       │
R6: Sub-Prompts ◄─────────┼───────┘  (R6 depends on R2, R4, R0)
                          │
R7: Orchestrator ◄────────┼──────  (R7 depends on R6, R1, R0)
                          │
R8: Integration Test ◄────┴──────  (R8 depends on everything above)
                          │
R9: MCP Server Core ◄─────┘       (R9 depends on R8)
                          │
R10: MCP Validation Tools ◄──     (R10 depends on R9)
                          │
R11: Migrate to MCP Tools ◄──    (R11 depends on R9, R10)
                          │
R12: Bootstrap & Self-Host ◄──   (R12 depends on R11)
```

**Parallelism:**
- **R0** runs first (schema fixes, doc updates only — fast)
- **R1 + R2 + R5** can all start immediately after R0
- **R3 + R4** can run in parallel after R2/R1 respectively
- **R6 → R7 → R8** are sequential
- **R9 → R10 → R11 → R12** are sequential (MCP build-out)

---

## Artifact Count by Phase

| Phase | New Files | Est. Lines | Focus |
|-------|-----------|------------|-------|
| R0: Schema Fixes | 0 new files (doc edits only) | ~200 edits | Schema & doc corrections |
| R1: Manifests | 5 manifests + validation | ~450 | Configuration |
| R2: QoS Fragments | 12 XML fragments | ~600 | QoS policies |
| R3: System Patterns | ~16 files (IDL + snippets + READMEs) | ~500 | System patterns |
| R4: Blueprints | ~33 templates + 7 READMEs | ~1100 | Code templates |
| R5: Test Infrastructure | 7 files (helpers + templates) | ~400 | Testing |
| R6: Sub-Prompts | 4 prompt files | ~1000 | Agent expertise |
| R7: Orchestrator | 3 prompt files (rewrite + phase_review) | ~600 | Agent orchestration + phase review |
| R8: Integration Test | 0 new files (testing pass) | — | Verification |
| R9: MCP Server Core | ~10 files (server + tools + indexer + config) | ~1500 | MCP server |
| R10: MCP Validation | 4 tool files + tests | ~600 | Validation tools |
| R11: Migrate to MCP | 6 tool files + prompt updates | ~1200 | Tool migration |
| R12: Bootstrap | 3 files (tools + tests) | ~400 | Self-hosting |
| **Total** | **~105 files** | **~8,450 lines** | |

---

## Phase Milestones

| Milestone | After Phase | What Works |
|-----------|-------------|------------|
| **M0: Schemas Corrected** | R0 | `participant_qos_profile`, per-process `language`, `downsample_hz`, FlatData constraints, Python import rules — all documented. Downstream phases build against a stable, validated contract. |
| **M1: Templates Ready** | R4 | All template slots populated including FlatData ZC and downsampled blueprints. Agent can manually read templates and generate code. |
| **M2: Prompts Complete** | R7 | `the workflow` orchestrates the full 5-phase workflow with sub-prompt dispatch. Prompts encode FlatData detection, cross-language constraints, participant QoS derivation. Phase review auto-captures concerns and commits after every implementation. |
| **M3: End-to-End Verified** | R8 | Both dry-run use cases pass: Python SHMEM large data + C++ zero-copy with Python downsampled viewer. |
| **M4: MCP Knowledge** | R9 | Sub-prompts query MCP for documentation, reference code, and type libraries. |
| **M5: MCP Validation** | R10 | Automated validation of IDL, QoS conflicts, and process designs. |
| **M6: MCP Operations** | R11 | Scaffold, build, test operations run via MCP tools. Agent focuses on creative work only. |
| **M7: Self-Contained** | R12 | Bootstrap fetches references. No external dependencies after Phase 0. |
