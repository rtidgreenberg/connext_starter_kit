"""Topics tab rendering for the rs_gui_v2 Dear PyGui shell."""

from typing import Callable, Optional

from app_core import AppCommand

from ..tabs.topics_tab import (
    TopicFieldRow,
    TopicRow,
    TopicsTabViewModel,
    build_topic_action_command,
    build_topic_field_command,
    build_topic_select_command,
)
from .shared import ACTION_BUTTON_WIDTH, COMPACT_BUTTON_WIDTH, add_action_button, add_labeled_input_text, collapsible_section


def render_topics_tab(
        dpg,
        topics: TopicsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the full Topics tab content."""
    dpg.add_text(
        f"Domain: {topics.domain_id} | Filter: {topics.search_text or '(none)'} | "
        f"Internal topics: {'shown' if topics.include_internal else 'hidden'}"
    )
    add_labeled_input_text(
        dpg,
        "Topic Filter",
        "##topic_filter",
        default_value=topics.search_text,
        callback=_topic_search_callback(topics, command_sink),
    )
    _render_topic_actions(dpg, topics, command_sink=command_sink)
    _render_topic_table(dpg, topics, command_sink=command_sink)
    dpg.add_text("Field Picker")
    with collapsible_section(dpg, "Show Field Picker", default_open=False):
        _render_field_picker(dpg, topics, command_sink=command_sink)
    dpg.add_text("Sample Inspector")
    with collapsible_section(dpg, "Show Sample Inspector", default_open=False):
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
            add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_topic_action_callback(topics, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
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
                add_action_button(
                    dpg,
                    label="*" if row.selected else "Select",
                    enabled=not row.selected,
                    callback=_topic_select_callback(row, command_sink),
                    width=COMPACT_BUTTON_WIDTH,
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
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Plot", "Path", "Type", "Kind", "Plottable"):
            dpg.add_table_column(label=heading)
        for row in topics.fields:
            with dpg.table_row():
                add_action_button(
                    dpg,
                    label="*" if row.selected else "Select",
                    callback=_topic_field_callback(row, topics, command_sink, plot=False),
                    width=COMPACT_BUTTON_WIDTH,
                )
                add_action_button(
                    dpg,
                    label="*" if row.plot_selected else "Plot",
                    enabled=row.plottable,
                    callback=_topic_field_callback(row, topics, command_sink, plot=True),
                    width=COMPACT_BUTTON_WIDTH,
                )
                dpg.add_text(f"{'  ' * row.depth}{row.path}")
                dpg.add_text(row.type_name)
                dpg.add_text(row.scalar_kind)
                dpg.add_text("yes" if row.plottable else "")


def _render_sample_inspector(dpg, topics: TopicsTabViewModel) -> None:
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("Path", "Value", "Kind"):
            dpg.add_table_column(label=heading)
        for row in topics.sample_rows:
            with dpg.table_row():
                dpg.add_text(row.path)
                dpg.add_text(row.value)
                dpg.add_text(row.value_kind)


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
