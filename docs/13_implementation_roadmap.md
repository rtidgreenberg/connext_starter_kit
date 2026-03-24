# Implementation Roadmap

Phased build plan for the DDS Process Builder — from empty template slots to a fully operational `/rti_dev` workflow backed by an internal MCP server. Each phase produces testable deliverables. Phases are ordered by dependency; independent phases can run in parallel.

---

## Current State (Baseline Audit)

### Exists and Complete

| Artifact | Path | Notes |
|----------|------|-------|
| Architecture docs | `DDS_PROCESS_BUILDER.md` + `docs/01-12` | 12 split docs + summary |
| Orchestrator prompt | `.github/prompts/rti_dev.prompt.md` | Basic — state detection + framework selector, needs full rewrite |
| Framework selector prompt | `.github/prompts/framework_selector.prompt.md` | Exists |
| Wrapper classes prompt | `.github/prompts/wrapper_classes.prompt.md` | Exists |
| Build C++ prompt | `.github/prompts/build_cxx.prompt.md` | Exists |
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
| System pattern dirs | `system_templates/system_patterns/{failover,health_monitoring,leader_election,redundant_publisher,request_reply}/` | IDL templates, QoS fragments, logic snippets |

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

## Phase R1: Planning Artifacts & Manifest Files

**Goal:** Manifest-driven scaffold is the core mechanic. Create the manifest YAML files that tell the agent what to create, where to source it, and where to write it. Validate that the planning YAML examples match the current architecture docs.

**Depends on:** Nothing (start here)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R1.1 | Create wrapper class manifest | `system_templates/wrapper_class/manifest.yaml` | Map each scaffold template → `filename`, `destination`, `source`, `template` path. Include `build_integration` for top-level CMakeLists. Follow schema from [docs/09](docs/09_repository_structure.md). |
| R1.2 | Create XML app creation manifest | `system_templates/xml_app_creation/manifest.yaml` | Same structure for XML App Creation scaffold files. Include XML library files. |
| R1.3 | Create Python manifest | `system_templates/python/manifest.yaml` | Same structure for Python scaffold. `pip` build integration instead of CMake. |
| R1.4 | Create system manifest | `system_templates/system_manifest.yaml` | Phase 2 baseline: directories to create, files to verify, system IDL/QoS to generate. Follow schema from [docs/04](docs/04_phase_2_system_impl.md). |
| R1.5 | Create reference manifest | `system_templates/reference_manifest.yaml` | Phase 0 bootstrap: maps empty template slots (blueprints, qos_templates, system_patterns) to GitHub source repos. |
| R1.6 | Validate planning YAMLs | `planning/*.yaml.example` | Verify `project.yaml.example` and `system_config.yaml.example` match current schemas in [docs/02](docs/02_phase_0_project_init.md) and [docs/03](docs/03_phase_1_system_design.md). Update if needed. |
| R1.7 | Validate process design YAMLs | `planning/processes/*.yaml.example` | Verify `gps_tracker.yaml.example` and `command_controller.yaml.example` match current PROCESS_DESIGN.yaml schema in [docs/05](docs/05_phase_3_process_design.md). Update if needed. |

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

**Goal:** Populate the empty `system_patterns/` directories. Each system pattern needs: an IDL template (type definitions), a logic snippet (how a process implements the pattern), and references to the QoS fragment from R2.

**Depends on:** R2 (references QoS profile names)

### Tasks

| # | Task | Artifact(s) | Description |
|---|------|-------------|-------------|
| R3.1 | Create system patterns IDL template | `system_templates/system_patterns/system_patterns.idl.template` | Combined IDL with all system pattern types: `ProcessRole` enum, `HeartbeatStatus`, `HealthStatus`, `LeaderBid`, `ServiceRequest`/`ServiceReply`. Gated by `{{PATTERN_*}}` conditionals. |
| R3.2 | Create failover pattern files | `system_templates/system_patterns/failover/` | `heartbeat_writer.cxx.snippet` (PRIMARY publishes heartbeat), `heartbeat_reader.cxx.snippet` (STANDBY monitors liveliness), `README.md` (pattern description, QoS rationale, opt-in behavior). |
| R3.3 | Create health monitoring files | `system_templates/system_patterns/health_monitoring/` | `health_publisher.cxx.snippet` (publish ProcessHealth at 1Hz), `health_subscriber.cxx.snippet` (monitor all processes), `README.md`. |
| R3.4 | Create leader election files | `system_templates/system_patterns/leader_election/` | `leader_bid_writer.cxx.snippet`, `leader_monitor.cxx.snippet`, `README.md`. |
| R3.5 | Create request-reply files | `system_templates/system_patterns/request_reply/` | `service_server.cxx.snippet`, `service_client.cxx.snippet`, `README.md`. |
| R3.6 | Create redundant publisher files | `system_templates/system_patterns/redundant_publisher/` | `redundant_writer.cxx.snippet` (EXCLUSIVE ownership with configurable strength), `README.md`. |

### Deliverables
- 1 combined system IDL template
- 5 pattern directories populated with snippets + READMEs (~15 files)

### Validation
- IDL template compiles with `rtiddsgen -ppDisable` when all conditionals are enabled
- Each snippet references correct QoS profile names from R2
- README describes when/how the pattern is opt-in per [docs/07](docs/07_patterns_reference.md)

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

### Deliverables
- 10 blueprint directories populated (~25 template files + 5 READMEs)
- Each template uses `{{VARIABLE}}` tokens matching manifest schema

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

**Goal:** Create the 4 specialized sub-prompts that `/rti_dev` loads contextually. These are the "expertise modules" for type definition, pattern selection, code generation, and testing.

**Depends on:** R2 (patterns.prompt.md references QoS profiles), R4 (builder.prompt.md references blueprints)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R6.1 | Create datamodel sub-prompt | `.github/prompts/datamodel.prompt.md` | Type definition specialist. Mandatory type gate (Define New / Select Existing), field-by-field walkthrough, IDL preview. MCP tools: `ask_connext_question`, `search_type_library`. Full spec in [docs/11](docs/11_sub_prompts.md) § datamodel. |
| R6.2 | Create patterns sub-prompt | `.github/prompts/patterns.prompt.md` | Pattern & QoS specialist. Auto-resolve rules, pattern catalog with numbered options, QoS profile mapping, callback assignment. MCP tools: `ask_connext_question`, `search_reference_code`. Full spec in [docs/11](docs/11_sub_prompts.md) § patterns. |
| R6.3 | Create builder sub-prompt | `.github/prompts/builder.prompt.md` | Code generation specialist. Clean architecture enforcement (main.cxx vs logic layer), anti-pattern rules, framework-specific generation, CMake integration. MCP tool: `search_reference_code`. Full spec in [docs/11](docs/11_sub_prompts.md) § builder. |
| R6.4 | Create tester sub-prompt | `.github/prompts/tester.prompt.md` | Test generation specialist. Auto-proposal per I/O pattern, pytest fixture usage, integration test subprocess pattern, domain isolation. MCP tool: `search_reference_code`. Full spec in [docs/11](docs/11_sub_prompts.md) § tester. |

### Deliverables
- 4 `.prompt.md` files in `.github/prompts/`
- Each with YAML frontmatter (`mode: agent`, `description`, `tools` list)

### Validation
- Each prompt loads correctly when referenced by `/rti_dev`
- MCP tool names match the `rti-connext-mcp` server tool names
- Rules match the spec in [docs/11](docs/11_sub_prompts.md)

---

## Phase R7: Orchestrator Prompt Rewrite

**Goal:** Replace the current basic `rti_dev.prompt.md` (120 lines, framework selector only) with the full five-phase orchestrator. Update `copilot-instructions.md` to match.

**Depends on:** R6 (dispatches to sub-prompts), R1 (reads manifests)

### Tasks

| # | Task | Artifact | Description |
|---|------|----------|-------------|
| R7.1 | Rewrite rti_dev.prompt.md | `.github/prompts/rti_dev.prompt.md` | Full orchestrator: state detection scan, Phase 0 routing (framework + API + bootstrap), Phase 1 routing (system design), Phase 2 automation (system implementation via manifest), Level 1 menu (Design / Implement / System Design / Done), Level 2a (process picker + modify sub-menu), Level 2b (implement picker), sub-prompt dispatch, direct request handling. Follow spec in [docs/12](docs/12_orchestrator_prompt.md). |
| R7.2 | Update copilot-instructions.md | `.github/copilot-instructions.md` | Update to describe all 5 phases. Point to `/rti_dev`. Reference `DDS_PROCESS_BUILDER.md` and `docs/` for details. |
| R7.3 | Wire sub-prompt loading | In `rti_dev.prompt.md` | Add explicit instructions for when to load each sub-prompt file (Step 2b → datamodel, Step 2c → patterns, Phase 4 Step 4 → builder, Phase 4 Step 5/7 → tester). |
| R7.4 | Add direct request parsing | In `rti_dev.prompt.md` | Handle natural language shortcuts: "/rti_dev add a Button input to gps_tracker" → load YAML → jump to Step 2 → add I/O → offer re-implement. |

### Deliverables
- Complete orchestrator prompt (~300-400 lines)
- Updated copilot-instructions.md

### Validation
- `/rti_dev` on fresh workspace → detects no project.yaml → starts Phase 0
- `/rti_dev` with project.yaml only → starts Phase 1
- `/rti_dev` with both configs → shows Level 1 menu with correct state summary
- `/rti_dev design` → jumps to Level 2a
- `/rti_dev implement` → jumps to Level 2b

---

## Phase R8: End-to-End Integration Testing

**Goal:** Walk through the complete workflow from scratch and fix issues. This is the first time all artifacts work together.

**Depends on:** R1-R7 (everything)

### Tasks

| # | Task | Description |
|---|------|-------------|
| R8.1 | Fresh workspace test | Invoke `/rti_dev` on clean workspace. Walk through Phase 0 (pick Wrapper Class + C++11) → Phase 1 (domain 0, failover + health monitoring) → Phase 2 (verify baseline generated). |
| R8.2 | Single process design test | Design `gps_tracker`: 1 input (CommandTopic, Command pattern), 1 output (PositionTopic, Status at 2Hz). Verify PROCESS_DESIGN.yaml matches schema. Verify IDL written to `dds/datamodel/idl/gps_types.idl`. |
| R8.3 | Single process implementation test | Implement `gps_tracker`. Verify: scaffold created at correct `destination` paths, rtiddsgen runs, QoS assembled, app code has clean architecture (main.cxx vs logic), tests generated, build succeeds, tests run. |
| R8.4 | Second process with type reuse | Design `command_controller` that reuses `gps_types::Command`. Verify type gate correctly offers "Select Existing". Implement and verify shared type support. |
| R8.5 | System design change + sweep | Go back to System Design, add Leader Election. Verify version increments, sweep flags existing processes, re-implementation works. |
| R8.6 | Batch design + implement all | Design 2 processes without implementing. Then "Implement ALL". Verify sequential execution, both pass. |
| R8.7 | Fix broken tests | Intentionally break a test. Return to design, fix, re-implement. Verify the iterate loop works. |

### Deliverables
- Working end-to-end workflow
- Bug fixes from integration testing
- Verified Phase 0→1→2→3→4 pipeline

### Validation
- All 7 test scenarios complete without manual intervention (beyond user choices)
- Generated code compiles and runs
- Generated tests pass

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
| R10.6 | Wire design validation into orchestrator | Update `rti_dev.prompt.md` | Phase 3 Step 4 (Review) calls `validate_process_design` before saving. Phase 3 Step 2b calls `list_workspace_types` for the "Select Existing" flow. |

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
| R11.7 | Update orchestrator for MCP tools | Update `rti_dev.prompt.md` | Phase 4 steps 1-3, 5-7 now call MCP tools instead of manual agent sequences. Step 4 (app code) remains agent-driven (creative work). |
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
| R12.3 | Wire bootstrap into Phase 0 | Update `rti_dev.prompt.md` | After framework selection, before creating project.yaml: call `bootstrap_references` → then `rebuild_index`. Show progress to user. |
| R12.4 | Add bootstrap re-entry guard | In `rti_dev.prompt.md` | If `reference_manifest.yaml` shows all slots filled (checksums present), skip bootstrap. Offer "Re-bootstrap?" only if user explicitly requests or manifest version changes. |
| R12.5 | Create bootstrap test | `mcp-server/tests/test_bootstrap.py` | Mock GitHub API. Verify: correct files fetched, written to correct paths, manifest updated with checksums, re-index triggered. |

### Deliverables
- Bootstrap tool + re-index tool
- Self-contained system (no GitHub access needed after Phase 0)
- Updated orchestrator with bootstrap integration

### Validation
- Fresh workspace: `/rti_dev` → Phase 0 → bootstrap fetches reference content → indexes it
- Second invocation: bootstrap skips (all slots filled)
- `search_reference_code` returns results from bootstrapped content
- `search_type_library` returns results from bootstrapped type libraries

---

## Execution Order & Dependencies

```
R1: Manifests ─────────────────┐
R2: QoS Fragments ─────────┐  │
R5: Test Infrastructure ──┐ │  │
                          │ │  │
R3: System Patterns ◄─────┼─┘  │  (R3 depends on R2)
R4: Blueprints ◄──────────┼────┘  (R4 depends on R1)
                          │
R6: Sub-Prompts ◄─────────┼──────  (R6 depends on R2, R4)
                          │
R7: Orchestrator ◄────────┼──────  (R7 depends on R6, R1)
                          │
R8: Integration Test ◄────┴──────  (R8 depends on everything above)
                          │
R9: MCP Server Core ◄─────┘       (R9 depends on R8 — need working workflow)
                          │
R10: MCP Validation Tools ◄──     (R10 depends on R9)
                          │
R11: Migrate to MCP Tools ◄──    (R11 depends on R9, R10)
                          │
R12: Bootstrap & Self-Host ◄──   (R12 depends on R11)
```

**Parallelism:**
- **R1 + R2 + R5** can all start immediately (no dependencies)
- **R3 + R4** can run in parallel after R2/R1 respectively
- **R6 → R7 → R8** are sequential
- **R9 → R10 → R11 → R12** are sequential (MCP build-out)

---

## Artifact Count by Phase

| Phase | New Files | Est. Lines | Focus |
|-------|-----------|------------|-------|
| R1: Manifests | 5 manifests + validation | ~400 | Configuration |
| R2: QoS Fragments | 12 XML fragments | ~600 | QoS policies |
| R3: System Patterns | ~16 files (IDL + snippets + READMEs) | ~500 | System patterns |
| R4: Blueprints | ~25 templates + 5 READMEs | ~800 | Code templates |
| R5: Test Infrastructure | 7 files (helpers + templates) | ~400 | Testing |
| R6: Sub-Prompts | 4 prompt files | ~800 | Agent expertise |
| R7: Orchestrator | 2 prompt files (rewrite) | ~500 | Agent orchestration |
| R8: Integration Test | 0 new files (testing pass) | — | Verification |
| R9: MCP Server Core | ~10 files (server + tools + indexer + config) | ~1500 | MCP server |
| R10: MCP Validation | 4 tool files + tests | ~600 | Validation tools |
| R11: Migrate to MCP | 6 tool files + prompt updates | ~1200 | Tool migration |
| R12: Bootstrap | 3 files (tools + tests) | ~400 | Self-hosting |
| **Total** | **~95 files** | **~7,700 lines** | |

---

## Phase Milestones

| Milestone | After Phase | What Works |
|-----------|-------------|------------|
| **M1: Templates Ready** | R4 | All template slots populated. Agent can manually read templates and generate code. |
| **M2: Prompts Complete** | R7 | `/rti_dev` orchestrates the full 5-phase workflow with sub-prompt dispatch. |
| **M3: End-to-End Verified** | R8 | Complete workflow tested: init → design → implement → test. |
| **M4: MCP Knowledge** | R9 | Sub-prompts query MCP for documentation, reference code, and type libraries. |
| **M5: MCP Validation** | R10 | Automated validation of IDL, QoS conflicts, and process designs. |
| **M6: MCP Operations** | R11 | Scaffold, build, test operations run via MCP tools. Agent focuses on creative work only. |
| **M7: Self-Contained** | R12 | Bootstrap fetches references. No external dependencies after Phase 0. |
