"""Dear PyGui renderer for the rs_gui_v2 shell."""

from typing import Callable, Optional

from app_core import AppCommand

from .tabs.convert_tab import ConvertTabViewModel, build_convert_action_command
from .tabs.plots_tab import PlotsTabViewModel
from .tabs.record_tab import RecordTabViewModel, build_record_action_command
from .tabs.replay_tab import (
    ReplayTargetRow,
    ReplayTabViewModel,
    build_replay_action_command,
)
from .tabs.topics_tab import (
    TopicFieldRow,
    TopicRow,
    TopicsTabViewModel,
    build_topic_action_command,
    build_topic_field_command,
    build_topic_select_command,
)
from .view_models import ShellViewModel, build_mock_shell_view_model


WORKSPACE_NAME_INPUT_TAG = "rs_gui_v2_workspace_name"
WORKSPACE_PATH_INPUT_TAG = "rs_gui_v2_workspace_path"


class DearPyGuiUnavailable(RuntimeError):
    """Raised when the optional Dear PyGui dependency is not installed."""


def load_dearpygui():
    """Import Dear PyGui lazily so headless tests do not require it."""

    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception as exc:
        raise DearPyGuiUnavailable(
            "Dear PyGui is not installed in this Python environment. "
            "Install dearpygui to run the rs_gui_v2 graphical shell."
        ) from exc


class DearPyGuiShell:
    """Minimal Dear PyGui shell backed by immutable view-model snapshots."""

    def __init__(
            self,
            view_provider: Callable[[], ShellViewModel] = build_mock_shell_view_model,
            command_sink: Optional[Callable[[AppCommand], bool]] = None,
            dpg_module=None,
    ) -> None:
        self._view_provider = view_provider
        self._command_sink = command_sink
        self._dpg = dpg_module

    def render_once(self) -> ShellViewModel:
        """Render one snapshot into a new Dear PyGui context."""

        dpg = self._dpg or load_dearpygui()
        view = self._view_provider()
        dpg.create_context()
        try:
            render_shell_view(dpg, view, command_sink=self._command_sink)
        finally:
            dpg.destroy_context()
        return view

    def run(self) -> None:
        """Run the interactive Dear PyGui shell."""

        dpg = self._dpg or load_dearpygui()
        dpg.create_context()
        view = self._view_provider()
        try:
            dpg.create_viewport(title="rs_gui_v2", width=1400, height=900)
            render_shell_view(dpg, view, command_sink=self._command_sink)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.start_dearpygui()
        finally:
            dpg.destroy_context()


def render_shell_view(
        dpg,
        view: ShellViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the first rs_gui_v2 shell snapshot with Dear PyGui calls."""

    with dpg.window(label=view.title, tag="rs_gui_v2_main_window", width=1380, height=860):
        _render_status_strip(dpg, view)
        with dpg.tab_bar(tag="rs_gui_v2_tabs"):
            with dpg.tab(label="Record"):
                _render_record_tab(dpg, view.record_tab, command_sink=command_sink)
            with dpg.tab(label="Replay"):
                _render_replay_tab(dpg, view.replay_tab, command_sink=command_sink)
            with dpg.tab(label="Convert"):
                _render_convert_tab(dpg, view.convert_tab, command_sink=command_sink)
            with dpg.tab(label="Topics"):
                _render_topics_tab(dpg, view.topics_tab, command_sink=command_sink)
            with dpg.tab(label="Plots"):
                _render_plots_tab(dpg, view.plots_tab)
            with dpg.tab(label="Workspace"):
                _render_workspace_tab(dpg, view, command_sink=command_sink)
        _render_inspector(dpg, view)
        _render_event_log(dpg, view)


def _render_status_strip(dpg, view: ShellViewModel) -> None:
    with dpg.group(horizontal=True):
        for item in view.status_items:
            dpg.add_text(f"{item.label}: {item.value}")


def _render_record_tab(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text(f"Recording target: {record.target_label}")
    dpg.add_text(
        f"Readiness: {record.readiness} | State: {record.observed_state} | "
        f"Admin domain: {record.admin_domain} | Monitoring domain: {record.monitoring_domain}"
    )
    labels = [row.control_name for row in record.candidates] or ["No Recording Service"]
    default_value = record.selected_candidate.control_name if record.selected_candidate else labels[0]
    dpg.add_combo(labels, default_value=default_value, label="Candidate")
    _render_candidate_table(dpg, record)
    _render_record_actions(dpg, record, command_sink=command_sink)
    _render_command_history(dpg, record)
    _render_monitoring_summary(dpg, record)


def _render_candidate_table(dpg, record: RecordTabViewModel) -> None:
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Control Name", "Source", "Host", "PID", "State", "Age", "Confidence"):
            dpg.add_table_column(label=heading)
        for row in record.candidates:
            with dpg.table_row():
                dpg.add_text("*" if row.selected else "")
                dpg.add_text(row.control_name)
                dpg.add_text(row.source)
                dpg.add_text(row.hostname)
                dpg.add_text(row.pid)
                dpg.add_text(row.state)
                dpg.add_text(row.age)
                dpg.add_text(row.confidence)


def _render_record_actions(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in record.actions:
            dpg.add_button(
                label=action.label,
                enabled=action.enabled,
                callback=_record_action_callback(record, action.action_id, command_sink),
            )
    dpg.add_input_text(label="Tag", default_value=record.tag_value)
    for diagnostic in record.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _record_action_callback(
        record: RecordTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        selected_row = record.selected_candidate
        if selected_row is None:
            return False
        candidate = _candidate_from_record_row(record, selected_row.candidate_id)
        command = build_record_action_command(action_id, candidate, tag_name=record.tag_value)
        return command_sink(command)
    return _callback


def _render_convert_tab(
        dpg,
        convert: ConvertTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    preset = convert.selected_preset
    dpg.add_text(
        f"Preset: {preset.label if preset else '(none)'} | "
        f"Format: {preset.output_format if preset else convert.output_storage.storage_format} | "
        f"Verbosity: {convert.verbosity}"
    )
    dpg.add_input_text(label="Config File", default_value=convert.config_file)
    dpg.add_input_text(label="Input Storage", default_value=convert.input_storage.path)
    dpg.add_input_text(label="Output Storage", default_value=convert.output_storage.path)
    dpg.add_input_text(label="Data Selection", default_value=convert.data_selection)
    _render_convert_actions(dpg, convert, command_sink=command_sink)
    _render_convert_presets(dpg, convert)
    _render_convert_jobs(dpg, convert)
    _render_convert_logs(dpg, convert)
    dpg.add_text("CLI Preview")
    dpg.add_text(convert.cli_preview)
    dpg.add_text("XML Preview")
    dpg.add_text(convert.xml_preview)
    for diagnostic in convert.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _render_convert_actions(
        dpg,
        convert: ConvertTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in convert.actions:
            dpg.add_button(
                label=action.label,
                enabled=action.enabled,
                callback=_convert_action_callback(convert, action.action_id, command_sink),
            )
            if action.reason and not action.enabled:
                dpg.add_text(action.reason)


def _render_convert_presets(dpg, convert: ConvertTabViewModel) -> None:
    dpg.add_text("Converter Presets")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Preset", "Config Name", "Output Format", "Description"):
            dpg.add_table_column(label=heading)
        for row in convert.presets:
            with dpg.table_row():
                dpg.add_text("*" if row.preset_id == convert.selected_preset_id else "")
                dpg.add_text(row.label)
                dpg.add_text(row.config_name)
                dpg.add_text(row.output_format)
                dpg.add_text(row.description)


def _render_convert_jobs(dpg, convert: ConvertTabViewModel) -> None:
    dpg.add_text("Conversion Jobs")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Job", "Preset", "Input", "Output", "Format", "State", "Progress", "Message"):
            dpg.add_table_column(label=heading)
        for row in convert.jobs:
            with dpg.table_row():
                dpg.add_text("*" if row.job_id == convert.selected_job_id else "")
                dpg.add_text(row.job_id)
                dpg.add_text(row.preset_id)
                dpg.add_text(row.input_path)
                dpg.add_text(row.output_path)
                dpg.add_text(row.output_format)
                dpg.add_text(row.state)
                dpg.add_text(row.progress)
                dpg.add_text(row.message)


def _render_convert_logs(dpg, convert: ConvertTabViewModel) -> None:
    dpg.add_text("Job Log")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("Time", "Severity", "Source", "Job", "Message"):
            dpg.add_table_column(label=heading)
        for row in convert.logs:
            with dpg.table_row():
                dpg.add_text(row.timestamp)
                dpg.add_text(row.severity)
                dpg.add_text(row.source)
                dpg.add_text(row.job_id)
                dpg.add_text(row.message)


def _convert_action_callback(
        convert: ConvertTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_convert_action_command(action_id, convert))
    return _callback


def _render_replay_tab(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    target_name = replay.selected_target.control_name if replay.selected_target else "(none)"
    dpg.add_text(
        f"Replay target: {target_name} | "
        f"State: {replay.observed_state} | Rate: {replay.playback_rate:g}x | "
        f"Loop: {'on' if replay.loop else 'off'}"
    )
    dpg.add_input_text(label="Recording Database", default_value=replay.database_path)
    dpg.add_input_text(label="Playback Rate", default_value=f"{replay.playback_rate:g}")
    dpg.add_input_text(label="Time Window", default_value=replay.time_window)
    _render_replay_actions(dpg, replay, command_sink=command_sink)
    _render_replay_targets(dpg, replay, command_sink=command_sink)
    _render_replay_timeline(dpg, replay)
    for diagnostic in replay.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _render_replay_actions(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in replay.actions:
            dpg.add_button(
                label=action.label,
                enabled=action.enabled,
                callback=_replay_action_callback(replay, action.action_id, command_sink),
            )
            if action.reason and not action.enabled:
                dpg.add_text(action.reason)


def _render_replay_targets(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text("Replay Service Candidates")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in (
                "Selected", "Control Name", "Source", "Host", "State",
                "Progress", "Diagnostic"):
            dpg.add_table_column(label=heading)
        for row in replay.targets:
            with dpg.table_row():
                dpg.add_button(
                    label="*" if row.selected else "Select",
                    enabled=not row.selected,
                    callback=_replay_select_callback(row, command_sink),
                )
                dpg.add_text(row.control_name)
                dpg.add_text(row.source)
                dpg.add_text(row.hostname)
                dpg.add_text(row.state)
                dpg.add_text(row.progress)
                dpg.add_text("duplicate target" if row.conflict else "")


def _render_replay_timeline(dpg, replay: ReplayTabViewModel) -> None:
    dpg.add_text("Recording Timeline")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("Label", "Start", "End", "State"):
            dpg.add_table_column(label=heading)
        for row in replay.timeline:
            with dpg.table_row():
                dpg.add_text(row.label)
                dpg.add_text(row.start_time)
                dpg.add_text(row.end_time)
                dpg.add_text(row.state)


def _replay_action_callback(
        replay: ReplayTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_replay_action_command(action_id, replay))
    return _callback


def _replay_select_callback(
        row: ReplayTargetRow,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(AppCommand(
            command_type="replay.select_target",
            target=row.control_name,
            payload={"target_id": row.target_id, "control_name": row.control_name},
        ))
    return _callback


def _candidate_from_record_row(record: RecordTabViewModel, candidate_id: str):
    for row in record.candidates:
        if row.candidate_id == candidate_id:
            from app_core.services import ServiceInstanceRef, ServiceKind, ServiceProcessCandidate
            return ServiceProcessCandidate(
                candidate_id=row.candidate_id,
                service=ServiceInstanceRef(ServiceKind.RECORDING, row.control_name, record.admin_domain, record.monitoring_domain),
                source=row.source,
                display_label=row.label,
                pid=int(row.pid) if row.pid else None,
                hostname=row.hostname,
                observed_state=row.state,
                owns_process=row.owned,
            )
    raise ValueError(f"Unknown Record tab candidate: {candidate_id}")


def _render_command_history(dpg, record: RecordTabViewModel) -> None:
    dpg.add_text("Command History")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("ID", "Command", "Reply", "Observed", "Resource"):
            dpg.add_table_column(label=heading)
        for row in record.command_history:
            with dpg.table_row():
                dpg.add_text(row.command_id)
                dpg.add_text(row.command)
                dpg.add_text(row.reply)
                dpg.add_text(row.observed)
                dpg.add_text(row.resource_path)


def _render_monitoring_summary(dpg, record: RecordTabViewModel) -> None:
    dpg.add_text("Monitoring Summary")
    for key, value in record.monitoring_summary:
        dpg.add_text(f"{key}: {value}")


def _render_topics_tab(
        dpg,
        topics: TopicsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text(
        f"Domain: {topics.domain_id} | Filter: {topics.search_text or '(none)'} | "
        f"Internal topics: {'shown' if topics.include_internal else 'hidden'}"
    )
    dpg.add_input_text(
        label="Filter",
        default_value=topics.search_text,
        callback=_topic_search_callback(topics, command_sink),
    )
    _render_topic_actions(dpg, topics, command_sink=command_sink)
    _render_topic_table(dpg, topics, command_sink=command_sink)
    _render_field_picker(dpg, topics, command_sink=command_sink)
    _render_sample_inspector(dpg, topics)
    for diagnostic in topics.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _render_topic_actions(
        dpg,
        topics: TopicsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in topics.actions:
            dpg.add_button(
                label=action.label,
                enabled=action.enabled,
                callback=_topic_action_callback(topics, action.action_id, command_sink),
            )
            if action.reason and not action.enabled:
                dpg.add_text(action.reason)


def _render_topic_table(
        dpg,
        topics: TopicsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text("Discovered Topics")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in (
                "Selected", "Topic", "Type", "State", "Writers", "Readers",
                "Subscription", "Samples", "Partitions", "Diagnostic"):
            dpg.add_table_column(label=heading)
        for row in topics.rows:
            with dpg.table_row():
                dpg.add_button(
                    label="*" if row.selected else "Select",
                    enabled=not row.selected,
                    callback=_topic_select_callback(row, command_sink),
                )
                dpg.add_text(row.topic_name)
                dpg.add_text(row.type_name)
                dpg.add_text(row.state)
                dpg.add_text(str(row.writers))
                dpg.add_text(str(row.readers))
                dpg.add_text(row.subscription_status)
                dpg.add_text(str(row.sample_count))
                dpg.add_text(row.partitions)
                dpg.add_text(row.diagnostic)


def _render_field_picker(
    dpg,
    topics: TopicsTabViewModel,
    command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text("Field Picker")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Plot", "Path", "Type", "Kind", "Plottable"):
            dpg.add_table_column(label=heading)
        for row in topics.fields:
            with dpg.table_row():
                dpg.add_button(
                    label="*" if row.selected else "Select",
                    callback=_topic_field_callback(row, topics, command_sink, plot=False),
                )
                dpg.add_button(
                    label="*" if row.plot_selected else "Plot",
                    enabled=row.plottable,
                    callback=_topic_field_callback(row, topics, command_sink, plot=True),
                )
                dpg.add_text(f"{'  ' * row.depth}{row.path}")
                dpg.add_text(row.type_name)
                dpg.add_text(row.scalar_kind)
                dpg.add_text("yes" if row.plottable else "")


def _topic_action_callback(
        topics: TopicsTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_topic_action_command(action_id, topics))
    return _callback


def _topic_search_callback(
        topics: TopicsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_topic_action_command("set_search", topics, value=app_data))
    return _callback


def _topic_select_callback(
        row: TopicRow,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_topic_select_command(row))
    return _callback


def _topic_field_callback(
        field: TopicFieldRow,
        topics: TopicsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]],
        plot: bool = False,
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        selected = not field.plot_selected if plot else not field.selected
        return command_sink(build_topic_field_command(field, topics, plot=plot, selected=selected))
    return _callback


def _render_sample_inspector(dpg, topics: TopicsTabViewModel) -> None:
    dpg.add_text("Sample Inspector")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("Path", "Value", "Kind"):
            dpg.add_table_column(label=heading)
        for row in topics.sample_rows:
            with dpg.table_row():
                dpg.add_text(row.path)
                dpg.add_text(row.value)
                dpg.add_text(row.value_kind)


def _render_plots_tab(dpg, plots: PlotsTabViewModel) -> None:
    selected = plots.selected_plot_name or "(none)"
    dpg.add_text(
        f"Selected plot: {selected} | Points: {plots.total_point_count} | "
        f"Updates: {'paused' if plots.paused else 'running'}"
    )
    _render_plot_actions(dpg, plots)
    _render_plot_table(dpg, plots)
    _render_plot_series_table(dpg, plots)
    _render_plot_points_table(dpg, plots)
    for diagnostic in plots.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _render_workspace_tab(
        dpg,
        view: ShellViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text(
        f"Workspace: {view.workspace_name} | "
        f"State: {'unsaved' if view.workspace_unsaved else 'saved'}"
    )
    dpg.add_input_text(
        label="Workspace Name",
        tag=WORKSPACE_NAME_INPUT_TAG,
        default_value=view.workspace_name,
    )
    dpg.add_input_text(
        label="Workspace Path",
        tag=WORKSPACE_PATH_INPUT_TAG,
        default_value=view.workspace_path,
    )
    with dpg.group(horizontal=True):
        dpg.add_button(
            label="Save Workspace",
            callback=_workspace_action_callback(dpg, view, "save", command_sink),
        )
        dpg.add_button(
            label="Load Workspace",
            callback=_workspace_action_callback(dpg, view, "load", command_sink),
        )


def build_workspace_action_command(
        action_id: str,
        path: str = "",
        workspace_name: str = "",
) -> AppCommand:
    """Build a workspace command from GUI control values."""

    if action_id == "save":
        return AppCommand(
            command_type="workspace.save",
            payload={"path": path, "workspace_name": workspace_name},
        )
    if action_id == "load":
        return AppCommand(
            command_type="workspace.load",
            payload={"path": path},
        )
    raise ValueError(f"Unsupported workspace action: {action_id}")


def _workspace_action_callback(
        dpg,
        view: ShellViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        path = _widget_value(dpg, WORKSPACE_PATH_INPUT_TAG, view.workspace_path)
        workspace_name = _widget_value(dpg, WORKSPACE_NAME_INPUT_TAG, view.workspace_name)
        command = build_workspace_action_command(
            action_id,
            path=path,
            workspace_name=workspace_name,
        )
        return command_sink(command)
    return _callback


def _widget_value(dpg, tag: str, default: str) -> str:
    get_value = getattr(dpg, "get_value", None)
    if get_value is None:
        return default
    value = get_value(tag)
    return str(value if value is not None else default)


def _render_plot_actions(dpg, plots: PlotsTabViewModel) -> None:
    with dpg.group(horizontal=True):
        for action in plots.actions:
            dpg.add_button(label=action.label, enabled=action.enabled)
            if action.reason and not action.enabled:
                dpg.add_text(action.reason)


def _render_plot_table(dpg, plots: PlotsTabViewModel) -> None:
    dpg.add_text("Configured Plots")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Name", "Series", "Points", "History", "Max Points"):
            dpg.add_table_column(label=heading)
        for row in plots.rows:
            with dpg.table_row():
                dpg.add_text("*" if row.selected else "")
                dpg.add_text(row.name)
                dpg.add_text(str(row.series_count))
                dpg.add_text(str(row.point_count))
                dpg.add_text(f"{row.history_seconds:g}s")
                dpg.add_text(str(row.max_points))


def _render_plot_series_table(dpg, plots: PlotsTabViewModel) -> None:
    dpg.add_text("Series")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in (
                "Label", "Topic", "Field", "Points", "Latest", "Timestamp",
                "Accepted", "Skipped", "Dropped", "Decimated", "Status"):
            dpg.add_table_column(label=heading)
        for row in plots.series:
            with dpg.table_row():
                dpg.add_text(row.label)
                dpg.add_text(row.topic_name)
                dpg.add_text(row.field_path)
                dpg.add_text(str(row.point_count))
                dpg.add_text(row.latest_value)
                dpg.add_text(row.latest_timestamp)
                dpg.add_text(str(row.accepted_samples))
                dpg.add_text(str(row.skipped_samples))
                dpg.add_text(str(row.dropped_points))
                dpg.add_text(str(row.decimated_points))
                dpg.add_text(row.status)


def _render_plot_points_table(dpg, plots: PlotsTabViewModel) -> None:
    dpg.add_text("Recent Points")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("Series", "Timestamp", "Value", "Source"):
            dpg.add_table_column(label=heading)
        for row in plots.point_rows:
            with dpg.table_row():
                dpg.add_text(row.label)
                dpg.add_text(row.timestamp)
                dpg.add_text(row.value)
                dpg.add_text(row.source)


def _render_inspector(dpg, view: ShellViewModel) -> None:
    dpg.add_separator()
    dpg.add_text(view.inspector_title)
    for line in view.inspector_lines:
        dpg.add_text(line)


def _render_event_log(dpg, view: ShellViewModel) -> None:
    dpg.add_separator()
    dpg.add_text("Event Log")
    for entry in view.event_log:
        dpg.add_text(f"{entry.timestamp} {entry.source}: {entry.message}")
