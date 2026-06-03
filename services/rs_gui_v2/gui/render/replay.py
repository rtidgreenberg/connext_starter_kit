"""Replay tab rendering for the rs_gui_v2 Dear PyGui shell."""

from dataclasses import replace
from typing import Callable, Optional

from app_core import AppCommand

from ..tabs.replay_tab import (
    ReplayTargetRow,
    ReplayTabViewModel,
    build_replay_action_command,
)
from .shared import (
    ACTION_BUTTON_WIDTH,
    COMPACT_BUTTON_WIDTH,
    add_action_button,
    add_labeled_input_text,
    collapsible_section,
    dpg_text_value,
    float_text_value,
)

REPLAY_DATABASE_PATH_TAG = "rs_gui_v2_replay_database_path"
REPLAY_PLAYBACK_RATE_TAG = "rs_gui_v2_replay_playback_rate"
REPLAY_TIME_WINDOW_TAG = "rs_gui_v2_replay_time_window"
REPLAY_QOS_FILE_TAG = "rs_gui_v2_replay_qos_file"
REPLAY_PARTICIPANT_QOS_TAG = "rs_gui_v2_replay_participant_qos"
REPLAY_WRITER_QOS_TAG = "rs_gui_v2_replay_writer_qos"


def render_replay_tab(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the full Replay tab content."""
    target_name = replay.selected_target.control_name if replay.selected_target else "(none)"
    dpg.add_text(
        f"Replay target: {target_name} | "
        f"State: {replay.observed_state} | Rate: {replay.playback_rate:g}x | "
        f"Loop: {'on' if replay.loop else 'off'}"
    )
    add_labeled_input_text(
        dpg,
        "Recording DB Path",
        f"##{REPLAY_DATABASE_PATH_TAG}",
        default_value=replay.database_path,
        tag=REPLAY_DATABASE_PATH_TAG,
    )
    add_labeled_input_text(
        dpg,
        "Playback Rate (x)",
        f"##{REPLAY_PLAYBACK_RATE_TAG}",
        default_value=f"{replay.playback_rate:g}",
        tag=REPLAY_PLAYBACK_RATE_TAG,
    )
    add_labeled_input_text(
        dpg,
        "Time Window [start,end]",
        f"##{REPLAY_TIME_WINDOW_TAG}",
        default_value=replay.time_window,
        tag=REPLAY_TIME_WINDOW_TAG,
    )
    with collapsible_section(dpg, "Replay QoS Overrides", default_open=False):
        add_labeled_input_text(
            dpg,
            "QoS XML Path",
            f"##{REPLAY_QOS_FILE_TAG}",
            default_value=replay.qos_file_path,
            tag=REPLAY_QOS_FILE_TAG,
        )
        add_labeled_input_text(
            dpg,
            "Participant QoS Profile",
            f"##{REPLAY_PARTICIPANT_QOS_TAG}",
            default_value=replay.participant_qos_profile,
            tag=REPLAY_PARTICIPANT_QOS_TAG,
        )
        add_labeled_input_text(
            dpg,
            "Writer QoS Profile",
            f"##{REPLAY_WRITER_QOS_TAG}",
            default_value=replay.writer_qos_profile,
            tag=REPLAY_WRITER_QOS_TAG,
        )
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
            add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_replay_action_callback(dpg, replay, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
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
                add_action_button(
                    dpg,
                    label="*" if row.selected else "Select",
                    enabled=not row.selected,
                    callback=_replay_select_callback(row, command_sink),
                    width=COMPACT_BUTTON_WIDTH,
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
        dpg,
        replay: ReplayTabViewModel,
        action_id: str,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        replay_with_inputs = _replay_view_from_inputs(dpg, replay)
        return command_sink(build_replay_action_command(action_id, replay_with_inputs))
    return _callback


def _replay_view_from_inputs(dpg, replay: ReplayTabViewModel) -> ReplayTabViewModel:
    return replace(
        replay,
        database_path=dpg_text_value(dpg, REPLAY_DATABASE_PATH_TAG, replay.database_path),
        playback_rate=float_text_value(dpg, REPLAY_PLAYBACK_RATE_TAG, replay.playback_rate),
        time_window=dpg_text_value(dpg, REPLAY_TIME_WINDOW_TAG, replay.time_window),
        qos_file_path=dpg_text_value(dpg, REPLAY_QOS_FILE_TAG, replay.qos_file_path),
        participant_qos_profile=dpg_text_value(
            dpg,
            REPLAY_PARTICIPANT_QOS_TAG,
            replay.participant_qos_profile,
        ),
        writer_qos_profile=dpg_text_value(
            dpg,
            REPLAY_WRITER_QOS_TAG,
            replay.writer_qos_profile,
        ),
    )


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
