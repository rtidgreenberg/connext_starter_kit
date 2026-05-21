"""Headless runtime lifecycle and queue management for rs_gui_v2."""

import asyncio
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Awaitable, Dict, List, Optional

from .events import AppCommand, AppEvent, LifecyclePhase
from .state import AppState


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration for the headless app runtime."""

    command_queue_max_size: int = 100
    event_queue_max_size: int = 500


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

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def lifecycle(self) -> LifecyclePhase:
        return self._state.lifecycle

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
            return True
        except Full:
            return False

    def drain_commands(self, limit: Optional[int] = None) -> List[AppCommand]:
        return self._drain_queue(self._command_queue, limit)

    def publish_event(self, event: AppEvent) -> bool:
        try:
            self._event_queue.put_nowait(event)
            return True
        except Full:
            return False

    def drain_events(self, limit: Optional[int] = None) -> List[AppEvent]:
        return self._drain_queue(self._event_queue, limit)

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

    @staticmethod
    def _drain_queue(queue: Queue, limit: Optional[int]) -> List[object]:
        drained = []
        while limit is None or len(drained) < limit:
            try:
                drained.append(queue.get_nowait())
            except Empty:
                break
        return drained