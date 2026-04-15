# Recording Service Remote Control (Python)

Remotely control a running RTI Recording Service instance using the common
Remote Administration Platform. This Python application uses **DynamicData** and
the **Request/Reply** pattern to send commands — no C++ compilation needed.

Based on the [C++ service admin example](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/recording_service/service_admin/c%2B%2B11).

## How it Works

1. **`setup.sh`** uses `rtiddsgen -convertToXML` to convert the admin IDL files
   (`ServiceAdmin.idl`, `ServiceCommon.idl`, `RecordingServiceTypes.idl`)
   into XML type descriptions for DynamicData CDR serialization.  It also
   generates **Python type modules** from the monitoring IDL files
   (`ServiceMonitoring.idl`, `RecordingServiceMonitoring.idl`, etc.) using
   `rtiddsgen -language Python` (requires `rti.connext >= 7.3.1`).
   Additionally it installs `sqlite3` (needed by
   `rtirecordingservice_list_tags`).
2. The admin CLI loads the XML types via `QosProvider`, builds
   `DynamicData` samples matching the `CommandRequest`/`CommandReply` types, and
   uses `rti.request.Requester` to send commands and receive replies.
3. The monitoring subscriber imports the generated Python type modules directly
   to create typed `Topic`/`DataReader` objects — no DynamicData needed.
4. For timestamp tags, `DataTagParams` is serialized to CDR via
   `DynamicData.to_cdr_buffer()` and placed into the request's `octet_body`.

## Prerequisites

- RTI Connext DDS 7.x with Python bindings installed (`rti.connext >= 7.3.1`)
- Virtual environment set up (`apps/python/install.sh`)
- Recording Service running with remote administration enabled

## Setup

```bash
# Generate XML type files from IDL and install dependencies (one-time)
./setup.sh
```

The setup script will:
- Auto-detect `$NDDSHOME` if not set
- Convert admin IDL type definitions to XML using `rtiddsgen -convertToXML`
- Generate Python type modules for monitoring using `rtiddsgen -language Python`
- Install `sqlite3` (required by `rtirecordingservice_list_tags`)

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

Or run directly with Python:

```bash
python3 recording_service_control.py --help
```

## Files

| File | Description |
|------|-------------|
| `recording_service_gui.py` | **GUI** — tkinter front-end for launch, monitor, control, and tag |
| `recording_service_monitor.py` | DDS monitoring subscriber — typed Python IDL reference example |
| `recording_service_control.py` | Headless CLI for remote admin commands |
| `setup.sh` | Converts admin IDL → XML, monitoring IDL → Python types, installs `sqlite3` |
| `run.sh` | Convenience wrapper for headless CLI |
| `run_gui.sh` | Convenience wrapper for GUI |
| `GUI_ARCHITECTURE.md` | Architecture and design document |
| `xml_types/` | Generated XML type files for admin (created by `setup.sh`) |
| `python_types/` | Generated Python type modules for monitoring (created by `setup.sh`) |
| `test/` | All tests (`test_gui.py`, `test_monitoring.py`, `test_control.py`, `test_e2e_tags.py`, `test_e2e_services.py`, `run_all_tests.py`) and E2E assets |

## GUI Mode

The GUI provides a graphical interface for configuring, launching, monitoring,
and controlling a recording session — all from a single window.

### Quick Start

```bash
cd services/recording_service_gui
./setup.sh       # One-time: generate XML types and Python type modules from IDL
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
2. Status monitoring uses DDS subscriptions to the well-known monitoring topics
   (`rti/service/monitoring/config`, `event`, `periodic`) on the admin domain
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

## Supported Commands

| Command | Action | Resource Path |
|---------|--------|---------------|
| `start` | UPDATE | `/recording_services/<name>/state` → `"running"` |
| `pause` | UPDATE | `/recording_services/<name>/state` → `"paused"` |
| `shutdown` | DELETE | `/recording_services/<name>` |
| `tag` | UPDATE | `/recording_services/<name>/storage/sqlite:tag_timestamp` |

## Tests

The `test/` directory contains 94 tests across four files covering unit,
widget, integration, and end-to-end testing. See
[test/README.md](test/README.md) for full details.

Services-level E2E tests for the start scripts live in
[`services/test/`](../test/README.md).

```bash
cd services/recording_service_gui

# Run the GUI test suite
python3 test/run_all_tests.py -v

# Run the services E2E tests separately
cd services
python3 test/run_all_tests.py -v
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
cd services/recording_service_gui
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
