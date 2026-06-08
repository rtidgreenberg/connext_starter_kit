"""DDS-free topic discovery catalog and selection models for rs_gui_v2."""

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, AsyncIterator, Dict, Iterable, Mapping, Optional, Protocol, Tuple
import time

from .types import EMPTY_TYPE_CATALOG, TypeCatalog, TypeResolution


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _tuple_of_text(value: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(str(item) for item in value)


class EndpointDirection(str, Enum):
    """DDS endpoint direction reported by built-in discovery topics."""

    WRITER = "writer"
    READER = "reader"


class TopicDiscoveryState(str, Enum):
    """Application-level state for a discovered topic."""

    DISCOVERED = "discovered"
    TYPE_AVAILABLE = "type_available"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    INTERNAL = "internal"


@dataclass(frozen=True)
class DiscoveredEndpoint:
    """One DDS DataWriter or DataReader observed through built-in discovery."""

    domain_id: int
    topic_name: str
    type_name: str
    direction: EndpointDirection
    endpoint_key: str
    participant_key: str = ""
    participant_name: str = ""
    participant_properties: Mapping[str, Any] = field(default_factory=dict)
    partitions: Tuple[str, ...] = field(default_factory=tuple)
    qos: Mapping[str, Any] = field(default_factory=dict)
    type_available: bool = False
    alive: bool = True
    observed_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.direction, EndpointDirection):
            object.__setattr__(self, "direction", EndpointDirection(self.direction))
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "participant_properties", _frozen_mapping(self.participant_properties))
        object.__setattr__(self, "partitions", _tuple_of_text(self.partitions))
        object.__setattr__(self, "qos", _frozen_mapping(self.qos))
        object.__setattr__(self, "type_available", bool(self.type_available))
        object.__setattr__(self, "alive", bool(self.alive))

    @property
    def topic_key(self) -> str:
        return topic_key(self.domain_id, self.topic_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_name": self.type_name,
            "direction": self.direction.value,
            "endpoint_key": self.endpoint_key,
            "participant_key": self.participant_key,
            "participant_name": self.participant_name,
            "participant_properties": dict(self.participant_properties),
            "partitions": list(self.partitions),
            "qos": dict(self.qos),
            "type_available": self.type_available,
            "alive": self.alive,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiscoveredEndpoint":
        return cls(
            domain_id=int(data.get("domain_id", 0)),
            topic_name=str(data.get("topic_name", "")),
            type_name=str(data.get("type_name", "")),
            direction=EndpointDirection(data.get("direction", EndpointDirection.WRITER.value)),
            endpoint_key=str(data.get("endpoint_key", "")),
            participant_key=str(data.get("participant_key", "")),
            participant_name=str(data.get("participant_name", "")),
            participant_properties=data.get("participant_properties", {}),
            partitions=tuple(data.get("partitions", ())),
            qos=data.get("qos", {}),
            type_available=bool(data.get("type_available", False)),
            alive=bool(data.get("alive", True)),
            observed_at=float(data.get("observed_at", time.time())),
        )


@dataclass(frozen=True)
class DiscoveredTopic:
    """Aggregated topic inventory row suitable for UI state and persistence."""

    domain_id: int
    topic_name: str
    type_names: Tuple[str, ...] = field(default_factory=tuple)
    writer_count: int = 0
    reader_count: int = 0
    internal: bool = False
    state: TopicDiscoveryState = TopicDiscoveryState.DISCOVERED
    type_resolution: TypeResolution = field(default_factory=lambda: EMPTY_TYPE_CATALOG.resolve(""))
    partitions: Tuple[str, ...] = field(default_factory=tuple)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.state, TopicDiscoveryState):
            object.__setattr__(self, "state", TopicDiscoveryState(self.state))
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "type_names", _tuple_of_text(self.type_names))
        object.__setattr__(self, "writer_count", int(self.writer_count))
        object.__setattr__(self, "reader_count", int(self.reader_count))
        object.__setattr__(self, "internal", bool(self.internal))
        object.__setattr__(self, "partitions", _tuple_of_text(self.partitions))

    @property
    def key(self) -> str:
        return topic_key(self.domain_id, self.topic_name)

    @property
    def endpoint_count(self) -> int:
        return self.writer_count + self.reader_count

    def visible(self, include_internal: bool = False) -> bool:
        return include_internal or not self.internal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_names": list(self.type_names),
            "writer_count": self.writer_count,
            "reader_count": self.reader_count,
            "internal": self.internal,
            "state": self.state.value,
            "type_resolution": self.type_resolution.to_dict(),
            "partitions": list(self.partitions),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiscoveredTopic":
        return cls(
            domain_id=int(data.get("domain_id", 0)),
            topic_name=str(data.get("topic_name", "")),
            type_names=tuple(data.get("type_names", ())),
            writer_count=int(data.get("writer_count", 0)),
            reader_count=int(data.get("reader_count", 0)),
            internal=bool(data.get("internal", False)),
            state=TopicDiscoveryState(data.get("state", TopicDiscoveryState.DISCOVERED.value)),
            type_resolution=TypeResolution.from_dict(data.get("type_resolution", {})),
            partitions=tuple(data.get("partitions", ())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass(frozen=True)
class TopicSelection:
    """Persistable user intent for topic and field selections."""

    domain_id: int
    topic_name: str
    type_name: str = ""
    selected_fields: Tuple[str, ...] = field(default_factory=tuple)
    plot_fields: Tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "selected_fields", _tuple_of_text(self.selected_fields))
        object.__setattr__(self, "plot_fields", _tuple_of_text(self.plot_fields))
        object.__setattr__(self, "enabled", bool(self.enabled))

    @property
    def key(self) -> str:
        return topic_key(self.domain_id, self.topic_name)

    def with_fields(
            self,
            selected_fields: Iterable[str] = (),
            plot_fields: Iterable[str] = (),
    ) -> "TopicSelection":
        selected = tuple(selected_fields) if selected_fields else self.selected_fields
        plots = tuple(plot_fields) if plot_fields else self.plot_fields
        return replace(
            self,
            selected_fields=selected,
            plot_fields=plots,
            updated_at=time.time(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_name": self.type_name,
            "selected_fields": list(self.selected_fields),
            "plot_fields": list(self.plot_fields),
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TopicSelection":
        return cls(
            domain_id=int(data.get("domain_id", 0)),
            topic_name=str(data.get("topic_name", "")),
            type_name=str(data.get("type_name", "")),
            selected_fields=tuple(data.get("selected_fields", ())),
            plot_fields=tuple(data.get("plot_fields", ())),
            enabled=bool(data.get("enabled", True)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass(frozen=True)
class TopicSelectionState:
    """Persistable collection of topic selections and display preferences."""

    selections: Mapping[str, TopicSelection] = field(default_factory=dict)
    include_internal: bool = False

    def __post_init__(self) -> None:
        converted = {}
        for key, selection in dict(self.selections).items():
            if not isinstance(selection, TopicSelection):
                selection = TopicSelection.from_dict(selection)
            converted[str(key)] = selection
        object.__setattr__(self, "selections", MappingProxyType(converted))
        object.__setattr__(self, "include_internal", bool(self.include_internal))

    def select(self, selection: TopicSelection) -> "TopicSelectionState":
        selections = dict(self.selections)
        selections[selection.key] = selection
        return replace(self, selections=selections)

    def deselect(self, domain_id: int, topic_name: str) -> "TopicSelectionState":
        selections = dict(self.selections)
        selections.pop(topic_key(domain_id, topic_name), None)
        return replace(self, selections=selections)

    def selected_for(self, domain_id: int, topic_name: str) -> Optional[TopicSelection]:
        return self.selections.get(topic_key(domain_id, topic_name))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "include_internal": self.include_internal,
            "selections": [
                self.selections[key].to_dict()
                for key in sorted(self.selections)
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TopicSelectionState":
        selections = {
            TopicSelection.from_dict(item).key: TopicSelection.from_dict(item)
            for item in data.get("selections", ())
        }
        return cls(
            selections=selections,
            include_internal=bool(data.get("include_internal", False)),
        )


class TopicDiscoveryClient(Protocol):
    """Transport-specific topic discovery contract used by the facade."""

    async def scan(
            self,
            domain_id: int,
            include_internal: bool = False,
    ) -> Tuple[DiscoveredTopic, ...]:
        """Return the currently known topic inventory for a domain."""

    async def topics(
            self,
            domain_id: int,
            include_internal: bool = False,
    ) -> AsyncIterator[DiscoveredTopic]:
        """Yield discovered topics for a domain."""


class TopicDiscoveryFacade:
    """DDS-free facade for topic inventory and persisted selections."""

    def __init__(
            self,
            client: TopicDiscoveryClient,
            selections: Optional[TopicSelectionState] = None,
    ) -> None:
        self._client = client
        self._selections = selections or TopicSelectionState()

    @property
    def selections(self) -> TopicSelectionState:
        return self._selections

    def set_selections(self, selections: TopicSelectionState) -> None:
        """Replace persisted topic-selection intent without changing discovery data."""

        self._selections = (
            selections if isinstance(selections, TopicSelectionState)
            else TopicSelectionState.from_dict(selections)
        )

    async def scan(
            self,
            domain_id: int,
            include_internal: Optional[bool] = None,
    ) -> Tuple[DiscoveredTopic, ...]:
        if include_internal is None:
            include_internal = self._selections.include_internal
        return await self._client.scan(domain_id, include_internal=include_internal)

    async def topics(
            self,
            domain_id: int,
            include_internal: Optional[bool] = None,
    ) -> AsyncIterator[DiscoveredTopic]:
        if include_internal is None:
            include_internal = self._selections.include_internal
        async for discovered in self._client.topics(domain_id, include_internal=include_internal):
            yield discovered

    def select_topic(
            self,
            domain_id: int,
            topic_name: str,
            type_name: str = "",
            selected_fields: Iterable[str] = (),
            plot_fields: Iterable[str] = (),
    ) -> TopicSelection:
        selection = TopicSelection(
            domain_id=domain_id,
            topic_name=topic_name,
            type_name=type_name,
            selected_fields=tuple(selected_fields),
            plot_fields=tuple(plot_fields),
        )
        self._selections = self._selections.select(selection)
        return selection

    def deselect_topic(self, domain_id: int, topic_name: str) -> None:
        self._selections = self._selections.deselect(domain_id, topic_name)


class TopicInventory:
    """Mutable DDS-free inventory builder for discovery adapters and fakes."""

    def __init__(self, type_catalog: Optional[TypeCatalog] = None) -> None:
        self._endpoints: Dict[str, DiscoveredEndpoint] = {}
        self._type_catalog = type_catalog or EMPTY_TYPE_CATALOG

    def apply(self, endpoint: DiscoveredEndpoint) -> None:
        if endpoint.alive:
            self._endpoints[endpoint.endpoint_key] = endpoint
        else:
            self._endpoints.pop(endpoint.endpoint_key, None)

    def remove_participant(self, participant_key: str, domain_id: Optional[int] = None) -> None:
        participant_key = str(participant_key)
        if not participant_key:
            return
        for endpoint_key, endpoint in tuple(self._endpoints.items()):
            if endpoint.participant_key != participant_key:
                continue
            if domain_id is not None and endpoint.domain_id != int(domain_id):
                continue
            self._endpoints.pop(endpoint_key, None)

    def remove_stale(self, now: float, max_age_sec: float, domain_id: Optional[int] = None) -> int:
        if max_age_sec <= 0.0:
            return 0
        removed = 0
        deadline = float(now) - float(max_age_sec)
        for endpoint_key, endpoint in tuple(self._endpoints.items()):
            if domain_id is not None and endpoint.domain_id != int(domain_id):
                continue
            if endpoint.observed_at >= deadline:
                continue
            self._endpoints.pop(endpoint_key, None)
            removed += 1
        return removed

    def endpoints(self, domain_id: Optional[int] = None) -> Tuple[DiscoveredEndpoint, ...]:
        endpoints = tuple(
            endpoint for endpoint in self._endpoints.values()
            if domain_id is None or endpoint.domain_id == int(domain_id)
        )
        return tuple(sorted(endpoints, key=lambda endpoint: endpoint.endpoint_key))

    def topics(
            self,
            domain_id: Optional[int] = None,
            include_internal: bool = False,
    ) -> Tuple[DiscoveredTopic, ...]:
        grouped: Dict[str, list] = {}
        for endpoint in self._endpoints.values():
            if domain_id is not None and endpoint.domain_id != int(domain_id):
                continue
            grouped.setdefault(endpoint.topic_key, []).append(endpoint)

        topics = tuple(
            topic for topic in (
                self._topic_from_endpoints(endpoints)
                for _key, endpoints in sorted(grouped.items())
            )
            if topic.visible(include_internal=include_internal)
        )
        return topics

    def _topic_from_endpoints(self, endpoints: Iterable[DiscoveredEndpoint]) -> DiscoveredTopic:
        endpoint_tuple = tuple(endpoints)
        first = endpoint_tuple[0]
        type_names = tuple(sorted({endpoint.type_name for endpoint in endpoint_tuple if endpoint.type_name}))
        partitions = tuple(sorted({
            partition
            for endpoint in endpoint_tuple
            for partition in endpoint.partitions
        }))
        writer_count = sum(1 for endpoint in endpoint_tuple if endpoint.direction == EndpointDirection.WRITER)
        reader_count = sum(1 for endpoint in endpoint_tuple if endpoint.direction == EndpointDirection.READER)
        internal = is_internal_topic(first.topic_name)
        type_resolution = _resolve_topic_type(type_names, endpoint_tuple, self._type_catalog)
        state = _topic_state(internal, type_names, type_resolution)
        return DiscoveredTopic(
            domain_id=first.domain_id,
            topic_name=first.topic_name,
            type_names=type_names,
            writer_count=writer_count,
            reader_count=reader_count,
            internal=internal,
            state=state,
            type_resolution=type_resolution,
            partitions=partitions,
            updated_at=max(endpoint.observed_at for endpoint in endpoint_tuple),
        )


def topic_key(domain_id: int, topic_name: str) -> str:
    return f"{int(domain_id)}:{topic_name}"


def is_internal_topic(topic_name: str) -> bool:
    topic_name = str(topic_name)
    return (
        topic_name.startswith("rti/")
        or topic_name.startswith("DCPS")
        or topic_name.startswith("dds/")
    )


def _resolve_topic_type(
        type_names: Tuple[str, ...],
        endpoints: Tuple[DiscoveredEndpoint, ...],
        type_catalog: TypeCatalog,
) -> TypeResolution:
    if not type_names:
        return type_catalog.resolve("")
    if len(type_names) > 1:
        return TypeResolution(
            type_name=type_names[0],
            status="ambiguous",
            candidates=type_names,
            message="multiple discovered type names for topic",
        )
    type_name = type_names[0]
    if any(endpoint.type_available for endpoint in endpoints):
        return TypeResolution(type_name=type_name, status="available", source="discovery")
    return type_catalog.resolve(type_name)


def _topic_state(
        internal: bool,
        type_names: Tuple[str, ...],
        type_resolution: TypeResolution,
) -> TopicDiscoveryState:
    if internal:
        return TopicDiscoveryState.INTERNAL
    if len(type_names) > 1 or type_resolution.status.value == "ambiguous":
        return TopicDiscoveryState.AMBIGUOUS
    if type_resolution.available:
        return TopicDiscoveryState.TYPE_AVAILABLE
    if type_names:
        return TopicDiscoveryState.UNRESOLVED
    return TopicDiscoveryState.DISCOVERED


class FakeTopicDiscoveryClient:
    """DDS-free discovery client with an in-memory endpoint inventory."""

    def __init__(self, type_catalog: Optional[TypeCatalog] = None) -> None:
        self.inventory = TopicInventory(type_catalog=type_catalog)
        self.scans = []

    def apply(self, endpoint: DiscoveredEndpoint) -> None:
        self.inventory.apply(endpoint)

    async def scan(
            self,
            domain_id: int,
            include_internal: bool = False,
    ) -> Tuple[DiscoveredTopic, ...]:
        self.scans.append((int(domain_id), bool(include_internal)))
        return self.inventory.topics(domain_id=domain_id, include_internal=include_internal)

    async def topics(self, domain_id: int, include_internal: bool = False):
        for topic in await self.scan(domain_id, include_internal=include_internal):
            yield topic