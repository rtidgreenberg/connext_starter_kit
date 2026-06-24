# Phase 2: System Implementation

Generates the **system baseline** — shared artifacts that all processes build on. This runs after Phase 1 completes, or again whenever system config changes.

**Reads both config files + the system manifest:**
- `planning/project.yaml` → determines scaffold templates, build system, rtiddsgen flags
- `planning/system_config.yaml` → determines which system pattern IDL/QoS to generate
- `system_templates/system_manifest.yaml` → defines the directory structure and verification checks

**What it generates:**

### QoS Strategy: Monolithic Source of Truth + Reference Fragments

`dds/qos/DDS_QOS_PROFILES.xml` is the **single source of truth** for all QoS profiles. It ships pre-built and complete — containing all data pattern profiles (`DataPatternsLibrary::*`) and participant profiles (`DPLibrary::*`).

QoS fragments in `system_templates/qos_templates/` are **reference material only** — they document the individual building blocks that comprise the monolithic XML. They exist for:
1. **Agent indexing**: the patterns sub-prompt reads fragments to understand individual QoS settings.
2. **Documentation**: users who want to understand what a specific pattern's QoS contains.
3. **MCP knowledge layer**: fragments are indexed by the internal MCP server for RAG queries.

**Fragments are NOT assembled at runtime.** Phase 4 Step 3 (QoS Assembly) becomes: "Verify the needed QoS profile exists in `DDS_QOS_PROFILES.xml`; if not, warn the user." System pattern QoS (e.g., `SystemPatternsLibrary::HeartbeatQoS`) is the one exception — it may be generated into a separate `SystemPatternsQoS.xml` file during Phase 2 if system patterns are selected.

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

**Agent-driven execution (reads `system_manifest.yaml`):**

The agent reads the system manifest and executes each step directly — no shell scripts required:

```yaml
# system_templates/system_manifest.yaml
# Defines what Phase 2 creates — the shared foundation all processes build on.
# The agent reads this and executes each entry.

directories:
  - path: "apps/cxx11/"
    condition: "project.api in [modern_cpp, modern_cpp_python]"
  - path: "apps/python/"
    condition: "project.api in [python, modern_cpp_python]"
  - path: "dds/datamodel/idl/"
  - path: "dds/qos/"
  - path: "dds/build/"
  - path: "planning/processes/"
  - path: "tests/"

verify_existing:
  - path: "dds/qos/DDS_QOS_PROFILES.xml"
    action: verify_exists
    description: "Base QoS profiles must be present"
  - path: "dds/utils/cxx11/"
    action: verify_exists
    condition: "project.framework == wrapper_class"
    description: "Wrapper class headers for DDSParticipantSetup etc."
  - path: "CMakeLists.txt"
    action: verify_exists
    description: "Top-level build file"

generate:
  - filename: "system_patterns.idl"
    destination: "dds/datamodel/idl/system_patterns.idl"
    source: template
    template: "system_templates/system_patterns/system_patterns.idl.template"
    condition: "system_config.system_patterns is not empty"
    description: "IDL types for selected system patterns (heartbeat, health, etc.)"

  - filename: "SystemPatternsQoS.xml"
    destination: "dds/qos/SystemPatternsQoS.xml"
    source: generate
    reference_fragments: "system_templates/qos_templates/"
    condition: "system_config.system_patterns is not empty"
    description: "QoS profiles for selected system patterns (exception to monolithic rule — system patterns are generated, not pre-built)"

commands:
  - step: "Run rtiddsgen on system-level types"
    command: "rtiddsgen -language {{rtiddsgen_language}} -replace -d dds/build/cxx11_gen/ dds/datamodel/idl/system_patterns.idl"
    condition: "system_config.system_patterns is not empty"
```

**Example: What the agent does when it reads this manifest:**

```
Agent reads system_manifest.yaml
  │
  ├── Create directories: apps/cxx11/, dds/datamodel/idl/, dds/qos/, ...
  ├── Verify: DDS_QOS_PROFILES.xml exists ✓
  ├── Verify: dds/utils/cxx11/ exists ✓
  ├── Verify: CMakeLists.txt exists ✓
  │
  ├── system_config has patterns [failover, health_monitoring]?
  │   ├── YES → Read system_patterns.idl.template
  │   │         Substitute {{PATTERNS}} based on system_config
  │   │         Write dds/datamodel/idl/system_patterns.idl
  │   │
  │   ├── YES → Generate SystemPatternsQoS.xml (using reference fragments for context)
  │   │
  │   └── YES → Run: rtiddsgen -language C++11 -replace ... system_patterns.idl
  │
  └── Report: "System baseline created. 3 directories, 2 files generated, 1 command run."
```

**Key behaviors:**
- **Idempotent**: re-running skips existing files unless `--force` is used
- **Additive for new patterns**: adding a system pattern generates new IDL/QoS without disturbing existing files
- **Process-specific IDL is NOT generated here** — that happens in Phase 4
- The agent runs this automatically after Phase 1 — no user interaction needed
