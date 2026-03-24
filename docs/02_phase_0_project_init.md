# Phase 0: Project Initialization

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

## Step 2: Bootstrap Reference Content

After the user confirms framework + API, the agent runs a one-time bootstrap to populate empty `system_templates/` slots with reference content. This ensures blueprints, QoS fragments, and system pattern examples are available locally before any process is designed.

**How it works:**

1. The agent reads `system_templates/reference_manifest.yaml` — a machine-readable spec that maps each empty template slot to a source.
2. For each entry with `source: github`, the agent calls `github_repo` MCP to search the specified repo, reviews the returned snippets, and writes the adapted content locally.
3. For each entry with `source: local`, the agent copies from elsewhere in the workspace (e.g., `apps/cxx11/large_data_app/` → `blueprints/large_data/cxx11/`).
4. For each entry with `source: extract`, the agent extracts a section from an existing file (e.g., a QoS profile from `DDS_QOS_PROFILES.xml`).
5. The agent records `bootstrap_version` and `bootstrap_date` in `project.yaml`.

**Example `reference_manifest.yaml`:**

```yaml
# system_templates/reference_manifest.yaml
# Maps empty template slots to sources. Read by the agent during Phase 0 bootstrap.
# After bootstrap, all content is local — no further GitHub access needed.

bootstrap_version: 1

qos_templates:
  - slot: "qos_templates/event_qos.xml.fragment"
    source: extract
    extract_from: "dds/qos/DDS_QOS_PROFILES.xml"
    profile: "DataPatternsLibrary::ReliableQoS"
    description: "Reliable, KEEP_ALL history for event pattern"

  - slot: "qos_templates/status_qos.xml.fragment"
    source: extract
    extract_from: "dds/qos/DDS_QOS_PROFILES.xml"
    profile: "DataPatternsLibrary::StatusQoS"
    description: "Best effort, KEEP_LAST 1 for periodic status"

  - slot: "qos_templates/command_qos.xml.fragment"
    source: extract
    extract_from: "dds/qos/DDS_QOS_PROFILES.xml"
    profile: "DataPatternsLibrary::CommandQoS"
    description: "Reliable with ownership for command pattern"

blueprints:
  - slot: "blueprints/event/cxx11/"
    source: github
    repo: "rticommunity/rticonnextdds-examples"
    query: "C++11 reliable publisher subscriber event callback KEEP_ALL"
    files_needed: ["main.cxx", "CMakeLists.txt"]
    post_process: templatize        # agent adds {{VARIABLE}} tokens

  - slot: "blueprints/status/cxx11/"
    source: github
    repo: "rticommunity/rticonnextdds-examples"
    query: "C++11 periodic publisher best effort status deadline"
    files_needed: ["main.cxx", "CMakeLists.txt"]
    post_process: templatize

  - slot: "blueprints/large_data/cxx11/"
    source: local
    copy_from: "apps/cxx11/large_data_app/"
    description: "Already exists in workspace"

system_patterns:
  - slot: "system_patterns/health_monitoring/"
    source: github
    repo: "rticommunity/rticonnextdds-medtech-reference-architecture"
    query: "heartbeat health monitoring IDL liveliness"
    files_needed: ["HealthStatus.idl"]
    post_process: templatize

  - slot: "system_patterns/failover/"
    source: github
    repo: "rticommunity/rticonnextdds-medtech-reference-architecture"
    query: "failover hot standby ownership strength IDL"
    files_needed: ["Failover.idl"]
    post_process: templatize
```

**The bootstrap is agent-driven, not scripted.** The agent:
- Calls `github_repo(repo, query)` → gets code snippets
- Reviews and selects the right content
- Adapts it to the template format (adds `{{VARIABLE}}` tokens where needed)
- Writes it to the target slot via `create_file`
- Validates naming conventions match the project's patterns

**After bootstrap, `project.yaml` records what was fetched:**

```yaml
project:
  framework: wrapper_class
  api: modern_cpp
  locked: true
  created: "2026-03-17T10:00:00Z"
  bootstrap:
    version: 1
    date: "2026-03-17T10:00:30Z"
    slots_populated: 12
    source_repos:
      - rticommunity/rticonnextdds-examples
      - rticommunity/rticonnextdds-medtech-reference-architecture
```

**Why bootstrap matters for privacy:** After this one-time fetch, all reference content lives in the local workspace. The internal MCP server's RAG indexes this local content. No further GitHub MCP calls are needed — the architecture docs and reference code stay private.

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
