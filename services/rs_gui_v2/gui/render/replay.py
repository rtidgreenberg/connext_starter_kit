"""Replay tab rendering for the rs_gui_v2 Dear PyGui shell."""

from dataclasses import replace
from typing import Callable, Optional

from app_core import AppCommand

from ..tabs.replay_tab import (
    ReplayTargetRow,
    ReplayTabViewModel,
    build_replay_action_command,
    build_replay_launch_command,
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
REPLAY_LAUNCH_LABEL_TAG = "rs_gui_v2_replay_launch_label"
REPLAY_LAUNCH_CONFIG_PATHS_TAG = "rs_gui_v2_replay_launch_config_paths"
REPLAY_LAUNCH_CONFIG_NAME_TAG = "rs_gui_v2_replay_launch_config_name"
REPLAY_LAUNCH_DATA_DOMAIN_TAG = "rs_gui_v2_replay_launch_data_domain"
REPLAY_LAUNCH_ADMIN_DOMAIN_TAG = "rs_gui_v2_replay_launch_admin_domain"
REPLAY_LAUNCH_MONITOR_DOMAIN_TAG = "rs_gui_v2_replay_launch_monitor_domain"
REPLAY_LAUNCH_DATABASE_PATH_TAG = "rs_gui_v2_replay_launch_database_path"
REPLAY_LAUNCH_VERBOSITY_TAG = "rs_gui_v2_replay_launch_verbosity"
REPLAY_LAUNCH_EXECUTABLE_TAG = "rs_gui_v2_replay_launch_executable"
REPLAY_LAUNCH_WORKING_DIR_TAG = "rs_gui_v2_replay_launch_working_dir"
REPLAY_LAUNCH_EXTRA_ARGS_TAG = "rs_gui_v2_replay_launch_extra_args"


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
    _render_replay_launch(dpg, replay, command_sink=command_sink)
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


def _render_replay_launch(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    launch = replay.launch
    with collapsible_section(dpg, "Launch Replay Service", default_open=True):
        add_labeled_input_text(dpg, "Label", f"##{REPLAY_LAUNCH_LABEL_TAG}", default_value=launch.label, tag=REPLAY_LAUNCH_LABEL_TAG)
        add_labeled_input_text(
            dpg,
            "Config XML Paths",
            f"##{REPLAY_LAUNCH_CONFIG_PATHS_TAG}",
            default_value=";".join(launch.config_paths),
            tag=REPLAY_LAUNCH_CONFIG_PATHS_TAG,
        )
        add_labeled_input_text(dpg, "Config Name", f"##{REPLAY_LAUNCH_CONFIG_NAME_TAG}", default_value=launch.config_name, tag=REPLAY_LAUNCH_CONFIG_NAME_TAG)
        add_labeled_input_text(dpg, "Data Domain", f"##{REPLAY_LAUNCH_DATA_DOMAIN_TAG}", default_value=str(launch.data_domain_id), tag=REPLAY_LAUNCH_DATA_DOMAIN_TAG)
        add_labeled_input_text(dpg, "Admin Domain", f"##{REPLAY_LAUNCH_ADMIN_DOMAIN_TAG}", default_value=str(launch.admin_domain_id), tag=REPLAY_LAUNCH_ADMIN_DOMAIN_TAG)
        add_labeled_input_text(dpg, "Monitoring Domain", f"##{REPLAY_LAUNCH_MONITOR_DOMAIN_TAG}", default_value=str(launch.monitoring_domain_id), tag=REPLAY_LAUNCH_MONITOR_DOMAIN_TAG)
        add_labeled_input_text(dpg, "Recording DB Path", f"##{REPLAY_LAUNCH_DATABASE_PATH_TAG}", default_value=launch.database_path, tag=REPLAY_LAUNCH_DATABASE_PATH_TAG)
        with collapsible_section(dpg, "Replay Launch Advanced", default_open=False):
            add_labeled_input_text(dpg, "Verbosity", f"##{REPLAY_LAUNCH_VERBOSITY_TAG}", default_value=launch.verbosity, tag=REPLAY_LAUNCH_VERBOSITY_TAG)
            add_labeled_input_text(dpg, "Executable", f"##{REPLAY_LAUNCH_EXECUTABLE_TAG}", default_value=launch.executable, tag=REPLAY_LAUNCH_EXECUTABLE_TAG)
            add_labeled_input_text(dpg, "Working Dir", f"##{REPLAY_LAUNCH_WORKING_DIR_TAG}", default_value=launch.working_dir, tag=REPLAY_LAUNCH_WORKING_DIR_TAG)
            add_labeled_input_text(dpg, "Extra Args", f"##{REPLAY_LAUNCH_EXTRA_ARGS_TAG}", default_value=" ".join(launch.extra_args), tag=REPLAY_LAUNCH_EXTRA_ARGS_TAG)
        add_action_button(
            dpg,
            label="Launch Replay Service",
            enabled=launch.enabled,
            callback=_replay_launch_callback(dpg, replay, command_sink),
            width=ACTION_BUTTON_WIDTH,
        )
        if launch.disabled_reason and not launch.enabled:
            dpg.add_text(launch.disabled_reason)


def _render_replay_targets(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    dpg.add_text("Replay Service Candidates")
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in (
            "Selected", "Control Name", "Source", "PID", "Host", "State",
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
                dpg.add_text(row.pid)
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


def _replay_launch_callback(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        launch = replace(
            replay.launch,
            label=dpg_text_value(dpg, REPLAY_LAUNCH_LABEL_TAG, replay.launch.label),
            config_paths=tuple(
                part.strip()
                for part in dpg_text_value(dpg, REPLAY_LAUNCH_CONFIG_PATHS_TAG, ";".join(replay.launch.config_paths)).replace("\n", ";").split(";")
                if part.strip()
            ),
            config_name=dpg_text_value(dpg, REPLAY_LAUNCH_CONFIG_NAME_TAG, replay.launch.config_name),
            data_domain_id=int(float_text_value(dpg, REPLAY_LAUNCH_DATA_DOMAIN_TAG, replay.launch.data_domain_id)),
            admin_domain_id=int(float_text_value(dpg, REPLAY_LAUNCH_ADMIN_DOMAIN_TAG, replay.launch.admin_domain_id)),
            monitoring_domain_id=int(float_text_value(dpg, REPLAY_LAUNCH_MONITOR_DOMAIN_TAG, replay.launch.monitoring_domain_id)),
            database_path=dpg_text_value(dpg, REPLAY_LAUNCH_DATABASE_PATH_TAG, replay.launch.database_path),
            verbosity=dpg_text_value(dpg, REPLAY_LAUNCH_VERBOSITY_TAG, replay.launch.verbosity),
            executable=dpg_text_value(dpg, REPLAY_LAUNCH_EXECUTABLE_TAG, replay.launch.executable),
            working_dir=dpg_text_value(dpg, REPLAY_LAUNCH_WORKING_DIR_TAG, replay.launch.working_dir),
            extra_args=tuple(
                part.strip()
                for part in dpg_text_value(dpg, REPLAY_LAUNCH_EXTRA_ARGS_TAG, " ".join(replay.launch.extra_args)).split()
                if part.strip()
            ),
        )
        return command_sink(build_replay_launch_command(launch))
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
