"""Convert tab rendering for the rs_gui_v2 Dear PyGui shell."""

from typing import Callable, Optional

from app_core import AppCommand

from ..tabs.convert_tab import ConvertTabViewModel, build_convert_action_command
from .shared import ACTION_BUTTON_WIDTH, add_action_button, add_labeled_input_text


def render_convert_tab(
        dpg,
        convert: ConvertTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the full Convert tab content."""
    preset = convert.selected_preset
    dpg.add_text(
        f"Preset: {preset.label if preset else '(none)'} | "
        f"Format: {preset.output_format if preset else convert.output_storage.storage_format} | "
        f"Verbosity: {convert.verbosity}"
    )
    add_labeled_input_text(dpg, "Converter Config File", "##convert_config_file", default_value=convert.config_file)
    add_labeled_input_text(dpg, "Input Storage Path", "##convert_input_storage", default_value=convert.input_storage.path)
    add_labeled_input_text(dpg, "Output Storage Path", "##convert_output_storage", default_value=convert.output_storage.path)
    add_labeled_input_text(dpg, "Data Selection Expression", "##convert_data_selection", default_value=convert.data_selection)
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
            add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_convert_action_callback(convert, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
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
