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
  │     MCP: rti-connext-mcp → ask_connext_question (IDL syntax)
  │     MCP: rti-connext-mcp → search_type_library (reference types)
  │
  ├── 🔀 patterns.prompt.md     — pattern selection, QoS profiles, transport config
  │     MCP: rti-connext-mcp → ask_connext_question (QoS docs)
  │     MCP: rti-connext-mcp → search_reference_code (existing QoS XML)
  │
  ├── 🏗 builder.prompt.md      — code generation, scaffold, CMake, rtiddsgen
  │     MCP: rti-connext-mcp → search_reference_code (reference apps, wrappers)
  │
  └── 🧪 tester.prompt.md       — test generation, pytest, DDS test utilities
  │     MCP: rti-connext-mcp → search_reference_code (test patterns)
  │
  └── 📚 DDS_PROCESS_BUILDER.md — full reference (this doc), loaded as context
```

### Internal MCP Server Tools

All sub-prompts query one internal MCP server (`rti-connext-mcp`) with three tools:

| Tool | Purpose | Used By |
|------|---------|--------|
| `ask_connext_question` | RAG over RTI documentation — IDL syntax, QoS policies, annotations, transport config, API usage | datamodel, patterns |
| `search_reference_code` | Search local reference code — starter kit examples, wrapper classes, CMake patterns, QoS XML, test fixtures | patterns, builder, tester |
| `search_type_library` | Search community/reference IDL type definitions by pattern (Command, Status, Event, etc.) | datamodel |

**Phase 0 bootstrap populates the reference code and type library** from GitHub repos into local `system_templates/` slots. After bootstrap, the internal MCP RAG indexes this local content — no further GitHub access needed.

**Future tool expansion** (not yet implemented):

| Tool | Purpose |
|------|--------|
| `validate_idl` | Validate IDL against rules (bounded strings, `@key` present, naming conventions) |
| `check_qos_conflicts` | Detect incompatible QoS combinations before generating XML |
| `validate_process_design` | Validate PROCESS_DESIGN.yaml against schema rules |
| `list_workspace_types` | Return all IDL types in workspace with metadata (used by, key fields, pattern) |

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
1. Query internal MCP `search_type_library` for existing types that match the user's description
2. Query internal MCP `ask_connext_question` for IDL syntax if using annotations or complex types
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

1. Query internal MCP `ask_connext_question` for QoS policy documentation when user asks
   about reliability, durability, deadline, ownership, or transport
2. Query internal MCP `search_reference_code` for existing QoS XML profiles in the project
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

1. Query internal MCP `search_reference_code` for existing app implementations to use
   as reference (especially `apps/cxx11/example_io_app/`)
2. Check `dds/utils/cxx11/` for available wrapper class headers
3. Check `system_templates/` for scaffold files and read the framework manifest

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

1. Query internal MCP `search_reference_code` for existing test patterns
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
   - Query internal MCP search_type_library for reference types
   - Query internal MCP ask_connext_question for IDL syntax if needed
   - The I/O CANNOT proceed until a type is confirmed

3. **Step 2c — Pattern & QoS** — Load `.github/prompts/patterns.prompt.md`
   and follow its instructions to select the data pattern and QoS.
   - This will auto-resolve the pattern from the type name
   - This will query internal MCP ask_connext_question for QoS documentation if needed
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

  Agent queries internal MCP search_type_library: "Command type IDL reference"
  Agent queries internal MCP ask_connext_question: "@key annotation usage"

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
