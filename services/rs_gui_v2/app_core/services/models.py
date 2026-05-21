"""Neutral service DTOs for rs_gui_v2 facades and tests."""

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple
import time
import uuid

from ..events import CommandStatus


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


class ServiceKind(str, Enum):
    """Infrastructure service categories supported by rs_gui_v2."""

    RECORDING = "recording"
    REPLAY = "replay"
    CONVERTER = "converter"
    UNKNOWN = "unknown"


class AdminReadinessStatus(str, Enum):
    """Readiness of the Service Admin request/reply channel."""

    UNKNOWN = "unknown"
    DISCOVERING = "discovering"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    ERROR = "error"


class ServiceCommand(str, Enum):
    """Operator commands represented before any DDS-specific encoding."""

    PAUSE = "pause"
    RESUME = "resume"
    SHUTDOWN = "shutdown"
    TAG = "tag"
    CUSTOM = "custom"


class MonitoringSnapshotKind(str, Enum):
    """Source category for infrastructure service monitoring data."""

    CONFIG = "config"
    EVENT = "event"
    PERIODIC = "periodic"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class ServiceInstanceRef:
    """Stable user-facing reference to one RTI infrastructure service."""

    kind: ServiceKind
    name: str
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0
    config_paths: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ServiceKind):
            object.__setattr__(self, "kind", ServiceKind(self.kind))
        object.__setattr__(self, "admin_domain_id", int(self.admin_domain_id))
        object.__setattr__(self, "monitoring_domain_id", int(self.monitoring_domain_id))
        object.__setattr__(self, "config_paths", tuple(self.config_paths))

    @property
    def key(self) -> str:
        return (
            f"{self.kind.value}:{self.name}:"
            f"admin={self.admin_domain_id}:monitor={self.monitoring_domain_id}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "admin_domain_id": self.admin_domain_id,
            "monitoring_domain_id": self.monitoring_domain_id,
            "config_paths": list(self.config_paths),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceInstanceRef":
        return cls(
            kind=ServiceKind(data.get("kind", ServiceKind.UNKNOWN.value)),
            name=str(data["name"]),
            admin_domain_id=int(data.get("admin_domain_id", 0)),
            monitoring_domain_id=int(data.get("monitoring_domain_id", 0)),
            config_paths=tuple(data.get("config_paths", ())),
        )


@dataclass(frozen=True)
class AdminReadiness:
    """Snapshot of Service Admin discovery state for one service."""

    service: ServiceInstanceRef
    status: AdminReadinessStatus = AdminReadinessStatus.UNKNOWN
    matched_request_writers: int = 0
    matched_reply_readers: int = 0
    message: str = ""
    checked_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.status, AdminReadinessStatus):
            object.__setattr__(self, "status", AdminReadinessStatus(self.status))
        object.__setattr__(self, "matched_request_writers", int(self.matched_request_writers))
        object.__setattr__(self, "matched_reply_readers", int(self.matched_reply_readers))

    @property
    def ready(self) -> bool:
        return self.status == AdminReadinessStatus.READY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service.to_dict(),
            "status": self.status.value,
            "matched_request_writers": self.matched_request_writers,
            "matched_reply_readers": self.matched_reply_readers,
            "message": self.message,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdminReadiness":
        return cls(
            service=ServiceInstanceRef.from_dict(data["service"]),
            status=AdminReadinessStatus(data.get("status", AdminReadinessStatus.UNKNOWN.value)),
            matched_request_writers=int(data.get("matched_request_writers", 0)),
            matched_reply_readers=int(data.get("matched_reply_readers", 0)),
            message=str(data.get("message", "")),
            checked_at=float(data.get("checked_at", time.time())),
        )


@dataclass(frozen=True)
class ServiceCommandRequest:
    """Service command intent before it is encoded for any transport."""

    service: ServiceInstanceRef
    command: ServiceCommand
    parameters: Mapping[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    timeout_sec: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, ServiceCommand):
            object.__setattr__(self, "command", ServiceCommand(self.command))
        object.__setattr__(self, "parameters", _frozen_mapping(self.parameters))

    def with_timeout(self, timeout_sec: Optional[float]) -> "ServiceCommandRequest":
        return replace(self, timeout_sec=timeout_sec)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service.to_dict(),
            "command": self.command.value,
            "parameters": dict(self.parameters),
            "command_id": self.command_id,
            "created_at": self.created_at,
            "timeout_sec": self.timeout_sec,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceCommandRequest":
        return cls(
            service=ServiceInstanceRef.from_dict(data["service"]),
            command=ServiceCommand(data["command"]),
            parameters=data.get("parameters", {}),
            command_id=str(data["command_id"]),
            created_at=float(data["created_at"]),
            timeout_sec=data.get("timeout_sec"),
        )


@dataclass(frozen=True)
class ServiceCommandOutcome:
    """Result from a service command after dispatch or failure."""

    request: ServiceCommandRequest
    status: CommandStatus
    message: str = ""
    native_retcode: Optional[int] = None
    resource_path: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.status, CommandStatus):
            object.__setattr__(self, "status", CommandStatus(self.status))
        if self.native_retcode is not None:
            object.__setattr__(self, "native_retcode", int(self.native_retcode))
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))

    @property
    def ok(self) -> bool:
        return self.status in (CommandStatus.ACKNOWLEDGED, CommandStatus.OBSERVED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "status": self.status.value,
            "message": self.message,
            "native_retcode": self.native_retcode,
            "resource_path": self.resource_path,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceCommandOutcome":
        return cls(
            request=ServiceCommandRequest.from_dict(data["request"]),
            status=CommandStatus(data["status"]),
            message=str(data.get("message", "")),
            native_retcode=data.get("native_retcode"),
            resource_path=str(data.get("resource_path", "")),
            payload=data.get("payload", {}),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Normalized infrastructure-service monitoring update."""

    service: ServiceInstanceRef
    kind: MonitoringSnapshotKind
    state: str = "unknown"
    metrics: Mapping[str, Any] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)
    observed_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MonitoringSnapshotKind):
            object.__setattr__(self, "kind", MonitoringSnapshotKind(self.kind))
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics))
        object.__setattr__(self, "details", _frozen_mapping(self.details))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service.to_dict(),
            "kind": self.kind.value,
            "state": self.state,
            "metrics": dict(self.metrics),
            "details": dict(self.details),
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MonitoringSnapshot":
        return cls(
            service=ServiceInstanceRef.from_dict(data["service"]),
            kind=MonitoringSnapshotKind(data["kind"]),
            state=str(data.get("state", "unknown")),
            metrics=data.get("metrics", {}),
            details=data.get("details", {}),
            observed_at=float(data.get("observed_at", time.time())),
        )


@dataclass(frozen=True)
class ServiceStateSnapshot:
    """Operator-facing state composed from commands and monitoring."""

    service: ServiceInstanceRef
    requested_state: str = "unknown"
    acknowledged_state: str = "unknown"
    observed_state: str = "unknown"
    last_command_id: str = ""
    last_monitoring_kind: MonitoringSnapshotKind = MonitoringSnapshotKind.SYNTHETIC
    metrics: Mapping[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.last_monitoring_kind, MonitoringSnapshotKind):
            object.__setattr__(
                self, "last_monitoring_kind", MonitoringSnapshotKind(self.last_monitoring_kind)
            )
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics))

    def with_monitoring(self, snapshot: MonitoringSnapshot) -> "ServiceStateSnapshot":
        return replace(
            self,
            observed_state=snapshot.state,
            last_monitoring_kind=snapshot.kind,
            metrics=snapshot.metrics,
            updated_at=snapshot.observed_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service.to_dict(),
            "requested_state": self.requested_state,
            "acknowledged_state": self.acknowledged_state,
            "observed_state": self.observed_state,
            "last_command_id": self.last_command_id,
            "last_monitoring_kind": self.last_monitoring_kind.value,
            "metrics": dict(self.metrics),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ServiceStateSnapshot":
        return cls(
            service=ServiceInstanceRef.from_dict(data["service"]),
            requested_state=str(data.get("requested_state", "unknown")),
            acknowledged_state=str(data.get("acknowledged_state", "unknown")),
            observed_state=str(data.get("observed_state", "unknown")),
            last_command_id=str(data.get("last_command_id", "")),
            last_monitoring_kind=MonitoringSnapshotKind(
                data.get("last_monitoring_kind", MonitoringSnapshotKind.SYNTHETIC.value)
            ),
            metrics=data.get("metrics", {}),
            updated_at=float(data.get("updated_at", time.time())),
        )