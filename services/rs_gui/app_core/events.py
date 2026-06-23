"""Typed command and event models for the rs_gui headless core."""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional
import time
import uuid


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


class LifecyclePhase(str, Enum):
    """Runtime lifecycle phases owned by the headless app core."""

    BOOTSTRAPPING = "bootstrapping"
    CONFIGURED = "configured"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class CommandStatus(str, Enum):
    """Command execution state independent of DDS-specific return codes."""

    REQUESTED = "requested"
    ACKNOWLEDGED = "acknowledged"
    OBSERVED = "observed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True)
class AppCommand:
    """User or system intent queued for app-core processing."""

    command_type: str
    target: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    timeout_sec: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "target": self.target,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "timeout_sec": self.timeout_sec,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AppCommand":
        return cls(
            command_type=str(data["command_type"]),
            target=str(data.get("target", "")),
            payload=data.get("payload", {}),
            command_id=str(data["command_id"]),
            created_at=float(data["created_at"]),
            timeout_sec=data.get("timeout_sec"),
        )


@dataclass(frozen=True)
class CommandResult:
    """Result of a command after dispatch, acknowledgment, or failure."""

    command_id: str
    status: CommandStatus
    message: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.status, CommandStatus):
            object.__setattr__(self, "status", CommandStatus(self.status))
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))

    @property
    def ok(self) -> bool:
        return self.status in (CommandStatus.ACKNOWLEDGED, CommandStatus.OBSERVED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "message": self.message,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AppEvent:
    """Immutable event emitted by the app core for UI or test consumers."""

    event_type: str
    source: str = "app_core"
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _frozen_mapping(self.payload))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }

    @classmethod
    def lifecycle_changed(
            cls, previous: LifecyclePhase, current: LifecyclePhase) -> "AppEvent":
        return cls(
            event_type="runtime.lifecycle_changed",
            payload={"previous": previous.value, "current": current.value},
        )