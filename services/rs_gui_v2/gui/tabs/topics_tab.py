"""Topics tab view models for discovery, field picking, and samples."""

from dataclasses import dataclass, field
import time
from typing import Any, Iterable, Mapping, Optional, Tuple

from app_core import (
    DiscoveredTopic,
    FieldCatalog,
    FieldCatalogStatus,
    FieldDescriptor,
    SampleEnvelope,
    SubscriptionStatus,
    TopicDiscoveryState,
    TopicSelectionState,
    TopicSubscriptionState,
    TypeAvailabilityStatus,
    TypeResolution,
)


@dataclass(frozen=True)
class TopicActionView:
    """One Topics-tab command affordance."""

    action_id: str
    label: str
    enabled: bool
    reason: str = ""


@dataclass(frozen=True)
class TopicRow:
    """One discovered topic row shown in the Topics tab."""

    topic_key: str
    domain_id: int
    topic_name: str
    type_name: str
    state: str
    writers: int
    readers: int
    partitions: str = ""
    internal: bool = False
    selected: bool = False
    selected_for_workspace: bool = False
    type_status: str = "unknown"
    subscription_status: str = "idle"
    sample_count: int = 0
    diagnostic: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "writers", int(self.writers))
        object.__setattr__(self, "readers", int(self.readers))
        object.__setattr__(self, "internal", bool(self.internal))
        object.__setattr__(self, "selected", bool(self.selected))
        object.__setattr__(self, "selected_for_workspace", bool(self.selected_for_workspace))
        object.__setattr__(self, "sample_count", int(self.sample_count))


@dataclass(frozen=True)
class TopicFieldRow:
    """One field picker row derived from a DDS-free field catalog."""

    path: str
    name: str
    type_name: str
    scalar_kind: str
    collection_kind: str
    depth: int = 0
    selected: bool = False
    plot_selected: bool = False
    plottable: bool = False
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "depth", int(self.depth))
        object.__setattr__(self, "selected", bool(self.selected))
        object.__setattr__(self, "plot_selected", bool(self.plot_selected))
        object.__setattr__(self, "plottable", bool(self.plottable))


@dataclass(frozen=True)
class SampleInspectorRow:
    """One flattened sample value shown in the sample inspector."""

    path: str
    value: str
    value_kind: str = "value"
    valid: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "valid", bool(self.valid))


@dataclass(frozen=True)
class TopicsTabViewModel:
    """Immutable Topics-tab snapshot consumed by the GUI renderer."""

    domain_id: int = 0
    search_text: str = ""
    include_internal: bool = False
    selected_topic_key: str = ""
    rows: Tuple[TopicRow, ...] = field(default_factory=tuple)
    fields: Tuple[TopicFieldRow, ...] = field(default_factory=tuple)
    sample_rows: Tuple[SampleInspectorRow, ...] = field(default_factory=tuple)
    actions: Tuple[TopicActionView, ...] = field(default_factory=tuple)
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "include_internal", bool(self.include_internal))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "sample_rows", tuple(self.sample_rows))
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "diagnostics", tuple(str(item) for item in self.diagnostics))

    @property
    def selected_topic(self) -> Optional[TopicRow]:
        for row in self.rows:
            if row.topic_key == self.selected_topic_key:
                return row
        return None

    @property
    def visible_topic_count(self) -> int:
        return len(self.rows)

    @property
    def action_by_id(self) -> Mapping[str, TopicActionView]:
        return {action.action_id: action for action in self.actions}


def build_topics_tab_view_model(
        topics: Iterable[DiscoveredTopic] = (),
        selections: Optional[TopicSelectionState] = None,
        field_catalogs: Optional[Mapping[str, FieldCatalog]] = None,
        subscription_states: Iterable[TopicSubscriptionState] = (),
        samples: Iterable[SampleEnvelope] = (),
        domain_id: int = 0,
        search_text: str = "",
        include_internal: Optional[bool] = None,
        selected_topic_key: str = "",
        now: float = None,
) -> TopicsTabViewModel:
    """Build a Topics-tab snapshot from app-core discovery and data-session state."""

    selections = selections or TopicSelectionState()
    field_catalogs = dict(field_catalogs or {})
    subscription_states = tuple(subscription_states)
    samples = tuple(samples)
    include_internal = selections.include_internal if include_internal is None else bool(include_internal)
    now = time.time() if now is None else float(now)

    filtered_topics = tuple(sorted(
        (
            topic for topic in topics
            if topic.visible(include_internal=include_internal) and _matches_search(topic, search_text)
        ),
        key=lambda topic: (topic.domain_id, topic.topic_name.lower()),
    ))
    selected_topic_key = _selected_topic_key(filtered_topics, selections, selected_topic_key)
    states_by_topic = _subscription_states_by_topic(subscription_states)
    samples_by_topic = _samples_by_topic(samples)
    rows = tuple(
        _topic_row(
            topic,
            selections=selections,
            selected_topic_key=selected_topic_key,
            subscription_state=states_by_topic.get(topic.key),
            sample_count=len(samples_by_topic.get(topic.key, ())),
        )
        for topic in filtered_topics
    )
    selected_topic = next((topic for topic in filtered_topics if topic.key == selected_topic_key), None)
    selected_selection = (
        selections.selected_for(selected_topic.domain_id, selected_topic.topic_name)
        if selected_topic is not None else None
    )
    field_catalog = _field_catalog_for(selected_topic, field_catalogs) if selected_topic is not None else None
    fields = _field_rows(field_catalog, selected_selection)
    sample_rows = _sample_rows(selected_topic, samples_by_topic.get(selected_topic_key, ()))
    diagnostics = _diagnostics(
        topics=tuple(topics),
        visible_topics=filtered_topics,
        selected_topic=selected_topic,
        field_catalog=field_catalog,
        search_text=search_text,
        include_internal=include_internal,
    )
    actions = _topic_actions(selected_topic, states_by_topic.get(selected_topic_key), search_text)
    return TopicsTabViewModel(
        domain_id=domain_id,
        search_text=search_text,
        include_internal=include_internal,
        selected_topic_key=selected_topic_key,
        rows=rows,
        fields=fields,
        sample_rows=sample_rows,
        actions=actions,
        diagnostics=diagnostics,
        updated_at=now,
    )


def build_mock_topics_tab_view_model(now: float = 120.0) -> TopicsTabViewModel:
    """Return a deterministic Topics-tab snapshot for GUI smoke rendering."""

    topics = (
        DiscoveredTopic(
            domain_id=0,
            topic_name="RobotTelemetry",
            type_names=("Robot::Telemetry",),
            writer_count=1,
            reader_count=1,
            state=TopicDiscoveryState.TYPE_AVAILABLE,
            type_resolution=TypeResolution(
                type_name="Robot::Telemetry",
                status=TypeAvailabilityStatus.AVAILABLE,
                source="dds/datamodel/xml_gen/RobotTelemetry.xml",
                kind="struct",
                candidates=("Robot::Telemetry",),
            ),
            partitions=("/robot/alpha",),
            updated_at=now - 2,
        ),
        DiscoveredTopic(
            domain_id=0,
            topic_name="CameraStatus",
            type_names=("Camera::Status",),
            writer_count=1,
            reader_count=0,
            state=TopicDiscoveryState.UNRESOLVED,
            type_resolution=TypeResolution(
                type_name="Camera::Status",
                status=TypeAvailabilityStatus.MISSING,
                message="type is not available in the local catalog",
            ),
            partitions=("/sensors",),
            updated_at=now - 8,
        ),
        DiscoveredTopic(
            domain_id=0,
            topic_name="rti/service/monitoring/periodic",
            type_names=("RTI::Service::Monitoring::Periodic",),
            writer_count=1,
            reader_count=0,
            internal=True,
            state=TopicDiscoveryState.INTERNAL,
            type_resolution=TypeResolution(
                type_name="RTI::Service::Monitoring::Periodic",
                status=TypeAvailabilityStatus.AVAILABLE,
                source="built-in monitoring XML",
                kind="struct",
                candidates=("RTI::Service::Monitoring::Periodic",),
            ),
            updated_at=now - 1,
        ),
    )
    selections = _mock_topic_selections(now)
    fields = {
        "Robot::Telemetry": FieldCatalog(
            type_name="Robot::Telemetry",
            fields=(
                FieldDescriptor("pose", "pose", "Robot::Pose", "struct", "struct", depth=0),
                FieldDescriptor("pose.x", "x", "float64", "float64", "float", parent_path="pose", depth=1),
                FieldDescriptor("pose.y", "y", "float64", "float64", "float", parent_path="pose", depth=1),
                FieldDescriptor("velocity", "velocity", "float32", "float32", "float", depth=0),
                FieldDescriptor("mode", "mode", "Robot::Mode", "enum", "enum", depth=0),
            ),
        )
    }
    subscription = TopicSubscriptionState(
        request=_mock_subscription_request(),
        status=SubscriptionStatus.RECEIVING,
        received_samples=42,
        updated_at=now,
    )
    samples = (
        SampleEnvelope(
            subscription_key=subscription.request.key,
            domain_id=0,
            topic_name="RobotTelemetry",
            type_name="Robot::Telemetry",
            data={"pose": {"x": 12.5, "y": -3.25}, "velocity": 1.7, "mode": "AUTO"},
            observed_at=now,
        ),
    )
    return build_topics_tab_view_model(
        topics=topics,
        selections=selections,
        field_catalogs=fields,
        subscription_states=(subscription,),
        samples=samples,
        domain_id=0,
        selected_topic_key="0:RobotTelemetry",
        now=now,
    )


def _mock_topic_selections(now: float) -> TopicSelectionState:
    from app_core import TopicSelection
    return TopicSelectionState().select(TopicSelection(
        domain_id=0,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        selected_fields=("pose.x", "pose.y", "velocity"),
        plot_fields=("velocity",),
        created_at=now - 60,
        updated_at=now - 10,
    ))


def _mock_subscription_request():
    from app_core import TopicSubscriptionRequest
    return TopicSubscriptionRequest(
        domain_id=0,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        selected_fields=("pose.x", "pose.y", "velocity"),
        max_samples=256,
    )


def _topic_row(
        topic: DiscoveredTopic,
        selections: TopicSelectionState,
        selected_topic_key: str,
        subscription_state: Optional[TopicSubscriptionState],
        sample_count: int,
) -> TopicRow:
    selection = selections.selected_for(topic.domain_id, topic.topic_name)
    return TopicRow(
        topic_key=topic.key,
        domain_id=topic.domain_id,
        topic_name=topic.topic_name,
        type_name=", ".join(topic.type_names) if topic.type_names else "(unknown)",
        state=topic.state.value,
        writers=topic.writer_count,
        readers=topic.reader_count,
        partitions=", ".join(topic.partitions),
        internal=topic.internal,
        selected=topic.key == selected_topic_key,
        selected_for_workspace=selection is not None,
        type_status=topic.type_resolution.status.value,
        subscription_status=subscription_state.status.value if subscription_state else "idle",
        sample_count=subscription_state.received_samples if subscription_state else sample_count,
        diagnostic=_topic_diagnostic(topic, subscription_state),
    )


def _field_rows(
        catalog: Optional[FieldCatalog],
        selection,
) -> Tuple[TopicFieldRow, ...]:
    if catalog is None or not catalog.available:
        return ()
    selected_fields = set(selection.selected_fields if selection else ())
    plot_fields = set(selection.plot_fields if selection else ())
    return tuple(
        TopicFieldRow(
            path=descriptor.path,
            name=descriptor.name,
            type_name=descriptor.type_name,
            scalar_kind=descriptor.scalar_kind.value,
            collection_kind=descriptor.collection_kind.value,
            depth=descriptor.depth,
            selected=descriptor.path in selected_fields,
            plot_selected=descriptor.path in plot_fields,
            plottable=descriptor.plottable,
            message=descriptor.message,
        )
        for descriptor in catalog.fields
    )


def _sample_rows(
        selected_topic: Optional[DiscoveredTopic],
        samples: Tuple[SampleEnvelope, ...],
) -> Tuple[SampleInspectorRow, ...]:
    if selected_topic is None or not samples:
        return ()
    sample = samples[-1]
    if not sample.valid:
        return (SampleInspectorRow("sample", "invalid sample", "invalid", valid=False),)
    return tuple(_flatten_sample_value(sample.data)) or (
        SampleInspectorRow("sample", _value_text(sample.data), _value_kind(sample.data)),
    )


def _flatten_sample_value(value: Any, path: str = "") -> Iterable[SampleInspectorRow]:
    if isinstance(value, Mapping):
        for key in sorted(value):
            next_path = f"{path}.{key}" if path else str(key)
            yield from _flatten_sample_value(value[key], next_path)
        return
    if isinstance(value, (tuple, list)):
        for index, item in enumerate(value[:8]):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            yield from _flatten_sample_value(item, next_path)
        if len(value) > 8:
            yield SampleInspectorRow(path or "sample", f"{len(value) - 8} more values", "sequence")
        return
    yield SampleInspectorRow(path or "sample", _value_text(value), _value_kind(value))


def _selected_topic_key(
        topics: Tuple[DiscoveredTopic, ...],
        selections: TopicSelectionState,
        selected_topic_key: str,
) -> str:
    keys = {topic.key for topic in topics}
    if selected_topic_key in keys:
        return selected_topic_key
    for topic in topics:
        if selections.selected_for(topic.domain_id, topic.topic_name) is not None:
            return topic.key
    return topics[0].key if topics else ""


def _subscription_states_by_topic(states: Iterable[TopicSubscriptionState]) -> Mapping[str, TopicSubscriptionState]:
    by_topic = {}
    for state in states:
        request = state.request
        by_topic[f"{request.domain_id}:{request.topic_name}"] = state
    return by_topic


def _samples_by_topic(samples: Iterable[SampleEnvelope]) -> Mapping[str, Tuple[SampleEnvelope, ...]]:
    by_topic = {}
    for sample in samples:
        key = f"{sample.domain_id}:{sample.topic_name}"
        by_topic[key] = by_topic.get(key, ()) + (sample,)
    return by_topic


def _field_catalog_for(
        topic: DiscoveredTopic,
        field_catalogs: Mapping[str, FieldCatalog],
) -> Optional[FieldCatalog]:
    names = (topic.type_resolution.resolved_type_name, topic.type_resolution.type_name) + topic.type_names
    for name in names:
        if name and name in field_catalogs:
            return field_catalogs[name]
    return None


def _topic_actions(
        selected_topic: Optional[DiscoveredTopic],
        subscription_state: Optional[TopicSubscriptionState],
        search_text: str,
) -> Tuple[TopicActionView, ...]:
    active = bool(subscription_state and subscription_state.active)
    can_subscribe = bool(selected_topic and selected_topic.type_resolution.available and not active)
    subscribe_reason = "" if can_subscribe else _subscribe_disabled_reason(selected_topic, active)
    return (
        TopicActionView("subscribe", "Subscribe", can_subscribe, subscribe_reason),
        TopicActionView("unsubscribe", "Unsubscribe", active, "reader is not active" if not active else ""),
        TopicActionView("toggle_internal", "Show Internal", True),
        TopicActionView("clear_filter", "Clear Filter", bool(search_text), "filter is already empty" if not search_text else ""),
    )


def _subscribe_disabled_reason(selected_topic: Optional[DiscoveredTopic], active: bool) -> str:
    if selected_topic is None:
        return "no topic is selected"
    if active:
        return "reader is already active"
    if not selected_topic.type_resolution.available:
        return selected_topic.type_resolution.message or "type is not available"
    return ""


def _diagnostics(
        topics: Tuple[DiscoveredTopic, ...],
        visible_topics: Tuple[DiscoveredTopic, ...],
        selected_topic: Optional[DiscoveredTopic],
        field_catalog: Optional[FieldCatalog],
        search_text: str,
        include_internal: bool,
) -> Tuple[str, ...]:
    diagnostics = []
    hidden_internal = sum(1 for topic in topics if topic.internal and not include_internal)
    if hidden_internal:
        diagnostics.append(f"{hidden_internal} internal topic(s) hidden")
    if search_text and not visible_topics:
        diagnostics.append("No topics match the current filter")
    if selected_topic is None:
        diagnostics.append("No topic selected")
    elif selected_topic.state == TopicDiscoveryState.AMBIGUOUS:
        diagnostics.append("Selected topic has multiple discovered type names")
    elif not selected_topic.type_resolution.available:
        diagnostics.append(selected_topic.type_resolution.message or "Selected topic type is not available")
    elif field_catalog is None:
        diagnostics.append("No field catalog is loaded for the selected type")
    elif field_catalog.status != FieldCatalogStatus.AVAILABLE:
        diagnostics.append(field_catalog.message or f"Field catalog is {field_catalog.status.value}")
    return tuple(diagnostics)


def _topic_diagnostic(
        topic: DiscoveredTopic,
        subscription_state: Optional[TopicSubscriptionState],
) -> str:
    if topic.state == TopicDiscoveryState.AMBIGUOUS:
        return topic.type_resolution.message or "multiple type names"
    if topic.type_resolution.status == TypeAvailabilityStatus.MISSING:
        return topic.type_resolution.message
    if subscription_state and subscription_state.status in (SubscriptionStatus.ERROR, SubscriptionStatus.UNRESOLVED_TYPE):
        return subscription_state.message
    return ""


def _matches_search(topic: DiscoveredTopic, search_text: str) -> bool:
    needle = search_text.strip().lower()
    if not needle:
        return True
    haystack = " ".join((
        topic.topic_name,
        " ".join(topic.type_names),
        topic.state.value,
        " ".join(topic.partitions),
    )).lower()
    return needle in haystack


def _value_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "text"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, (tuple, list)):
        return "sequence"
    return type(value).__name__
