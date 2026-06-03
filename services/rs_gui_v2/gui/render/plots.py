"""Plots tab rendering for the rs_gui_v2 Dear PyGui shell."""

from typing import Callable, Optional

from app_core import AppCommand

from ..tabs.plots_tab import PlotsTabViewModel, build_plot_action_command
from .shared import ACTION_BUTTON_WIDTH, COMPACT_BUTTON_WIDTH, add_action_button, collapsible_section


def render_plots_tab(
        dpg,
        plots: PlotsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the full Plots tab content."""
    dpg.add_text(
        f"Active: {plots.active_plot_label or '(none)'} | "
        f"Plots: {len(plots.plot_table)} | Series: {len(plots.series_table)} | "
        f"Running: {'yes' if plots.running else 'no'}"
    )
    _render_plot_actions(dpg, plots, command_sink=command_sink)
    _render_plot_table(dpg, plots)
    with collapsible_section(dpg, "Series Table", default_open=True):
        _render_plot_series_table(dpg, plots)
    with collapsible_section(dpg, "Points Table (Last N)", default_open=False):
        _render_plot_points_table(dpg, plots)
    for diagnostic in plots.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _render_plot_actions(
        dpg,
        plots: PlotsTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in plots.actions:
            add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_plot_action_callback(plots, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
            )
            if action.reason and not action.enabled:
                dpg.add_text(action.reason)


def _render_plot_table(dpg, plots: PlotsTabViewModel) -> None:
    dpg.add_text("Configured Plots")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Plot Name", "Series", "State", "History"):
            dpg.add_table_column(label=heading)
        for row in plots.plot_table:
            with dpg.table_row():
                dpg.add_text("*" if row.selected else "")
                dpg.add_text(row.plot_name)
                dpg.add_text(str(row.series_count))
                dpg.add_text(row.state)
                dpg.add_text(f"{row.history_size}")


def _render_plot_series_table(dpg, plots: PlotsTabViewModel) -> None:
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in (
                "Selected", "Series", "Source Topic", "Field", "Points",
                "Y Range", "Color", "Axis"):
            dpg.add_table_column(label=heading)
        for row in plots.series_table:
            with dpg.table_row():
                dpg.add_text("*" if row.selected else "")
                dpg.add_text(row.label)
                dpg.add_text(row.source_topic)
                dpg.add_text(row.field_path)
                dpg.add_text(str(row.point_count))
                dpg.add_text(row.y_range)
                dpg.add_text(row.color)
                dpg.add_text(row.axis_label)


def _render_plot_points_table(dpg, plots: PlotsTabViewModel) -> None:
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True):
        for heading in ("Time", "X", "Y", "Series"):
            dpg.add_table_column(label=heading)
        for row in plots.point_rows:
            with dpg.table_row():
                dpg.add_text(row.timestamp)
                dpg.add_text(f"{row.x:g}")
                dpg.add_text(f"{row.y:g}")
                dpg.add_text(row.series_label)


def _plot_action_callback(
        plots: PlotsTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_plot_action_command(action_id, plots))
    return _callback
