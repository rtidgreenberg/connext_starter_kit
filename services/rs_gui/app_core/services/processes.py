"""DDS-free local process launch/control helpers for RTI services."""

from dataclasses import dataclass, field, replace
from enum import Enum
import os
import signal
import socket
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Tuple
import uuid

from ..discovery import DiscoveredEndpoint
from .candidates import build_service_candidate_selection, candidate_from_control_identity
from .control import (
    ServiceCandidateSelection,
    ServiceControlIdentity,
    ServiceLaunchIntent,
    ServiceProcessCandidate,
)
from .models import MonitoringSnapshot, ServiceKind


def _frozen_mapping(value: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return MappingProxyType(dict(value or {}))


def _tuple_of_text(value: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(str(item) for item in value)


class ServiceProcessLaunchState(str, Enum):
    """Local runtime state of a GUI-launched infrastructure service process."""

    STARTING = "starting"
    RUNNING = "running"
    EXITED = "exited"
    START_FAILED = "start_failed"
    TERMINATE_REQUESTED = "terminate_requested"


class ServiceProcessTerminationStatus(str, Enum):
    """Outcome of a guarded local process termination request."""

    REQUESTED = "requested"
    NOT_ALLOWED = "not_allowed"
    NOT_FOUND = "not_found"
    ALREADY_EXITED = "already_exited"


@dataclass(frozen=True)
class ServiceProcessLaunchRequest:
    """Runtime request for starting an RTI infrastructure service process."""

    intent: ServiceLaunchIntent
    config_name: str
    executable: str = ""
    working_dir: str = ""
    verbosity: str = "ERROR:ERROR"
    environment: Mapping[str, str] = field(default_factory=dict)
    extra_args: Tuple[str, ...] = field(default_factory=tuple)
    domain_id_base: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ServiceLaunchIntent):
            object.__setattr__(self, "intent", ServiceLaunchIntent.from_dict(self.intent))
        object.__setattr__(self, "config_name", str(self.config_name))
        object.__setattr__(self, "executable", str(self.executable))
        object.__setattr__(self, "working_dir", str(self.working_dir))
        object.__setattr__(self, "verbosity", str(self.verbosity))
        object.__setattr__(self, "environment", _frozen_mapping(self.environment))
        object.__setattr__(self, "extra_args", _tuple_of_text(self.extra_args))
        if self.domain_id_base is not None:
            object.__setattr__(self, "domain_id_base", int(self.domain_id_base))
        if not self.config_name:
            raise ValueError("config_name is required to launch an RTI service")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "config_name": self.config_name,
            "executable": self.executable,
            "working_dir": self.working_dir,
            "verbosity": self.verbosity,
            "environment": dict(self.environment),
            "extra_args": list(self.extra_args),
            "domain_id_base": self.domain_id_base,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceProcessLaunchRequest":
        return cls(
            intent=ServiceLaunchIntent.from_dict(data["intent"]),
            config_name=str(data["config_name"]),
            executable=str(data.get("executable", "")),
            working_dir=str(data.get("working_dir", "")),
            verbosity=str(data.get("verbosity", "ERROR:ERROR")),
            environment=data.get("environment", {}),
            extra_args=tuple(data.get("extra_args", ())),
            domain_id_base=data.get("domain_id_base"),
        )


@dataclass(frozen=True)
class ServiceProcessLaunch:
    """Snapshot of a GUI-created local service process."""

    launch_id: str
    identity: ServiceControlIdentity
    request: ServiceProcessLaunchRequest
    command_line: Tuple[str, ...]
    pid: Optional[int]
    hostname: str
    state: ServiceProcessLaunchState = ServiceProcessLaunchState.STARTING
    returncode: Optional[int] = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    termination_requested: bool = False
    message: str = ""
    output_path: str = ""
    output_tail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, ServiceProcessLaunchState):
            object.__setattr__(self, "state", ServiceProcessLaunchState(self.state))
        object.__setattr__(self, "command_line", _tuple_of_text(self.command_line))
        if self.pid is not None:
            object.__setattr__(self, "pid", int(self.pid))
        if self.returncode is not None:
            object.__setattr__(self, "returncode", int(self.returncode))
        object.__setattr__(self, "termination_requested", bool(self.termination_requested))

    @property
    def alive(self) -> bool:
        return self.state in (
            ServiceProcessLaunchState.STARTING,
            ServiceProcessLaunchState.RUNNING,
            ServiceProcessLaunchState.TERMINATE_REQUESTED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "identity": self.identity.to_dict(),
            "request": self.request.to_dict(),
            "command_line": list(self.command_line),
            "pid": self.pid,
            "hostname": self.hostname,
            "state": self.state.value,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "termination_requested": self.termination_requested,
            "message": self.message,
            "output_path": self.output_path,
            "output_tail": self.output_tail,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceProcessLaunch":
        return cls(
            launch_id=str(data["launch_id"]),
            identity=ServiceControlIdentity.from_dict(data["identity"]),
            request=ServiceProcessLaunchRequest.from_dict(data["request"]),
            command_line=tuple(data.get("command_line", ())),
            pid=data.get("pid"),
            hostname=str(data.get("hostname", "")),
            state=ServiceProcessLaunchState(data.get("state", ServiceProcessLaunchState.STARTING.value)),
            returncode=data.get("returncode"),
            started_at=float(data.get("started_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            termination_requested=bool(data.get("termination_requested", False)),
            message=str(data.get("message", "")),
            output_path=str(data.get("output_path", "")),
            output_tail=str(data.get("output_tail", "")),
        )


@dataclass(frozen=True)
class ServiceProcessTerminationOutcome:
    """Result from requesting guarded local process termination."""

    status: ServiceProcessTerminationStatus
    candidate_id: str = ""
    launch_id: str = ""
    pid: Optional[int] = None
    message: str = ""
    output_path: str = ""
    output_tail: str = ""
    requested_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ServiceProcessTerminationStatus):
            object.__setattr__(self, "status", ServiceProcessTerminationStatus(self.status))
        if self.pid is not None:
            object.__setattr__(self, "pid", int(self.pid))

    @property
    def ok(self) -> bool:
        return self.requested

    @property
    def requested(self) -> bool:
        return self.status == ServiceProcessTerminationStatus.REQUESTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "candidate_id": self.candidate_id,
            "launch_id": self.launch_id,
            "pid": self.pid,
            "message": self.message,
            "output_path": self.output_path,
            "output_tail": self.output_tail,
            "requested_at": self.requested_at,
        }


class ServiceProcessHandle(Protocol):
    """Minimal process-handle contract used by the local process manager."""

    pid: int

    def poll(self) -> Optional[int]:
        """Return a process return code, or None when still running."""

    def terminate(self) -> None:
        """Request normal local process termination."""

    def kill(self) -> None:
        """Request forceful local process termination."""


class ServiceProcessSpawner(Protocol):
    """Process-spawn contract so tests can avoid starting real services."""

    def start(
            self,
            command_line: Sequence[str],
            working_dir: str = "",
            environment: Optional[Mapping[str, str]] = None,
    ) -> ServiceProcessHandle:
        """Start a local process and return a handle."""


class SubprocessServiceProcessSpawner:
    """Standard-library spawner used by production wiring."""

    def __init__(self, log_dir: str = "services/rs_gui/service_logs") -> None:
        self._log_dir = _workspace_relative_path(str(log_dir))

    def start(
            self,
            command_line: Sequence[str],
            working_dir: str = "",
            environment: Optional[Mapping[str, str]] = None,
    ) -> ServiceProcessHandle:
        env = os.environ.copy()
        env.update(dict(environment or {}))
        os.makedirs(self._log_dir, exist_ok=True)
        output_path = os.path.join(self._log_dir, _service_log_filename(command_line))
        output_file = open(output_path, "ab", buffering=0)
        try:
            handle = subprocess.Popen(
                list(command_line),
                cwd=working_dir or None,
                env=env,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            output_file.close()
            raise
        return _SubprocessServiceProcessHandle(handle, output_file, output_path)


class _SubprocessServiceProcessHandle:
    def __init__(self, handle, output_file, output_path: str) -> None:
        self._handle = handle
        self._output_file = output_file
        self._output_lock = threading.Lock()
        self.output_path = str(output_path)
        self._reap_thread = threading.Thread(target=self._wait_for_exit, daemon=True)
        self._reap_thread.start()

    @property
    def pid(self) -> int:
        return int(self._handle.pid)

    def poll(self) -> Optional[int]:
        returncode = self._handle.poll()
        if returncode is not None:
            self._close_output()
        return returncode

    def terminate(self) -> None:
        try:
            os.killpg(os.getpgid(self._handle.pid), signal.SIGTERM)
        except Exception:
            self._handle.terminate()

    def kill(self) -> None:
        try:
            os.killpg(os.getpgid(self._handle.pid), signal.SIGKILL)
        except Exception:
            self._handle.kill()

    def _close_output(self) -> None:
        with self._output_lock:
            if not self._output_file.closed:
                self._output_file.close()

    def _wait_for_exit(self) -> None:
        try:
            self._handle.wait()
        except Exception:
            return
        self._close_output()


class ServiceProcessManager:
    """Launch and track GUI-owned local RTI service processes."""

    def __init__(
            self,
            spawner: Optional[ServiceProcessSpawner] = None,
            hostname: Optional[str] = None,
            clock=time.time,
    ) -> None:
        self._spawner = spawner or SubprocessServiceProcessSpawner()
        self._hostname = hostname or socket.gethostname()
        self._clock = clock
        self._launches: Dict[str, ServiceProcessLaunch] = {}
        self._handles: Dict[str, ServiceProcessHandle] = {}

    def launch(
            self,
            request: ServiceProcessLaunchRequest,
            launch_id: str = "",
            session_guid: str = "",
    ) -> ServiceProcessLaunch:
        identity = ServiceControlIdentity(
            intent=request.intent,
            session_guid=session_guid or str(uuid.uuid4()),
            created_at=self._clock(),
        )
        actual_launch_id = launch_id or str(uuid.uuid4())
        command_line = build_service_process_command(identity, request)
        started_at = self._clock()
        try:
            handle = self._spawner.start(
                command_line,
                working_dir=request.working_dir,
                environment=request.environment,
            )
            output_path = str(getattr(handle, "output_path", ""))
        except Exception as exc:
            launch = ServiceProcessLaunch(
                launch_id=actual_launch_id,
                identity=identity,
                request=request,
                command_line=command_line,
                pid=None,
                hostname=self._hostname,
                state=ServiceProcessLaunchState.START_FAILED,
                started_at=started_at,
                updated_at=self._clock(),
                message=str(exc),
            )
            self._launches[actual_launch_id] = launch
            return launch

        launch = ServiceProcessLaunch(
            launch_id=actual_launch_id,
            identity=identity,
            request=request,
            command_line=command_line,
            pid=handle.pid,
            hostname=self._hostname,
            state=ServiceProcessLaunchState.STARTING,
            started_at=started_at,
            updated_at=started_at,
            output_path=output_path,
        )
        self._handles[actual_launch_id] = handle
        self._launches[actual_launch_id] = launch
        return launch

    def refresh(self, launch_id: str) -> Optional[ServiceProcessLaunch]:
        launch = self._launches.get(launch_id)
        if launch is None:
            return None
        handle = self._handles.get(launch_id)
        if handle is None:
            return launch
        returncode = handle.poll()
        state = launch.state
        message = launch.message
        output_tail = _read_tail(launch.output_path)
        if returncode is None:
            if state == ServiceProcessLaunchState.STARTING:
                state = ServiceProcessLaunchState.RUNNING
        else:
            state = ServiceProcessLaunchState.EXITED
            message = f"process exited with return code {returncode}"
            if output_tail:
                message = f"{message}; see {launch.output_path}"
        updated = replace(
            launch,
            state=state,
            returncode=returncode,
            updated_at=self._clock(),
            message=message,
            output_tail=output_tail,
        )
        self._launches[launch_id] = updated
        return updated

    def launches(self) -> Tuple[ServiceProcessLaunch, ...]:
        return tuple(
            self.refresh(launch_id) or launch
            for launch_id, launch in sorted(self._launches.items())
        )

    def candidates(self) -> Tuple[ServiceProcessCandidate, ...]:
        return tuple(candidate_from_process_launch(launch) for launch in self.launches())

    def candidate_selection(
            self,
            service,
            monitoring_snapshots: Iterable[MonitoringSnapshot] = (),
            discovery_endpoints: Iterable[DiscoveredEndpoint] = (),
            selected_candidate_id: str = "",
            display_label: str = "",
    ) -> ServiceCandidateSelection:
        return build_service_candidate_selection(
            service,
            launch_candidates=self.candidates(),
            monitoring_snapshots=monitoring_snapshots,
            discovery_endpoints=discovery_endpoints,
            selected_candidate_id=selected_candidate_id,
            display_label=display_label,
        )

    def request_local_termination(
            self,
            selection: ServiceCandidateSelection,
            graceful_shutdown_failed: bool,
            candidate_id: str = "",
            local_hostnames: Iterable[str] = (),
    ) -> ServiceProcessTerminationOutcome:
        selected = selection.selected_candidate
        if candidate_id:
            selected = selection.select(candidate_id).selected_candidate
        if selected is None:
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.NOT_ALLOWED,
                message="no candidate selected",
            )

        availability = ServiceCandidateSelection(
            candidates=selection.candidates,
            selected_candidate_id=selected.candidate_id,
        ).control_availability(
            local_hostnames=tuple(local_hostnames) or (self._hostname,),
            graceful_shutdown_failed=graceful_shutdown_failed,
        )
        output_path = str(selected.details.get("output_path", ""))
        output_tail = str(selected.details.get("output_tail", ""))
        if not availability.process_terminate_enabled:
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.NOT_ALLOWED,
                candidate_id=selected.candidate_id,
                launch_id=selected.launch_id,
                pid=selected.pid,
                message="; ".join(availability.reasons),
                output_path=output_path,
                output_tail=output_tail,
                requested_at=self._clock(),
            )

        launch_id = selected.launch_id or selected.candidate_id
        handle = self._handles.get(launch_id)
        if handle is None:
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.NOT_FOUND,
                candidate_id=selected.candidate_id,
                launch_id=launch_id,
                pid=selected.pid,
                message="local process handle not found",
                output_path=output_path,
                output_tail=output_tail,
                requested_at=self._clock(),
            )
        returncode = handle.poll()
        if returncode is not None:
            launch = self._launches[launch_id]
            output_path = output_path or launch.output_path
            output_tail = output_tail or _read_tail(output_path)
            self._launches[launch_id] = replace(
                launch,
                state=ServiceProcessLaunchState.EXITED,
                returncode=returncode,
                updated_at=self._clock(),
                message=f"process exited with return code {returncode}",
                output_tail=output_tail,
            )
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.ALREADY_EXITED,
                candidate_id=selected.candidate_id,
                launch_id=launch_id,
                pid=selected.pid,
                message=f"process already exited with return code {returncode}",
                output_path=output_path,
                output_tail=output_tail,
                requested_at=self._clock(),
            )

        handle.terminate()
        self._launches[launch_id] = replace(
            self._launches[launch_id],
            state=ServiceProcessLaunchState.TERMINATE_REQUESTED,
            termination_requested=True,
            updated_at=self._clock(),
            message="local termination requested after graceful shutdown failure",
        )
        return ServiceProcessTerminationOutcome(
            ServiceProcessTerminationStatus.REQUESTED,
            candidate_id=selected.candidate_id,
            launch_id=launch_id,
            pid=selected.pid,
            message="local termination requested",
            output_path=output_path,
            output_tail=output_tail,
            requested_at=self._clock(),
        )

    def request_local_kill(
            self,
            selection: ServiceCandidateSelection,
            candidate_id: str = "",
    ) -> ServiceProcessTerminationOutcome:
        selected = selection.selected_candidate
        if candidate_id:
            selected = selection.select(candidate_id).selected_candidate
        if selected is None:
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.NOT_ALLOWED,
                message="no candidate selected",
            )

        launch_id = selected.launch_id or selected.candidate_id
        handle = self._handles.get(launch_id)
        output_path = str(selected.details.get("output_path", ""))
        output_tail = str(selected.details.get("output_tail", ""))
        if handle is None:
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.NOT_FOUND,
                candidate_id=selected.candidate_id,
                launch_id=launch_id,
                pid=selected.pid,
                message="local process handle not found",
                output_path=output_path,
                output_tail=output_tail,
                requested_at=self._clock(),
            )
        returncode = handle.poll()
        if returncode is not None:
            launch = self._launches[launch_id]
            output_path = output_path or launch.output_path
            output_tail = output_tail or _read_tail(output_path)
            self._launches[launch_id] = replace(
                launch,
                state=ServiceProcessLaunchState.EXITED,
                returncode=returncode,
                updated_at=self._clock(),
                message=f"process exited with return code {returncode}",
                output_tail=output_tail,
            )
            return ServiceProcessTerminationOutcome(
                ServiceProcessTerminationStatus.ALREADY_EXITED,
                candidate_id=selected.candidate_id,
                launch_id=launch_id,
                pid=selected.pid,
                message=f"process already exited with return code {returncode}",
                output_path=output_path,
                output_tail=output_tail,
                requested_at=self._clock(),
            )

        kill = getattr(handle, "kill", None)
        if callable(kill):
            kill()
        else:
            handle.terminate()
        self._launches[launch_id] = replace(
            self._launches[launch_id],
            state=ServiceProcessLaunchState.TERMINATE_REQUESTED,
            termination_requested=True,
            updated_at=self._clock(),
            message="local kill requested after failed termination",
        )
        return ServiceProcessTerminationOutcome(
            ServiceProcessTerminationStatus.REQUESTED,
            candidate_id=selected.candidate_id,
            launch_id=launch_id,
            pid=selected.pid,
            message="local kill requested",
            output_path=output_path,
            output_tail=output_tail,
            requested_at=self._clock(),
        )


def candidate_from_process_launch(launch: ServiceProcessLaunch) -> ServiceProcessCandidate:
    """Build selector-ready process evidence from a local launch snapshot."""

    details = {
        "executable": launch.command_line[0] if launch.command_line else "",
        "command_line": list(launch.command_line),
        "admin_resource_name": launch.request.config_name,
        "config_name": launch.request.config_name,
        "working_dir": launch.request.working_dir,
        "launch_state": launch.state.value,
        "termination_requested": launch.termination_requested,
    }
    if launch.output_path:
        details["output_path"] = launch.output_path
    if launch.output_tail:
        details["output_tail"] = launch.output_tail
    if launch.returncode is not None:
        details["returncode"] = launch.returncode
    if launch.message:
        details["message"] = launch.message
    candidate = candidate_from_control_identity(
        launch.identity,
        launch_id=launch.launch_id,
        pid=launch.pid,
        hostname=launch.hostname,
        observed_state=launch.state.value,
        details=details,
        observed_at=launch.updated_at,
    )
    return replace(
        candidate,
        alive=launch.alive,
        first_seen_at=launch.started_at,
        last_seen_at=launch.updated_at,
    )


def build_service_process_command(
        identity: ServiceControlIdentity,
        request: ServiceProcessLaunchRequest,
) -> Tuple[str, ...]:
    """Build the RTI service command line without invoking a shell."""

    executable = request.executable or default_service_executable(
        identity.intent.kind,
        nddshome=str(request.environment.get("NDDSHOME", "")),
    )
    command = [executable, "-cfgName", request.config_name]
    if _supports_app_name(identity.intent.kind):
        command.extend(["-appName", identity.control_name])
    if request.domain_id_base is not None:
        command.extend(["-domainIdBase", str(request.domain_id_base)])
    if _supports_remote_admin(identity.intent.kind):
        command.extend(["-remoteAdministrationDomainId", str(identity.intent.admin_domain_id)])
        command.extend(["-remoteMonitoringDomainId", str(identity.intent.monitoring_domain_id)])
    if request.verbosity:
        command.extend(["-verbosity", request.verbosity])
    if identity.intent.config_paths:
        resolved_config_paths = tuple(_resolve_launch_path(path) for path in identity.intent.config_paths)
        command.extend(["-cfgFile", ";".join(resolved_config_paths)])
    command.extend(request.extra_args)
    return tuple(command)


def default_service_executable(kind: ServiceKind, nddshome: str = "") -> str:
    """Return the default executable path or binary name for a service kind."""

    if not isinstance(kind, ServiceKind):
        kind = ServiceKind(kind)
    binary_by_kind = {
        ServiceKind.RECORDING: "rtirecordingservice",
        ServiceKind.REPLAY: "rtireplayservice",
        ServiceKind.CONVERTER: "rticonverter",
    }
    binary = binary_by_kind.get(kind)
    if not binary:
        raise ValueError(f"No RTI service executable is known for {kind.value}")
    home = nddshome or os.environ.get("NDDSHOME", "")
    if home:
        return os.path.join(home, "bin", binary)
    return binary


def _service_log_filename(command_line: Sequence[str]) -> str:
    executable = os.path.basename(str(command_line[0])) if command_line else "service"
    safe_executable = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in executable)
    return f"{safe_executable}_{int(time.time() * 1000)}_{os.getpid()}.log"


def _workspace_relative_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    root = os.path.abspath(os.path.dirname(__file__))
    for _ in range(4):
        root = os.path.dirname(root)
    return os.path.join(root, path)


def _resolve_launch_path(path: str) -> str:
    normalized = str(path).strip()
    if not normalized or os.path.isabs(normalized):
        return normalized
    cwd_candidate = os.path.abspath(normalized)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    return _workspace_relative_path(normalized)


def _read_tail(path: str, max_bytes: int = 8192) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - int(max_bytes)), os.SEEK_SET)
            return file.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _supports_app_name(kind: ServiceKind) -> bool:
    return kind in (ServiceKind.RECORDING, ServiceKind.REPLAY)


def _supports_remote_admin(kind: ServiceKind) -> bool:
    return kind in (ServiceKind.RECORDING, ServiceKind.REPLAY)
