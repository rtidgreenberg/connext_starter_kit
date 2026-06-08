"""Topics tab controller wiring discovery snapshots into GUI views."""

from dataclasses import dataclass, replace
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

from app_core import (
    AppCommand,
    CommandResult,
    CommandStatus,
    DataSessionSnapshot,
    FieldCatalog,
    SampleEnvelope,
    SubscriptionStatus,
    TopicDiscoveryFacade,
    TopicSelection,
    TopicSelectionState,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
)

from .topics_tab import TopicsTabViewModel, build_topics_tab_view_model


@dataclass(frozen=True)
class TopicsTabControllerConfig:
    """Runtime wiring options for the Topics tab controller."""

    domain_id: int = 0
    include_internal: bool = False
    search_text: str = ""
    selected_topic_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_id", int(self.domain_id))
        object.__setattr__(self, "include_internal", bool(self.include_internal))
        object.__setattr__(self, "search_text", str(self.search_text))
        object.__setattr__(self, "selected_topic_key", str(self.selected_topic_key))


class TopicsTabController:
    """Build Topics tab snapshots from app-core discovery and data-session state."""

    def __init__(
            self,
            discovery_facade: Optional[TopicDiscoveryFacade] = None,
            field_catalogs: Optional[Mapping[str, FieldCatalog]] = None,
            subscription_states: Tuple[TopicSubscriptionState, ...] = (),
            samples: Tuple[SampleEnvelope, ...] = (),
            data_session_snapshot_provider: Optional[Callable[[], Optional[DataSessionSnapshot]]] = None,
            config: Optional[TopicsTabControllerConfig] = None,
            clock=time.time,
    ) -> None:
        self._discovery_facade = discovery_facade
        self._field_catalogs = dict(field_catalogs or {})
        self._subscription_states = tuple(subscription_states)
        self._subscription_overrides = {}
        self._samples = tuple(samples)
        self._data_session_snapshot_provider = data_session_snapshot_provider
        self._config = config or TopicsTabControllerConfig()
        self._selection_state = TopicSelectionState(include_internal=self._config.include_internal)
        self._clock = clock
        self._last_view = TopicsTabViewModel(domain_id=self._config.domain_id)

    @property
    def discovery_facade(self) -> Optional[TopicDiscoveryFacade]:
        return self._discovery_facade

    @property
    def selected_topic_key(self) -> str:
        return self._config.selected_topic_key

    @property
    def include_internal(self) -> bool:
        return self._config.include_internal

    @property
    def search_text(self) -> str:
        return self._config.search_text

    @property
    def last_view(self) -> TopicsTabViewModel:
        return self._last_view

    def select_topic(self, topic_key: str) -> None:
        self._config = replace(self._config, selected_topic_key=str(topic_key))

    def set_search_text(self, value: str) -> None:
        self._config = replace(self._config, search_text=str(value))

    def set_include_internal(self, value: bool) -> None:
        self._config = replace(self._config, include_internal=bool(value))
        self._selection_state = TopicSelectionState(
            selections=self._selection_state.selections,
            include_internal=bool(value),
        )

    def set_field_catalogs(self, catalogs: Mapping[str, FieldCatalog]) -> None:
        self._field_catalogs = dict(catalogs)

    def set_subscription_states(self, states: Tuple[TopicSubscriptionState, ...]) -> None:
        self._subscription_states = tuple(states)

    def set_samples(self, samples: Tuple[SampleEnvelope, ...]) -> None:
        self._samples = tuple(samples)

    def apply_data_session_snapshot(self, snapshot: DataSessionSnapshot) -> None:
        """Use a data-session snapshot as the source for subscription/sample state."""

        self._subscription_states, self._samples = topics_inputs_from_data_session_snapshot(snapshot)

    def workspace_topic_selections(self) -> TopicSelectionState:
        """Return persistable topic/field display intent for the workspace layer."""

        selections = self._current_selections()
        return TopicSelectionState(
            selections=selections.selections,
            include_internal=self._config.include_internal,
        )

    def workspace_subscription_requests(self) -> Tuple[TopicSubscriptionRequest, ...]:
        """Return active subscription requests that should survive restarts."""

        return tuple(
            state.request for state in self._effective_subscription_states()
            if state.active
        )

    def workspace_metadata(self) -> Mapping[str, Any]:
        """Return GUI-only Topics preferences for workspace metadata."""

        return {
            "domain_id": self._config.domain_id,
            "search_text": self._config.search_text,
            "selected_topic_key": self._config.selected_topic_key,
        }

    def apply_workspace_intent(
            self,
            selections: TopicSelectionState,
            subscriptions: Tuple[TopicSubscriptionRequest, ...] = (),
            metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Restore declarative Topics state from a workspace document."""

        metadata = dict(metadata or {})
        selections = selections if isinstance(selections, TopicSelectionState) else TopicSelectionState.from_dict(selections)
        self._selection_state = selections
        if self._discovery_facade is not None:
            self._discovery_facade.set_selections(selections)
        self._config = replace(
            self._config,
            include_internal=selections.include_internal,
            search_text=str(metadata.get("search_text", "")),
            selected_topic_key=str(metadata.get("selected_topic_key", "")),
        )
        self._subscription_overrides = {
            request.key: TopicSubscriptionState(
                request=request,
                status=SubscriptionStatus.READER_CREATED,
                message="subscription restored from workspace",
                updated_at=self._clock(),
            )
            for request in subscriptions
        }

    async def handle_command(self, command: AppCommand) -> CommandResult:
        """Apply a queued Topics command to the controller state."""

        payload = dict(command.payload)
        if command.command_type == "topics.select":
            topic_key = str(payload.get("topic_key") or command.target)
            self.select_topic(topic_key)
            return _command_result(command, f"Selected topic {topic_key}")
        if command.command_type == "topics.set_search":
            search_text = str(payload.get("search_text", ""))
            self.set_search_text(search_text)
            return _command_result(command, f"Set topic filter to {search_text!r}")
        if command.command_type == "topics.set_include_internal":
            include_internal = bool(payload.get("include_internal", False))
            self.set_include_internal(include_internal)
            return _command_result(command, f"Set internal topic visibility to {include_internal}")
        if command.command_type == "topics.subscribe":
            state = self.subscribe_topic(payload)
            return _command_result(command, f"Subscribed to {state.request.topic_name}", {"subscription_key": state.request.key})
        if command.command_type == "topics.unsubscribe":
            state = self.unsubscribe_topic(payload)
            return _command_result(command, f"Unsubscribed from {state.request.topic_name}", {"subscription_key": state.request.key})
        if command.command_type == "topics.set_field_selected":
            selection = self.set_field_selected(
                payload,
                field_path=str(payload.get("field_path", "")),
                selected=payload.get("selected"),
            )
            return _command_result(command, f"Updated selected fields for {selection.topic_name}")
        if command.command_type == "topics.set_plot_field_selected":
            selection = self.set_plot_field_selected(
                payload,
                field_path=str(payload.get("field_path", "")),
                selected=payload.get("selected"),
            )
            return _command_result(command, f"Updated plot fields for {selection.topic_name}")
        raise ValueError(f"Unsupported Topics command type: {command.command_type}")

    def subscribe_topic(self, payload: Mapping[str, Any]) -> TopicSubscriptionState:
        """Record a fake-first subscription request for the selected topic."""

        topic = self._topic_identity(payload)
        selected_fields = _tuple_payload(payload.get("selected_fields")) or self._selected_fields_for(topic[0], topic[1])
        request = TopicSubscriptionRequest(
            domain_id=topic[0],
            topic_name=topic[1],
            type_name=topic[2],
            selected_fields=selected_fields,
        )
        state = TopicSubscriptionState(
            request=request,
            status=SubscriptionStatus.READER_CREATED,
            message="subscription requested from GUI",
            updated_at=self._clock(),
        )
        self._subscription_overrides[request.key] = state
        self._upsert_selection(topic, selected_fields=selected_fields)
        self.select_topic(f"{topic[0]}:{topic[1]}")
        return state

    def unsubscribe_topic(self, payload: Mapping[str, Any]) -> TopicSubscriptionState:
        """Record a fake-first unsubscribe request for the selected topic."""

        topic = self._topic_identity(payload, allow_existing_state=True)
        existing = self._state_for_topic(topic[0], topic[1], topic[2])
        request = existing.request if existing is not None else TopicSubscriptionRequest(
            domain_id=topic[0],
            topic_name=topic[1],
            type_name=topic[2],
        )
        state = TopicSubscriptionState(
            request=request,
            status=SubscriptionStatus.STOPPED,
            message="subscription stopped from GUI",
            received_samples=existing.received_samples if existing is not None else 0,
            invalid_samples=existing.invalid_samples if existing is not None else 0,
            dropped_samples=existing.dropped_samples if existing is not None else 0,
            updated_at=self._clock(),
        )
        self._subscription_overrides[request.key] = state
        self.select_topic(f"{topic[0]}:{topic[1]}")
        return state

    def set_field_selected(
            self,
            payload: Mapping[str, Any],
            field_path: str,
            selected: Optional[bool] = None,
    ) -> TopicSelection:
        topic = self._topic_identity(payload)
        selection = self._selection_for(topic[0], topic[1], topic[2])
        selected_fields = _updated_tuple(selection.selected_fields, field_path, selected)
        return self._upsert_selection(topic, selected_fields=selected_fields)

    def set_plot_field_selected(
            self,
            payload: Mapping[str, Any],
            field_path: str,
            selected: Optional[bool] = None,
    ) -> TopicSelection:
        topic = self._topic_identity(payload)
        selection = self._selection_for(topic[0], topic[1], topic[2])
        plot_fields = _updated_tuple(selection.plot_fields, field_path, selected)
        return self._upsert_selection(topic, plot_fields=plot_fields)

    async def refresh_view(self) -> TopicsTabViewModel:
        """Scan discovery state and return the next Topics-tab view."""

        topics = ()
        diagnostics = []
        if self._data_session_snapshot_provider is not None:
            try:
                snapshot = self._data_session_snapshot_provider()
                if snapshot is not None:
                    self.apply_data_session_snapshot(snapshot)
            except Exception as exc:
                diagnostics.append(f"Data session snapshot failed: {exc}")

        selections = self._selection_state
        if self._discovery_facade is not None:
            selections = self._discovery_facade.selections
            try:
                topics = await self._discovery_facade.scan(
                    self._config.domain_id,
                    include_internal=self._config.include_internal,
                )
            except Exception as exc:
                diagnostics.append(f"Discovery scan failed: {exc}")

        view = build_topics_tab_view_model(
            topics=topics,
            selections=selections,
            field_catalogs=self._field_catalogs,
            subscription_states=self._effective_subscription_states(),
            samples=self._samples,
            domain_id=self._config.domain_id,
            search_text=self._config.search_text,
            include_internal=self._config.include_internal,
            selected_topic_key=self._config.selected_topic_key,
            now=self._clock(),
        )
        if diagnostics:
            view = replace(view, diagnostics=tuple(diagnostics) + view.diagnostics)
        if view.selected_topic_key and view.selected_topic_key != self._config.selected_topic_key:
            self._config = replace(self._config, selected_topic_key=view.selected_topic_key)
        self._last_view = view
        return view

    def _effective_subscription_states(self) -> Tuple[TopicSubscriptionState, ...]:
        states = {state.request.key: state for state in self._subscription_states}
        states.update(self._subscription_overrides)
        return tuple(states[key] for key in sorted(states))

    def _topic_identity(
            self,
            payload: Mapping[str, Any],
            allow_existing_state: bool = False,
    ) -> Tuple[int, str, str]:
        domain_id = int(payload.get("domain_id", self._config.domain_id))
        topic_name = str(payload.get("topic_name", ""))
        type_name = str(payload.get("type_name", ""))
        topic_key = str(payload.get("topic_key", ""))
        if not topic_name and topic_key:
            domain_id, topic_name = _parse_topic_key(topic_key)
        if (not topic_name or not type_name) and self._last_view.selected_topic is not None:
            row = self._last_view.selected_topic
            domain_id = row.domain_id
            topic_name = topic_name or row.topic_name
            type_name = type_name or row.type_name
        if (not type_name or allow_existing_state) and topic_name:
            existing = self._state_for_topic(domain_id, topic_name, type_name)
            if existing is not None:
                type_name = existing.request.type_name
        if not topic_name:
            raise ValueError("Topics command requires topic_name or topic_key")
        if not type_name:
            raise ValueError("Topics command requires type_name")
        return domain_id, topic_name, type_name

    def _state_for_topic(
            self,
            domain_id: int,
            topic_name: str,
            type_name: str = "",
    ) -> Optional[TopicSubscriptionState]:
        for state in reversed(self._effective_subscription_states()):
            request = state.request
            if request.domain_id != int(domain_id) or request.topic_name != topic_name:
                continue
            if type_name and request.type_name != type_name:
                continue
            return state
        return None

    def _selection_for(self, domain_id: int, topic_name: str, type_name: str) -> TopicSelection:
        selections = self._current_selections()
        return selections.selected_for(domain_id, topic_name) or TopicSelection(domain_id, topic_name, type_name)

    def _selected_fields_for(self, domain_id: int, topic_name: str) -> Tuple[str, ...]:
        selection = self._current_selections().selected_for(domain_id, topic_name)
        return selection.selected_fields if selection is not None else ()

    def _current_selections(self) -> TopicSelectionState:
        if self._discovery_facade is not None:
            return self._discovery_facade.selections
        return self._selection_state

    def _upsert_selection(
            self,
            topic: Tuple[int, str, str],
            selected_fields: Optional[Iterable[str]] = None,
            plot_fields: Optional[Iterable[str]] = None,
    ) -> TopicSelection:
        current = self._selection_for(topic[0], topic[1], topic[2])
        selection = TopicSelection(
            domain_id=topic[0],
            topic_name=topic[1],
            type_name=topic[2],
            selected_fields=tuple(current.selected_fields if selected_fields is None else selected_fields),
            plot_fields=tuple(current.plot_fields if plot_fields is None else plot_fields),
            enabled=current.enabled,
            created_at=current.created_at,
            updated_at=self._clock(),
        )
        if self._discovery_facade is not None:
            self._discovery_facade.select_topic(
                selection.domain_id,
                selection.topic_name,
                selection.type_name,
                selected_fields=selection.selected_fields,
                plot_fields=selection.plot_fields,
            )
        else:
            self._selection_state = self._selection_state.select(selection)
        return selection


def topics_inputs_from_data_session_snapshot(
        snapshot: DataSessionSnapshot,
) -> Tuple[Tuple[TopicSubscriptionState, ...], Tuple[SampleEnvelope, ...]]:
    """Extract Topics-tab subscription and sample inputs from a data-session snapshot."""

    samples = []
    for key in sorted(snapshot.samples):
        samples.extend(snapshot.samples[key])
    return tuple(snapshot.subscriptions), tuple(samples)


def _command_result(
        command: AppCommand,
        message: str,
        payload: Optional[Mapping[str, Any]] = None,
) -> CommandResult:
    return CommandResult(
        command_id=command.command_id,
        status=CommandStatus.ACKNOWLEDGED,
        message=message,
        payload=payload or {},
        created_at=command.created_at,
    )


def _parse_topic_key(topic_key: str) -> Tuple[int, str]:
    domain_text, separator, topic_name = str(topic_key).partition(":")
    if not separator:
        raise ValueError(f"Invalid topic key: {topic_key}")
    return int(domain_text), topic_name


def _tuple_payload(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value)


def _updated_tuple(values: Iterable[str], field_path: str, selected: Optional[bool]) -> Tuple[str, ...]:
    field_path = str(field_path)
    if not field_path:
        raise ValueError("Topics field command requires field_path")
    items = list(values)
    if selected is None:
        selected = field_path not in items
    if selected and field_path not in items:
        items.append(field_path)
    if not selected:
        items = [item for item in items if item != field_path]
    return tuple(items)
