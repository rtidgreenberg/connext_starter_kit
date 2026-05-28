"""Replay tab controller for fake-first GUI command routing."""

from dataclasses import dataclass, replace
import time
from typing import Iterable, Mapping, Tuple

from app_core import AppCommand, CommandResult, CommandStatus

from .replay_tab import (
    ReplayTabViewModel,
    ReplayTargetRow,
    ReplayTimelineRow,
    build_mock_replay_tab_view_model,
    build_replay_tab_view_model,
)


@dataclass(frozen=True)
class ReplayTabControllerConfig:
    """Runtime wiring options for the Replay tab controller."""

    selected_target_id: str = ""
    database_path: str = ""
    playback_rate: float = 1.0
    loop: bool = False
    time_window: str = ""
    qos_file_path: str = ""
    participant_qos_profile: str = ""
    writer_qos_profile: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_target_id", str(self.selected_target_id))
        object.__setattr__(self, "database_path", str(self.database_path))
        object.__setattr__(self, "playback_rate", float(self.playback_rate))
        object.__setattr__(self, "loop", bool(self.loop))
        object.__setattr__(self, "time_window", str(self.time_window))
        object.__setattr__(self, "qos_file_path", str(self.qos_file_path))
        object.__setattr__(self, "participant_qos_profile", str(self.participant_qos_profile))
        object.__setattr__(self, "writer_qos_profile", str(self.writer_qos_profile))


class ReplayTabController:
    """Build Replay tab snapshots and apply queued fake-first Replay commands."""

    def __init__(
            self,
            targets: Iterable[ReplayTargetRow] = (),
            timeline: Iterable[ReplayTimelineRow] = (),
            diagnostics: Iterable[str] = (),
            config: ReplayTabControllerConfig = None,
            clock=time.time,
    ) -> None:
        self._targets = tuple(targets)
        self._timeline = tuple(timeline)
        self._diagnostics = tuple(str(item) for item in diagnostics)
        self._config = config or ReplayTabControllerConfig()
        self._clock = clock
        self._last_view = ReplayTabViewModel()

    @classmethod
    def mock(cls, clock=time.time) -> "ReplayTabController":
        """Create a controller seeded with the deterministic mock Replay view."""

        view = build_mock_replay_tab_view_model()
        return cls(
            targets=view.targets,
            timeline=view.timeline,
            config=ReplayTabControllerConfig(
                selected_target_id=view.selected_target_id,
                database_path=view.database_path,
                playback_rate=view.playback_rate,
                loop=view.loop,
                time_window=view.time_window,
                qos_file_path=view.qos_file_path,
                participant_qos_profile=view.participant_qos_profile,
                writer_qos_profile=view.writer_qos_profile,
            ),
            clock=clock,
        )

    @property
    def selected_target_id(self) -> str:
        return self._config.selected_target_id

    @property
    def last_view(self) -> ReplayTabViewModel:
        return self._last_view

    def select_target(self, target_id: str) -> ReplayTargetRow:
        """Select a Replay Service candidate by target id."""

        target = self._target_by_id(str(target_id))
        self._config = replace(self._config, selected_target_id=target.target_id)
        return target

    def handle_command(self, command: AppCommand) -> CommandResult:
        """Apply a queued Replay command to the controller state."""

        payload = dict(command.payload)
        if command.command_type == "replay.select_target":
            target_id = str(payload.get("target_id") or command.target)
            target = self.select_target(target_id)
            return _command_result(command, f"Selected Replay target {target.control_name}", target)
        if command.command_type == "replay.start":
            target = self._apply_action_payload(payload)
            self._set_target_state(target.target_id, "RUNNING", progress="running")
            return _command_result(
                command,
                f"Started replay {target.control_name}",
                self._target_by_id(target.target_id),
            )
        if command.command_type == "replay.pause":
            target = self._selected_target()
            self._set_target_state(target.target_id, "PAUSED")
            return _command_result(
                command,
                f"Paused replay {target.control_name}",
                self._target_by_id(target.target_id),
            )
        if command.command_type == "replay.resume":
            target = self._selected_target()
            self._set_target_state(target.target_id, "RUNNING", progress="running")
            return _command_result(
                command,
                f"Resumed replay {target.control_name}",
                self._target_by_id(target.target_id),
            )
        if command.command_type == "replay.stop":
            target = self._selected_target()
            self._set_target_state(target.target_id, "STOPPED", progress="0%")
            return _command_result(
                command,
                f"Stopped replay {target.control_name}",
                self._target_by_id(target.target_id),
            )
        if command.command_type == "replay.shutdown":
            target = self._selected_target()
            self._set_target_state(target.target_id, "SHUTDOWN", progress="")
            return _command_result(
                command,
                f"Shutdown replay {target.control_name}",
                self._target_by_id(target.target_id),
            )
        raise ValueError(f"Unsupported Replay command type: {command.command_type}")

    async def refresh_view(self) -> ReplayTabViewModel:
        """Return the next Replay-tab view from controller state."""

        view = build_replay_tab_view_model(
            targets=self._targets,
            selected_target_id=self._config.selected_target_id,
            database_path=self._config.database_path,
            playback_rate=self._config.playback_rate,
            loop=self._config.loop,
            time_window=self._config.time_window,
            qos_file_path=self._config.qos_file_path,
            participant_qos_profile=self._config.participant_qos_profile,
            writer_qos_profile=self._config.writer_qos_profile,
            timeline=self._timeline,
            diagnostics=self._diagnostics,
        )
        if view.selected_target_id != self._config.selected_target_id:
            self._config = replace(self._config, selected_target_id=view.selected_target_id)
        self._last_view = view
        return view

    def _apply_action_payload(self, payload: Mapping[str, object]) -> ReplayTargetRow:
        target_id = str(payload.get("target_id") or self._config.selected_target_id)
        if target_id:
            self.select_target(target_id)
        database_path = str(payload.get("database_path") or self._config.database_path)
        if not database_path.strip():
            raise ValueError("replay.start requires a recording database path")
        playback_rate = float(payload.get("playback_rate", self._config.playback_rate))
        loop = bool(payload.get("loop", self._config.loop))
        time_window = str(payload.get("time_window") or self._config.time_window)
        qos_file_path = str(payload.get("qos_file_path") or self._config.qos_file_path)
        participant_qos_profile = str(
            payload.get("participant_qos_profile") or self._config.participant_qos_profile
        )
        writer_qos_profile = str(payload.get("writer_qos_profile") or self._config.writer_qos_profile)
        self._config = replace(
            self._config,
            database_path=database_path,
            playback_rate=playback_rate,
            loop=loop,
            time_window=time_window,
            qos_file_path=qos_file_path,
            participant_qos_profile=participant_qos_profile,
            writer_qos_profile=writer_qos_profile,
        )
        return self._selected_target()

    def _selected_target(self) -> ReplayTargetRow:
        target_id = self._config.selected_target_id
        if not target_id and self._targets:
            target_id = self._targets[0].target_id
            self._config = replace(self._config, selected_target_id=target_id)
        return self._target_by_id(target_id)

    def _target_by_id(self, target_id: str) -> ReplayTargetRow:
        for target in self._targets:
            if target.target_id == target_id or target.control_name == target_id:
                return target
        raise ValueError(f"Unknown Replay target: {target_id}")

    def _set_target_state(self, target_id: str, state: str, progress: str = None) -> None:
        updated = []
        for target in self._targets:
            if target.target_id == target_id:
                updated.append(replace(
                    target,
                    state=str(state),
                    progress=target.progress if progress is None else str(progress),
                ))
            else:
                updated.append(target)
        self._targets = tuple(updated)


def _command_result(
        command: AppCommand,
        message: str,
        target: ReplayTargetRow,
) -> CommandResult:
    return CommandResult(
        command_id=command.command_id,
        status=CommandStatus.ACKNOWLEDGED,
        message=message,
        payload={
            "target_id": target.target_id,
            "control_name": target.control_name,
            "state": target.state,
            "progress": target.progress,
        },
        created_at=command.created_at,
    )
