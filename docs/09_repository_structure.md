# Repository Structure

This section defines the **template repo** — the workflow infrastructure artifacts that ship in the repository. Everything listed here is checked in and maintained as reusable tooling. Generated output (planning configs, application code, IDL, tests, build artifacts) is produced by executing the workflow and is NOT part of the template.

## Prompt Infrastructure

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

## MCP Configuration

```
mcp.json                                  # MCP server endpoints
                                           #   - rti-connext-mcp (internal: docs RAG,
                                           #     reference code, type library)
                                           #   - github (Phase 0 bootstrap only)
```

## Manifest Files (machine-readable scaffold specs)

```
system_templates/
├── wrapper_class/
│   └── manifest.yaml                     # Per-process file list, template paths,
│                                         #   variable tokens, build integration
├── xml_app_creation/
│   └── manifest.yaml
├── python/
│   └── manifest.yaml
├── system_manifest.yaml                  # Phase 2: system baseline directories,
│                                         #   verification checks, generation rules
└── reference_manifest.yaml               # Phase 0 bootstrap: maps empty template
                                           #   slots to GitHub repos / local sources
```

**Example `wrapper_class/manifest.yaml`:**

```yaml
# system_templates/wrapper_class/manifest.yaml
# The agent reads this to scaffold a new process directory.
# Each entry maps a template to a target file with variable substitution.

framework: wrapper_class
api: modern_cpp

files:
  - filename: "CMakeLists.txt"
    destination: "apps/cxx11/{{PROCESS_NAME}}/CMakeLists.txt"
    source: template
    template: "system_templates/wrapper_class/scaffold/CMakeLists.txt.template"

  - filename: "main.cxx"
    destination: "apps/cxx11/{{PROCESS_NAME}}/main.cxx"
    source: template
    template: "system_templates/wrapper_class/scaffold/app_main.cxx.template"

  - filename: "{{PROCESS_NAME}}_logic.hpp"
    destination: "apps/cxx11/{{PROCESS_NAME}}/{{PROCESS_NAME}}_logic.hpp"
    source: template
    template: "system_templates/wrapper_class/scaffold/process_logic.hpp.template"

  - filename: "{{PROCESS_NAME}}_logic.cxx"
    destination: "apps/cxx11/{{PROCESS_NAME}}/{{PROCESS_NAME}}_logic.cxx"
    source: template
    template: "system_templates/wrapper_class/scaffold/process_logic.cxx.template"

  - filename: "application.hpp"
    destination: "apps/cxx11/{{PROCESS_NAME}}/application.hpp"
    source: template
    template: "system_templates/wrapper_class/scaffold/application.hpp.template"

  - filename: "run.sh"
    destination: "apps/cxx11/{{PROCESS_NAME}}/run.sh"
    source: template
    template: "system_templates/wrapper_class/scaffold/run.sh.template"
    executable: true

shared_files:
  - filename: "{{IDL_MODULE}}.idl"
    destination: "dds/datamodel/idl/{{IDL_MODULE}}.idl"
    source: authored                       # written during Phase 3, not from template

  - filename: "DDS_QOS_PROFILES.xml"
    destination: "dds/qos/DDS_QOS_PROFILES.xml"
    source: assemble                       # merged from qos_templates/ fragments
    fragments:
      - "system_templates/qos_templates/{{PATTERN}}_qos.xml.fragment"

build_integration:
  - file: "CMakeLists.txt"                 # top-level
    action: add_subdirectory
    value: "apps/cxx11/{{PROCESS_NAME}}"
```

## Implementation Steps (Agent-Driven)

```
scripts/
├── (no shell scripts required — agent performs all steps directly)
│
│   Phase 4 Steps executed by the agent:
├── Step 1: Scaffold       — agent reads manifest.yaml, copies/substitutes templates
├── Step 2: rtiddsgen      — agent runs rtiddsgen in terminal with correct flags
├── Step 3: QoS assembly   — agent merges QoS XML fragments from qos_templates/
├── Step 4: App code       — agent generates code using builder.prompt.md + blueprints
├── Step 5: Test scaffold  — agent generates test files from design YAML
├── Step 6: Build          — agent runs cmake/pip/maven in terminal
└── Step 7: Run tests      — agent runs pytest/ctest in terminal
```

## System Templates (read-only scaffolds)

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

## Architecture Documentation

```
DDS_PROCESS_BUILDER.md                    # Top-level summary + table of contents
docs/
├── 01_rules.md                           # All rules (IDL, naming, architecture, workflow)
├── 02_phase_0_project_init.md            # Phase 0: Project Initialization
├── 03_phase_1_system_design.md           # Phase 1: System Design
├── 04_phase_2_system_impl.md             # Phase 2: System Implementation
├── 05_phase_3_process_design.md          # Phase 3: Process Design + PROCESS_DESIGN.yaml
├── 06_phase_4_process_impl.md            # Phase 4: Process Implementation
├── 07_patterns_reference.md              # System Patterns + Data Patterns catalog
├── 08_decision_points.md                 # All decision points with auto-resolve rules
├── 09_repository_structure.md            # This file — template repo layout
├── 10_iterative_workflow.md              # Session examples and workflow scenarios
├── 11_sub_prompts.md                     # Sub-prompt architecture + embedded definitions
└── 12_orchestrator_prompt.md             # /rti_dev prompt + menu system + MCP tools
```

## What Gets Generated (NOT part of the template)

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
