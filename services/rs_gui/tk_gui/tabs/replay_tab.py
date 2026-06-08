"""Tkinter Replay tab widgets and adapter wiring for rs_gui."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os
import re
import subprocess
from typing import Callable, Dict, Optional, Tuple

from app_core.debug_log import dbg
from app_core.connext_environment import detect_nddshome
from gui.tabs.replay_tab import (
    ReplayLaunchViewModel,
    ReplayTabViewModel,
    build_replay_action_command,
    build_replay_launch_command,
    build_replay_next_tag_command,
)
from ..theme import DARK_THEME


_VERBOSITY_LEVELS = ("SILENT", "ERROR", "WARN", "LOCAL", "REMOTE", "ALL")
_REPLAY_MONITORING_FIELDS = (
    "state",
    "progress",
    "playback_rate",
    "loop",
    "database",
    "pid",
    "hostname",
)
_REPLAY_MONITORING_COLUMN_WIDTH = 42
_REPLAY_MONITORING_ROWS = (_REPLAY_MONITORING_FIELDS.__len__() + 1) // 2
_TAGS_FOUND_COLOR = "#7fd38d"
_TAGS_NONE_COLOR = DARK_THEME["muted"]
_TAGS_ERROR_COLOR = DARK_THEME["danger"]
_DEFAULT_TRANSIENT_LOCAL_WRITER_QOS = "DataPatternsLibrary::replay_writer_transient_local"
_TAG_TIME_TOKEN_RE = re.compile(
    r"(?:\d{2}:\d{2}:\d{2}(?:\.\d+)?|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)"
)


def _split_verbosity(value: str) -> tuple[str, str]:
    raw = str(value or "").strip().upper()
    if not raw:
        return ("ERROR", "ERROR")
    parts = raw.split(":", 1)
    service_level = parts[0].strip() or "ERROR"
    api_level = parts[1].strip() if len(parts) > 1 else service_level
    if service_level not in _VERBOSITY_LEVELS:
        service_level = "ERROR"
    if api_level not in _VERBOSITY_LEVELS:
        api_level = "ERROR"
    return (service_level, api_level)


def _join_verbosity(service_level: str, api_level: str) -> str:
    service = str(service_level or "ERROR").strip().upper() or "ERROR"
    api = str(api_level or "ERROR").strip().upper() or "ERROR"
    if service not in _VERBOSITY_LEVELS:
        service = "ERROR"
    if api not in _VERBOSITY_LEVELS:
        api = "ERROR"
    return f"{service}:{api}"


class ReplayTabAdapter:
    """Thin adapter that keeps Tk widgets on the existing Replay/session boundary."""

    def __init__(
            self,
            command_sink: Callable[[object], bool],
            select_target: Callable[[str], object],
    ) -> None:
        self._command_sink = command_sink
        self._select_target = select_target

    def select_target(self, target_id: str) -> object:
        return self._select_target(target_id)

    def queue_launch(self, launch: ReplayLaunchViewModel) -> bool:
        return bool(self._command_sink(build_replay_launch_command(launch)))

    def queue_action(self, action_id: str, replay_view: ReplayTabViewModel) -> bool:
        return bool(self._command_sink(build_replay_action_command(action_id, replay_view)))

    def queue_next_tag(self, replay_view: ReplayTabViewModel, tag_name: str) -> bool:
        return bool(self._command_sink(build_replay_next_tag_command(replay_view, tag_name)))


class TkReplayTab:
    """Tkinter Replay tab renderer backed by immutable shell snapshots."""

    def __init__(self, parent, ttk, tk, adapter: Optional[ReplayTabAdapter] = None) -> None:
        self._ttk = ttk
        self._tk = tk
        self._adapter = adapter
        self._view: Optional[ReplayTabViewModel] = None
        self._target_display_to_id: Dict[str, str] = {}
        self._launch_initialized = False
        self._launch_preview_expanded = False
        self._monitoring_section_expanded = True
        self._mousewheel_bound = False
        self._mousewheel_bind_ids: Dict[str, str] = {}
        self._tags_output_cache = ""
        self._tag_windows: Tuple[Tuple[str, str, str], ...] = ()
        self._tag_names: Tuple[str, ...] = ()
        self._has_tags = False

        outer = ttk.Frame(parent)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        self.frame = outer

        self._canvas = tk.Canvas(
            outer,
            background=DARK_THEME["bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        self._vscroll = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")

        frame = ttk.Frame(self._canvas)
        frame.columnconfigure(0, weight=1)
        self.content_frame = frame
        self._canvas_window = self._canvas.create_window((0, 0), window=frame, anchor="nw")
        self.content_frame.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self.frame.bind("<Enter>", self._on_dialog_enter)
        self.frame.bind("<Leave>", self._on_dialog_leave)

        selector = ttk.LabelFrame(frame, text="Targets And Actions", padding=12)
        selector.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        selector.columnconfigure(1, weight=1)

        self.target_select_var = tk.StringVar(value="")
        ttk.Label(selector, text="Target").grid(row=0, column=0, sticky="w")
        self.target_combo = ttk.Combobox(selector, textvariable=self.target_select_var, state="readonly")
        self.target_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.target_combo.bind("<<ComboboxSelected>>", self._on_target_selected)

        self.tags_status_var = tk.StringVar(value="Tags: unknown")
        self.tags_status_label = tk.Label(
            selector,
            textvariable=self.tags_status_var,
            anchor="w",
            background=DARK_THEME["panel"],
            foreground=_TAGS_NONE_COLOR,
        )
        self.tags_status_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        actions = ttk.Frame(selector)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.action_buttons = {}
        for index, action_id in enumerate(("start", "pause", "resume", "stop", "shutdown")):
            button = ttk.Button(actions, text=action_id.title(), command=lambda value=action_id: self._on_action_clicked(value))
            button.grid(row=0, column=index, sticky="w", padx=(0, 8))
            self.action_buttons[action_id] = button
        self.next_tag_button = ttk.Button(actions, text="Go To", command=self._on_go_to_tag_clicked)
        self.next_tag_button.grid(row=0, column=5, sticky="w", padx=(0, 8))
        self.go_to_tag_var = tk.StringVar(value="")
        ttk.Label(actions, text="Tag").grid(row=0, column=6, sticky="w", padx=(8, 6))
        self.go_to_tag_combo = ttk.Combobox(actions, textvariable=self.go_to_tag_var, state="readonly", width=24)
        self.go_to_tag_combo.grid(
            row=0,
            column=7,
            sticky="w",
        )

        launch = ttk.LabelFrame(frame, text="Launch Replay Service", padding=12)
        launch.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        launch.columnconfigure(1, weight=1)
        launch.columnconfigure(3, weight=1)

        self.config_name_var = tk.StringVar(value="")
        self.database_path_var = tk.StringVar(value="")
        self.service_verbosity_var = tk.StringVar(value="ERROR")
        self.api_verbosity_var = tk.StringVar(value="ERROR")
        self.playback_rate_var = tk.StringVar(value="1.0")
        self.loop_var = tk.BooleanVar(value=False)
        self.time_window_var = tk.StringVar(value="")
        self.data_domain_var = tk.StringVar(value="0")
        self.admin_domain_var = tk.StringVar(value="0")
        self.monitoring_domain_var = tk.StringVar(value="0")
        self.topic_allow_var = tk.StringVar(value="*")
        self.topic_deny_var = tk.StringVar(value="rti/*")
        self.qos_file_var = tk.StringVar(value="")
        self.participant_qos_var = tk.StringVar(value="")
        self.writer_qos_var = tk.StringVar(value="")
        self.writer_transient_local_var = tk.BooleanVar(value=True)
        self.config_paths_var = tk.StringVar(value="")
        self.writer_qos_summary_var = tk.StringVar(value="")

        ttk.Label(launch, text="Playback file / directory").grid(row=0, column=0, columnspan=4, sticky="w")
        db_path_frame = ttk.Frame(launch)
        db_path_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        db_path_frame.columnconfigure(0, weight=1)
        ttk.Entry(db_path_frame, textvariable=self.database_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(db_path_frame, text="Browse...", command=self._on_browse_database_file).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 0),
        )
        ttk.Label(launch, text="Config name").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.config_name_var).grid(row=2, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))

        verbosity_row = ttk.Frame(launch)
        verbosity_row.grid(row=2, column=2, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(verbosity_row, text="Service verbosity").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            verbosity_row,
            textvariable=self.service_verbosity_var,
            state="readonly",
            values=_VERBOSITY_LEVELS,
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=(8, 12))
        ttk.Label(verbosity_row, text="API verbosity").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            verbosity_row,
            textvariable=self.api_verbosity_var,
            state="readonly",
            values=_VERBOSITY_LEVELS,
            width=8,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        timing_row = ttk.Frame(launch)
        timing_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(timing_row, text="Playback rate").grid(row=0, column=0, sticky="w")
        ttk.Entry(timing_row, textvariable=self.playback_rate_var, width=8).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Checkbutton(timing_row, text="Loop", variable=self.loop_var).grid(row=0, column=2, sticky="w")

        domain_row = ttk.Frame(launch)
        domain_row.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(domain_row, text="Data domain").grid(row=0, column=0, sticky="w")
        ttk.Entry(domain_row, textvariable=self.data_domain_var, width=2).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(domain_row, text="Admin domain").grid(row=0, column=2, sticky="w")
        ttk.Entry(domain_row, textvariable=self.admin_domain_var, width=2).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Label(domain_row, text="Monitoring domain").grid(row=0, column=4, sticky="w")
        ttk.Entry(domain_row, textvariable=self.monitoring_domain_var, width=2).grid(row=0, column=5, sticky="w", padx=(8, 0))

        topic_row = ttk.Frame(launch)
        topic_row.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        topic_row.columnconfigure(1, weight=1)
        topic_row.columnconfigure(3, weight=1)
        ttk.Label(topic_row, text="Topic allow").grid(row=0, column=0, sticky="w")
        ttk.Entry(topic_row, textvariable=self.topic_allow_var).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(topic_row, text="Topic deny").grid(row=0, column=2, sticky="w")
        ttk.Entry(topic_row, textvariable=self.topic_deny_var).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        qos_row = ttk.Frame(launch)
        qos_row.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        qos_row.columnconfigure(1, weight=1)
        ttk.Button(qos_row, text="Writer QoS...", command=self._open_writer_qos_dialog).grid(row=0, column=0, sticky="w")
        ttk.Label(qos_row, textvariable=self.writer_qos_summary_var, justify="left").grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(launch, text="Config files").grid(row=7, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(launch, textvariable=self.config_paths_var, justify="left", wraplength=780).grid(row=7, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.launch_preview_toggle = ttk.Button(
            launch,
            text="> Launch preview",
            command=self._on_toggle_launch_preview,
        )
        self.launch_preview_toggle.grid(row=8, column=0, sticky="w", pady=(8, 0))
        self.launch_preview_text = tk.Text(
            launch,
            height=4,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
            background=DARK_THEME["panel_alt"],
            foreground=DARK_THEME["text"],
            insertbackground=DARK_THEME["text"],
            selectbackground=DARK_THEME["selection"],
            selectforeground=DARK_THEME["text"],
        )
        self.launch_preview_text.grid(row=8, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.launch_preview_text.grid_remove()
        self.launch_button = ttk.Button(launch, text="Launch Replay Service", command=self._on_launch_clicked)
        self.launch_button.grid(row=9, column=3, sticky="e", pady=(12, 0))

        for variable in (
                self.config_name_var,
                self.database_path_var,
            self.service_verbosity_var,
            self.api_verbosity_var,
                self.playback_rate_var,
                self.time_window_var,
                self.data_domain_var,
                self.admin_domain_var,
                self.monitoring_domain_var,
                self.topic_allow_var,
                self.topic_deny_var,
                self.qos_file_var,
                self.participant_qos_var,
                self.writer_qos_var,
                self.writer_transient_local_var,
        ):
            variable.trace_add("write", self._on_launch_form_changed)

        summary = ttk.LabelFrame(frame, text="Replay Status", padding=12)
        summary.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        summary.columnconfigure(0, weight=1)

        self.target_var = tk.StringVar(value="Target: none")
        self.readiness_var = tk.StringVar(value="Readiness: not checked")
        self.state_var = tk.StringVar(value="State: no service")
        self.database_var = tk.StringVar(value="Database: -")
        self.error_var = tk.StringVar(value="")

        ttk.Label(summary, textvariable=self.target_var).grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.readiness_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(summary, textvariable=self.state_var).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(summary, textvariable=self.database_var).grid(row=3, column=0, sticky="w", pady=(4, 0))

        self.monitoring_toggle = ttk.Button(
            summary,
            text="v Monitoring details",
            command=self._on_toggle_monitoring_section,
        )
        self.monitoring_toggle.grid(row=4, column=0, sticky="w", pady=(6, 0))
        monitoring = ttk.Frame(summary)
        monitoring.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        monitoring.columnconfigure(0, weight=1)
        self.monitoring_frame = monitoring
        self.monitoring_text = tk.Text(
            monitoring,
            height=_REPLAY_MONITORING_ROWS + 1,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
            background=DARK_THEME["panel_alt"],
            foreground=DARK_THEME["text"],
            insertbackground=DARK_THEME["text"],
            selectbackground=DARK_THEME["selection"],
            selectforeground=DARK_THEME["text"],
            font="TkFixedFont",
        )
        self.monitoring_text.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(summary, textvariable=self.error_var, wraplength=860, justify="left").grid(row=6, column=0, sticky="w", pady=(6, 0))

        diagnostics = ttk.LabelFrame(frame, text="Replay Diagnostics", padding=12)
        diagnostics.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))
        diagnostics.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        self.diagnostics_list = tk.Listbox(diagnostics, height=6)
        self.diagnostics_list.configure(
            background=DARK_THEME["panel_alt"],
            foreground=DARK_THEME["text"],
            selectbackground=DARK_THEME["selection"],
            selectforeground=DARK_THEME["text"],
            highlightbackground=DARK_THEME["border"],
            highlightcolor=DARK_THEME["accent"],
            borderwidth=1,
            relief="solid",
        )
        self.diagnostics_list.grid(row=0, column=0, sticky="nsew")

    def render(self, view: ReplayTabViewModel) -> None:
        self._view = view
        selected = view.selected_target
        self.target_var.set(f"Target: {selected.control_name if selected is not None else 'none'}")
        self.readiness_var.set(f"Readiness: {view.readiness}")
        self.state_var.set(f"State: {view.observed_state} | Playback rate: {view.playback_rate:g}")
        self.database_var.set(f"Database: {view.database_path or '-'}")
        self._set_monitoring_text(_fixed_replay_monitoring_text(view))
        self.error_var.set(" | ".join(view.diagnostics[:3]))

        self._render_targets(view)
        self._render_launch_form(view.launch)
        self._render_actions(view)
        self._render_diagnostics(view)

    def _render_targets(self, view: ReplayTabViewModel) -> None:
        options = []
        self._target_display_to_id = {}
        selected_display = ""
        for row in view.targets:
            display = f"{row.label} | {row.state} | {row.hostname} | {row.progress or '-'}"
            options.append(display)
            self._target_display_to_id[display] = row.target_id
            if row.target_id == view.selected_target_id:
                selected_display = display
        self.target_combo["values"] = tuple(options)
        self.target_select_var.set(selected_display or (options[0] if options else ""))

    def _render_launch_form(self, launch: ReplayLaunchViewModel) -> None:
        if self._launch_initialized:
            return
        self.config_name_var.set(launch.config_name)
        self.database_path_var.set(launch.database_path)
        service_level, api_level = _split_verbosity(launch.verbosity)
        self.service_verbosity_var.set(service_level)
        self.api_verbosity_var.set(api_level)
        self.playback_rate_var.set(f"{launch.playback_rate:g}")
        self.loop_var.set(launch.loop)
        self.time_window_var.set(launch.time_window)
        self.data_domain_var.set(str(launch.data_domain_id))
        self.admin_domain_var.set(str(launch.admin_domain_id))
        self.monitoring_domain_var.set(str(launch.monitoring_domain_id))
        self.topic_allow_var.set(launch.topic_allow)
        self.topic_deny_var.set(launch.topic_deny)
        self.qos_file_var.set(launch.qos_file_path)
        self.participant_qos_var.set(launch.participant_qos_profile)
        self.writer_qos_var.set(launch.writer_qos_profile)
        self.config_paths_var.set("; ".join(launch.config_paths) or "-")
        self._refresh_writer_qos_summary()
        self._set_launch_preview_text(launch.command_preview)
        self._launch_initialized = True
        self._auto_list_tags_for_current_path()

    def _render_actions(self, view: ReplayTabViewModel) -> None:
        action_map = view.action_by_id
        for action_id, button in self.action_buttons.items():
            action = action_map.get(action_id)
            if action is None or not action.enabled:
                button.state(["disabled"])
            else:
                button.state(["!disabled"])
        self._refresh_next_tag_button_state()

    def _refresh_next_tag_button_state(self) -> None:
        if self._has_tags and self._tag_names:
            self.next_tag_button.state(["!disabled"])
        else:
            self.next_tag_button.state(["disabled"])
        self._refresh_go_to_tag_dropdown()

    def _refresh_go_to_tag_dropdown(self) -> None:
        values = tuple(self._tag_names)
        self.go_to_tag_combo["values"] = values
        if not values:
            self.go_to_tag_var.set("")
            return
        selected = self.go_to_tag_var.get().strip()
        if selected not in values:
            self.go_to_tag_var.set(values[0])

    def _render_diagnostics(self, view: ReplayTabViewModel) -> None:
        self.diagnostics_list.delete(0, self._tk.END)
        items = list(view.diagnostics) or [f"Observed state: {view.observed_state}"]
        for item in items[:6]:
            self.diagnostics_list.insert(self._tk.END, item)

    def _set_monitoring_text(self, value: str) -> None:
        self.monitoring_text.configure(state="normal")
        self.monitoring_text.delete("1.0", self._tk.END)
        self.monitoring_text.insert("1.0", value)
        self.monitoring_text.configure(state="disabled")

    def _set_monitoring_section_expanded(self, expanded: bool) -> None:
        self._monitoring_section_expanded = bool(expanded)
        if self._monitoring_section_expanded:
            self.monitoring_toggle.configure(text="v Monitoring details")
            self.monitoring_frame.grid()
        else:
            self.monitoring_toggle.configure(text="> Monitoring details")
            self.monitoring_frame.grid_remove()

    def _on_toggle_monitoring_section(self) -> None:
        self._set_monitoring_section_expanded(not self._monitoring_section_expanded)

    def _set_tags_text(self, value: str) -> None:
        self._tags_output_cache = str(value or "")

    def _set_tags_indicator(self, text: str, color: str) -> None:
        self.tags_status_var.set(text)
        self.tags_status_label.configure(foreground=color)

    def _set_launch_preview_text(self, value: str) -> None:
        self.launch_preview_text.configure(state="normal")
        self.launch_preview_text.delete("1.0", self._tk.END)
        self.launch_preview_text.insert("1.0", value)
        self.launch_preview_text.configure(state="disabled")

    def _on_content_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_dialog_enter(self, _event=None) -> None:
        if self._mousewheel_bound:
            return
        self._mousewheel_bound = True
        target = self.frame.winfo_toplevel()
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            bind_id = target.bind(sequence, self._on_mousewheel, add="+")
            if bind_id:
                self._mousewheel_bind_ids[sequence] = bind_id

    def _on_dialog_leave(self, _event=None) -> None:
        if not self._mousewheel_bound:
            return
        self._mousewheel_bound = False
        target = self.frame.winfo_toplevel()
        for sequence, bind_id in tuple(self._mousewheel_bind_ids.items()):
            target.unbind(sequence, bind_id)
        self._mousewheel_bind_ids.clear()

    def _on_mousewheel(self, event):
        if not self._pointer_inside_dialog(event):
            return None
        step = 0
        delta = int(getattr(event, "delta", 0) or 0)
        if delta:
            step = -1 if delta > 0 else 1
        else:
            event_num = int(getattr(event, "num", 0) or 0)
            if event_num == 4:
                step = -1
            elif event_num == 5:
                step = 1
        if step:
            self._canvas.yview_scroll(step, "units")
            return "break"
        return None

    def _pointer_inside_dialog(self, event) -> bool:
        widget = getattr(event, "widget", None)
        while widget is not None:
            if widget is self.frame:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _set_launch_preview_expanded(self, expanded: bool) -> None:
        self._launch_preview_expanded = bool(expanded)
        if self._launch_preview_expanded:
            self.launch_preview_toggle.configure(text="v Launch preview")
            self.launch_preview_text.grid()
        else:
            self.launch_preview_toggle.configure(text="> Launch preview")
            self.launch_preview_text.grid_remove()

    def _on_toggle_launch_preview(self) -> None:
        self._set_launch_preview_expanded(not self._launch_preview_expanded)

    def _on_launch_form_changed(self, *_args) -> None:
        if not self._launch_initialized:
            return
        self._refresh_writer_qos_summary()
        self._set_launch_preview_text(self._build_launch_preview_from_form())

    def _build_launch_preview_from_form(self) -> str:
        data_domain = self.data_domain_var.get().strip() or "0"
        admin_domain = self.admin_domain_var.get().strip() or "0"
        monitoring_domain = self.monitoring_domain_var.get().strip() or "0"
        database_path = self.database_path_var.get().strip() or "<database_path>"
        topic_allow = self.topic_allow_var.get().strip() or "*"
        topic_deny = self.topic_deny_var.get().strip()
        qos_file_path = self.qos_file_var.get().strip()
        participant_qos_profile = self.participant_qos_var.get().strip()
        writer_qos_profile = self._effective_writer_qos_profile()
        executable = self._view.launch.executable if self._view is not None else ""
        executable = executable or "rtireplayservice"
        config_name = self.config_name_var.get().strip() or "<config>"
        playback_rate = self.playback_rate_var.get().strip() or "1.0"
        loop_text = "true" if self.loop_var.get() else "false"
        verbosity = _join_verbosity(self.service_verbosity_var.get(), self.api_verbosity_var.get())
        config_paths = self.config_paths_var.get().strip()
        env_text = " ".join((
            f"REPLAY_DOMAIN_ID={data_domain}",
            f"REPLAY_ADMIN_DOMAIN_ID={admin_domain}",
            f"REPLAY_MON_DOMAIN_ID={monitoring_domain}",
            f"REPLAY_DATABASE_DIR={database_path}",
            f"REPLAY_TOPIC_ALLOW={topic_allow}",
            f"REPLAY_TOPIC_DENY={topic_deny}",
            f"DOMAIN_ID={data_domain}",
        ))
        cmd_parts = [
            executable,
            "-cfgName", config_name,
            "-appName", "<generated>",
            "-remoteAdministrationDomainId", admin_domain,
            "-remoteMonitoringDomainId", monitoring_domain,
            "-verbosity", verbosity,
        ]
        if config_paths and config_paths != "-":
            cmd_parts.extend(["-cfgFile", config_paths])
        cmd_parts.extend([
            f"-DREPLAY_DOMAIN_ID={data_domain}",
            f"-DREPLAY_ADMIN_DOMAIN_ID={admin_domain}",
            f"-DREPLAY_MON_DOMAIN_ID={monitoring_domain}",
            f"-DREPLAY_DATABASE_DIR={database_path}",
            f"-DREPLAY_PLAYBACK_RATE={playback_rate}",
            f"-DREPLAY_ENABLE_LOOPING={loop_text}",
            f"-DREPLAY_TOPIC_ALLOW={topic_allow}",
            f"-DREPLAY_TOPIC_DENY={topic_deny}",
            f"-DDOMAIN_ID={data_domain}",
        ])
        if qos_file_path:
            cmd_parts.append(f"-DREPLAY_QOS_FILE={qos_file_path}")
        if participant_qos_profile:
            cmd_parts.append(f"-DREPLAY_DP_QOS={participant_qos_profile}")
        if writer_qos_profile:
            cmd_parts.append(f"-DREPLAY_DW_QOS={writer_qos_profile}")
        return env_text + "\n" + " ".join(cmd_parts)

    def _effective_writer_qos_profile(self) -> str:
        writer_qos_profile = self.writer_qos_var.get().strip()
        if writer_qos_profile:
            return writer_qos_profile
        if self.writer_transient_local_var.get():
            return _DEFAULT_TRANSIENT_LOCAL_WRITER_QOS
        return ""

    def _refresh_writer_qos_summary(self) -> None:
        writer_qos = self._effective_writer_qos_profile()
        summary = f"Writer QoS: {writer_qos or '-'}"
        if self.writer_transient_local_var.get() and not self.writer_qos_var.get().strip():
            summary += " (transient local default)"
        self.writer_qos_summary_var.set(summary)

    def _open_writer_qos_dialog(self) -> None:
        dialog = self._tk.Toplevel(self.frame)
        dialog.title("Replay Writer QoS")
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()
        container = self._ttk.Frame(dialog, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(1, weight=1)

        self._ttk.Label(container, text="QoS file").grid(row=0, column=0, sticky="w")
        self._ttk.Entry(container, textvariable=self.qos_file_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self._ttk.Button(container, text="Browse...", command=self._on_browse_qos_file).grid(row=0, column=2, sticky="e")

        self._ttk.Label(container, text="Participant QoS").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._ttk.Entry(container, textvariable=self.participant_qos_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(8, 0))

        self._ttk.Label(container, text="Writer QoS").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self._ttk.Entry(container, textvariable=self.writer_qos_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(8, 0))

        self._ttk.Checkbutton(
            container,
            text="Default writer to transient local durability",
            variable=self.writer_transient_local_var,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self._ttk.Button(container, text="Close", command=dialog.destroy).grid(row=4, column=2, sticky="e", pady=(12, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _on_browse_qos_file(self) -> None:
        try:
            from tkinter import filedialog
        except Exception:
            self.error_var.set("File dialog is unavailable in this environment")
            return
        start_file = self.qos_file_var.get().strip()
        start_dir = os.path.dirname(start_file) if start_file else None
        selected = filedialog.askopenfilename(
            parent=self.frame,
            title="Select QoS XML file",
            initialdir=start_dir or None,
            filetypes=(("XML files", "*.xml"), ("All files", "*")),
        )
        if selected:
            self.qos_file_var.set(selected)

    def _on_target_selected(self, _event=None) -> None:
        target_id = self._target_display_to_id.get(self.target_select_var.get(), "")
        if target_id and self._adapter is not None:
            self._adapter.select_target(target_id)

    def _on_launch_clicked(self) -> None:
        if self._adapter is None or self._view is None:
            return
        try:
            database_path = _normalize_replay_database_path(self.database_path_var.get().strip())
            self.database_path_var.set(database_path)
            launch = replace(
                self._view.launch,
                config_name=self.config_name_var.get().strip(),
                database_path=database_path,
                playback_rate=float(self.playback_rate_var.get().strip() or self._view.launch.playback_rate),
                loop=bool(self.loop_var.get()),
                time_window=self.time_window_var.get().strip(),
                verbosity=_join_verbosity(self.service_verbosity_var.get(), self.api_verbosity_var.get()),
                data_domain_id=int(self.data_domain_var.get().strip() or self._view.launch.data_domain_id),
                admin_domain_id=int(self.admin_domain_var.get().strip() or self._view.launch.admin_domain_id),
                monitoring_domain_id=int(self.monitoring_domain_var.get().strip() or self._view.launch.monitoring_domain_id),
                topic_allow=self.topic_allow_var.get().strip() or self._view.launch.topic_allow,
                topic_deny=self.topic_deny_var.get().strip(),
                qos_file_path=self.qos_file_var.get().strip(),
                participant_qos_profile=self.participant_qos_var.get().strip(),
                writer_qos_profile=self._effective_writer_qos_profile(),
            )
            accepted = self._adapter.queue_launch(launch)
            self.error_var.set("Launch queued" if accepted else "Launch command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))

    def _on_browse_database_file(self) -> None:
        try:
            from tkinter import filedialog
        except Exception:
            self.error_var.set("File dialog is unavailable in this environment")
            return
        start_dir = _resolve_database_dialog_initialdir(self.database_path_var.get().strip())
        selected = filedialog.askopenfilename(
            parent=self.frame,
            title="Select replay database file",
            initialdir=start_dir or None,
            filetypes=(("SQLite DB", "*.db"), ("All files", "*")),
        )
        if not selected:
            return
        self.database_path_var.set(_normalize_replay_database_path(selected))
        self._auto_list_tags_for_current_path()

    def _on_action_clicked(self, action_id: str) -> None:
        if self._adapter is None or self._view is None:
            return
        try:
            accepted = self._adapter.queue_action(action_id, self._view)
            self.error_var.set(f"{action_id} queued" if accepted else f"{action_id} command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))

    def _on_go_to_tag_clicked(self) -> None:
        if self._adapter is None or self._view is None:
            return
        if not self._tag_names:
            tags_output = self._tags_output_cache
            self._tag_windows = _extract_tag_windows(tags_output)
            self._tag_names = _extract_tag_names(tags_output)
            if not self._tag_names and self._tag_windows:
                self._tag_names = tuple(dict.fromkeys(window[2] for window in self._tag_windows if str(window[2]).strip()))
            self._refresh_next_tag_button_state()
        if not self._tag_names:
            dbg(
                "replay.next_tag",
                "Unable to derive tag names",
                has_tags=self._has_tags,
                database_path=self.database_path_var.get().strip(),
                tags_text_preview=(self._tags_output_cache[:400]),
            )
            self.error_var.set("Tags found, but no tag names were detected in list-tags output.")
            return
        label = self.go_to_tag_var.get().strip() or self._tag_names[0]
        if label not in self._tag_names:
            label = self._tag_names[0]
            self.go_to_tag_var.set(label)

        time_window = self.time_window_var.get().strip()
        for start_time, end_time, tag_label in self._tag_windows:
            if str(tag_label).strip() == label:
                time_window = f"{start_time} - {end_time}"
                self.time_window_var.set(time_window)
                break
        try:
            replay_view = replace(
                self._view,
                database_path=_normalize_replay_database_path(self.database_path_var.get().strip()),
                playback_rate=float(self.playback_rate_var.get().strip() or self._view.playback_rate),
                loop=bool(self.loop_var.get()),
                time_window=time_window,
                qos_file_path=self.qos_file_var.get().strip(),
                participant_qos_profile=self.participant_qos_var.get().strip(),
                writer_qos_profile=self._effective_writer_qos_profile(),
            )
            accepted = self._adapter.queue_next_tag(replay_view, label)
            if accepted:
                self.error_var.set(f"Jumping to tag: {label}")
            else:
                self.error_var.set("next_tag command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))

    def _on_list_tags_clicked(self) -> None:
        self._list_tags_for_current_path(silent_when_missing=False)

    def _auto_list_tags_for_current_path(self) -> None:
        self._list_tags_for_current_path(silent_when_missing=True)

    def _list_tags_for_current_path(self, silent_when_missing: bool) -> None:
        db_dir = _normalize_replay_database_path(self.database_path_var.get().strip())
        if not db_dir:
            self._has_tags = False
            self._tag_windows = ()
            self._tag_names = ()
            self._refresh_next_tag_button_state()
            self._set_tags_indicator("Tags: no database selected", _TAGS_NONE_COLOR)
            if not silent_when_missing:
                self.error_var.set("Database path is required to list tags")
                self._set_tags_text("No database directory selected.")
            return
        resolved_db_dir = db_dir if os.path.isabs(db_dir) else os.path.join(_repo_root(), db_dir)
        resolved_db_dir = os.path.normpath(resolved_db_dir)
        if not os.path.isdir(resolved_db_dir):
            self._has_tags = False
            self._tag_windows = ()
            self._tag_names = ()
            self._refresh_next_tag_button_state()
            self._set_tags_indicator("Tags: directory missing", _TAGS_NONE_COLOR)
            if not silent_when_missing:
                self.error_var.set(f"Database directory does not exist: {resolved_db_dir}")
                self._set_tags_text(f"Database directory does not exist:\n{resolved_db_dir}")
            return

        if not _has_replay_db_files(resolved_db_dir):
            self._has_tags = False
            self._tag_windows = ()
            self._tag_names = ()
            self._refresh_next_tag_button_state()
            self._set_tags_indicator("Tags: no database files", _TAGS_NONE_COLOR)
            if not silent_when_missing:
                self.error_var.set("No replay .db files found in selected directory")
                self._set_tags_text(f"No replay .db files found in:\n{resolved_db_dir}")
            return

        executable = _resolve_list_tags_executable()
        command = [executable, "-d", resolved_db_dir]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True)
        except Exception as exc:
            self._has_tags = False
            self._tag_windows = ()
            self._tag_names = ()
            self._refresh_next_tag_button_state()
            self._set_tags_indicator("Tags: error", _TAGS_ERROR_COLOR)
            self.error_var.set(f"List tags failed: {exc}")
            self._set_tags_text(f"Command failed to start:\n{' '.join(command)}\n\n{exc}")
            return

        output = (result.stdout or "").strip()
        errors = (result.stderr or "").strip()
        if result.returncode == 0:
            has_tags = _output_has_tags(output)
            self._has_tags = has_tags
            if has_tags:
                self._set_tags_indicator("Tags: found", _TAGS_FOUND_COLOR)
            else:
                self._set_tags_indicator("Tags: none", _TAGS_NONE_COLOR)
            self._tag_windows = _extract_tag_windows(output)
            self._tag_names = _extract_tag_names(output)
            if not self._tag_names and self._tag_windows:
                self._tag_names = tuple(dict.fromkeys(window[2] for window in self._tag_windows if str(window[2]).strip()))
            self._refresh_next_tag_button_state()
            self.error_var.set("Tags listed")
            self._set_tags_text(output or "No tags found.")
        else:
            self._has_tags = False
            self._set_tags_indicator("Tags: error", _TAGS_ERROR_COLOR)
            self.error_var.set(f"List tags failed (exit {result.returncode})")
            self._tag_windows = ()
            self._tag_names = ()
            self._refresh_next_tag_button_state()
            details = output
            if errors:
                details = (details + "\n\n" if details else "") + errors
            self._set_tags_text(details or f"Command failed with exit code {result.returncode}.")


def _normalize_replay_database_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    base = os.path.basename(value).lower()
    if base == "metadata.db" or (base.startswith("data_") and base.endswith(".db")):
        return os.path.dirname(value) or value
    return value


def _resolve_database_dialog_initialdir(path: str) -> str:
    value = _normalize_replay_database_path(path)
    if not value:
        return ""
    candidate = value if os.path.isabs(value) else os.path.join(_repo_root(), value)
    candidate = os.path.normpath(candidate)
    if os.path.isfile(candidate):
        return os.path.dirname(candidate)
    if os.path.isdir(candidate):
        return candidate
    parent = os.path.dirname(candidate)
    while parent and parent != os.path.dirname(parent):
        if os.path.isdir(parent):
            return parent
        parent = os.path.dirname(parent)
    return _repo_root()


def _has_replay_db_files(directory: str) -> bool:
    candidate = os.path.normpath(str(directory or "").strip())
    if not candidate or not os.path.isdir(candidate):
        return False
    if os.path.isfile(os.path.join(candidate, "metadata.db")):
        return True
    try:
        return any(name.endswith(".db") for name in os.listdir(candidate))
    except OSError:
        return False


def _repo_root() -> str:
    cursor = os.path.abspath(os.path.dirname(__file__))
    while True:
        if (
            os.path.isfile(os.path.join(cursor, "ARCHITECTURE.md"))
            and os.path.isdir(os.path.join(cursor, "dds", "qos"))
            and os.path.isdir(os.path.join(cursor, "services", "rs_gui"))
        ):
            return cursor
        parent = os.path.dirname(cursor)
        if parent == cursor:
            return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
        cursor = parent


def _resolve_list_tags_executable() -> str:
    nddshome = os.environ.get("NDDSHOME", "") or detect_nddshome()
    if not nddshome:
        return "rtirecordingservice_list_tags"
    candidate = os.path.join(nddshome, "bin", "rtirecordingservice_list_tags")
    if os.path.isfile(candidate):
        return candidate
    return "rtirecordingservice_list_tags"


def _output_has_tags(text: str) -> bool:
    cleaned = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not cleaned:
        return False
    joined = " ".join(cleaned).lower()
    if "no tags" in joined or "no tag" in joined:
        return False
    return True


def _extract_tag_windows(text: str) -> Tuple[Tuple[str, str, str], ...]:
    windows = []
    seen = set()
    pending_begin: Optional[str] = None
    pending_label: str = ""

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        matches = _TAG_TIME_TOKEN_RE.findall(line)

        # Common one-line format: "tag_a: 00:00:10 -> 00:00:20" or
        # "tag_a begin ... end ..." (including ISO timestamps).
        if len(matches) >= 2:
            start_time = matches[0]
            end_time = matches[1]
            tag_label = line
            if ":" in line:
                maybe_label = line.split(":", 1)[0].strip()
                if maybe_label:
                    tag_label = maybe_label
            key = (start_time, end_time, tag_label)
            if key not in seen:
                seen.add(key)
                windows.append(key)
            continue

        # Multi-line format support:
        # Tag: X
        # Begin Time: ...
        # End Time: ...
        if "tag" in lower and ":" in line and not matches:
            pending_label = line.split(":", 1)[1].strip() or pending_label
            continue

        if ("begin" in lower or "start" in lower) and matches:
            pending_begin = matches[0]
            if ":" in line and not pending_label:
                pending_label = line.split(":", 1)[0].strip()
            continue

        if ("end" in lower or "stop" in lower) and matches and pending_begin:
            end_time = matches[0]
            tag_label = pending_label or line
            key = (pending_begin, end_time, tag_label)
            if key not in seen:
                seen.add(key)
                windows.append(key)
            pending_begin = None
            pending_label = ""

    if windows:
        return tuple(windows)

    # Fallback for rtirecordingservice_list_tags tabular output:
    # tag_name timestamp_ms tag_description
    # <name>   <epoch_ms>   <desc>
    stamp_rows = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("tag_name") or set(line) <= {"-", " ", "\t"}:
            continue
        match = re.match(r"^(\S+)\s+(\d{10,})\b", line)
        if not match:
            continue
        tag_name = match.group(1)
        stamp_ms = int(match.group(2))
        stamp_rows.append((tag_name, stamp_ms))

    if len(stamp_rows) < 2:
        return tuple(windows)

    fallback_windows = []
    for idx in range(len(stamp_rows) - 1):
        label, start_ms = stamp_rows[idx]
        _next_label, end_ms = stamp_rows[idx + 1]
        if end_ms <= start_ms:
            continue
        start_iso = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        end_iso = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        fallback_windows.append((start_iso, end_iso, label))

    return tuple(fallback_windows)


def _extract_tag_names(text: str) -> Tuple[str, ...]:
    names = []
    seen = set()

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("tag_name") or set(line) <= {"-", " ", "\t"}:
            continue
        if "no tag" in lower:
            continue

        candidate = ""
        table_match = re.match(r"^(\S+)\s+(\d{10,})\b", line)
        if table_match:
            candidate = table_match.group(1)
        elif lower.startswith("tag:"):
            candidate = line.split(":", 1)[1].strip()
        elif _TAG_TIME_TOKEN_RE.search(line) and ":" in line:
            candidate = line.split(":", 1)[0].strip()
        elif " " not in line and "\t" not in line:
            candidate = line

        if candidate and candidate not in seen:
            seen.add(candidate)
            names.append(candidate)

    return tuple(names)


def _fixed_replay_monitoring_text(view: ReplayTabViewModel) -> str:
    selected = view.selected_target
    values = {
        "state": str(view.observed_state or "-"),
        "progress": str(selected.progress if selected is not None else "-"),
        "playback_rate": f"{view.playback_rate:g}",
        "loop": "true" if view.loop else "false",
        "database": str(view.database_path or "-"),
        "time_window": str(view.time_window or "-"),
        "pid": str(selected.pid if selected is not None and selected.pid else "-"),
        "hostname": str(selected.hostname if selected is not None else "-"),
    }
    half = (_REPLAY_MONITORING_FIELDS.__len__() + 1) // 2
    left_fields = _REPLAY_MONITORING_FIELDS[:half]
    right_fields = _REPLAY_MONITORING_FIELDS[half:]

    def _fmt(field: str) -> str:
        return f"{field:<13}: {values.get(field, '-')}"

    lines = []
    for index in range(half):
        left = _fmt(left_fields[index]) if index < len(left_fields) else ""
        right = _fmt(right_fields[index]) if index < len(right_fields) else ""
        if right:
            lines.append(f"{left:<{_REPLAY_MONITORING_COLUMN_WIDTH}}{right}")
        else:
            lines.append(left)
    timeline_labels = [row.label for row in view.timeline[:2] if str(row.label).strip()]
    if timeline_labels:
        lines.append("events       : " + " | ".join(timeline_labels))
    return "\n".join(lines)