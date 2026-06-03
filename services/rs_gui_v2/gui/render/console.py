"""Console tab rendering for the rs_gui_v2 Dear PyGui shell."""

import json
from typing import Callable, Optional, Tuple

from app_core import AppCommand

from .shared import ACTION_BUTTON_WIDTH, COMPACT_BUTTON_WIDTH, add_action_button, collapsible_section

CONSOLE_OUTPUT_TAG = "rs_gui_v2_console_output"
EVENT_OUTPUT_TAG = "rs_gui_v2_event_output"


def render_console_tab(
        dpg,
        console_lines: Tuple[str, ...] = (),
        event_lines: Tuple[str, ...] = (),
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the full Console tab content."""
    dpg.add_text("Console Output")
    dpg.add_text(
        "\n".join(console_lines) if console_lines else "(empty)",
        tag=CONSOLE_OUTPUT_TAG,
    )
    with dpg.group(horizontal=True):
        add_action_button(
            dpg,
            label="Copy Console",
            enabled=bool(console_lines),
            callback=_copy_console_callback(dpg, CONSOLE_OUTPUT_TAG),
            width=COMPACT_BUTTON_WIDTH,
        )
        add_action_button(
            dpg,
            label="Clear Console",
            enabled=bool(console_lines),
            callback=_console_clear_callback(command_sink),
            width=COMPACT_BUTTON_WIDTH,
        )
    with collapsible_section(dpg, "Event Log", default_open=False):
        dpg.add_text(
            "\n".join(event_lines) if event_lines else "(empty)",
            tag=EVENT_OUTPUT_TAG,
        )
        add_action_button(
            dpg,
            label="Copy Events",
            enabled=bool(event_lines),
            callback=_copy_console_callback(dpg, EVENT_OUTPUT_TAG),
            width=COMPACT_BUTTON_WIDTH,
        )


def refresh_console_output(
        dpg,
        console_lines: Tuple[str, ...] = (),
        event_lines: Tuple[str, ...] = (),
) -> None:
    """Refresh the console output text in-place."""
    set_value = getattr(dpg, "set_value", None)
    if not callable(set_value):
        return
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if callable(does_item_exist):
        if does_item_exist(CONSOLE_OUTPUT_TAG):
            set_value(CONSOLE_OUTPUT_TAG, "\n".join(console_lines) if console_lines else "(empty)")
        if does_item_exist(EVENT_OUTPUT_TAG):
            set_value(EVENT_OUTPUT_TAG, "\n".join(event_lines) if event_lines else "(empty)")


def _copy_console_callback(dpg, tag: str):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        get_value = getattr(dpg, "get_value", None)
        if not callable(get_value):
            return False
        try:
            import pyperclip
            text = get_value(tag)
            pyperclip.copy(text or "")
            return True
        except (ImportError, Exception):
            return False
    return _callback


def _console_clear_callback(command_sink: Optional[Callable[[AppCommand], bool]]):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        return command_sink(AppCommand(command_type="console.clear"))
    return _callback


def _json_block(obj: object) -> str:
    """Format an object as an indented JSON string."""
    try:
        return json.dumps(obj, indent=2, default=str)
    except (TypeError, ValueError):
        return str(obj)
