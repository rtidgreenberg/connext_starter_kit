"""RTI Connext DynamicData subscription adapter for rs_gui_v2.

This module owns Connext DynamicData topic and reader creation. The subscription
request, state, sample envelope, and cache models remain DDS-free in
`subscriptions.py`.
"""

import asyncio
from dataclasses import dataclass
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .connext_environment import detect_nddshome, ensure_rti_license, license_setup_message
from .rti_types import RtiTypeRegistry
from .subscriptions import (
    SampleEnvelope,
    SampleInfoSnapshot,
    SubscriptionStatus,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
)


@dataclass(frozen=True)
class RtiSubscriptionConfig:
    """Runtime inputs for the RTI DynamicData subscription adapter."""

    poll_interval_sec: float = 0.25
    reader_history_depth: int = 0
    reader_resource_max_samples: int = 0
    reader_resource_max_instances: int = 1
    reader_resource_max_samples_per_instance: int = 0
    reader_take_max_samples: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_interval_sec", max(0.001, float(self.poll_interval_sec)))
        object.__setattr__(self, "reader_history_depth", max(0, int(self.reader_history_depth)))
        object.__setattr__(self, "reader_resource_max_samples", max(0, int(self.reader_resource_max_samples)))
        object.__setattr__(self, "reader_resource_max_instances", max(1, int(self.reader_resource_max_instances)))
        object.__setattr__(
            self,
            "reader_resource_max_samples_per_instance",
            max(0, int(self.reader_resource_max_samples_per_instance)),
        )
        object.__setattr__(self, "reader_take_max_samples", max(0, int(self.reader_take_max_samples)))


@dataclass
class _SubscriptionSession:
    request: TopicSubscriptionRequest
    participant: Any
    topic: Any
    reader: Any
    state: TopicSubscriptionState


class RtiSubscriptionClient:
    """Connext DDS implementation of a pull-based DynamicData subscription client."""

    def __init__(
            self,
            config: Optional[RtiSubscriptionConfig] = None,
            type_registry: Optional[RtiTypeRegistry] = None,
            dds_module: Any = None,
    ) -> None:
        self.config = config or RtiSubscriptionConfig()
        self._type_registry = type_registry or RtiTypeRegistry(dds_module=dds_module)
        self._dds = dds_module
        self._uses_real_connext = dds_module is None
        self._sessions: Dict[str, _SubscriptionSession] = {}

    async def subscribe(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        return await self._run_blocking(self._subscribe_sync, request)

    async def unsubscribe(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        return await self._run_blocking(self._unsubscribe_sync, request)

    async def take_available(self, request: TopicSubscriptionRequest) -> Tuple[SampleEnvelope, ...]:
        return await self._run_blocking(self._take_available_sync, request)

    async def samples(self, request: TopicSubscriptionRequest):
        await self.subscribe(request)
        while True:
            for sample in await self.take_available(request):
                yield sample
            await asyncio.sleep(self.config.poll_interval_sec)

    async def close(self) -> None:
        await self._run_blocking(self.close_sync)

    def close_sync(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            _close_session(session)

    async def _run_blocking(self, function, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: function(*args))

    def _subscribe_sync(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        session = self._sessions.get(request.key)
        if session is not None:
            return session.state

        lookup = self._type_registry.lookup(request.type_name)
        if not lookup.available:
            return TopicSubscriptionState(
                request=request,
                status=SubscriptionStatus.UNRESOLVED_TYPE,
                message=lookup.resolution.message,
            )

        self._load_connext_module()
        self._prepare_runtime_environment()
        try:
            participant = self._dds.DomainParticipant(request.domain_id)
        except Exception as exc:
            nddshome = detect_nddshome()
            raise RuntimeError(
                f"Failed to create DDS DomainParticipant on domain {request.domain_id}. "
                f"{license_setup_message(nddshome)}"
            ) from exc

        try:
            topic = self._dds.DynamicData.Topic(
                participant,
                request.topic_name,
                lookup.dynamic_type,
            )
            reader_qos = self._reader_qos()
            if reader_qos is None:
                reader = self._dds.DynamicData.DataReader(participant, topic)
            else:
                reader = self._dds.DynamicData.DataReader(participant, topic, reader_qos)
        except Exception:
            _safe_close(participant)
            raise

        state = TopicSubscriptionState(
            request=request,
            status=SubscriptionStatus.READER_CREATED,
            message=f"reader created for {request.topic_name}",
        )
        self._sessions[request.key] = _SubscriptionSession(
            request=request,
            participant=participant,
            topic=topic,
            reader=reader,
            state=state,
        )
        return state

    def _unsubscribe_sync(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        session = self._sessions.pop(request.key, None)
        if session is None:
            return TopicSubscriptionState(
                request=request,
                status=SubscriptionStatus.STOPPED,
                message="subscription was not active",
            )
        _close_session(session)
        return session.state.with_status(SubscriptionStatus.STOPPED, "subscription stopped")

    def _take_available_sync(self, request: TopicSubscriptionRequest) -> Tuple[SampleEnvelope, ...]:
        session = self._sessions.get(request.key)
        if session is None:
            state = self._subscribe_sync(request)
            if state.status == SubscriptionStatus.UNRESOLVED_TYPE:
                return ()
            session = self._sessions[request.key]

        samples = tuple(
            sample for sample in (
                envelope_from_dynamic_sample(request, sample)
                for sample in _reader_take(session.reader, self.config.reader_take_max_samples)
            )
            if sample is not None
        )
        session.state = session.state.with_samples(samples)
        return samples

    def _load_connext_module(self) -> None:
        if self._dds is None:
            import rti.connextdds as dds
            self._dds = dds

    def _prepare_runtime_environment(self) -> None:
        if not self._uses_real_connext:
            return
        nddshome = detect_nddshome()
        ensure_rti_license(nddshome)

    def _reader_qos(self) -> Any:
        if self.config.reader_history_depth <= 0:
            return None
        self._load_connext_module()
        return bounded_dynamic_data_reader_qos(
            self._dds,
            history_depth=self.config.reader_history_depth,
            max_samples=self.config.reader_resource_max_samples or self.config.reader_history_depth,
            max_instances=self.config.reader_resource_max_instances,
            max_samples_per_instance=(
                self.config.reader_resource_max_samples_per_instance
                or self.config.reader_history_depth
            ),
        )


def envelope_from_dynamic_sample(
        request: TopicSubscriptionRequest,
        sample: Any,
) -> Optional[SampleEnvelope]:
    data, info = _sample_data_and_info(sample)
    if info is None:
        return None
    info_snapshot = sample_info_snapshot(info)
    return SampleEnvelope(
        subscription_key=request.key,
        domain_id=request.domain_id,
        topic_name=request.topic_name,
        type_name=request.type_name,
        data=data if info_snapshot.valid else None,
        info=info_snapshot,
        observed_at=time.time(),
    )


def sample_info_snapshot(info: Any) -> SampleInfoSnapshot:
    return SampleInfoSnapshot(
        valid=bool(_safe_attr(info, "valid", False)),
        source_timestamp=_timestamp_seconds(_safe_attr(info, "source_timestamp", None)),
        reception_timestamp=_timestamp_seconds(_safe_attr(info, "reception_timestamp", None)),
        instance_state=_to_text(_safe_attr(info, "instance_state", "")),
        view_state=_to_text(_safe_attr(info, "view_state", "")),
        sample_state=_to_text(_safe_attr(info, "sample_state", "")),
        rank=_rank_to_int(_safe_attr(info, "sample_rank", _safe_attr(info, "rank", 0))),
    )


def _sample_data_and_info(sample: Any) -> Tuple[Any, Any]:
    if isinstance(sample, tuple) and len(sample) == 2:
        return sample[0], sample[1]
    return getattr(sample, "data", None), getattr(sample, "info", None)


def bounded_dynamic_data_reader_qos(
        dds: Any,
        history_depth: int,
        max_samples: int,
        max_instances: int = 1,
        max_samples_per_instance: int = 0,
) -> Any:
    """Create bounded reader QoS for live soak/readback paths."""

    qos = dds.DataReaderQos()
    depth = max(1, int(history_depth))
    qos.history.kind = _keep_last_history_kind(dds)
    qos.history.depth = depth
    qos.resource_limits.max_samples = max(depth, int(max_samples))
    qos.resource_limits.max_instances = max(1, int(max_instances))
    qos.resource_limits.max_samples_per_instance = max(depth, int(max_samples_per_instance or depth))
    _set_if_present(qos.resource_limits, "initial_samples", min(depth, qos.resource_limits.max_samples))
    _set_if_present(qos.resource_limits, "initial_instances", min(1, qos.resource_limits.max_instances))
    _set_if_present(
        qos.resource_limits,
        "initial_samples_per_instance",
        min(depth, qos.resource_limits.max_samples_per_instance),
    )
    return qos


def _keep_last_history_kind(dds: Any) -> Any:
    for enum_name, value_name in (
            ("HistoryQosPolicyKind", "KEEP_LAST_HISTORY_QOS"),
            ("HistoryKind", "KEEP_LAST"),
            ("HistoryQosPolicyKind", "KEEP_LAST"),
    ):
        enum = getattr(dds, enum_name, None)
        value = getattr(enum, value_name, None)
        if value is not None:
            return value
    raise RuntimeError("Connext Python API does not expose a KEEP_LAST history QoS enum")


def _set_if_present(obj: Any, name: str, value: Any) -> None:
    if hasattr(obj, name):
        setattr(obj, name, value)


def _reader_take(reader: Any, max_samples: int = 0) -> Iterable[Any]:
    if max_samples > 0:
        select = getattr(reader, "select", None)
        if select is not None:
            selector = select()
            selector = selector.max_samples(max_samples)
            return selector.take()
    take = getattr(reader, "take")
    samples = take()
    if max_samples > 0:
        return tuple(samples)[:max_samples]
    return samples


def _timestamp_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    seconds = _safe_attr(value, "sec", _safe_attr(value, "seconds", None))
    nanoseconds = _safe_attr(value, "nanosec", _safe_attr(value, "nanoseconds", 0))
    if seconds is None:
        return None
    return float(seconds) + (float(nanoseconds or 0) / 1_000_000_000.0)


def _rank_to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    return int(_safe_attr(value, "sample", 0) or 0)


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _close_session(session: _SubscriptionSession) -> None:
    _safe_close(session.reader)
    participant = session.participant
    try:
        close_contained = getattr(participant, "close_contained_entities", None)
        if close_contained is not None:
            close_contained()
    finally:
        _safe_close(participant)


def _safe_close(entity: Any) -> None:
    close = getattr(entity, "close", None)
    if close is not None:
        close()