# Recording Service Remote Control (Python)

Remotely control a running RTI Recording Service instance using the common
Remote Administration Platform. This Python application uses **DynamicData** and
the **Request/Reply** pattern to send commands — no C++ compilation needed.

Based on the [C++ service admin example](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/recording_service/service_admin/c%2B%2B11).

## How it Works

1. **`setup.sh`** uses `rtiddsgen -convertToXML` to convert the RTI-provided IDL
   files (`ServiceAdmin.idl`, `ServiceCommon.idl`, `RecordingServiceTypes.idl`)
   into XML type descriptions. It also installs `sqlite3` (needed by
   `rtirecordingservice_list_tags`).
2. The Python script loads these XML types via `QosProvider`, builds
   `DynamicData` samples matching the `CommandRequest`/`CommandReply` types, and
   uses `rti.request.Requester` to send commands and receive replies.
3. For timestamp tags, `DataTagParams` is serialized to CDR via
   `DynamicData.to_cdr_buffer()` and placed into the request's `octet_body`.

## Prerequisites

- RTI Connext DDS 7.x with Python bindings installed
- Virtual environment set up (`apps/python/install.sh`)
- Recording Service running with remote administration enabled

## Setup

```bash
# Generate XML type files from IDL and install dependencies (one-time)
./setup.sh
```

The setup script will:
- Auto-detect `$NDDSHOME` if not set
- Convert IDL type definitions to XML using `rtiddsgen -convertToXML`
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
| `recording_service_control.py` | Main Python application |
| `setup.sh` | Converts IDL → XML type files using `rtiddsgen`, installs `sqlite3` |
| `run.sh` | Convenience wrapper (env setup + run) |
| `ServiceAdmin_QOS_PROFILES.xml` | QoS profiles matching the service's admin QoS |
| `xml_types/` | Generated XML type files (created by `setup.sh`) |
| `test/` | End-to-end test files (config, publisher, instructions) |

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

The `ServiceAdmin_QOS_PROFILES.xml` in this directory contains the QoS
profiles used by this control application for QoS matching with the service.

## Supported Commands

| Command | Action | Resource Path |
|---------|--------|---------------|
| `start` | UPDATE | `/recording_services/<name>/state` → `"running"` |
| `pause` | UPDATE | `/recording_services/<name>/state` → `"paused"` |
| `shutdown` | DELETE | `/recording_services/<name>` |
| `tag` | UPDATE | `/recording_services/<name>/storage/sqlite:tag_timestamp` |

## End-to-End Test

The `test/` directory contains everything needed for a full end-to-end
verification: a Recording Service config with remote admin enabled, and a
simple DDS publisher.

### Step 1 — Run setup

```bash
cd services/python_control
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
