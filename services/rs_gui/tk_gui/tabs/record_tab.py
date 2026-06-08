"""Tkinter Record tab widgets and adapter wiring for rs_gui."""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Callable, Dict, Optional

from gui.tabs.record_tab import RecordLaunchViewModel, RecordTabViewModel, build_record_action_command, build_record_launch_command
from ..theme import DARK_THEME


_VERBOSITY_LEVELS = ("SILENT", "ERROR", "WARN", "LOCAL", "REMOTE", "ALL")
_MONITORING_FIELDS = (
    "db_file_size",
    "rollover_count",
    "memory_mb",
    "sessions",
    "topics",
    "last_event",
)
_MONITORING_COLUMN_WIDTH = 34
_MONITORING_ROWS = (_MONITORING_FIELDS.__len__() + 1) // 2


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


class RecordTabAdapter:
    """Thin adapter that keeps Tk widgets on the existing Record/session boundary."""

    def __init__(
            self,
            command_sink: Callable[[object], bool],
            select_candidate: Callable[[str], None],
            set_tag_value: Callable[[str], None],
            resolve_candidate: Callable[[str], object],
    ) -> None:
        self._command_sink = command_sink
        self._select_candidate = select_candidate
        self._set_tag_value = set_tag_value
        self._resolve_candidate = resolve_candidate

    def select_candidate(self, candidate_id: str) -> None:
        self._select_candidate(candidate_id)

    def set_tag_value(self, value: str) -> None:
        self._set_tag_value(value)

    def queue_launch(self, launch: RecordLaunchViewModel) -> bool:
        return bool(self._command_sink(build_record_launch_command(launch)))

    def queue_action(self, action_id: str, candidate_id: str, tag_value: str = "") -> bool:
        candidate = self._resolve_candidate(candidate_id)
        if candidate is None:
            raise ValueError("selected candidate is no longer available")
        command = build_record_action_command(action_id, candidate, tag_name=tag_value)
        return bool(self._command_sink(command))


class TkRecordTab:
    """Tkinter Record tab renderer backed by immutable shell snapshots."""

    def __init__(self, parent, ttk, tk, adapter: Optional[RecordTabAdapter] = None) -> None:
        self._ttk = ttk
        self._tk = tk
        self._adapter = adapter
        self._view: Optional[RecordTabViewModel] = None
        self._candidate_display_to_id: Dict[str, str] = {}
        self._launch_initialized = False
        self._launch_preview_expanded = False
        self._syncing_tag_from_view = False
        self._tag_dirty = False
        self._mousewheel_bound = False
        self._mousewheel_bind_ids: Dict[str, str] = {}

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

        selector = ttk.LabelFrame(frame, text="Candidates And Actions", padding=12)
        selector.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        selector.columnconfigure(1, weight=1)
        selector.columnconfigure(2, weight=0)

        self.candidate_var = tk.StringVar(value="")
        ttk.Label(selector, text="Candidate").grid(row=0, column=0, sticky="w")
        self.candidate_combo = ttk.Combobox(selector, textvariable=self.candidate_var, state="readonly")
        self.candidate_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.candidate_combo.bind("<<ComboboxSelected>>", self._on_candidate_selected)

        self.tag_var = tk.StringVar(value="")
        ttk.Label(selector, text="Tag").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.tag_entry = ttk.Entry(selector, textvariable=self.tag_var)
        self.tag_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.tag_entry.bind("<FocusOut>", self._on_tag_focus_out)
        self.tag_var.trace_add("write", self._on_tag_changed)
        self.action_buttons = {}
        self.action_buttons["tag"] = ttk.Button(
            selector,
            text="Send Tag",
            command=lambda value="tag": self._on_action_clicked(value),
        )
        self.action_buttons["tag"].grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(8, 0))

        actions = ttk.Frame(selector)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        for index, action_id in enumerate(("pause", "resume", "shutdown", "terminate_local")):
            button = ttk.Button(actions, text=action_id.replace("_", " ").title(), command=lambda value=action_id: self._on_action_clicked(value))
            button.grid(row=0, column=index, sticky="w", padx=(0, 8))
            self.action_buttons[action_id] = button

        launch = ttk.LabelFrame(frame, text="Launch Recording Service", padding=12)
        launch.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        launch.columnconfigure(1, weight=1)
        launch.columnconfigure(3, weight=1)

        self.config_name_var = tk.StringVar(value="")
        self.storage_format_var = tk.StringVar(value="XCDR")
        self.service_verbosity_var = tk.StringVar(value="ERROR")
        self.api_verbosity_var = tk.StringVar(value="ERROR")
        self.working_dir_var = tk.StringVar(value="")
        self.extra_args_var = tk.StringVar(value="")
        self.data_domain_var = tk.StringVar(value="0")
        self.admin_domain_var = tk.StringVar(value="0")
        self.monitoring_domain_var = tk.StringVar(value="0")
        self.topic_allow_var = tk.StringVar(value="*")
        self.topic_deny_var = tk.StringVar(value="rti/*")
        self.log_directory_var = tk.StringVar(value="log_dir")
        self.config_paths_var = tk.StringVar(value="")

        ttk.Label(launch, text="Config name").grid(row=0, column=0, sticky="w")
        self.config_name_combo = ttk.Combobox(launch, textvariable=self.config_name_var, state="readonly")
        self.config_name_combo.grid(row=0, column=1, sticky="ew", padx=(8, 16))

        verbosity_row = ttk.Frame(launch)
        verbosity_row.grid(row=0, column=2, columnspan=2, sticky="ew")
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

        ttk.Label(launch, text="Working dir").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.working_dir_var).grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="Extra args").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.extra_args_var).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(launch, text="Log directory").grid(row=2, column=0, sticky="w", pady=(8, 0))
        log_dir_frame = ttk.Frame(launch)
        log_dir_frame.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        log_dir_frame.columnconfigure(0, weight=1)
        ttk.Entry(log_dir_frame, textvariable=self.log_directory_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(log_dir_frame, text="Browse...", command=self._on_browse_log_directory).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 0),
        )

        domain_row = ttk.Frame(launch)
        domain_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(domain_row, text="Data domain").grid(row=0, column=0, sticky="w")
        ttk.Entry(domain_row, textvariable=self.data_domain_var, width=2).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(domain_row, text="Admin domain").grid(row=0, column=2, sticky="w")
        ttk.Entry(domain_row, textvariable=self.admin_domain_var, width=2).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Label(domain_row, text="Monitoring domain").grid(row=0, column=4, sticky="w")
        ttk.Entry(domain_row, textvariable=self.monitoring_domain_var, width=2).grid(row=0, column=5, sticky="w", padx=(8, 0))

        ttk.Label(launch, text="Topic allow").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.topic_allow_var).grid(row=4, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="Topic deny").grid(row=4, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.topic_deny_var).grid(row=4, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(launch, text="Storage format").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(launch, textvariable=self.storage_format_var, state="readonly", values=("XCDR", "JSON")).grid(
            row=5,
            column=1,
            sticky="w",
            padx=(8, 0),
            pady=(8, 0),
        )
        ttk.Label(launch, text="Config files").grid(row=6, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(launch, textvariable=self.config_paths_var, justify="left", wraplength=780).grid(row=6, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.launch_preview_toggle = ttk.Button(
            launch,
            text="> Launch preview",
            command=self._on_toggle_launch_preview,
        )
        self.launch_preview_toggle.grid(row=7, column=0, sticky="w", pady=(8, 0))
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
        self.launch_preview_text.grid(row=7, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.launch_preview_text.grid_remove()
        self.launch_button = ttk.Button(launch, text="Launch Recording Service", command=self._on_launch_clicked)
        self.launch_button.grid(row=8, column=3, sticky="e", pady=(12, 0))

        for variable in (
                self.config_name_var,
                self.service_verbosity_var,
                self.api_verbosity_var,
                self.working_dir_var,
                self.extra_args_var,
                self.data_domain_var,
                self.admin_domain_var,
                self.monitoring_domain_var,
                self.storage_format_var,
                self.log_directory_var,
                self.topic_allow_var,
                self.topic_deny_var,
        ):
            variable.trace_add("write", self._on_launch_form_changed)

        summary = ttk.LabelFrame(frame, text="Record Status", padding=12)
        summary.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        summary.columnconfigure(0, weight=1)

        self.target_var = tk.StringVar(value="Target: none")
        self.readiness_var = tk.StringVar(value="Readiness: not checked")
        self.current_file_var = tk.StringVar(value="Current file: -")
        self.error_var = tk.StringVar(value="")

        ttk.Label(summary, textvariable=self.target_var).grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.readiness_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(summary, textvariable=self.current_file_var).grid(row=2, column=0, sticky="w", pady=(4, 0))

        monitoring = ttk.Frame(summary)
        monitoring.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        monitoring.columnconfigure(0, weight=1)
        ttk.Label(monitoring, text="Monitoring").grid(row=0, column=0, sticky="w")
        self.monitoring_text = tk.Text(
            monitoring,
            height=_MONITORING_ROWS + 1,
            wrap="none",
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

        ttk.Label(summary, textvariable=self.error_var, wraplength=860, justify="left").grid(row=4, column=0, sticky="w", pady=(6, 0))

        history = ttk.LabelFrame(frame, text="Command History", padding=12)
        history.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))
        history.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        self.command_history = tk.Listbox(history, height=6)
        self.command_history.configure(
            background=DARK_THEME["panel_alt"],
            foreground=DARK_THEME["text"],
            selectbackground=DARK_THEME["selection"],
            selectforeground=DARK_THEME["text"],
            highlightbackground=DARK_THEME["border"],
            highlightcolor=DARK_THEME["accent"],
            borderwidth=1,
            relief="solid",
        )
        self.command_history.grid(row=0, column=0, sticky="nsew")

    def render(self, view: RecordTabViewModel) -> None:
        self._view = view
        selected = view.selected_candidate
        self.target_var.set(f"Target: {view.target_label}")
        self.readiness_var.set(f"Readiness: {view.readiness} | Observed: {view.observed_state}")
        self.current_file_var.set(f"Current file: {selected.current_file if selected and selected.current_file else '-'}")
        monitoring_text = _fixed_monitoring_text(view.monitoring_summary)
        self._set_monitoring_text(monitoring_text)
        diagnostics = " | ".join(view.diagnostics[:3])
        self.error_var.set(diagnostics)

        self._render_candidates(view)
        self._render_tag(view)
        self._render_launch_form(view.launch)
        self._render_actions(view)
        self._render_history(view)

    def _render_candidates(self, view: RecordTabViewModel) -> None:
        options = []
        self._candidate_display_to_id = {}
        selected_display = ""
        for row in view.candidates:
            display = f"{row.label} | {row.state} | {row.hostname} | pid={row.pid or '-'}"
            options.append(display)
            self._candidate_display_to_id[display] = row.candidate_id
            if row.candidate_id == view.selected_candidate_id:
                selected_display = display
        self.candidate_combo["values"] = tuple(options)
        self.candidate_var.set(selected_display or (options[0] if options else ""))

    def _render_tag(self, view: RecordTabViewModel) -> None:
        current = self.tag_var.get()
        if self._tag_dirty:
            if current == view.tag_value:
                self._tag_dirty = False
            else:
                return
        if current != view.tag_value:
            self._syncing_tag_from_view = True
            try:
                self.tag_var.set(view.tag_value)
            finally:
                self._syncing_tag_from_view = False

    def _render_launch_form(self, launch: RecordLaunchViewModel) -> None:
        if self._launch_initialized:
            return
        config_names = tuple(launch.available_config_names) or ((launch.config_name or "template"),)
        self.config_name_combo["values"] = config_names
        self.config_name_var.set(launch.config_name)
        self.storage_format_var.set(launch.storage_format)
        service_level, api_level = _split_verbosity(launch.verbosity)
        self.service_verbosity_var.set(service_level)
        self.api_verbosity_var.set(api_level)
        self.working_dir_var.set(launch.working_dir)
        self.extra_args_var.set(" ".join(launch.extra_args))
        self.data_domain_var.set(str(launch.data_domain_id))
        self.admin_domain_var.set(str(launch.admin_domain_id))
        self.monitoring_domain_var.set(str(launch.monitoring_domain_id))
        self.log_directory_var.set(launch.log_directory)
        self.topic_allow_var.set(launch.topic_allow)
        self.topic_deny_var.set(launch.topic_deny)
        self.config_paths_var.set("; ".join(launch.config_paths) or "-")
        self._set_launch_preview_text(launch.command_preview)
        self._launch_initialized = True

    def _render_actions(self, view: RecordTabViewModel) -> None:
        action_map = view.action_by_id
        for action_id, button in self.action_buttons.items():
            action = action_map.get(action_id)
            if action is None or not action.enabled:
                button.state(["disabled"])
            else:
                button.state(["!disabled"])

    def _render_history(self, view: RecordTabViewModel) -> None:
        self.command_history.delete(0, self._tk.END)
        for row in view.command_history:
            message = row.message or row.reply or row.observed
            self.command_history.insert(self._tk.END, f"{row.command}: {message}")

    def _set_monitoring_text(self, value: str) -> None:
        self.monitoring_text.configure(state="normal")
        self.monitoring_text.delete("1.0", self._tk.END)
        self.monitoring_text.insert("1.0", value)
        self.monitoring_text.configure(state="disabled")

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
        self._set_launch_preview_text(self._build_launch_preview_from_form())

    def _build_launch_preview_from_form(self) -> str:
        data_domain = self.data_domain_var.get().strip() or "0"
        admin_domain = self.admin_domain_var.get().strip() or "0"
        monitoring_domain = self.monitoring_domain_var.get().strip() or "0"
        storage_ui = self.storage_format_var.get().strip().upper() or "XCDR"
        storage_env = "JSON_SQLITE" if storage_ui == "JSON" else "XCDR_AUTO"
        log_directory = self.log_directory_var.get().strip() or "log_dir"
        topic_allow = self.topic_allow_var.get().strip() or "*"
        topic_deny = self.topic_deny_var.get().strip()
        executable = self._view.launch.executable if self._view is not None else ""
        executable = executable or "rtirecordingservice"
        config_name = self.config_name_var.get().strip() or "<config>"
        verbosity = _join_verbosity(self.service_verbosity_var.get(), self.api_verbosity_var.get())
        config_paths = self.config_paths_var.get().strip()
        extra_args = " ".join(arg for arg in self.extra_args_var.get().split() if arg.strip())
        env_text = " ".join((
            f"REC_DOMAIN_ID={data_domain}",
            f"REC_ADMIN_DOMAIN_ID={admin_domain}",
            f"REC_MON_DOMAIN_ID={monitoring_domain}",
            f"REC_LOG_DIR={log_directory}",
            f"REC_STORAGE_FORMAT={storage_env}",
            f"REC_TOPIC_ALLOW={topic_allow}",
            f"REC_TOPIC_DENY={topic_deny}",
            f"DOMAIN_ID={data_domain}",
            f"ADMIN_DOMAIN_ID={admin_domain}",
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
            f"-DDOMAIN_ID={data_domain}",
            f"-DADMIN_DOMAIN_ID={admin_domain}",
            f"-DREC_LOG_DIR={log_directory}",
            f"-DREC_STORAGE_FORMAT={storage_env}",
            f"-DREC_TOPIC_ALLOW={topic_allow}",
            f"-DREC_TOPIC_DENY={topic_deny}",
        ])
        if extra_args:
            cmd_parts.append(extra_args)
        return env_text + "\n" + " ".join(cmd_parts)

    def _on_candidate_selected(self, _event=None) -> None:
        candidate_id = self._candidate_display_to_id.get(self.candidate_var.get(), "")
        if candidate_id and self._adapter is not None:
            self._adapter.select_candidate(candidate_id)

    def _on_tag_focus_out(self, _event=None) -> None:
        if self._adapter is not None:
            self._adapter.set_tag_value(self.tag_var.get())

    def _on_tag_changed(self, *_args) -> None:
        if self._syncing_tag_from_view:
            return
        self._tag_dirty = True
        if self._adapter is None:
            return
        self._adapter.set_tag_value(self.tag_var.get())

    def _on_launch_clicked(self) -> None:
        if self._adapter is None or self._view is None:
            return
        try:
            launch = replace(
                self._view.launch,
                config_name=self.config_name_var.get().strip(),
                verbosity=_join_verbosity(self.service_verbosity_var.get(), self.api_verbosity_var.get()),
                working_dir=self.working_dir_var.get().strip(),
                extra_args=tuple(arg for arg in self.extra_args_var.get().split() if arg.strip()),
                data_domain_id=int(self.data_domain_var.get().strip() or self._view.launch.data_domain_id),
                admin_domain_id=int(self.admin_domain_var.get().strip() or self._view.launch.admin_domain_id),
                monitoring_domain_id=int(self.monitoring_domain_var.get().strip() or self._view.launch.monitoring_domain_id),
                storage_format=self.storage_format_var.get().strip() or self._view.launch.storage_format,
                log_directory=self.log_directory_var.get().strip() or self._view.launch.log_directory,
                topic_allow=self.topic_allow_var.get().strip() or self._view.launch.topic_allow,
                topic_deny=self.topic_deny_var.get().strip(),
            )
            accepted = self._adapter.queue_launch(launch)
            self.error_var.set("Launch queued" if accepted else "Launch command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))

    def _on_browse_log_directory(self) -> None:
        try:
            from tkinter import filedialog
        except Exception:
            self.error_var.set("File dialog is unavailable in this environment")
            return
        start_dir = self.log_directory_var.get().strip()
        if start_dir and os.path.isfile(start_dir):
            start_dir = os.path.dirname(start_dir)
        selected = filedialog.askdirectory(
            parent=self.frame,
            title="Select recording log directory",
            initialdir=start_dir or None,
        )
        if not selected:
            return
        self.log_directory_var.set(selected)

    def _on_action_clicked(self, action_id: str) -> None:
        if self._adapter is None or self._view is None:
            return
        candidate_id = self._candidate_display_to_id.get(self.candidate_var.get(), self._view.selected_candidate_id)
        try:
            self._adapter.set_tag_value(self.tag_var.get())
            accepted = self._adapter.queue_action(action_id, candidate_id, tag_value=self.tag_var.get())
            if accepted and action_id == "tag":
                self.tag_var.set("")
            self.error_var.set(f"{action_id} queued" if accepted else f"{action_id} command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))


def _fixed_monitoring_text(summary) -> str:
    values = {str(key): str(value) for key, value in summary}
    half = (_MONITORING_FIELDS.__len__() + 1) // 2
    left_fields = _MONITORING_FIELDS[:half]
    right_fields = _MONITORING_FIELDS[half:]

    def _fmt(field: str) -> str:
        return f"{field:<14}: {values.get(field, '-') }"

    lines = []
    for index in range(half):
        left = _fmt(left_fields[index]) if index < len(left_fields) else ""
        right = _fmt(right_fields[index]) if index < len(right_fields) else ""
        if right:
            lines.append(f"{left:<{_MONITORING_COLUMN_WIDTH}}{right}")
        else:
            lines.append(left)
    extras = [f"{key}={value}" for key, value in summary if str(key) not in _MONITORING_FIELDS]
    if extras:
        lines.append("extra         : " + ", ".join(extras[:4]))
    return "\n".join(lines)