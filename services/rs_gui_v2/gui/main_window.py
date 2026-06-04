"""Dear PyGui renderer for the rs_gui_v2 shell."""

from contextlib import nullcontext
from dataclasses import replace
import json
import re
import time
from typing import Callable, Mapping, Optional, Tuple

from app_core import AppCommand

from .tabs.convert_tab import ConvertTabViewModel, build_convert_action_command
from .tabs.plots_tab import PlotsTabViewModel
from .tabs.record_tab import (
    RecordLaunchViewModel,
    RecordTabViewModel,
    build_record_action_command,
    build_record_launch_command,
)
from .tabs.replay_tab import (
    ReplayTargetRow,
    ReplayTabViewModel,
    build_replay_action_command,
    build_replay_launch_command,
)
from .tabs.topics_tab import (
    TopicFieldRow,
    TopicRow,
    TopicsTabViewModel,
    build_topic_action_command,
    build_topic_field_command,
    build_topic_select_command,
)
from .view_models import ShellViewModel, build_empty_shell_view_model


WORKSPACE_NAME_INPUT_TAG = "rs_gui_v2_workspace_name"
WORKSPACE_PATH_INPUT_TAG = "rs_gui_v2_workspace_path"
RECORD_LAUNCH_LABEL_TAG = "rs_gui_v2_record_launch_label"
RECORD_LAUNCH_CONFIG_PATHS_TAG = "rs_gui_v2_record_launch_config_paths"
RECORD_LAUNCH_CONFIG_NAME_TAG = "rs_gui_v2_record_launch_config_name"
RECORD_LAUNCH_DATA_DOMAIN_TAG = "rs_gui_v2_record_launch_data_domain"
RECORD_LAUNCH_ADMIN_DOMAIN_TAG = "rs_gui_v2_record_launch_admin_domain"
RECORD_LAUNCH_MONITOR_DOMAIN_TAG = "rs_gui_v2_record_launch_monitor_domain"
RECORD_LAUNCH_VERBOSITY_TAG = "rs_gui_v2_record_launch_verbosity"
RECORD_LAUNCH_EXECUTABLE_TAG = "rs_gui_v2_record_launch_executable"
RECORD_LAUNCH_WORKING_DIR_TAG = "rs_gui_v2_record_launch_working_dir"
RECORD_LAUNCH_EXTRA_ARGS_TAG = "rs_gui_v2_record_launch_extra_args"
RECORD_LAUNCH_PRESET_TAG = "rs_gui_v2_record_launch_preset"
RECORD_VAR_SESSION_NAME_TAG = "rs_gui_v2_record_var_session_name"
RECORD_VAR_TOPIC_ALLOW_TAG = "rs_gui_v2_record_var_topic_allow"
RECORD_VAR_TOPIC_DENY_TAG = "rs_gui_v2_record_var_topic_deny"
RECORD_VAR_STORAGE_FORMAT_TAG = "rs_gui_v2_record_var_storage_format"
RECORD_VAR_WORKSPACE_DIR_TAG = "rs_gui_v2_record_var_workspace_dir"
RECORD_VAR_EXEC_DIR_EXPR_TAG = "rs_gui_v2_record_var_exec_dir_expr"
RECORD_VAR_FILENAME_EXPR_TAG = "rs_gui_v2_record_var_filename_expr"
RECORD_VAR_FILENAME_BASE_TAG = "rs_gui_v2_record_var_filename_base"
RECORD_VAR_STORAGE_PATH_EXPR_TAG = "rs_gui_v2_record_var_storage_path_expr"
RECORD_VAR_ROLLOVER_ENABLED_TAG = "rs_gui_v2_record_var_rollover_enabled"
RECORD_VAR_ROLLOVER_MB_TAG = "rs_gui_v2_record_var_rollover_mb"
RECORD_TAB_CONTENT_TAG = "rs_gui_v2_record_tab_content"
RECORD_TAB_DYNAMIC_TAG = "rs_gui_v2_record_tab_dynamic"
RECORD_CANDIDATE_COMBO_TAG = "rs_gui_v2_record_candidate_combo"
REPLAY_TAB_DYNAMIC_TAG = "rs_gui_v2_replay_tab_dynamic"
REPLAY_CANDIDATE_COMBO_TAG = "rs_gui_v2_replay_candidate_combo"
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
CONSOLE_OUTPUT_TAG = "rs_gui_v2_console_output"
APP_CLOSE_MODAL_TAG = "rs_gui_v2_close_modal"
APP_CLOSE_STATUS_TAG = "rs_gui_v2_close_status"
CLOSE_POLICY_NOTE_TAG = "rs_gui_v2_close_policy_note"
CLOSE_POLICY_NOTE_TEXT = "Closing this app will shut down all derived/spawned processes."
PRIMARY_BUTTON_WIDTH = 220
ACTION_BUTTON_WIDTH = 170
COMPACT_BUTTON_WIDTH = 90
DOMAIN_ID_INPUT_WIDTH = 72
STORAGE_PATH_INPUT_WIDTH = 640
FRAME_REFRESH_INTERVAL_SEC = 0.5
TIMESTAMP_DIR_EXPR = "recording_%ts%"
DEFAULT_FILENAME_BASE = "data"
AUTO_FILENAME_TOKEN = "%auto:0-9%"
TIMESTAMP_FILENAME_TOKEN = "%ts%"


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
            view_provider: Callable[[], ShellViewModel] = build_empty_shell_view_model,
            command_sink: Optional[Callable[[AppCommand], bool]] = None,
            close_handler: Optional[Callable[[str, Tuple[str, ...]], bool]] = None,
            dpg_module=None,
    ) -> None:
        self._view_provider = view_provider
        self._command_sink = command_sink
        self._close_handler = close_handler
        self._dpg = dpg_module
        self._close_handled = False
        self._exit_requested = False

    def render_once(self) -> ShellViewModel:
        """Render one snapshot into a new Dear PyGui context."""

        dpg = self._dpg or load_dearpygui()
        view = self._view_provider()
        dpg.create_context()
        try:
            render_shell_view(
                dpg,
                view,
                command_sink=self._command_sink,
            )
        finally:
            dpg.destroy_context()
        return view

    def run(self) -> None:
        """Run the interactive Dear PyGui shell."""

        dpg = self._dpg or load_dearpygui()
        dpg.create_context()
        self._close_handled = False
        self._exit_requested = False
        try:
            dpg.create_viewport(title="rs_gui_v2", width=1400, height=900, disable_close=False)
            command_sink = self._interactive_command_sink(dpg)
            close_callback = self._close_prompt_callback(dpg)
            view = self._view_provider()
            render_shell_view(dpg, view, command_sink=command_sink)
            _refresh_console_output(dpg, view)
            if self._close_handler:
                set_viewport_close_callback = getattr(dpg, "set_viewport_close_callback", None)
                if callable(set_viewport_close_callback):
                    set_viewport_close_callback(close_callback)
                set_exit_callback = getattr(dpg, "set_exit_callback", None)
                if callable(set_exit_callback):
                    set_exit_callback(self._exit_request_callback())
            dpg.setup_dearpygui()
            dpg.show_viewport()
            if _supports_frame_callbacks(dpg):
                self._schedule_frame_refresh(dpg, command_sink)
                dpg.start_dearpygui()
            elif _supports_manual_frame_loop(dpg):
                self._run_manual_frame_loop(dpg, command_sink)
            else:
                dpg.start_dearpygui()
        finally:
            try:
                self._handle_deferred_app_close()
            finally:
                dpg.destroy_context()

    def _schedule_frame_refresh(self, dpg, command_sink) -> None:
        set_frame_callback = getattr(dpg, "set_frame_callback")
        get_frame_count = getattr(dpg, "get_frame_count")
        last_refresh = {"value": 0.0}

        def _callback(_sender=None, _app_data=None, _user_data=None):
            if self._exit_requested:
                return
            try:
                now = time.monotonic()
                if now - last_refresh["value"] >= FRAME_REFRESH_INTERVAL_SEC:
                    view = self._view_provider()
                    _refresh_record_tab(dpg, view, command_sink)
                    _refresh_replay_tab(dpg, view, command_sink)
                    _refresh_console_output(dpg, view)
                    last_refresh["value"] = now
            except Exception:
                pass
            try:
                set_frame_callback(get_frame_count() + 1, _callback)
            except Exception:
                return

        set_frame_callback(get_frame_count() + 1, _callback)

    def _run_manual_frame_loop(self, dpg, command_sink) -> None:
        is_running = getattr(dpg, "is_dearpygui_running")
        render_frame = getattr(dpg, "render_dearpygui_frame")
        last_refresh = 0.0
        while is_running():
            now = time.monotonic()
            if now - last_refresh >= FRAME_REFRESH_INTERVAL_SEC:
                try:
                    view = self._view_provider()
                    _refresh_record_tab(dpg, view, command_sink)
                    _refresh_replay_tab(dpg, view, command_sink)
                    _refresh_console_output(dpg, view)
                    last_refresh = now
                except Exception:
                    last_refresh = now
            render_frame()

    def _interactive_command_sink(self, dpg):
        if self._command_sink is None:
            return None

        def _sink(command: AppCommand) -> bool:
            accepted = self._command_sink(command)
            view = self._view_provider()
            _refresh_record_tab(dpg, view, _sink)
            _refresh_replay_tab(dpg, view, _sink)
            _refresh_console_output(dpg, view)
            return accepted
        return _sink

    def _close_prompt_callback(self, dpg):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            if self._close_handler is None:
                stop = getattr(dpg, "stop_dearpygui", None)
                if callable(stop):
                    stop()
                return True
            view = self._view_provider()
            close_items = _close_process_items(view)
            if not any(item.get("active") for item in close_items):
                if self._handle_close_action("leave_running", ()):
                    stop = getattr(dpg, "stop_dearpygui", None)
                    if callable(stop):
                        stop()
                    return True
                return False
            _show_close_prompt(dpg, view, self._handle_close_action)
            return False
        return _callback

    def _exit_cleanup_callback(self):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            if self._close_handler is None:
                return True
            if self._close_handled:
                return True
            action, item_ids = _default_close_policy(self._view_provider())
            self._handle_close_action(action, item_ids)
            return True
        return _callback

    def _exit_request_callback(self):
        def _callback(_sender=None, _app_data=None, _user_data=None):
            self._exit_requested = True
            return True
        return _callback

    def _handle_deferred_app_close(self) -> None:
        if self._close_handler is None or self._close_handled:
            return
        action, item_ids = _default_close_policy(self._view_provider())
        self._handle_close_action(action, item_ids)

    def _handle_close_action(self, action: str, item_ids: Tuple[str, ...]) -> bool:
        if self._close_handler is None:
            return True
        if self._close_handled:
            return True
        result = self._close_handler(action, tuple(item_ids))
        if result is False:
            return False
        self._close_handled = True
        return True


def render_shell_view(
        dpg,
        view: ShellViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Render the first rs_gui_v2 shell snapshot with Dear PyGui calls."""

    _apply_button_theme_if_supported(dpg)
    with dpg.window(label=view.title, tag="rs_gui_v2_main_window", width=1380, height=860, no_close=True):
        with dpg.tab_bar(tag="rs_gui_v2_tabs"):
            with dpg.tab(label="Record"):
                with dpg.group(tag=RECORD_TAB_CONTENT_TAG):
                    _render_record_tab(
                        dpg,
                        view.record_tab,
                        command_sink=command_sink,
                        status_items=view.status_items,
                    )
            with dpg.tab(label="Replay"):
                _render_replay_tab(dpg, view.replay_tab, command_sink=command_sink)
            with dpg.tab(label="Convert"):
                _render_convert_tab(dpg, view.convert_tab, command_sink=command_sink)
            # Topics and Plots tabs moved to standalone rti_view project
            # with dpg.tab(label="Topics"):
            #     _render_topics_tab(dpg, view.topics_tab, command_sink=command_sink)
            # with dpg.tab(label="Plots"):
            #     _render_plots_tab(dpg, view.plots_tab)
            with dpg.tab(label="Workspace"):
                _render_workspace_tab(dpg, view, command_sink=command_sink)
            with dpg.tab(label="Console"):
                _render_console_tab(dpg, view)
        dpg.add_separator()
        dpg.add_text(CLOSE_POLICY_NOTE_TEXT, tag=CLOSE_POLICY_NOTE_TAG)


def _show_close_prompt(
        dpg,
        view: ShellViewModel,
        close_handler: Callable[[str, Tuple[str, ...]], bool],
) -> None:
    delete_item = getattr(dpg, "delete_item", None)
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if callable(delete_item) and callable(does_item_exist):
        try:
            if does_item_exist(APP_CLOSE_MODAL_TAG):
                delete_item(APP_CLOSE_MODAL_TAG)
        except Exception:
            pass

    close_items = _close_process_items(view)
    gui_owned_item_ids = tuple(item["item_id"] for item in close_items if item.get("owned") and item.get("active"))
    with dpg.window(
            label="Close rs_gui_v2",
            tag=APP_CLOSE_MODAL_TAG,
            modal=True,
            show=True,
            no_close=True,
            width=720,
            height=360,
    ):
        dpg.add_text("Detected RTI service processes")
        if close_items:
            for item in close_items:
                dpg.add_text(_close_process_item_text(item))
        else:
            dpg.add_text("No Recording Service or Converter processes are currently detected by this GUI.")
        dpg.add_separator()
        dpg.add_text("", tag=APP_CLOSE_STATUS_TAG)
        with dpg.group(horizontal=True):
            _add_action_button(
                dpg,
                label="Leave Running",
                callback=_close_dialog_action_callback(dpg, close_handler, "leave_running", ()),
                width=ACTION_BUTTON_WIDTH,
            )
            _add_action_button(
                dpg,
                label="Shutdown GUI-Launched",
                enabled=bool(gui_owned_item_ids),
                callback=_close_dialog_action_callback(dpg, close_handler, "shutdown_gui_launched", gui_owned_item_ids),
                width=PRIMARY_BUTTON_WIDTH,
            )
            _add_action_button(
                dpg,
                label="Cancel",
                callback=_close_dialog_cancel_callback(dpg),
                width=COMPACT_BUTTON_WIDTH,
            )


def _close_process_items(view: ShellViewModel) -> Tuple[Mapping[str, object], ...]:
    items = []
    for row in view.record_tab.candidates:
        active = str(row.state).lower() not in ("exited", "start_failed", "stopped", "shutdown")
        items.append({
            "item_id": f"record:{row.candidate_id}",
            "kind": "Recording Service",
            "name": row.control_name,
            "source": row.source,
            "pid": row.pid,
            "hostname": row.hostname,
            "state": row.state,
            "owned": bool(row.owned),
            "active": active,
        })
    convert = view.convert_tab
    replay = view.replay_tab
    if replay is not None:
        for row in replay.targets:
            active = str(row.state).lower() not in ("exited", "start_failed", "stopped", "shutdown")
            items.append({
                "item_id": f"replay:{row.candidate_id}",
                "kind": "Replay Service",
                "name": row.control_name,
                "source": row.source,
                "pid": row.pid,
                "hostname": row.hostname,
                "state": row.state,
                "owned": bool(row.owned),
                "active": active,
            })
    if convert is not None:
        for job in convert.jobs:
            active = str(job.state).lower() in ("queued", "starting", "running", "cancel_requested")
            if not active:
                continue
            items.append({
                "item_id": f"convert:{job.job_id}",
                "kind": "Converter Job",
                "name": job.job_id,
                "source": "gui_launch",
                "pid": "",
                "hostname": "",
                "state": job.state,
                "owned": True,
                "active": True,
            })
    return tuple(items)


def _default_close_policy(view: ShellViewModel) -> Tuple[str, Tuple[str, ...]]:
    close_items = _close_process_items(view)
    gui_owned_item_ids = tuple(
        str(item["item_id"])
        for item in close_items
        if item.get("owned") and item.get("active")
    )
    if gui_owned_item_ids:
        return "shutdown_gui_launched", gui_owned_item_ids
    return "leave_running", ()


def _close_process_item_text(item: Mapping[str, object]) -> str:
    ownership = "launched by this GUI" if item.get("owned") else "detected externally"
    pid = str(item.get("pid", "")).strip() or "unknown pid"
    hostname = str(item.get("hostname", "")).strip()
    location = f" on {hostname}" if hostname else ""
    state = str(item.get("state", "unknown"))
    name = str(item.get("name", "")) or str(item.get("item_id", ""))
    return f"{item.get('kind')}: {name} | {ownership} | {pid}{location} | {state}"


def _close_dialog_action_callback(
        dpg,
        close_handler: Callable[[str, Tuple[str, ...]], bool],
        action: str,
        item_ids: Tuple[str, ...],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        _set_close_status(dpg, _close_action_status(action))
        _render_one_frame_if_possible(dpg)
        if close_handler(action, tuple(item_ids)):
            _set_close_status(dpg, "Cleanup complete. Closing...")
            _render_one_frame_if_possible(dpg)
            stop = getattr(dpg, "stop_dearpygui", None)
            if callable(stop):
                stop()
            return True
        _set_close_status(dpg, "Close canceled or failed.")
        return False
    return _callback


def _close_action_status(action: str) -> str:
    if action == "shutdown_gui_launched":
        return "Shutting down GUI-launched services..."
    if action == "leave_running":
        return "Leaving detected services running..."
    return "Closing..."


def _set_close_status(dpg, message: str) -> None:
    set_value = getattr(dpg, "set_value", None)
    if callable(set_value):
        try:
            set_value(APP_CLOSE_STATUS_TAG, str(message))
        except Exception:
            pass


def _render_one_frame_if_possible(dpg) -> None:
    render_frame = getattr(dpg, "render_dearpygui_frame", None)
    if callable(render_frame):
        try:
            render_frame()
        except Exception:
            pass


def _close_dialog_cancel_callback(dpg):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        delete_item = getattr(dpg, "delete_item", None)
        if callable(delete_item):
            try:
                delete_item(APP_CLOSE_MODAL_TAG)
            except Exception:
                pass
        return False
    return _callback


def _refresh_record_tab(
        dpg,
        view: ShellViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    if not _has_item(dpg, RECORD_TAB_DYNAMIC_TAG):
        return
    delete_item = getattr(dpg, "delete_item", None)
    push_container_stack = getattr(dpg, "push_container_stack", None)
    pop_container_stack = getattr(dpg, "pop_container_stack", None)
    if not (callable(delete_item) and callable(push_container_stack) and callable(pop_container_stack)):
        _refresh_record_candidate_combo(dpg, view)
        return
    try:
        delete_item(RECORD_TAB_DYNAMIC_TAG, children_only=True)
        push_container_stack(RECORD_TAB_DYNAMIC_TAG)
        try:
            _render_record_dynamic_section(
                dpg,
                view.record_tab,
                command_sink=command_sink,
                status_items=view.status_items,
            )
        finally:
            pop_container_stack()
    except Exception:
        _refresh_record_candidate_combo(dpg, view)


def _refresh_record_candidate_combo(dpg, view: ShellViewModel) -> None:
    if not _has_item(dpg, RECORD_CANDIDATE_COMBO_TAG):
        return
    configure_item = getattr(dpg, "configure_item", None)
    set_value = getattr(dpg, "set_value", None)
    if not (callable(configure_item) and callable(set_value)):
        return
    labels = _record_candidate_labels(view.record_tab)
    selected = _selected_record_candidate_label(view.record_tab, labels)
    try:
        configure_item(RECORD_CANDIDATE_COMBO_TAG, items=labels)
        set_value(RECORD_CANDIDATE_COMBO_TAG, selected)
    except Exception:
        return


def _refresh_replay_tab(
        dpg,
        view: ShellViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    if not _has_item(dpg, REPLAY_TAB_DYNAMIC_TAG):
        return
    delete_item = getattr(dpg, "delete_item", None)
    push_container_stack = getattr(dpg, "push_container_stack", None)
    pop_container_stack = getattr(dpg, "pop_container_stack", None)
    if not (callable(delete_item) and callable(push_container_stack) and callable(pop_container_stack)):
        _refresh_replay_candidate_combo(dpg, view)
        return
    try:
        delete_item(REPLAY_TAB_DYNAMIC_TAG, children_only=True)
        push_container_stack(REPLAY_TAB_DYNAMIC_TAG)
        try:
            replay = _replay_view_from_inputs(dpg, view.replay_tab)
            _render_replay_dynamic_section(dpg, replay, command_sink=command_sink)
        finally:
            pop_container_stack()
    except Exception:
        _refresh_replay_candidate_combo(dpg, view)


def _refresh_replay_candidate_combo(dpg, view: ShellViewModel) -> None:
    if not _has_item(dpg, REPLAY_CANDIDATE_COMBO_TAG):
        return
    configure_item = getattr(dpg, "configure_item", None)
    set_value = getattr(dpg, "set_value", None)
    if not (callable(configure_item) and callable(set_value)):
        return
    labels = _replay_candidate_labels(view.replay_tab)
    selected = _selected_replay_target_label(view.replay_tab, labels)
    try:
        configure_item(REPLAY_CANDIDATE_COMBO_TAG, items=labels)
        set_value(REPLAY_CANDIDATE_COMBO_TAG, selected)
    except Exception:
        return


def _has_item(dpg, tag: str) -> bool:
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if callable(does_item_exist):
        try:
            return bool(does_item_exist(tag))
        except Exception:
            return False
    return False


def _supports_manual_frame_loop(dpg) -> bool:
    return callable(getattr(dpg, "is_dearpygui_running", None)) and callable(
        getattr(dpg, "render_dearpygui_frame", None)
    )


def _supports_frame_callbacks(dpg) -> bool:
    return callable(getattr(dpg, "set_frame_callback", None)) and callable(
        getattr(dpg, "get_frame_count", None)
    )


def _record_candidate_labels(record: RecordTabViewModel):
    return [row.control_name for row in record.candidates] or ["No Recording Service"]


def _selected_record_candidate_label(record: RecordTabViewModel, labels):
    return record.selected_candidate.control_name if record.selected_candidate else labels[0]


def _replay_candidate_labels(replay: ReplayTabViewModel):
    return [_replay_candidate_label(row) for row in replay.targets] or ["No Replay Service"]


def _selected_replay_target_label(replay: ReplayTabViewModel, labels):
    return _replay_candidate_label(replay.selected_target) if replay.selected_target else labels[0]


def _replay_candidate_label(row: Optional[ReplayTargetRow]) -> str:
    if row is None:
        return "No Replay Service"
    pid = row.pid or "no pid"
    host = row.hostname or "unknown host"
    return f"{row.control_name} | {row.source} | {pid} | {host}"


def _render_record_tab(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
    status_items: Tuple[object, ...] = (),
) -> None:
    _render_record_launch_controls(dpg, record, command_sink=command_sink)
    dpg.add_separator()
    with dpg.group(tag=RECORD_TAB_DYNAMIC_TAG):
        _render_record_dynamic_section(dpg, record, command_sink=command_sink, status_items=status_items)


def _render_record_dynamic_section(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
        status_items: Tuple[object, ...] = (),
) -> None:
    dpg.add_text(f"Recording target: {record.target_label}")
    dpg.add_text(
        f"Readiness: {record.readiness} | State: {record.observed_state} | "
        f"Admin domain: {record.admin_domain} | Monitoring domain: {record.monitoring_domain}"
    )
    labels = _record_candidate_labels(record)
    default_value = _selected_record_candidate_label(record, labels)
    dpg.add_text("Candidate")
    dpg.add_combo(
        labels,
        default_value=default_value,
        label="##record_candidate_combo",
        tag=RECORD_CANDIDATE_COMBO_TAG,
    )
    _render_candidate_table(dpg, record)
    _render_record_actions(dpg, record, command_sink=command_sink)
    _render_record_details(dpg, record, status_items=status_items)


def _render_record_launch_controls(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    launch = record.launch
    preset_options = ("record_selected", "record_all", "record_json")
    default_preset = launch.config_name if launch.config_name in preset_options else "record_selected"
    default_session = _record_var_from_extra_args(
        launch.extra_args,
        "REC_SESSION_NAME",
        _safe_record_session_name(launch.label or "recording_session"),
    )
    default_topic_allow = _record_var_from_extra_args(launch.extra_args, "REC_TOPIC_ALLOW", "*")
    default_topic_deny = _record_var_from_extra_args(launch.extra_args, "REC_TOPIC_DENY", "rti/*")
    default_storage_format = _record_var_from_extra_args(
        launch.extra_args,
        "REC_STORAGE_FORMAT",
        _default_storage_for_config(default_preset),
    )
    default_workspace_dir = _record_var_from_extra_args(launch.extra_args, "REC_WORKSPACE_DIR", "log_dir")
    default_exec_dir_expr = _record_var_from_extra_args(launch.extra_args, "REC_EXEC_DIR_EXPR", TIMESTAMP_DIR_EXPR)
    default_filename_expr = _record_var_from_extra_args(
        launch.extra_args,
        "REC_FILENAME_EXPR",
        _record_filename_expression_from_base(DEFAULT_FILENAME_BASE),
    )
    default_filename_base = _record_filename_base_from_expression(default_filename_expr, DEFAULT_FILENAME_BASE)
    default_rollover_enabled = _record_var_from_extra_args(launch.extra_args, "REC_ROLLOVER_ENABLED", "false")
    default_rollover_mb = _record_var_from_extra_args(launch.extra_args, "REC_ROLLOVER_MB", "1024")
    dpg.add_text("Launch Recording Service")
    dpg.add_text("Variable Preset")
    dpg.add_combo(
        preset_options,
        default_value=default_preset,
        label=f"##{RECORD_LAUNCH_PRESET_TAG}",
        callback=_record_preset_callback(dpg),
    )
    dpg.add_text("Config Files: managed by default launch profile")
    dpg.add_text(" ; ".join(launch.config_paths))
    if launch.available_config_names:
        dpg.add_text(f"Available configs: {', '.join(launch.available_config_names)}")
    _add_labeled_input_text(
        dpg,
        "Config Name",
        f"##{RECORD_LAUNCH_CONFIG_NAME_TAG}",
        default_value=default_preset,
        tag=RECORD_LAUNCH_CONFIG_NAME_TAG,
    )
    dpg.add_text("Domain IDs")
    with dpg.group(horizontal=True):
        _add_labeled_input_text(
            dpg,
            "Data Domain ID",
            f"##{RECORD_LAUNCH_DATA_DOMAIN_TAG}",
            default_value=str(launch.data_domain_id),
            tag=RECORD_LAUNCH_DATA_DOMAIN_TAG,
            width=DOMAIN_ID_INPUT_WIDTH,
        )
        _add_labeled_input_text(
            dpg,
            "Admin Domain ID",
            f"##{RECORD_LAUNCH_ADMIN_DOMAIN_TAG}",
            default_value=str(launch.admin_domain_id),
            tag=RECORD_LAUNCH_ADMIN_DOMAIN_TAG,
            width=DOMAIN_ID_INPUT_WIDTH,
        )
        _add_labeled_input_text(
            dpg,
            "Monitoring Domain ID",
            f"##{RECORD_LAUNCH_MONITOR_DOMAIN_TAG}",
            default_value=str(launch.monitoring_domain_id),
            tag=RECORD_LAUNCH_MONITOR_DOMAIN_TAG,
            width=DOMAIN_ID_INPUT_WIDTH,
        )
    with _collapsible_section(dpg, "Template Variables (REC_*)", default_open=True):
        _add_labeled_input_text(
            dpg,
            "REC_SESSION_NAME",
            f"##{RECORD_VAR_SESSION_NAME_TAG}",
            default_value=default_session,
            tag=RECORD_VAR_SESSION_NAME_TAG,
        )
        _add_labeled_input_text(
            dpg,
            "REC_TOPIC_ALLOW",
            f"##{RECORD_VAR_TOPIC_ALLOW_TAG}",
            default_value=default_topic_allow,
            tag=RECORD_VAR_TOPIC_ALLOW_TAG,
        )
        _add_labeled_input_text(
            dpg,
            "REC_TOPIC_DENY",
            f"##{RECORD_VAR_TOPIC_DENY_TAG}",
            default_value=default_topic_deny,
            tag=RECORD_VAR_TOPIC_DENY_TAG,
        )
        _add_labeled_input_text(
            dpg,
            "REC_STORAGE_FORMAT",
            f"##{RECORD_VAR_STORAGE_FORMAT_TAG}",
            default_value=default_storage_format,
            tag=RECORD_VAR_STORAGE_FORMAT_TAG,
        )
    with _collapsible_section(dpg, "Advanced Launch Fields", default_open=False):
        dpg.add_text("Storage Naming")
        with dpg.group(horizontal=True):
            _add_labeled_input_text(
                dpg,
                "Output Root Directory",
                f"##{RECORD_VAR_WORKSPACE_DIR_TAG}",
                default_value=default_workspace_dir,
                tag=RECORD_VAR_WORKSPACE_DIR_TAG,
                callback=_record_storage_path_preview_callback(dpg),
            )
            _add_labeled_input_text(
                dpg,
                "Execution Subdirectory",
                f"##{RECORD_VAR_EXEC_DIR_EXPR_TAG}",
                default_value=default_exec_dir_expr,
                tag=RECORD_VAR_EXEC_DIR_EXPR_TAG,
                callback=_record_storage_path_preview_callback(dpg),
            )
        with dpg.group(horizontal=True):
            _add_labeled_input_text(
                dpg,
                "File Name",
                f"##{RECORD_VAR_FILENAME_BASE_TAG}",
                default_value=default_filename_base,
                tag=RECORD_VAR_FILENAME_BASE_TAG,
                callback=_record_filename_base_callback(dpg),
            )
            _add_labeled_input_text(
                dpg,
                "Filename Template",
                f"##{RECORD_VAR_FILENAME_EXPR_TAG}",
                default_value=default_filename_expr,
                tag=RECORD_VAR_FILENAME_EXPR_TAG,
                callback=_record_storage_path_preview_callback(dpg),
            )
        _add_labeled_input_text(
            dpg,
            "Derived Storage Expression",
            f"##{RECORD_VAR_STORAGE_PATH_EXPR_TAG}",
            default_value=_record_storage_path_expression(
                default_workspace_dir,
                default_exec_dir_expr,
                default_filename_expr,
            ),
            tag=RECORD_VAR_STORAGE_PATH_EXPR_TAG,
            width=STORAGE_PATH_INPUT_WIDTH,
            readonly=True,
        )
        with dpg.group(horizontal=True):
            _add_labeled_checkbox(
                dpg,
                "Enable Rollover",
                default_value=_boolean_text(default_rollover_enabled) == "true",
                tag=RECORD_VAR_ROLLOVER_ENABLED_TAG,
            )
            _add_labeled_input_text(
                dpg,
                "Rollover Size MB",
                f"##{RECORD_VAR_ROLLOVER_MB_TAG}",
                default_value=default_rollover_mb,
                tag=RECORD_VAR_ROLLOVER_MB_TAG,
            )
        with dpg.group(horizontal=True):
            _add_labeled_input_text(
                dpg,
                "Logging Verbosity",
                f"##{RECORD_LAUNCH_VERBOSITY_TAG}",
                default_value=launch.verbosity,
                tag=RECORD_LAUNCH_VERBOSITY_TAG,
            )
        with dpg.group(horizontal=True):
            _add_labeled_input_text(
                dpg,
                "Executable Path",
                f"##{RECORD_LAUNCH_EXECUTABLE_TAG}",
                default_value=launch.executable,
                tag=RECORD_LAUNCH_EXECUTABLE_TAG,
            )
            _add_labeled_input_text(
                dpg,
                "Working Directory",
                f"##{RECORD_LAUNCH_WORKING_DIR_TAG}",
                default_value=launch.working_dir,
                tag=RECORD_LAUNCH_WORKING_DIR_TAG,
            )
        _add_labeled_input_text(
            dpg,
            "Extra Launch Args",
            f"##{RECORD_LAUNCH_EXTRA_ARGS_TAG}",
            default_value=" ".join(launch.extra_args),
            tag=RECORD_LAUNCH_EXTRA_ARGS_TAG,
        )
    with _collapsible_section(dpg, "Command Preview", default_open=False):
        dpg.add_text(launch.command_preview)
    _add_action_button(
        dpg,
        label="Launch Recording Service",
        enabled=launch.enabled,
        callback=_record_launch_callback(dpg, record, command_sink),
        width=PRIMARY_BUTTON_WIDTH,
    )
    if launch.disabled_reason:
        dpg.add_text(launch.disabled_reason)


def _render_candidate_table(dpg, record: RecordTabViewModel) -> None:
    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True, borders_innerV=True):
        for heading in ("Selected", "Control Name", "Source", "Host", "PID", "State", "Current File", "Age", "Confidence"):
            dpg.add_table_column(label=heading)
        for row in record.candidates:
            with dpg.table_row():
                dpg.add_text("*" if row.selected else "")
                dpg.add_text(row.control_name)
                dpg.add_text(row.source)
                dpg.add_text(row.hostname)
                dpg.add_text(row.pid)
                dpg.add_text(row.state)
                dpg.add_text(row.current_file)
                dpg.add_text(row.age)
                dpg.add_text(row.confidence)


def _render_record_actions(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    with dpg.group(horizontal=True):
        for action in record.actions:
            _add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_record_action_callback(record, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
            )
    _add_labeled_input_text(dpg, "Command Tag", "##record_command_tag", default_value=record.tag_value)


def _render_record_details(
        dpg,
        record: RecordTabViewModel,
        status_items: Tuple[object, ...] = (),
) -> None:
    if not (record.diagnostics or record.command_history or record.monitoring_summary or status_items):
        return
    label = "Record Details"
    if record.diagnostics:
        label = f"Record Details ({len(record.diagnostics)} diagnostics)"
    with _collapsible_section(dpg, label, default_open=False):
        if status_items:
            _render_debug_status(dpg, status_items)
        if record.diagnostics:
            dpg.add_text("Diagnostics")
            for diagnostic in record.diagnostics:
                dpg.add_text(f"Diagnostic: {diagnostic}")
        if record.command_history:
            _render_command_history(dpg, record)
        if record.monitoring_summary:
            _render_monitoring_summary(dpg, record)


def _render_debug_status(dpg, status_items: Tuple[object, ...]) -> None:
    dpg.add_text("Debug")
    for item in status_items:
        label = str(getattr(item, "label", ""))
        value = str(getattr(item, "value", ""))
        if label:
            dpg.add_text(f"{label}: {value}")


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


def _record_launch_callback(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        if command_sink is None:
            return False
        config_name = _dpg_text_value(dpg, RECORD_LAUNCH_CONFIG_NAME_TAG, record.launch.config_name)
        data_domain_id = _int_text_value(dpg, RECORD_LAUNCH_DATA_DOMAIN_TAG, record.launch.data_domain_id)
        admin_domain_id = _int_text_value(dpg, RECORD_LAUNCH_ADMIN_DOMAIN_TAG, record.launch.admin_domain_id)
        monitoring_domain_id = _int_text_value(dpg, RECORD_LAUNCH_MONITOR_DOMAIN_TAG, record.launch.monitoring_domain_id)
        raw_extra_args = _extra_args_from_text(
            _dpg_text_value(dpg, RECORD_LAUNCH_EXTRA_ARGS_TAG, " ".join(record.launch.extra_args))
        )
        managed_var_args = _record_variable_args(
            data_domain_id=data_domain_id,
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=monitoring_domain_id,
            session_name=_dpg_text_value(dpg, RECORD_VAR_SESSION_NAME_TAG, record.launch.label),
            topic_allow=_dpg_text_value(dpg, RECORD_VAR_TOPIC_ALLOW_TAG, "*"),
            topic_deny=_dpg_text_value(dpg, RECORD_VAR_TOPIC_DENY_TAG, "rti/*"),
            storage_format=_dpg_text_value(
                dpg,
                RECORD_VAR_STORAGE_FORMAT_TAG,
                _default_storage_for_config(config_name),
            ),
            workspace_dir=_dpg_text_value(dpg, RECORD_VAR_WORKSPACE_DIR_TAG, "log_dir"),
            exec_dir_expr=_dpg_text_value(dpg, RECORD_VAR_EXEC_DIR_EXPR_TAG, "recording_%ts%"),
            filename_expr=_dpg_text_value(dpg, RECORD_VAR_FILENAME_EXPR_TAG, "data_%auto:0-9%.db"),
            rollover_enabled=_dpg_text_value(dpg, RECORD_VAR_ROLLOVER_ENABLED_TAG, "false"),
            rollover_mb=_dpg_text_value(dpg, RECORD_VAR_ROLLOVER_MB_TAG, "1024"),
        )
        launch = RecordLaunchViewModel(
            label=_dpg_text_value(dpg, RECORD_LAUNCH_LABEL_TAG, record.launch.label),
            config_paths=_config_paths_from_text(
                _dpg_text_value(dpg, RECORD_LAUNCH_CONFIG_PATHS_TAG, ";".join(record.launch.config_paths))
            ),
            available_config_names=record.launch.available_config_names,
            config_name=config_name,
            data_domain_id=data_domain_id,
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=monitoring_domain_id,
            verbosity=_dpg_text_value(dpg, RECORD_LAUNCH_VERBOSITY_TAG, record.launch.verbosity),
            executable=_dpg_text_value(dpg, RECORD_LAUNCH_EXECUTABLE_TAG, record.launch.executable),
            working_dir=_dpg_text_value(dpg, RECORD_LAUNCH_WORKING_DIR_TAG, record.launch.working_dir),
            extra_args=_merge_record_variable_args(raw_extra_args, managed_var_args),
        )
        return command_sink(build_record_launch_command(launch))
    return _callback


def _record_preset_callback(dpg):
    def _callback(_sender=None, app_data=None, _user_data=None):
        if app_data is None:
            return False
        preset = str(app_data)
        set_value = getattr(dpg, "set_value", None)
        if not callable(set_value):
            return False
        set_value(RECORD_LAUNCH_CONFIG_NAME_TAG, preset)
        set_value(RECORD_VAR_STORAGE_FORMAT_TAG, _default_storage_for_config(preset))
        if preset == "record_selected":
            set_value(RECORD_VAR_TOPIC_ALLOW_TAG, "Telemetry*")
            set_value(RECORD_VAR_TOPIC_DENY_TAG, "rti/*")
        elif preset in ("record_all", "record_json"):
            set_value(RECORD_VAR_TOPIC_ALLOW_TAG, "*")
            set_value(RECORD_VAR_TOPIC_DENY_TAG, "rti/*")
        return True
    return _callback


def _record_filename_base_callback(dpg):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        set_value = getattr(dpg, "set_value", None)
        if not callable(set_value):
            return False
        set_value(
            RECORD_VAR_FILENAME_EXPR_TAG,
            _record_filename_expression_from_base(
                _dpg_text_value(dpg, RECORD_VAR_FILENAME_BASE_TAG, DEFAULT_FILENAME_BASE),
            ),
        )
        return _update_record_storage_path_preview(dpg)
    return _callback


def _record_storage_path_preview_callback(dpg):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        return _update_record_storage_path_preview(dpg)
    return _callback


def _update_record_storage_path_preview(dpg) -> bool:
    set_value = getattr(dpg, "set_value", None)
    if not callable(set_value):
        return False
    set_value(
        RECORD_VAR_STORAGE_PATH_EXPR_TAG,
        _record_storage_path_expression(
            _dpg_text_value(dpg, RECORD_VAR_WORKSPACE_DIR_TAG, "log_dir"),
            _dpg_text_value(dpg, RECORD_VAR_EXEC_DIR_EXPR_TAG, TIMESTAMP_DIR_EXPR),
            _dpg_text_value(
                dpg,
                RECORD_VAR_FILENAME_EXPR_TAG,
                _record_filename_expression_from_base(DEFAULT_FILENAME_BASE),
            ),
        ),
    )
    return True


def _record_storage_path_expression(workspace_dir: str, exec_dir_expr: str, filename_expr: str) -> str:
    workspace = str(workspace_dir).strip().rstrip("/")
    exec_dir = str(exec_dir_expr).strip().strip("/")
    filename = str(filename_expr).strip().strip("/")
    path = workspace
    if exec_dir:
        path = f"{path}/{exec_dir}" if path else exec_dir
    if filename:
        path = f"{path}/{filename}" if path else filename
    return path


def _record_filename_expression_from_base(filename_base: str, include_timestamp: bool = False) -> str:
    base = _safe_record_filename_base(filename_base)
    if include_timestamp:
        return f"{base}_{TIMESTAMP_FILENAME_TOKEN}_{AUTO_FILENAME_TOKEN}.db"
    return f"{base}_{AUTO_FILENAME_TOKEN}.db"


def _record_filename_base_from_expression(filename_expr: str, default: str = DEFAULT_FILENAME_BASE) -> str:
    value = str(filename_expr).strip()
    if value.lower().endswith(".db"):
        value = value[:-3]
    value = value.replace(AUTO_FILENAME_TOKEN, "")
    value = value.replace(TIMESTAMP_FILENAME_TOKEN, "")
    value = value.strip("_.- ")
    return _safe_record_filename_base(value or default)


def _safe_record_filename_base(filename_base: str) -> str:
    value = str(filename_base).strip()
    if value.lower().endswith(".db"):
        value = value[:-3]
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.-")
    return value or DEFAULT_FILENAME_BASE


def _dpg_text_value(dpg, tag: str, default: str = "") -> str:
    try:
        value = dpg.get_value(tag)
    except Exception:
        return str(default)
    if value is None:
        return str(default)
    return str(value)


def _int_text_value(dpg, tag: str, default: int = 0) -> int:
    value = _dpg_text_value(dpg, tag, str(default)).strip()
    return int(value or default)


def _float_text_value(dpg, tag: str, default: float = 0.0) -> float:
    value = _dpg_text_value(dpg, tag, str(default)).strip()
    return float(value or default)


def _config_paths_from_text(value: str):
    return tuple(part.strip() for part in value.replace("\n", ";").split(";") if part.strip())


def _extra_args_from_text(value: str):
    return tuple(part.strip() for part in value.split() if part.strip())


def _default_storage_for_config(config_name: str) -> str:
    return "JSON_SQLITE" if str(config_name).strip() == "record_json" else "XCDR_AUTO"


def _record_var_from_extra_args(extra_args, var_name: str, default: str = "") -> str:
    prefix = f"-D{var_name}="
    for arg in extra_args or ():
        token = str(arg).strip()
        if token.startswith(prefix):
            return token[len(prefix):]
    return str(default)


def _record_variable_args(
        data_domain_id: int,
        admin_domain_id: int,
        monitoring_domain_id: int,
        session_name: str,
        topic_allow: str,
        topic_deny: str,
        storage_format: str,
        workspace_dir: str,
        exec_dir_expr: str,
        filename_expr: str,
        rollover_enabled: str,
        rollover_mb: str,
):
    return (
        f"-DREC_DOMAIN_ID={int(data_domain_id)}",
        f"-DREC_ADMIN_DOMAIN_ID={int(admin_domain_id)}",
        f"-DREC_MON_DOMAIN_ID={int(monitoring_domain_id)}",
        "-DREC_STATUS_PERIOD_SEC=0",
        "-DREC_STATUS_PERIOD_NSEC=500000000",
        f"-DREC_SESSION_NAME={_safe_record_session_name(session_name)}",
        f"-DREC_TOPIC_ALLOW={str(topic_allow).strip()}",
        f"-DREC_TOPIC_DENY={str(topic_deny).strip()}",
        f"-DREC_STORAGE_FORMAT={str(storage_format).strip()}",
        f"-DREC_WORKSPACE_DIR={str(workspace_dir).strip()}",
        f"-DREC_EXEC_DIR_EXPR={str(exec_dir_expr).strip()}",
        f"-DREC_FILENAME_EXPR={str(filename_expr).strip()}",
        f"-DREC_ROLLOVER_ENABLED={_boolean_text(rollover_enabled)}",
        f"-DREC_ROLLOVER_MB={max(1, int(str(rollover_mb).strip() or 1))}",
    )


def _merge_record_variable_args(existing_args, managed_args):
    managed_names = (
        "REC_DOMAIN_ID",
        "REC_ADMIN_DOMAIN_ID",
        "REC_MON_DOMAIN_ID",
        "REC_STATUS_PERIOD_SEC",
        "REC_STATUS_PERIOD_NSEC",
        "REC_SESSION_NAME",
        "REC_TOPIC_ALLOW",
        "REC_TOPIC_DENY",
        "REC_STORAGE_FORMAT",
        "REC_WORKSPACE_DIR",
        "REC_EXEC_DIR_EXPR",
        "REC_FILENAME_EXPR",
        "REC_ROLLOVER_ENABLED",
        "REC_ROLLOVER_MB",
    )
    managed_prefixes = tuple(f"-D{name}=" for name in managed_names)
    retained = tuple(
        arg for arg in existing_args
        if not str(arg).strip().startswith(managed_prefixes)
    )
    return retained + tuple(arg for arg in managed_args if str(arg).strip())


def _safe_record_session_name(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "recording_session"


def _boolean_text(value: str) -> str:
    return "true" if str(value).strip().lower() in ("1", "true", "yes", "on", "enabled") else "false"


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
    _add_labeled_input_text(dpg, "Converter Config File", "##convert_config_file", default_value=convert.config_file)
    _add_labeled_input_text(dpg, "Input Storage Path", "##convert_input_storage", default_value=convert.input_storage.path)
    _add_labeled_input_text(dpg, "Output Storage Path", "##convert_output_storage", default_value=convert.output_storage.path)
    _add_labeled_input_text(dpg, "Data Selection Expression", "##convert_data_selection", default_value=convert.data_selection)
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
            _add_action_button(
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


def _render_replay_tab(
        dpg,
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    _render_replay_launch(dpg, replay, command_sink=command_sink)
    dpg.add_separator()
    with dpg.group(tag=REPLAY_TAB_DYNAMIC_TAG):
        _render_replay_dynamic_section(dpg, replay, command_sink=command_sink)


def _render_replay_dynamic_section(
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
    _add_labeled_input_text(
        dpg,
        "Recording DB Path",
        f"##{REPLAY_DATABASE_PATH_TAG}",
        default_value=replay.database_path,
        tag=REPLAY_DATABASE_PATH_TAG,
    )
    _add_labeled_input_text(
        dpg,
        "Playback Rate (x)",
        f"##{REPLAY_PLAYBACK_RATE_TAG}",
        default_value=f"{replay.playback_rate:g}",
        tag=REPLAY_PLAYBACK_RATE_TAG,
    )
    _add_labeled_input_text(
        dpg,
        "Time Window [start,end]",
        f"##{REPLAY_TIME_WINDOW_TAG}",
        default_value=replay.time_window,
        tag=REPLAY_TIME_WINDOW_TAG,
    )
    with _collapsible_section(dpg, "Replay QoS Overrides", default_open=False):
        _add_labeled_input_text(
            dpg,
            "QoS XML Path",
            f"##{REPLAY_QOS_FILE_TAG}",
            default_value=replay.qos_file_path,
            tag=REPLAY_QOS_FILE_TAG,
        )
        _add_labeled_input_text(
            dpg,
            "Participant QoS Profile",
            f"##{REPLAY_PARTICIPANT_QOS_TAG}",
            default_value=replay.participant_qos_profile,
            tag=REPLAY_PARTICIPANT_QOS_TAG,
        )
        _add_labeled_input_text(
            dpg,
            "Writer QoS Profile",
            f"##{REPLAY_WRITER_QOS_TAG}",
            default_value=replay.writer_qos_profile,
            tag=REPLAY_WRITER_QOS_TAG,
        )
    labels = _replay_candidate_labels(replay)
    dpg.add_text("Detected Replay Instance")
    dpg.add_combo(
        labels,
        default_value=_selected_replay_target_label(replay, labels),
        label="##replay_candidate_combo",
        tag=REPLAY_CANDIDATE_COMBO_TAG,
        callback=_replay_candidate_combo_callback(replay, command_sink),
    )
    _render_replay_actions(dpg, replay, command_sink=command_sink)
    _render_replay_targets(dpg, replay, command_sink=command_sink)
    _render_replay_details(dpg, replay)
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
            _add_action_button(
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
    with _collapsible_section(dpg, "Launch Replay Service", default_open=True):
        _add_labeled_input_text(dpg, "Label", f"##{REPLAY_LAUNCH_LABEL_TAG}", default_value=launch.label, tag=REPLAY_LAUNCH_LABEL_TAG)
        _add_labeled_input_text(
            dpg,
            "Config XML Paths",
            f"##{REPLAY_LAUNCH_CONFIG_PATHS_TAG}",
            default_value=";".join(launch.config_paths),
            tag=REPLAY_LAUNCH_CONFIG_PATHS_TAG,
        )
        _add_labeled_input_text(dpg, "Config Name", f"##{REPLAY_LAUNCH_CONFIG_NAME_TAG}", default_value=launch.config_name, tag=REPLAY_LAUNCH_CONFIG_NAME_TAG)
        _add_labeled_input_text(dpg, "Data Domain", f"##{REPLAY_LAUNCH_DATA_DOMAIN_TAG}", default_value=str(launch.data_domain_id), tag=REPLAY_LAUNCH_DATA_DOMAIN_TAG)
        _add_labeled_input_text(dpg, "Admin Domain", f"##{REPLAY_LAUNCH_ADMIN_DOMAIN_TAG}", default_value=str(launch.admin_domain_id), tag=REPLAY_LAUNCH_ADMIN_DOMAIN_TAG)
        _add_labeled_input_text(dpg, "Monitoring Domain", f"##{REPLAY_LAUNCH_MONITOR_DOMAIN_TAG}", default_value=str(launch.monitoring_domain_id), tag=REPLAY_LAUNCH_MONITOR_DOMAIN_TAG)
        _add_labeled_input_text(dpg, "Recording DB Path", f"##{REPLAY_LAUNCH_DATABASE_PATH_TAG}", default_value=launch.database_path, tag=REPLAY_LAUNCH_DATABASE_PATH_TAG)
        with _collapsible_section(dpg, "Replay Launch Advanced", default_open=False):
            _add_labeled_input_text(dpg, "Verbosity", f"##{REPLAY_LAUNCH_VERBOSITY_TAG}", default_value=launch.verbosity, tag=REPLAY_LAUNCH_VERBOSITY_TAG)
            _add_labeled_input_text(dpg, "Executable", f"##{REPLAY_LAUNCH_EXECUTABLE_TAG}", default_value=launch.executable, tag=REPLAY_LAUNCH_EXECUTABLE_TAG)
            _add_labeled_input_text(dpg, "Working Dir", f"##{REPLAY_LAUNCH_WORKING_DIR_TAG}", default_value=launch.working_dir, tag=REPLAY_LAUNCH_WORKING_DIR_TAG)
            _add_labeled_input_text(dpg, "Extra Args", f"##{REPLAY_LAUNCH_EXTRA_ARGS_TAG}", default_value=" ".join(launch.extra_args), tag=REPLAY_LAUNCH_EXTRA_ARGS_TAG)
        _add_action_button(
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
                _add_action_button(
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


def _render_replay_details(dpg, replay: ReplayTabViewModel) -> None:
    selected = replay.selected_target
    if selected is None:
        return
    with _collapsible_section(dpg, "Replay Details", default_open=False):
        dpg.add_text(f"Control Name: {selected.control_name}")
        dpg.add_text(f"Source: {selected.source}")
        dpg.add_text(f"Host: {selected.hostname or '(unknown)'}")
        dpg.add_text(f"PID: {selected.pid or '(unknown)'}")
        dpg.add_text(f"State: {selected.state}")
        dpg.add_text(f"Progress: {selected.progress or '(n/a)'}")
        dpg.add_text(f"Confidence: {selected.confidence or '(n/a)'}")
        dpg.add_text(f"Owned By GUI: {'yes' if selected.owned else 'no'}")
        dpg.add_text(f"Last Seen Age: {selected.age or '(n/a)'}")
        if selected.output_path:
            dpg.add_text(f"Output Log: {selected.output_path}")
        if selected.output_tail:
            dpg.add_text("Recent Output")
            dpg.add_text(selected.output_tail)


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
        database_path=_dpg_text_value(dpg, REPLAY_DATABASE_PATH_TAG, replay.database_path),
        playback_rate=_float_text_value(dpg, REPLAY_PLAYBACK_RATE_TAG, replay.playback_rate),
        time_window=_dpg_text_value(dpg, REPLAY_TIME_WINDOW_TAG, replay.time_window),
        qos_file_path=_dpg_text_value(dpg, REPLAY_QOS_FILE_TAG, replay.qos_file_path),
        participant_qos_profile=_dpg_text_value(
            dpg,
            REPLAY_PARTICIPANT_QOS_TAG,
            replay.participant_qos_profile,
        ),
        writer_qos_profile=_dpg_text_value(
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
            label=_dpg_text_value(dpg, REPLAY_LAUNCH_LABEL_TAG, replay.launch.label),
            config_paths=tuple(
                part.strip()
                for part in _dpg_text_value(
                    dpg,
                    REPLAY_LAUNCH_CONFIG_PATHS_TAG,
                    ";".join(replay.launch.config_paths),
                ).replace("\n", ";").split(";")
                if part.strip()
            ),
            config_name=_dpg_text_value(dpg, REPLAY_LAUNCH_CONFIG_NAME_TAG, replay.launch.config_name),
            data_domain_id=int(_float_text_value(dpg, REPLAY_LAUNCH_DATA_DOMAIN_TAG, replay.launch.data_domain_id)),
            admin_domain_id=int(_float_text_value(dpg, REPLAY_LAUNCH_ADMIN_DOMAIN_TAG, replay.launch.admin_domain_id)),
            monitoring_domain_id=int(_float_text_value(dpg, REPLAY_LAUNCH_MONITOR_DOMAIN_TAG, replay.launch.monitoring_domain_id)),
            database_path=_dpg_text_value(dpg, REPLAY_LAUNCH_DATABASE_PATH_TAG, replay.launch.database_path),
            verbosity=_dpg_text_value(dpg, REPLAY_LAUNCH_VERBOSITY_TAG, replay.launch.verbosity),
            executable=_dpg_text_value(dpg, REPLAY_LAUNCH_EXECUTABLE_TAG, replay.launch.executable),
            working_dir=_dpg_text_value(dpg, REPLAY_LAUNCH_WORKING_DIR_TAG, replay.launch.working_dir),
            extra_args=tuple(
                part.strip()
                for part in _dpg_text_value(dpg, REPLAY_LAUNCH_EXTRA_ARGS_TAG, " ".join(replay.launch.extra_args)).split()
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


def _replay_candidate_combo_callback(
        replay: ReplayTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]],
):
    label_to_row = {
        _replay_candidate_label(row): row
        for row in replay.targets
    }

    def _callback(_sender=None, app_data=None, _user_data=None):
        if command_sink is None:
            return False
        row = label_to_row.get(str(app_data or ""))
        if row is None:
            return False
        return _replay_select_callback(row, command_sink)()

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
    _add_labeled_input_text(
        dpg,
        "Topic Filter",
        "##topic_filter",
        default_value=topics.search_text,
        callback=_topic_search_callback(topics, command_sink),
    )
    _render_topic_actions(dpg, topics, command_sink=command_sink)
    _render_topic_table(dpg, topics, command_sink=command_sink)
    dpg.add_text("Field Picker")
    with _collapsible_section(dpg, "Show Field Picker", default_open=False):
        _render_field_picker(dpg, topics, command_sink=command_sink)
    dpg.add_text("Sample Inspector")
    with _collapsible_section(dpg, "Show Sample Inspector", default_open=False):
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
            _add_action_button(
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
                _add_action_button(
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
                _add_action_button(
                    dpg,
                    label="*" if row.selected else "Select",
                    callback=_topic_field_callback(row, topics, command_sink, plot=False),
                    width=COMPACT_BUTTON_WIDTH,
                )
                _add_action_button(
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
    _add_labeled_input_text(
        dpg,
        "Workspace Name",
        f"##{WORKSPACE_NAME_INPUT_TAG}",
        tag=WORKSPACE_NAME_INPUT_TAG,
        default_value=view.workspace_name,
    )
    _add_labeled_input_text(
        dpg,
        "Workspace Path",
        f"##{WORKSPACE_PATH_INPUT_TAG}",
        tag=WORKSPACE_PATH_INPUT_TAG,
        default_value=view.workspace_path,
    )
    with dpg.group(horizontal=True):
        _add_action_button(
            dpg,
            label="Save Workspace",
            callback=_workspace_action_callback(dpg, view, "save", command_sink),
            width=ACTION_BUTTON_WIDTH,
        )
        _add_action_button(
            dpg,
            label="Load Workspace",
            callback=_workspace_action_callback(dpg, view, "load", command_sink),
            width=ACTION_BUTTON_WIDTH,
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
            _add_action_button(dpg, label=action.label, enabled=action.enabled, width=ACTION_BUTTON_WIDTH)
            if action.reason and not action.enabled:
                dpg.add_text(action.reason)


def _add_action_button(
        dpg,
        label: str,
        callback=None,
        enabled: bool = True,
        width: int = ACTION_BUTTON_WIDTH,
):
    kwargs = {"label": label, "enabled": enabled, "width": int(width)}
    if callback is not None:
        kwargs["callback"] = callback
    return dpg.add_button(**kwargs)


def _add_labeled_input_text(
        dpg,
        visible_label: str,
        input_label: str,
        default_value: str = "",
        tag: Optional[str] = None,
        callback=None,
        width: Optional[int] = None,
    readonly: bool = False,
):
    dpg.add_text(visible_label)
    kwargs = {
        "label": input_label,
        "default_value": default_value,
    }
    if width is not None:
        kwargs["width"] = int(width)
    if readonly:
        kwargs["readonly"] = True
    if tag is not None:
        kwargs["tag"] = tag
    if callback is not None:
        kwargs["callback"] = callback
    return dpg.add_input_text(**kwargs)


def _add_labeled_checkbox(
        dpg,
        visible_label: str,
        default_value: bool = False,
        tag: Optional[str] = None,
        callback=None,
):
    dpg.add_text(visible_label)
    kwargs = {"default_value": bool(default_value)}
    if tag is not None:
        kwargs["tag"] = tag
    if callback is not None:
        kwargs["callback"] = callback
    return dpg.add_checkbox(**kwargs)


def _collapsible_section(dpg, label: str, default_open: bool = False):
    builder = getattr(dpg, "collapsing_header", None)
    if callable(builder):
        try:
            return builder(label=label, default_open=default_open)
        except TypeError:
            return builder(label=label)
    group_builder = getattr(dpg, "group", None)
    if callable(group_builder):
        return group_builder()
    return nullcontext()


def _apply_button_theme_if_supported(dpg) -> None:
    required = (
        "theme",
        "theme_component",
        "add_theme_style",
        "add_theme_color",
        "bind_theme",
        "mvButton",
        "mvThemeCat_Core",
        "mvStyleVar_FramePadding",
        "mvStyleVar_FrameRounding",
        "mvThemeCol_Button",
        "mvThemeCol_ButtonHovered",
        "mvThemeCol_ButtonActive",
    )
    if any(not hasattr(dpg, name) for name in required):
        return
    try:
        with dpg.theme(tag="rs_gui_v2_accessible_theme"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 14, 8, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Button, (36, 99, 168, 255), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (56, 122, 193, 255), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (24, 77, 136, 255), category=dpg.mvThemeCat_Core)
        dpg.bind_theme("rs_gui_v2_accessible_theme")
    except Exception:
        return


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


def _render_console_tab(dpg, view: ShellViewModel) -> None:
    dpg.add_text("Console Output")
    with dpg.group(horizontal=True):
        _add_action_button(
            dpg,
            label="Copy Console",
            callback=_copy_console_callback(dpg),
            width=ACTION_BUTTON_WIDTH,
        )
        if view.event_log:
            _add_action_button(
                dpg,
                label="Copy Latest Event",
                callback=_copy_text_callback(dpg, _event_output_text(view.event_log[-1])),
                width=ACTION_BUTTON_WIDTH,
            )
    dpg.add_input_text(
        tag=CONSOLE_OUTPUT_TAG,
        label="##console_output",
        default_value=_console_output_text(view),
        multiline=True,
        readonly=True,
        width=-1,
        height=620,
    )
    if view.event_log:
        with _collapsible_section(dpg, "Copy Individual Events", default_open=False):
            for index, entry in enumerate(view.event_log, start=1):
                _add_action_button(
                    dpg,
                    label=f"Copy Event {index}",
                    callback=_copy_text_callback(dpg, _event_output_text(entry)),
                    width=ACTION_BUTTON_WIDTH,
                )
                dpg.add_text(f"{entry.timestamp} {entry.level.upper()} {entry.event_type}: {entry.message}")


def _refresh_console_output(dpg, view: ShellViewModel) -> None:
    set_value = getattr(dpg, "set_value", None)
    if not callable(set_value):
        return
    try:
        set_value(CONSOLE_OUTPUT_TAG, _console_output_text(view))
    except Exception:
        return


def _console_output_text(view: ShellViewModel) -> str:
    lines = ["=== Events ==="]
    if view.event_log:
        for index, entry in enumerate(view.event_log, start=1):
            lines.append(f"[{index}] {_event_output_text(entry)}")
            lines.append("")
    else:
        lines.append("No events yet.")
    lines.append("=== Diagnostics ===")
    if view.operator_diagnostics:
        lines.extend(view.operator_diagnostics)
    else:
        lines.append("No diagnostics.")
    lines.append("=== Inspector ===")
    if view.inspector_lines:
        lines.extend(view.inspector_lines)
    else:
        lines.append("No inspector data.")
    return "\n".join(lines)


def _event_output_text(entry) -> str:
    return "\n".join((
        f"{entry.timestamp} {entry.level.upper()} {entry.source} {entry.event_type}",
        f"message: {entry.message}",
        f"event_id: {entry.event_id}",
        "payload:",
        _json_block(entry.payload),
    ))


def _copy_text_callback(dpg, text: str):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        set_clipboard_text = getattr(dpg, "set_clipboard_text", None)
        if not callable(set_clipboard_text):
            return False
        set_clipboard_text(str(text))
        return True
    return _callback


def _copy_console_callback(dpg):
    def _callback(_sender=None, _app_data=None, _user_data=None):
        set_clipboard_text = getattr(dpg, "set_clipboard_text", None)
        get_value = getattr(dpg, "get_value", None)
        if not (callable(set_clipboard_text) and callable(get_value)):
            return False
        value = get_value(CONSOLE_OUTPUT_TAG)
        set_clipboard_text(str(value or ""))
        return True
    return _callback


def _json_block(value) -> str:
    try:
        return json.dumps(value, indent=2, sort_keys=True, default=str)
    except TypeError:
        return str(value)
