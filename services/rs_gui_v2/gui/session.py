"""Runtime-backed GUI shell session for rs_gui_v2."""

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Tuple

from app_core import AppCommand, AppEvent, AppRuntime

from .scheduler import UiFrameScheduler
from .tabs import PlotsTabController, RecordTabController, TopicsTabController
from .view_models import ShellViewModel
from .workspace import GuiWorkspaceController


@dataclass(frozen=True)
class GuiShellSessionConfig:
    """Presentation and queue-processing options for one GUI shell session."""

    workspace_name: str = "Workspace"
    unsaved: bool = False
    command_drain_limit: Optional[int] = 20
    local_hostnames: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hostnames", tuple(str(name) for name in self.local_hostnames))
        if self.command_drain_limit is not None:
            object.__setattr__(self, "command_drain_limit", int(self.command_drain_limit))


class GuiShellSession:
    """Connect app-core queues, Record-tab controller snapshots, and shell views."""

    def __init__(
            self,
            runtime: AppRuntime,
            scheduler: UiFrameScheduler,
            record_controller: RecordTabController,
            topics_controller: Optional[TopicsTabController] = None,
            plots_controller: Optional[PlotsTabController] = None,
            workspace_controller: Optional[GuiWorkspaceController] = None,
            config: Optional[GuiShellSessionConfig] = None,
    ) -> None:
        self._runtime = runtime
        self._scheduler = scheduler
        self._record_controller = record_controller
        self._topics_controller = topics_controller
        self._plots_controller = plots_controller
        self._config = config or GuiShellSessionConfig()
        self._workspace_controller = workspace_controller or GuiWorkspaceController(
            topics_controller=topics_controller,
            plots_controller=plots_controller,
        )

    @property
    def runtime(self) -> AppRuntime:
        return self._runtime

    @property
    def record_controller(self) -> RecordTabController:
        return self._record_controller

    @property
    def topics_controller(self) -> Optional[TopicsTabController]:
        return self._topics_controller

    @property
    def plots_controller(self) -> Optional[PlotsTabController]:
        return self._plots_controller

    @property
    def workspace_controller(self) -> GuiWorkspaceController:
        return self._workspace_controller

    def command_sink(self, command: AppCommand) -> bool:
        """Queue a GUI command intent for app-core processing."""

        accepted = self._runtime.enqueue_command(command)
        event_type = "gui.command_queued" if accepted else "gui.command_dropped"
        level = "info" if accepted else "error"
        message = f"Queued {command.command_type}" if accepted else f"Dropped {command.command_type}"
        self._runtime.publish_event(AppEvent(
            event_type=event_type,
            source="gui",
            payload={
                "command_id": command.command_id,
                "command_type": command.command_type,
                "level": level,
                "message": message,
            },
            created_at=command.created_at,
        ))
        return accepted

    def next_view(self) -> ShellViewModel:
        """Synchronously build the next GUI view when no event loop is running."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.next_view_async())
        raise RuntimeError("Use next_view_async() when an asyncio event loop is already running")

    async def next_view_async(self, process_commands: bool = True) -> ShellViewModel:
        """Process queued commands, refresh Record state, and build a shell view."""

        if process_commands:
            await self.process_pending_commands(limit=self._config.command_drain_limit)
        record_view = await self._record_controller.refresh_view()
        topics_view = None
        if self._topics_controller is not None:
            topics_view = await self._topics_controller.refresh_view()
        plots_view = None
        if self._plots_controller is not None:
            plots_view = await self._plots_controller.refresh_view()
        return self._scheduler.next_view(
            record_tab=record_view,
            topics_tab=topics_view,
            plots_tab=plots_view,
            workspace_name=self._config.workspace_name,
            unsaved=self._config.unsaved,
        )

    async def process_pending_commands(self, limit: Optional[int] = None) -> Tuple[Any, ...]:
        """Dispatch queued GUI commands through the app-core controller layer."""

        results = []
        for command in self._runtime.drain_commands(limit=limit):
            try:
                result = await self.dispatch_command(command)
                self._runtime.publish_event(AppEvent(
                    event_type="gui.command_dispatched",
                    source="gui",
                    payload={
                        "command_id": command.command_id,
                        "command_type": command.command_type,
                        "level": "info",
                        "message": f"Dispatched {command.command_type}",
                    },
                    created_at=command.created_at,
                ))
                results.append(result)
            except Exception as exc:
                self._runtime.publish_event(AppEvent(
                    event_type="gui.command_failed",
                    source="gui",
                    payload={
                        "command_id": command.command_id,
                        "command_type": command.command_type,
                        "level": "error",
                        "message": str(exc),
                    },
                    created_at=command.created_at,
                ))
                results.append(exc)
        return tuple(results)

    async def dispatch_command(self, command: AppCommand):
        """Translate one queued app command into the matching GUI controller action."""

        if command.command_type.startswith("topics."):
            if self._topics_controller is None:
                raise ValueError(f"Unsupported GUI command type: {command.command_type}")
            return self._topics_controller.handle_command(command)
        if command.command_type.startswith("workspace."):
            result = self._workspace_controller.handle_command(
                command,
                workspace_name=self._config.workspace_name,
            )
            if command.command_type == "workspace.load" and result.ok:
                name = str(result.payload.get("workspace_name", ""))
                if name:
                    self._config = replace(self._config, workspace_name=name, unsaved=False)
            elif command.command_type == "workspace.save" and result.ok:
                self._config = replace(self._config, unsaved=False)
            return result

        action_id = _record_action_for_command(command.command_type)
        payload = dict(command.payload)
        candidate_id = str(payload.get("candidate_id", ""))
        if candidate_id:
            self._record_controller.select_candidate(candidate_id)
        if action_id == "tag":
            tag_name = str(payload.get("tag_name", ""))
            self._record_controller.set_tag_value(tag_name)
            return await self._record_controller.execute_action(
                action_id,
                tag_name=tag_name,
                description=str(payload.get("description", "")),
                timeout_sec=command.timeout_sec,
            )
        return await self._record_controller.execute_action(
            action_id,
            timeout_sec=command.timeout_sec,
        )


def _record_action_for_command(command_type: str) -> str:
    mapping = {
        "service.pause": "pause",
        "service.resume": "resume",
        "service.tag": "tag",
        "service.shutdown": "shutdown",
        "service.terminate_local_process": "terminate_local",
    }
    try:
        return mapping[command_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported GUI command type: {command_type}") from exc
