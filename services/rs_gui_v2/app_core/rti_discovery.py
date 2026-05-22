"""RTI Connext built-in topic discovery adapter for rs_gui_v2.

This module owns the Connext DDS built-in publication and subscription readers.
The DDS-free discovery catalog and selection models remain in `discovery.py`.
"""

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict, Iterable, Optional, Tuple

from .connext_environment import detect_nddshome, ensure_rti_license, license_setup_message
from .discovery import (
    DiscoveredEndpoint,
    DiscoveredTopic,
    EndpointDirection,
    TopicInventory,
)
from .types import TypeCatalog


DEFAULT_DISCOVERY_POLL_SEC = 0.25


@dataclass(frozen=True)
class RtiTopicDiscoveryConfig:
    """Timing inputs for the RTI built-in topic discovery adapter."""

    poll_interval_sec: float = DEFAULT_DISCOVERY_POLL_SEC


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
        for endpoint in _endpoints_from_reader(
                getattr(session.participant, "publication_reader"),
                domain_id,
                EndpointDirection.WRITER,
        ):
            session.inventory.apply(endpoint)
        for endpoint in _endpoints_from_reader(
                getattr(session.participant, "subscription_reader"),
                domain_id,
                EndpointDirection.READER,
        ):
            session.inventory.apply(endpoint)

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
) -> Iterable[DiscoveredEndpoint]:
    for sample in _reader_take(reader):
        endpoint = endpoint_from_builtin_sample(domain_id, direction, sample)
        if endpoint is not None:
            yield endpoint


def endpoint_from_builtin_sample(
        domain_id: int,
        direction: EndpointDirection,
        sample: Any,
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
    return DiscoveredEndpoint(
        domain_id=domain_id,
        topic_name=topic_name,
        type_name=type_name,
        direction=direction,
        endpoint_key=endpoint_key,
        participant_key=_key_to_text(_field(data, "participant_key", "")),
        partitions=_partition_names(_field(data, "partition", None)),
        qos=_qos_summary(data),
        type_available=_field(data, "type", None) is not None,
        alive=alive,
        observed_at=time.time(),
    )


def _sample_data_and_info(sample: Any) -> Tuple[Any, Any]:
    if isinstance(sample, tuple) and len(sample) == 2:
        return sample[0], sample[1]
    return getattr(sample, "data", None), getattr(sample, "info", None)


def _reader_take(reader: Any) -> Iterable[Any]:
    take = getattr(reader, "take")
    return take()


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