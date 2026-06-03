"""Per-tab rendering modules for the rs_gui_v2 Dear PyGui shell.

NOTE: These modules are not yet wired into main_window.py. They exist as
reference implementations for future scaling — when main_window.py needs to be
decomposed, migrate one tab at a time by delegating to the corresponding render
module here. Currently only RecordLaunchVariables and CloseItem are actively
used elsewhere.
"""

from .record import (
    render_record_tab,
    refresh_record_tab,
    RecordLaunchVariables,
    merge_record_variable_args,
    record_var_from_extra_args,
    record_storage_path_expression,
    record_filename_expression_from_base,
    record_filename_base_from_expression,
    safe_record_filename_base,
    safe_record_session_name,
    boolean_text,
)
from .replay import render_replay_tab
from .convert import render_convert_tab
from .topics import render_topics_tab
from .plots import render_plots_tab
from .workspace import render_workspace_tab, build_workspace_action_command
from .console import render_console_tab, refresh_console_output
from .close_dialog import (
    CloseItem,
    close_process_items,
    default_close_policy,
    show_close_prompt,
)
from .shared import (
    ACTION_BUTTON_WIDTH,
    COMPACT_BUTTON_WIDTH,
    DOMAIN_ID_INPUT_WIDTH,
    PRIMARY_BUTTON_WIDTH,
    STORAGE_PATH_INPUT_WIDTH,
    add_action_button,
    add_labeled_checkbox,
    add_labeled_input_text,
    apply_button_theme_if_supported,
    collapsible_section,
    dpg_text_value,
    float_text_value,
    has_item,
    int_text_value,
    widget_value,
)

__all__ = [
    "CloseItem",
    "add_action_button",
    "add_labeled_checkbox",
    "add_labeled_input_text",
    "apply_button_theme_if_supported",
    "close_process_items",
    "collapsible_section",
    "default_close_policy",
    "dpg_text_value",
    "float_text_value",
    "has_item",
    "int_text_value",
    "refresh_console_output",
    "refresh_record_tab",
    "render_console_tab",
    "render_convert_tab",
    "render_plots_tab",
    "render_record_tab",
    "render_replay_tab",
    "render_topics_tab",
    "render_workspace_tab",
    "build_workspace_action_command",
    "show_close_prompt",
    "widget_value",
]
