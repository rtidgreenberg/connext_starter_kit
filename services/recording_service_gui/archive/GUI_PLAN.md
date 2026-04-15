# Recording Service GUI — Design Plan

## Goal

Provide a **tkinter GUI** alongside the existing headless CLI that lets a user:

1. **Configure** Recording Service launch parameters (env vars, config name, verbosity, etc.)
2. **Launch** Recording Service in a separate terminal window
3. **Monitor** Recording Service status by subscribing to DDS monitoring topics (not managing the process directly)
4. **Control** the running service via remote admin commands (start/pause/tag/shutdown)
5. **View tags** that have been set during the recording session

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  recording_service_gui.py                │
│                                                          │
│  ┌─────────────────────┐   ┌──────────────────────────┐  │
│  │  Configuration      │   │  Status Monitor          │  │
│  │  Panel (left)       │   │  Panel (right)           │  │
│  │                     │   │                           │  │
│  │  - Config File      │   │  - Service State         │  │
│  │  - Config Name      │   │    (RUNNING/PAUSED/etc)  │  │
│  │  - Domain ID        │   │  - Uptime                │  │
│  │  - Admin Domain ID  │   │  - CPU / Memory          │  │
│  │  - Verbosity        │   │  - Current DB File       │  │
│  │  - Topic Filter     │   │  - Current File Size     │  │
│  │  - NDDSHOME         │   │  - Topics Being Recorded │  │
│  │  - Log Directory    │   │  - Rollover Count        │  │
│  └─────────────────────┘   └──────────────────────────┘  │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Control Bar                                        │  │
│  │  [Launch Service]  [Pause] [Resume] [Shutdown]      │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────┐  ┌──────────────────────────┐  │
│  │  Tag Panel           │  │  Log Panel               │  │
│  │                      │  │                           │  │
│  │  Tag Name: [______]  │  │  (scrolling text box of   │  │
│  │  Description: [___]  │  │   command responses and   │  │
│  │  [Set Tag]           │  │   monitoring events)      │  │
│  │                      │  │                           │  │
│  │  Tag History Table:  │  │                           │  │
│  │  name | time | desc  │  │                           │  │
│  └──────────────────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## Configuration Panel — Fields & Constraints

| Field | Widget | Default | Allowed Values / Notes |
|-------|--------|---------|----------------------|
| **NDDSHOME** | Text entry + auto-detect | Auto-detect `~/rti_connext_dds-*` | Free text; validated as directory |
| **Config File** | File chooser (Browse) | `../recording_service_config.xml` | Must exist; populates Config Name dropdown |
| **Config Name** | Dropdown (ComboBox) | `deploy` | **Parsed from the selected XML file** — extracts all `<recording_service name="...">` values |
| **Domain ID** | Spinbox (0–232) | `1` | Integer; sets `DOMAIN_ID` env var or `-DDOMAIN_ID=X` |
| **Admin Domain ID** | Spinbox (0–232) | `0` | Integer; domain for remote admin + monitoring subscriptions. Matches `$(ADMIN_DOMAIN_ID)` in config. |
| **Verbosity** | Dropdown | `ERROR:ERROR` | `SILENT`, `ERROR`, `WARN`, `LOCAL`, `REMOTE` for both service and DDS levels, formatted as `service:dds` |
| **Topic Filter** | Text entry | `*` (record all) | Comma-separated topic names or wildcard patterns |
| **Log Directory** | Directory chooser | `log_dir` | Free text + Browse button |

### How Config Names Are Populated

When the user selects a config XML file, the GUI will parse it with `xml.etree.ElementTree`, find all `<recording_service name="X">` elements, and populate the Config Name dropdown with those names. This way the dropdown is always accurate to the file's contents.

### How Recording Service Is Launched

The GUI builds a command and opens it in a **new terminal window** (via `gnome-terminal --`, `xterm -e`, etc. depending on what's available). The GUI does **not** manage the process — it just fires the launch command:

```bash
# Constructed by the GUI — all config overrides passed as -D flags
# so the full command is visible, copy-pasteable, and reproducible:
$NDDSHOME/bin/rtirecordingservice \
    -cfgFile <config_file> \
    -cfgName <config_name> \
    -DDOMAIN_ID=<value> \
    -DADMIN_DOMAIN_ID=<value> \
    -verbosity <verbosity>
```

Using `-DVAR=value` on the command line (rather than environment variables) means the user can see exactly what was run in the terminal's scrollback and re-run the same command manually. The `-D` syntax overrides `<configuration_variables>` in the XML, just like `export VAR=value` would.

The GUI also logs the full command string in its Log Panel for easy copy/paste.

After launching, the GUI watches for the service to appear on DDS by subscribing to the monitoring topics.

---

## Status Monitoring — DDS Subscription Approach

> **Reference implementation**: [rticonnextdds-examples / routing_service / monitoring / c++11](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/routing_service/monitoring/c%2B%2B11)
>
> That C++ example subscribes to the same three well-known monitoring topics
> and demonstrates the pattern we will follow in Python: create three
> DataReaders (one per topic), use the Config reader as a lookup table keyed
> by instance handle, and switch on the `ResourceKind` discriminator to
> extract Recording-Service-specific fields.

Instead of managing the Recording Service process directly, the GUI subscribes to the **well-known monitoring topics** published by Recording Service when `<monitoring>` is enabled:

| Topic Name | Type | What It Provides |
|------------|------|-----------------|
| `rti/service/monitoring/config` | `RTI::Service::Monitoring::Config` | One-time: service name, application GUID, host info, SQLite config (db_directory, execution_dir), participant names |
| `rti/service/monitoring/event` | `RTI::Service::Monitoring::Event` | On state change: `EntityStateKind` = RUNNING / PAUSED / STOPPED / etc., SQLite events (current_db_directory, rollover_count) |
| `rti/service/monitoring/periodic` | `RTI::Service::Monitoring::Periodic` | Periodic (every ~1s): host CPU/memory, process CPU/memory/uptime, current SQLite file path + size, current timestamp |

### QoS Profiles for Monitoring Subscription

Following the reference example's `USER_QOS_PROFILES.xml`, we need three distinct QoS profiles for the monitoring readers. These will be added to a new `MonitoringSubscriber_QOS_PROFILES.xml`:

| Profile | Base QoS | Durability | Rationale |
|---------|----------|------------|-----------|
| `config_Profile` | `BuiltinQosLib::Generic.KeepLastReliable` | `TRANSIENT_LOCAL` | Config samples are published once; late-joiner must receive them |
| `event_Profile` | `BuiltinQosLib::Generic.StrictReliable` | `TRANSIENT_LOCAL` | State-change events must not be lost; late-joiner gets last state |
| `periodic_Profile` | `BuiltinQosLib::Generic.BestEffort` | (default) | Periodic stats are high-frequency, loss-tolerant |

All three profiles also set `pool_buffer_max_size = 4096` for unbounded type support (matching the reference example).

### Monitoring Implementation

1. **setup.sh is extended** to also run `rtiddsgen -convertToXML` on the monitoring IDL files to generate **XML type definitions**. Python typed classes generated by `rtiddsgen -language python` use `idl.xtypes_compliance` which is not available prior to `rti.connext 7.3.1` (resolved in 7.3.1), so we use **DynamicData + QosProvider** instead — the same proven pattern already used by the admin commands.
   
   ```bash
   # In setup.sh, add (alongside existing XML generation):
   MONITORING_IDL_FILES=("ServiceMonitoring.idl" "RecordingServiceMonitoring.idl"
                         "RoutingServiceMonitoring.idl" "ServiceCommon.idl")
   for idl in "${MONITORING_IDL_FILES[@]}"; do
       "$RTIDDSGEN" -convertToXml -d "$XML_OUT_DIR" -I "$IDL_DIR" "$IDL_DIR/$idl" -replace
   done
   # Post-process: strip unsupported 'deprecated' attribute from generated XML
   (# JIRA CORE-11987)
   sed -i 's/ deprecated="true"//g' "$XML_OUT_DIR"/*.xml
   ```

2. The GUI creates a `DomainParticipant` on the **admin domain** (same domain as the Recording Service's `<administration><domain_id>`) and creates **three DynamicData DataReaders** — one for each monitoring topic:

   ```python
   # DynamicData approach — types loaded from XML via QosProvider
   type_provider = dds.QosProvider(xml_types_dir + "/ServiceMonitoring.xml")
   config_type = type_provider.type("RTI::Service::Monitoring::Config")
   event_type  = type_provider.type("RTI::Service::Monitoring::Event")
   periodic_type = type_provider.type("RTI::Service::Monitoring::Periodic")

   participant = dds.DomainParticipant(admin_domain_id)

   config_topic = dds.DynamicData.Topic(participant, "rti/service/monitoring/config",
                                         config_type)
   event_topic  = dds.DynamicData.Topic(participant, "rti/service/monitoring/event",
                                         event_type)
   periodic_topic = dds.DynamicData.Topic(participant, "rti/service/monitoring/periodic",
                                           periodic_type)

   # Readers with appropriate QoS
   config_reader   = dds.DynamicData.DataReader(subscriber, config_topic,
                                    qos_provider.datareader_qos("config_Profile"))
   event_reader    = dds.DynamicData.DataReader(subscriber, event_topic,
                                    qos_provider.datareader_qos("event_Profile"))
   periodic_reader = dds.DynamicData.DataReader(subscriber, periodic_topic,
                                    qos_provider.datareader_qos("periodic_Profile"))
   ```

3. **Config reader as lookup table** (key pattern from the reference example):
   When processing `event` or `periodic` samples, use the sample's `instance_handle` to look up the corresponding `config` sample. This gives context (service name, resource_id, etc.) for the metrics:

   ```python
   def get_config(config_reader, instance_handle):
       """Look up the config sample for a given instance handle (DynamicData)."""
       samples = config_reader.select().instance(instance_handle).read()
       if len(samples) == 0:
           return None  # Config not yet received
       return samples[-1].data  # latest DynamicData config sample
   ```

4. **ResourceKind discriminator switching** (key pattern from the reference example):
   Each monitoring sample contains a union discriminated by `ResourceKind`. We filter for `RECORDING_SERVICE`, `RECORDING_SESSION`, `RECORDING_TOPIC_GROUP`, and `RECORDING_TOPIC`:

   ```python
   # Processing periodic data — switch on ResourceKind discriminator (DynamicData)
   # The RECORDING_SERVICE ResourceKind enum value is 20000
   RECORDING_SERVICE = 20000
   RECORDING_TOPIC = 20003

   for sample in periodic_reader.take():
       if not sample.info.valid:
           continue
       value_union = sample.data["value"]
       kind = value_union.discriminator_value
       if kind == RECORDING_SERVICE:
           svc = value_union["recording_service"]
           update_cpu(svc["process.cpu_usage_percentage.publication_period_metrics.mean"])
           update_uptime(svc["process.uptime_sec"])
           update_db_file(svc["builtin_sqlite.current_file"])
           update_db_size(svc["builtin_sqlite.current_file_size"])
       elif kind == RECORDING_TOPIC:
           config = get_config(config_reader, sample.info.instance_handle)
           if config:
               topic_name = config["value"]["recording_topic"]["topic_name"]
               update_topic_list(topic_name)
   ```

5. A `tkinter.after(500)` polling loop calls `take()` on the event and periodic readers, and `read()` on the config reader, updating GUI labels each cycle.

6. **State detection**: When an `Event` sample arrives with `ResourceKind == RECORDING_SERVICE`, we read `event.state` (`EntityStateKind` enum: `RUNNING`, `PAUSED`, `STOPPED`, `ENABLED`, `DISABLED`). This drives the GUI button states and status indicator.

7. If no samples arrive within a timeout (e.g., 10s after launch), the GUI shows "Service Not Detected" — which could mean monitoring isn't enabled in the config, the admin domain is wrong, or the service failed to start.

### Status Panel Fields (Updated from Monitoring Data)

| Field | Source | Update Frequency |
|-------|--------|-----------------|
| Service State | `Event.value.recording_service.state` | On change |
| Service Name | `Config.value.recording_service.application_name` | Once |
| Host Name | `Config.value.recording_service.host.name` | Once |
| DB Directory | `Config.value.recording_service.builtin_sqlite.db_directory` | Once |
| Uptime | `Periodic.value.recording_service.process.uptime_sec` | ~1s |
| CPU Usage | `Periodic.value.recording_service.process.cpu_usage_percentage.mean` | ~1s |
| Memory (KB) | `Periodic.value.recording_service.process.physical_memory_kb.mean` | ~1s |
| Current DB File | `Periodic.value.recording_service.builtin_sqlite.current_file` | ~1s |
| DB File Size | `Periodic.value.recording_service.builtin_sqlite.current_file_size` | ~1s |
| Rollover Count | `Event.value.recording_service.builtin_sqlite.rollover_count` | On change |
| Recorded Topics | `Config.value.recording_topic.topic_name` (per instance) | On discovery |

---

## Control Bar — Remote Admin Commands

Uses the existing `RecordingServiceController` class from `recording_service_control.py` (reused as a module, not forked):

| Button | Action | Notes |
|--------|--------|-------|
| **Launch Service** | Opens Recording Service in a new terminal | Only enabled when no service detected on monitoring topics |
| **Pause** | `controller.pause()` | Only enabled when state = RUNNING |
| **Resume** | `controller.start()` | Only enabled when state = PAUSED |
| **Shutdown** | `controller.shutdown()` | Only enabled when service is detected; confirmation dialog |

Button states are driven by the monitoring subscription — they enable/disable based on the observed `EntityStateKind`.

Commands are sent via a **background thread** (to avoid blocking the tkinter main loop) with results posted back to the log panel.

---

## Tag Panel

| Element | Description |
|---------|-------------|
| **Tag Name** field | Text entry, required |
| **Tag Description** field | Text entry, optional |
| **[Set Tag]** button | Calls `controller.tag_timestamp(name, desc)` in a background thread |
| **Tag History** table | `ttk.Treeview` showing all tags set in this session: name, timestamp, description |

Tags are tracked locally in the GUI (appended to the table on each successful tag command). The list can optionally be verified against the SQLite database using `rtirecordingservice_list_tags` after shutdown.

---

## Log Panel

A scrollable `tk.Text` widget (read-only) that shows:
- Launch command that was executed
- Remote admin command requests and replies
- Monitoring state change events
- Errors and warnings
- Timestamped entries

---

## File Structure (New / Modified)

```
services/recording_service_gui/
├── recording_service_control.py          # UNCHANGED — reused as module
├── recording_service_gui.py              # NEW — tkinter GUI application
├── run_gui.sh                            # NEW — convenience launcher for GUI
├── setup.sh                              # MODIFIED — also generates monitoring XML
│                                         #   types via rtiddsgen -convertToXML
├── run.sh                                # UNCHANGED
├── ServiceAdmin_QOS_PROFILES.xml         # UNCHANGED
├── MonitoringSubscriber_QOS_PROFILES.xml # NEW — QoS for monitoring readers
│                                         #   (config=KeepLastReliable+TRANSIENT_LOCAL,
│                                         #    event=StrictReliable+TRANSIENT_LOCAL,
│                                         #    periodic=BestEffort)
├── README.md                             # MODIFIED — add GUI section
├── xml_types/                            # existing + NEW monitoring XML types
│   ├── ServiceAdmin.xml                  #   (existing)
│   ├── ServiceCommon.xml                 #   (existing, also used by monitoring)
│   ├── RecordingServiceTypes.xml         #   (existing)
│   ├── ServiceMonitoring.xml             #   NEW — top-level monitoring types
│   ├── RecordingServiceMonitoring.xml    #   NEW — recording-specific monitoring
│   └── RoutingServiceMonitoring.xml      #   NEW — required include (unused types)
├── test/                                 # UNCHANGED
└── test_gui.py                           # NEW — automated GUI logic tests
```

---

## Test Strategy — `test_gui.py`

Automated tests that validate GUI logic **without requiring a running Recording
Service or a visible display** (uses `Xvfb` or headless tkinter). Tests are
structured into three layers:

### 1. Pure Logic Tests (no tkinter, no DDS)

Test helper functions in isolation:

| Test | What It Validates |
|------|-------------------|
| `test_parse_config_names` | Parses a recording service XML file and extracts all `<recording_service name="...">` values |
| `test_parse_config_names_missing_file` | Returns empty list / raises on missing file |
| `test_build_launch_command` | Given config file, config name, domain ID, admin domain ID, verbosity → produces correct command list with `-D` flags |
| `test_build_launch_command_defaults` | Verifies default values are applied correctly |
| `test_detect_terminal_emulator` | Verifies detection order (gnome-terminal → xfce4-terminal → xterm → x-terminal-emulator) |
| `test_format_file_size` | Human-readable size formatting (bytes → KB/MB/GB) |
| `test_format_uptime` | Seconds → "Xh Ym Zs" formatting |

### 2. Widget Tests (tkinter, no DDS)

Programmatically create the GUI and test widget interactions using `tkinter`'s
`.invoke()`, `.get()`, `.set()`, and `.event_generate()` methods:

| Test | What It Validates |
|------|-------------------|
| `test_config_file_populates_dropdown` | Selecting a config XML file populates the Config Name combobox with correct values |
| `test_domain_id_spinbox_range` | Domain ID spinbox enforces 0–232 range |
| `test_launch_button_builds_command` | Launch button is enabled at startup; clicking it logs the correct command string |
| `test_button_states_no_service` | Before service detected: Launch=enabled, Pause/Resume/Shutdown=disabled |
| `test_button_states_running` | When state set to RUNNING: Launch=disabled, Pause=enabled, Resume=disabled, Shutdown=enabled |
| `test_button_states_paused` | When state set to PAUSED: Launch=disabled, Pause=disabled, Resume=enabled, Shutdown=enabled |
| `test_tag_requires_name` | Set Tag button is disabled or shows error when tag name is empty |
| `test_tag_adds_to_history` | After simulated successful tag, entry appears in the tag history treeview |
| `test_log_panel_append` | Log messages are appended with timestamps and auto-scroll to bottom |

### 3. Integration Smoke Test (tkinter + DDS, optional)

Only runs if `rti.connextdds` is importable and DDS types are generated:

| Test | What It Validates |
|------|-------------------|
| `test_monitoring_readers_created` | DomainParticipant and three DataReaders are created without error |
| `test_controller_initialization` | `RecordingServiceController` initializes with XML types loaded |

### Running the Tests

```bash
# From services/recording_service_gui/
# Pure logic + widget tests (no DDS required):
python3 -m pytest test_gui.py -v -k "not integration"

# All tests including DDS integration:
python3 -m pytest test_gui.py -v

# Or without pytest:
python3 test_gui.py
```

The widget tests create a `tk.Tk()` root window but never call `mainloop()` —
they use `root.update()` / `root.update_idletasks()` to process events
synchronously. This works headless on CI with `Xvfb` or `DISPLAY=:99`.

### Test Architecture

To make widget tests possible, the GUI code separates concerns:

```python
# recording_service_gui.py structure:
class RecordingServiceGUI:
    def __init__(self, root, ...):
        # All widget creation
        ...

    # --- Testable methods ---
    def set_service_state(self, state: str):    # Updates labels + button states
    def append_log(self, message: str):          # Adds timestamped log entry
    def add_tag_to_history(self, name, ts, desc): # Adds row to treeview
    def build_launch_command(self) -> list:      # Returns command list
    def parse_config_names(self, path) -> list:  # Returns config names from XML
```

This means tests can instantiate `RecordingServiceGUI`, call methods directly,
and assert on widget state without simulating the full DDS stack.

---

## setup.sh Changes

Extend the existing `IDL_FILES` array and add a post-processing step:

```bash
# --- Existing admin IDL files ---
IDL_FILES=("ServiceCommon.idl" "ServiceAdmin.idl" "RecordingServiceTypes.idl")

# --- Add monitoring IDL files ---
MONITORING_IDL_FILES=("ServiceMonitoring.idl" "RecordingServiceMonitoring.idl"
                      "RoutingServiceMonitoring.idl")
# Note: ServiceCommon.idl is already in IDL_FILES (shared by both admin and monitoring)

# After converting all IDL to XML:
# Post-process: strip 'deprecated' attribute (rtiddsgen 4.3.1 emits it but
# the XML parser in the Connext Python bindings doesn't recognize it)
# See CORE-11987
sed -i 's/ deprecated="true"//g' "$XML_OUT_DIR"/*.xml
```

This is additive — the existing admin XML generation still works, and the
monitoring XML files land in the same `xml_types/` directory. The
`ServiceCommon.xml` is shared by both admin and monitoring types (already
generated by the existing step, so the monitoring step uses `-replace`).

The generated XML files will contain DynamicType definitions loadable via
`dds.QosProvider`, following the same pattern as the admin command types.

---

## run_gui.sh

Mirrors the existing `run.sh` pattern:
- Auto-detect NDDSHOME
- Validate license
- Activate virtual environment
- Check for XML type files + Python monitoring types (run setup.sh if missing)
- Launch `python3 recording_service_gui.py`

---

## Threading Model

```
Main Thread (tkinter)
  │
  ├── tkinter.after(500ms) → poll monitoring DataReaders → update UI labels
  │
  ├── Button click → submit command to ThreadPoolExecutor
  │     └── Worker thread: controller.start/pause/shutdown/tag()
  │           └── Post result back via queue → main thread reads & updates log
  │
  └── Launch button → subprocess.Popen(["xterm", "-e", cmd])
        (fire-and-forget; monitoring detects the service)
```

- **No direct process management** — the GUI never holds a reference to the Recording Service process
- Status is entirely driven by DDS monitoring subscriptions
- Commands are sent via the existing `RecordingServiceController` (DDS remote admin)

---

## Dependencies

- `tkinter` / `tkinter.ttk` — already available (verified)
- `rti.connextdds` — already installed in venv
- `rti.request` — already installed in venv
- Generated monitoring XML types — created by `setup.sh` (`rtiddsgen -convertToXML`), loaded via `QosProvider` for DynamicData
- `MonitoringSubscriber_QOS_PROFILES.xml` — new file, ships with the GUI
- `xml.etree.ElementTree` — stdlib, for parsing config XML to extract config names
- `concurrent.futures.ThreadPoolExecutor` — stdlib
- `subprocess` — stdlib, for launching the terminal
- `xterm` or `gnome-terminal` — for launching Recording Service in a separate window

---

## Open Questions

1. **Terminal emulator**: ~~Should we prefer `xterm`, `gnome-terminal`, `xfce4-terminal`, or detect what's available?~~ **Resolved: auto-detect in order of preference.** The GUI will try these in order and use the first one found:
   1. `gnome-terminal -- bash -c "..."`
   2. `xfce4-terminal -e "..."`
   3. `xterm -e "..."`
   4. `x-terminal-emulator -e "..."` (Debian/Ubuntu fallback)
   
   Recording Service runs visibly in its own terminal window so the user can see stdout/stderr output directly. The GUI monitors state via DDS monitoring topics, not the process.

2. **Monitoring config requirement**: ~~The Recording Service config must have `<monitoring>` enabled for the GUI status panel to work.~~ **Resolved: all recording service configs now ship with `<administration>` and `<monitoring>` enabled by default.** The admin domain is controlled via the `$(ADMIN_DOMAIN_ID)` configuration variable (default: 0).

3. **Config XML env var overrides**: ~~When the user changes Domain ID or Topic Filter in the GUI, should we use env vars or `-D` syntax?~~ **Resolved: `-DVAR=value` command-line flags.** This makes the full command visible in the terminal and easily reproducible. The `-D` syntax overrides `<configuration_variables>` in the XML the same way environment variables do.

4. **Multiple services**: ~~Should the GUI support monitoring/controlling multiple Recording Service instances simultaneously, or just one at a time?~~ **Resolved: single service** for simplicity. The GUI targets one Recording Service instance at a time.

5. **Type generation approach**: `rtiddsgen -language python` generates types using `idl.xtypes_compliance` which is not available prior to `rti.connext 7.3.1` (resolved in 7.3.1). **Resolved: use `rtiddsgen -convertToXML` and DynamicData via QosProvider** — the same proven pattern used by the admin command types. The monitoring XML files (`ServiceMonitoring.xml`, `RecordingServiceMonitoring.xml`, `RoutingServiceMonitoring.xml`) are generated into the existing `xml_types/` directory alongside the admin types. A `sed` post-processing step strips the unsupported `deprecated` attribute from the generated XML (see JIRA CORE-11987).
