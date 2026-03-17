# System Templates

This directory contains all parameterized templates used by the `/rti_dev` DDS Process Builder
to generate DDS applications during Phases 2-4 of the workflow.

## Directory Structure

```
system_templates/
├── wrapper_class/           # Code-driven framework (DDSParticipantSetup wrappers)
│   └── scaffold/            # Base app templates (CMake, main, logic, run.sh)
├── xml_app_creation/        # Config-driven framework (entities in XML)
│   └── scaffold/            # Base app templates + DomainLibrary/ParticipantLibrary XML
├── python/                  # Python asyncio framework
│   └── scaffold/            # Base app templates (asyncio, logic, requirements, run.sh)
├── qos_templates/           # QoS profile fragments per data pattern
├── blueprints/              # Complete data-pattern example files per framework
│   ├── event/
│   ├── status/
│   ├── command/
│   ├── parameter/
│   └── large_data/
└── system_patterns/         # Shared IDL + logic for architectural patterns
    ├── failover/
    ├── health_monitoring/
    ├── leader_election/
    ├── request_reply/
    └── redundant_publisher/
```

## Template Substitution

All templates use `{{VARIABLE}}` syntax for substitution. The DDS Process Builder
replaces these tokens during code generation based on:

- **`planning/project.yaml`** — API choice, project name, domain ID
- **`planning/system_config.yaml`** — system patterns, versioning
- **`planning/processes/<name>.yaml`** — process I/O, patterns, logic markers

## Frameworks

| Framework | Directory | When to Use |
|---|---|---|
| **Wrapper Class** | `wrapper_class/` | Full programmatic control, complex logic, custom threading |
| **XML App Creation** | `xml_app_creation/` | Rapid prototyping, config-driven, minimal code |
| **Python** | `python/` | Python-preferred projects, asyncio data processing |

## How Templates Are Used

1. **Phase 2 (System Implementation)**: Scaffold templates create the base directory + files
2. **Phase 3 (Process Design)**: PROCESS_DESIGN.yaml specifies I/O, patterns, logic
3. **Phase 4 (Process Implementation)**: Templates are populated with process-specific code blocks

The generated blocks (`{{READERS_SETUP}}`, `{{WRITERS_SETUP}}`, etc.) are computed from
the PROCESS_DESIGN.yaml I/O definitions and the data pattern catalog.
