"""DDS-free topic subscription models and bounded sample cache for rs_gui_v2."""

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, AsyncIterator, Deque, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple
import time


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _tuple_of_text(value: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(str(item) for item in value)


class SubscriptionStatus(str, Enum):
    """Lifecycle state for a requested topic subscription."""

    REQUESTED = "requested"
    READER_CREATED = "reader_created"
    MATCHED = "matched"
    RECEIVING = "receiving"
    PAUSED = "paused"
    STOPPED = "stopped"
    UNRESOLVED_TYPE = "unresolved_type"
    ERROR = "error"


@dataclass(frozen=True)
class TopicSubscriptionRequest:
    """Declarative request to subscribe to a DDS topic."""

    domain_id: int
    topic_name: str
    type_name: str
    selected_fields: Tuple[str, ...] = field(default_factory=tuple)
    max_samples: int = 1024
    request_id: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "topic_name", str(self.topic_name))
        object.__setattr__(self, "type_name", str(self.type_name))
        object.__setattr__(self, "selected_fields", _tuple_of_text(self.selected_fields))
        object.__setattr__(self, "max_samples", max(1, int(self.max_samples)))
        if not self.request_id:
            object.__setattr__(self, "request_id", subscription_key(
                self.domain_id, self.topic_name, self.type_name
            ))

    @property
    def key(self) -> str:
        return subscription_key(self.domain_id, self.topic_name, self.type_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_name": self.type_name,
            "selected_fields": list(self.selected_fields),
            "max_samples": self.max_samples,
            "request_id": self.request_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TopicSubscriptionRequest":
        return cls(
            domain_id=int(data.get("domain_id", 0)),
            topic_name=str(data.get("topic_name", "")),
            type_name=str(data.get("type_name", "")),
            selected_fields=tuple(data.get("selected_fields", ())),
            max_samples=int(data.get("max_samples", 1024)),
            request_id=str(data.get("request_id", "")),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(frozen=True)
class SampleInfoSnapshot:
    """DDS-free sample metadata used by subscriptions and caches."""

    valid: bool = True
    source_timestamp: Optional[float] = None
    reception_timestamp: Optional[float] = None
    instance_state: str = ""
    view_state: str = ""
    sample_state: str = ""
    rank: int = 0
    native: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "valid", bool(self.valid))
        if self.source_timestamp is not None:
            object.__setattr__(self, "source_timestamp", float(self.source_timestamp))
        if self.reception_timestamp is not None:
            object.__setattr__(self, "reception_timestamp", float(self.reception_timestamp))
        object.__setattr__(self, "rank", int(self.rank))
        object.__setattr__(self, "native", _frozen_mapping(self.native))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "source_timestamp": self.source_timestamp,
            "reception_timestamp": self.reception_timestamp,
            "instance_state": self.instance_state,
            "view_state": self.view_state,
            "sample_state": self.sample_state,
            "rank": self.rank,
            "native": dict(self.native),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SampleInfoSnapshot":
        return cls(
            valid=bool(data.get("valid", True)),
            source_timestamp=data.get("source_timestamp"),
            reception_timestamp=data.get("reception_timestamp"),
            instance_state=str(data.get("instance_state", "")),
            view_state=str(data.get("view_state", "")),
            sample_state=str(data.get("sample_state", "")),
            rank=int(data.get("rank", 0)),
            native=data.get("native", {}),
        )


@dataclass(frozen=True)
class SampleEnvelope:
    """DDS-free sample wrapper returned by subscription clients."""

    subscription_key: str
    domain_id: int
    topic_name: str
    type_name: str
    data: Any = None
    info: SampleInfoSnapshot = field(default_factory=SampleInfoSnapshot)
    observed_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        if not isinstance(self.info, SampleInfoSnapshot):
            object.__setattr__(self, "info", SampleInfoSnapshot.from_dict(self.info))

    @property
    def valid(self) -> bool:
        return self.info.valid

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subscription_key": self.subscription_key,
            "domain_id": self.domain_id,
            "topic_name": self.topic_name,
            "type_name": self.type_name,
            "data": self.data,
            "info": self.info.to_dict(),
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SampleEnvelope":
        return cls(
            subscription_key=str(data.get("subscription_key", "")),
            domain_id=int(data.get("domain_id", 0)),
            topic_name=str(data.get("topic_name", "")),
            type_name=str(data.get("type_name", "")),
            data=data.get("data"),
            info=SampleInfoSnapshot.from_dict(data.get("info", {})),
            observed_at=float(data.get("observed_at", time.time())),
        )


@dataclass(frozen=True)
class TopicSubscriptionState:
    """Operator-facing state for one topic subscription."""

    request: TopicSubscriptionRequest
    status: SubscriptionStatus = SubscriptionStatus.REQUESTED
    message: str = ""
    received_samples: int = 0
    invalid_samples: int = 0
    dropped_samples: int = 0
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.status, SubscriptionStatus):
            object.__setattr__(self, "status", SubscriptionStatus(self.status))
        object.__setattr__(self, "received_samples", int(self.received_samples))
        object.__setattr__(self, "invalid_samples", int(self.invalid_samples))
        object.__setattr__(self, "dropped_samples", int(self.dropped_samples))

    @property
    def active(self) -> bool:
        return self.status in (
            SubscriptionStatus.READER_CREATED,
            SubscriptionStatus.MATCHED,
            SubscriptionStatus.RECEIVING,
            SubscriptionStatus.PAUSED,
        )

    def with_status(self, status: SubscriptionStatus, message: str = "") -> "TopicSubscriptionState":
        return replace(self, status=status, message=message, updated_at=time.time())

    def with_samples(self, samples: Iterable[SampleEnvelope], dropped_samples: int = 0) -> "TopicSubscriptionState":
        samples = tuple(samples)
        valid_count = sum(1 for sample in samples if sample.valid)
        invalid_count = len(samples) - valid_count
        status = SubscriptionStatus.RECEIVING if samples else self.status
        return replace(
            self,
            status=status,
            received_samples=self.received_samples + valid_count,
            invalid_samples=self.invalid_samples + invalid_count,
            dropped_samples=self.dropped_samples + int(dropped_samples),
            updated_at=time.time(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "status": self.status.value,
            "message": self.message,
            "received_samples": self.received_samples,
            "invalid_samples": self.invalid_samples,
            "dropped_samples": self.dropped_samples,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TopicSubscriptionState":
        return cls(
            request=TopicSubscriptionRequest.from_dict(data["request"]),
            status=SubscriptionStatus(data.get("status", SubscriptionStatus.REQUESTED.value)),
            message=str(data.get("message", "")),
            received_samples=int(data.get("received_samples", 0)),
            invalid_samples=int(data.get("invalid_samples", 0)),
            dropped_samples=int(data.get("dropped_samples", 0)),
            updated_at=float(data.get("updated_at", time.time())),
        )


class TopicSubscriptionClient(Protocol):
    """Transport-specific topic subscription contract used by app-core sessions."""

    async def subscribe(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        """Create or reuse a subscription for the requested topic."""

    async def unsubscribe(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        """Stop a topic subscription if it is active."""

    async def take_available(self, request: TopicSubscriptionRequest) -> Tuple[SampleEnvelope, ...]:
        """Return currently available samples for the requested topic."""

    async def samples(self, request: TopicSubscriptionRequest) -> AsyncIterator[SampleEnvelope]:
        """Yield samples for the requested topic."""

    async def close(self) -> None:
        """Release any resources owned by the subscription client."""


class SampleCache:
    """Bounded in-memory sample cache keyed by subscription."""

    def __init__(self, default_max_samples: int = 1024) -> None:
        self.default_max_samples = max(1, int(default_max_samples))
        self._samples: Dict[str, Deque[SampleEnvelope]] = {}
        self._limits: Dict[str, int] = {}
        self._dropped: Dict[str, int] = defaultdict(int)

    def configure(self, request: TopicSubscriptionRequest) -> None:
        self._limits[request.key] = request.max_samples
        self._samples.setdefault(request.key, deque(maxlen=request.max_samples))

    def append(self, sample: SampleEnvelope, max_samples: Optional[int] = None) -> int:
        key = sample.subscription_key
        limit = max(1, int(max_samples or self._limits.get(key, self.default_max_samples)))
        existing = self._samples.get(key)
        if existing is None or existing.maxlen != limit:
            existing_values = list(existing or ())[-limit:]
            existing = deque(existing_values, maxlen=limit)
            self._samples[key] = existing
            self._limits[key] = limit
        dropped = 1 if len(existing) == existing.maxlen else 0
        existing.append(sample)
        self._dropped[key] += dropped
        return dropped

    def extend(self, samples: Iterable[SampleEnvelope], max_samples: Optional[int] = None) -> int:
        dropped = 0
        for sample in samples:
            dropped += self.append(sample, max_samples=max_samples)
        return dropped

    def snapshot(self, subscription_key: str) -> Tuple[SampleEnvelope, ...]:
        return tuple(self._samples.get(subscription_key, ()))

    def dropped_count(self, subscription_key: str) -> int:
        return int(self._dropped.get(subscription_key, 0))

    def clear(self, subscription_key: str) -> None:
        self._samples.pop(subscription_key, None)
        self._limits.pop(subscription_key, None)
        self._dropped.pop(subscription_key, None)


class FakeTopicSubscriptionClient:
    """DDS-free subscription client with deterministic queued samples."""

    def __init__(self) -> None:
        self.states: Dict[str, TopicSubscriptionState] = {}
        self.queued_samples: Dict[str, List[SampleEnvelope]] = defaultdict(list)
        self.subscribed_requests: List[TopicSubscriptionRequest] = []
        self.unsubscribed_requests: List[TopicSubscriptionRequest] = []
        self.taken_requests: List[TopicSubscriptionRequest] = []
        self.closed = False

    async def subscribe(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        state = self.states.get(request.key)
        if state is None:
            state = TopicSubscriptionState(
                request=request,
                status=SubscriptionStatus.READER_CREATED,
                message=f"fake reader created for {request.topic_name}",
            )
        self.states[request.key] = state
        self.subscribed_requests.append(request)
        return state

    async def unsubscribe(self, request: TopicSubscriptionRequest) -> TopicSubscriptionState:
        state = self.states.get(request.key, TopicSubscriptionState(request=request))
        state = state.with_status(SubscriptionStatus.STOPPED, "fake subscription stopped")
        self.states[request.key] = state
        self.unsubscribed_requests.append(request)
        return state

    async def take_available(self, request: TopicSubscriptionRequest) -> Tuple[SampleEnvelope, ...]:
        self.taken_requests.append(request)
        samples = tuple(self.queued_samples.pop(request.key, ()))
        state = self.states.get(request.key, TopicSubscriptionState(request=request))
        self.states[request.key] = state.with_samples(samples)
        return samples

    async def samples(self, request: TopicSubscriptionRequest) -> AsyncIterator[SampleEnvelope]:
        for sample in await self.take_available(request):
            yield sample

    async def close(self) -> None:
        self.closed = True

    def queue_sample(self, sample: SampleEnvelope) -> None:
        self.queued_samples[sample.subscription_key].append(sample)

    def queue_samples(self, samples: Iterable[SampleEnvelope]) -> None:
        for sample in samples:
            self.queue_sample(sample)


def subscription_key(domain_id: int, topic_name: str, type_name: str) -> str:
    return f"{int(domain_id)}:{topic_name}:{type_name}"