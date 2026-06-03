"""Replay tab view models and command factories for rs_gui_v2."""

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from app_core import AppCommand


@dataclass(frozen=True)
class ReplayTargetRow:
    """UI-facing Replay Service candidate row."""

    target_id: str
    label: str
    control_name: str
    source: str
    hostname: str
    state: str
    progress: str
    candidate_id: str = ""
    pid: str = ""
    owned: bool = False
    age: str = ""
    confidence: str = ""
    output_path: str = ""
    output_tail: str = ""
    selected: bool = False
    conflict: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", str(self.candidate_id or self.target_id))
        object.__setattr__(self, "pid", str(self.pid))
        object.__setattr__(self, "owned", bool(self.owned))
        object.__setattr__(self, "selected", bool(self.selected))
        object.__setattr__(self, "conflict", bool(self.conflict))


@dataclass(frozen=True)
class ReplayLaunchViewModel:
    """Operator-facing launch settings for Replay Service."""

    label: str = "Replay Service"
    config_paths: Tuple[str, ...] = ("services/replay_service_config.xml",)
    available_config_names: Tuple[str, ...] = ("xcdr", "json")
    config_name: str = "xcdr"
    data_domain_id: int = 0
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0
    database_path: str = "log_dir/xcdr"
    storage_format: str = "XCDR"
    playback_rate: float = 1.0
    loop: bool = False
    time_window: str = ""
    topic_allow: str = "*"
    topic_deny: str = ""
    qos_file_path: str = ""
    participant_qos_profile: str = ""
    writer_qos_profile: str = ""
    verbosity: str = "ERROR:ERROR"
    executable: str = ""
    working_dir: str = ""
    extra_args: Tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    disabled_reason: str = ""
    command_preview: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_paths", tuple(str(path) for path in self.config_paths if str(path).strip()))
        object.__setattr__(self, "available_config_names", tuple(str(name) for name in self.available_config_names if str(name).strip()))
        object.__setattr__(self, "data_domain_id", int(self.data_domain_id))
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "playback_rate", float(self.playback_rate))
        object.__setattr__(self, "loop", bool(self.loop))
        object.__setattr__(self, "extra_args", tuple(str(arg) for arg in self.extra_args if str(arg).strip()))
        object.__setattr__(self, "enabled", bool(self.enabled))


@dataclass(frozen=True)
class ReplayActionView:
    """Enabled/disabled state for one Replay tab action."""

    action_id: str
    label: str
    enabled: bool
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", bool(self.enabled))


@dataclass(frozen=True)
class ReplayTimelineRow:
    """One persisted replay range or segment summary."""

    label: str
    start_time: str
    end_time: str
    state: str = "available"


@dataclass(frozen=True)
class ReplayTabViewModel:
    """Immutable Replay-tab snapshot consumed by the GUI renderer."""

    selected_target_id: str = ""
    database_path: str = ""
    observed_state: str = "no service"
    playback_rate: float = 1.0
    loop: bool = False
    time_window: str = ""
    qos_file_path: str = ""
    participant_qos_profile: str = ""
    writer_qos_profile: str = ""
    launch: ReplayLaunchViewModel = field(default_factory=ReplayLaunchViewModel)
    targets: Tuple[ReplayTargetRow, ...] = field(default_factory=tuple)
    timeline: Tuple[ReplayTimelineRow, ...] = field(default_factory=tuple)
    actions: Tuple[ReplayActionView, ...] = field(default_factory=tuple)
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "playback_rate", float(self.playback_rate))
        object.__setattr__(self, "loop", bool(self.loop))
        if not isinstance(self.launch, ReplayLaunchViewModel):
            object.__setattr__(self, "launch", ReplayLaunchViewModel(**self.launch))
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "timeline", tuple(self.timeline))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "diagnostics", tuple(str(item) for item in self.diagnostics))

    @property
    def selected_target(self) -> Optional[ReplayTargetRow]:
        for row in self.targets:
            if row.target_id == self.selected_target_id:
                return row
        return None

    @property
    def action_by_id(self) -> Mapping[str, ReplayActionView]:
        return {action.action_id: action for action in self.actions}

    @property
    def target_count(self) -> int:
        return len(self.targets)


def build_replay_tab_view_model(
        targets: Iterable[ReplayTargetRow] = (),
        selected_target_id: str = "",
        database_path: str = "",
        observed_state: str = "no service",
        playback_rate: float = 1.0,
        loop: bool = False,
        time_window: str = "",
    qos_file_path: str = "",
    participant_qos_profile: str = "",
    writer_qos_profile: str = "",
        launch: ReplayLaunchViewModel = None,
        timeline: Iterable[ReplayTimelineRow] = (),
        diagnostics: Iterable[str] = (),
) -> ReplayTabViewModel:
    """Build a Replay-tab snapshot from UI-facing target and timeline rows."""

    targets = tuple(targets)
    selected_target_id = _selected_target_id(targets, selected_target_id)
    targets = tuple(
        replace(target, selected=target.target_id == selected_target_id)
        for target in targets
    )
    selected_target = next(
        (target for target in targets if target.target_id == selected_target_id),
        None,
    )
    if selected_target is not None:
        observed_state = selected_target.state
    diagnostics = tuple(str(item) for item in diagnostics) + _diagnostics(targets, database_path)
    return ReplayTabViewModel(
        selected_target_id=selected_target_id,
        database_path=str(database_path),
        observed_state=str(observed_state),
        playback_rate=playback_rate,
        loop=loop,
        time_window=str(time_window),
        qos_file_path=str(qos_file_path),
        participant_qos_profile=str(participant_qos_profile),
        writer_qos_profile=str(writer_qos_profile),
        launch=launch or ReplayLaunchViewModel(
            database_path=str(database_path),
            playback_rate=playback_rate,
            loop=loop,
            time_window=str(time_window),
            qos_file_path=str(qos_file_path),
            participant_qos_profile=str(participant_qos_profile),
            writer_qos_profile=str(writer_qos_profile),
        ),
        targets=targets,
        timeline=tuple(timeline),
        actions=_replay_actions(selected_target, database_path, observed_state),
        diagnostics=diagnostics,
    )


def build_mock_replay_tab_view_model() -> ReplayTabViewModel:
    """Return a deterministic Replay-tab snapshot for GUI smoke rendering."""

    targets = (
        ReplayTargetRow(
            target_id="launch-replay-main",
            label="Replay Service",
            control_name="replay_service_2d91c4a0",
            source="local",
            hostname="dev-host",
            state="STOPPED",
            progress="0%",
            selected=True,
        ),
        ReplayTargetRow(
            target_id="discovery:replay:archive",
            label="Archive Replay",
            control_name="replay_archive_external",
            source="discovery",
            hostname="lab-host",
            state="PAUSED",
            progress="38%",
        ),
    )
    return build_replay_tab_view_model(
        targets=targets,
        selected_target_id="launch-replay-main",
        database_path="services/replay_input/robot_run_03",
        observed_state="STOPPED",
        playback_rate=1.0,
        loop=False,
        time_window="00:00:10 - 00:02:30",
        qos_file_path="dds/qos/DDS_QOS_PROFILES.xml",
        participant_qos_profile="DPLibrary::DefaultParticipant",
        writer_qos_profile="BuiltinQosLib::Generic.Common",
        launch=ReplayLaunchViewModel(
            label="Replay Service",
            config_paths=("services/replay_service_config.xml",),
            available_config_names=("xcdr", "json"),
            config_name="xcdr",
            database_path="services/replay_input/robot_run_03",
            playback_rate=1.0,
            loop=False,
            time_window="00:00:10 - 00:02:30",
            qos_file_path="dds/qos/DDS_QOS_PROFILES.xml",
            participant_qos_profile="DPLibrary::DefaultParticipant",
            writer_qos_profile="BuiltinQosLib::Generic.Common",
        ),
        timeline=(
            ReplayTimelineRow("Robot run", "00:00:10", "00:02:30"),
            ReplayTimelineRow("Tag: e2e_tag_beta", "00:01:05", "00:01:25"),
        ),
    )


def build_replay_action_command(
        action_id: str,
        replay: ReplayTabViewModel,
) -> AppCommand:
    """Translate a Replay-tab button action into an app-core command intent."""

    action_to_command = {
        "start": "replay.start",
        "pause": "replay.pause",
        "resume": "replay.resume",
        "stop": "replay.stop",
        "shutdown": "replay.shutdown",
    }
    if action_id not in action_to_command:
        raise ValueError(f"Unsupported Replay tab action: {action_id}")
    target = replay.selected_target
    payload: Dict[str, Any] = {
        "target_id": target.target_id if target is not None else "",
        "control_name": target.control_name if target is not None else "",
        "database_path": replay.database_path,
        "playback_rate": replay.playback_rate,
        "loop": replay.loop,
        "time_window": replay.time_window,
        "qos_file_path": replay.qos_file_path,
        "participant_qos_profile": replay.participant_qos_profile,
        "writer_qos_profile": replay.writer_qos_profile,
    }
    return AppCommand(
        command_type=action_to_command[action_id],
        target=payload["control_name"],
        payload=payload,
    )


def build_replay_launch_command(launch: ReplayLaunchViewModel) -> AppCommand:
    """Translate Replay launch settings into an app-core launch command."""

    payload: Dict[str, Any] = {
        "label": launch.label,
        "config_paths": list(launch.config_paths),
        "config_name": launch.config_name,
        "data_domain_id": launch.data_domain_id,
        "admin_domain_id": launch.admin_domain_id,
        "monitoring_domain_id": launch.monitoring_domain_id,
        "database_path": launch.database_path,
        "storage_format": launch.storage_format,
        "playback_rate": launch.playback_rate,
        "loop": launch.loop,
        "time_window": launch.time_window,
        "topic_allow": launch.topic_allow,
        "topic_deny": launch.topic_deny,
        "qos_file_path": launch.qos_file_path,
        "participant_qos_profile": launch.participant_qos_profile,
        "writer_qos_profile": launch.writer_qos_profile,
        "verbosity": launch.verbosity,
        "executable": launch.executable,
        "working_dir": launch.working_dir,
        "extra_args": list(launch.extra_args),
    }
    return AppCommand(
        command_type="service.launch_replay",
        target="replay",
        payload=payload,
    )


def _selected_target_id(targets: Tuple[ReplayTargetRow, ...], requested: str) -> str:
    if requested and any(target.target_id == requested for target in targets):
        return str(requested)
    if targets:
        return targets[0].target_id
    return str(requested)


def _replay_actions(
        selected_target: Optional[ReplayTargetRow],
        database_path: str,
        observed_state: str,
) -> Tuple[ReplayActionView, ...]:
    has_target = selected_target is not None
    has_database = bool(str(database_path).strip())
    conflict = bool(selected_target.conflict) if selected_target is not None else False
    disabled_reason = _disabled_reason(has_target, has_database, conflict)
    ready = has_target and has_database and not conflict
    state = str(observed_state).lower()
    running = "running" in state or "started" in state
    paused = "pause" in state
    return (
        ReplayActionView(
            "start", "Start", ready and not running,
            "already running" if ready and running else disabled_reason,
        ),
        ReplayActionView(
            "pause", "Pause", ready and running and not paused,
            "not running" if ready and not running else disabled_reason,
        ),
        ReplayActionView(
            "resume", "Resume", ready and paused,
            "not paused" if ready and not paused else disabled_reason,
        ),
        ReplayActionView(
            "stop", "Stop", ready and (running or paused),
            "not active" if ready and not (running or paused) else disabled_reason,
        ),
        ReplayActionView(
            "shutdown", "Shutdown", has_target and not conflict,
            "duplicate replay target" if conflict else "no Replay Service selected",
        ),
    )


def _disabled_reason(has_target: bool, has_database: bool, conflict: bool) -> str:
    if not has_target:
        return "no Replay Service selected"
    if conflict:
        return "duplicate replay target"
    if not has_database:
        return "recording database required"
    return ""


def _diagnostics(
        targets: Tuple[ReplayTargetRow, ...],
        database_path: str,
) -> Tuple[str, ...]:
    diagnostics = []
    if not targets:
        diagnostics.append("No Replay Service candidates discovered")
    if not str(database_path).strip():
        diagnostics.append("No recording database selected")
    if any(target.conflict for target in targets):
        diagnostics.append("Duplicate Replay Service target detected")
    return tuple(diagnostics)
