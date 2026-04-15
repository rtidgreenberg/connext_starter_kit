#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

"""
Recording Service GUI — tkinter front-end for configuring, launching,
monitoring, and controlling an RTI Recording Service instance.

Monitoring is done via DDS subscription to the well-known monitoring topics
published by the service.  Control commands (start/pause/tag/shutdown) are
sent via the existing RecordingServiceController (DDS remote admin).

Usage:
    python3 recording_service_gui.py [--nddshome /path/to/rti_connext_dds-X.Y.Z]
"""

import os
import sys
import glob
import time
import shlex
import shutil
import argparse
import datetime
import threading
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ResourceKind enum values (from ServiceCommon.idl)
RESOURCE_KIND_RECORDING_SERVICE = 20000
RESOURCE_KIND_RECORDING_SESSION = 20001
RESOURCE_KIND_RECORDING_TOPIC_GROUP = 20002
RESOURCE_KIND_RECORDING_TOPIC = 20003

# EntityStateKind enum values (from ServiceCommon.idl)
STATE_INVALID = 0
STATE_ENABLED = 1
STATE_DISABLED = 2
STATE_STARTED = 3
STATE_STOPPED = 4
STATE_RUNNING = 5
STATE_PAUSED = 6

STATE_NAMES = {
    STATE_INVALID: "INVALID",
    STATE_ENABLED: "ENABLED",
    STATE_DISABLED: "DISABLED",
    STATE_STARTED: "STARTED",
    STATE_STOPPED: "STOPPED",
    STATE_RUNNING: "RUNNING",
    STATE_PAUSED: "PAUSED",
}

# Monitoring topic names
MONITORING_CONFIG_TOPIC = "rti/service/monitoring/config"
MONITORING_EVENT_TOPIC = "rti/service/monitoring/event"
MONITORING_PERIODIC_TOPIC = "rti/service/monitoring/periodic"

POLL_INTERVAL_MS = 500       # How often to poll DDS readers
NO_SERVICE_TIMEOUT_S = 15    # Show "not detected" warning after this

# Default field values
DEFAULT_DOMAIN_ID = 1
DEFAULT_ADMIN_DOMAIN_ID = 0
DEFAULT_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "recording_service_config.xml"
)
DEFAULT_CONFIG_NAME = "deploy"
DEFAULT_VERBOSITY = "ERROR:ERROR"

VERBOSITY_OPTIONS = [
    "SILENT",
    "ERROR:ERROR",
    "WARN:WARN",
    "LOCAL:LOCAL",
    "REMOTE:REMOTE",
]


# ---------------------------------------------------------------------------
# Pure helper functions (testable without tkinter or DDS)
# ---------------------------------------------------------------------------

def detect_nddshome() -> str:
    """Auto-detect NDDSHOME from environment or ~/rti_connext_dds-*."""
    env = os.environ.get("NDDSHOME")
    if env and os.path.isdir(env):
        return env
    candidates = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if candidates:
        return candidates[-1]
    return ""


def parse_config_names(config_file: str) -> list:
    """
    Parse a Recording Service XML config and return a list of all
    ``<recording_service name="...">`` values.
    """
    if not os.path.isfile(config_file):
        return []
    try:
        tree = ET.parse(config_file)
        root = tree.getroot()
        names = []
        for elem in root.iter("recording_service"):
            name = elem.get("name")
            if name:
                names.append(name)
        return names
    except (ET.ParseError, OSError):
        return []


def build_launch_command(nddshome: str, config_file: str, config_name: str,
                         domain_id: int, admin_domain_id: int,
                         verbosity: str) -> list:
    """
    Build the command list for launching Recording Service.

    Returns a list suitable for subprocess.Popen.
    """
    exe = os.path.join(nddshome, "bin", "rtirecordingservice")
    cmd = [
        exe,
        "-cfgFile", config_file,
        "-cfgName", config_name,
        f"-DDOMAIN_ID={domain_id}",
        f"-DADMIN_DOMAIN_ID={admin_domain_id}",
        "-verbosity", verbosity,
    ]
    return cmd


def detect_terminal_emulator() -> list:
    """
    Detect an available terminal emulator, returning the prefix args
    needed to run a command inside it.

    Order: gnome-terminal, xfce4-terminal, xterm, x-terminal-emulator.
    """
    checks = [
        (["gnome-terminal", "--"], "gnome-terminal"),
        (["xfce4-terminal", "-e"], "xfce4-terminal"),
        (["xterm", "-e"], "xterm"),
        (["x-terminal-emulator", "-e"], "x-terminal-emulator"),
    ]
    for prefix, binary in checks:
        if shutil.which(binary):
            return prefix
    return []


def format_file_size(size_bytes: int) -> str:
    """Format bytes into a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_uptime(seconds: int) -> str:
    """Format seconds into a human-readable uptime string."""
    if seconds < 0:
        return "N/A"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0 or h > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# DDS Monitoring Subscriber
# ---------------------------------------------------------------------------

class MonitoringSubscriber:
    """
    Subscribes to the three DDS monitoring topics published by
    Recording Service and extracts status information.

    Uses DynamicData loaded from XML type definitions (not typed Python
    classes) because rtiddsgen -language python generates code using
    idl.xtypes_compliance which is unavailable prior to rti.connext 7.3.1
    (resolved in 7.3.1).
    """

    def __init__(self, admin_domain_id: int, xml_types_dir: str,
                 qos_file: str, on_update=None):
        import rti.connextdds as dds

        self._dds = dds
        self._on_update = on_update or (lambda _update: None)

        class _ReaderListener(dds.DynamicData.DataReaderListener):
            """DDS listener that forwards data-available callbacks to the owner."""

            def __init__(self, owner, reader_kind: str):
                super().__init__()
                self._owner = owner
                self._reader_kind = reader_kind

            def on_data_available(self, reader):
                self._owner._on_data_available(self._reader_kind, reader)

        self._listener_type = _ReaderListener

        # Load monitoring types from XML
        type_provider = dds.QosProvider(
            os.path.join(xml_types_dir, "ServiceMonitoring.xml")
        )
        config_type = type_provider.type("RTI::Service::Monitoring::Config")
        event_type = type_provider.type("RTI::Service::Monitoring::Event")
        periodic_type = type_provider.type("RTI::Service::Monitoring::Periodic")

        # Load QoS profiles
        qos_provider = dds.QosProvider(qos_file)

        # Create participant
        self._participant = dds.DomainParticipant(admin_domain_id)

        # Register types
        self._participant.register_type("RTI::Service::Monitoring::Config",
                                        config_type)
        self._participant.register_type("RTI::Service::Monitoring::Event",
                                        event_type)
        self._participant.register_type("RTI::Service::Monitoring::Periodic",
                                        periodic_type)

        # Create topics
        config_topic = dds.DynamicData.Topic(
            self._participant, MONITORING_CONFIG_TOPIC, config_type)
        event_topic = dds.DynamicData.Topic(
            self._participant, MONITORING_EVENT_TOPIC, event_type)
        periodic_topic = dds.DynamicData.Topic(
            self._participant, MONITORING_PERIODIC_TOPIC, periodic_type)

        # Create subscriber
        subscriber = dds.Subscriber(self._participant)

        # Create readers with appropriate QoS
        config_qos = qos_provider.datareader_qos_from_profile(
            "MonitoringSubscriberProfiles::config_Profile")
        event_qos = qos_provider.datareader_qos_from_profile(
            "MonitoringSubscriberProfiles::event_Profile")
        periodic_qos = qos_provider.datareader_qos_from_profile(
            "MonitoringSubscriberProfiles::periodic_Profile")

        self._config_reader = dds.DynamicData.DataReader(
            subscriber, config_topic, config_qos)
        self._event_reader = dds.DynamicData.DataReader(
            subscriber, event_topic, event_qos)
        self._periodic_reader = dds.DynamicData.DataReader(
            subscriber, periodic_topic, periodic_qos)

        self._config_listener = self._listener_type(self, "config")
        self._event_listener = self._listener_type(self, "event")
        self._periodic_listener = self._listener_type(self, "periodic")

        self._config_reader.set_listener(
            self._config_listener, dds.StatusMask.DATA_AVAILABLE)
        self._event_reader.set_listener(
            self._event_listener, dds.StatusMask.DATA_AVAILABLE)
        self._periodic_reader.set_listener(
            self._periodic_listener, dds.StatusMask.DATA_AVAILABLE)

    def _emit(self, update: dict):
        try:
            self._on_update(update)
        except Exception:
            pass

    def _on_data_available(self, reader_kind: str, reader):
        try:
            samples = reader.take()
        except Exception as e:
            self._emit({"kind": "error", "error": str(e)})
            return

        for sample in samples:
            if not sample.info.valid:
                continue
            try:
                if reader_kind == "config":
                    update = self._parse_config_sample(sample.data)
                elif reader_kind == "event":
                    update = self._parse_event_sample(sample.data)
                else:
                    update = self._parse_periodic_sample(sample.data)

                if update is not None:
                    self._emit(update)
            except Exception as e:
                self._emit({
                    "kind": "error",
                    "error": f"{reader_kind} sample parse error: {e}"
                })

    def _parse_config_sample(self, data) -> dict:
        value = data["value"]
        kind = value.discriminator_value
        if kind == RESOURCE_KIND_RECORDING_SERVICE:
            update = {
                "kind": "config",
                "service_detected": True,
                "service_name": "",
                "db_directory": "",
                "topics": [],
            }
            svc = value["recording_service"]
            update["service_name"] = str(svc["application_name"])
            try:
                sqlite_cfg = svc["builtin_sqlite"]
                update["db_directory"] = str(sqlite_cfg["db_directory"])
            except Exception:
                pass
            return update

        if kind == RESOURCE_KIND_RECORDING_TOPIC:
            topic = value["recording_topic"]
            return {
                "kind": "config",
                "service_detected": True,
                "service_name": "",
                "db_directory": "",
                "topics": [str(topic["topic_name"])],
            }

        return None

    def _parse_event_sample(self, data) -> dict:
        value = data["value"]
        kind = value.discriminator_value
        if kind != RESOURCE_KIND_RECORDING_SERVICE:
            return None

        svc_event = value["recording_service"]
        state_int = svc_event["state"]
        state_name = STATE_NAMES.get(state_int, f"UNKNOWN({state_int})")
        update = {
            "kind": "event",
            "service_detected": True,
            "state_int": state_int,
            "rollover_count": -1,
            "events": [f"Service state changed to: {state_name}"],
        }

        try:
            sqlite_evt = svc_event["builtin_sqlite"]
            try:
                update["rollover_count"] = sqlite_evt["rollover_count"]
            except Exception:
                pass
        except Exception:
            pass

        return update

    def _parse_periodic_sample(self, data) -> dict:
        value = data["value"]
        kind = value.discriminator_value
        if kind != RESOURCE_KIND_RECORDING_SERVICE:
            return None

        svc = value["recording_service"]
        update = {
            "kind": "periodic",
            "service_detected": True,
            "uptime": -1,
            "cpu": -1.0,
            "memory_kb": -1.0,
            "db_file": "",
            "db_file_size": -1,
        }

        try:
            process = svc["process"]
            update["uptime"] = process["uptime_sec"]
            try:
                cpu_stats = process["cpu_usage_percentage"]
                metrics = cpu_stats["publication_period_metrics"]
                update["cpu"] = metrics["mean"]
            except Exception:
                pass
            try:
                mem_stats = process["physical_memory_kb"]
                metrics = mem_stats["publication_period_metrics"]
                update["memory_kb"] = metrics["mean"]
            except Exception:
                pass
        except Exception:
            pass

        try:
            sqlite = svc["builtin_sqlite"]
            try:
                update["db_file"] = str(sqlite["current_file"])
            except Exception:
                pass
            try:
                update["db_file_size"] = sqlite["current_file_size"]
            except Exception:
                pass
        except Exception:
            pass

        return update

    def close(self):
        """Clean up DDS resources."""
        try:
            self._participant.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

class RecordingServiceGUI:
    """
    Main GUI class.  All widget creation happens in __init__.
    Public methods (set_service_state, append_log, etc.) are separated
    for testability.
    """

    def __init__(self, root: tk.Tk, nddshome: str = None):
        self.root = root
        self.root.title("RTI Recording Service Control")
        self.root.geometry("1000x750")
        self.root.minsize(800, 600)

        # Resolve paths
        self._script_dir = os.path.dirname(os.path.abspath(__file__))
        self._xml_types_dir = os.path.join(self._script_dir, "xml_types")
        self._qos_file = os.path.join(
            self._script_dir, "MonitoringSubscriber_QOS_PROFILES.xml")
        self._admin_qos_file = os.path.join(
            self._script_dir, "ServiceAdmin_QOS_PROFILES.xml")

        # State
        self._nddshome = nddshome or detect_nddshome()
        self._controller = None
        self._monitoring = None
        self._monitoring_domain_id = None
        self._service_state = STATE_INVALID
        self._service_detected = False
        self._launch_time = None
        self._tag_history = []
        self._known_topics = set()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._result_queue = Queue()
        self._monitor_queue = Queue()
        self._result_after_id = None
        self._monitor_queue_after_id = None
        self._closed = False

        # Build UI
        self._build_menu()
        self._build_config_panel()
        self._build_status_panel()
        self._build_control_bar()
        self._build_bottom_panels()
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)

        # Initialize config dropdown
        self._on_config_file_changed()
        self._ensure_monitoring_started()

        # Update button states
        self._update_button_states()

        # Start polling loop
        self._poll_results()
        self._poll_monitor_events()

    # ----- UI Construction --------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self._on_exit)
        menubar.add_cascade(label="File", menu=file_menu)

    def _build_config_panel(self):
        frame = ttk.LabelFrame(self.root, text="Configuration", padding=8)
        frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        row = 0

        # NDDSHOME
        ttk.Label(frame, text="NDDSHOME:").grid(
            row=row, column=0, sticky="w", pady=2)
        self._nddshome_var = tk.StringVar(value=self._nddshome)
        ttk.Entry(frame, textvariable=self._nddshome_var, width=50).grid(
            row=row, column=1, sticky="ew", pady=2)
        ttk.Button(frame, text="Browse...",
                   command=self._browse_nddshome).grid(
            row=row, column=2, padx=4, pady=2)
        row += 1

        # Config File
        ttk.Label(frame, text="Config File:").grid(
            row=row, column=0, sticky="w", pady=2)
        default_cfg = os.path.normpath(DEFAULT_CONFIG_FILE)
        self._config_file_var = tk.StringVar(value=default_cfg)
        self._config_file_var.trace_add("write",
                                        lambda *_: self._on_config_file_changed())
        ttk.Entry(frame, textvariable=self._config_file_var, width=50).grid(
            row=row, column=1, sticky="ew", pady=2)
        ttk.Button(frame, text="Browse...",
                   command=self._browse_config_file).grid(
            row=row, column=2, padx=4, pady=2)
        row += 1

        # Config Name
        ttk.Label(frame, text="Config Name:").grid(
            row=row, column=0, sticky="w", pady=2)
        self._config_name_var = tk.StringVar(value=DEFAULT_CONFIG_NAME)
        self._config_name_combo = ttk.Combobox(
            frame, textvariable=self._config_name_var, width=30, state="readonly")
        self._config_name_combo.grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        # Domain ID
        ttk.Label(frame, text="Domain ID:").grid(
            row=row, column=0, sticky="w", pady=2)
        self._domain_id_var = tk.IntVar(value=DEFAULT_DOMAIN_ID)
        self._domain_id_spin = ttk.Spinbox(
            frame, from_=0, to=232, textvariable=self._domain_id_var, width=10)
        self._domain_id_spin.grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        # Admin Domain ID
        ttk.Label(frame, text="Admin Domain ID:").grid(
            row=row, column=0, sticky="w", pady=2)
        self._admin_domain_id_var = tk.IntVar(value=DEFAULT_ADMIN_DOMAIN_ID)
        self._admin_domain_id_var.trace_add(
            "write", lambda *_: self._on_admin_domain_changed())
        ttk.Spinbox(frame, from_=0, to=232,
                     textvariable=self._admin_domain_id_var, width=10).grid(
            row=row, column=1, sticky="w", pady=2)
        row += 1

        # Verbosity
        ttk.Label(frame, text="Verbosity:").grid(
            row=row, column=0, sticky="w", pady=2)
        self._verbosity_var = tk.StringVar(value=DEFAULT_VERBOSITY)
        ttk.Combobox(frame, textvariable=self._verbosity_var, width=20,
                     values=VERBOSITY_OPTIONS, state="readonly").grid(
            row=row, column=1, sticky="w", pady=2)
        row += 1

        frame.columnconfigure(1, weight=1)

    def _build_status_panel(self):
        frame = ttk.LabelFrame(self.root, text="Service Status", padding=8)
        frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        labels = [
            ("State:", "_state_label"),
            ("Service Name:", "_name_label"),
            ("Uptime:", "_uptime_label"),
            ("CPU Usage:", "_cpu_label"),
            ("Memory:", "_memory_label"),
            ("DB Directory:", "_dbdir_label"),
            ("Current DB File:", "_dbfile_label"),
            ("DB File Size:", "_dbsize_label"),
            ("Rollover Count:", "_rollover_label"),
            ("Topics Recorded:", "_topics_label"),
        ]

        for i, (text, attr) in enumerate(labels):
            ttk.Label(frame, text=text).grid(row=i, column=0, sticky="w",
                                              pady=1)
            lbl = ttk.Label(frame, text="—", foreground="gray")
            lbl.grid(row=i, column=1, sticky="w", padx=8, pady=1)
            setattr(self, attr, lbl)

        frame.columnconfigure(1, weight=1)

    def _build_control_bar(self):
        frame = ttk.Frame(self.root, padding=4)
        frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=2)

        self._launch_btn = ttk.Button(
            frame, text="Launch Service", command=self._on_launch)
        self._launch_btn.pack(side="left", padx=4)

        self._pause_btn = ttk.Button(
            frame, text="Pause", command=self._on_pause)
        self._pause_btn.pack(side="left", padx=4)

        self._resume_btn = ttk.Button(
            frame, text="Resume", command=self._on_resume)
        self._resume_btn.pack(side="left", padx=4)

        self._shutdown_btn = ttk.Button(
            frame, text="Shutdown", command=self._on_shutdown)
        self._shutdown_btn.pack(side="left", padx=4)

    def _build_bottom_panels(self):
        bottom = ttk.Frame(self.root)
        bottom.grid(row=2, column=0, columnspan=2, sticky="nsew",
                    padx=5, pady=5)
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)

        # Tag Panel (left)
        tag_frame = ttk.LabelFrame(bottom, text="Tags", padding=8)
        tag_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tag_input = ttk.Frame(tag_frame)
        tag_input.pack(fill="x")

        ttk.Label(tag_input, text="Name:").grid(row=0, column=0, sticky="w")
        self._tag_name_var = tk.StringVar()
        ttk.Entry(tag_input, textvariable=self._tag_name_var, width=20).grid(
            row=0, column=1, sticky="ew", padx=4)

        ttk.Label(tag_input, text="Description:").grid(
            row=1, column=0, sticky="w")
        self._tag_desc_var = tk.StringVar()
        ttk.Entry(tag_input, textvariable=self._tag_desc_var, width=20).grid(
            row=1, column=1, sticky="ew", padx=4)

        tag_input.columnconfigure(1, weight=1)

        self._tag_btn = ttk.Button(
            tag_frame, text="Set Tag", command=self._on_set_tag)
        self._tag_btn.pack(pady=4)

        # Tag history treeview
        self._tag_tree = ttk.Treeview(
            tag_frame, columns=("name", "time", "desc"),
            show="headings", height=6)
        self._tag_tree.heading("name", text="Name")
        self._tag_tree.heading("time", text="Time")
        self._tag_tree.heading("desc", text="Description")
        self._tag_tree.column("name", width=80)
        self._tag_tree.column("time", width=80)
        self._tag_tree.column("desc", width=100)
        self._tag_tree.pack(fill="both", expand=True)

        # Log Panel (right)
        log_frame = ttk.LabelFrame(bottom, text="Log", padding=8)
        log_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self._log_text = tk.Text(log_frame, height=12, state="disabled",
                                  wrap="word", font=("Courier", 9))
        scrollbar = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        # Grid weights for root
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)

    # ----- Public testable methods ------------------------------------------

    def set_service_state(self, state_int: int):
        """Update displayed state and button states."""
        self._service_state = state_int
        state_name = STATE_NAMES.get(state_int, f"UNKNOWN({state_int})")
        color = {
            STATE_RUNNING: "green",
            STATE_PAUSED: "orange",
            STATE_STOPPED: "red",
        }.get(state_int, "gray")
        self._state_label.config(text=state_name, foreground=color)
        self._update_button_states()

    def append_log(self, message: str):
        """Append a timestamped message to the log panel."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_text.config(state="normal")
        self._log_text.insert("end", f"[{ts}] {message}\n")
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def add_tag_to_history(self, name: str, timestamp: str, description: str):
        """Add a row to the tag history treeview."""
        self._tag_tree.insert("", "end", values=(name, timestamp, description))
        self._tag_history.append({
            "name": name, "time": timestamp, "description": description})

    def get_launch_command(self) -> list:
        """Build and return the launch command from current config fields."""
        return build_launch_command(
            nddshome=self._nddshome_var.get(),
            config_file=self._config_file_var.get(),
            config_name=self._config_name_var.get(),
            domain_id=self._domain_id_var.get(),
            admin_domain_id=self._admin_domain_id_var.get(),
            verbosity=self._verbosity_var.get(),
        )

    # ----- Config file parsing ----------------------------------------------

    def _on_config_file_changed(self):
        """Re-parse config names when the config file path changes."""
        path = self._config_file_var.get()
        names = parse_config_names(path)
        self._config_name_combo["values"] = names
        if names:
            if self._config_name_var.get() not in names:
                self._config_name_var.set(names[0])
        else:
            self._config_name_var.set("")

    def _on_admin_domain_changed(self):
        """Restart monitoring on admin-domain changes."""
        if self._closed:
            return
        self._ensure_monitoring_started(force_restart=True)

    # ----- Button state management ------------------------------------------

    def _update_button_states(self):
        """Enable/disable buttons based on current service state."""
        detected = self._service_detected

        # Launch: enabled when no service detected
        self._launch_btn.config(
            state="normal" if not detected else "disabled")

        # Pause: enabled when RUNNING
        self._pause_btn.config(
            state="normal" if self._service_state == STATE_RUNNING else "disabled")

        # Resume: enabled when PAUSED
        self._resume_btn.config(
            state="normal" if self._service_state == STATE_PAUSED else "disabled")

        # Shutdown: enabled when service detected
        self._shutdown_btn.config(
            state="normal" if detected else "disabled")

        # Tag: enabled when service detected
        self._tag_btn.config(
            state="normal" if detected else "disabled")

    # ----- File browser callbacks -------------------------------------------

    def _browse_nddshome(self):
        path = filedialog.askdirectory(
            title="Select NDDSHOME directory",
            initialdir=self._nddshome_var.get() or os.path.expanduser("~"))
        if path:
            self._nddshome_var.set(path)

    def _browse_config_file(self):
        path = filedialog.askopenfilename(
            title="Select Recording Service Config",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
            initialdir=os.path.dirname(self._config_file_var.get())
                       or self._script_dir)
        if path:
            self._config_file_var.set(path)

    # ----- Command callbacks ------------------------------------------------

    def _on_launch(self):
        """Launch Recording Service in a new terminal window."""
        self._ensure_monitoring_started()
        cmd = self.get_launch_command()
        exe = cmd[0]

        if not os.path.isfile(exe):
            messagebox.showerror(
                "Launch Error",
                f"Recording Service executable not found:\n{exe}\n\n"
                "Check NDDSHOME setting.")
            return

        terminal_prefix = detect_terminal_emulator()
        if not terminal_prefix:
            messagebox.showerror(
                "Launch Error",
                "No terminal emulator found.\n"
                "Install xterm, gnome-terminal, or xfce4-terminal.")
            return

        cmd_str = shlex.join(cmd)
        # Wrap in bash to keep terminal open after service exits
        full_cmd = terminal_prefix + [
            "bash", "-c", f"{cmd_str}; echo; echo 'Press Enter to close...'; read"]

        self.append_log(f"Launching: {cmd_str}")
        try:
            subprocess.Popen(full_cmd, start_new_session=True)
            self._launch_time = time.time()
            self.append_log("Recording Service terminal opened.")
        except Exception as e:
            self.append_log(f"ERROR launching service: {e}")
            messagebox.showerror("Launch Error", str(e))

    def _ensure_controller(self):
        """Create the RecordingServiceController if needed."""
        if self._controller is not None:
            return True
        try:
            # Import here to avoid circular dependency
            from recording_service_control import RecordingServiceController
            self._controller = RecordingServiceController(
                domain_id=self._admin_domain_id_var.get(),
                service_name=self._config_name_var.get(),
                xml_types_dir=self._xml_types_dir,
                qos_file=self._admin_qos_file,
            )
            return True
        except Exception as e:
            self.append_log(f"ERROR creating controller: {e}")
            return False

    def _run_command_async(self, func, description: str):
        """Run a controller command in a background thread."""
        def worker():
            try:
                result = func()
                self._result_queue.put(("cmd_ok", description, result))
            except Exception as e:
                self._result_queue.put(("cmd_err", description, str(e)))

        self.append_log(f"Sending command: {description}...")
        self._executor.submit(worker)

    def _on_pause(self):
        if not self._ensure_controller():
            return
        self._run_command_async(self._controller.pause, "Pause")

    def _on_resume(self):
        if not self._ensure_controller():
            return
        self._run_command_async(self._controller.start, "Resume")

    def _on_shutdown(self):
        if not messagebox.askyesno("Confirm Shutdown",
                                    "Shut down the Recording Service?"):
            return
        if not self._ensure_controller():
            return
        self._run_command_async(self._controller.shutdown, "Shutdown")

    def _on_set_tag(self):
        name = self._tag_name_var.get().strip()
        if not name:
            messagebox.showwarning("Tag Error", "Tag name is required.")
            return
        desc = self._tag_desc_var.get().strip()
        if not self._ensure_controller():
            return

        def do_tag():
            return self._controller.tag_timestamp(name, desc)

        self._run_command_async(do_tag, f"Tag '{name}'")
        # Optimistically add to history
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.add_tag_to_history(name, ts, desc)
        self._tag_name_var.set("")
        self._tag_desc_var.set("")

    # ----- Monitoring -------------------------------------------------------

    def _on_monitor_update(self, update: dict):
        """Receive callback-driven monitoring updates from DDS listeners."""
        self._monitor_queue.put(update)

    def _ensure_monitoring_started(self, force_restart: bool = False):
        """Start or restart automatic monitoring for the selected admin domain."""
        target_domain = self._admin_domain_id_var.get()
        if (not force_restart and self._monitoring is not None and
                self._monitoring_domain_id == target_domain):
            return True

        if self._monitoring is not None:
            self._stop_monitoring(append_log=False)

        try:
            self._monitoring = MonitoringSubscriber(
                admin_domain_id=target_domain,
                xml_types_dir=self._xml_types_dir,
                qos_file=self._qos_file,
                on_update=self._on_monitor_update,
            )
            self._monitoring_domain_id = target_domain
            self.append_log(f"Monitoring active on domain {target_domain}")
            return True
        except Exception as e:
            self._monitoring = None
            self._monitoring_domain_id = None
            self.append_log(f"ERROR starting monitoring: {e}")
            return False

    def _stop_monitoring(self, append_log: bool = True):
        """Stop the DDS monitoring subscription."""
        if self._monitoring:
            self._monitoring.close()
            self._monitoring = None
        self._monitoring_domain_id = None
        self._service_detected = False
        self._service_state = STATE_INVALID
        self._update_button_states()
        self._reset_status_labels()
        if append_log:
            self.append_log("Monitoring stopped.")

    def _reset_status_labels(self):
        """Reset all status labels to default."""
        for attr in ["_state_label", "_name_label", "_uptime_label",
                      "_cpu_label", "_memory_label", "_dbdir_label",
                      "_dbfile_label", "_dbsize_label", "_rollover_label",
                      "_topics_label"]:
            getattr(self, attr).config(text="—", foreground="gray")
        self._known_topics.clear()

    def _poll_monitor_events(self):
        """Process callback-driven monitoring events on the tkinter thread."""
        if self._closed:
            return

        try:
            while True:
                update = self._monitor_queue.get_nowait()
                if update.get("service_detected"):
                    self._service_detected = True

                kind = update.get("kind")
                if kind == "config":
                    if update.get("service_name"):
                        self._name_label.config(
                            text=update["service_name"], foreground="black")
                    if update.get("db_directory"):
                        self._dbdir_label.config(
                            text=update["db_directory"], foreground="black")
                    for topic in update.get("topics", []):
                        if topic not in self._known_topics:
                            self._known_topics.add(topic)
                    if self._known_topics:
                        self._topics_label.config(
                            text=f"{len(self._known_topics)} topics",
                            foreground="black")

                elif kind == "event":
                    state_int = update.get("state_int", STATE_INVALID)
                    if state_int != STATE_INVALID:
                        self.set_service_state(state_int)
                    if update.get("rollover_count", -1) >= 0:
                        self._rollover_label.config(
                            text=str(update["rollover_count"]),
                            foreground="black")
                    for evt in update.get("events", []):
                        self.append_log(evt)

                elif kind == "periodic":
                    if update.get("uptime", -1) >= 0:
                        self._uptime_label.config(
                            text=format_uptime(update["uptime"]),
                            foreground="black")
                    if update.get("cpu", -1.0) >= 0:
                        self._cpu_label.config(
                            text=f"{update['cpu']:.1f}%", foreground="black")
                    if update.get("memory_kb", -1.0) >= 0:
                        self._memory_label.config(
                            text=f"{update['memory_kb']:.0f} KB",
                            foreground="black")
                    if update.get("db_file"):
                        self._dbfile_label.config(
                            text=os.path.basename(update["db_file"]),
                            foreground="black")
                    if update.get("db_file_size", -1) >= 0:
                        self._dbsize_label.config(
                            text=format_file_size(update["db_file_size"]),
                            foreground="black")

                elif kind == "error":
                    self.append_log(f"Monitoring error: {update.get('error', 'unknown error')}")

                if (self._service_detected and
                        self._state_label.cget("text") == "Service Not Detected" and
                        self._service_state == STATE_INVALID):
                    self._state_label.config(text="UNKNOWN", foreground="gray")

                self._update_button_states()

        except Empty:
            pass

        if (self._launch_time and not self._service_detected and
                time.time() - self._launch_time > NO_SERVICE_TIMEOUT_S):
            self._state_label.config(
                text="Service Not Detected", foreground="red")

        self._monitor_queue_after_id = self.root.after(
            POLL_INTERVAL_MS, self._poll_monitor_events)

    # ----- Result queue processing -------------------------------------------

    def _poll_results(self):
        """Process results from background command threads."""
        if self._closed:
            return
        try:
            while True:
                msg = self._result_queue.get_nowait()
                kind = msg[0]
                if kind == "cmd_ok":
                    _, desc, result = msg
                    if result:
                        retcode = result.get("retcode", -1)
                        body = result.get("string_body", "")
                        status = "OK" if retcode == 0 else "ERROR"
                        self.append_log(
                            f"{desc}: {status}"
                            + (f" - {body}" if body else ""))
                    else:
                        self.append_log(f"{desc}: No reply received")
                elif kind == "cmd_err":
                    _, desc, error = msg
                    self.append_log(f"{desc} ERROR: {error}")
        except Empty:
            pass

        self._result_after_id = self.root.after(200, self._poll_results)

    def close(self):
        """Release resources and cancel scheduled callbacks."""
        if self._closed:
            return
        self._closed = True

        if self._result_after_id is not None:
            try:
                self.root.after_cancel(self._result_after_id)
            except Exception:
                pass
            self._result_after_id = None

        if self._monitor_queue_after_id is not None:
            try:
                self.root.after_cancel(self._monitor_queue_after_id)
            except Exception:
                pass
            self._monitor_queue_after_id = None

        if self._monitoring is not None:
            self._stop_monitoring()

        if self._controller is not None:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None

        self._executor.shutdown(wait=False)

    def _on_exit(self):
        """Handle window/menu exit."""
        self.close()
        try:
            self.root.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RTI Recording Service GUI Control")
    parser.add_argument(
        "--nddshome", default=None,
        help="Path to RTI Connext DDS installation "
             "(auto-detected if not specified)")
    args = parser.parse_args()

    root = tk.Tk()
    app = RecordingServiceGUI(root, nddshome=args.nddshome)
    root.mainloop()


if __name__ == "__main__":
    main()
