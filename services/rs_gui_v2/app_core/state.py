"""Immutable state snapshots for the rs_gui_v2 headless core."""

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

from .events import LifecyclePhase


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


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
    recent_errors: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle, LifecyclePhase):
            object.__setattr__(self, "lifecycle", LifecyclePhase(self.lifecycle))
        object.__setattr__(self, "services", _frozen_mapping(self.services))
        object.__setattr__(self, "topics", _frozen_mapping(self.topics))
        object.__setattr__(self, "plots", _frozen_mapping(self.plots))
        object.__setattr__(self, "recent_errors", tuple(self.recent_errors))

    def with_lifecycle(self, lifecycle: LifecyclePhase) -> "AppState":
        return replace(self, lifecycle=lifecycle)

    def with_error(self, message: str) -> "AppState":
        return replace(self, recent_errors=self.recent_errors + (message,))

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
            recent_errors=tuple(data.get("recent_errors", ())),
        )