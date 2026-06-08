"""DDS-free workspace persistence for rs_gui_v2 declarative state."""

from dataclasses import dataclass, field
import json
import os
import time
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .discovery import TopicSelectionState
from .extractors import FieldPath
from .subscriptions import TopicSubscriptionRequest


WORKSPACE_SCHEMA_VERSION = 2


class WorkspaceFormatError(ValueError):
    """Raised when a workspace document cannot be loaded safely."""


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _tuple_of_text(value: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(str(item) for item in value)


def _tuple_of_int(value: Iterable[Any]) -> Tuple[int, ...]:
    return tuple(int(item) for item in value)


@dataclass(frozen=True)
class WorkspacePlotSeries:
    """One declarative plot series selection."""

    domain_id: int
    topic_name: str
    type_name: str
    field_path: str
    label: str = ""
    enabled: bool = True
    style: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "topic_name", str(self.topic_name))
        object.__setattr__(self, "type_name", str(self.type_name))
        object.__setattr__(self, "field_path", FieldPath.parse(self.field_path).text)
        object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "style", _frozen_mapping(self.style))

    @property
    def key(self) -> str:
        return f"{self.domain_id}:{self.topic_name}:{self.field_path}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_name": self.type_name,
            "field_path": self.field_path,
            "label": self.label,
            "enabled": self.enabled,
            "style": dict(self.style),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkspacePlotSeries":
        if not isinstance(data, Mapping):
            raise WorkspaceFormatError("plot series must be an object")
        try:
            return cls(
                domain_id=int(data["domain_id"]),
                topic_name=str(data["topic_name"]),
                type_name=str(data.get("type_name", "")),
                field_path=str(data["field_path"]),
                label=str(data.get("label", "")),
                enabled=bool(data.get("enabled", True)),
                style=data.get("style", {}),
            )
        except KeyError as exc:
            raise WorkspaceFormatError(f"plot series missing required field: {exc.args[0]}") from exc
        except ValueError as exc:
            raise WorkspaceFormatError(f"invalid plot series: {exc}") from exc


@dataclass(frozen=True)
class WorkspacePlotDefinition:
    """Declarative plot configuration that can survive restarts."""

    name: str
    series: Tuple[WorkspacePlotSeries, ...] = field(default_factory=tuple)
    history_seconds: float = 60.0
    max_points: int = 2000
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "series", tuple(
            item if isinstance(item, WorkspacePlotSeries) else WorkspacePlotSeries.from_dict(item)
            for item in self.series
        ))
        object.__setattr__(self, "history_seconds", max(0.1, float(self.history_seconds)))
        object.__setattr__(self, "max_points", max(1, int(self.max_points)))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(self, "updated_at", float(self.updated_at))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "series": [item.to_dict() for item in self.series],
            "history_seconds": self.history_seconds,
            "max_points": self.max_points,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkspacePlotDefinition":
        if not isinstance(data, Mapping):
            raise WorkspaceFormatError("plot definition must be an object")
        try:
            return cls(
                name=str(data["name"]),
                series=tuple(WorkspacePlotSeries.from_dict(item) for item in data.get("series", ())),
                history_seconds=float(data.get("history_seconds", 60.0)),
                max_points=int(data.get("max_points", 2000)),
                enabled=bool(data.get("enabled", True)),
                created_at=float(data.get("created_at", time.time())),
                updated_at=float(data.get("updated_at", time.time())),
            )
        except KeyError as exc:
            raise WorkspaceFormatError(f"plot definition missing required field: {exc.args[0]}") from exc
        except ValueError as exc:
            raise WorkspaceFormatError(f"invalid plot definition: {exc}") from exc


@dataclass(frozen=True)
class WorkspaceDocument:
    """Versioned, DDS-free workspace document for rs_gui_v2."""

    name: str = ""
    domains: Tuple[int, ...] = field(default_factory=tuple)
    topic_selections: TopicSelectionState = field(default_factory=TopicSelectionState)
    subscriptions: Tuple[TopicSubscriptionRequest, ...] = field(default_factory=tuple)
    plots: Tuple[WorkspacePlotDefinition, ...] = field(default_factory=tuple)
    xml_type_paths: Tuple[str, ...] = field(default_factory=tuple)
    recent_files: Tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    version: int = WORKSPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", int(self.version))
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "domains", _tuple_of_int(self.domains))
        if not isinstance(self.topic_selections, TopicSelectionState):
            object.__setattr__(self, "topic_selections", TopicSelectionState.from_dict(self.topic_selections))
        object.__setattr__(self, "subscriptions", tuple(
            item if isinstance(item, TopicSubscriptionRequest) else TopicSubscriptionRequest.from_dict(item)
            for item in self.subscriptions
        ))
        object.__setattr__(self, "plots", tuple(
            item if isinstance(item, WorkspacePlotDefinition) else WorkspacePlotDefinition.from_dict(item)
            for item in self.plots
        ))
        object.__setattr__(self, "xml_type_paths", _tuple_of_text(self.xml_type_paths))
        object.__setattr__(self, "recent_files", _tuple_of_text(self.recent_files))
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "domains": list(self.domains),
            "topic_selections": self.topic_selections.to_dict(),
            "subscriptions": [request.to_dict() for request in self.subscriptions],
            "plots": [plot.to_dict() for plot in self.plots],
            "xml_type_paths": list(self.xml_type_paths),
            "recent_files": list(self.recent_files),
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkspaceDocument":
        migrated = migrate_workspace_dict(data)
        try:
            return cls(
                name=str(migrated.get("name", "")),
                domains=tuple(migrated.get("domains", ())),
                topic_selections=TopicSelectionState.from_dict(migrated.get("topic_selections", {})),
                subscriptions=tuple(
                    TopicSubscriptionRequest.from_dict(item)
                    for item in migrated.get("subscriptions", ())
                ),
                plots=tuple(WorkspacePlotDefinition.from_dict(item) for item in migrated.get("plots", ())),
                xml_type_paths=tuple(migrated.get("xml_type_paths", ())),
                recent_files=tuple(migrated.get("recent_files", ())),
                metadata=migrated.get("metadata", {}),
                version=WORKSPACE_SCHEMA_VERSION,
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise WorkspaceFormatError(f"invalid workspace document: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> "WorkspaceDocument":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkspaceFormatError(f"workspace JSON is invalid: {exc}") from exc
        return cls.from_dict(data)


def migrate_workspace_dict(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a current-version workspace dictionary from a supported document."""
    if not isinstance(data, Mapping):
        raise WorkspaceFormatError("workspace document must be a JSON object")
    version = int(data.get("version", 1))
    if version == WORKSPACE_SCHEMA_VERSION:
        return dict(data)
    if version == 1:
        return _migrate_v1_to_current(data)
    raise WorkspaceFormatError(f"unsupported workspace version: {version}")


def load_workspace(path: str) -> WorkspaceDocument:
    """Load a workspace document from a JSON file."""
    with open(path, "r", encoding="utf-8") as workspace_file:
        return WorkspaceDocument.from_json(workspace_file.read())


def save_workspace(document: WorkspaceDocument, path: str) -> None:
    """Save a workspace document as deterministic JSON."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as workspace_file:
        workspace_file.write(document.to_json())


def _migrate_v1_to_current(data: Mapping[str, Any]) -> Dict[str, Any]:
    topics = data.get("topics", data.get("selections", ()))
    return {
        "version": WORKSPACE_SCHEMA_VERSION,
        "name": data.get("name", ""),
        "domains": list(data.get("domains", ())),
        "topic_selections": {
            "include_internal": bool(data.get("include_internal", False)),
            "selections": list(topics),
        },
        "subscriptions": list(data.get("subscriptions", ())),
        "plots": list(data.get("plots", ())),
        "xml_type_paths": list(data.get("xml_type_paths", ())),
        "recent_files": list(data.get("recent_files", ())),
        "metadata": dict(data.get("metadata", {})),
    }