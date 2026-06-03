"""Workspace tab rendering for the rs_gui_v2 Dear PyGui shell."""

from typing import Callable, Optional

from app_core import AppCommand

from ..tabs.workspace_tab import WorkspaceTabViewModel
from .shared import ACTION_BUTTON_WIDTH, add_action_button, add_labeled_input_text, collapsible_section


def render_workspace_tab(
        dpg,
        workspace: WorkspaceTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the full Workspace tab content."""
    dpg.add_text(
        f"Workspace: {workspace.workspace_path} | "
        f"Recordings: {workspace.file_count} | "
        f"Total: {workspace.total_size}"
    )
    add_labeled_input_text(
        dpg,
        "Workspace Path",
        "##workspace_path",
        default_value=workspace.workspace_path,
    )
    _render_workspace_actions(dpg, workspace, command_sink=command_sink)
    _render_workspace_file_table(dpg, workspace)
    for diagnostic in workspace.diagnostics:
        dpg.add_text(f"Diagnostic: {diagnostic}")


def _render_workspace_actions(
        dpg,
        workspace: WorkspaceTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in workspace.actions:
            add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_workspace_action_callback(workspace, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
            )


def _render_workspace_file_table(dpg, workspace: WorkspaceTabViewModel) -> None:
    dpg.add_text("Recording Files")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in (
                "Selected", "File Name", "Path", "Size", "Created",
                "Format", "Duration", "Diagnostic"):
            dpg.add_table_column(label=heading)
        for row in workspace.files:
            with dpg.table_row():
                dpg.add_text("*" if row.selected else "")
                dpg.add_text(row.name)
                dpg.add_text(row.path)
                dpg.add_text(row.size)
                dpg.add_text(row.created)
                dpg.add_text(row.format)
                dpg.add_text(row.duration)
                dpg.add_text(row.diagnostic)


def build_workspace_action_command(action_id: str, workspace: WorkspaceTabViewModel) -> AppCommand:
    """Build AppCommand for a workspace tab action."""
    return AppCommand(
        command_type=f"workspace.{action_id}",
        payload={
            "workspace_path": workspace.workspace_path,
            "selected_files": [f.path for f in workspace.files if f.selected],
        },
    )


def _workspace_action_callback(
        workspace: WorkspaceTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(build_workspace_action_command(action_id, workspace))
    return _callback
