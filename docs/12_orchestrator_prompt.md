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
   - Query internal MCP search_type_library for reference types
   - Query internal MCP ask_connext_question for IDL syntax if needed

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

Read `planning/processes/<name>.yaml` and execute steps **agent-driven**.
Read `planning/project.yaml` for framework/API.

Execute steps in order, stopping on first failure:

```
# Step 1: Scaffold — agent reads manifest, copies/substitutes templates
Agent reads system_templates/<framework>/manifest.yaml
For each file entry: read template → substitute {{VARIABLES}} → create_file()

# Step 2: Run rtiddsgen (IDL files already exist from Phase 3 design)
Agent runs in terminal: rtiddsgen -language <flag> -replace -d <output_dir> <idl_file>

# Step 3: Assemble QoS XML
Agent reads design YAML for qos_profile refs → reads fragments from qos_templates/
→ merges into dds/qos/DDS_QOS_PROFILES.xml

# Step 4: Generate app code (AGENT-DRIVEN — uses builder.prompt.md)
Load builder.prompt.md, use blueprints/<pattern>/ as reference
This is the only step that requires AI-generated code

# Step 5: Generate tests
Agent reads design YAML → generates test scaffold files into tests/

# Step 6: Build
Agent runs in terminal: cmake / pip / maven (based on project.yaml framework)

# Step 7: Run tests
Agent runs in terminal: pytest / ctest (based on project.yaml framework)
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
| datamodel | `ask_connext_question` | IDL syntax, annotations, bounded types |
| datamodel | `search_type_library` | Reference IDL templates per pattern |
| patterns  | `ask_connext_question` | QoS policies, transport config, profiles |
| patterns  | `search_reference_code` | Existing QoS XML in the project |
| builder   | `search_reference_code` | Reference apps, wrapper classes, CMake |
| tester    | `search_reference_code` | Existing test patterns, pytest fixtures |
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
