"""Headless runtime lifecycle and queue management for rs_gui."""

import asyncio
from dataclasses import dataclass
import json
import os
from queue import Empty, Full, Queue
import time
from typing import Awaitable, Dict, Iterable, List, Optional

from .events import AppCommand, AppEvent, LifecyclePhase
from .state import AppState, OperatorDiagnostic, RuntimeCounters


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration for the headless app runtime."""

    command_queue_max_size: int = 100
    event_queue_max_size: int = 500
    app_log_dir: str = ""


@dataclass(frozen=True)
class _ManagedTask:
    name: str
    task: asyncio.Task
    fatal: bool


class AppRuntime:
    """Owns app-core lifecycle, queues, and async task shutdown."""

    def __init__(self, config: Optional[RuntimeConfig] = None) -> None:
        self.config = config or RuntimeConfig()
        self._command_queue = Queue(maxsize=self.config.command_queue_max_size)
        self._event_queue = Queue(maxsize=self.config.event_queue_max_size)
        self._state = AppState()
        self._tasks: Dict[str, _ManagedTask] = {}
        self._event_log_writer = _EventLogWriter(self.config.app_log_dir) if self.config.app_log_dir else None

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def lifecycle(self) -> LifecyclePhase:
        return self._state.lifecycle

    @property
    def counters(self) -> RuntimeCounters:
        return self._state.runtime_counters

    @property
    def event_log_path(self) -> str:
        if self._event_log_writer is None:
            return ""
        return self._event_log_writer.path

    @property
    def task_names(self) -> List[str]:
        return sorted(self._tasks.keys())

    def start(self) -> None:
        """Start the headless runtime without creating DDS or UI entities."""
        if self.lifecycle == LifecyclePhase.RUNNING:
            return
        if self.lifecycle == LifecyclePhase.STOPPING:
            raise RuntimeError("Cannot start while runtime is stopping")
        previous = self.lifecycle
        self._set_lifecycle(LifecyclePhase.STARTING)
        self.publish_event(AppEvent.lifecycle_changed(previous, LifecyclePhase.STARTING))
        self._set_lifecycle(LifecyclePhase.RUNNING)
        self.publish_event(AppEvent.lifecycle_changed(LifecyclePhase.STARTING,
                                                      LifecyclePhase.RUNNING))

    async def shutdown(self) -> None:
        """Cancel managed tasks and transition to STOPPED."""
        if self.lifecycle == LifecyclePhase.STOPPED:
            return
        previous = self.lifecycle
        self._set_lifecycle(LifecyclePhase.STOPPING)
        self.publish_event(AppEvent.lifecycle_changed(previous, LifecyclePhase.STOPPING))

        managed_tasks = list(self._tasks.values())
        for managed_task in managed_tasks:
            if not managed_task.task.done():
                managed_task.task.cancel()
        if managed_tasks:
            await asyncio.gather(
                *(managed_task.task for managed_task in managed_tasks),
                return_exceptions=True,
            )
        self._tasks.clear()

        self._set_lifecycle(LifecyclePhase.STOPPED)
        self.publish_event(AppEvent.lifecycle_changed(LifecyclePhase.STOPPING,
                                                      LifecyclePhase.STOPPED))

    def enqueue_command(self, command: AppCommand) -> bool:
        try:
            self._command_queue.put_nowait(command)
            self._increment_counters(commands_enqueued=1)
            return True
        except Full:
            self._increment_counters(commands_dropped=1)
            return False

    def drain_commands(self, limit: Optional[int] = None) -> List[AppCommand]:
        commands = self._drain_queue(self._command_queue, limit)
        if commands:
            self._increment_counters(commands_drained=len(commands))
        return commands

    def publish_event(self, event: AppEvent) -> bool:
        if self._event_log_writer is not None:
            self._event_log_writer.write(event)
        try:
            self._event_queue.put_nowait(event)
            self._increment_counters(events_published=1)
            return True
        except Full:
            self._increment_counters(events_dropped=1)
            return False

    def drain_events(self, limit: Optional[int] = None) -> List[AppEvent]:
        events = self._drain_queue(self._event_queue, limit)
        if events:
            self._increment_counters(events_drained=len(events))
        return events

    def record_ui_frame(self, event_count: int = 0, dropped_log_entries: int = 0) -> None:
        self._increment_counters(
            ui_frames_built=1,
            ui_events_ingested=max(0, int(event_count)),
            ui_event_log_dropped=max(0, int(dropped_log_entries)),
        )

    def record_samples(self, received: int = 0, dropped: int = 0) -> None:
        self._increment_counters(
            samples_received=max(0, int(received)),
            samples_dropped=max(0, int(dropped)),
        )

    def record_data_session_update(self, update) -> None:
        self.record_samples(
            received=getattr(update, "sample_count", 0),
            dropped=getattr(update, "dropped_sample_count", 0),
        )

    def set_operator_diagnostics(self, diagnostics: Iterable[OperatorDiagnostic]) -> None:
        self._state = self._state.with_operator_diagnostics(tuple(diagnostics))

    def spawn_task(
            self, name: str, awaitable: Awaitable[object], fatal: bool = True
    ) -> asyncio.Task:
        """Create a named asyncio task owned by this runtime."""
        if self.lifecycle != LifecyclePhase.RUNNING:
            self._close_unowned_awaitable(awaitable)
            raise RuntimeError("Runtime must be running before spawning tasks")
        if name in self._tasks:
            self._close_unowned_awaitable(awaitable)
            raise ValueError(f"Task already exists: {name}")

        task = asyncio.create_task(awaitable, name=name)
        self._tasks[name] = _ManagedTask(name=name, task=task, fatal=fatal)
        task.add_done_callback(lambda completed_task: self._handle_task_done(name, completed_task))
        return task

    def _handle_task_done(self, name: str, task: asyncio.Task) -> None:
        managed_task = self._tasks.pop(name, None)
        fatal = managed_task.fatal if managed_task else True
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:
            self.publish_event(AppEvent(
                event_type="runtime.task_failed",
                payload={"task": name, "fatal": fatal, "error": str(exc)},
            ))
            if fatal:
                self._set_lifecycle(LifecyclePhase.FAILED)
                self._state = self._state.with_error(str(exc))

    @staticmethod
    def _close_unowned_awaitable(awaitable: Awaitable[object]) -> None:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()

    def _set_lifecycle(self, lifecycle: LifecyclePhase) -> None:
        self._state = self._state.with_lifecycle(lifecycle)

    def _increment_counters(self, **deltas: int) -> None:
        self._state = self._state.increment_counters(**deltas)

    @staticmethod
    def _drain_queue(queue: Queue, limit: Optional[int]) -> List[object]:
        drained = []
        while limit is None or len(drained) < limit:
            try:
                drained.append(queue.get_nowait())
            except Empty:
                break
        return drained


class _EventLogWriter:
    def __init__(self, log_dir: str) -> None:
        self._log_dir = _workspace_relative_path(str(log_dir))
        self.path = os.path.join(
            self._log_dir,
            f"rs_gui_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.jsonl",
        )
        os.environ["RS_GUI_EVENT_LOG_PATH"] = self.path

    def write(self, event: AppEvent) -> None:
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(event.to_dict(), default=str, sort_keys=True) + "\n")
        except OSError:
            pass


def _workspace_relative_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    root = os.path.abspath(os.path.dirname(__file__))
    for _ in range(3):
        root = os.path.dirname(root)
    return os.path.join(root, path)