# Rules

All rules that govern the system. Sub-prompts, implementation scripts, and the orchestrator all follow these rules. This is the canonical reference — if a rule appears here but contradicts something elsewhere, this section wins.

A concise version of these rules is also loaded via `.github/copilot-instructions.md` on every invocation.

## IDL / Data Type Rules

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

## Naming Conventions

| ID | Rule | Example |
|----|------|---------|
| NAME-1 | Module names = `snake_case` | `gps_types`, `system_patterns` |
| NAME-2 | Struct/enum names = `PascalCase` | `Position`, `CommandAction` |
| NAME-3 | Field names = `snake_case` | `device_id`, `cpu_percent` |
| NAME-4 | Process names = valid C identifier (no spaces, starts with letter) | `gps_tracker` |
| NAME-5 | Topic names = `PascalCase` + "Topic" suffix | `PositionTopic`, `CommandTopic` |
| NAME-6 | Unit test files = `test_<io_name>.py` | `test_position_publish.py` |
| NAME-7 | Integration test files = `test_<process_name>_e2e.py` | `test_gps_tracker_e2e.py` |

## Architecture Rules (Clean Separation)

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

## Workflow Rules

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

## Schema Validation Rules

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

## Implementation Rules

| ID | Rule | Severity |
|----|------|----------|
| IMPL-1 | Implementation is fully automatic — no user interaction after "Implement Now" | **MUST** |
| IMPL-2 | Scripts run in order (Steps 1→7), stopping on first non-zero exit code | **MUST** |
| IMPL-3 | Step 4 (app code generation) is the ONLY agent-driven step — all others are scripts | **MUST** |
| IMPL-4 | All scripts are idempotent — re-running skips existing files (use `--force` to overwrite) | **MUST** |
| IMPL-5 | `rtiddsgen` always uses `-replace` flag | **MUST** |
| IMPL-6 | `system_templates/` is read-only — NEVER modify template files | **NEVER** |

## Code Convention Rules

| ID | Rule |
|----|------|
| CODE-1 | Use `application.hpp` for signal handling and app config struct |
| CODE-2 | Process command-line args: `--domain`, `--qos-file`, `--verbose` |
| CODE-3 | Return codes: 0 = success, 1 = error |
| CODE-4 | Always call `participant.finalize()` before exit |
| CODE-5 | CMake minimum version: 3.11 |
| CODE-6 | Source files in CMakeLists.txt: `main.cxx`, `<process_name>_logic.cxx` |

## Test Rules

| ID | Rule |
|----|------|
| TEST-1 | Use isolated domain (`domain_id=100`) in test fixtures |
| TEST-2 | Timeout: 10s max per unit test |
| TEST-3 | Cleanup: dispose all DDS entities in fixture teardown |
| TEST-4 | Integration tests: wait 5s for discovery before asserting |
| TEST-5 | At least one integration (end-to-end) test per process (recommended) |

## MCP / Tool Usage Rules

| ID | Rule | Severity |
|----|------|----------|
| MCP-1 | Before defining any type: (1) query internal MCP `search_type_library` for reference types, (2) query internal MCP `ask_connext_question` for IDL syntax, (3) scan workspace IDL, (4) scan other process YAMLs | **MUST** |
| MCP-2 | `/rti_dev` does NOT query MCP directly — loads the appropriate sub-prompt which contains MCP instructions | **MUST** |
| MCP-3 | The user NEVER needs to know sub-prompts exist — `/rti_dev` is the only visible prompt | **NEVER** expose |
| MCP-4 | GitHub MCP (`github_repo`) is used ONLY during Phase 0 bootstrap to fetch reference content. After bootstrap, all queries go through the internal MCP server. | **MUST** |
| MCP-5 | Internal MCP server (`rti-connext-mcp`) is the single knowledge layer for Phases 1–4. Three tools: `ask_connext_question` (docs RAG), `search_reference_code` (starter kit examples), `search_type_library` (IDL type references). | **MUST** |

## Auto-Resolve Rules (Pattern Selection)

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
