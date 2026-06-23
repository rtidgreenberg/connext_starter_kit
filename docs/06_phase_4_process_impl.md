# Phase 4: Process Implementation

When the user selects "Implement Now", the agent reads `PROCESS_DESIGN.yaml` and executes these steps **automatically** with no user interaction required.

## Implementation Steps

Each step is driven by **manifest files** and **terminal commands**. The agent reads the framework manifest to determine which template files to copy and substitute, then runs deterministic commands (rtiddsgen, cmake) in the terminal. Step 4 (app code generation) is the only AI-driven step.

```
Manifest + command inventory:
  manifest.yaml        — framework-specific file list, template paths, variable tokens
  rtiddsgen             — run rtiddsgen with correct API flags (terminal command)
  QoS fragment assembly — agent merges fragments from qos_templates/ based on design
  builder.prompt.md     — agent generates app code using blueprints as reference
  cmake / pip / maven   — build commands run in terminal
  pytest                — test runner in terminal
```

```
Step 1: SCAFFOLD PROJECT (agent reads manifest)
  Manifest: system_templates/<framework>/manifest.yaml

  What the agent does:
    - Reads manifest.yaml for the selected framework
    - Reads project.yaml for api, framework
    - For each entry in manifest.files[]:
        1. Reads the template file from the `template` path
        2. Substitutes {{VARIABLES}} from PROCESS_DESIGN.yaml + project.yaml
        3. Creates the output file at the `destination` path
    - Executes build_integration actions (e.g., adds process to top-level CMakeLists.txt)
    - If wrapper_class: verifies wrapper headers exist in dds/utils/cxx11/ 
    - Idempotent: skips if scaffold already exists (unless user requests --force)

  Example manifest entry → execution:
    manifest says:
      filename: "CMakeLists.txt"
      destination: "apps/cxx11/gps_tracker/CMakeLists.txt"
      template: "system_templates/wrapper_class/scaffold/CMakeLists.txt.template"
    agent does:
      1. read_file("system_templates/wrapper_class/scaffold/CMakeLists.txt.template")
      2. Replace {{PROCESS_NAME}} → "gps_tracker", {{IDL_MODULES}} → "gps_types"
      3. create_file("apps/cxx11/gps_tracker/CMakeLists.txt", substituted_content)

Step 2: RUN RTIDDSGEN (terminal command)
  Command: rtiddsgen -language <flag> -replace -d <output_dir> <idl_file>

  What the agent does:
    - IDL files already exist (written during Phase 3 design)
    - Reads project.yaml for api → maps to rtiddsgen -language flag:
        modern_cpp       → -language C++11  → dds/build/cxx11_gen/
        python           → -language python → dds/build/python_gen/
        java             → -language java   → dds/build/java_gen/
        c                → -language C      → dds/build/c_gen/
        modern_cpp_python → runs BOTH C++11 and python
    - Runs rtiddsgen in the terminal for each IDL file referenced in the design
    - Uses -replace flag (always overwrites generated code)
    - Validates: rtiddsgen exit code == 0

Step 3: ASSEMBLE QoS XML (agent-driven)
  The agent assembles QoS XML by reading the design YAML and merging fragments:

  What the agent does:
    - Reads all qos_profile references from inputs[] and outputs[]
    - For each unique profile: reads the matching XML fragment from qos_templates/
    - Merges fragments into dds/qos/DDS_QOS_PROFILES.xml
    - If output file already exists: merges new profiles (no duplicates)
    - Sets transport configs based on process.transports

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

Step 5: GENERATE TESTS (agent-driven)
  What the agent does:
    - Reads tests.unit[] and tests.integration[] from design YAML
    - Generates conftest.py (if not exists): fixtures, domain isolation, cleanup
    - For each unit test: generates test_<name>.py from test templates
    - For each integration test: generates test_<name>.py with process launcher
    - Idempotent: skips existing test files (unless user requests overwrite)

Step 6: BUILD (terminal command)
  What the agent does:
    - modern_cpp / c:
        Runs: mkdir -p build && cd build && cmake .. && cmake --build .
    - python:
        Runs: pip install -e apps/python/<process_name>/
    - java:
        Runs: cd apps/java/<process_name> && mvn compile
    - Validates: exit code == 0, no compile errors

Step 7: RUN TESTS (terminal command)
  What the agent does:
    - Runs: python -m pytest test_<process_name>*.py -v --tb=short
    - Captures output to tests/test_results/<process_name>_results.xml (JUnit format)
    - Reports: pass/fail per test, with failure details
```

## Agent's Role During Implementation

The agent's job is to:
1. Parse the design YAML to extract step parameters
2. Execute steps in order (Steps 1→7), stopping on failure
3. **Steps 1-3, 5 are deterministic** — template copy, rtiddsgen, QoS merge, test scaffold
4. **Step 4 is the only AI-generative step** — app code generation requires
   understanding the I/O logic, callbacks, and patterns. The agent uses
   `builder.prompt.md` + blueprints as reference.
5. **Steps 6-7 run terminal commands** — cmake/pip build and pytest
6. Report results back to the user after each step

## Implementation Output

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

## Type Reuse Across Processes

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

## Build & Test

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
