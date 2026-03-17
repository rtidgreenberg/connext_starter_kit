# Wrapper Class Scaffold Templates

These parameterized templates are used by the `/rti_dev` DDS Process Builder to generate
new Wrapper Class processes during **Phase 4 (Process Implementation)**.

## Files

| Template | Generated As | Purpose |
|---|---|---|
| `CMakeLists.txt.template` | `apps/cxx11/<process>/CMakeLists.txt` | Build configuration |
| `application.hpp.template` | `apps/cxx11/<process>/application.hpp` | Signal handling, arg parsing |
| `app_main.cxx.template` | `apps/cxx11/<process>/main.cxx` | DDS infrastructure layer |
| `process_logic.hpp.template` | `apps/cxx11/<process>/<name>_logic.hpp` | Business logic interface |
| `process_logic.cxx.template` | `apps/cxx11/<process>/<name>_logic.cxx` | Business logic implementation |
| `run.sh.template` | `apps/cxx11/<process>/run.sh` | Launch script |

## Substitution Variables

The following `{{VARIABLE}}` tokens are replaced during code generation:

### Identity
- `{{PROCESS_NAME}}` — snake_case (e.g., `gps_tracker`)
- `{{PROCESS_NAME_PASCAL}}` — PascalCase (e.g., `GpsTracker`)
- `{{PROCESS_NAME_UPPER}}` — UPPER_CASE (e.g., `GPS_TRACKER`)
- `{{APP_DISPLAY_NAME}}` — human-readable (e.g., `GPS Tracker Application`)
- `{{PROCESS_DESCRIPTION}}` — one-line description from PROCESS_DESIGN

### DDS Configuration
- `{{DEFAULT_DOMAIN_ID}}` — from `system_config.yaml`
- `{{PARTICIPANT_PROFILE}}` — QoS profile string for DomainParticipant
- `{{INCLUDES}}` — `#include` directives for IDL-generated type headers

### Generated Blocks (populated from PROCESS_DESIGN I/O)
- `{{READERS_SETUP}}` — DDSReaderSetup instantiations for each input topic
- `{{WRITERS_SETUP}}` — DDSWriterSetup instantiations for each output topic
- `{{CALLBACK_WIRING}}` — Lambda registrations connecting readers to logic callbacks
- `{{PUBLISH_LOOP}}` — Periodic write calls in the main loop

### Logic Layer
- `{{LOGIC_INCLUDES}}` — includes for POD types (no DDS headers)
- `{{CALLBACK_DECLARATIONS}}` — function signatures for reader callbacks
- `{{CALLBACK_IMPLEMENTATIONS}}` — function bodies
- `{{COMPUTE_DECLARATIONS}}` — periodic compute function signatures
- `{{COMPUTE_IMPLEMENTATIONS}}` — periodic compute function bodies
- `{{STATE_MEMBERS}}` — private member variables for the logic class

## Clean Architecture Rule

The generated code enforces separation of concerns:
- **`main.cxx`** — DDS infrastructure only (participant, readers, writers, waitsets)
- **`_logic.hpp` / `_logic.cxx`** — Business logic only (NO `#include <dds/...>`)

This enables unit testing of logic without DDS middleware running.
