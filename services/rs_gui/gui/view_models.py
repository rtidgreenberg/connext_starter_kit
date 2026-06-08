"""Immutable shell view models for the rs_gui UI layer."""

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Tuple

from app_core import AppEvent, AppState, LifecyclePhase
from app_core.services import ServiceCandidateSelection

from .tabs.convert_tab import ConvertTabViewModel, build_mock_convert_tab_view_model
from .tabs.plots_tab import PlotsTabViewModel, build_mock_plots_tab_view_model
from .tabs.record_tab import RecordTabViewModel, build_mock_record_tab_view_model, build_record_tab_view_model
from .tabs.replay_tab import ReplayTabViewModel, build_mock_replay_tab_view_model
from .tabs.topics_tab import TopicsTabViewModel, build_mock_topics_tab_view_model


@dataclass(frozen=True)
class ShellStatusItem:
    """One compact value in the top application status strip."""

    label: str
    value: str
    state: str = "normal"


@dataclass(frozen=True)
class EventLogEntry:
    """UI-facing event log row."""

    timestamp: str
    level: str
    source: str
    message: str
    event_type: str = ""
    event_id: str = ""
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ShellViewModel:
    """Top-level immutable snapshot consumed by the GUI renderer."""

    title: str
    active_tab: str
    workspace_name: str = "Workspace"
    workspace_path: str = ""
    workspace_unsaved: bool = False
    status_items: Tuple[ShellStatusItem, ...] = field(default_factory=tuple)
    convert_tab: ConvertTabViewModel = field(default_factory=ConvertTabViewModel)
    record_tab: RecordTabViewModel = field(default_factory=lambda: build_record_tab_view_model(ServiceCandidateSelection()))
    replay_tab: ReplayTabViewModel = field(default_factory=ReplayTabViewModel)
    topics_tab: TopicsTabViewModel = field(default_factory=TopicsTabViewModel)
    plots_tab: PlotsTabViewModel = field(default_factory=PlotsTabViewModel)
    event_log: Tuple[EventLogEntry, ...] = field(default_factory=tuple)
    operator_diagnostics: Tuple[str, ...] = field(default_factory=tuple)
    inspector_title: str = "Inspector"
    inspector_lines: Tuple[str, ...] = field(default_factory=tuple)


def build_shell_view_model(
        app_state: AppState,
        record_tab: RecordTabViewModel,
    convert_tab: ConvertTabViewModel = None,
        replay_tab: ReplayTabViewModel = None,
        topics_tab: TopicsTabViewModel = None,
        plots_tab: PlotsTabViewModel = None,
        event_log: Iterable[EventLogEntry] = (),
        workspace_name: str = "Workspace",
        workspace_path: str = "",
        unsaved: bool = False,
) -> ShellViewModel:
    """Build the first shell snapshot from app state and a Record tab view."""

    convert_tab = convert_tab or ConvertTabViewModel()
    replay_tab = replay_tab or ReplayTabViewModel()
    topics_tab = topics_tab or TopicsTabViewModel()
    plots_tab = plots_tab or PlotsTabViewModel()
    selected = record_tab.selected_candidate
    operator_diagnostics = _operator_diagnostics(app_state, record_tab)
    inspector_lines = (
        f"Target: {record_tab.target_label}",
        f"Selected: {selected.candidate_id if selected else 'none'}",
        f"Readiness: {record_tab.readiness}",
        f"Observed: {record_tab.observed_state}",
    ) + record_tab.diagnostics + _runtime_counter_lines(app_state)
    title = f"Workspace: {workspace_name}{' *' if unsaved else ''}"
    return ShellViewModel(
        title=title,
        active_tab="Record",
        workspace_name=workspace_name,
        workspace_path=workspace_path,
        workspace_unsaved=unsaved,
        status_items=_status_items(app_state, record_tab, convert_tab, replay_tab, topics_tab, plots_tab),
        convert_tab=convert_tab,
        record_tab=record_tab,
        replay_tab=replay_tab,
        topics_tab=topics_tab,
        plots_tab=plots_tab,
        event_log=tuple(event_log),
        operator_diagnostics=operator_diagnostics,
        inspector_title="Record Inspector",
        inspector_lines=inspector_lines,
    )


def build_mock_shell_view_model(now: float = 120.0) -> ShellViewModel:
    """Return a deterministic shell snapshot for GUI smoke rendering."""

    app_state = AppState(
        lifecycle=LifecyclePhase.RUNNING,
        dds_enabled=True,
        monitoring_enabled=True,
        discovery_enabled=True,
        admin_rpc_enabled=True,
    )
    event_log = (
        EventLogEntry("13:12:01", "info", "runtime", "Monitoring active on domain 0"),
        EventLogEntry("13:12:03", "info", "service_admin", "Pause acknowledged"),
    )
    return build_shell_view_model(
        app_state,
        build_mock_record_tab_view_model(now=now),
        convert_tab=build_mock_convert_tab_view_model(now=now),
        replay_tab=build_mock_replay_tab_view_model(),
        topics_tab=build_mock_topics_tab_view_model(now=now),
        plots_tab=build_mock_plots_tab_view_model(now=now),
        event_log=event_log,
        workspace_name="Robot Run 03",
        workspace_path="services/rs_gui/test_output/robot_run_03.json",
        unsaved=True,
    )


def build_empty_shell_view_model() -> ShellViewModel:
    """Return a clean shell snapshot with no mock/demo service or DDS data."""

    return build_shell_view_model(
        AppState(),
        build_record_tab_view_model(ServiceCandidateSelection()),
        convert_tab=ConvertTabViewModel(),
        replay_tab=ReplayTabViewModel(),
        topics_tab=TopicsTabViewModel(),
        plots_tab=PlotsTabViewModel(),
        workspace_name="Workspace",
    )


def event_log_entry_from_event(event: AppEvent) -> EventLogEntry:
    """Normalize an app-core event for the bottom shell event log."""

    level = str(event.payload.get("level", "info"))
    message = str(event.payload.get("message", ""))
    if not message and event.event_type == "runtime.lifecycle_changed":
        message = (
            f"Lifecycle {event.payload.get('previous', '?')} -> "
            f"{event.payload.get('current', '?')}"
        )
    if not message:
        message = event.event_type
    return EventLogEntry(
        timestamp=_time_text(event.created_at),
        level=level,
        source=event.source,
        message=message,
        event_type=event.event_type,
        event_id=event.event_id,
        payload=dict(event.payload),
    )


def _status_items(
        app_state: AppState,
        record_tab: RecordTabViewModel,
        convert_tab: ConvertTabViewModel,
        replay_tab: ReplayTabViewModel,
        topics_tab: TopicsTabViewModel,
        plots_tab: PlotsTabViewModel,
) -> Tuple[ShellStatusItem, ...]:
    error_count = len(app_state.recent_errors)
    counter = app_state.runtime_counters
    operator_diagnostics = _operator_diagnostics(app_state, record_tab)
    drop_count = (
        counter.commands_dropped
        + counter.events_dropped
        + counter.ui_event_log_dropped
        + counter.samples_dropped
    )
    return (
        ShellStatusItem("Runtime", app_state.lifecycle.value, _state_for_lifecycle(app_state.lifecycle)),
        ShellStatusItem("DDS", "enabled" if app_state.dds_enabled else "off", "ok" if app_state.dds_enabled else "muted"),
        ShellStatusItem("Admin", "enabled" if app_state.admin_rpc_enabled else "off", "ok" if app_state.admin_rpc_enabled else "muted"),
        ShellStatusItem("Monitoring", "enabled" if app_state.monitoring_enabled else "off", "ok" if app_state.monitoring_enabled else "muted"),
        ShellStatusItem("Frames", str(counter.ui_frames_built), "normal"),
        ShellStatusItem("Drops", str(drop_count), "error" if drop_count else "ok"),
        ShellStatusItem("Diagnostics", str(len(operator_diagnostics)), "error" if error_count else ("busy" if operator_diagnostics else "ok")),
        ShellStatusItem("Record", record_tab.observed_state, "ok" if record_tab.observed_state.lower() == "running" else "normal"),
        ShellStatusItem("Replay", replay_tab.observed_state, "ok" if replay_tab.observed_state.lower() == "running" else "normal"),
        ShellStatusItem("Convert", str(len(convert_tab.jobs)), "ok" if convert_tab.jobs else "normal"),
        ShellStatusItem("Topics", str(topics_tab.visible_topic_count), "ok" if topics_tab.visible_topic_count else "normal"),
        ShellStatusItem("Plots", str(plots_tab.total_point_count), "ok" if plots_tab.total_point_count else "normal"),
        ShellStatusItem("Errors", str(error_count), "error" if error_count else "ok"),
    )


def _operator_diagnostics(app_state: AppState, record_tab: RecordTabViewModel) -> Tuple[str, ...]:
    diagnostics = [
        f"{diagnostic.severity.upper()} {diagnostic.source}: {diagnostic.message}"
        for diagnostic in app_state.operator_diagnostics
        if diagnostic.message
    ]
    diagnostics.extend(f"ERROR runtime: {message}" for message in app_state.recent_errors)
    diagnostics.extend(f"WARN record: {message}" for message in record_tab.diagnostics)
    if record_tab.readiness and record_tab.readiness not in ("request+reply matched", "not checked"):
        diagnostics.append(f"WARN service_admin: {record_tab.readiness}")
    return tuple(diagnostics)


def _runtime_counter_lines(app_state: AppState) -> Tuple[str, ...]:
    counter = app_state.runtime_counters
    return (
        f"Frames: {counter.ui_frames_built}",
        f"Commands: {counter.commands_enqueued} queued / {counter.commands_drained} handled / {counter.commands_dropped} dropped",
        f"Events: {counter.events_published} published / {counter.events_drained} drained / {counter.events_dropped} dropped",
        f"Samples: {counter.samples_received} received / {counter.samples_dropped} dropped",
    )


def _state_for_lifecycle(lifecycle: LifecyclePhase) -> str:
    if lifecycle == LifecyclePhase.RUNNING:
        return "ok"
    if lifecycle == LifecyclePhase.FAILED:
        return "error"
    if lifecycle in (LifecyclePhase.STARTING, LifecyclePhase.STOPPING):
        return "busy"
    return "normal"


def _time_text(created_at: float) -> str:
    if created_at <= 0:
        return "--:--:--"
    seconds = int(created_at) % 86400
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    second = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{second:02d}"
