# Recording Service GUI — Tests

Unit, widget, and integration tests for the Recording Service GUI, monitoring
subscriber, and remote admin controller.

> **Tip:** Services-level E2E tests for the start scripts (`start_record.sh`,
> `start_convert.sh`, `start_replay.sh`) live in
> [`services/test/`](../../test/README.md).

## Running Tests

```bash
cd services/recording_service_gui

# Run the GUI test suite (94 tests, includes E2E tags)
../../connext_dds_env/bin/python test/run_all_tests.py -v

# Run an individual test file
../../connext_dds_env/bin/python test/test_monitoring.py -v
../../connext_dds_env/bin/python test/test_gui.py -v
../../connext_dds_env/bin/python test/test_control.py -v
../../connext_dds_env/bin/python test/test_e2e_tags.py -v

# Run with pytest (skip DDS integration tests)
../../connext_dds_env/bin/python -m pytest test/ -v -k "not Integration"
```

`test/run_all_tests.py` will re-exec itself with `../../connext_dds_env/bin/python`
if it is started with a different interpreter.

> **Note:** Integration tests require `rti.connextdds`, generated type files
> (`setup.sh`), and a display for tkinter. They are automatically skipped when
> those dependencies are unavailable.

## Test Files

| File | Module Under Test | Tests |
|------|-------------------|-------|
| `test_monitoring.py` | `recording_service_monitor.py` | Typed sample parsing, callback plumbing, DDS reader creation |
| `test_gui.py` | `recording_service_gui.py` | Pure helpers, widget interactions, queue draining, lifecycle |
| `test_control.py` | `recording_service_control.py` | Constants, CLI parsing, resource paths, DDS construction |
| `test_e2e_tags.py` | `recording_service_control.py` | Full E2E: start recorder, publish data, set tags, shutdown, verify in DB |
| `run_all_tests.py` | — | Suite runner — discovers and runs all `test_*.py` files |

## Test Layers

Each test file follows a layered approach so most tests run without DDS or a
display:

### Layer 1 — Pure Logic (no DDS, no tkinter)

Exercises helper functions, constants, and parsing logic using mock objects.
Runs everywhere, no special dependencies.

**`test_monitoring.py`:**
- `TestParseConfigSample` — service-level and topic-level config parsing
- `TestParseEventSample` — state changes (RUNNING, PAUSED), rollover count
- `TestParsePeriodicSample` — uptime, CPU, memory, DB file/size
- `TestEmitCallback` — callback invocation, exception swallowing, error emission

**`test_gui.py`:**
- `TestParseConfigNames` — XML config file parsing
- `TestBuildLaunchCommand` — launch command construction
- `TestDetectTerminalEmulator` — terminal emulator detection
- `TestFormatFileSize` — byte formatting (B, KB, MB, GB)
- `TestFormatUptime` — seconds to human-readable duration
- `TestDetectNddshome` — NDDSHOME auto-detection

**`test_control.py`:**
- `TestConstants` — IDL-derived action/retcode values
- `TestActionName` — action name helper
- `TestCLIParsing` — CLI argument parsing via `main()`
- `TestResourcePaths` — resource path construction for commands

### Layer 2 — Widget / Mock-DDS Tests

**`test_gui.py` → `TestWidgets`:**
Requires tkinter (headless display OK). Uses `_skip_dds=True` to avoid DDS.
Covers config panel, button states, state display, tags, log panel, queue
draining, and lifecycle.

### Layer 3 — Integration Tests (require `rti.connextdds`)

Skipped automatically when DDS libraries or generated types are unavailable.

**`test_monitoring.py` → `TestIntegration`:**
Creates a real `RecordingServiceMonitor` with DDS readers on a high domain ID.

**`test_gui.py` → `TestIntegration`:**
Creates a full GUI with live DDS monitoring; verifies domain-change restarts.

**`test_control.py` → `TestDDSConstruction`:**
Creates a real `RecordingServiceController` with DDS objects; tests
idempotent `close()` and missing XML error handling.

## End-to-End Tag Test (`test_e2e_tags.py`)

Fully automated end-to-end test that verifies the complete tag workflow:

1. Cleans any previous `test_recording/` database
2. Starts Recording Service in the background (`test_recorder_config.xml`)
3. Publishes DDS samples so the recorder has data
4. Sends tag commands via `RecordingServiceController`
5. Shuts down Recording Service via DDS admin command
6. Verifies tags in SQLite directly (`metadata.db → SymbolicTimestamps`)
7. Verifies tags via `rtirecordingservice_list_tags` utility

```bash
# Run the E2E test standalone
../../connext_dds_env/bin/python test/test_e2e_tags.py -v
```

Skipped automatically when `rtirecordingservice`, XML type files, or
`rti.connextdds` are unavailable.

## E2E Test Assets

| File | Purpose |
|------|--------|
| `test_publisher.py` | Publishes `TestMessage` samples on domain 0 for Recording Service to capture |
| `test_recorder_config.xml` | Recording Service config with remote admin enabled on domain 0 |
| `test_recording/` | Runtime output directory — SQLite databases created by Recording Service |

## Manual E2E Procedure

The same flow can be run manually across separate terminals for debugging
or demonstration purposes.

### Step 1 — Generate type files

```bash
cd services/recording_service_gui
./setup.sh
```

### Step 2 — Start Recording Service

```bash
$NDDSHOME/bin/rtirecordingservice \
    -cfgFile test/test_recorder_config.xml \
    -cfgName remote_admin \
    -verbosity WARN
```

The config enables remote administration on domain 0 and records all topics
into an SQLite database under `test/test_recording/`.

### Step 3 — Publish test data

In a second terminal:

```bash
source ../../connext_dds_env/bin/activate
cd test
python3 test_publisher.py
```

Publishes 20 samples of a `TestMessage` type on domain 0.

### Step 4 — Send tag commands

In a third terminal:

```bash
./run.sh tag "test_event_1" --tag-description "First test event marker"
./run.sh tag "test_event_2" --tag-description "Second test event marker"
```

Expected output for each command:

```
Reply 1: retcode=OK, native_retcode=0, string_body=".../storage/sqlite:tag_timestamp: invoked tag_timestamp operation"
```

### Step 5 — Stop Recording Service

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
sqlite3 test/test_recording/metadata.db \
    "SELECT tag_name, tag_description FROM SymbolicTimestamps;"
```

### Cleanup

```bash
rm -rf test/test_recording
```
