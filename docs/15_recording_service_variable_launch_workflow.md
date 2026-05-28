# 15. Recording Service Variable-Driven Launch Workflow

## Purpose
Define a production workflow for launching RTI Recording Service using:
- stable XML templates,
- named configurations selected by `-cfgName`, and
- runtime overrides via `-DVAR=value`.

This avoids per-run XML generation and keeps operator launches reproducible.

## Goals
- Let operators choose recording-specific options in UI/CLI.
- Map selections to validated variables.
- Launch with a compact command line (`-cfgFile`, `-cfgName`, `-D...`).
- Keep multi-instance runs safe and collision-free.

## Non-Goals
- Dynamic XML structure generation per run.
- Runtime editing of QoS XML internals.

## Core Pattern
1. Keep one stable `recording_service.xml` template with variable placeholders like `$(REC_DOMAIN_ID)`.
2. Reuse centralized system QoS from `DDS_QOS_PROFILES.xml`.
3. Put major structural choices in named service configurations (`-cfgName`).
4. Put per-launch values in configuration variables overridden with `-D...`.

## File Architecture
Recommended structure:

```text
dds/
  qos/
    recording_service.xml
    DDS_QOS_PROFILES.xml
  presets/
    record_all.json
    record_selected.json
    record_json.json
```

### Why this split
- `-cfgName` handles structural differences:
  - record-all vs selected topics
  - XCDR vs JSON_SQLITE mode
  - monitoring/admin enabled profiles
- `-D...` handles scalar runtime values:
  - domain IDs
  - paths
  - session names
  - filters
  - profile names

## Variable Naming Standard
Use `REC_` prefix, uppercase, underscore-separated.

Examples:
- `REC_DOMAIN_ID`
- `REC_ADMIN_ENABLED`
- `REC_ADMIN_DOMAIN_ID`
- `REC_MON_ENABLED`
- `REC_MON_DOMAIN_ID`
- `REC_SESSION_NAME`
- `REC_WORKSPACE_DIR`
- `REC_EXEC_DIR_EXPR`
- `REC_FILENAME_EXPR`
- `REC_STORAGE_FORMAT`
- `REC_TOPIC_ALLOW`
- `REC_TOPIC_DENY`
- `REC_DP_QOS`
- `REC_SUB_QOS`
- `REC_DR_QOS`
- `REC_ROLLOVER_ENABLED`
- `REC_ROLLOVER_MB`

## Defaulting Policy
Define defaults in XML `<configuration_variables>`.

Default classes:
1. Safe XML defaults:
   - `REC_TOPIC_DENY=rti/*`
   - `REC_STORAGE_FORMAT=XCDR_AUTO`
2. Deployment defaults from preset:
   - domain IDs
   - workspace root
   - monitoring defaults
3. Required-at-launch values:
   - output root (if site-specific)
   - operator/session label (if required)

## Variable Precedence
For RTI Services variable expansion:
1. environment variables
2. `-DVAR=value`
3. XML `<configuration_variables>` defaults

Operational guidance:
- Prefer launcher-controlled `-D...` values for reproducible launches.
- Avoid exporting conflicting `REC_*` environment variables in operator shells.

## Minimal XML Template Snippet

```xml
<?xml version="1.0" encoding="UTF-8"?>
<dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation="[NDDSHOME]/resource/schema/rti_recording_service.xsd">

  <configuration_variables>
    <value>
      <element><name>REC_DOMAIN_ID</name><value>0</value></element>
      <element><name>REC_ADMIN_ENABLED</name><value>true</value></element>
      <element><name>REC_ADMIN_DOMAIN_ID</name><value>99</value></element>
      <element><name>REC_MON_ENABLED</name><value>true</value></element>
      <element><name>REC_MON_DOMAIN_ID</name><value>99</value></element>
      <element><name>REC_SESSION_NAME</name><value>DefaultSession</value></element>
      <element><name>REC_WORKSPACE_DIR</name><value>.</value></element>
      <element><name>REC_EXEC_DIR_EXPR</name><value>recording_%ts%</value></element>
      <element><name>REC_FILENAME_EXPR</name><value>data_%auto:0%.db</value></element>
      <element><name>REC_STORAGE_FORMAT</name><value>XCDR_AUTO</value></element>
      <element><name>REC_TOPIC_ALLOW</name><value>*</value></element>
      <element><name>REC_TOPIC_DENY</name><value>rti/*</value></element>
      <element><name>REC_DP_QOS</name><value>RtiServicesLib::RecordingService</value></element>
      <element><name>REC_SUB_QOS</name><value>BuiltinQosLib::Generic.Common</value></element>
      <element><name>REC_DR_QOS</name><value>BuiltinQosLib::Generic.Common</value></element>
    </value>
  </configuration_variables>

  <recording_service name="record_all">
    <administration>
      <enabled>$(REC_ADMIN_ENABLED)</enabled>
      <domain_id>$(REC_ADMIN_DOMAIN_ID)</domain_id>
    </administration>

    <monitoring>
      <enabled>$(REC_MON_ENABLED)</enabled>
      <domain_id>$(REC_MON_DOMAIN_ID)</domain_id>
    </monitoring>

    <storage>
      <sqlite>
        <storage_format>$(REC_STORAGE_FORMAT)</storage_format>
        <fileset>
          <workspace_dir>$(REC_WORKSPACE_DIR)</workspace_dir>
          <execution_dir_expression>$(REC_EXEC_DIR_EXPR)</execution_dir_expression>
          <filename_expression>$(REC_FILENAME_EXPR)</filename_expression>
        </fileset>
      </sqlite>
    </storage>

    <domain_participant name="RecorderParticipant">
      <domain_id>$(REC_DOMAIN_ID)</domain_id>
      <domain_participant_qos base_name="$(REC_DP_QOS)"/>
    </domain_participant>

    <session name="$(REC_SESSION_NAME)">
      <subscriber_qos base_name="$(REC_SUB_QOS)"/>
      <topic_group name="RecordSelected" participant_ref="RecorderParticipant">
        <allow_topic_name_filter>$(REC_TOPIC_ALLOW)</allow_topic_name_filter>
        <deny_topic_name_filter>$(REC_TOPIC_DENY)</deny_topic_name_filter>
        <datareader_qos base_name="$(REC_DR_QOS)"/>
      </topic_group>
    </session>
  </recording_service>
</dds>
```

## Launch Command Contract
Launcher should emit only:
- `-cfgFile "recording_service.xml;DDS_QOS_PROFILES.xml"`
- `-cfgName <name>`
- `-DREC_...=...`
- optional: `-appName`, `-verbosity`, `-logFormat`

Example:

```bash
rtirecordingservice \
  -cfgFile "dds/qos/recording_service.xml;dds/qos/DDS_QOS_PROFILES.xml" \
  -cfgName record_selected \
  -DREC_DOMAIN_ID=42 \
  -DREC_WORKSPACE_DIR=/var/rti/recordings \
  -DREC_EXEC_DIR_EXPR=plantA_shiftB_%ts% \
  -DREC_FILENAME_EXPR=data_%auto:0%.db \
  -DREC_SESSION_NAME=shiftB_capture \
  -DREC_TOPIC_ALLOW=Telemetry* \
  -DREC_TOPIC_DENY=rti/* \
  -DREC_STORAGE_FORMAT=XCDR_AUTO
```

## UI Workflow (Basic + Advanced)

### Basic fields (always visible)
- Mode (`-cfgName`)
- Data Domain ID (`REC_DOMAIN_ID`)
- Output Directory (`REC_WORKSPACE_DIR`)
- Session Label (`REC_SESSION_NAME`)
- Topic Scope (`REC_TOPIC_ALLOW`)
- Storage Format (`REC_STORAGE_FORMAT`)

### Advanced fields (collapsible)
- Admin/Monitoring enable + domain IDs
- QoS profile references (`REC_DP_QOS`, `REC_SUB_QOS`, `REC_DR_QOS`)
- Deny filter (`REC_TOPIC_DENY`)
- Rollover controls
- Plugin-specific properties
- Verbosity/logging/app name

## Validation Pipeline
Pre-launch validation in launcher:
1. Required variables for selected `-cfgName`.
2. Type/range checks:
   - integer domain IDs
   - boolean `true|false`
   - numeric rollover thresholds > 0
3. Path checks:
   - directory exists or is creatable
   - writable parent
4. Enum checks:
   - allowed `REC_STORAGE_FORMAT`
5. Filter checks:
   - non-empty allow filter for selected-topic mode
6. Collision checks:
   - resolved output path uniqueness

Runtime validation:
- Keep XSD validation enabled (do not use `-ignoreXsdValidation` in normal operation).
- Provide launcher dry-run preview of resolved `-D...` and full command.

## Multi-Instance Safety
Rules:
1. Unique execution directory per launch.
2. Deterministic run ID in path and session.
3. Unique app name (`-appName`) for observability.
4. Never allow two runs to write to same effective output path.

Recommended run ID format:

```text
<site>_d<domain>_<mode>_<utc_timestamp>
```

Example usage:
- `REC_SESSION_NAME=plantA_d42_selected_20260528T154210Z`
- `REC_EXEC_DIR_EXPR=plantA_d42_selected_20260528T154210Z`

## Implementation Plan For This Repository
1. Add `dds/qos/recording_service.xml` with `record_all`, `record_selected`, and `record_json` named configs.
2. Reference existing system profiles in `dds/qos/DDS_QOS_PROFILES.xml` for `REC_*_QOS` variables.
3. Add launcher preset JSON files under `dds/presets/`.
4. Update service launch model in GUI to map form fields to `REC_*` variables.
5. Add pre-launch validation module and command preview panel.
6. Persist launch manifest JSON per run in workspace output.

## Roadmap: Live Service Admin Control

Status: baseline implemented in `rs_gui_v2` with `RtiServiceAdminClient` wired
into LIVE GUI assembly and validated by the live service churn gate. Continue to
extend operator-facing status details as new admin workflows are added.

Once process launch is reliable, wire the Record tab actions to a live DDS
Service Admin client/facade instead of leaving LIVE mode without an admin
transport.

Required work:
- Implement a live Recording Service Admin client for pause, resume, shutdown,
  and SQLite timestamp tagging.
- Use the RTI Service Admin request/reply topics on the configured
  administration domain.
- Apply QoS compatible with the system `ServiceAdministrationProfiles` request
  and reply profiles.
- Address the correct Recording Service resource identifiers, such as
  `/recording_services/<service_name>` and storage-specific resources below it.
- Correlate replies to requests and surface reply return codes, errors, and
  timeouts.
- Check service availability/readiness before enabling admin actions.
- Publish command outcomes to the GUI Console, Record command history, and
  visible status/diagnostics.

Definition of done:
- In LIVE mode, `Pause`, `Resume`, `Shutdown`, and `Tag` send DDS Service Admin
  requests to the selected launched or discovered Recording Service.
- The GUI shows whether the admin request was acknowledged, timed out, or
  rejected, including native return codes and reply messages when available.
- Local process termination remains a guarded fallback after graceful DDS
  shutdown fails.

## Operator Output Manifest
For each launch, persist:
- timestamp
- cfgName
- resolved variables
- full command line
- hostname/user
- resulting process PID

This enables reproducibility and troubleshooting without regenerating XML.

## References
- RTI Recording Service 7.7.0 documentation:
  - Configuring RTI Services
  - Recording Service Usage
  - Recording Service Configuration
- RTI MedTech reference architecture recording configuration examples.
