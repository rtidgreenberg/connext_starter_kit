"""DDS discovery models and RTI builtin-topic adapter for rti_view.

Pattern sourced from tools/rti_spy/rtispy.py: create a DomainParticipant with
publication/subscription builtin-topic listeners and capture endpoint type/QoS data
for DynamicData subscriptions.
"""

from dataclasses import dataclass
from threading import RLock
import time
from typing import Callable, Dict, Optional, Tuple

import rti.connextdds as dds


@dataclass(frozen=True)
class DiscoveredParticipant:
    """A discovered DDS participant shown as a process-like row in the UI."""

    key: str
    name: str = ""
    ip: str = ""
    rtps_host_id: int = 0
    rtps_app_id: int = 0
    observed_at: float = 0.0

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        if self.ip:
            return f"Participant {self.key} @ {self.ip}"
        return f"Participant {self.key}"


@dataclass(frozen=True)
class DiscoveredEndpoint:
    """A discovered DataWriter or DataReader endpoint."""

    key: str
    topic_name: str
    type_name: str
    dynamic_type: Optional[dds.DynamicType] = None
    kind: str = ""  # "Writer" or "Reader"
    participant_key: str = ""
    reliability: Optional[object] = None
    durability: Optional[object] = None
    deadline: Optional[object] = None
    ownership: Optional[object] = None
    presentation: Optional[object] = None
    partition: Optional[object] = None
    type_debug: Tuple[str, ...] = ()
    observed_at: float = 0.0

    @property
    def is_writer(self) -> bool:
        return self.kind.lower() == "writer"

    @property
    def type_available(self) -> bool:
        return self.dynamic_type is not None


@dataclass(frozen=True)
class DiscoveryDiagnostic:
    """A user-visible discovery diagnostic."""

    code: str
    message: str


class DiscoveryRegistry:
    """Registry of participants and endpoints discovered on one domain."""

    def __init__(self) -> None:
        self._participants: Dict[str, DiscoveredParticipant] = {}
        self._endpoints: Dict[str, DiscoveredEndpoint] = {}
        self._lock = RLock()

    def clear(self) -> None:
        with self._lock:
            self._participants.clear()
            self._endpoints.clear()

    def add_participant(self, participant: DiscoveredParticipant) -> None:
        with self._lock:
            self._participants[participant.key] = participant

    def add_endpoint(self, endpoint: DiscoveredEndpoint) -> None:
        with self._lock:
            previous = self._endpoints.get(endpoint.key)
            self._endpoints[endpoint.key] = _merge_endpoint(previous, endpoint) if previous else endpoint

    def participants(self) -> Tuple[DiscoveredParticipant, ...]:
        with self._lock:
            return tuple(sorted(self._participants.values(), key=lambda item: (item.label, item.key)))

    def participant_for_key(self, participant_key: str) -> Optional[DiscoveredParticipant]:
        with self._lock:
            return self._participants.get(participant_key)

    def writers_for_participant(self, participant_key: str) -> Tuple[DiscoveredEndpoint, ...]:
        with self._lock:
            return self._matching_endpoints(
                lambda endpoint: endpoint.is_writer and endpoint.participant_key == participant_key,
                key=lambda endpoint: (endpoint.topic_name, endpoint.key),
            )

    def writers_for_topic(self, topic_name: str) -> Tuple[DiscoveredEndpoint, ...]:
        with self._lock:
            return self._matching_endpoints(
                lambda endpoint: endpoint.is_writer and endpoint.topic_name == topic_name,
                key=lambda endpoint: (endpoint.participant_key, endpoint.key),
            )

    def topics_for_participant(self, participant_key: str) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(ep.topic_name for ep in self.writers_for_participant(participant_key)))

    def writer_by_topic_for_participant(self, participant_key: str) -> Dict[str, DiscoveredEndpoint]:
        """Return the best writer endpoint per topic for a participant."""
        writers_by_topic: Dict[str, DiscoveredEndpoint] = {}
        for endpoint in self.writers_for_participant(participant_key):
            current = writers_by_topic.get(endpoint.topic_name)
            writers_by_topic[endpoint.topic_name] = preferred_endpoint(current, endpoint)
        return writers_by_topic

    def get_all_topics(self) -> Dict[str, str]:
        """Return unique topic names with the first observed type name."""
        with self._lock:
            topics: Dict[str, str] = {}
            for endpoint in self._matching_endpoints(lambda endpoint: True, key=lambda endpoint: (endpoint.topic_name, endpoint.key)):
                topics.setdefault(endpoint.topic_name, endpoint.type_name)
            return topics

    @property
    def endpoints(self) -> Dict[str, DiscoveredEndpoint]:
        with self._lock:
            return dict(self._endpoints)

    def diagnose_participants(self) -> Optional[DiscoveryDiagnostic]:
        if not self.participants():
            return DiscoveryDiagnostic("no_participants", "No DDS participants discovered on this domain yet.")
        return None

    def diagnose_participant_writers(self, participant_key: str) -> Optional[DiscoveryDiagnostic]:
        if not self.writers_for_participant(participant_key):
            return DiscoveryDiagnostic("no_writers", "Selected process/participant has no discovered writer topics.")
        return None

    def select_writer_for_topic(self, topic_name: str) -> Tuple[Optional[DiscoveredEndpoint], Tuple[DiscoveryDiagnostic, ...]]:
        writers = self.writers_for_topic(topic_name)
        if not writers:
            return None, (DiscoveryDiagnostic("topic_not_found", f"Topic '{topic_name}' was not discovered."),)
        diagnostics = []
        if len(writers) > 1:
            diagnostics.append(DiscoveryDiagnostic(
                "multiple_writers",
                f"Multiple writers found for topic '{topic_name}'; using the first compatible writer.",
            ))
        endpoint = preferred_endpoint(None, *writers)
        if not endpoint.type_available:
            diagnostics.append(DiscoveryDiagnostic(
                "type_unavailable",
                f"Topic '{topic_name}' was discovered but did not propagate a usable DynamicType.",
            ))
        return endpoint, tuple(diagnostics)

    def _matching_endpoints(
            self,
            predicate: Callable[[DiscoveredEndpoint], bool],
            key: Callable[[DiscoveredEndpoint], Tuple[str, str]],
    ) -> Tuple[DiscoveredEndpoint, ...]:
        return tuple(sorted((endpoint for endpoint in self._endpoints.values() if predicate(endpoint)), key=key))


registry = DiscoveryRegistry()
_listener_refs: Dict[int, Tuple[object, object]] = {}


def preferred_endpoint(
        current: Optional[DiscoveredEndpoint],
        *candidates: DiscoveredEndpoint,
) -> Optional[DiscoveredEndpoint]:
    """Choose the most useful endpoint for topic inspection."""
    best = current
    for candidate in candidates:
        if best is None or _endpoint_score(candidate) > _endpoint_score(best):
            best = candidate
    return best


def _endpoint_score(endpoint: DiscoveredEndpoint) -> Tuple[bool, float, str]:
    return (endpoint.type_available, float(endpoint.observed_at), endpoint.key)


def _merge_endpoint(previous: DiscoveredEndpoint, current: DiscoveredEndpoint) -> DiscoveredEndpoint:
    return DiscoveredEndpoint(
        key=current.key,
        topic_name=_coalesce(current.topic_name, previous.topic_name),
        type_name=_coalesce(current.type_name, previous.type_name),
        dynamic_type=_coalesce_defined(current.dynamic_type, previous.dynamic_type),
        kind=_coalesce(current.kind, previous.kind),
        participant_key=_coalesce(current.participant_key, previous.participant_key),
        reliability=_coalesce_defined(current.reliability, previous.reliability),
        durability=_coalesce_defined(current.durability, previous.durability),
        deadline=_coalesce_defined(current.deadline, previous.deadline),
        ownership=_coalesce_defined(current.ownership, previous.ownership),
        presentation=_coalesce_defined(current.presentation, previous.presentation),
        partition=_coalesce_defined(current.partition, previous.partition),
        type_debug=_coalesce(current.type_debug, previous.type_debug),
        observed_at=max(float(previous.observed_at), float(current.observed_at)),
    )


def _coalesce(current, fallback):
    return current or fallback


def _coalesce_defined(current, fallback):
    return current if current is not None else fallback


def _key_bytes(key_value) -> Optional[bytes]:
    if isinstance(key_value, bytes):
        return key_value
    if isinstance(key_value, bytearray):
        return bytes(key_value)
    if isinstance(key_value, memoryview):
        return key_value.tobytes()
    if isinstance(key_value, (list, tuple)) and len(key_value) == 1:
        return _key_bytes(key_value[0])
    return None


def _key_string(key_value) -> str:
    key_bytes = _key_bytes(key_value)
    if key_bytes is not None:
        return key_bytes.hex()
    return str(tuple(key_value)) if isinstance(key_value, (list, tuple)) else str(key_value)


def _key_parts(key_value) -> Tuple[int, ...]:
    key_bytes = _key_bytes(key_value)
    if key_bytes is not None:
        return tuple(
            int.from_bytes(key_bytes[index:index + 4], byteorder="big")
            for index in range(0, len(key_bytes), 4)
            if key_bytes[index:index + 4]
        )
    if isinstance(key_value, (list, tuple)):
        return tuple(_coerce_int(value) for value in key_value)
    try:
        return (int(key_value),)
    except Exception:
        return ()


def _coerce_int(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _participant_ip(participant_data) -> str:
    try:
        locator = participant_data.default_unicast_locators[0]
        return ".".join(str(byte) for byte in locator.address[-4:])
    except Exception:
        return ""


def _participant_name(participant_data) -> str:
    try:
        return str(participant_data.participant_name.name or "")
    except Exception:
        return ""


def participant_from_builtin_data(participant_data, observed_at: Optional[float] = None) -> DiscoveredParticipant:
    key_value = getattr(getattr(participant_data, "key", None), "value", ())
    key = _key_string(key_value)
    key_parts = _key_parts(key_value)
    host_id = key_parts[0] if len(key_parts) >= 1 else 0
    app_id = key_parts[1] if len(key_parts) >= 2 else 0
    return DiscoveredParticipant(
        key=key,
        name=_participant_name(participant_data),
        ip=_participant_ip(participant_data),
        rtps_host_id=host_id,
        rtps_app_id=app_id,
        observed_at=_observed_at(observed_at),
    )


def endpoint_from_builtin_data(data, kind: str, observed_at: Optional[float] = None) -> DiscoveredEndpoint:
    # Prefer TypeObject v2 ("type") from 7.7.0+ remotes; fall back to
    # TypeObject v1 ("type_code") from 6.1.2/7.3.0 remotes.
    dynamic_type = getattr(data, "type", None) or getattr(data, "type_code", None)
    return DiscoveredEndpoint(
        key=_key_string(data.key.value),
        topic_name=str(data.topic_name),
        type_name=str(data.type_name),
        dynamic_type=dynamic_type,
        kind=kind,
        participant_key=_key_string(data.participant_key.value),
        reliability=getattr(data, "reliability", None),
        durability=getattr(data, "durability", None),
        deadline=getattr(data, "deadline", None),
        ownership=getattr(data, "ownership", None),
        presentation=getattr(data, "presentation", None),
        partition=getattr(data, "partition", None),
        type_debug=_type_debug_lines(data),
        observed_at=_observed_at(observed_at),
    )


def _observed_at(observed_at: Optional[float]) -> float:
    return time.time() if observed_at is None else float(observed_at)


def _type_debug_lines(data) -> Tuple[str, ...]:
    lines = []
    try:
        names = sorted(name for name in dir(data) if "type" in name.lower() or "representation" in name.lower())
    except Exception:
        return ()
    for name in names:
        if name.startswith("_"):
            continue
        try:
            value = getattr(data, name)
        except Exception as exc:
            value_text = f"<error: {exc}>"
        else:
            value_text = _short_debug_value(value)
        lines.append(f"{name}={value_text}")
    return tuple(lines)


def _short_debug_value(value) -> str:
    try:
        value_text = repr(value)
    except Exception as exc:
        value_text = f"<repr error: {exc}>"
    if len(value_text) > 240:
        return value_text[:237] + "..."
    return value_text


class PublicationListener(dds.PublicationBuiltinTopicData.DataReaderListener):
    """Listener for DataWriter discovery via DCPSPublication builtin topic."""

    def on_data_available(self, reader):
        for data, info in reader.take():
            if info.valid:
                registry.add_endpoint(endpoint_from_builtin_data(data, "Writer"))


class SubscriptionListener(dds.SubscriptionBuiltinTopicData.DataReaderListener):
    """Listener for DataReader discovery via DCPSSubscription builtin topic."""

    def on_data_available(self, reader):
        for data, info in reader.take():
            if info.valid:
                registry.add_endpoint(endpoint_from_builtin_data(data, "Reader"))


def refresh_participants(participant: dds.DomainParticipant, target_registry: DiscoveryRegistry = registry) -> None:
    """Refresh process-like participant rows from discovered participant handles."""
    for handle in participant.discovered_participants():
        try:
            data = participant.discovered_participant_data(handle)
        except Exception:
            continue
        target_registry.add_participant(participant_from_builtin_data(data))


def refresh_endpoints(participant: dds.DomainParticipant, target_registry: DiscoveryRegistry = registry) -> None:
    """Poll builtin endpoint readers so discovery does not depend only on listener callbacks."""
    _poll_endpoint_reader(participant.publication_reader, "Writer", target_registry)
    _poll_endpoint_reader(participant.subscription_reader, "Reader", target_registry)


def _poll_endpoint_reader(reader, kind: str, target_registry: DiscoveryRegistry) -> None:
    for data, info in reader.take():
        if info.valid:
            target_registry.add_endpoint(endpoint_from_builtin_data(data, kind))


def configure_type_lookup_qos(qos: dds.DomainParticipantQos) -> bool:
    """Enable type discovery for both old (v1 inline) and new (v2 lookup) remotes.

    - enabled_builtin_channels = ALL: enables TypeLookup Service channel for
      7.7.0+ remotes that support TypeObject v2.
    - endpoint_type_object_lb_serialization_threshold = -1: accept uncompressed
      TypeObject v1 from 6.1.2/7.3.x remotes that propagate types inline.
    - request_types_filter: set to "*" if available (7.7.0+ Python binding) to
      proactively request types without requiring local endpoint matches.
    """
    try:
        discovery_config = qos.discovery_config
        discovery_config.enabled_builtin_channels = dds.DiscoveryConfigBuiltinChannelKindMask.ALL
        discovery_config.endpoint_type_object_lb_serialization_threshold = -1
        # request_types_filter available in 7.7.0+ Python binding only
        try:
            discovery_config.request_types_filter = "*"
        except AttributeError:
            pass
        return True
    except Exception:
        return False


def create_participant(domain_id: int, name: str = "rti_view") -> dds.DomainParticipant:
    """Create a DomainParticipant with builtin topic listeners attached."""
    factory_qos = dds.DomainParticipantFactoryQos()
    factory_qos.entity_factory.autoenable_created_entities = False
    dds.DomainParticipant.participant_factory_qos = factory_qos

    qos = dds.DomainParticipantQos()
    qos.participant_name.name = name
    configure_type_lookup_qos(qos)

    try:
        participant = dds.DomainParticipant(domain_id, qos=qos)
        publication_listener = PublicationListener()
        subscription_listener = SubscriptionListener()
        participant.publication_reader.set_listener(publication_listener, dds.StatusMask.DATA_AVAILABLE)
        participant.subscription_reader.set_listener(subscription_listener, dds.StatusMask.DATA_AVAILABLE)
        _listener_refs[id(participant)] = (publication_listener, subscription_listener)
        participant.enable()
    finally:
        factory_qos.entity_factory.autoenable_created_entities = True
        dds.DomainParticipant.participant_factory_qos = factory_qos
    return participant
