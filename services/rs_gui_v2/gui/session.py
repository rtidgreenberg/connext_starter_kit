"""Runtime-backed GUI shell session for rs_gui_v2."""

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Tuple

from app_core import AppCommand, AppEvent, AppRuntime
from app_core.debug_log import dbg, dbg_exc
from app_core.services import ServiceProcessLaunch, ServiceProcessLaunchState

from .scheduler import UiFrameScheduler
from .tabs import (
    ConvertTabController,
    PlotsTabController,
    RecordTabController,
    ReplayTabController,
    TopicsTabController,
)
from .view_models import ShellViewModel
from .workspace import GuiWorkspaceController


@dataclass(frozen=True)
class GuiShellSessionConfig:
    """Presentation and queue-processing options for one GUI shell session."""

    workspace_name: str = "Workspace"
    unsaved: bool = False
    command_drain_limit: Optional[int] = 20
    local_hostnames: Tuple[str, ...] = field(default_factory=tuple)
    close_shutdown_exit_timeout_sec: float = 3.0
    close_shutdown_poll_sec: float = 0.1

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hostnames", tuple(str(name) for name in self.local_hostnames))
        if self.command_drain_limit is not None:
            object.__setattr__(self, "command_drain_limit", int(self.command_drain_limit))
        object.__setattr__(self, "close_shutdown_exit_timeout_sec", max(0.0, float(self.close_shutdown_exit_timeout_sec)))
        object.__setattr__(self, "close_shutdown_poll_sec", max(0.01, float(self.close_shutdown_poll_sec)))


class GuiShellSession:
    """Connect app-core queues, Record-tab controller snapshots, and shell views."""

    def __init__(
            self,
            runtime: AppRuntime,
            scheduler: UiFrameScheduler,
            record_controller: RecordTabController,
            convert_controller: Optional[ConvertTabController] = None,
            replay_controller: Optional[ReplayTabController] = None,
            topics_controller: Optional[TopicsTabController] = None,
            plots_controller: Optional[PlotsTabController] = None,
            workspace_controller: Optional[GuiWorkspaceController] = None,
            config: Optional[GuiShellSessionConfig] = None,
    ) -> None:
        self._runtime = runtime
        self._scheduler = scheduler
        self._record_controller = record_controller
        self._convert_controller = convert_controller
        self._replay_controller = replay_controller
        self._topics_controller = topics_controller
        self._plots_controller = plots_controller
        self._config = config or GuiShellSessionConfig()
        self._workspace_controller = workspace_controller or GuiWorkspaceController(
            topics_controller=topics_controller,
            plots_controller=plots_controller,
            convert_controller=convert_controller,
        )
        self._record_process_states = {}
        self._replay_process_states = {}

    @property
    def runtime(self) -> AppRuntime:
        return self._runtime

    @property
    def config(self) -> GuiShellSessionConfig:
        return self._config

    @property
    def record_controller(self) -> RecordTabController:
        return self._record_controller

    @property
    def convert_controller(self) -> Optional[ConvertTabController]:
        return self._convert_controller

    @property
    def replay_controller(self) -> Optional[ReplayTabController]:
        return self._replay_controller

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
                "command": command.to_dict(),
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
        dbg("session", "refresh_view start")
        record_view = await self._record_controller.refresh_view()
        dbg("session", "refresh_view done",
            candidates=len(record_view.candidates),
            state=record_view.observed_state)
        self._publish_record_process_state_events()
        self._publish_record_monitoring_events()
        convert_view = None
        if self._convert_controller is not None:
            convert_view = await self._convert_controller.refresh_view()
        replay_view = None
        if self._replay_controller is not None:
            replay_view = await self._replay_controller.refresh_view()
            self._publish_replay_monitoring_events()
            self._publish_replay_process_state_events()
        topics_view = None
        if self._topics_controller is not None:
            topics_view = await self._topics_controller.refresh_view()
        plots_view = None
        if self._plots_controller is not None:
            plots_view = await self._plots_controller.refresh_view()
        return self._scheduler.next_view(
            record_tab=record_view,
            convert_tab=convert_view,
            replay_tab=replay_view,
            topics_tab=topics_view,
            plots_tab=plots_view,
            workspace_name=self._config.workspace_name,
            workspace_path=self._workspace_controller.current_path,
            unsaved=self._config.unsaved,
        )

    async def process_pending_commands(self, limit: Optional[int] = None) -> Tuple[Any, ...]:
        """Dispatch queued GUI commands through the app-core controller layer."""

        results = []
        for command in self._runtime.drain_commands(limit=limit):
            try:
                result = await self.dispatch_command(command)
                result_payload = _console_payload(result)
                self._runtime.publish_event(AppEvent(
                    event_type="gui.command_dispatched",
                    source="gui",
                    payload={
                        "command_id": command.command_id,
                        "command_type": command.command_type,
                        "command": command.to_dict(),
                        "result": result_payload,
                        "level": "info",
                        "message": f"Dispatched {command.command_type}",
                    },
                    created_at=command.created_at,
                ))
                if isinstance(result, ServiceProcessLaunch) and result.state == ServiceProcessLaunchState.START_FAILED:
                    self._runtime.publish_event(AppEvent(
                        event_type="gui.command_failed",
                        source="gui",
                        payload={
                            "command_id": command.command_id,
                            "command_type": command.command_type,
                            "command": command.to_dict(),
                            "result": result.to_dict(),
                            "level": "error",
                            "message": result.message or "Recording Service launch failed",
                        },
                        created_at=command.created_at,
                    ))
                elif _result_failed(result):
                    self._runtime.publish_event(AppEvent(
                        event_type="gui.command_failed",
                        source="gui",
                        payload={
                            "command_id": command.command_id,
                            "command_type": command.command_type,
                            "command": command.to_dict(),
                            "result": result_payload,
                            "level": "error",
                            "message": _result_message(result) or f"{command.command_type} failed",
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
                        "command": command.to_dict(),
                        "exception_type": type(exc).__name__,
                        "level": "error",
                        "message": str(exc),
                    },
                    created_at=command.created_at,
                ))
                results.append(exc)
        return tuple(results)

    async def dispatch_command(self, command: AppCommand):
        """Translate one queued app command into the matching GUI controller action."""

        if command.command_type.startswith("convert."):
            if self._convert_controller is None:
                raise ValueError(f"Unsupported GUI command type: {command.command_type}")
            return await self._convert_controller.handle_command(command)
        if command.command_type.startswith("topics."):
            if self._topics_controller is None:
                raise ValueError(f"Unsupported GUI command type: {command.command_type}")
            return await self._topics_controller.handle_command(command)
        if command.command_type.startswith("replay."):
            if self._replay_controller is None:
                raise ValueError(f"Unsupported GUI command type: {command.command_type}")
            return await self._replay_controller.handle_command(command)
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

        if command.command_type == "service.launch_recording":
            return self._record_controller.launch_recording(command.payload)
        if command.command_type == "service.launch_replay":
            if self._replay_controller is None:
                raise ValueError(f"Unsupported GUI command type: {command.command_type}")
            return self._replay_controller.launch_replay(command.payload)

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

    def handle_close_request(self, action: str, item_ids: Tuple[str, ...] = ()) -> bool:
        """Apply the operator's app-close process policy before the GUI exits."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.handle_close_request_async(action, item_ids))
            return True
        raise RuntimeError("Use handle_close_request_async() when an asyncio event loop is already running")

    async def handle_close_request_async(self, action: str, item_ids: Tuple[str, ...] = ()) -> None:
        """Leave services running or clean up selected GUI-owned processes."""

        normalized_action = str(action).strip()
        selected = tuple(str(item_id) for item_id in item_ids)
        self._runtime.publish_event(AppEvent(
            event_type="gui.close_requested",
            source="gui",
            payload={
                "action": normalized_action,
                "item_ids": list(selected),
                "level": "info",
                "message": f"Close requested: {normalized_action}",
            },
        ))
        cleanup_results = ()
        if normalized_action == "shutdown_gui_launched":
            print("[INFO] SHUTDOWN_START: Shutting down GUI-spawned local processes", flush=True)
            cleanup_results = await self._shutdown_gui_launched_items(selected)
        elif normalized_action != "leave_running":
            raise ValueError(f"Unsupported close action: {action}")

        self._runtime.publish_event(AppEvent(
            event_type="gui.close_completed",
            source="gui",
            payload={
                "action": normalized_action,
                "item_ids": list(selected),
                "cleanup_results": list(cleanup_results),
                "level": "info",
                "message": f"Close completed: {normalized_action}",
            },
        ))
        _print_shutdown_summary(normalized_action, cleanup_results)
        await self._runtime.shutdown()

    async def _shutdown_gui_launched_items(self, item_ids: Tuple[str, ...]) -> Tuple[Any, ...]:
        cleanup_results = []
        record_ids = tuple(item_id.split(":", 1)[1] for item_id in item_ids if item_id.startswith("record:"))
        for candidate_id in record_ids:
            self._record_controller.select_candidate(candidate_id)
            outcome = await self._record_controller.execute_action("shutdown", timeout_sec=3.0)
            cleanup_result = {
                "kind": "recording",
                "candidate_id": candidate_id,
                "admin_shutdown": _console_payload(outcome),
                "admin_shutdown_ok": bool(getattr(outcome, "ok", False)),
                "process_exit_observed": False,
                "local_termination": None,
                "local_kill": None,
            }
            if getattr(outcome, "ok", False):
                exited = await self._wait_for_record_process_exit(candidate_id)
                if exited:
                    cleanup_result["process_exit_observed"] = True
                    cleanup_results.append(cleanup_result)
                    continue
                self._record_controller.mark_graceful_shutdown_failed()
            else:
                self._record_controller.mark_graceful_shutdown_failed()
                termination = await self._record_controller.execute_action("terminate_local", timeout_sec=1.0)
                cleanup_result["local_termination"] = _console_payload(termination)
                if getattr(termination, "ok", False):
                    cleanup_result["process_exit_observed"] = await self._wait_for_record_process_exit(candidate_id)
                    if not cleanup_result["process_exit_observed"]:
                        kill = await self._record_controller.execute_action("kill_local", timeout_sec=1.0)
                        cleanup_result["local_kill"] = _console_payload(kill)
                        if getattr(kill, "ok", False):
                            cleanup_result["process_exit_observed"] = await self._wait_for_record_process_exit(candidate_id)
                cleanup_results.append(cleanup_result)
                continue
            termination = await self._record_controller.execute_action("terminate_local", timeout_sec=1.0)
            cleanup_result["local_termination"] = _console_payload(termination)
            if getattr(termination, "ok", False):
                cleanup_result["process_exit_observed"] = await self._wait_for_record_process_exit(candidate_id)
                if not cleanup_result["process_exit_observed"]:
                    kill = await self._record_controller.execute_action("kill_local", timeout_sec=1.0)
                    cleanup_result["local_kill"] = _console_payload(kill)
                    if getattr(kill, "ok", False):
                        cleanup_result["process_exit_observed"] = await self._wait_for_record_process_exit(candidate_id)
            cleanup_results.append(cleanup_result)

        convert_job_ids = tuple(item_id.split(":", 1)[1] for item_id in item_ids if item_id.startswith("convert:"))
        if convert_job_ids and self._convert_controller is not None:
            cleanup_results.extend(
                await self._convert_controller.terminate_gui_launched_jobs_and_wait(
                    convert_job_ids,
                    timeout_sec=self._config.close_shutdown_exit_timeout_sec,
                    poll_sec=self._config.close_shutdown_poll_sec,
                )
            )
        replay_ids = tuple(item_id.split(":", 1)[1] for item_id in item_ids if item_id.startswith("replay:"))
        if replay_ids and self._replay_controller is not None:
            for candidate_id in replay_ids:
                self._replay_controller.select_target(candidate_id)
                cleanup_result = {
                    "kind": "replay",
                    "candidate_id": candidate_id,
                    "admin_shutdown": None,
                    "admin_shutdown_ok": False,
                    "process_exit_observed": False,
                    "local_termination": None,
                    "local_kill": None,
                }
                try:
                    outcome = await self._replay_controller.execute_action("shutdown", timeout_sec=3.0)
                except Exception as exc:
                    outcome = None
                    cleanup_result["admin_shutdown"] = {
                        "status": "failed",
                        "message": str(exc),
                    }
                if outcome is not None:
                    cleanup_result["admin_shutdown"] = _console_payload(outcome)
                    cleanup_result["admin_shutdown_ok"] = bool(getattr(outcome, "ok", False))
                if cleanup_result["admin_shutdown_ok"]:
                    exited = await self._wait_for_replay_process_exit(candidate_id)
                    if exited:
                        cleanup_result["process_exit_observed"] = True
                        cleanup_results.append(cleanup_result)
                        continue
                    self._replay_controller.mark_graceful_shutdown_failed()
                else:
                    self._replay_controller.mark_graceful_shutdown_failed()
                termination = await self._replay_controller.execute_action("terminate_local", timeout_sec=1.0)
                cleanup_result["local_termination"] = _console_payload(termination)
                if getattr(termination, "ok", False):
                    cleanup_result["process_exit_observed"] = await self._wait_for_replay_process_exit(candidate_id)
                    if not cleanup_result["process_exit_observed"]:
                        kill = await self._replay_controller.execute_action("kill_local", timeout_sec=1.0)
                        cleanup_result["local_kill"] = _console_payload(kill)
                        if getattr(kill, "ok", False):
                            cleanup_result["process_exit_observed"] = await self._wait_for_replay_process_exit(candidate_id)
                cleanup_results.append(cleanup_result)
        return tuple(cleanup_results)

    async def _wait_for_record_process_exit(self, candidate_id: str) -> bool:
        deadline = asyncio.get_running_loop().time() + self._config.close_shutdown_exit_timeout_sec
        while True:
            record_view = await self._record_controller.refresh_view()
            self._publish_record_process_state_events()
            candidate = next(
                (row for row in record_view.candidates if row.candidate_id == candidate_id),
                None,
            )
            if candidate is None:
                return True
            exited_states = {"exited", "start_failed"}
            if not candidate.owned:
                exited_states = exited_states | {"stopped", "shutdown"}
            if str(candidate.state).lower() in exited_states:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self._config.close_shutdown_poll_sec)

    async def _wait_for_replay_process_exit(self, candidate_id: str) -> bool:
        if self._replay_controller is None:
            return True
        deadline = asyncio.get_running_loop().time() + self._config.close_shutdown_exit_timeout_sec
        while True:
            replay_view = await self._replay_controller.refresh_view()
            self._publish_replay_monitoring_events()
            self._publish_replay_process_state_events()
            target = next(
                (row for row in replay_view.targets if row.candidate_id == candidate_id or row.target_id == candidate_id),
                None,
            )
            if target is None or str(target.state).lower() in {"exited", "start_failed", "stopped", "shutdown"}:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self._config.close_shutdown_poll_sec)

    def _publish_record_process_state_events(self) -> None:
        for candidate in self._record_controller.last_selection.candidates:
            key = candidate.launch_id or candidate.candidate_id
            if not key:
                continue
            state = str(candidate.observed_state)
            previous = self._record_process_states.get(key)
            if previous == state:
                continue
            self._record_process_states[key] = state
            is_error_state = state in {"exited", "start_failed"}
            self._runtime.publish_event(AppEvent(
                event_type="service.process_state",
                source="gui",
                payload={
                    "candidate": candidate.to_dict(),
                    "level": "error" if is_error_state else "info",
                    "message": f"Recording Service process observed: {state}",
                },
                created_at=candidate.last_seen_at,
            ))

    def _publish_record_monitoring_events(self) -> None:
        for snapshot in self._record_controller.last_monitoring_updates:
            self._runtime.publish_event(AppEvent(
                event_type="service.monitoring_update",
                source="gui",
                payload={
                    "service": snapshot.service.to_dict(),
                    "kind": snapshot.kind.value,
                    "state": snapshot.state,
                    "metrics": dict(snapshot.metrics),
                    "details": dict(snapshot.details),
                    "level": "info",
                    "message": f"Recording Service monitoring {snapshot.kind.value}: {snapshot.state}",
                },
                created_at=snapshot.observed_at,
            ))

    def _publish_replay_process_state_events(self) -> None:
        if self._replay_controller is None:
            return
        for candidate in self._replay_controller.last_selection.candidates:
            key = candidate.launch_id or candidate.candidate_id
            if not key:
                continue
            state = str(candidate.observed_state)
            previous = self._replay_process_states.get(key)
            if previous == state:
                continue
            self._replay_process_states[key] = state
            is_error_state = state in {"exited", "start_failed"}
            self._runtime.publish_event(AppEvent(
                event_type="service.process_state",
                source="gui",
                payload={
                    "candidate": candidate.to_dict(),
                    "level": "error" if is_error_state else "info",
                    "message": f"Replay Service process observed: {state}",
                },
                created_at=candidate.last_seen_at,
            ))

    def _publish_replay_monitoring_events(self) -> None:
        if self._replay_controller is None:
            return
        for snapshot in self._replay_controller.last_monitoring_updates:
            self._runtime.publish_event(AppEvent(
                event_type="service.monitoring_update",
                source="gui",
                payload={
                    "service": snapshot.service.to_dict(),
                    "kind": snapshot.kind.value,
                    "state": snapshot.state,
                    "metrics": dict(snapshot.metrics),
                    "details": dict(snapshot.details),
                    "level": "info",
                    "message": f"Replay Service monitoring {snapshot.kind.value}: {snapshot.state}",
                },
                created_at=snapshot.observed_at,
            ))


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


def _console_payload(value):
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, BaseException):
        return {"exception_type": type(value).__name__, "message": str(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_console_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _console_payload(item) for key, item in value.items()}
    return str(value)


def _print_shutdown_summary(action: str, cleanup_results: Tuple[Any, ...]) -> None:
    results = tuple(_console_payload(item) for item in cleanup_results)
    if action == "leave_running":
        print("[INFO] SHUTDOWN_SUMMARY: No GUI-spawned local processes were selected for shutdown", flush=True)
        return
    if not results:
        print("[INFO] SHUTDOWN_SUMMARY: No GUI-spawned local processes required shutdown", flush=True)
        return

    for result in results:
        level = "INFO" if bool(result.get("process_exit_observed")) else "WARNING"
        print(f"[{level}] {_shutdown_result_code(result)}: {_shutdown_result_message(result)}", flush=True)

    verified_count = sum(1 for result in results if bool(result.get("process_exit_observed")))
    total_count = len(results)
    if verified_count == total_count:
        print(
            f"[INFO] SHUTDOWN_SUMMARY: All GUI-spawned local processes have exited ({total_count} process(es))",
            flush=True,
        )
    else:
        missing_count = total_count - verified_count
        print(
            f"[WARNING] SHUTDOWN_SUMMARY: {missing_count} GUI-spawned local process(es) "
            "did not confirm exit",
            flush=True,
        )


def _shutdown_result_code(result: Mapping[str, Any]) -> str:
    kind = str(result.get("kind", "process")).lower()
    if kind == "recording":
        return "SHUTDOWN_RECORDING"
    if kind == "replay":
        return "SHUTDOWN_REPLAY"
    if kind == "convert":
        return "SHUTDOWN_CONVERTER"
    return "SHUTDOWN_PROCESS"


def _shutdown_result_message(result: Mapping[str, Any]) -> str:
    kind = str(result.get("kind", "process")).lower()
    observed = bool(result.get("process_exit_observed"))
    state = "exited" if observed else "exit not verified"
    if kind == "recording":
        name = str(result.get("candidate_id", "recording"))
        if bool(result.get("admin_shutdown_ok")) and result.get("local_termination") is None:
            method = "admin shutdown acknowledged"
        elif result.get("local_termination") is not None:
            method = "local termination fallback used"
        else:
            method = "admin shutdown attempted"
        return f"Recording Service {name} {state} ({method})"
    if kind == "convert":
        job_id = str(result.get("job_id", "converter"))
        pid = result.get("process_pid")
        pid_text = f" pid {pid}" if pid else ""
        termination = str(result.get("local_termination", "requested"))
        return f"Converter job {job_id}{pid_text} {state} (local termination {termination})"
    if kind == "replay":
        name = str(result.get("candidate_id", "replay"))
        if result.get("local_termination") is not None:
            method = "local termination fallback used"
        else:
            method = "local termination attempted"
        return f"Replay Service {name} {state} ({method})"
    return f"GUI-spawned process {state}"


def _result_failed(value) -> bool:
    ok = getattr(value, "ok", None)
    if ok is False:
        return True
    status = getattr(value, "status", None)
    status_value = getattr(status, "value", str(status)).lower() if status is not None else ""
    return status_value in {"failed", "not_allowed", "not_found", "already_exited", "start_failed"}


def _result_message(value) -> str:
    return str(getattr(value, "message", ""))
