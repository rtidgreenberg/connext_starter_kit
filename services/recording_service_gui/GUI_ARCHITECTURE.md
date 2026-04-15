# Recording Service GUI — Architecture & Implementation Plan

## 1. Purpose

This is an **RTI DDS API reference example** showing how to:

1. **Subscribe** to Recording Service monitoring topics using DDS listeners
2. **Control** a Recording Service via DDS remote administration (Request/Reply)
3. **Display** live DDS data in a simple tkinter GUI

Design priorities — **simplicity**, **composability**, **minimal abstraction**.
Every DDS API call should be obvious to a developer reading the code for the
first time.

---

## 2. Scope

| In Scope | Out of Scope |
|----------|-------------|
| Configure & launch Recording Service | Process management / restart logic |
| Subscribe to 3 monitoring topics on startup | Timeout detection / "Service Not Detected" |
| Display monitoring data as it arrives | Debouncing, reconnect logic |
| Remote control: Pause / Resume / Shutdown / Tag | Modifying `recording_service_control.py` |
| Clean DDS listener → Queue → tkinter pattern | Frameworks, abstraction layers |

---

## 3. File Structure

```
services/recording_service_gui/
├── recording_service_gui.py        # tkinter GUI + helpers + main()
├── recording_service_monitor.py    # DDS monitoring subscriber (listener-based)
├── recording_service_control.py    # DDS remote admin CLI + class
├── run_gui.sh                      # Environment setup + GUI launcher
├── run.sh                          # Convenience wrapper for headless CLI
├── setup.sh                        # IDL → XML (admin) + Python (monitoring) generation
├── xml_types/                      # Generated XML type files (admin)
├── python_types/                   # Generated Python type modules (monitoring)
├── test/                           # All tests and E2E assets
│   ├── test_gui.py                 #   Tests for GUI (pure logic + widget + DDS integration)
│   ├── test_monitoring.py          #   Tests for monitoring subscriber
│   ├── test_control.py             #   Tests for controller
│   ├── run_all_tests.py            #   Suite runner for all tests
│   ├── test_publisher.py           #   E2E DDS publisher helper
│   └── test_recorder_config.xml    #   E2E Recording Service config
└── archive/                        # Previous implementation (reference only)

dds/qos/
└── DDS_QOS_PROFILES.xml            # Centralized QoS (includes RecordingServiceMonitorProfiles
                                    #   and ServiceAdministrationProfiles libraries)
```

---

## 4. Module Design

### 4.1 `recording_service_monitor.py` — DDS Monitoring (Reference DDS Code)

This file contains **all DDS API usage for monitoring**. It is the primary
reference example for:
- Importing generated Python type modules (requires rti.connext >= 7.3.1)
- Creating typed `Topic` and `DataReader` objects
- Using `dds.NoOpDataReaderListener` for event-driven data reception
- Reading typed samples with discriminated unions

```python
"""
recording_service_monitor.py — DDS Recording Service Monitor

Subscribes to the three RTI Recording Service monitoring topics using
generated Python type modules and DDS DataReaderListeners.

DDS API Patterns Demonstrated:
  - Typed Topic / DataReader with generated Python IDL types
  - QosProvider for QoS profile selection
  - DomainParticipant, Subscriber, Topic, DataReader creation
  - DataReaderListener with on_data_available callback
  - Typed field access on received samples
"""
```

**Class: `RecordingServiceMonitor`**

```
RecordingServiceMonitor
├── __init__(domain_id, python_types_dir, qos_file, on_update)
│   ├── Import generated Python type modules (rti.connext >= 7.3.1)
│   ├── Create DomainParticipant
│   ├── Create 3 typed DataReaders (config, event, periodic)
│   ├── Attach DataReaderListener to each reader
│   └── Listeners call on_update(dict) with parsed data
│
├── on_data_available(reader_kind, reader)
│   ├── reader.take()
│   ├── Parse typed sample based on reader_kind
│   └── Emit update dict via callback
│
└── close()
    └── participant.close()
```

**Enum types used (from generated Python modules):**
```python
# RTI.Service.Monitoring.ResourceKind (from ServiceCommon.idl)
RECORDING_SERVICE = 20000
RECORDING_SESSION = 20001
RECORDING_TOPIC_GROUP = 20002
RECORDING_TOPIC = 20003

# RTI.Service.EntityStateKind (from ServiceCommon.idl)
INVALID = 0
ENABLED = 1
DISABLED = 2
STARTED = 3
STOPPED = 4
RUNNING = 5
PAUSED = 6
```

**Constants:**
```python
# Monitoring topic names
MONITORING_CONFIG_TOPIC = "rti/service/monitoring/config"
MONITORING_EVENT_TOPIC = "rti/service/monitoring/event"
MONITORING_PERIODIC_TOPIC = "rti/service/monitoring/periodic"
```

**Update dict contract** (what `on_update` receives):

```python
# Config update
{"kind": "config", "service_detected": True,
 "service_name": "...", "db_directory": "...", "topics": [...]}

# Event update
{"kind": "event", "service_detected": True,
 "state_int": 5, "rollover_count": 0, "events": ["..."]}

# Periodic update
{"kind": "periodic", "service_detected": True,
 "uptime": 42, "cpu": 5.0, "memory_kb": 1024.0,
 "db_file": "...", "db_file_size": 4096}

# Error (parsing failure)
{"kind": "error", "error": "..."}
```

**DDS thread → tkinter thread bridge:**

The `on_update` callback is invoked on a DDS listener thread. The GUI passes
a function that does `queue.put(update)`. The tkinter main thread drains the
queue with a `root.after()` timer. This is the minimal correct pattern for
thread-safe GUI updates from DDS.

```
DDS Listener Thread          Queue            tkinter Main Thread
  on_data_available() ──→ queue.put() ──→ root.after() drains → update widgets
```

### 4.2 `recording_service_gui.py` — tkinter GUI

Contains the GUI class, pure helper functions, and `main()`.
**No DDS imports** — all DDS interaction happens through `RecordingServiceMonitor`
and `RecordingServiceController`.

```
recording_service_gui.py
├── Pure Helpers (no tkinter, no DDS)
│   ├── detect_nddshome()
│   ├── parse_config_names(config_file) → list[str]
│   ├── build_launch_command(...) → list[str]
│   ├── detect_terminal_emulator() → list[str]
│   ├── format_file_size(bytes) → str
│   └── format_uptime(seconds) → str
│
├── RecordingServiceGUI
│   ├── __init__(root, nddshome)
│   │   ├── Build UI panels (config, status, controls, tags, log)
│   │   ├── Create RecordingServiceMonitor → starts listening immediately
│   │   └── Start queue drain loop (root.after)
│   │
│   ├── UI Update Methods
│   │   ├── _apply_config_update(update)
│   │   ├── _apply_event_update(update)
│   │   ├── _apply_periodic_update(update)
│   │   └── _poll_monitor_queue()  — drain queue, apply updates
│   │
│   ├── Control Callbacks
│   │   ├── _on_launch()     — build command, open in terminal
│   │   ├── _on_pause()      — delegate to RecordingServiceController
│   │   ├── _on_resume()     — delegate to RecordingServiceController
│   │   ├── _on_shutdown()   — delegate to RecordingServiceController
│   │   └── _on_set_tag()    — delegate to RecordingServiceController
│   │
│   └── close()  — cancel callbacks, close DDS resources
│
└── main()
```

### 4.3 `recording_service_control.py` — DDS Remote Admin

Standalone DDS remote admin module. Used by the GUI via:
```python
from recording_service_control import RecordingServiceController
```

### 4.4 Module Dependency Diagram

```
┌─────────────────────────────────┐
│    recording_service_gui.py     │
│                                 │
│  RecordingServiceGUI            │
│  + pure helpers                 │
│  + main()                       │
└──────┬──────────────┬───────────┘
       │              │
       │ imports      │ imports
       ▼              ▼
┌────────────────────────┐  ┌──────────────────────────┐
│ recording_service_     │  │ recording_service_       │
│ monitor.py             │  │ control.py               │
│                        │  │                          │
│ DDS Listeners          │  │ DDS Request/Reply        │
│ Typed Python API       │  │ DynamicData              │
│ QosProvider            │  │ QosProvider              │
└────────────────────────┘  └──────────────────────────┘
       │                      │
       └──────────┬───────────┘
                  │
          ┌───────▼────────┐
          │ rti.connextdds │
          │ rti.request    │
          └────────────────┘
```

---

## 5. GUI Theme & Layout

### 5.1 Dark Mode Theme

The GUI uses a **dark color scheme** for comfortable extended use and a modern
look. Applied via tkinter `ttk.Style` and direct widget configuration at
startup — no external theme packages required.

```python
# Color palette
BG_DARK      = "#1e1e1e"   # Main background
BG_PANEL     = "#252526"   # Panel/frame background
BG_INPUT     = "#3c3c3c"   # Entry/spinbox/combobox background
FG_TEXT      = "#d4d4d4"   # Primary text
FG_DIM       = "#808080"   # Secondary/placeholder text
FG_ACCENT    = "#569cd6"   # Accent (headers, links)
FG_GREEN     = "#4ec9b0"   # RUNNING state
FG_ORANGE    = "#ce9178"   # PAUSED state
FG_RED       = "#f44747"   # STOPPED / error state
BORDER_COLOR = "#3c3c3c"   # Subtle borders
SELECT_BG    = "#264f78"   # Selection highlight
```

Implementation approach:
- Configure `ttk.Style()` for all ttk widgets (TLabel, TFrame, TLabelframe,
  TButton, TEntry, TCombobox, TSpinbox, Treeview)
- Set `root.configure(bg=BG_DARK)`
- `tk.Text` (log panel) uses `bg=BG_PANEL, fg=FG_TEXT, insertbackground=FG_TEXT`
- State colors: RUNNING=`FG_GREEN`, PAUSED=`FG_ORANGE`, STOPPED=`FG_RED`

### 5.2 Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ File                                                     [dark]  │
├──────────────────────────────┬───────────────────────────────────┤
│ Configuration                │ Service Status                    │
│                              │                                   │
│ NDDSHOME: [___________][…]  │ State:          RUNNING ●         │
│ Config File: [_______][…]   │ Service Name:   remote_admin      │
│ Config Name: [deploy  ▾]    │ Uptime:         1h 23m 45s        │
│ Domain ID:   [1   ]         │ CPU Usage:      3.5%              │
│ Admin Domain:[0   ]         │ Memory:         2048 KB           │
│ Verbosity:   [ERROR:ERROR▾] │ DB Directory:   /tmp/recording    │
│                              │ Current DB:     test_data.db      │
│                              │ DB Size:        4.2 MB            │
│                              │ Rollover Count: 2                 │
│                              │ Topics:         3 topics          │
├──────────────────────────────┴───────────────────────────────────┤
│ [Launch Service] [Pause] [Resume] [Shutdown]                     │
├──────────────────────┬──────────────────────────────────────────┤
│ Tags                 │ Log                                       │
│ Name: [____]         │ [12:00:01] Monitoring active on domain 0 │
│ Desc: [____]         │ [12:00:03] Service state: RUNNING        │
│ [Set Tag]            │ [12:05:00] Tag 'marker_1' set            │
│                      │ [12:10:00] Pause: OK                     │
│ Name  Time   Desc    │                                          │
│ ───── ────── ─────── │                                          │
│ mk_1  12:05  Test    │                                          │
└──────────────────────┴──────────────────────────────────────────┘
```

---

## 6. Test Plan

### 6.1 `test_monitoring.py` — Monitoring Subscriber Tests

```
TestRecordingServiceMonitor
├── TestParseConfigSample
│   ├── test_recording_service_config → service_name, db_directory
│   ├── test_recording_topic_config → topic name in topics list
│   ├── test_unrelated_resource_kind → returns None
│   └── test_missing_fields → graceful fallback
│
├── TestParseEventSample
│   ├── test_state_change → state_int, events list
│   ├── test_rollover_count → rollover_count field
│   └── test_non_service_resource → returns None
│
├── TestParsePeriodicSample
│   ├── test_uptime_cpu_memory → all stats populated
│   ├── test_sqlite_fields → db_file, db_file_size
│   ├── test_missing_process → graceful -1 defaults
│   └── test_non_service_resource → returns None
│
├── TestEmitCallback
│   ├── test_callback_invoked → on_update receives dict
│   └── test_callback_exception_swallowed → no crash
│
└── TestIntegration (requires rti.connextdds)
    └── test_readers_created → 3 readers exist after init
```

### 6.2 `test_gui.py` — GUI Tests

```
Layer 1: Pure Logic (no tkinter, no DDS)
├── TestParseConfigNames (7 tests)
├── TestBuildLaunchCommand (3 tests)
├── TestDetectTerminalEmulator (3 tests)
├── TestFormatFileSize (5 tests)
├── TestFormatUptime (5 tests)
└── TestDetectNddshome (2 tests)

Layer 2: Widget Tests (tkinter, mock DDS)
├── TestWidgets
│   ├── test_config_file_populates_dropdown
│   ├── test_domain_id_default
│   ├── test_launch_button_builds_command
│   ├── test_button_states (no_service, running, paused)
│   ├── test_set_service_state_updates_label
│   ├── test_tag_adds_to_history
│   ├── test_log_panel_append
│   ├── test_monitoring_starts_on_init
│   ├── test_apply_config_update
│   ├── test_apply_event_update
│   ├── test_apply_periodic_update
│   ├── test_close_cancels_callbacks
│   └── test_launch_shell_safe_paths
│
└── Layer 3: Integration (requires rti.connextdds + rtirecordingservice)
    ├── test_monitoring_readers_created
    ├── test_controller_initialization
    └── test_live_monitoring_after_launch
```

---

## 7. Implementation Phases

### Phase 1: Create `recording_service_monitor.py`
- New file with DDS constants + `RecordingServiceMonitor` class
- Listener-based: create readers, attach listeners, emit parsed dicts
- Tests in `test_monitoring.py`
- Validate: `python3 test_monitoring.py`

### Phase 2: Create `recording_service_gui.py`
- tkinter GUI class importing from `recording_service_monitor` and
  `recording_service_control`
- Simple queue-drain loop, no timeout logic
- Create monitoring subscriber on startup
- Pure helpers in same file
- Tests in `test_gui.py`
- Validate: `python3 test_gui.py`

### Phase 3: Create `run_gui.sh`
- Environment setup (NDDSHOME, license, venv, XML types)
- Launch `recording_service_gui.py`

### Phase 4: Integration Test
- Launch real Recording Service, verify monitoring data arrives
- Validate: `python3 test_gui.py -k integration`

### Phase 5: Update `README.md`
- Document new file structure and usage

---

## 8. Acceptance Criteria

- [ ] `recording_service_monitor.py` is a standalone DDS reference — importable
      and usable without tkinter
- [ ] `recording_service_gui.py` has no DDS imports (`rti.*`)
- [ ] GUI starts monitoring immediately on launch — no manual "start" button
- [ ] All monitoring data (state, CPU, memory, uptime, DB, topics) displays
- [ ] Remote control buttons (Pause/Resume/Shutdown/Tag) work
- [ ] All tests pass: `cd test && python3 run_all_tests.py -v`
- [ ] GUI launches and shows live data from a real Recording Service
