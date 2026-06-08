"""Tkinter Replay tab widgets and adapter wiring for rs_gui_v2."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, Optional

from gui.tabs.replay_tab import ReplayLaunchViewModel, ReplayTabViewModel, build_replay_action_command, build_replay_launch_command
from ..theme import DARK_THEME


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


class TkReplayTab:
    """Tkinter Replay tab renderer backed by immutable shell snapshots."""

    def __init__(self, parent, ttk, tk, adapter: Optional[ReplayTabAdapter] = None) -> None:
        self._ttk = ttk
        self._tk = tk
        self._adapter = adapter
        self._view: Optional[ReplayTabViewModel] = None
        self._target_display_to_id: Dict[str, str] = {}
        self._launch_initialized = False

        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        self.frame = frame

        selector = ttk.LabelFrame(frame, text="Targets And Actions", padding=12)
        selector.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        selector.columnconfigure(1, weight=1)

        self.target_select_var = tk.StringVar(value="")
        ttk.Label(selector, text="Target").grid(row=0, column=0, sticky="w")
        self.target_combo = ttk.Combobox(selector, textvariable=self.target_select_var, state="readonly")
        self.target_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.target_combo.bind("<<ComboboxSelected>>", self._on_target_selected)

        actions = ttk.Frame(selector)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.action_buttons = {}
        for index, action_id in enumerate(("start", "pause", "resume", "stop", "shutdown")):
            button = ttk.Button(actions, text=action_id.title(), command=lambda value=action_id: self._on_action_clicked(value))
            button.grid(row=0, column=index, sticky="w", padx=(0, 8))
            self.action_buttons[action_id] = button

        launch = ttk.LabelFrame(frame, text="Launch Replay Service", padding=12)
        launch.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        launch.columnconfigure(1, weight=1)
        launch.columnconfigure(3, weight=1)

        self.config_name_var = tk.StringVar(value="")
        self.database_path_var = tk.StringVar(value="")
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
        self.config_paths_var = tk.StringVar(value="")

        ttk.Label(launch, text="Config name").grid(row=0, column=0, sticky="w")
        ttk.Entry(launch, textvariable=self.config_name_var).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(launch, text="Database path").grid(row=0, column=2, sticky="w")
        ttk.Entry(launch, textvariable=self.database_path_var).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        ttk.Label(launch, text="Playback rate").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.playback_rate_var).grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="Time window").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.time_window_var).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(launch, text="Loop", variable=self.loop_var).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.launch_button = ttk.Button(launch, text="Launch Replay Service", command=self._on_launch_clicked)
        self.launch_button.grid(row=2, column=3, sticky="e", pady=(12, 0))

        ttk.Label(launch, text="Data domain").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.data_domain_var, width=2).grid(row=3, column=1, sticky="w", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="Admin domain").grid(row=3, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.admin_domain_var, width=2).grid(row=3, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(launch, text="Monitoring domain").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.monitoring_domain_var, width=2).grid(row=4, column=1, sticky="w", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="Topic allow").grid(row=4, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.topic_allow_var).grid(row=4, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(launch, text="Topic deny").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.topic_deny_var).grid(row=5, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="QoS file").grid(row=5, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.qos_file_var).grid(row=5, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(launch, text="Participant QoS").grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.participant_qos_var).grid(row=6, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(launch, text="Writer QoS").grid(row=6, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(launch, textvariable=self.writer_qos_var).grid(row=6, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(launch, text="Config files").grid(row=7, column=0, sticky="nw", pady=(8, 0))
        ttk.Label(launch, textvariable=self.config_paths_var, justify="left", wraplength=780).grid(row=7, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(launch, text="Launch preview").grid(row=8, column=0, sticky="nw", pady=(8, 0))
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

        for variable in (
                self.config_name_var,
                self.database_path_var,
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
        ):
            variable.trace_add("write", self._on_launch_form_changed)

        summary = ttk.LabelFrame(frame, text="Replay Status", padding=12)
        summary.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        summary.columnconfigure(0, weight=1)

        self.target_var = tk.StringVar(value="Target: none")
        self.state_var = tk.StringVar(value="State: no service")
        self.database_var = tk.StringVar(value="Database: -")
        self.error_var = tk.StringVar(value="")

        ttk.Label(summary, textvariable=self.target_var).grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.state_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(summary, textvariable=self.database_var).grid(row=2, column=0, sticky="w", pady=(4, 0))

        timeline = ttk.Frame(summary)
        timeline.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        timeline.columnconfigure(0, weight=1)
        ttk.Label(timeline, text="Timeline").grid(row=0, column=0, sticky="w")
        self.timeline_text = tk.Text(
            timeline,
            height=3,
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
        self.timeline_text.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(summary, textvariable=self.error_var, wraplength=860, justify="left").grid(row=4, column=0, sticky="w", pady=(6, 0))

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
        self.state_var.set(f"State: {view.observed_state} | Playback rate: {view.playback_rate:g}")
        self.database_var.set(f"Database: {view.database_path or '-'}")
        timeline = " | ".join(row.label for row in view.timeline[:3]) or "-"
        self._set_timeline_text(timeline)
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
        self._set_launch_preview_text(launch.command_preview)
        self._launch_initialized = True

    def _render_actions(self, view: ReplayTabViewModel) -> None:
        action_map = view.action_by_id
        for action_id, button in self.action_buttons.items():
            action = action_map.get(action_id)
            if action is None or not action.enabled:
                button.state(["disabled"])
            else:
                button.state(["!disabled"])

    def _render_diagnostics(self, view: ReplayTabViewModel) -> None:
        self.diagnostics_list.delete(0, self._tk.END)
        items = list(view.diagnostics) or [f"Observed state: {view.observed_state}"]
        for item in items[:6]:
            self.diagnostics_list.insert(self._tk.END, item)

    def _set_timeline_text(self, value: str) -> None:
        self.timeline_text.configure(state="normal")
        self.timeline_text.delete("1.0", self._tk.END)
        self.timeline_text.insert("1.0", value)
        self.timeline_text.configure(state="disabled")

    def _set_launch_preview_text(self, value: str) -> None:
        self.launch_preview_text.configure(state="normal")
        self.launch_preview_text.delete("1.0", self._tk.END)
        self.launch_preview_text.insert("1.0", value)
        self.launch_preview_text.configure(state="disabled")

    def _on_launch_form_changed(self, *_args) -> None:
        if not self._launch_initialized:
            return
        self._set_launch_preview_text(self._build_launch_preview_from_form())

    def _build_launch_preview_from_form(self) -> str:
        data_domain = self.data_domain_var.get().strip() or "0"
        admin_domain = self.admin_domain_var.get().strip() or "0"
        monitoring_domain = self.monitoring_domain_var.get().strip() or "0"
        database_path = self.database_path_var.get().strip() or "<database_path>"
        topic_allow = self.topic_allow_var.get().strip() or "*"
        topic_deny = self.topic_deny_var.get().strip()
        executable = self._view.launch.executable if self._view is not None else ""
        executable = executable or "rtireplayservice"
        config_name = self.config_name_var.get().strip() or "<config>"
        playback_rate = self.playback_rate_var.get().strip() or "1.0"
        loop_text = "true" if self.loop_var.get() else "false"
        verbosity = self._view.launch.verbosity if self._view is not None else "ERROR:ERROR"
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
        return env_text + "\n" + " ".join(cmd_parts)

    def _on_target_selected(self, _event=None) -> None:
        target_id = self._target_display_to_id.get(self.target_select_var.get(), "")
        if target_id and self._adapter is not None:
            self._adapter.select_target(target_id)

    def _on_launch_clicked(self) -> None:
        if self._adapter is None or self._view is None:
            return
        try:
            launch = replace(
                self._view.launch,
                config_name=self.config_name_var.get().strip(),
                database_path=self.database_path_var.get().strip(),
                playback_rate=float(self.playback_rate_var.get().strip() or self._view.launch.playback_rate),
                loop=bool(self.loop_var.get()),
                time_window=self.time_window_var.get().strip(),
                data_domain_id=int(self.data_domain_var.get().strip() or self._view.launch.data_domain_id),
                admin_domain_id=int(self.admin_domain_var.get().strip() or self._view.launch.admin_domain_id),
                monitoring_domain_id=int(self.monitoring_domain_var.get().strip() or self._view.launch.monitoring_domain_id),
                topic_allow=self.topic_allow_var.get().strip() or self._view.launch.topic_allow,
                topic_deny=self.topic_deny_var.get().strip(),
                qos_file_path=self.qos_file_var.get().strip(),
                participant_qos_profile=self.participant_qos_var.get().strip(),
                writer_qos_profile=self.writer_qos_var.get().strip(),
            )
            accepted = self._adapter.queue_launch(launch)
            self.error_var.set("Launch queued" if accepted else "Launch command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))

    def _on_action_clicked(self, action_id: str) -> None:
        if self._adapter is None or self._view is None:
            return
        try:
            accepted = self._adapter.queue_action(action_id, self._view)
            self.error_var.set(f"{action_id} queued" if accepted else f"{action_id} command dropped")
        except Exception as exc:
            self.error_var.set(str(exc))