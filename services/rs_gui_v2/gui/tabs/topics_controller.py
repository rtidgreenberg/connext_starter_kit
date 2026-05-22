"""Topics tab controller wiring discovery snapshots into GUI views."""

from dataclasses import dataclass, field, replace
import time
from typing import Mapping, Optional, Tuple

from app_core import (
    FieldCatalog,
    SampleEnvelope,
    TopicDiscoveryFacade,
    TopicSelectionState,
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
            config: Optional[TopicsTabControllerConfig] = None,
            clock=time.time,
    ) -> None:
        self._discovery_facade = discovery_facade
        self._field_catalogs = dict(field_catalogs or {})
        self._subscription_states = tuple(subscription_states)
        self._samples = tuple(samples)
        self._config = config or TopicsTabControllerConfig()
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

    def set_field_catalogs(self, catalogs: Mapping[str, FieldCatalog]) -> None:
        self._field_catalogs = dict(catalogs)

    def set_subscription_states(self, states: Tuple[TopicSubscriptionState, ...]) -> None:
        self._subscription_states = tuple(states)

    def set_samples(self, samples: Tuple[SampleEnvelope, ...]) -> None:
        self._samples = tuple(samples)

    async def refresh_view(self) -> TopicsTabViewModel:
        """Scan discovery state and return the next Topics-tab view."""

        topics = ()
        diagnostics = ()
        selections = TopicSelectionState(include_internal=self._config.include_internal)
        if self._discovery_facade is not None:
            selections = self._discovery_facade.selections
            try:
                topics = await self._discovery_facade.scan(
                    self._config.domain_id,
                    include_internal=self._config.include_internal,
                )
            except Exception as exc:
                diagnostics = (f"Discovery scan failed: {exc}",)

        view = build_topics_tab_view_model(
            topics=topics,
            selections=selections,
            field_catalogs=self._field_catalogs,
            subscription_states=self._subscription_states,
            samples=self._samples,
            domain_id=self._config.domain_id,
            search_text=self._config.search_text,
            include_internal=self._config.include_internal,
            selected_topic_key=self._config.selected_topic_key,
            now=self._clock(),
        )
        if diagnostics:
            view = replace(view, diagnostics=diagnostics + view.diagnostics)
        if view.selected_topic_key and view.selected_topic_key != self._config.selected_topic_key:
            self._config = replace(self._config, selected_topic_key=view.selected_topic_key)
        self._last_view = view
        return view
