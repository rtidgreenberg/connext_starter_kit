"""RTI Connext built-in topic discovery adapter for rs_gui_v2.

This module owns the Connext DDS built-in publication and subscription readers.
The DDS-free discovery catalog and selection models remain in `discovery.py`.
"""

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .connext_environment import detect_nddshome, ensure_rti_license, license_setup_message
from .discovery import (
    DiscoveredEndpoint,
    DiscoveredTopic,
    EndpointDirection,
    TopicInventory,
)
from .types import TypeCatalog


DEFAULT_DISCOVERY_POLL_SEC = 0.25
SYS_INFO_PROPERTY_NAMES = (
    "dds.sys_info.hostname",
    "dds.sys_info.process_id",
    "dds.sys_info.username",
    "dds.sys_info.executable_filepath",
    "dds.sys_info.target",
)


@dataclass(frozen=True)
class RtiTopicDiscoveryConfig:
    """Timing inputs for the RTI built-in topic discovery adapter."""

    poll_interval_sec: float = DEFAULT_DISCOVERY_POLL_SEC
    endpoint_stale_after_sec: float = 0.0


@dataclass
class _DiscoverySession:
    participant: Any
    inventory: TopicInventory


class RtiTopicDiscoveryClient:
    """Connext DDS implementation of the `TopicDiscoveryClient` protocol."""

    def __init__(
            self,
            config: Optional[RtiTopicDiscoveryConfig] = None,
            type_catalog: Optional[TypeCatalog] = None,
            dds_module: Any = None,
    ) -> None:
        self.config = config or RtiTopicDiscoveryConfig()
        self._type_catalog = type_catalog or TypeCatalog()
        self._dds = dds_module
        self._uses_real_connext = dds_module is None
        self._sessions: Dict[int, _DiscoverySession] = {}

    async def scan(
            self,
            domain_id: int,
            include_internal: bool = False,
    ) -> Tuple[DiscoveredTopic, ...]:
        return await self._run_blocking(self._scan_sync, domain_id, include_internal)

    async def topics(self, domain_id: int, include_internal: bool = False):
        while True:
            for topic in await self.scan(domain_id, include_internal=include_internal):
                yield topic
            await asyncio.sleep(self.config.poll_interval_sec)

    async def close(self) -> None:
        await self._run_blocking(self.close_sync)

    def close_sync(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            participant = session.participant
            try:
                close_contained = getattr(participant, "close_contained_entities", None)
                if close_contained is not None:
                    close_contained()
            finally:
                _safe_close(participant)

    async def _run_blocking(self, function, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: function(*args))

    def _scan_sync(self, domain_id: int, include_internal: bool) -> Tuple[DiscoveredTopic, ...]:
        session = self._session_for_domain(domain_id)
        self._take_builtin_samples(session, int(domain_id))
        return session.inventory.topics(domain_id=domain_id, include_internal=include_internal)

    def _session_for_domain(self, domain_id: int) -> _DiscoverySession:
        domain_id = int(domain_id)
        session = self._sessions.get(domain_id)
        if session is not None:
            return session

        self._load_connext_module()
        self._prepare_runtime_environment()
        try:
            participant = self._dds.DomainParticipant(domain_id)
        except Exception as exc:
            nddshome = detect_nddshome()
            raise RuntimeError(
                f"Failed to create DDS DomainParticipant on domain {domain_id}. "
                f"{license_setup_message(nddshome)}"
            ) from exc
        session = _DiscoverySession(
            participant=participant,
            inventory=TopicInventory(type_catalog=self._type_catalog),
        )
        self._sessions[domain_id] = session
        return session

    def _take_builtin_samples(self, session: _DiscoverySession, domain_id: int) -> None:
        participant_identity, removed_participant_keys = _participant_changes_by_key(session.participant)
        for participant_key in removed_participant_keys:
            session.inventory.remove_participant(participant_key, domain_id=domain_id)
        for endpoint in _endpoints_from_reader(
                getattr(session.participant, "publication_reader"),
                domain_id,
                EndpointDirection.WRITER,
            participant_identity,
        ):
            session.inventory.apply(endpoint)
        for endpoint in _endpoints_from_reader(
                getattr(session.participant, "subscription_reader"),
                domain_id,
                EndpointDirection.READER,
            participant_identity,
        ):
            session.inventory.apply(endpoint)
        session.inventory.remove_stale(
            time.time(),
            self.config.endpoint_stale_after_sec,
            domain_id=domain_id,
        )

    def _load_connext_module(self) -> None:
        if self._dds is None:
            import rti.connextdds as dds
            self._dds = dds

    def _prepare_runtime_environment(self) -> None:
        if not self._uses_real_connext:
            return
        nddshome = detect_nddshome()
        ensure_rti_license(nddshome)


def _endpoints_from_reader(
        reader: Any,
        domain_id: int,
        direction: EndpointDirection,
        participant_identity: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Iterable[DiscoveredEndpoint]:
    for sample in _reader_take(reader):
        endpoint = endpoint_from_builtin_sample(domain_id, direction, sample, participant_identity)
        if endpoint is not None:
            yield endpoint


def endpoint_from_builtin_sample(
        domain_id: int,
        direction: EndpointDirection,
        sample: Any,
    participant_identity: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[DiscoveredEndpoint]:
    data, info = _sample_data_and_info(sample)
    alive = bool(getattr(info, "valid", False))
    if data is None:
        return None

    endpoint_key = _key_to_text(_field(data, "key", ""))
    if not endpoint_key:
        return None
    topic_name = _to_text(_field(data, "topic_name", ""))
    type_name = _to_text(_field(data, "type_name", ""))
    if not alive and not topic_name:
        return DiscoveredEndpoint(
            domain_id=domain_id,
            topic_name="",
            type_name="",
            direction=direction,
            endpoint_key=endpoint_key,
            alive=False,
        )
    if not topic_name:
        return None
    participant_key = _key_to_text(_field(data, "participant_key", ""))
    identity = dict((participant_identity or {}).get(participant_key, {}))
    participant_name = str(identity.pop("participant_name", ""))
    properties = _participant_properties(data)
    properties.update(identity)
    return DiscoveredEndpoint(
        domain_id=domain_id,
        topic_name=topic_name,
        type_name=type_name,
        direction=direction,
        endpoint_key=endpoint_key,
        participant_key=participant_key,
        participant_name=participant_name,
        participant_properties=properties,
        partitions=_partition_names(_field(data, "partition", None)),
        qos=_qos_summary(data),
        type_available=_field(data, "type", None) is not None,
        alive=alive,
        observed_at=time.time(),
    )


def _participant_changes_by_key(participant: Any) -> Tuple[Dict[str, Mapping[str, Any]], Tuple[str, ...]]:
    identity: Dict[str, Mapping[str, Any]] = {}
    removed = []
    for data in _discovered_participant_data(participant):
        key = _key_to_text(_field(data, "key", ""))
        if not key:
            continue
        values = dict(_participant_properties(data))
        participant_name = _participant_name(data)
        if participant_name:
            values["participant_name"] = participant_name
        identity[key] = values
    for data, info in _participant_builtin_samples(participant):
        if data is None:
            continue
        key = _key_to_text(_field(data, "key", ""))
        if bool(getattr(info, "valid", False)):
            values = dict(_participant_properties(data))
            participant_name = _participant_name(data)
            if participant_name:
                values["participant_name"] = participant_name
            if key:
                identity[key] = values
            continue
        if key:
            removed.append(key)
    return identity, tuple(removed)


def _discovered_participant_data(participant: Any) -> Iterable[Any]:
    discovered = getattr(participant, "discovered_participants", None)
    data_for = getattr(participant, "discovered_participant_data", None)
    if callable(discovered) and callable(data_for):
        try:
            for handle in discovered():
                yield data_for(handle)
            return
        except Exception:
            pass

    return ()


def _participant_builtin_data(participant: Any) -> Iterable[Any]:
    for data in _discovered_participant_data(participant):
        yield data

    for data, info in _participant_builtin_samples(participant):
        if data is not None and bool(getattr(info, "valid", False)):
            yield data


def _participant_builtin_samples(participant: Any) -> Iterable[Tuple[Any, Any]]:
    reader = getattr(participant, "participant_reader", None)
    if reader is None:
        return ()
    return tuple(_sample_data_and_info(sample) for sample in _reader_take(reader))


def _participant_name(data: Any) -> str:
    participant_name = _field(data, "participant_name", "")
    return _to_text(_field(participant_name, "name", participant_name))


def _participant_properties(data: Any) -> Dict[str, Any]:
    properties = _field(data, "property", None)
    if properties is None:
        return {}
    values: Dict[str, Any] = {}
    for name in SYS_INFO_PROPERTY_NAMES:
        value = _property_try_get(properties, name)
        if value is not None:
            values[name] = _to_text(value)
    return values


def _property_try_get(properties: Any, name: str) -> Optional[Any]:
    try_get = getattr(properties, "try_get", None)
    if callable(try_get):
        return try_get(name)
    get = getattr(properties, "get", None)
    if callable(get):
        try:
            return get(name)
        except Exception:
            return None
    if isinstance(properties, Mapping):
        return properties.get(name)
    return None


def _sample_data_and_info(sample: Any) -> Tuple[Any, Any]:
    if isinstance(sample, tuple) and len(sample) == 2:
        return sample[0], sample[1]
    return getattr(sample, "data", None), getattr(sample, "info", None)


def _reader_take(reader: Any) -> Iterable[Any]:
    select = getattr(reader, "select", None)
    data_state = _any_data_state()
    if callable(select) and data_state is not None:
        try:
            return select().state(data_state).take()
        except Exception:
            pass
    take = getattr(reader, "take")
    return take()


def _any_data_state() -> Any:
    try:
        import rti.connextdds as dds
        return getattr(getattr(dds, "DataState", None), "any", None)
    except Exception:
        return None


def _field(data: Any, name: str, default: Any = None) -> Any:
    if data is None:
        return default
    if isinstance(data, dict):
        return data.get(name, default)
    try:
        return getattr(data, name)
    except Exception:
        return default


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _key_to_text(value: Any) -> str:
    raw = _field(value, "value", value)
    if isinstance(raw, (list, tuple)):
        return ":".join(str(item) for item in raw)
    return str(raw) if raw is not None else ""


def _partition_names(partition: Any) -> Tuple[str, ...]:
    names = _field(partition, "name", ())
    if names is None:
        return ()
    if isinstance(names, str):
        return (names,)
    try:
        return tuple(str(name) for name in names)
    except TypeError:
        return (str(names),)


def _qos_summary(data: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for policy_name in ("reliability", "durability", "ownership", "destination_order"):
        policy = _field(data, policy_name, None)
        kind = _field(policy, "kind", None)
        if kind is not None:
            summary[policy_name] = str(kind)
    return summary


def _safe_close(entity: Any) -> None:
    close = getattr(entity, "close", None)
    if close is not None:
        close()