# Decision Points

All decisions during planning, listed with auto-resolve rules:

**Project-level decisions** (one-time, locked, stored in `project.yaml`):

| ID | Phase | Prompt | Options | Default | Auto-Resolve | Reversible? |
|----|-------|--------|---------|---------|-------------|-------------|
| `project.framework` | 0 | How to create DDS endpoints? | Wrapper Class / XML App | Wrapper Class | User says "XML" → XML; "wrapper" or "code" → Wrapper | **No** |
| `project.api` | 0 | Which Connext API? | Modern C++ / Python / Java / C / Both | Modern C++ | User says "python" → Python; "java" → Java | **No** |

**System-level decisions** (modifiable, versioned, stored in `system_config.yaml`):

| ID | Phase | Prompt | Options | Default | Auto-Resolve |
|----|-------|--------|---------|---------|-------------|
| `system.domain_id` | 1 | Default domain ID? | 0-232 | 0 | — |
| `system.system_pattern` | 1 | System-level behaviors? | None / Failover / Health / Leader / ReqReply / Redundant | None | User mentions "failover", "standby" → Failover |
| `system.system_pattern_option` | 1 | Which approach per pattern? | Varies per pattern | Option 1 | — (always ask, multiple valid approaches) |

**Process-level decisions** (per process, stored in `PROCESS_DESIGN.yaml`):

| ID | Step | Prompt | Options | Default | Auto-Resolve |
|----|------|--------|---------|---------|-------------|
| `plan.domain_id` | 1b | Override domain ID? | null (inherit) / 0-232 | null | — (inherit unless specified) |
| `plan.transports` | 1c | Which transports? | SHMEM+UDP / SHMEM / UDP / TCP / Custom | SHMEM+UDP | User says "network" or "remote" → UDP; "same host" → SHMEM |
| `plan.system_pattern_optin` | 1d | Participate in system pattern? | Yes / No per pattern | No | — (always ask for each available pattern) |
| `plan.system_pattern_role` | 1d | What role for this process? | Varies per pattern (PRIMARY/STANDBY, publisher/monitor) | — | — (always ask) |
| `plan.system_pattern_io` | 1d | Accept auto-generated I/O? | Accept / Modify / Remove | Accept | — (always show for review) |
| `plan.pattern.<topic>` | 2 | Pattern for topic? | Event/Status/Command/Parameter/LargeData | Inferred from type | See auto-resolve per pattern |
| `plan.pattern_option.<topic>` | 2 | Which option within pattern? | Varies per pattern | Option 1 | See auto-resolve per pattern |
| `plan.tests` | 3 | Accept proposed tests? | Accept / Add / Remove / Modify | Accept | — (always ask) |

**Decision persistence**: All decisions are recorded in the `decisions:` section of `PROCESS_DESIGN.yaml`. If the user re-enters planning for the same process, prior decisions are loaded and shown as defaults.
