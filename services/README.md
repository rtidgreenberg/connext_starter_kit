# RTI Services Configuration

Configuration files for RTI Recording, Replay, and Converter Services - capture, replay, convert, and analyze DDS data flows without modifying applications.

## Table of Contents

- [RTI Services Configuration](#rti-services-configuration)
  - [Table of Contents](#table-of-contents)
  - [I want to control Recording and Replay Services with a GUI](#i-want-to-control-recording-and-replay-services-with-a-gui)
  - [Command-line service scripts](#command-line-service-scripts)
  - [I want to record a selective group of topics](#i-want-to-record-a-selective-group-of-topics)
  - [I want to record topics using external XML type definitions](#i-want-to-record-topics-using-external-xml-type-definitions)
  - [I want to convert my recorded data to JSON for post-processing](#i-want-to-convert-my-recorded-data-to-json-for-post-processing)
  - [I want to convert my recorded data to CSV for post-processing](#i-want-to-convert-my-recorded-data-to-csv-for-post-processing)
  - [I want to replay my recorded data](#i-want-to-replay-my-recorded-data)
  - [I want to replay converted JSON data](#i-want-to-replay-converted-json-data)
  - [Tests](#tests)
  - [Configuration Files](#configuration-files)
  - [Scripts](#scripts)
  - [Prerequisites](#prerequisites)
  - [Directory Structure](#directory-structure)
  - [Resources](#resources)
  - [Questions or Feedback?](#questions-or-feedback)

---

## I want to control Recording and Replay Services with a GUI

**Objective**: Launch, monitor, pause/resume, tag, replay, and shut down RTI Recording and Replay Services from a Python tkinter desktop GUI.

Use the GUI when you want an operator-friendly workflow for live capture and playback without manually coordinating service processes and Admin Console commands.

**What the GUI supports**:
- Launch Recording Service with selectable domains, configuration files, topic allow/deny filters, verbosity, and storage settings.
- Monitor GUI-launched and discovered Recording/Replay Service processes, including state, ownership, host, PID, uptime, readiness, output logs, and live DDS monitoring data.
- Control process lifecycle from the desktop: pause, resume, stop, request graceful shutdown, terminate local processes, and clean up GUI-launched services on close.
- Send tags to Recording Service so operators can mark items or time ranges of interest while data is being captured.
- Launch Replay Service against recorded databases, choose playback settings, and control replay start/pause/resume/stop/shutdown from the Replay tab.
- Inspect replay readiness, playback status, database path, progress, and monitoring details while replay is running.

**Running**:
```bash
cd services/rs_gui
./run_rs_gui.sh
```

See [rs_gui/README.md](rs_gui/README.md) for prerequisites, setup, troubleshooting, and usage details.

---

## Command-line service scripts

Use these scripts when you want repeatable terminal workflows for Recording, Replay, and Converter Services, or when you are running automation without the GUI.

Available scripts:
- `start_record.sh` starts Recording Service with selective topics or debug recording.
- `start_record_external_types.sh` starts Recording Service with external XML type definitions.
- `start_convert.sh` converts recorded data to JSON or CSV.
- `start_replay.sh` replays XCDR or converted JSON data.

---

## I want to record a selective group of topics

**Objective**: Auto-discover and record specific application topics while filtering out RTI internal topics.

**What Gets Recorded**:
- ✅ Application topics: `Button`, `Command`, `Position`
- ❌ RTI internal topics: `rti/*`

**Configuration File**: `recording_service_config.xml` (uses `deploy` configuration)

**Running**:
```bash
cd services
./start_record.sh
# Or explicitly: ./start_record.sh deploy
```

**Output**: Recorded data is stored in `log_dir/xcdr/`

**Alternative - Debug Mode**: To record all topics in JSON format for easy review:
```bash
./start_record.sh debug
```
This records all topics (except `rti/*`) in JSON format to `log_dir/` with timestamped directories and 5GB file rollover.

**Configuration Variables**: You can override settings by exporting environment variables in the script:
```bash
# Example: Change domain ID
export DOMAIN_ID=5
```

---

## I want to record topics using external XML type definitions

**Objective**: Record topics from external DDS applications (e.g., ROS2, third-party systems) using XML type definitions when data type has not been propagated in discovery (default for most open source DDS).

**Scenario**: Recording the `Button` topic using an external XML type definition instead of the generated IDL.

**What Gets Recorded**:
- ✅ Application topics: `Button` (using external XML type)

**Configuration File**: `recording_service_config_external_types.xml`

**Prerequisites**: 
Run the top-level build to generate XML type definitions:
```bash
cd /path/to/connext_starter_kit
mkdir -p build && cd build
cmake .. && cmake --build .
# This generates XML type definitions in build/dds/xml_gen/ directory
```

**Running**:
```bash
cd services
./start_record_external_types.sh
```

**Output**: Recorded data is stored in `log_dir/` with timestamped directories

---

## I want to convert my recorded data to JSON for post-processing

**Objective**: Convert recorded XCDR data to JSON format for analysis, debugging, or integration with other tools.

**Input**: Recorded data from `log_dir/xcdr/`

**Output**: Converted JSON data in `converted/json/` directory

**Configuration File**: `converter_service_config.xml` (uses `json` configuration)

**Running**:
```bash
cd services
./start_convert.sh json
# Or simply: ./start_convert.sh (json is the default)
```

**Optional**: Specify a different domain ID:
```bash
./start_convert.sh json 1
```

---

## I want to convert my recorded data to CSV for post-processing

**Objective**: Convert recorded XCDR data to CSV format for spreadsheet analysis or data science workflows.

**Input**: Recorded data from `log_dir/xcdr/`

**Output**: Converted CSV files in `converted/csv/` directory

**Configuration File**: `converter_service_config.xml` (uses `csv` configuration)

**Running**:
```bash
cd services
./start_convert.sh csv
```

**Optional**: Specify a different domain ID:
```bash
./start_convert.sh csv 1
```

**Note**: By default, CSV files are created per topic. To merge all data into a single CSV file, modify the `CSV_MERGE_FILES` variable in `converter_service_config.xml`.

---

## I want to replay my recorded data

**Objective**: Replay recorded XCDR data back onto the DDS network for testing, validation, or simulation.

**Input**: Recorded data from `log_dir/xcdr/`

**What Gets Replayed**:
- ✅ Application topics: `Button`, `Command`, `Position`
- ❌ RTI internal topics: `rti/*`

**Configuration File**: `dds/qos/replay_service.xml` (uses `xcdr` configuration)

**Running**:
```bash
cd services
./start_replay.sh
```

**Playback Options**: Edit `dds/qos/replay_service.xml` to configure:
- Playback rate (speed multiplier)
- Looping behavior
- Time range selection
- Timestamp ordering (reception vs. source timestamp)

---

## I want to replay converted JSON data

**Objective**: Replay JSON-formatted data back onto the DDS network (useful after modifying or analyzing JSON data).

**Input**: Converted JSON data from `converted/json/`

**What Gets Replayed**:
- ✅ Application topics: `Button`, `Command`, `Position`
- ❌ RTI internal topics: `rti/*`

**Prerequisites**: First convert your recorded data to JSON (see [convert to JSON](#i-want-to-convert-my-recorded-data-to-json-for-post-processing))

**Configuration File**: `dds/qos/replay_service.xml` (uses `json` configuration)

**Running**:
```bash
cd services
# First, ensure you have converted data
./start_convert.sh json

# Then replay the JSON data
./start_replay.sh json 1
```

## Tests

End-to-end tests for the services start scripts live in `test/`:

```bash
cd services

# Run services E2E tests (7 tests: record → convert CSV → replay)
python3 test/run_all_tests.py -v

# Run a specific test standalone
python3 test/test_e2e_services.py -v
```

See [test/README.md](test/README.md) for details on the test pipeline.

GUI-specific tests (unit, widget, integration, E2E tags) live in
[rs_gui/test/](rs_gui/test/README.md).

---

## Configuration Files

| File | Purpose |
|------|---------|
| `recording_service_config.xml` | Main recording configuration - selective topic recording |
| `recording_service_config_external_types.xml` | Recording with external XML type definitions |
| `converter_service_config.xml` | Conversion configurations (XCDR to JSON/CSV) |
| `dds/qos/replay_service.xml` | Replay configurations (XCDR and JSON) |

## Scripts

| Script | Purpose |
|--------|---------|
| `start_record.sh` | Start recording service with selective topics |
| `start_record_external_types.sh` | Start recording with external XML types |
| `start_convert.sh` | Convert recorded data (supports json, csv) |
| `start_replay.sh` | Replay recorded or converted data (supports xcdr, json) |

## Prerequisites

- RTI Connext DDS 7.3.0+ with Recording, Replay, and Converter Services for command-line scripts
- Python 3.10 and `rti.connext==7.7.*` from PyPI for the `rs_gui` Python GUI
- Set `NDDSHOME` environment variable pointing to your RTI Connext installation

## Directory Structure

```
services/
├── test/
│   ├── run_all_tests.py            # Services test suite runner
│   ├── test_e2e_services.py        # E2E: record → convert → replay
│   └── README.md
├── log_dir/
│   └── xcdr/                   # Recorded XCDR data (deploy mode)
│   └── <timestamped dirs>/     # Recorded JSON data (debug mode)
├── converted/
│   ├── json/                   # Converted JSON data
│   └── csv/                    # Converted CSV data
├── recording_service_config.xml
├── recording_service_config_external_types.xml
├── converter_service_config.xml
├── ../dds/qos/replay_service.xml
├── start_record.sh
├── start_record_external_types.sh
├── start_convert.sh
├── start_replay.sh
└── rs_gui/                      # tkinter GUI, monitoring, and tests
```

## Resources

- [RTI Recording Service Manual (7.3.0)](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/recording_service/)
- [RTI Recording Service Manual (7.6.0)](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/services/recording_service/index.html)
- [RTI Replay Service Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/replay_service/)
- [RTI Converter Service Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/converter_service/)

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
