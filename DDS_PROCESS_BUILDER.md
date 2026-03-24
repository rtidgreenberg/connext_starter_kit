# DDS Process Builder — Architecture

Five-phase system for designing and building RTI Connext DDS applications: **Init → Design System → Build Baseline → Design Process → Build Process.** Invoked as `/rti_dev` in VS Code Copilot Chat.


## High-Level Overview

The DDS Process Builder is a guided, agent-driven workflow for designing and implementing RTI Connext DDS applications. It runs as `/rti_dev` inside VS Code Copilot Chat and walks the user through every decision — from selecting a framework to publishing data on the wire.

### What it does

A user describes what their DDS processes should do in plain English. The workflow translates that into concrete artifacts: IDL type definitions, QoS XML profiles, application source code (C++, Python, Java, or C), build files, and integration tests. Every generated artifact traces back to a design decision stored in YAML.

### How it works

The workflow is split into **five phases** that execute in order. The first three run once to establish a project foundation; the last two repeat for each DDS process the user wants to build.

1. **Project Initialization** — The user picks a framework (Wrapper Class or XML App Creation) and an API language. These choices are **permanent** — they determine the scaffold templates, code generator flags, and build system used for every process in the project.

2. **System Design** — The user sets a domain ID and selects system-level architectural patterns (failover, health monitoring, leader election, etc.) along with their implementation approach. These choices are **versioned** — changing them later triggers a reconciliation sweep across all existing process designs.

3. **System Implementation** — The agent automatically creates the baseline: directory structure, system-level IDL (e.g., heartbeat types), QoS profiles for system patterns, and the top-level build file. No user interaction required.

4. **Process Design** — An interactive loop where the user names a process, selects transports, opts into system patterns, defines inputs/outputs (each with a topic, data type, data pattern, and QoS profile), and specifies tests. Data types are written directly to `.idl` files during this phase. The result is a `PROCESS_DESIGN.yaml` — a complete, machine-readable specification.

5. **Process Implementation** — Fully automated. The agent reads the design YAML and executes: scaffold the app directory, run `rtiddsgen` on the IDL files, assemble QoS XML, generate application code (the only AI-driven step), generate tests, build, and run tests. If tests fail, the user returns to design to fix.

### Key mechanics

- **Three decision scopes**: Project-level decisions are locked. System-level decisions are versioned and trigger sweeps. Process-level decisions are freely editable per process.
- **IDL-first type design**: Types are defined as actual IDL and written to `.idl` files during design — not embedded in YAML.
- **Manifest-driven scaffold**: YAML manifest files define the folder structure, template files, and variable substitutions for each framework.
- **Agent-driven implementation**: The agent reads templates, performs `{{VARIABLE}}` substitution, writes output files, and runs build commands.
- **Sub-prompts for expertise**: Four specialized prompt files handle type definition, pattern/QoS selection, code generation, and test generation.
- **MCP for knowledge**: One internal MCP server (`rti-connext-mcp`) provides RTI documentation RAG, reference code search, and type library search.
- **Reference bootstrap**: Phase 0 includes a one-time bootstrap that fetches reference content from GitHub into local `system_templates/` slots.
- **Design ↔ Implementation loop**: Design one and implement, batch-design several and implement all, or iterate until tests pass.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                            /rti_dev                                    │
│                                                                        │
│  PHASE 0: PROJECT INIT (one-time, irreversible)                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Framework: Wrapper Class / XML App Creation    🔒 LOCKED        │  │
│  │  API: Modern C++ / Python / Java / C / Both     🔒 LOCKED        │  │
│  │  → planning/project.yaml                                         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                         │
│                              ▼                                         │
│  PHASE 1: SYSTEM DESIGN (modifiable, versioned)                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Domain ID, System Patterns + approaches                         │  │
│  │  → planning/system_config.yaml (version: N)                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                         │
│                              ▼                                         │
│  PHASE 2: SYSTEM IMPLEMENTATION (baseline scaffold)                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  system_patterns.idl, SystemPatternsQoS.xml, dir structure       │  │
│  │  Top-level CMake/pip, rtiddsgen for system types                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                         │
│              ┌───────────────┴────────────────┐                        │
│              ▼                                ▼                        │
│  PHASE 3: PROCESS DESIGN         PHASE 4: PROCESS IMPLEMENTATION       │
│  ┌──────────────────────────┐    ┌──────────────────────────────┐      │
│  │ Name, transports         │    │ Write process IDL            │      │
│  │ Opt-in to system patterns│───►│ rtiddsgen process types      │      │
│  │ Define I/O + types       │    │ App code (main + logic)      │      │
│  │ Define tests             │    │ QoS assembly                 │      │
│  │ Review                   │    │ Tests, build, run            │      │
│  └──────────┬───────────────┘    └──────────────┬───────────────┘      │
│             │                                   │                      │
│             └── Plan another ───────────────────┘                      │
│                                                                        │
│  ◄── "Back to System Design" (version++, triggers sweep) ────────────► │
│  ◄── "Back to Project Init" → ⚠ "Requires full regeneration" ──────►   │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Five phases, three scopes:**

| Phase | Scope | Reversible? | Output |
|-------|-------|-------------|--------|
| **0. Project Init** | Framework + API | **No** — locked after scaffold | `planning/project.yaml` |
| **1. System Design** | Domain ID, system patterns + approaches | Yes — version-tracked | `planning/system_config.yaml` |
| **2. System Implementation** | Baseline IDL, QoS, directory scaffold | Re-runnable (idempotent) | `dds/`, top-level build files |
| **3. Process Design** | Per-process I/O, types, tests, pattern opt-in | Yes — per process | `planning/processes/<name>.yaml` |
| **4. Process Implementation** | Per-process code, build, test | Re-runnable | `apps/`, tests |

**Typical flows:**

- **Init → System Design → System Impl → Design one → Implement one → repeat** (incremental)
- **Init → System Design → System Impl → Design several → Implement all** (batch)
- **Design → Implement → modify design → re-implement** (iterate)
- **Implement → test fails → return to design → fix → re-implement** (fix forward)
- **Back to System Design → add pattern → sweep existing processes** (evolve)

---

## Detailed Documentation

Each section of the architecture is documented in its own file for easier navigation:

| # | Document | Description |
|---|----------|-------------|
| 1 | [Rules](docs/01_rules.md) | IDL, naming, architecture, workflow, schema, implementation, code, test, MCP, and auto-resolve rules |
| 2 | [Phase 0: Project Init](docs/02_phase_0_project_init.md) | Framework/API selection, `project.yaml` schema, derived fields, bootstrap, re-entry guard |
| 3 | [Phase 1: System Design](docs/03_phase_1_system_design.md) | Domain ID, system patterns, `system_config.yaml` schema, versioning, sweep |
| 4 | [Phase 2: System Implementation](docs/04_phase_2_system_impl.md) | Baseline generation, `system_manifest.yaml`, agent-driven execution |
| 5 | [Phase 3: Process Design](docs/05_phase_3_process_design.md) | Planning loop, I/O sub-loop, `PROCESS_DESIGN.yaml` schema |
| 6 | [Phase 4: Process Implementation](docs/06_phase_4_process_impl.md) | 7 implementation steps, agent's role, output tree, type reuse, build & test |
| 7 | [Patterns Reference](docs/07_patterns_reference.md) | System Patterns Catalog + Data Patterns Reference + pattern→code mapping |
| 8 | [Decision Points](docs/08_decision_points.md) | Project-level, system-level, process-level decisions with auto-resolve rules |
| 9 | [Repository Structure](docs/09_repository_structure.md) | Template repo layout, manifest files, generated output tree |
| 10 | [Iterative Workflow](docs/10_iterative_workflow.md) | 6 workflow scenarios — fresh, incremental, batch, return-to-design, direct command, fix |
| 11 | [Sub-Prompt Architecture](docs/11_sub_prompts.md) | 4 sub-prompts (datamodel, patterns, builder, tester), MCP tools, trigger flow |
| 12 | [Orchestrator & Prompt Reference](docs/12_orchestrator_prompt.md) | Five Phases table, `/rti_dev` prompt, interactive menu, embedded prompt definitions |
