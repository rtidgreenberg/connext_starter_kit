"""Immutable state snapshots for the rs_gui_v2 headless core."""

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Tuple

from .events import LifecyclePhase


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class RuntimeCounters:
    """Monotonic counters used by Milestone L diagnostics and soak tests."""

    commands_enqueued: int = 0
    commands_dropped: int = 0
    commands_drained: int = 0
    events_published: int = 0
    events_dropped: int = 0
    events_drained: int = 0
    ui_frames_built: int = 0
    ui_events_ingested: int = 0
    ui_event_log_dropped: int = 0
    samples_received: int = 0
    samples_dropped: int = 0

    def increment(self, **deltas: int) -> "RuntimeCounters":
        values = self.to_dict()
        for key, delta in deltas.items():
            if key not in values:
                raise KeyError(f"Unknown runtime counter: {key}")
            values[key] = int(values[key]) + int(delta)
        return RuntimeCounters(**values)

    def to_dict(self) -> Dict[str, int]:
        return {
            "commands_enqueued": self.commands_enqueued,
            "commands_dropped": self.commands_dropped,
            "commands_drained": self.commands_drained,
            "events_published": self.events_published,
            "events_dropped": self.events_dropped,
            "events_drained": self.events_drained,
            "ui_frames_built": self.ui_frames_built,
            "ui_events_ingested": self.ui_events_ingested,
            "ui_event_log_dropped": self.ui_event_log_dropped,
            "samples_received": self.samples_received,
            "samples_dropped": self.samples_dropped,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeCounters":
        known = {key: int(data.get(key, 0)) for key in cls().to_dict()}
        return cls(**known)


@dataclass(frozen=True)
class OperatorDiagnostic:
    """Top-level diagnostic intended for operator-facing shell surfaces."""

    source: str
    severity: str
    message: str
    code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", str(self.source))
        object.__setattr__(self, "severity", str(self.severity or "info"))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "code", str(self.code))

    def to_dict(self) -> Dict[str, str]:
        return {
            "source": self.source,
            "severity": self.severity,
            "message": self.message,
            "code": self.code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OperatorDiagnostic":
        return cls(
            source=str(data.get("source", "runtime")),
            severity=str(data.get("severity", "info")),
            message=str(data.get("message", "")),
            code=str(data.get("code", "")),
        )


def _diagnostics(value: Iterable[Any]) -> Tuple[OperatorDiagnostic, ...]:
    diagnostics = []
    for item in value or ():
        if isinstance(item, OperatorDiagnostic):
            diagnostics.append(item)
        elif isinstance(item, Mapping):
            diagnostics.append(OperatorDiagnostic.from_dict(item))
        else:
            diagnostics.append(OperatorDiagnostic("runtime", "info", str(item)))
    return tuple(diagnostics)


@dataclass(frozen=True)
class AppState:
    """Snapshot of app-core state safe to share with tests or UI code."""

    lifecycle: LifecyclePhase = LifecyclePhase.STOPPED
    dds_enabled: bool = False
    monitoring_enabled: bool = False
    discovery_enabled: bool = False
    admin_rpc_enabled: bool = False
    services: Mapping[str, Any] = field(default_factory=dict)
    topics: Mapping[str, Any] = field(default_factory=dict)
    plots: Mapping[str, Any] = field(default_factory=dict)
    runtime_counters: RuntimeCounters = field(default_factory=RuntimeCounters)
    operator_diagnostics: Tuple[OperatorDiagnostic, ...] = field(default_factory=tuple)
    recent_errors: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle, LifecyclePhase):
            object.__setattr__(self, "lifecycle", LifecyclePhase(self.lifecycle))
        object.__setattr__(self, "services", _frozen_mapping(self.services))
        object.__setattr__(self, "topics", _frozen_mapping(self.topics))
        object.__setattr__(self, "plots", _frozen_mapping(self.plots))
        if not isinstance(self.runtime_counters, RuntimeCounters):
            object.__setattr__(self, "runtime_counters", RuntimeCounters.from_dict(self.runtime_counters))
        object.__setattr__(self, "operator_diagnostics", _diagnostics(self.operator_diagnostics))
        object.__setattr__(self, "recent_errors", tuple(self.recent_errors))

    def with_lifecycle(self, lifecycle: LifecyclePhase) -> "AppState":
        return replace(self, lifecycle=lifecycle)

    def with_error(self, message: str) -> "AppState":
        return replace(self, recent_errors=self.recent_errors + (message,))

    def with_runtime_counters(self, counters: RuntimeCounters) -> "AppState":
        return replace(self, runtime_counters=counters)

    def increment_counters(self, **deltas: int) -> "AppState":
        return self.with_runtime_counters(self.runtime_counters.increment(**deltas))

    def with_operator_diagnostics(
            self, diagnostics: Iterable[OperatorDiagnostic]
    ) -> "AppState":
        return replace(self, operator_diagnostics=tuple(diagnostics))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lifecycle": self.lifecycle.value,
            "dds_enabled": self.dds_enabled,
            "monitoring_enabled": self.monitoring_enabled,
            "discovery_enabled": self.discovery_enabled,
            "admin_rpc_enabled": self.admin_rpc_enabled,
            "services": dict(self.services),
            "topics": dict(self.topics),
            "plots": dict(self.plots),
            "runtime_counters": self.runtime_counters.to_dict(),
            "operator_diagnostics": [diagnostic.to_dict() for diagnostic in self.operator_diagnostics],
            "recent_errors": list(self.recent_errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AppState":
        return cls(
            lifecycle=LifecyclePhase(data.get("lifecycle", LifecyclePhase.STOPPED.value)),
            dds_enabled=bool(data.get("dds_enabled", False)),
            monitoring_enabled=bool(data.get("monitoring_enabled", False)),
            discovery_enabled=bool(data.get("discovery_enabled", False)),
            admin_rpc_enabled=bool(data.get("admin_rpc_enabled", False)),
            services=data.get("services", {}),
            topics=data.get("topics", {}),
            plots=data.get("plots", {}),
            runtime_counters=RuntimeCounters.from_dict(data.get("runtime_counters", {})),
            operator_diagnostics=tuple(
                OperatorDiagnostic.from_dict(item)
                for item in data.get("operator_diagnostics", ())
            ),
            recent_errors=tuple(data.get("recent_errors", ())),
        )