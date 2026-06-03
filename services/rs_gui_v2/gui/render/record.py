"""Record tab rendering for the rs_gui_v2 Dear PyGui shell."""

import re
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from app_core import AppCommand
from app_core.services import ServiceInstanceRef, ServiceKind, ServiceProcessCandidate

from ..tabs.record_tab import (
    RecordLaunchViewModel,
    RecordTabViewModel,
    build_record_action_command,
    build_record_launch_command,
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
    collapsible_section,
    dpg_text_value,
    int_text_value,
)


# --- Widget Tags ---
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
RECORD_CANDIDATE_COMBO_TAG = "rs_gui_v2_record_candidate_combo"

# --- Constants ---
TIMESTAMP_DIR_EXPR = "recording_%ts%"
DEFAULT_FILENAME_BASE = "data"
AUTO_FILENAME_TOKEN = "%auto:0-9%"
TIMESTAMP_FILENAME_TOKEN = "%ts%"


@dataclass(frozen=True)
class RecordLaunchVariables:
    """Typed representation of Recording Service -D template variables."""

    data_domain_id: int = 0
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0
    session_name: str = "recording_session"
    topic_allow: str = "*"
    topic_deny: str = "rti/*"
    storage_format: str = "XCDR_AUTO"
    workspace_dir: str = "log_dir"
    exec_dir_expr: str = TIMESTAMP_DIR_EXPR
    filename_expr: str = "data_%auto:0-9%.db"
    rollover_enabled: str = "false"
    rollover_mb: str = "1024"

    def to_args(self) -> Tuple[str, ...]:
        """Serialize to -D command-line arguments."""
        return (
            f"-DREC_DOMAIN_ID={int(self.data_domain_id)}",
            f"-DREC_ADMIN_DOMAIN_ID={int(self.admin_domain_id)}",
            f"-DREC_MON_DOMAIN_ID={int(self.monitoring_domain_id)}",
            "-DREC_STATUS_PERIOD_SEC=0",
            "-DREC_STATUS_PERIOD_NSEC=500000000",
            f"-DREC_SESSION_NAME={safe_record_session_name(self.session_name)}",
            f"-DREC_TOPIC_ALLOW={self.topic_allow.strip()}",
            f"-DREC_TOPIC_DENY={self.topic_deny.strip()}",
            f"-DREC_STORAGE_FORMAT={self.storage_format.strip()}",
            f"-DREC_WORKSPACE_DIR={self.workspace_dir.strip()}",
            f"-DREC_EXEC_DIR_EXPR={self.exec_dir_expr.strip()}",
            f"-DREC_FILENAME_EXPR={self.filename_expr.strip()}",
            f"-DREC_ROLLOVER_ENABLED={boolean_text(self.rollover_enabled)}",
            f"-DREC_ROLLOVER_MB={max(1, int(str(self.rollover_mb).strip() or 1))}",
        )

    @classmethod
    def from_extra_args(cls, extra_args: Tuple[str, ...], defaults=None) -> "RecordLaunchVariables":
        """Parse -D template variables from extra_args tuple."""
        d = defaults or cls()
        return cls(
            data_domain_id=int(record_var_from_extra_args(extra_args, "REC_DOMAIN_ID", str(d.data_domain_id))),
            admin_domain_id=int(record_var_from_extra_args(extra_args, "REC_ADMIN_DOMAIN_ID", str(d.admin_domain_id))),
            monitoring_domain_id=int(record_var_from_extra_args(extra_args, "REC_MON_DOMAIN_ID", str(d.monitoring_domain_id))),
            session_name=record_var_from_extra_args(extra_args, "REC_SESSION_NAME", d.session_name),
            topic_allow=record_var_from_extra_args(extra_args, "REC_TOPIC_ALLOW", d.topic_allow),
            topic_deny=record_var_from_extra_args(extra_args, "REC_TOPIC_DENY", d.topic_deny),
            storage_format=record_var_from_extra_args(extra_args, "REC_STORAGE_FORMAT", d.storage_format),
            workspace_dir=record_var_from_extra_args(extra_args, "REC_WORKSPACE_DIR", d.workspace_dir),
            exec_dir_expr=record_var_from_extra_args(extra_args, "REC_EXEC_DIR_EXPR", d.exec_dir_expr),
            filename_expr=record_var_from_extra_args(extra_args, "REC_FILENAME_EXPR", d.filename_expr),
            rollover_enabled=record_var_from_extra_args(extra_args, "REC_ROLLOVER_ENABLED", d.rollover_enabled),
            rollover_mb=record_var_from_extra_args(extra_args, "REC_ROLLOVER_MB", d.rollover_mb),
        )

    @classmethod
    def managed_prefixes(cls) -> Tuple[str, ...]:
        """Return all -D prefixes managed by this class."""
        names = (
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
        return tuple(f"-D{name}=" for name in names)


def merge_record_variable_args(existing_args, managed_args) -> Tuple[str, ...]:
    """Merge user extra_args with managed -D variable args, managed args win."""
    managed_prefixes = RecordLaunchVariables.managed_prefixes()
    retained = tuple(
        arg for arg in existing_args
        if not str(arg).strip().startswith(managed_prefixes)
    )
    return retained + tuple(arg for arg in managed_args if str(arg).strip())


# --- Rendering ---

def render_record_tab(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
        status_items: Tuple[object, ...] = (),
) -> None:
    """Render the full Record tab content."""
    _render_record_launch_controls(dpg, record, command_sink=command_sink)
    dpg.add_separator()
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


def refresh_record_tab(
        dpg,
        view: "ShellViewModel",
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    """Refresh the Record tab content in-place."""
    from ..view_models import ShellViewModel as _VM  # noqa: F811
    if not _has_item(dpg, RECORD_TAB_CONTENT_TAG):
        return
    delete_item = getattr(dpg, "delete_item", None)
    push_container_stack = getattr(dpg, "push_container_stack", None)
    pop_container_stack = getattr(dpg, "pop_container_stack", None)
    if not (callable(delete_item) and callable(push_container_stack) and callable(pop_container_stack)):
        _refresh_record_candidate_combo(dpg, view)
        return
    try:
        delete_item(RECORD_TAB_CONTENT_TAG, children_only=True)
        push_container_stack(RECORD_TAB_CONTENT_TAG)
        try:
            render_record_tab(
                dpg,
                view.record_tab,
                command_sink=command_sink,
                status_items=view.status_items,
            )
        finally:
            pop_container_stack()
    except Exception:
        _refresh_record_candidate_combo(dpg, view)


def _has_item(dpg, tag: str) -> bool:
    does_item_exist = getattr(dpg, "does_item_exist", None)
    if callable(does_item_exist):
        try:
            return bool(does_item_exist(tag))
        except Exception:
            return False
    return False


def _refresh_record_candidate_combo(dpg, view) -> None:
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


def _record_candidate_labels(record: RecordTabViewModel):
    return [row.control_name for row in record.candidates] or ["No Recording Service"]


def _selected_record_candidate_label(record: RecordTabViewModel, labels):
    return record.selected_candidate.control_name if record.selected_candidate else labels[0]


def _render_record_launch_controls(
        dpg,
        record: RecordTabViewModel,
        command_sink: Optional[Callable[[AppCommand], bool]] = None,
) -> None:
    launch = record.launch
    preset_options = ("record_selected", "record_all", "record_json")
    default_preset = launch.config_name if launch.config_name in preset_options else "record_selected"
    default_session = record_var_from_extra_args(
        launch.extra_args,
        "REC_SESSION_NAME",
        safe_record_session_name(launch.label or "recording_session"),
    )
    default_topic_allow = record_var_from_extra_args(launch.extra_args, "REC_TOPIC_ALLOW", "*")
    default_topic_deny = record_var_from_extra_args(launch.extra_args, "REC_TOPIC_DENY", "rti/*")
    default_storage_format = record_var_from_extra_args(
        launch.extra_args,
        "REC_STORAGE_FORMAT",
        _default_storage_for_config(default_preset),
    )
    default_workspace_dir = record_var_from_extra_args(launch.extra_args, "REC_WORKSPACE_DIR", "log_dir")
    default_exec_dir_expr = record_var_from_extra_args(launch.extra_args, "REC_EXEC_DIR_EXPR", TIMESTAMP_DIR_EXPR)
    default_filename_expr = record_var_from_extra_args(
        launch.extra_args,
        "REC_FILENAME_EXPR",
        record_filename_expression_from_base(DEFAULT_FILENAME_BASE),
    )
    default_filename_base = record_filename_base_from_expression(default_filename_expr, DEFAULT_FILENAME_BASE)
    default_rollover_enabled = record_var_from_extra_args(launch.extra_args, "REC_ROLLOVER_ENABLED", "false")
    default_rollover_mb = record_var_from_extra_args(launch.extra_args, "REC_ROLLOVER_MB", "1024")
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
    add_labeled_input_text(
        dpg,
        "Config Name",
        f"##{RECORD_LAUNCH_CONFIG_NAME_TAG}",
        default_value=default_preset,
        tag=RECORD_LAUNCH_CONFIG_NAME_TAG,
    )
    dpg.add_text("Domain IDs")
    with dpg.group(horizontal=True):
        add_labeled_input_text(
            dpg,
            "Data Domain ID",
            f"##{RECORD_LAUNCH_DATA_DOMAIN_TAG}",
            default_value=str(launch.data_domain_id),
            tag=RECORD_LAUNCH_DATA_DOMAIN_TAG,
            width=DOMAIN_ID_INPUT_WIDTH,
        )
        add_labeled_input_text(
            dpg,
            "Admin Domain ID",
            f"##{RECORD_LAUNCH_ADMIN_DOMAIN_TAG}",
            default_value=str(launch.admin_domain_id),
            tag=RECORD_LAUNCH_ADMIN_DOMAIN_TAG,
            width=DOMAIN_ID_INPUT_WIDTH,
        )
        add_labeled_input_text(
            dpg,
            "Monitoring Domain ID",
            f"##{RECORD_LAUNCH_MONITOR_DOMAIN_TAG}",
            default_value=str(launch.monitoring_domain_id),
            tag=RECORD_LAUNCH_MONITOR_DOMAIN_TAG,
            width=DOMAIN_ID_INPUT_WIDTH,
        )
    with collapsible_section(dpg, "Template Variables (REC_*)", default_open=True):
        add_labeled_input_text(
            dpg,
            "REC_SESSION_NAME",
            f"##{RECORD_VAR_SESSION_NAME_TAG}",
            default_value=default_session,
            tag=RECORD_VAR_SESSION_NAME_TAG,
        )
        add_labeled_input_text(
            dpg,
            "REC_TOPIC_ALLOW",
            f"##{RECORD_VAR_TOPIC_ALLOW_TAG}",
            default_value=default_topic_allow,
            tag=RECORD_VAR_TOPIC_ALLOW_TAG,
        )
        add_labeled_input_text(
            dpg,
            "REC_TOPIC_DENY",
            f"##{RECORD_VAR_TOPIC_DENY_TAG}",
            default_value=default_topic_deny,
            tag=RECORD_VAR_TOPIC_DENY_TAG,
        )
        add_labeled_input_text(
            dpg,
            "REC_STORAGE_FORMAT",
            f"##{RECORD_VAR_STORAGE_FORMAT_TAG}",
            default_value=default_storage_format,
            tag=RECORD_VAR_STORAGE_FORMAT_TAG,
        )
    with collapsible_section(dpg, "Advanced Launch Fields", default_open=False):
        dpg.add_text("Storage Naming")
        with dpg.group(horizontal=True):
            add_labeled_input_text(
                dpg,
                "Output Root Directory",
                f"##{RECORD_VAR_WORKSPACE_DIR_TAG}",
                default_value=default_workspace_dir,
                tag=RECORD_VAR_WORKSPACE_DIR_TAG,
                callback=_record_storage_path_preview_callback(dpg),
            )
            add_labeled_input_text(
                dpg,
                "Execution Subdirectory",
                f"##{RECORD_VAR_EXEC_DIR_EXPR_TAG}",
                default_value=default_exec_dir_expr,
                tag=RECORD_VAR_EXEC_DIR_EXPR_TAG,
                callback=_record_storage_path_preview_callback(dpg),
            )
        with dpg.group(horizontal=True):
            add_labeled_input_text(
                dpg,
                "File Name",
                f"##{RECORD_VAR_FILENAME_BASE_TAG}",
                default_value=default_filename_base,
                tag=RECORD_VAR_FILENAME_BASE_TAG,
                callback=_record_filename_base_callback(dpg),
            )
            add_labeled_input_text(
                dpg,
                "Filename Template",
                f"##{RECORD_VAR_FILENAME_EXPR_TAG}",
                default_value=default_filename_expr,
                tag=RECORD_VAR_FILENAME_EXPR_TAG,
                callback=_record_storage_path_preview_callback(dpg),
            )
        add_labeled_input_text(
            dpg,
            "Derived Storage Expression",
            f"##{RECORD_VAR_STORAGE_PATH_EXPR_TAG}",
            default_value=record_storage_path_expression(
                default_workspace_dir,
                default_exec_dir_expr,
                default_filename_expr,
            ),
            tag=RECORD_VAR_STORAGE_PATH_EXPR_TAG,
            width=STORAGE_PATH_INPUT_WIDTH,
            readonly=True,
        )
        with dpg.group(horizontal=True):
            add_labeled_checkbox(
                dpg,
                "Enable Rollover",
                default_value=boolean_text(default_rollover_enabled) == "true",
                tag=RECORD_VAR_ROLLOVER_ENABLED_TAG,
            )
            add_labeled_input_text(
                dpg,
                "Rollover Size MB",
                f"##{RECORD_VAR_ROLLOVER_MB_TAG}",
                default_value=default_rollover_mb,
                tag=RECORD_VAR_ROLLOVER_MB_TAG,
            )
        with dpg.group(horizontal=True):
            add_labeled_input_text(
                dpg,
                "Logging Verbosity",
                f"##{RECORD_LAUNCH_VERBOSITY_TAG}",
                default_value=launch.verbosity,
                tag=RECORD_LAUNCH_VERBOSITY_TAG,
            )
        with dpg.group(horizontal=True):
            add_labeled_input_text(
                dpg,
                "Executable Path",
                f"##{RECORD_LAUNCH_EXECUTABLE_TAG}",
                default_value=launch.executable,
                tag=RECORD_LAUNCH_EXECUTABLE_TAG,
            )
            add_labeled_input_text(
                dpg,
                "Working Directory",
                f"##{RECORD_LAUNCH_WORKING_DIR_TAG}",
                default_value=launch.working_dir,
                tag=RECORD_LAUNCH_WORKING_DIR_TAG,
            )
        add_labeled_input_text(
            dpg,
            "Extra Launch Args",
            f"##{RECORD_LAUNCH_EXTRA_ARGS_TAG}",
            default_value=" ".join(launch.extra_args),
            tag=RECORD_LAUNCH_EXTRA_ARGS_TAG,
        )
    with collapsible_section(dpg, "Command Preview", default_open=False):
        dpg.add_text(launch.command_preview)
    add_action_button(
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
            add_action_button(
                dpg,
                label=action.label,
                enabled=action.enabled,
                callback=_record_action_callback(record, action.action_id, command_sink),
                width=ACTION_BUTTON_WIDTH,
            )
    add_labeled_input_text(dpg, "Command Tag", "##record_command_tag", default_value=record.tag_value)


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
    with collapsible_section(dpg, label, default_open=False):
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


# --- Callbacks ---

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
        config_name = dpg_text_value(dpg, RECORD_LAUNCH_CONFIG_NAME_TAG, record.launch.config_name)
        data_domain_id = int_text_value(dpg, RECORD_LAUNCH_DATA_DOMAIN_TAG, record.launch.data_domain_id)
        admin_domain_id = int_text_value(dpg, RECORD_LAUNCH_ADMIN_DOMAIN_TAG, record.launch.admin_domain_id)
        monitoring_domain_id = int_text_value(dpg, RECORD_LAUNCH_MONITOR_DOMAIN_TAG, record.launch.monitoring_domain_id)
        raw_extra_args = _extra_args_from_text(
            dpg_text_value(dpg, RECORD_LAUNCH_EXTRA_ARGS_TAG, " ".join(record.launch.extra_args))
        )
        variables = RecordLaunchVariables(
            data_domain_id=data_domain_id,
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=monitoring_domain_id,
            session_name=dpg_text_value(dpg, RECORD_VAR_SESSION_NAME_TAG, record.launch.label),
            topic_allow=dpg_text_value(dpg, RECORD_VAR_TOPIC_ALLOW_TAG, "*"),
            topic_deny=dpg_text_value(dpg, RECORD_VAR_TOPIC_DENY_TAG, "rti/*"),
            storage_format=dpg_text_value(
                dpg,
                RECORD_VAR_STORAGE_FORMAT_TAG,
                _default_storage_for_config(config_name),
            ),
            workspace_dir=dpg_text_value(dpg, RECORD_VAR_WORKSPACE_DIR_TAG, "log_dir"),
            exec_dir_expr=dpg_text_value(dpg, RECORD_VAR_EXEC_DIR_EXPR_TAG, "recording_%ts%"),
            filename_expr=dpg_text_value(dpg, RECORD_VAR_FILENAME_EXPR_TAG, "data_%auto:0-9%.db"),
            rollover_enabled=dpg_text_value(dpg, RECORD_VAR_ROLLOVER_ENABLED_TAG, "false"),
            rollover_mb=dpg_text_value(dpg, RECORD_VAR_ROLLOVER_MB_TAG, "1024"),
        )
        launch = RecordLaunchViewModel(
            label=dpg_text_value(dpg, RECORD_LAUNCH_LABEL_TAG, record.launch.label),
            config_paths=_config_paths_from_text(
                dpg_text_value(dpg, RECORD_LAUNCH_CONFIG_PATHS_TAG, ";".join(record.launch.config_paths))
            ),
            available_config_names=record.launch.available_config_names,
            config_name=config_name,
            data_domain_id=data_domain_id,
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=monitoring_domain_id,
            verbosity=dpg_text_value(dpg, RECORD_LAUNCH_VERBOSITY_TAG, record.launch.verbosity),
            executable=dpg_text_value(dpg, RECORD_LAUNCH_EXECUTABLE_TAG, record.launch.executable),
            working_dir=dpg_text_value(dpg, RECORD_LAUNCH_WORKING_DIR_TAG, record.launch.working_dir),
            extra_args=merge_record_variable_args(raw_extra_args, variables.to_args()),
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
            record_filename_expression_from_base(
                dpg_text_value(dpg, RECORD_VAR_FILENAME_BASE_TAG, DEFAULT_FILENAME_BASE),
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
        record_storage_path_expression(
            dpg_text_value(dpg, RECORD_VAR_WORKSPACE_DIR_TAG, "log_dir"),
            dpg_text_value(dpg, RECORD_VAR_EXEC_DIR_EXPR_TAG, TIMESTAMP_DIR_EXPR),
            dpg_text_value(
                dpg,
                RECORD_VAR_FILENAME_EXPR_TAG,
                record_filename_expression_from_base(DEFAULT_FILENAME_BASE),
            ),
        ),
    )
    return True


def _candidate_from_record_row(record: RecordTabViewModel, candidate_id: str):
    for row in record.candidates:
        if row.candidate_id == candidate_id:
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


# --- Template Variable Utilities ---

def record_var_from_extra_args(extra_args, var_name: str, default: str = "") -> str:
    """Extract a -D variable value from the extra_args tuple."""
    prefix = f"-D{var_name}="
    for arg in extra_args or ():
        token = str(arg).strip()
        if token.startswith(prefix):
            return token[len(prefix):]
    return str(default)


def record_storage_path_expression(workspace_dir: str, exec_dir_expr: str, filename_expr: str) -> str:
    """Compose the derived storage path from three components."""
    workspace = str(workspace_dir).strip().rstrip("/")
    exec_dir = str(exec_dir_expr).strip().strip("/")
    filename = str(filename_expr).strip().strip("/")
    path = workspace
    if exec_dir:
        path = f"{path}/{exec_dir}" if path else exec_dir
    if filename:
        path = f"{path}/{filename}" if path else filename
    return path


def record_filename_expression_from_base(filename_base: str, include_timestamp: bool = False) -> str:
    """Build the filename template from a user-friendly base name."""
    base = safe_record_filename_base(filename_base)
    if include_timestamp:
        return f"{base}_{TIMESTAMP_FILENAME_TOKEN}_{AUTO_FILENAME_TOKEN}.db"
    return f"{base}_{AUTO_FILENAME_TOKEN}.db"


def record_filename_base_from_expression(filename_expr: str, default: str = DEFAULT_FILENAME_BASE) -> str:
    """Extract the user-friendly base name from a filename template."""
    value = str(filename_expr).strip()
    if value.lower().endswith(".db"):
        value = value[:-3]
    value = value.replace(AUTO_FILENAME_TOKEN, "")
    value = value.replace(TIMESTAMP_FILENAME_TOKEN, "")
    value = value.strip("_.- ")
    return safe_record_filename_base(value or default)


def safe_record_filename_base(filename_base: str) -> str:
    """Sanitize a filename base for Recording Service output."""
    value = str(filename_base).strip()
    if value.lower().endswith(".db"):
        value = value[:-3]
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.-")
    return value or DEFAULT_FILENAME_BASE


def safe_record_session_name(value: str) -> str:
    """Sanitize a session name for Recording Service -D variable."""
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "recording_session"


def boolean_text(value: str) -> str:
    """Normalize a boolean text value."""
    return "true" if str(value).strip().lower() in ("1", "true", "yes", "on", "enabled") else "false"


def _default_storage_for_config(config_name: str) -> str:
    return "JSON_SQLITE" if str(config_name).strip() == "record_json" else "XCDR_AUTO"


def _config_paths_from_text(value: str):
    return tuple(part.strip() for part in value.replace("\n", ";").split(";") if part.strip())


def _extra_args_from_text(value: str):
    return tuple(part.strip() for part in value.split() if part.strip())
