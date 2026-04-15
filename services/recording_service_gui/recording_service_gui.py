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

Monitoring is done via DDS subscription (see recording_service_monitor.py).
Control commands (start/pause/tag/shutdown) are sent via
RecordingServiceController (recording_service_control.py).

No DDS imports in this file — all DDS interaction happens through
RecordingServiceMonitor and RecordingServiceController.

Usage:
    python3 recording_service_gui.py [--nddshome /path/to/rti_connext_dds-X.Y.Z]
"""

import os
import sys
import glob
import shlex
import shutil
import argparse
import datetime
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ---------------------------------------------------------------------------
# Dark mode colour palette (VS Code–inspired)
# ---------------------------------------------------------------------------
BG_DARK = "#1e1e1e"
BG_PANEL = "#252526"
BG_INPUT = "#3c3c3c"
FG_TEXT = "#d4d4d4"
FG_DIM = "#808080"
FG_ACCENT = "#569cd6"
FG_GREEN = "#4ec9b0"
FG_ORANGE = "#ce9178"
FG_RED = "#f44747"
BORDER_COLOR = "#3c3c3c"
SELECT_BG = "#264f78"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_DOMAIN_ID = 1
DEFAULT_ADMIN_DOMAIN_ID = 1
DEFAULT_CONFIG_FILE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "recording_service_config.xml"))
DEFAULT_CONFIG_NAME = "deploy"
DEFAULT_VERBOSITY = "ERROR:ERROR"

VERBOSITY_OPTIONS = [
    "SILENT",
    "ERROR:ERROR",
    "WARN:WARN",
    "LOCAL:LOCAL",
    "REMOTE:REMOTE",
    "ALL:ALL",
]

POLL_INTERVAL_MS = 500  # Queue drain interval

# State constants (mirrors recording_service_monitor but avoids importing DDS)
STATE_INVALID = 0
STATE_RUNNING = 5
STATE_PAUSED = 6

STATE_NAMES = {
    0: "INVALID",
    1: "ENABLED",
    2: "DISABLED",
    3: "STARTED",
    4: "STOPPED",
    5: "RUNNING",
    6: "PAUSED",
}

STATE_COLORS = {
    STATE_RUNNING: FG_GREEN,
    STATE_PAUSED: FG_ORANGE,
}


# ---------------------------------------------------------------------------
# Pure helper functions (no tkinter, no DDS — easily testable)
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
    Parse a Recording Service XML config and return all
    ``<recording_service name="...">`` values.
    """
    if not os.path.isfile(config_file):
        return []
    try:
        tree = ET.parse(config_file)
        root = tree.getroot()
        return [
            elem.get("name")
            for elem in root.iter("recording_service")
            if elem.get("name")
        ]
    except (ET.ParseError, OSError):
        return []


def build_launch_command(nddshome: str, config_file: str, config_name: str,
                         domain_id: int, admin_domain_id: int,
                         verbosity: str,
                         qos_file: str = None) -> list:
    """Build the command list for launching Recording Service.

    Args:
        nddshome: Path to RTI Connext DDS installation.
        config_file: Path to the Recording Service XML configuration file.
        config_name: Name of the configuration within the XML file.
        domain_id: DDS domain ID for data recording.
        admin_domain_id: DDS domain ID for remote administration.
        verbosity: Logging verbosity level (e.g. "ERROR:ERROR").
        qos_file: Optional path to a QoS XML file.  When provided it is
            appended to -cfgFile as a semicolon-separated list so
            Recording Service loads the profiles
            (e.g. ServiceAdministrationProfiles) from this file.
    """
    exe = os.path.join(nddshome, "bin", "rtirecordingservice")

    # -cfgFile accepts semicolon-separated paths; append qos_file if given
    cfg_file_value = config_file
    if qos_file:
        cfg_file_value = f"{config_file};{qos_file}"

    cmd = [
        exe,
        "-cfgFile", cfg_file_value,
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
    if size_bytes < 0:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
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
# Dark-mode ttk style configuration
# ---------------------------------------------------------------------------

def apply_dark_theme(root: tk.Tk):
    """Apply VS Code–inspired dark theme to root and all ttk widgets."""
    root.configure(bg=BG_DARK)

    style = ttk.Style(root)
    style.theme_use("clam")

    # General
    style.configure(".", background=BG_DARK, foreground=FG_TEXT,
                     fieldbackground=BG_INPUT, bordercolor=BORDER_COLOR,
                     troughcolor=BG_INPUT, selectbackground=SELECT_BG,
                     selectforeground=FG_TEXT, font=("Segoe UI", 10))

    style.configure("TFrame", background=BG_DARK)
    style.configure("TLabel", background=BG_DARK, foreground=FG_TEXT)
    style.configure("TLabelframe", background=BG_DARK, foreground=FG_ACCENT,
                     bordercolor=BORDER_COLOR)
    style.configure("TLabelframe.Label", background=BG_DARK,
                     foreground=FG_ACCENT, font=("Segoe UI", 10, "bold"))

    # Buttons
    style.configure("TButton", background=BG_INPUT, foreground=FG_TEXT,
                     bordercolor=BORDER_COLOR, padding=(8, 4))
    style.map("TButton",
              background=[("active", SELECT_BG), ("disabled", BG_DARK)],
              foreground=[("disabled", FG_DIM)])

    # Entry / Spinbox / Combobox
    style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG_TEXT,
                     insertcolor=FG_TEXT, bordercolor=BORDER_COLOR)
    style.configure("TSpinbox", fieldbackground=BG_INPUT, foreground=FG_TEXT,
                     arrowcolor=FG_TEXT, bordercolor=BORDER_COLOR)
    style.configure("TCombobox", fieldbackground=BG_INPUT, foreground=FG_TEXT,
                     arrowcolor=FG_TEXT, bordercolor=BORDER_COLOR,
                     selectbackground=SELECT_BG)
    style.map("TCombobox",
              fieldbackground=[("readonly", BG_INPUT)],
              selectbackground=[("readonly", SELECT_BG)])

    # Treeview
    style.configure("Treeview", background=BG_PANEL, foreground=FG_TEXT,
                     fieldbackground=BG_PANEL, bordercolor=BORDER_COLOR,
                     rowheight=22)
    style.configure("Treeview.Heading", background=BG_INPUT,
                     foreground=FG_TEXT, bordercolor=BORDER_COLOR)
    style.map("Treeview", background=[("selected", SELECT_BG)])

    # Scrollbar
    style.configure("TScrollbar", background=BG_INPUT,
                     troughcolor=BG_PANEL, arrowcolor=FG_TEXT,
                     bordercolor=BORDER_COLOR)

    # Menu styling (tk.Menu, not ttk)
    root.option_add("*Menu.background", BG_PANEL)
    root.option_add("*Menu.foreground", FG_TEXT)
    root.option_add("*Menu.activeBackground", SELECT_BG)
    root.option_add("*Menu.activeForeground", FG_TEXT)
    root.option_add("*Menu.relief", "flat")


# ---------------------------------------------------------------------------
# RecordingServiceGUI
# ---------------------------------------------------------------------------

class RecordingServiceGUI:
    """
    tkinter GUI for configuring, launching, monitoring, and controlling
    an RTI Recording Service.

    Architecture:
      - Monitoring: RecordingServiceMonitor (DDS listeners → queue → after())
      - Control: RecordingServiceController (DDS Request/Reply, async)
      - No DDS imports here — all DDS interaction happens through those two
        modules.
    """

    def __init__(self, root: tk.Tk, nddshome: str = None,
                 _skip_dds: bool = False):
        """
        Args:
            root: tkinter root window.
            nddshome: Path to RTI Connext DDS installation.
            _skip_dds: If True, skip creating DDS objects (for testing).
        """
        self.root = root
        self.root.title("RTI Recording Service Control")
        self.root.geometry("1050x780")
        self.root.minsize(850, 620)

        # Apply dark theme
        apply_dark_theme(root)

        # Paths
        self._script_dir = os.path.dirname(os.path.abspath(__file__))
        self._xml_types_dir = os.path.join(self._script_dir, "xml_types")
        self._python_types_dir = os.path.join(self._script_dir, "python_types")
        self._qos_file = os.path.normpath(os.path.join(
            self._script_dir, "..", "..", "dds", "qos",
            "DDS_QOS_PROFILES.xml"))
        self._admin_qos_file = self._qos_file

        # State
        self._nddshome = nddshome or detect_nddshome()
        self._controller = None
        self._monitoring = None
        self._monitoring_domain_id = None
        self._service_state = STATE_INVALID
        self._service_detected = False
        self._tag_history = []
        self._known_topics = set()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._result_queue = Queue()
        self._monitor_queue = Queue()
        self._result_after_id = None
        self._monitor_after_id = None
        self._closed = False
        self._skip_dds = _skip_dds

        # Build UI
        self._build_menu()
        self._build_config_panel()
        self._build_status_panel()
        self._build_control_bar()
        self._build_bottom_panels()
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)

        # Configure grid weights for root
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)

        # Initialize config dropdown
        self._on_config_file_changed()

        # Update button states
        self._update_button_states()

        # Start monitoring and polling
        if not _skip_dds:
            self._ensure_monitoring_started()
        self._poll_results()
        self._poll_monitor_queue()

    # ===================================================================
    # UI Construction
    # ===================================================================

    def _build_menu(self):
        menubar = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self._on_exit)
        menubar.add_cascade(label="File", menu=file_menu)

    def _build_config_panel(self):
        frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        row = 0

        # NDDSHOME
        ttk.Label(frame, text="NDDSHOME:").grid(
            row=row, column=0, sticky="w", pady=3)
        self._nddshome_var = tk.StringVar(value=self._nddshome)
        ttk.Entry(frame, textvariable=self._nddshome_var, width=45).grid(
            row=row, column=1, sticky="ew", pady=3)
        ttk.Button(frame, text="...",
                   command=self._browse_nddshome).grid(
            row=row, column=2, padx=4, pady=3)
        row += 1

        # Config File
        ttk.Label(frame, text="Config File:").grid(
            row=row, column=0, sticky="w", pady=3)
        self._config_file_var = tk.StringVar(value=DEFAULT_CONFIG_FILE)
        self._config_file_var.trace_add(
            "write", lambda *_: self._on_config_file_changed())
        ttk.Entry(frame, textvariable=self._config_file_var, width=45).grid(
            row=row, column=1, sticky="ew", pady=3)
        ttk.Button(frame, text="...",
                   command=self._browse_config_file).grid(
            row=row, column=2, padx=4, pady=3)
        row += 1

        # Config Name
        ttk.Label(frame, text="Config Name:").grid(
            row=row, column=0, sticky="w", pady=3)
        self._config_name_var = tk.StringVar(value=DEFAULT_CONFIG_NAME)
        self._config_name_combo = ttk.Combobox(
            frame, textvariable=self._config_name_var, width=28,
            state="readonly")
        self._config_name_combo.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # Domain ID
        ttk.Label(frame, text="Domain ID:").grid(
            row=row, column=0, sticky="w", pady=3)
        self._domain_id_var = tk.IntVar(value=DEFAULT_DOMAIN_ID)
        self._domain_id_spin = ttk.Spinbox(
            frame, from_=0, to=232, textvariable=self._domain_id_var, width=8)
        self._domain_id_spin.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # Admin Domain ID
        ttk.Label(frame, text="Admin Domain:").grid(
            row=row, column=0, sticky="w", pady=3)
        self._admin_domain_id_var = tk.IntVar(value=DEFAULT_ADMIN_DOMAIN_ID)
        self._admin_domain_id_var.trace_add(
            "write", lambda *_: self._on_admin_domain_changed())
        ttk.Spinbox(frame, from_=0, to=232,
                     textvariable=self._admin_domain_id_var, width=8).grid(
            row=row, column=1, sticky="w", pady=3)
        row += 1

        # Verbosity
        ttk.Label(frame, text="Verbosity:").grid(
            row=row, column=0, sticky="w", pady=3)
        self._verbosity_var = tk.StringVar(value=DEFAULT_VERBOSITY)
        ttk.Combobox(frame, textvariable=self._verbosity_var, width=18,
                     values=VERBOSITY_OPTIONS, state="readonly").grid(
            row=row, column=1, sticky="w", pady=3)
        row += 1

        frame.columnconfigure(1, weight=1)

    def _build_status_panel(self):
        frame = ttk.LabelFrame(self.root, text="Service Status", padding=10)
        frame.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)

        labels = [
            ("State:", "_state_label"),
            ("Service Name:", "_name_label"),
            ("Uptime:", "_uptime_label"),
            ("CPU Usage:", "_cpu_label"),
            ("Memory:", "_memory_label"),
            ("DB Directory:", "_dbdir_label"),
            ("Current DB:", "_dbfile_label"),
            ("DB Size:", "_dbsize_label"),
            ("Rollover Count:", "_rollover_label"),
            ("Topics:", "_topics_label"),
        ]

        for i, (text, attr) in enumerate(labels):
            ttk.Label(frame, text=text).grid(
                row=i, column=0, sticky="w", pady=2)
            lbl = ttk.Label(frame, text="\u2014", foreground=FG_DIM)
            lbl.grid(row=i, column=1, sticky="w", padx=10, pady=2)
            setattr(self, attr, lbl)

        frame.columnconfigure(1, weight=1)

    def _build_control_bar(self):
        frame = ttk.Frame(self.root, padding=4)
        frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=3)

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
                    padx=6, pady=6)
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)

        # --- Tag Panel (left) ---
        tag_frame = ttk.LabelFrame(bottom, text="Tags", padding=10)
        tag_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tag_input = ttk.Frame(tag_frame)
        tag_input.pack(fill="x")

        ttk.Label(tag_input, text="Name:").grid(row=0, column=0, sticky="w")
        self._tag_name_var = tk.StringVar()
        ttk.Entry(tag_input, textvariable=self._tag_name_var, width=18).grid(
            row=0, column=1, sticky="ew", padx=4, pady=2)

        ttk.Label(tag_input, text="Desc:").grid(row=1, column=0, sticky="w")
        self._tag_desc_var = tk.StringVar()
        ttk.Entry(tag_input, textvariable=self._tag_desc_var, width=18).grid(
            row=1, column=1, sticky="ew", padx=4, pady=2)

        tag_input.columnconfigure(1, weight=1)

        self._tag_btn = ttk.Button(
            tag_frame, text="Set Tag", command=self._on_set_tag)
        self._tag_btn.pack(pady=6)

        # Tag history treeview
        self._tag_tree = ttk.Treeview(
            tag_frame, columns=("name", "time", "desc"),
            show="headings", height=6)
        self._tag_tree.heading("name", text="Name")
        self._tag_tree.heading("time", text="Time")
        self._tag_tree.heading("desc", text="Description")
        self._tag_tree.column("name", width=80)
        self._tag_tree.column("time", width=70)
        self._tag_tree.column("desc", width=100)
        self._tag_tree.pack(fill="both", expand=True)

        # --- Log Panel (right) ---
        log_frame = ttk.LabelFrame(bottom, text="Log", padding=10)
        log_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self._log_text = tk.Text(
            log_frame, height=12, state="disabled", wrap="word",
            font=("Consolas", 9), bg=BG_PANEL, fg=FG_TEXT,
            insertbackground=FG_TEXT, selectbackground=SELECT_BG,
            selectforeground=FG_TEXT, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

    # ===================================================================
    # Public / testable helpers
    # ===================================================================

    def set_service_state(self, state_int: int):
        """Update displayed service state and button states."""
        self._service_state = state_int
        state_name = STATE_NAMES.get(state_int, f"UNKNOWN({state_int})")
        color = STATE_COLORS.get(state_int, FG_RED)
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
            "name": name, "time": timestamp, "description": description,
        })

    def get_launch_command(self) -> list:
        """Build and return the launch command from current config fields."""
        return build_launch_command(
            nddshome=self._nddshome_var.get(),
            config_file=self._config_file_var.get(),
            config_name=self._config_name_var.get(),
            domain_id=self._domain_id_var.get(),
            admin_domain_id=self._admin_domain_id_var.get(),
            verbosity=self._verbosity_var.get(),
            qos_file=self._qos_file,
        )

    # ===================================================================
    # Config file parsing
    # ===================================================================

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
        """Restart monitoring and invalidate controller when the admin domain changes."""
        if self._closed or self._skip_dds:
            return
        # Invalidate controller so it will be re-created with new domain
        if self._controller is not None:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None
        self._ensure_monitoring_started(force_restart=True)

    # ===================================================================
    # Button state management
    # ===================================================================

    def _update_button_states(self):
        """Enable/disable buttons based on current service state."""
        detected = self._service_detected

        self._launch_btn.config(
            state="normal" if not detected else "disabled")
        self._pause_btn.config(
            state="normal" if self._service_state == STATE_RUNNING else "disabled")
        self._resume_btn.config(
            state="normal" if self._service_state == STATE_PAUSED else "disabled")
        self._shutdown_btn.config(
            state="normal" if detected else "disabled")
        self._tag_btn.config(
            state="normal" if detected else "disabled")

    # ===================================================================
    # File browser callbacks
    # ===================================================================

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

    # ===================================================================
    # Command callbacks
    # ===================================================================

    def _on_launch(self):
        """Launch Recording Service in a new terminal window."""
        if not self._skip_dds:
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
        full_cmd = terminal_prefix + [
            "bash", "-c",
            f"{cmd_str}; echo; echo 'Press Enter to close...'; read",
        ]

        self.append_log(f"Launching: {cmd_str}")
        try:
            subprocess.Popen(full_cmd, start_new_session=True)
            self.append_log("Recording Service terminal opened.")
        except Exception as e:
            self.append_log(f"ERROR launching service: {e}")
            messagebox.showerror("Launch Error", str(e))

    def _ensure_controller(self):
        """Create the RecordingServiceController if needed.

        If the admin domain or service name changed since the controller
        was created, discard the old one and create a fresh instance.
        """
        desired_domain = self._admin_domain_id_var.get()
        desired_name = self._config_name_var.get()
        if self._controller is not None:
            # Invalidate if settings changed
            if (getattr(self._controller, '_domain_id', None) != desired_domain or
                    getattr(self._controller, '_service_name', None) != desired_name):
                try:
                    self._controller.close()
                except Exception:
                    pass
                self._controller = None
            else:
                return True
        try:
            from recording_service_control import RecordingServiceController
            self._controller = RecordingServiceController(
                domain_id=desired_domain,
                service_name=desired_name,
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
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.add_tag_to_history(name, ts, desc)
        self._tag_name_var.set("")
        self._tag_desc_var.set("")

    # ===================================================================
    # Monitoring — DDS listener → queue → tkinter
    # ===================================================================

    def _on_monitor_update(self, update: dict):
        """Callback from RecordingServiceMonitor (runs on DDS thread)."""
        self._monitor_queue.put(update)

    def _ensure_monitoring_started(self, force_restart: bool = False):
        """Start or restart monitoring for the selected admin domain."""
        target_domain = self._admin_domain_id_var.get()
        if (not force_restart and self._monitoring is not None
                and self._monitoring_domain_id == target_domain):
            return

        if self._monitoring is not None:
            self._stop_monitoring(log=False)

        try:
            from recording_service_monitor import RecordingServiceMonitor
            self._monitoring = RecordingServiceMonitor(
                domain_id=target_domain,
                python_types_dir=self._python_types_dir,
                qos_file=self._qos_file,
                on_update=self._on_monitor_update,
            )
            self._monitoring_domain_id = target_domain
            self.append_log(f"Monitoring active on domain {target_domain}")
        except Exception as e:
            self._monitoring = None
            self._monitoring_domain_id = None
            self.append_log(f"ERROR starting monitoring: {e}")

    def _stop_monitoring(self, log: bool = True):
        """Close the DDS monitoring subscription."""
        if self._monitoring is not None:
            self._monitoring.close()
            self._monitoring = None
        self._monitoring_domain_id = None
        self._service_detected = False
        self._service_state = STATE_INVALID
        self._update_button_states()
        self._reset_status_labels()
        if log:
            self.append_log("Monitoring stopped.")

    def _reset_status_labels(self):
        """Reset all status labels to defaults."""
        for attr in ("_state_label", "_name_label", "_uptime_label",
                     "_cpu_label", "_memory_label", "_dbdir_label",
                     "_dbfile_label", "_dbsize_label", "_rollover_label",
                     "_topics_label"):
            getattr(self, attr).config(text="\u2014", foreground=FG_DIM)
        self._known_topics.clear()

    def _apply_config_update(self, update: dict):
        """Apply a config monitoring update to the GUI."""
        if update.get("service_name"):
            self._name_label.config(
                text=update["service_name"], foreground=FG_TEXT)
        if update.get("db_directory"):
            self._dbdir_label.config(
                text=update["db_directory"], foreground=FG_TEXT)
        for topic in update.get("topics", []):
            self._known_topics.add(topic)
        if self._known_topics:
            count = len(self._known_topics)
            label = f"{count} topic" if count == 1 else f"{count} topics"
            self._topics_label.config(
                text=label, foreground=FG_TEXT)

    def _apply_event_update(self, update: dict):
        """Apply an event monitoring update to the GUI."""
        state_int = update.get("state_int", STATE_INVALID)
        if state_int != STATE_INVALID:
            self.set_service_state(state_int)
        rollover = update.get("rollover_count", -1)
        if rollover >= 0:
            self._rollover_label.config(
                text=str(rollover), foreground=FG_TEXT)
        for evt in update.get("events", []):
            self.append_log(evt)

    def _apply_periodic_update(self, update: dict):
        """Apply a periodic monitoring update to the GUI."""
        if update.get("uptime", -1) >= 0:
            self._uptime_label.config(
                text=format_uptime(update["uptime"]), foreground=FG_TEXT)
        if update.get("cpu", -1.0) >= 0:
            self._cpu_label.config(
                text=f"{update['cpu']:.1f}%", foreground=FG_TEXT)
        if update.get("memory_kb", -1.0) >= 0:
            self._memory_label.config(
                text=f"{update['memory_kb']:.0f} KB", foreground=FG_TEXT)
        if update.get("db_file"):
            self._dbfile_label.config(
                text=os.path.basename(update["db_file"]),
                foreground=FG_TEXT)
        if update.get("db_file_size", -1) >= 0:
            self._dbsize_label.config(
                text=format_file_size(update["db_file_size"]),
                foreground=FG_TEXT)

    def _poll_monitor_queue(self):
        """Drain the monitor queue and apply updates (tkinter thread)."""
        if self._closed:
            return

        try:
            while True:
                update = self._monitor_queue.get_nowait()
                if update.get("service_detected"):
                    self._service_detected = True

                kind = update.get("kind")
                if kind == "config":
                    self._apply_config_update(update)
                elif kind == "event":
                    self._apply_event_update(update)
                elif kind == "periodic":
                    self._apply_periodic_update(update)
                elif kind == "error":
                    self.append_log(
                        f"Monitoring error: {update.get('error', '?')}")

                self._update_button_states()
        except Empty:
            pass

        self._monitor_after_id = self.root.after(
            POLL_INTERVAL_MS, self._poll_monitor_queue)

    # ===================================================================
    # Result queue — background command results
    # ===================================================================

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

    # ===================================================================
    # Lifecycle
    # ===================================================================

    def close(self):
        """Release resources and cancel scheduled callbacks."""
        if self._closed:
            return
        self._closed = True

        for after_id_attr in ("_result_after_id", "_monitor_after_id"):
            after_id = getattr(self, after_id_attr, None)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
                setattr(self, after_id_attr, None)

        if self._monitoring is not None:
            self._stop_monitoring(log=False)

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
    app.close()


if __name__ == "__main__":
    main()
