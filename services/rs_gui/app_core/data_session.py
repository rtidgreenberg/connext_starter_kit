"""DDS-free topic data session coordination for rs_gui_v2."""

from collections import defaultdict
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
import time

from .plotting import (
    PlotBufferSet,
    PlotBufferSnapshot,
    PlotUpdateResult,
    build_plot_buffer_sets,
)
from .subscriptions import (
    SampleCache,
    SampleEnvelope,
    SubscriptionStatus,
    TopicSubscriptionClient,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
)
from .types import TypeCatalog, TypeResolution
from .workspace import WorkspaceDocument, WorkspacePlotDefinition, WorkspacePlotSeries


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class DataSessionConfig:
    """Headless data-session limits and plotting behavior."""

    default_max_samples: int = 1024
    plot_min_interval_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "default_max_samples", max(1, int(self.default_max_samples)))
        object.__setattr__(self, "plot_min_interval_seconds", max(0.0, float(self.plot_min_interval_seconds)))


@dataclass(frozen=True)
class DataSessionUpdate:
    """Result of applying one batch of samples to a data session."""

    samples: Tuple[SampleEnvelope, ...] = field(default_factory=tuple)
    dropped_samples: Mapping[str, int] = field(default_factory=dict)
    plot_results: Tuple[PlotUpdateResult, ...] = field(default_factory=tuple)
    updated_states: Tuple[TopicSubscriptionState, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))
        object.__setattr__(self, "dropped_samples", _frozen_mapping({
            str(key): int(value)
            for key, value in dict(self.dropped_samples).items()
        }))
        object.__setattr__(self, "plot_results", tuple(self.plot_results))
        object.__setattr__(self, "updated_states", tuple(self.updated_states))

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def dropped_sample_count(self) -> int:
        return sum(self.dropped_samples.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "samples": [sample.to_dict() for sample in self.samples],
            "dropped_samples": dict(self.dropped_samples),
            "plot_results": [result.to_dict() for result in self.plot_results],
            "updated_states": [state.to_dict() for state in self.updated_states],
        }


@dataclass(frozen=True)
class DataSessionSnapshot:
    """Immutable state snapshot safe for future GUI rendering."""

    workspace_name: str = ""
    subscriptions: Tuple[TopicSubscriptionState, ...] = field(default_factory=tuple)
    samples: Mapping[str, Tuple[SampleEnvelope, ...]] = field(default_factory=dict)
    plots: Tuple[PlotBufferSnapshot, ...] = field(default_factory=tuple)
    type_resolutions: Mapping[str, TypeResolution] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_name", str(self.workspace_name))
        object.__setattr__(self, "subscriptions", tuple(self.subscriptions))
        object.__setattr__(self, "samples", _frozen_mapping({
            str(key): tuple(value)
            for key, value in dict(self.samples).items()
        }))
        object.__setattr__(self, "plots", tuple(self.plots))
        object.__setattr__(self, "type_resolutions", _frozen_mapping(self.type_resolutions))
        object.__setattr__(self, "updated_at", float(self.updated_at))

    @property
    def sample_count(self) -> int:
        return sum(len(samples) for samples in self.samples.values())

    @property
    def plot_point_count(self) -> int:
        return sum(plot.point_count for plot in self.plots)

    def subscription_state(self, subscription_key: str) -> Optional[TopicSubscriptionState]:
        for state in self.subscriptions:
            if state.request.key == subscription_key:
                return state
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_name": self.workspace_name,
            "subscriptions": [state.to_dict() for state in self.subscriptions],
            "samples": {
                key: [sample.to_dict() for sample in samples]
                for key, samples in self.samples.items()
            },
            "plots": [plot.to_dict() for plot in self.plots],
            "type_resolutions": {
                key: resolution.to_dict()
                for key, resolution in self.type_resolutions.items()
            },
            "updated_at": self.updated_at,
        }


class DataSessionCoordinator:
    """Coordinate workspace subscriptions, sample caches, and plot buffers."""

    def __init__(
            self,
            workspace: WorkspaceDocument,
            subscription_client: TopicSubscriptionClient,
            type_catalog: Optional[TypeCatalog] = None,
            config: Optional[DataSessionConfig] = None,
    ) -> None:
        self.workspace = workspace
        self.subscription_client = subscription_client
        self.type_catalog = type_catalog or TypeCatalog()
        self.config = config or DataSessionConfig()
        self.sample_cache = SampleCache(default_max_samples=self.config.default_max_samples)
        self._requests = {
            request.key: request
            for request in build_workspace_subscription_requests(
                workspace,
                default_max_samples=self.config.default_max_samples,
            )
        }
        self._states: Dict[str, TopicSubscriptionState] = {
            key: TopicSubscriptionState(request=request)
            for key, request in self._requests.items()
        }
        self._type_resolutions: Dict[str, TypeResolution] = {}
        self._plot_buffers = build_plot_buffer_sets(
            workspace.plots,
            min_interval_seconds=self.config.plot_min_interval_seconds,
        )

    @property
    def requests(self) -> Tuple[TopicSubscriptionRequest, ...]:
        return tuple(self._requests[key] for key in sorted(self._requests))

    @property
    def plot_buffers(self) -> Tuple[PlotBufferSet, ...]:
        return tuple(self._plot_buffers)

    def resolve_requests(self) -> Mapping[str, TypeResolution]:
        for key, request in self._requests.items():
            self._type_resolutions[key] = self.type_catalog.resolve(request.type_name)
        return _frozen_mapping(self._type_resolutions)

    async def start(self) -> DataSessionSnapshot:
        self.resolve_requests()
        for key, request in self._requests.items():
            resolution = self._type_resolutions[key]
            if not resolution.available:
                self._states[key] = TopicSubscriptionState(
                    request=request,
                    status=SubscriptionStatus.UNRESOLVED_TYPE,
                    message=_resolution_message(resolution),
                )
                continue
            self.sample_cache.configure(request)
            try:
                self._states[key] = await self.subscription_client.subscribe(request)
            except Exception as exc:
                self._states[key] = TopicSubscriptionState(
                    request=request,
                    status=SubscriptionStatus.ERROR,
                    message=str(exc),
                )
        return self.snapshot()

    async def poll_once(self) -> DataSessionUpdate:
        samples: List[SampleEnvelope] = []
        errored_states: List[TopicSubscriptionState] = []
        for key in sorted(self._states):
            state = self._states[key]
            if not state.active:
                continue
            try:
                samples.extend(await self.subscription_client.take_available(state.request))
            except Exception as exc:
                errored = state.with_status(SubscriptionStatus.ERROR, str(exc))
                self._states[key] = errored
                errored_states.append(errored)

        update = self.apply_samples(samples)
        if not errored_states:
            return update
        return DataSessionUpdate(
            samples=update.samples,
            dropped_samples=update.dropped_samples,
            plot_results=update.plot_results,
            updated_states=update.updated_states + tuple(errored_states),
        )

    def apply_samples(self, samples: Iterable[SampleEnvelope]) -> DataSessionUpdate:
        samples = tuple(samples)
        samples_by_key: Dict[str, List[SampleEnvelope]] = defaultdict(list)
        dropped_by_key: Dict[str, int] = defaultdict(int)
        plot_results: List[PlotUpdateResult] = []

        for sample in samples:
            samples_by_key[sample.subscription_key].append(sample)
            request = self._requests.get(sample.subscription_key)
            dropped_by_key[sample.subscription_key] += self.sample_cache.append(
                sample,
                max_samples=request.max_samples if request is not None else None,
            )
            for plot_buffer in self._plot_buffers:
                plot_results.extend(plot_buffer.update_from_sample(sample))

        updated_states = []
        for key in sorted(samples_by_key):
            state = self._states.get(key)
            if state is None:
                continue
            updated = state.with_samples(
                samples_by_key[key],
                dropped_samples=dropped_by_key.get(key, 0),
            )
            self._states[key] = updated
            updated_states.append(updated)

        return DataSessionUpdate(
            samples=samples,
            dropped_samples=dropped_by_key,
            plot_results=tuple(plot_results),
            updated_states=tuple(updated_states),
        )

    async def stop(self) -> DataSessionSnapshot:
        for key in sorted(self._states):
            state = self._states[key]
            if not state.active:
                continue
            try:
                self._states[key] = await self.subscription_client.unsubscribe(state.request)
            except Exception as exc:
                self._states[key] = state.with_status(SubscriptionStatus.ERROR, str(exc))
        return self.snapshot()

    async def close(self) -> None:
        await self.stop()
        await self.subscription_client.close()

    def snapshot(self) -> DataSessionSnapshot:
        return DataSessionSnapshot(
            workspace_name=self.workspace.name,
            subscriptions=tuple(self._states[key] for key in sorted(self._states)),
            samples={
                key: self.sample_cache.snapshot(key)
                for key in sorted(self._requests)
            },
            plots=tuple(plot.snapshot() for plot in self._plot_buffers),
            type_resolutions={
                key: self._type_resolutions[key]
                for key in sorted(self._type_resolutions)
            },
        )


def build_workspace_subscription_requests(
        workspace: WorkspaceDocument,
        default_max_samples: int = 1024,
) -> Tuple[TopicSubscriptionRequest, ...]:
    """Build topic subscription intent from workspace topics, plots, and subscriptions."""
    requests: Dict[str, TopicSubscriptionRequest] = {}

    def add(request: TopicSubscriptionRequest) -> None:
        existing = requests.get(request.key)
        if existing is None:
            requests[request.key] = request
            return
        requests[request.key] = _merge_subscription_requests(existing, request)

    for request in workspace.subscriptions:
        add(request)

    for key in sorted(workspace.topic_selections.selections):
        selection = workspace.topic_selections.selections[key]
        if not selection.enabled:
            continue
        add(TopicSubscriptionRequest(
            domain_id=selection.domain_id,
            topic_name=selection.topic_name,
            type_name=selection.type_name,
            selected_fields=selection.selected_fields,
            max_samples=default_max_samples,
        ))

    for plot in workspace.plots:
        if not plot.enabled:
            continue
        for series in plot.series:
            if not series.enabled:
                continue
            add(_request_from_plot_series(series, default_max_samples=default_max_samples))

    return tuple(requests[key] for key in sorted(requests))


def _request_from_plot_series(
        series: WorkspacePlotSeries,
        default_max_samples: int,
) -> TopicSubscriptionRequest:
    return TopicSubscriptionRequest(
        domain_id=series.domain_id,
        topic_name=series.topic_name,
        type_name=series.type_name,
        selected_fields=(series.field_path,),
        max_samples=default_max_samples,
    )


def _merge_subscription_requests(
        primary: TopicSubscriptionRequest,
        secondary: TopicSubscriptionRequest,
) -> TopicSubscriptionRequest:
    fields = list(primary.selected_fields)
    for field_path in secondary.selected_fields:
        if field_path not in fields:
            fields.append(field_path)
    return TopicSubscriptionRequest(
        domain_id=primary.domain_id,
        topic_name=primary.topic_name,
        type_name=primary.type_name,
        selected_fields=tuple(fields),
        max_samples=primary.max_samples,
        request_id=primary.request_id,
        created_at=primary.created_at,
    )


def _resolution_message(resolution: TypeResolution) -> str:
    if resolution.message:
        return resolution.message
    return f"type resolution is {resolution.status.value} for {resolution.type_name}"