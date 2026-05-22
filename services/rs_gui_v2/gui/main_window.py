"""Dear PyGui renderer for the rs_gui_v2 shell."""

from typing import Callable, Optional

from app_core import AppCommand

from .tabs.plots_tab import PlotsTabViewModel
from .tabs.record_tab import RecordTabViewModel, build_record_action_command
from .tabs.topics_tab import (
    TopicFieldRow,
    TopicRow,
    TopicsTabViewModel,
    build_topic_action_command,
    build_topic_field_command,
    build_topic_select_command,
)
from .view_models import ShellViewModel, build_mock_shell_view_model


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
                dpg.add_text("No Replay Service selected")
            with dpg.tab(label="Convert"):
                dpg.add_text("No Converter job selected")
            with dpg.tab(label="Topics"):
                _render_topics_tab(dpg, view.topics_tab, command_sink=command_sink)
            with dpg.tab(label="Plots"):
                _render_plots_tab(dpg, view.plots_tab)
            with dpg.tab(label="Workspace"):
                dpg.add_text("No workspace changes")
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
