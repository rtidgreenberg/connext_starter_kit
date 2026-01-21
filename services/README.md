# RTI Services Configuration

Configuration files for RTI Recording, Replay, and Converter Services - capture, replay, convert, and analyze DDS data flows without modifying applications.

## Table of Contents

- [I want to record a selective group of topics](#i-want-to-record-a-selective-group-of-topics)
- [I want to record topics using external XML type definitions](#i-want-to-record-topics-using-external-xml-type-definitions)
- [I want to convert my recorded data to JSON for post-processing](#i-want-to-convert-my-recorded-data-to-json-for-post-processing)
- [I want to convert my recorded data to CSV for post-processing](#i-want-to-convert-my-recorded-data-to-csv-for-post-processing)
- [I want to replay my recorded data](#i-want-to-replay-my-recorded-data)
- [I want to replay converted JSON data](#i-want-to-replay-converted-json-data)

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
Run CMake in the `dds` folder to convert IDL files to XML format:
```bash
cd ../dds/build
cmake ..
make
# This generates XML type definitions in dds/build/xml_gen/ directory
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

**Configuration File**: `replay_service_config.xml` (uses `xcdr` configuration)

**Running**:
```bash
cd services
./start_replay.sh
```

**Playback Options**: Edit `replay_service_config.xml` to configure:
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

**Configuration File**: `replay_service_config.xml` (uses `json` configuration)

**Running**:
```bash
cd services
# First, ensure you have converted data
./start_convert.sh json

# Then replay the JSON data
./start_replay.sh json 1
```

---

## Configuration Files

| File | Purpose |
|------|---------|
| `recording_service_config.xml` | Main recording configuration - selective topic recording |
| `recording_service_config_external_types.xml` | Recording with external XML type definitions |
| `converter_service_config.xml` | Conversion configurations (XCDR to JSON/CSV) |
| `replay_service_config.xml` | Replay configurations (XCDR and JSON) |

## Scripts

| Script | Purpose |
|--------|---------|
| `start_record.sh` | Start recording service with selective topics |
| `start_record_external_types.sh` | Start recording with external XML types |
| `start_convert.sh` | Convert recorded data (supports json, csv) |
| `start_replay.sh` | Replay recorded or converted data (supports xcdr, json) |

## Prerequisites

- RTI Connext DDS 7.3.0+ with Recording, Replay, and Converter Services
- Set `NDDSHOME` environment variable pointing to your RTI Connext installation

## Directory Structure

```
services/
├── log_dir/
│   └── xcdr/                   # Recorded XCDR data (deploy mode)
│   └── <timestamped dirs>/     # Recorded JSON data (debug mode)
├── converted/
│   ├── json/                   # Converted JSON data
│   └── csv/                    # Converted CSV data
├── recording_service_config.xml
├── recording_service_config_external_types.xml
├── converter_service_config.xml
├── replay_service_config.xml
├── start_record.sh
├── start_record_external_types.sh
├── start_convert.sh
└── start_replay.sh
```

## Resources

- [RTI Recording Service Manual (7.3.0)](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/recording_service/)
- [RTI Recording Service Manual (7.3.1)](https://community.rti.com/static/documentation/connext-dds/7.3.1/doc/manuals/connext_dds_professional/services/recording_service/index.html)
- [RTI Replay Service Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/replay_service/)
- [RTI Converter Service Manual](https://community.rti.com/static/documentation/connext-dds/7.3.0/doc/manuals/connext_dds_professional/services/converter_service/)

---

## Questions or Feedback?

Reach out to us at services_community@rti.com - we welcome your questions and feedback!
