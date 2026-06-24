"""DDS-free service identity, candidate selection, and control-state models."""

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
import time
import uuid

from .models import ServiceInstanceRef, ServiceKind


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _tuple_of_text(value: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(str(item) for item in value)


def _short_guid(value: str) -> str:
    compact = re.sub(r"[^0-9A-Fa-f]", "", value)
    return (compact or value.replace("-", ""))[:8].lower()


def service_label_prefix(label: str, fallback: str = "service") -> str:
    """Return a Service Admin-name-safe prefix derived from an operator label."""

    normalized = re.sub(r"[^0-9A-Za-z]+", "_", label.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"svc_{normalized}"
    return normalized


def service_admin_target_key(service: ServiceInstanceRef) -> str:
    """Key for the Service Admin addressable target."""

    return f"{service.kind.value}:{service.name}:admin={service.admin_domain_id}"


class ServiceCandidateSource(str, Enum):
    """How a service process candidate was observed."""

    GUI_LAUNCH = "gui_launch"
    DISCOVERY = "discovery"
    MONITORING = "monitoring"
    RESTORED = "restored"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServiceLaunchIntent:
    """Persistable operator intent for launching a service process."""

    kind: ServiceKind
    label: str
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0
    config_paths: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ServiceKind):
            object.__setattr__(self, "kind", ServiceKind(self.kind))
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "config_paths", _tuple_of_text(self.config_paths))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "admin_domain_id": self.admin_domain_id,
            "monitoring_domain_id": self.monitoring_domain_id,
            "config_paths": list(self.config_paths),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceLaunchIntent":
        return cls(
            kind=ServiceKind(data.get("kind", ServiceKind.UNKNOWN.value)),
            label=str(data["label"]),
            admin_domain_id=int(data.get("admin_domain_id", 0)),
            monitoring_domain_id=int(data.get("monitoring_domain_id", 0)),
            config_paths=tuple(data.get("config_paths", ())),
        )


@dataclass(frozen=True)
class ServiceControlIdentity:
    """Runtime identity used to address a GUI-created service process."""

    intent: ServiceLaunchIntent
    session_guid: str = field(default_factory=lambda: str(uuid.uuid4()))
    control_name: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ServiceLaunchIntent):
            object.__setattr__(self, "intent", ServiceLaunchIntent.from_dict(self.intent))
        if not self.control_name:
            prefix = service_label_prefix(self.intent.label, self.intent.kind.value)
            object.__setattr__(self, "control_name", f"{prefix}_{_short_guid(self.session_guid)}")

    @property
    def service_ref(self) -> ServiceInstanceRef:
        return ServiceInstanceRef(
            kind=self.intent.kind,
            name=self.control_name,
            admin_domain_id=self.intent.admin_domain_id,
            monitoring_domain_id=self.intent.monitoring_domain_id,
            config_paths=self.intent.config_paths,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "session_guid": self.session_guid,
            "control_name": self.control_name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceControlIdentity":
        return cls(
            intent=ServiceLaunchIntent.from_dict(data["intent"]),
            session_guid=str(data["session_guid"]),
            control_name=str(data.get("control_name", "")),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(frozen=True)
class ServiceProcessCandidate:
    """One launched or discovered process that may correspond to a service target."""

    candidate_id: str
    service: ServiceInstanceRef
    source: ServiceCandidateSource = ServiceCandidateSource.UNKNOWN
    display_label: str = ""
    launch_id: str = ""
    pid: Optional[int] = None
    hostname: str = ""
    participant_key: str = ""
    participant_name: str = ""
    application_guid: str = ""
    config_paths: Tuple[str, ...] = field(default_factory=tuple)
    observed_state: str = "unknown"
    metrics: Mapping[str, Any] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)
    alive: bool = True
    owns_process: bool = False
    confidence: float = 0.0
    first_seen_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.source, ServiceCandidateSource):
            object.__setattr__(self, "source", ServiceCandidateSource(self.source))
        if self.pid is not None:
            object.__setattr__(self, "pid", int(self.pid))
        object.__setattr__(self, "config_paths", _tuple_of_text(self.config_paths))
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics))
        object.__setattr__(self, "details", _frozen_mapping(self.details))
        object.__setattr__(self, "alive", bool(self.alive))
        object.__setattr__(self, "owns_process", bool(self.owns_process))
        object.__setattr__(self, "confidence", float(self.confidence))

    @property
    def admin_target_key(self) -> str:
        return service_admin_target_key(self.service)

    @property
    def local_process_known(self) -> bool:
        return self.pid is not None and (self.owns_process or bool(self.hostname))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "service": self.service.to_dict(),
            "source": self.source.value,
            "display_label": self.display_label,
            "launch_id": self.launch_id,
            "pid": self.pid,
            "hostname": self.hostname,
            "participant_key": self.participant_key,
            "participant_name": self.participant_name,
            "application_guid": self.application_guid,
            "config_paths": list(self.config_paths),
            "observed_state": self.observed_state,
            "metrics": dict(self.metrics),
            "details": dict(self.details),
            "alive": self.alive,
            "owns_process": self.owns_process,
            "confidence": self.confidence,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceProcessCandidate":
        return cls(
            candidate_id=str(data["candidate_id"]),
            service=ServiceInstanceRef.from_dict(data["service"]),
            source=ServiceCandidateSource(data.get("source", ServiceCandidateSource.UNKNOWN.value)),
            display_label=str(data.get("display_label", "")),
            launch_id=str(data.get("launch_id", "")),
            pid=data.get("pid"),
            hostname=str(data.get("hostname", "")),
            participant_key=str(data.get("participant_key", "")),
            participant_name=str(data.get("participant_name", "")),
            application_guid=str(data.get("application_guid", "")),
            config_paths=tuple(data.get("config_paths", ())),
            observed_state=str(data.get("observed_state", "unknown")),
            metrics=data.get("metrics", {}),
            details=data.get("details", {}),
            alive=bool(data.get("alive", True)),
            owns_process=bool(data.get("owns_process", False)),
            confidence=float(data.get("confidence", 0.0)),
            first_seen_at=float(data.get("first_seen_at", time.time())),
            last_seen_at=float(data.get("last_seen_at", time.time())),
        )


@dataclass(frozen=True)
class ServiceControlAvailability:
    """Controls that may be shown for the selected candidate."""

    service_admin_enabled: bool
    process_terminate_enabled: bool
    duplicate_admin_target: bool = False
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_admin_enabled", bool(self.service_admin_enabled))
        object.__setattr__(self, "process_terminate_enabled", bool(self.process_terminate_enabled))
        object.__setattr__(self, "duplicate_admin_target", bool(self.duplicate_admin_target))
        object.__setattr__(self, "reasons", _tuple_of_text(self.reasons))


@dataclass(frozen=True)
class ServiceCandidateSelection:
    """Snapshot backing a Record/Replay service selector UI."""

    candidates: Tuple[ServiceProcessCandidate, ...] = field(default_factory=tuple)
    selected_candidate_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))

    @property
    def selected_candidate(self) -> Optional[ServiceProcessCandidate]:
        if self.selected_candidate_id:
            for candidate in self.candidates:
                if candidate.candidate_id == self.selected_candidate_id or candidate.launch_id == self.selected_candidate_id:
                    return candidate
        for candidate in self.candidates:
            if candidate.alive:
                return candidate
        return self.candidates[0] if self.candidates else None

    def select(self, candidate_id: str) -> "ServiceCandidateSelection":
        selected_id = ""
        for candidate in self.candidates:
            if candidate.candidate_id == candidate_id or candidate.launch_id == candidate_id:
                selected_id = candidate.candidate_id
                break
        if not selected_id:
            raise ValueError(f"Unknown service candidate: {candidate_id}")
        return ServiceCandidateSelection(
            candidates=self.candidates,
            selected_candidate_id=selected_id,
        )

    def candidates_for_admin_target(self, service: ServiceInstanceRef) -> Tuple[ServiceProcessCandidate, ...]:
        target_key = service_admin_target_key(service)
        return tuple(
            candidate for candidate in self.candidates
            if candidate.alive and candidate.admin_target_key == target_key
        )

    def control_availability(
            self,
            local_hostnames: Iterable[str] = (),
            graceful_shutdown_failed: bool = False,
    ) -> ServiceControlAvailability:
        selected = self.selected_candidate
        if selected is None:
            return ServiceControlAvailability(False, False, reasons=("no candidate selected",))

        local_names = {name.lower() for name in local_hostnames if name}
        same_target = self.candidates_for_admin_target(selected.service)
        duplicate_admin_target = len(same_target) > 1
        reasons = []

        service_admin_enabled = selected.alive and not duplicate_admin_target
        if duplicate_admin_target:
            reasons.append("duplicate service admin target")
        if not selected.alive:
            reasons.append("candidate is not alive")

        hostname = selected.hostname.lower()
        local_host_match = bool(hostname and hostname in local_names)
        local_process_verified = selected.owns_process or local_host_match
        launch_state = str(selected.details.get("launch_state", "")).strip().lower()
        local_launch_active = selected.owns_process and launch_state not in {"exited", "start_failed"}
        process_terminate_enabled = (
            (selected.alive or local_launch_active)
            and graceful_shutdown_failed
            and selected.pid is not None
            and local_process_verified
        )
        if graceful_shutdown_failed and selected.pid is None:
            reasons.append("no process id available")
        elif graceful_shutdown_failed and selected.pid is not None and not local_process_verified:
            reasons.append("process is not verified as local")
        elif not graceful_shutdown_failed:
            reasons.append("process termination requires failed graceful shutdown")

        return ServiceControlAvailability(
            service_admin_enabled=service_admin_enabled,
            process_terminate_enabled=process_terminate_enabled,
            duplicate_admin_target=duplicate_admin_target,
            reasons=tuple(reasons),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_candidate_id": self.selected_candidate_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceCandidateSelection":
        return cls(
            candidates=tuple(
                ServiceProcessCandidate.from_dict(candidate)
                for candidate in data.get("candidates", ())
            ),
            selected_candidate_id=str(data.get("selected_candidate_id", "")),
        )
