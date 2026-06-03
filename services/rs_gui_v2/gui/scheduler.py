"""Frame scheduler bridge between app-core queues and the Dear PyGui thread."""

from typing import Callable, Iterable, Tuple

from app_core import AppEvent, AppRuntime, AppState

from .tabs.convert_tab import ConvertTabViewModel
from .tabs.plots_tab import PlotsTabViewModel
from app_core.services import ServiceCandidateSelection

from .tabs.record_tab import RecordTabViewModel, build_record_tab_view_model
from .tabs.replay_tab import ReplayTabViewModel
from .tabs.topics_tab import TopicsTabViewModel
from .view_models import EventLogEntry, ShellViewModel, build_shell_view_model, event_log_entry_from_event


class UiFrameScheduler:
    """Drain app-core events and build immutable GUI snapshots on demand."""

    def __init__(
            self,
            runtime: AppRuntime,
            max_event_log: int = 200,
            event_drain_limit: int = 50,
            view_builder: Callable[..., ShellViewModel] = build_shell_view_model,
    ) -> None:
        self._runtime = runtime
        self._max_event_log = int(max_event_log)
        self._event_drain_limit = int(event_drain_limit)
        self._view_builder = view_builder
        self._event_log: Tuple[EventLogEntry, ...] = ()

    @property
    def event_log(self) -> Tuple[EventLogEntry, ...]:
        return self._event_log

    def next_view(
            self,
            record_tab: RecordTabViewModel = None,
            convert_tab: ConvertTabViewModel = None,
            replay_tab: ReplayTabViewModel = None,
            topics_tab: TopicsTabViewModel = None,
            plots_tab: PlotsTabViewModel = None,
            workspace_name: str = "Workspace",
            workspace_path: str = "",
            unsaved: bool = False,
    ) -> ShellViewModel:
        """Drain pending events and return the next GUI-safe shell snapshot."""

        event_count, dropped_log_entries = self.ingest_events(
            self._runtime.drain_events(limit=self._event_drain_limit)
        )
        self._runtime.record_ui_frame(
            event_count=event_count,
            dropped_log_entries=dropped_log_entries,
        )
        return self._view_builder(
            self._runtime.state,
            record_tab or build_record_tab_view_model(ServiceCandidateSelection()),
            convert_tab=convert_tab,
            replay_tab=replay_tab,
            topics_tab=topics_tab,
            plots_tab=plots_tab,
            event_log=self._event_log,
            workspace_name=workspace_name,
            workspace_path=workspace_path,
            unsaved=unsaved,
        )

    def ingest_events(self, events: Iterable[AppEvent]) -> Tuple[int, int]:
        """Append app-core events to the bounded UI event log."""

        entries = tuple(event_log_entry_from_event(event) for event in events)
        if not entries:
            return 0, 0
        previous_count = len(self._event_log)
        combined = self._event_log + entries
        self._event_log = combined[-self._max_event_log:]
        dropped = max(0, previous_count + len(entries) - len(self._event_log))
        if dropped > 0:
            warning = EventLogEntry(
                timestamp="",
                level="warning",
                source="scheduler",
                message=f"{dropped} event log entries dropped (log capped at {self._max_event_log})",
                event_type="scheduler.log_overflow",
            )
            self._event_log = self._event_log[1:] + (warning,)
        return len(entries), dropped

    @property
    def state(self) -> AppState:
        return self._runtime.state
