"""Record tab view models and command factories for rs_gui."""

from dataclasses import dataclass, field
import os
import shlex
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from app_core.events import AppCommand, CommandStatus
from app_core.services import (
    AdminReadiness,
    AdminReadinessStatus,
    ServiceCandidateSelection,
    ServiceCandidateSource,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceControlIdentity,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceProcessCandidate,
    candidate_from_control_identity,
)

from .controller_common import candidate_display_fields, candidate_has_duplicate_admin_target


@dataclass(frozen=True)
class RecordCandidateRow:
    """UI-facing candidate table row for the Record tab."""

    candidate_id: str
    label: str
    control_name: str
    source: str
    pid: str
    hostname: str
    state: str
    age: str
    confidence: str
    current_file: str = ""
    selected: bool = False
    conflict: bool = False
    owned: bool = False


@dataclass(frozen=True)
class RecordActionView:
    """Enabled/disabled state for one Record tab action."""

    action_id: str
    label: str
    enabled: bool
    reason: str = ""


@dataclass(frozen=True)
class RecordCommandRow:
    """UI-facing command history row."""

    command_id: str
    command: str
    reply: str
    observed: str = ""
    resource_path: str = ""
    message: str = ""


@dataclass(frozen=True)
class RecordLaunchViewModel:
    """UI-facing Recording Service launch configuration."""

    label: str = "Recording Service"
    config_paths: Tuple[str, ...] = field(default_factory=tuple)
    available_config_names: Tuple[str, ...] = field(default_factory=tuple)
    config_name: str = "template"
    storage_format: str = "XCDR"
    data_domain_id: int = 0
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0
    topic_allow: str = "*"
    topic_deny: str = "rti/*"
    log_directory: str = "services/rs_gui/log_data"
    verbosity: str = "ERROR:ERROR"
    executable: str = ""
    working_dir: str = ""
    extra_args: Tuple[str, ...] = field(default_factory=tuple)
    command_preview: str = ""
    enabled: bool = True
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_paths", tuple(str(path) for path in self.config_paths if str(path).strip()))
        object.__setattr__(self, "available_config_names", tuple(str(name) for name in self.available_config_names if str(name).strip()))
        object.__setattr__(self, "storage_format", _normalize_storage_format(self.storage_format))
        object.__setattr__(self, "extra_args", tuple(str(arg) for arg in self.extra_args if str(arg).strip()))
        object.__setattr__(self, "data_domain_id", int(self.data_domain_id))
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "topic_allow", str(self.topic_allow).strip() or "*")
        object.__setattr__(self, "topic_deny", str(self.topic_deny).strip())
        object.__setattr__(self, "log_directory", str(self.log_directory).strip() or "services/rs_gui/log_data")
        if not self.command_preview:
            object.__setattr__(self, "command_preview", _launch_command_preview(self))
        if self.enabled and not self.config_name.strip():
            object.__setattr__(self, "enabled", False)
            object.__setattr__(self, "disabled_reason", "config name required")


@dataclass(frozen=True)
class RecordTabViewModel:
    """Immutable snapshot consumed by the Record tab renderer."""

    target_label: str
    admin_domain: int
    monitoring_domain: int
    readiness: str
    observed_state: str
    selected_candidate_id: str
    candidates: Tuple[RecordCandidateRow, ...] = field(default_factory=tuple)
    actions: Tuple[RecordActionView, ...] = field(default_factory=tuple)
    tag_value: str = ""
    command_history: Tuple[RecordCommandRow, ...] = field(default_factory=tuple)
    monitoring_summary: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)
    launch: RecordLaunchViewModel = field(default_factory=RecordLaunchViewModel)

    @property
    def selected_candidate(self) -> Optional[RecordCandidateRow]:
        for row in self.candidates:
            if row.candidate_id == self.selected_candidate_id:
                return row
        return None

    @property
    def action_by_id(self) -> Dict[str, RecordActionView]:
        return {action.action_id: action for action in self.actions}


def build_record_tab_view_model(
        selection: ServiceCandidateSelection,
        readiness: Optional[AdminReadiness] = None,
        command_history: Iterable[ServiceCommandOutcome] = (),
        local_hostnames: Iterable[str] = (),
        graceful_shutdown_failed: bool = False,
        tag_value: str = "",
    launch: Optional[RecordLaunchViewModel] = None,
        now: float = 0.0,
) -> RecordTabViewModel:
    """Build a Record-tab snapshot from app-core service DTOs."""

    selected = selection.selected_candidate
    service = selected.service if selected else _empty_recording_service()
    availability = selection.control_availability(
        local_hostnames=local_hostnames,
        graceful_shutdown_failed=graceful_shutdown_failed,
    )
    duplicate_target = availability.duplicate_admin_target
    rows = tuple(
        _candidate_row(
            candidate,
            selected_id=selected.candidate_id if selected else "",
            conflict=(
                candidate.alive
                and candidate_has_duplicate_admin_target(
                    selection,
                    candidate.candidate_id,
                    local_hostnames,
                    graceful_shutdown_failed,
                )
            ),
            now=now,
        )
        for candidate in selection.candidates
    )
    diagnostics = tuple(availability.reasons)
    if readiness and not readiness.ready and readiness.message:
        diagnostics = diagnostics + (readiness.message,)
    observed_state = _record_display_state(selected.observed_state) if selected else "no service"
    return RecordTabViewModel(
        target_label=_target_label(selected, service),
        admin_domain=service.admin_domain_id,
        monitoring_domain=service.monitoring_domain_id,
        readiness=_readiness_text(readiness),
        observed_state=observed_state,
        selected_candidate_id=selected.candidate_id if selected else "",
        candidates=rows,
        actions=_record_actions(selected, availability, tag_value),
        tag_value=tag_value,
        command_history=tuple(_command_row(outcome) for outcome in command_history),
        monitoring_summary=_monitoring_summary(selected),
        diagnostics=diagnostics,
        launch=launch or RecordLaunchViewModel(),
    )


def build_record_action_command(
        action_id: str,
        candidate: ServiceProcessCandidate,
        tag_name: str = "",
        description: str = "",
) -> AppCommand:
    """Translate a Record-tab button action into an app-core command intent."""

    action_to_command = {
        "pause": "service.pause",
        "resume": "service.resume",
        "tag": "service.tag",
        "shutdown": "service.shutdown",
        "terminate_local": "service.terminate_local_process",
    }
    if action_id not in action_to_command:
        raise ValueError(f"Unsupported Record tab action: {action_id}")
    payload: Dict[str, Any] = {
        "service": candidate.service.to_dict(),
        "candidate_id": candidate.candidate_id,
        "launch_id": candidate.launch_id,
        "pid": candidate.pid,
        "hostname": candidate.hostname,
    }
    if action_id == "tag":
        if not tag_name.strip():
            raise ValueError("tag_name is required for Record tag commands")
        payload.update({"tag_name": tag_name.strip(), "description": description})
    return AppCommand(
        command_type=action_to_command[action_id],
        target=candidate.service.key,
        payload=payload,
    )


def build_record_launch_command(launch: RecordLaunchViewModel) -> AppCommand:
    """Translate Record-tab launch fields into an app-core launch command."""

    if not launch.config_name.strip():
        raise ValueError("config_name is required for Record launch commands")
    return AppCommand(
        command_type="service.launch_recording",
        target="recording",
        payload={
            "label": launch.label,
            "config_paths": list(launch.config_paths),
            "config_name": launch.config_name,
            "storage_format": launch.storage_format,
            "data_domain_id": launch.data_domain_id,
            "admin_domain_id": launch.admin_domain_id,
            "monitoring_domain_id": launch.monitoring_domain_id,
            "topic_allow": launch.topic_allow,
            "topic_deny": launch.topic_deny,
            "log_directory": launch.log_directory,
            "verbosity": launch.verbosity,
            "executable": launch.executable,
            "working_dir": launch.working_dir,
            "extra_args": list(launch.extra_args),
        },
    )


def build_mock_record_tab_view_model(now: float = 120.0) -> RecordTabViewModel:
    """Return a deterministic Record tab snapshot for the first GUI shell."""

    intent = ServiceLaunchIntent(
        kind=ServiceKind.RECORDING,
        label="Recording Service",
        admin_domain_id=0,
        monitoring_domain_id=0,
        config_paths=(
            "dds/qos/recording_service.xml",
            "dds/qos/DDS_QOS_PROFILES.xml",
        ),
    )
    identity = ServiceControlIdentity(
        intent=intent,
        session_guid="8f4f2a1c-0000-4000-8000-000000000000",
        created_at=1.0,
    )
    local_candidate = candidate_from_control_identity(
        identity,
        launch_id="launch-recording-main",
        pid=4218,
        hostname="dev-host",
        observed_state="RUNNING",
        metrics={"cpu_percent": 2.0, "memory_mb": 180, "throughput": "1.2 MB/s"},
        details={"sessions": 1, "topics": 4, "last_event": "rollover not detected"},
        observed_at=118.0,
    )
    stale_external = ServiceProcessCandidate(
        candidate_id="discovery:recording:old",
        service=identity.service_ref,
        source=ServiceCandidateSource.DISCOVERY,
        display_label="Recording Service",
        pid=5110,
        hostname="lab-host",
        participant_key="01:02:03",
        observed_state="STALE",
        alive=False,
        confidence=0.35,
        first_seen_at=40.0,
        last_seen_at=90.0,
    )
    selection = ServiceCandidateSelection(
        candidates=(local_candidate, stale_external),
        selected_candidate_id=local_candidate.candidate_id,
    )
    readiness = AdminReadiness(
        service=identity.service_ref,
        status=AdminReadinessStatus.READY,
        matched_request_writers=1,
        matched_reply_readers=1,
        message="request+reply matched",
        checked_at=119.0,
    )
    history = (
        ServiceCommandOutcome(
            request=ServiceCommandRequest(
                service=identity.service_ref,
                command=ServiceCommand.PAUSE,
                command_id="pause-21",
                created_at=111.0,
            ),
            status=CommandStatus.ACKNOWLEDGED,
            message="pause acknowledged",
            resource_path="/recording_services/RecordingService",
            payload={"observed_state": "PAUSED"},
            created_at=112.0,
        ),
    )
    return build_record_tab_view_model(
        selection,
        readiness=readiness,
        command_history=history,
        local_hostnames=("dev-host",),
        tag_value="e2e_tag_beta",
        now=now,
    )


def _candidate_row(
        candidate: ServiceProcessCandidate,
        selected_id: str,
        conflict: bool,
        now: float,
) -> RecordCandidateRow:
    display = candidate_display_fields(candidate, now)
    return RecordCandidateRow(
        candidate_id=candidate.candidate_id,
        label=str(display["label"]),
        control_name=str(display["control_name"]),
        source=str(display["source"]),
        pid=str(display["pid"]),
        hostname=str(display["hostname"]),
        state=_record_display_state(candidate.observed_state),
        current_file=_current_file(candidate.details),
        age=str(display["age"]),
        confidence=str(display["confidence"]),
        selected=candidate.candidate_id == selected_id,
        conflict=conflict,
        owned=bool(display["owned"]),
    )


def _record_display_state(state: str) -> str:
    normalized = str(state).strip()
    if normalized.upper() == "SHUTDOWN":
        return "exited"
    return normalized


def _record_actions(
        selected: Optional[ServiceProcessCandidate],
        availability,
        tag_value: str,
) -> Tuple[RecordActionView, ...]:
    disabled_reason = "; ".join(availability.reasons)
    admin_enabled = selected is not None and availability.service_admin_enabled
    terminate_enabled = selected is not None and availability.process_terminate_enabled
    state = (selected.observed_state if selected else "").lower()
    pause_enabled = admin_enabled and "pause" not in state
    resume_enabled = admin_enabled and "pause" in state
    return (
        RecordActionView("pause", "Pause", pause_enabled, "already paused" if admin_enabled and not pause_enabled else disabled_reason),
        RecordActionView("resume", "Resume", resume_enabled, "not paused" if admin_enabled and not resume_enabled else disabled_reason),
        RecordActionView("tag", "Apply Tag", admin_enabled and bool(tag_value.strip()), "tag name required" if admin_enabled and not tag_value.strip() else disabled_reason),
        RecordActionView("shutdown", "Shutdown", admin_enabled, disabled_reason),
        RecordActionView("terminate_local", "Terminate Local Process", terminate_enabled, disabled_reason),
    )


def _command_row(outcome: ServiceCommandOutcome) -> RecordCommandRow:
    return RecordCommandRow(
        command_id=outcome.request.command_id,
        command=outcome.request.command.value,
        reply=outcome.status.value,
        observed=str(outcome.payload.get("observed_state", "")),
        resource_path=outcome.resource_path,
        message=outcome.message,
    )


def _monitoring_summary(selected: Optional[ServiceProcessCandidate]) -> Tuple[Tuple[str, str], ...]:
    if selected is None:
        return ()
    rows = []
    current_file = _current_file(selected.details)
    if current_file:
        rows.append(("current_file", current_file))
    for key in ("db_file_size", "rollover_count", "memory_mb", "memory_kb"):
        if key in selected.metrics:
            rows.append((key, str(selected.metrics[key])))
    for key in ("current_db_directory", "db_directory", "sessions", "topics", "last_event", "message", "output_path"):
        if key in selected.details:
            rows.append((key, str(selected.details[key])))
    return tuple(rows)


def _current_file(details: Mapping[str, Any]) -> str:
    current_file = str(details.get("current_file", "")).strip()
    if current_file:
        return current_file
    db_file = str(details.get("db_file", "")).strip()
    if not db_file:
        return ""
    db_directory = str(
        details.get("current_db_directory", "") or details.get("db_directory", "")
    ).strip()
    if os.path.isabs(db_file) or not db_directory:
        return db_file
    normalized_directory = os.path.normpath(db_directory)
    normalized_file = os.path.normpath(db_file)
    if normalized_file == normalized_directory or normalized_file.startswith(normalized_directory + os.sep):
        return db_file
    return os.path.join(db_directory, db_file)


def _readiness_text(readiness: Optional[AdminReadiness]) -> str:
    if readiness is None:
        return "not checked"
    if readiness.ready:
        return "request+reply matched"
    return readiness.message or readiness.status.value


def _target_label(selected: Optional[ServiceProcessCandidate], service: ServiceInstanceRef) -> str:
    if selected is None:
        return "No Recording Service"
    label = selected.display_label or service.name
    if label == service.name:
        return service.name
    return f"{label} ({service.name})"


def _empty_recording_service() -> ServiceInstanceRef:
    return ServiceInstanceRef(ServiceKind.RECORDING, "", 0, 0)


def _launch_command_preview(launch: RecordLaunchViewModel) -> str:
    executable = launch.executable or "rtirecordingservice"
    command = [
        executable,
        "-cfgName", launch.config_name or "<config>",
        "-appName", "<generated>",
        "-remoteAdministrationDomainId", str(launch.admin_domain_id),
        "-remoteMonitoringDomainId", str(launch.monitoring_domain_id),
    ]
    if launch.verbosity:
        command.extend(["-verbosity", launch.verbosity])
    if launch.config_paths:
        command.extend(["-cfgFile", ";".join(launch.config_paths)])
    storage_value = _storage_format_env_value(launch.storage_format)
    command.extend((f"-DDOMAIN_ID={launch.data_domain_id}", f"-DADMIN_DOMAIN_ID={launch.admin_domain_id}"))
    command.append(f"-DREC_LOG_DIR={launch.log_directory}")
    command.append(f"-DREC_STORAGE_FORMAT={storage_value}")
    command.extend((f"-DREC_TOPIC_ALLOW={launch.topic_allow}", f"-DREC_TOPIC_DENY={launch.topic_deny}"))
    command.extend(launch.extra_args)
    return " ".join(shlex.quote(str(part)) for part in command)


def _normalize_storage_format(value: str) -> str:
    text = str(value or "").strip().upper()
    if text in {"JSON", "JSON_SQLITE"}:
        return "JSON"
    return "XCDR"


def _storage_format_env_value(value: str) -> str:
    return "JSON_SQLITE" if _normalize_storage_format(value) == "JSON" else "XCDR_AUTO"
