# Recording Service Remote Control (Python)

Remotely control a running RTI Recording Service instance using the common
Remote Administration Platform. This Python application uses **DynamicData** and
the **Request/Reply** pattern to send commands — no C++ compilation needed.

Based on the [C++ service admin example](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/recording_service/service_admin/c%2B%2B11).

Architecture notes:
- [GUI_ARCHITECTURE.md](GUI_ARCHITECTURE.md) describes the current tkinter
   Recording Service reference GUI.
- [../rs_gui_v2/DEARPYGUI_APP_ARCHITECTURE.md](../rs_gui_v2/DEARPYGUI_APP_ARCHITECTURE.md) sketches the
   target Dear PyGui application architecture for recording, replay, conversion,
   topic browsing, plotting, and persisted workspaces.
- [../rs_gui_v2/DEARPYGUI_IMPLEMENTATION_PLAN.md](../rs_gui_v2/DEARPYGUI_IMPLEMENTATION_PLAN.md) breaks
   that architecture into phased implementation milestones and validation gates.
- [../rs_gui_v2/DEARPYGUI_WIREFRAME_PLAN.md](../rs_gui_v2/DEARPYGUI_WIREFRAME_PLAN.md) defines the mock
   wireframes and approval gate required before Dear PyGui UI implementation.

## How it Works

1. **`setup.sh`** uses `rtiddsgen -convertToXML` to convert the admin and
   monitoring IDL files into XML type descriptions for DynamicData CDR
   serialization. It also normalizes monitoring union discriminator labels from
   symbolic enum references to literal integers for Python DynamicData readers.
   The IDL source is `$NDDSHOME/resource/idl`, so generated XML is tied to the
   selected Connext installation.
   Additionally it installs `sqlite3` (needed by
   `rtirecordingservice_list_tags`).
2. The admin CLI loads the XML types via `QosProvider`, builds
   `DynamicData` samples matching the `CommandRequest`/`CommandReply` types, and
   uses `rti.request.Requester` to send commands and receive replies.
3. The monitoring subscriber loads the XML monitoring types and creates
   `DynamicData` `Topic`/`DataReader` objects for the shared Recording Service
   monitoring topics. It processes them with `rti.asyncio` reader loops backed
   by WaitSet dispatch, so parsing and GUI queue callbacks stay off DDS
   listener threads.
4. For timestamp tags and state changes, the payload type is serialized to CDR
   via `DynamicData.to_cdr_buffer()` and placed into the request's
   `octet_body`.

## Prerequisites

- RTI Connext DDS 7.6.0 with matching Python bindings installed (`rti.connext==7.6.0`)
- Virtual environment set up (`apps/python/install.sh`)
- Recording Service running with remote administration enabled
- RTI license available via `RTI_LICENSE_FILE`, `$NDDSHOME/rti_license.dat`,
  `~/.rti/rti_license.dat`, or `~/rti_license.dat`

## Setup

```bash
# Generate XML type files from IDL and install dependencies (one-time)
./setup.sh
```

The setup script will:
- Auto-detect `$NDDSHOME` if not set
- Convert admin and monitoring IDL type definitions to XML using
   `rtiddsgen -convertToXML`
- Normalize monitoring XML discriminator and enum references for Python
   DynamicData deserialization
- Stamp `xml_types/` with the source `$NDDSHOME` and Connext version so stale
   generated XML is rejected after switching Connext installs
- Install `sqlite3` (required by `rtirecordingservice_list_tags`)

The run scripts and Python modules prefer Connext 7.6.0 when auto-detecting an
installation. They also auto-export `RTI_LICENSE_FILE` from the detected install
license when possible; if no license is found, set `RTI_LICENSE_FILE` before
starting the GUI or CLI. `xml_types/` is a generated local artifact and should
be recreated with `./setup.sh` whenever `$NDDSHOME` changes. The launchers
regenerate it automatically when the metadata stamp is missing or stale.

## Usage

```bash
# Pause recording
./run.sh pause

# Resume recording
./run.sh start

# Set a timestamp tag
./run.sh tag "my_tag" --tag-description "Description of this tag"

# Shut down the service
./run.sh shutdown

# Use a different domain ID (must match Recording Service admin domain)
./run.sh pause --domain-id 54

# Specify a custom service name
./run.sh pause --service-name my_recorder
```

Or run directly with the repository virtual environment:

```bash
../../connext_dds_env/bin/python recording_service_control.py --help
```

## Files

| File | Description |
|------|-------------|
| `recording_service_gui.py` | **GUI** — tkinter front-end for launch, monitor, control, and tag |
| `recording_service_monitor.py` | DDS monitoring subscriber — XML DynamicData monitoring reader using `rti.asyncio` |
| `recording_service_control.py` | Headless CLI for remote admin commands |
| `setup.sh` | Converts admin and monitoring IDL → XML, normalizes XML, installs `sqlite3` |
| `run.sh` | Convenience wrapper for headless CLI |
| `run_gui.sh` | Convenience wrapper for GUI |
| `GUI_ARCHITECTURE.md` | Architecture and design document |
| `xml_types/` | Generated XML type files for admin and monitoring, stamped with source Connext install (created by `setup.sh`) |
| `test/` | All tests (`test_gui.py`, `test_monitoring.py`, `test_control.py`, `test_e2e_tags.py`, `test_e2e_services.py`, `run_all_tests.py`) and E2E assets |

## GUI Mode

The GUI provides a graphical interface for configuring, launching, monitoring,
and controlling a recording session — all from a single window.

### Quick Start

```bash
cd services/rs_gui_v1
./setup.sh       # One-time: generate and normalize XML types from IDL
./run_gui.sh     # Launch the GUI
```

### Features

- **Configuration panel** — set config file, config name, domain IDs, verbosity
- **Launch** — opens Recording Service in a new terminal window with `-D` flags
- **Live monitoring** — subscribes to DDS monitoring topics for real-time status
  (service state, CPU, memory, uptime, DB file/size, recorded topics)
- **Remote control** — Pause / Resume / Shutdown via DDS admin commands
- **Tags** — set timestamp tags with name and description, tracked in a history table
- **Log panel** — timestamped log of all commands, events, and monitoring data

### How It Works

1. The GUI builds and executes a `rtirecordingservice` command in a separate
   terminal window (fire-and-forget — the GUI does not manage the process)
2. Status monitoring uses `rti.asyncio` DDS subscriptions to the well-known
   monitoring topics (`rti/service/monitoring/config`, `event`, `periodic`) on
   the admin domain
3. Control commands use the `RecordingServiceController` class (same as the CLI)

See [GUI_ARCHITECTURE.md](GUI_ARCHITECTURE.md) for the full design document.

## Recording Service Configuration

The Recording Service must have remote administration enabled. Example
configuration snippet (already in `recording_service_config.xml`):

```xml
<administration>
    <domain_id>0</domain_id>
    <datareader_qos base_name="ServiceAdministrationProfiles::ServiceAdminReplierProfile" />
    <datawriter_qos base_name="ServiceAdministrationProfiles::ServiceAdminReplierProfile" />
</administration>
```

QoS profiles for both the admin Request/Reply and monitoring DataReaders are
centralized in `dds/qos/DDS_QOS_PROFILES.xml` (libraries
`ServiceAdministrationProfiles` and `RecordingServiceMonitorProfiles`).

The monitoring subscriber configures the Connext XTypes compliance mask at
startup. It sets `ACCEPT_UNKNOWN_DISCRIMINATOR_BIT` and clears
`SELECT_DEFAULT_DISCRIMINATOR_BIT` so DynamicData readers accept Recording
Service monitoring samples that contain an unknown union discriminator while
preserving the received discriminator without selecting a default branch.

The monitor keeps its public synchronous API for the GUI, but internally owns a
dedicated Python thread with a private asyncio loop. Each monitoring DataReader
is consumed with `reader.take_async()`, and shutdown cancels those reader tasks
before closing the participant.

Generated XML type files are validated before loading. The monitor and
controller reject `xml_types/` if its metadata stamp does not match the active
Connext install, preventing accidental use of XML generated from another
`NDDSHOME`.

## Requester Compatibility

The controller uses `rti.request.Requester` to send `ServiceAdmin.idl` commands
to Recording Service's built-in remote administration interface. This interface
uses the documented admin request/reply topics:

- `rti/service/admin/command_request`
- `rti/service/admin/command_reply`

Recording Service remote administration uses the fixed ServiceAdmin topics and
standard DDS endpoint matching. `RecordingServiceController` constructs the
requester with `require_matching_service_on_send_request=False`, then performs
the checks required for this interface:

- request `DataWriter` publication match with Recording Service's admin request reader
- reply `DataReader` subscription match with Recording Service's admin reply writer
- correlated replies using the request sample identity
- bounded reply timeout
- `CommandReply.retcode` validation

This requester setting is scoped to the built-in Recording Service ServiceAdmin
interface, where command delivery is validated through DDS endpoint matching
and correlated replies on the documented admin topics.

References:

- [Recording Service Remote Administration Platform](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/manuals/connext_dds_professional/services/recording_service/common/remote_admin_platform.html)
- [Recording Service Remote Administration](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/manuals/connext_dds_professional/services/recording_service/recorder/record_administration.html)
- [Request-Reply Endpoint Discovery](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/manuals/connext_dds_professional/users_manual/users_manual/RequestReply_Endpt_Discovery.htm)
- [Connext Python Request/Reply API](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/api/connext_dds/api_python/rti.rpc.html)
- [RTI Recording Service ServiceAdmin example](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/recording_service/service_admin/c%2B%2B11)

## Supported Commands

| Command | Action | Resource Path |
|---------|--------|---------------|
| `start` | UPDATE | `/recording_services/<name>/state` with serialized `EntityState{state=RUNNING}` in `octet_body` |
| `pause` | UPDATE | `/recording_services/<name>/state` with serialized `EntityState{state=PAUSED}` in `octet_body` |
| `shutdown` | DELETE | `/recording_services/<name>` |
| `tag` | UPDATE | `/recording_services/<name>/storage/sqlite:tag_timestamp` |

## Tests

The `test/` directory contains 94 tests across four files covering unit,
widget, integration, and end-to-end testing. See
[test/README.md](test/README.md) for full details.

Services-level E2E tests for the start scripts live in
[`services/test/`](../test/README.md).

```bash
cd services/rs_gui_v1

# Run the GUI test suite
../../connext_dds_env/bin/python test/run_all_tests.py -v

# Run the services E2E tests separately
cd ../..
./connext_dds_env/bin/python services/test/run_all_tests.py -v
```

### Test Layers

| Layer | What it covers | DDS required? |
|-------|---------------|---------------|
| **Unit / Pure logic** | Helper functions, parsing, constants, CLI args | No |
| **Widget** | tkinter panel interactions, queue draining, lifecycle | No (headless display OK) |
| **Integration** | Real DDS readers/participants on a high domain ID | Yes |
| **E2E Tags** | Record → publish → tag via admin → shutdown → verify DB | Yes + Recording Service |
| **E2E Services** | `start_record.sh` → `start_convert.sh` (CSV) → `start_replay.sh` pipeline + orphan cleanup | Yes + Recording/Replay/Converter |

Tests that require DDS or Recording Service binaries are automatically
skipped when prerequisites are unavailable.

## Manual End-to-End Test

The `test/` directory also contains everything needed for a manual end-to-end
verification: a Recording Service config with remote admin enabled, and a
simple DDS publisher.

### Step 1 — Run setup

```bash
cd services/rs_gui_v1
./setup.sh
```

### Step 2 — Start Recording Service

Open a terminal and start Recording Service with the test configuration:

```bash
$NDDSHOME/bin/rtirecordingservice \
    -cfgFile test/test_recorder_config.xml \
    -cfgName remote_admin \
    -verbosity WARN
```

The config enables remote administration on domain 0 and records all topics
into an SQLite database under `test/test_recording/`.

### Step 3 — Publish test data

In a second terminal, publish some DDS data so the recorder has something to
capture:

```bash
source ../../connext_dds_env/bin/activate
cd test
python3 test_publisher.py
```

This publishes 20 samples of a `TestMessage` type on domain 0.

### Step 4 — Send tag commands

While the Recording Service is still running, send tag commands from a third
terminal:

```bash
./run.sh tag "test_event_1" --tag-description "First test event marker"
./run.sh tag "test_event_2" --tag-description "Second test event marker"
```

Expected output for each command:

```
Reply 1: retcode=OK, native_retcode=0, string_body=".../storage/sqlite:tag_timestamp: invoked tag_timestamp operation"
```

### Step 5 — Stop Recording Service

Stop the Recording Service (Ctrl-C in its terminal, or):

```bash
./run.sh shutdown
```

### Step 6 — Verify tags in the database

Use the RTI tag-listing utility to confirm the tags were persisted:

```bash
$NDDSHOME/bin/rtirecordingservice_list_tags \
    -d test/test_recording/
```

Expected output:

```
tag_name      timestamp_ms   tag_description
------------  -------------  -----------------------
test_event_1  1773413075563  First test event marker
test_event_2  1773413095622  Second test event marker
```

You can also query the SQLite database directly:

```bash
sqlite3 test/test_recording/test_data.db \
    "SELECT tag_name, tag_description FROM tags;"
```

### Cleanup

```bash
rm -rf test/test_recording
```
