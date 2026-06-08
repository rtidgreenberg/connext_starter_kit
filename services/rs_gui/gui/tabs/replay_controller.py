"""Replay tab controller for GUI command routing and local service launches."""

from dataclasses import dataclass, field, replace
import os
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from app_core import AppCommand, CommandResult, CommandStatus
from app_core.connext_environment import detect_nddshome, ensure_rti_license
from app_core.services.rti_admin import (
    ACTION_UPDATE,
    ENTITY_STATE_PAUSED,
    ENTITY_STATE_RUNNING,
    ENTITY_STATE_STOPPED,
    replay_service_resource,
    replay_service_state_resource,
)
from app_core.services import (
    AdminReadiness,
    AdminReadinessStatus,
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceAdminFacade,
    ServiceCandidateSelection,
    ServiceCommand,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceMonitoringFacade,
    ServiceProcessCandidate,
    ServiceProcessLaunch,
    ServiceProcessLaunchRequest,
    ServiceProcessManager,
    ServiceProcessTerminationOutcome,
)

from .replay_tab import (
    ReplayLaunchViewModel,
    ReplayTabViewModel,
    ReplayTargetRow,
    ReplayTimelineRow,
    build_mock_replay_tab_view_model,
    build_replay_tab_view_model,
)


def _workspace_launch_path(path: str) -> str:
    normalized = str(path).strip()
    if not normalized or os.path.isabs(normalized):
        return normalized
    root = os.path.abspath(os.path.dirname(__file__))
    for _ in range(4):
        root = os.path.dirname(root)
    return os.path.join(root, normalized)


def _has_replayable_sqlite_files(path: str) -> bool:
    candidate = _workspace_launch_path(path)
    if not candidate or not os.path.isdir(candidate):
        return False
    if not os.path.isfile(os.path.join(candidate, "metadata.db")):
        return False
    return any(
        entry.startswith("data_") and entry.endswith(".db")
        for entry in os.listdir(candidate)
    )


def _compose_verbosity(
        payload: Mapping[str, object],
        fallback: str,
) -> str:
    service_level = str(payload.get("service_verbosity", "")).strip().upper()
    api_level = str(payload.get("api_verbosity", "")).strip().upper()
    if service_level or api_level:
        service = service_level or "ERROR"
        api = api_level or service
        return f"{service}:{api}"
    return str(payload.get("verbosity", fallback)).strip() or "ERROR:ERROR"


@dataclass(frozen=True)
class ReplayTabControllerConfig:
    """Runtime wiring options for the Replay tab controller."""

    service: Optional[ServiceInstanceRef] = None
    display_label: str = "Replay Service"
    local_hostnames: Tuple[str, ...] = field(default_factory=tuple)
    selected_target_id: str = ""
    database_path: str = ""
    playback_rate: float = 1.0
    loop: bool = False
    time_window: str = ""
    qos_file_path: str = ""
    participant_qos_profile: str = ""
    writer_qos_profile: str = "DataPatternsLibrary::replay_writer_transient_local"
    launch_label: str = "Replay Service"
    launch_config_paths: Tuple[str, ...] = (
        "dds/qos/replay_service_config.xml",
        "dds/qos/DDS_QOS_PROFILES.xml",
    )
    launch_config_name: str = "template"
    launch_data_domain_id: int = 0
    launch_admin_domain_id: int = 0
    launch_monitoring_domain_id: int = 0
    launch_database_path: str = "services/rs_gui/log_data/xcdr"
    launch_storage_format: str = "XCDR"
    launch_topic_allow: str = "*"
    launch_topic_deny: str = "rti/*"
    launch_verbosity: str = "ERROR:ERROR"
    launch_executable: str = ""
    launch_working_dir: str = ""
    launch_extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hostnames", tuple(str(name) for name in self.local_hostnames))
        object.__setattr__(self, "selected_target_id", str(self.selected_target_id))
        object.__setattr__(self, "database_path", str(self.database_path))
        object.__setattr__(self, "playback_rate", float(self.playback_rate))
        object.__setattr__(self, "loop", bool(self.loop))
        object.__setattr__(self, "time_window", str(self.time_window))
        object.__setattr__(self, "qos_file_path", str(self.qos_file_path))
        object.__setattr__(self, "participant_qos_profile", str(self.participant_qos_profile))
        object.__setattr__(self, "writer_qos_profile", str(self.writer_qos_profile))
        object.__setattr__(self, "launch_config_paths", tuple(str(path) for path in self.launch_config_paths if str(path).strip()))
        object.__setattr__(self, "launch_data_domain_id", int(self.launch_data_domain_id))
        object.__setattr__(self, "launch_admin_domain_id", int(self.launch_admin_domain_id))
        object.__setattr__(self, "launch_monitoring_domain_id", int(self.launch_monitoring_domain_id))
        object.__setattr__(self, "launch_extra_args", tuple(str(arg) for arg in self.launch_extra_args if str(arg).strip()))


class ReplayTabController:
    """Build Replay tab snapshots and apply queued Replay commands."""

    def __init__(
            self,
            targets: Iterable[ReplayTargetRow] = (),
            timeline: Iterable[ReplayTimelineRow] = (),
            diagnostics: Iterable[str] = (),
            config: ReplayTabControllerConfig = None,
            process_manager: Optional[ServiceProcessManager] = None,
            admin_facade: Optional[ServiceAdminFacade] = None,
            monitoring_facade: Optional[ServiceMonitoringFacade] = None,
            clock=time.time,
    ) -> None:
        self._process_manager = process_manager
        self._admin_facade = admin_facade
        self._monitoring_facade = monitoring_facade
        self._targets = tuple(targets)
        self._state_overrides = {}
        self._timeline = tuple(timeline)
        self._diagnostics = tuple(str(item) for item in diagnostics)
        self._config = config or ReplayTabControllerConfig()
        self._clock = clock
        self._last_view = ReplayTabViewModel()
        self._last_selection = ServiceCandidateSelection()
        self._last_readiness: Optional[AdminReadiness] = None
        self._latest_monitoring_by_service: Dict[str, Dict[MonitoringSnapshotKind, MonitoringSnapshot]] = {}
        self._latest_monitoring: Tuple[MonitoringSnapshot, ...] = ()
        self._graceful_shutdown_failed = False

    @classmethod
    def mock(
            cls,
            process_manager: Optional[ServiceProcessManager] = None,
            admin_facade: Optional[ServiceAdminFacade] = None,
            monitoring_facade: Optional[ServiceMonitoringFacade] = None,
            clock=time.time,
    ) -> "ReplayTabController":
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
                launch_database_path=view.launch.database_path,
            ),
            process_manager=process_manager,
            admin_facade=admin_facade,
            monitoring_facade=monitoring_facade,
            clock=clock,
        )

    @property
    def selected_target_id(self) -> str:
        return self._config.selected_target_id

    @property
    def last_view(self) -> ReplayTabViewModel:
        return self._last_view

    @property
    def last_selection(self) -> ServiceCandidateSelection:
        return self._last_selection

    @property
    def last_monitoring_updates(self) -> Tuple[MonitoringSnapshot, ...]:
        return self._latest_monitoring

    def select_target(self, target_id: str) -> ReplayTargetRow:
        """Select a Replay Service candidate by target id."""

        target = self._target_by_id(str(target_id))
        self._config = replace(self._config, selected_target_id=target.target_id)
        return target

    def mark_graceful_shutdown_failed(self) -> None:
        self._graceful_shutdown_failed = True

    async def handle_command(self, command: AppCommand) -> CommandResult:
        """Apply a queued Replay command to the controller state."""

        payload = dict(command.payload)
        if command.command_type == "replay.select_target":
            target_id = str(payload.get("target_id") or command.target)
            target = self.select_target(target_id)
            return _command_result(command, f"Selected Replay target {target.control_name}", target)
        if command.command_type == "replay.start":
            target = self._apply_action_payload(payload)
            if self._admin_facade is not None:
                if _relaunch_required_for_start(target):
                    launch = self.launch_replay(payload)
                    self._runtime_targets()
                    self._state_overrides[launch.identity.service_ref.key] = ("RUNNING", "running")
                    return _command_result(command, f"Started replay {launch.identity.control_name}", self._target_by_id(launch.launch_id))
                return await self._execute_playback_command(command, target, ENTITY_STATE_RUNNING, "Started")
            self._state_overrides[self._selected_candidate_for_target(target.target_id).service.key] = ("RUNNING", "running")
            self._set_target_state(target.target_id, "RUNNING", progress="running")
            return _command_result(command, f"Started replay {target.control_name}", self._target_by_id(target.target_id))
        if command.command_type == "replay.pause":
            target = self._apply_action_payload(payload)
            if self._admin_facade is not None:
                return await self._execute_playback_command(command, target, ENTITY_STATE_PAUSED, "Paused")
            self._state_overrides[self._selected_candidate_for_target(target.target_id).service.key] = ("PAUSED", None)
            self._set_target_state(target.target_id, "PAUSED")
            return _command_result(command, f"Paused replay {target.control_name}", self._target_by_id(target.target_id))
        if command.command_type == "replay.resume":
            target = self._apply_action_payload(payload)
            if self._admin_facade is not None:
                return await self._execute_playback_command(command, target, ENTITY_STATE_RUNNING, "Resumed")
            self._state_overrides[self._selected_candidate_for_target(target.target_id).service.key] = ("RUNNING", "running")
            self._set_target_state(target.target_id, "RUNNING", progress="running")
            return _command_result(command, f"Resumed replay {target.control_name}", self._target_by_id(target.target_id))
        if command.command_type == "replay.stop":
            target = self._apply_action_payload(payload)
            if self._admin_facade is not None:
                return await self._execute_playback_command(command, target, ENTITY_STATE_STOPPED, "Stopped")
            self._state_overrides[self._selected_candidate_for_target(target.target_id).service.key] = ("STOPPED", "0%")
            self._set_target_state(target.target_id, "STOPPED", progress="0%")
            return _command_result(command, f"Stopped replay {target.control_name}", self._target_by_id(target.target_id))
        if command.command_type == "replay.next_tag":
            target = self._apply_action_payload(payload)
            tag_name = str(payload.get("tag_name", "")).strip()
            if not tag_name:
                raise ValueError("replay.next_tag requires tag_name")
            if self._admin_facade is None:
                self._state_overrides[self._selected_candidate_for_target(target.target_id).service.key] = ("RUNNING", "running")
                self._set_target_state(target.target_id, "RUNNING", progress="running")
                return _command_result(command, f"Jumped replay {target.control_name} to tag {tag_name}", self._target_by_id(target.target_id))
            selected = self._selected_candidate_for_target(target.target_id)
            resource_name = str(selected.details.get("admin_resource_name", ""))
            resource_path = f"{replay_service_resource(selected.service, resource_name)}/playback/current_tag"
            outcome = await self._admin_facade.execute(
                selected.service,
                ServiceCommand.CUSTOM,
                parameters={
                    **_admin_resource_parameters(selected),
                    "action": ACTION_UPDATE,
                    "resource_path": resource_path,
                    "string_body": tag_name,
                },
                timeout_sec=command.timeout_sec,
            )
            return CommandResult(
                command_id=command.command_id,
                status=CommandStatus.ACKNOWLEDGED if outcome.ok else outcome.status,
                message=outcome.message or f"Jumped replay {target.control_name} to tag {tag_name}",
                payload={
                    "target_id": target.target_id,
                    "control_name": target.control_name,
                    "resource_path": outcome.resource_path or resource_path,
                    "command": ServiceCommand.CUSTOM.value,
                    "tag_name": tag_name,
                },
                created_at=command.created_at,
            )
        if command.command_type == "replay.shutdown":
            target = self._apply_action_payload(payload)
            if self._admin_facade is not None:
                selected = self._selected_candidate_for_target(target.target_id)
                outcome = await self._admin_facade.execute(
                    selected.service,
                    ServiceCommand.SHUTDOWN,
                    parameters=_admin_resource_parameters(selected),
                    timeout_sec=command.timeout_sec,
                )
                self._graceful_shutdown_failed = not outcome.ok
                if self._process_manager is not None and target.owned:
                    self._process_manager.request_local_termination(
                        self._last_selection,
                        graceful_shutdown_failed=True,
                        candidate_id=selected.candidate_id,
                        local_hostnames=self._config.local_hostnames,
                    )
            self._state_overrides[self._selected_candidate_for_target(target.target_id).service.key] = ("SHUTDOWN", "")
            self._set_target_state(target.target_id, "SHUTDOWN", progress="")
            return _command_result(command, f"Shutdown replay {target.control_name}", self._target_by_id(target.target_id))
        raise ValueError(f"Unsupported Replay command type: {command.command_type}")

    def launch_replay(self, payload: Mapping[str, object]) -> ServiceProcessLaunch:
        """Launch Replay Service from Replay-tab operator fields."""

        if self._process_manager is None:
            raise RuntimeError("Replay Service launch requires a ServiceProcessManager")
        config_paths = _config_paths_from_value(payload.get("config_paths", self._config.launch_config_paths))
        label = str(payload.get("label", self._config.launch_label)).strip() or "Replay Service"
        config_name = str(payload.get("config_name", self._config.launch_config_name)).strip()
        data_domain_id = _int_payload(payload, "data_domain_id", self._config.launch_data_domain_id)
        admin_domain_id = _int_payload(payload, "admin_domain_id", self._config.launch_admin_domain_id)
        monitoring_domain_id = _int_payload(payload, "monitoring_domain_id", self._config.launch_monitoring_domain_id)
        database_path = str(payload.get("database_path", self._config.launch_database_path)).strip()
        resolved_database_path = _workspace_launch_path(database_path)
        if not database_path:
            raise ValueError("Replay launch requires a recording database path")
        if not _has_replayable_sqlite_files(database_path):
            raise ValueError(
                "Replay launch requires a recording database directory with metadata.db and at least one data_*.db file"
            )
        storage_format = str(payload.get("storage_format", self._config.launch_storage_format)).strip() or "XCDR"
        playback_rate = float(str(payload.get("playback_rate", self._config.playback_rate)).strip() or self._config.playback_rate)
        loop = bool(payload.get("loop", self._config.loop))
        time_window = str(payload.get("time_window", self._config.time_window)).strip()
        topic_allow = str(payload.get("topic_allow", self._config.launch_topic_allow)).strip() or "*"
        topic_deny = str(payload.get("topic_deny", self._config.launch_topic_deny)).strip()
        qos_file_path = str(payload.get("qos_file_path", self._config.qos_file_path)).strip()
        resolved_qos_file_path = _workspace_launch_path(qos_file_path)
        participant_qos_profile = str(payload.get("participant_qos_profile", self._config.participant_qos_profile)).strip()
        writer_qos_profile = str(payload.get("writer_qos_profile", self._config.writer_qos_profile)).strip()
        verbosity = _compose_verbosity(payload, self._config.launch_verbosity)
        executable = str(payload.get("executable", self._config.launch_executable)).strip()
        working_dir = str(payload.get("working_dir", self._config.launch_working_dir)).strip()
        operator_extra_args = _operator_extra_args(_extra_args_from_value(payload.get("extra_args", self._config.launch_extra_args)))
        storage_variable_prefix = _storage_variable_prefix(config_name)
        launch_extra_args = (
            f"-DREPLAY_DOMAIN_ID={data_domain_id}",
            f"-DREPLAY_ADMIN_DOMAIN_ID={admin_domain_id}",
            f"-DREPLAY_MON_DOMAIN_ID={monitoring_domain_id}",
            f"-DREPLAY_STORAGE_FORMAT={storage_format}",
            f"-DREPLAY_DATABASE_DIR={resolved_database_path}",
            f"-D{storage_variable_prefix}_STORAGE_FORMAT={storage_format}",
            f"-D{storage_variable_prefix}_DATABASE_DIR={resolved_database_path}",
            f"-DREPLAY_PLAYBACK_RATE={playback_rate:g}",
            f"-DREPLAY_ENABLE_LOOPING={'true' if loop else 'false'}",
            f"-DREPLAY_TOPIC_ALLOW={topic_allow}",
            f"-DREPLAY_TOPIC_DENY={topic_deny}",
            f"-DDOMAIN_ID={data_domain_id}",
        ) + operator_extra_args
        if resolved_qos_file_path:
            launch_extra_args += (f"-DREPLAY_QOS_FILE={resolved_qos_file_path}",)
        if participant_qos_profile:
            launch_extra_args += (f"-DREPLAY_DP_QOS={participant_qos_profile}",)
        if writer_qos_profile:
            launch_extra_args += (f"-DREPLAY_DW_QOS={writer_qos_profile}",)
        environment = {
            "REPLAY_DOMAIN_ID": str(data_domain_id),
            "REPLAY_ADMIN_DOMAIN_ID": str(admin_domain_id),
            "REPLAY_MON_DOMAIN_ID": str(monitoring_domain_id),
            "REPLAY_DATABASE_DIR": resolved_database_path,
            f"{storage_variable_prefix}_STORAGE_FORMAT": storage_format,
            f"{storage_variable_prefix}_DATABASE_DIR": resolved_database_path,
            "DOMAIN_ID": str(data_domain_id),
        }
        nddshome = os.environ.get("NDDSHOME", "") or detect_nddshome()
        if nddshome:
            environment["NDDSHOME"] = nddshome
        license_file = os.environ.get("RTI_LICENSE_FILE", "") or ensure_rti_license(nddshome)
        if license_file:
            environment["RTI_LICENSE_FILE"] = license_file
        request = ServiceProcessLaunchRequest(
            intent=ServiceLaunchIntent(
                kind=ServiceKind.REPLAY,
                label=label,
                admin_domain_id=admin_domain_id,
                monitoring_domain_id=monitoring_domain_id,
                config_paths=config_paths,
            ),
            config_name=config_name,
            executable=executable,
            working_dir=working_dir,
            verbosity=verbosity,
            environment=environment,
            extra_args=launch_extra_args,
        )
        launch = self._process_manager.launch(request)
        self._config = replace(
            self._config,
            service=launch.identity.service_ref,
            selected_target_id=launch.launch_id,
            database_path=database_path,
            playback_rate=playback_rate,
            loop=loop,
            time_window=time_window,
            qos_file_path=qos_file_path,
            participant_qos_profile=participant_qos_profile,
            writer_qos_profile=writer_qos_profile,
            launch_label=label,
            launch_config_paths=config_paths,
            launch_config_name=config_name,
            launch_data_domain_id=data_domain_id,
            launch_admin_domain_id=admin_domain_id,
            launch_monitoring_domain_id=monitoring_domain_id,
            launch_database_path=database_path,
            launch_storage_format=storage_format,
            launch_topic_allow=topic_allow,
            launch_topic_deny=topic_deny,
            launch_verbosity=verbosity,
            launch_executable=executable,
            launch_working_dir=working_dir,
            launch_extra_args=operator_extra_args,
        )
        self._graceful_shutdown_failed = False
        return launch

    async def execute_action(self, action_id: str, timeout_sec: Optional[float] = None):
        """Dispatch high-confidence Replay process actions."""

        if self._process_manager is None:
            raise RuntimeError("Replay Service actions require a ServiceProcessManager")
        self._runtime_targets()
        selection = self._last_selection
        if self._config.selected_target_id:
            selection = selection.select(self._config.selected_target_id)
        selected = selection.selected_candidate
        if selected is None:
            raise ValueError("No Replay Service candidate is selected")
        if action_id == "terminate_local":
            return self._process_manager.request_local_termination(
                selection,
                graceful_shutdown_failed=self._graceful_shutdown_failed,
                candidate_id=selected.candidate_id,
                local_hostnames=self._config.local_hostnames,
            )
        if action_id == "kill_local":
            return self._process_manager.request_local_kill(
                selection,
                candidate_id=selected.candidate_id,
            )
        if action_id == "shutdown":
            if self._admin_facade is None:
                raise RuntimeError("Replay Service shutdown requires a Service Admin facade")
            outcome = await self._admin_facade.execute(
                selected.service,
                ServiceCommand.SHUTDOWN,
                parameters=_admin_resource_parameters(selected),
                timeout_sec=timeout_sec,
            )
            self._graceful_shutdown_failed = not outcome.ok
            return outcome
        raise ValueError(f"Unsupported Replay tab action: {action_id}")

    async def _execute_playback_command(
            self,
            command: AppCommand,
            target: ReplayTargetRow,
            state_value: int,
            verb: str,
    ) -> CommandResult:
        selected = self._selected_candidate_for_target(target.target_id)
        resource_name = str(selected.details.get("admin_resource_name", ""))
        resource_path = replay_service_state_resource(selected.service, resource_name)
        outcome = await self._admin_facade.execute(
            selected.service,
            ServiceCommand.CUSTOM,
            parameters={
                **_admin_resource_parameters(selected),
                "action": ACTION_UPDATE,
                "resource_path": resource_path,
                "entity_state_value": state_value,
            },
        )
        if outcome.ok:
            override = None
            if state_value == ENTITY_STATE_PAUSED:
                override = ("PAUSED", None)
            elif state_value == ENTITY_STATE_STOPPED:
                override = ("STOPPED", "0%")
            elif state_value == ENTITY_STATE_RUNNING:
                override = ("RUNNING", "running")
            if override is not None:
                self._state_overrides[selected.service.key] = override
                self._set_target_state(target.target_id, override[0], progress=override[1])
        return CommandResult(
            command_id=command.command_id,
            status=CommandStatus.ACKNOWLEDGED if outcome.ok else outcome.status,
            message=outcome.message or f"{verb} replay {target.control_name}",
            payload={
                "target_id": target.target_id,
                "control_name": target.control_name,
                "resource_path": outcome.resource_path or resource_path,
                "command": ServiceCommand.CUSTOM.value,
            },
            created_at=command.created_at,
        )

    async def refresh_view(self) -> ReplayTabViewModel:
        """Return the next Replay-tab view from controller state."""

        service = self._target_service()
        monitoring_updates = await self._take_monitoring_updates(self._monitoring_services(service))
        self._cache_monitoring_updates(monitoring_updates)
        if not service.name:
            discovered = self._discover_service_from_cache(service)
            if discovered is not None:
                service = discovered
                self._config = replace(self._config, service=discovered)
        self._latest_monitoring = self._monitoring_snapshots_for_service(service)
        readiness = await self._readiness(service)
        self._last_readiness = readiness
        runtime_targets = self._runtime_targets(service, self._latest_monitoring)
        targets = runtime_targets + self._targets
        view = build_replay_tab_view_model(
            targets=targets,
            selected_target_id=self._config.selected_target_id,
            database_path=self._config.database_path,
            readiness=_readiness_text(readiness),
            playback_rate=self._config.playback_rate,
            loop=self._config.loop,
            time_window=self._config.time_window,
            qos_file_path=self._config.qos_file_path,
            participant_qos_profile=self._config.participant_qos_profile,
            writer_qos_profile=self._config.writer_qos_profile,
            launch=self._launch_view(),
            timeline=self._timeline,
            diagnostics=self._diagnostics,
        )
        if view.selected_target_id != self._config.selected_target_id:
            self._config = replace(self._config, selected_target_id=view.selected_target_id)
        self._last_view = view
        return view

    def _target_service(self) -> ServiceInstanceRef:
        if self._config.service is not None:
            return self._config.service
        if self._process_manager is not None:
            for launch in self._process_manager.launches():
                if launch.identity.intent.kind == ServiceKind.REPLAY:
                    return launch.identity.service_ref
        return ServiceInstanceRef(
            ServiceKind.REPLAY,
            "",
            admin_domain_id=self._config.launch_admin_domain_id,
            monitoring_domain_id=self._config.launch_monitoring_domain_id,
            config_paths=self._config.launch_config_paths,
        )

    def _monitoring_services(self, service: ServiceInstanceRef) -> Tuple[ServiceInstanceRef, ...]:
        services = []
        if service.name:
            services.append(service)
        if self._process_manager is not None:
            for launch in self._process_manager.launches():
                if launch.identity.intent.kind == ServiceKind.REPLAY:
                    services.append(launch.identity.service_ref)
        if not services:
            services.append(ServiceInstanceRef(
                kind=ServiceKind.REPLAY,
                name="",
                admin_domain_id=self._config.launch_admin_domain_id,
                monitoring_domain_id=self._config.launch_monitoring_domain_id,
            ))
        unique = {}
        for item in services:
            unique.setdefault(item.key, item)
        return tuple(unique.values())

    async def _take_monitoring_updates(self, services: Tuple[ServiceInstanceRef, ...]) -> Tuple[MonitoringSnapshot, ...]:
        if self._monitoring_facade is None:
            return ()
        updates = []
        for service in services:
            updates.extend(await self._monitoring_facade.take_available(service))
        return tuple(updates)

    def _cache_monitoring_updates(self, updates: Iterable[MonitoringSnapshot]) -> None:
        for snapshot in updates:
            by_kind = self._latest_monitoring_by_service.setdefault(snapshot.service.key, {})
            current = by_kind.get(snapshot.kind)
            if current is None:
                by_kind[snapshot.kind] = snapshot
                continue
            if snapshot.kind == MonitoringSnapshotKind.CONFIG:
                newer, older = (
                    (snapshot, current)
                    if snapshot.observed_at >= current.observed_at
                    else (current, snapshot)
                )
                by_kind[snapshot.kind] = MonitoringSnapshot(
                    service=newer.service,
                    kind=newer.kind,
                    state=newer.state,
                    metrics=newer.metrics,
                    details=_merge_monitoring_details(older.details, newer.details),
                    observed_at=newer.observed_at,
                )
                continue
            if snapshot.observed_at >= current.observed_at:
                by_kind[snapshot.kind] = snapshot

    def _discover_service_from_cache(self, probe: ServiceInstanceRef) -> Optional[ServiceInstanceRef]:
        for cached_by_kind in self._latest_monitoring_by_service.values():
            if not cached_by_kind:
                continue
            sample = next(iter(cached_by_kind.values()))
            if sample.service.kind != ServiceKind.REPLAY:
                continue
            if sample.service.monitoring_domain_id != probe.monitoring_domain_id:
                continue
            if sample.service.name:
                return sample.service
        return None

    def _monitoring_snapshots_for_service(self, service: ServiceInstanceRef) -> Tuple[MonitoringSnapshot, ...]:
        by_kind = self._latest_monitoring_by_service.get(service.key, {})
        remap_service = False
        if not by_kind and service.name:
            for cached_by_kind in self._latest_monitoring_by_service.values():
                if not cached_by_kind:
                    continue
                sample = next(iter(cached_by_kind.values()))
                if (sample.service.kind == service.kind
                        and sample.service.monitoring_domain_id == service.monitoring_domain_id):
                    by_kind = cached_by_kind
                    remap_service = True
                    break
        snapshots = tuple(
            snapshot for kind, snapshot in sorted(by_kind.items(), key=lambda item: item[0].value)
        )
        if remap_service and snapshots:
            snapshots = tuple(
                MonitoringSnapshot(
                    service=service,
                    kind=s.kind,
                    state=s.state,
                    metrics=s.metrics,
                    details=s.details,
                    observed_at=s.observed_at,
                )
                for s in snapshots
            )
        return snapshots

    async def _readiness(self, service: ServiceInstanceRef) -> Optional[AdminReadiness]:
        if not service.name:
            return None
        if self._admin_facade is None:
            return AdminReadiness(
                service=service,
                status=AdminReadinessStatus.UNKNOWN,
                message="Service Admin facade is not configured",
                checked_at=self._clock(),
            )
        return await self._admin_facade.readiness(service)

    def _runtime_targets(
            self,
            service: Optional[ServiceInstanceRef] = None,
            monitoring_snapshots: Iterable[MonitoringSnapshot] = (),
    ) -> Tuple[ReplayTargetRow, ...]:
        if self._process_manager is None:
            self._last_selection = ServiceCandidateSelection()
            return ()
        service = service or self._target_service()
        selection = self._process_manager.candidate_selection(
            service,
            monitoring_snapshots=monitoring_snapshots,
            selected_candidate_id=self._config.selected_target_id,
            display_label=self._config.display_label,
        )
        replay_candidates = tuple(candidate for candidate in selection.candidates if candidate.service.kind == ServiceKind.REPLAY)
        self._last_selection = ServiceCandidateSelection(
            candidates=replay_candidates,
            selected_candidate_id=selection.selected_candidate_id,
        )
        targets = []
        for candidate in replay_candidates:
            target = _target_from_candidate(candidate, self._clock())
            target = _stabilize_replay_target_state(target, candidate)
            override = self._state_overrides.get(candidate.service.key)
            if override is not None:
                state, progress = override
                target = replace(target, state=state, progress=target.progress if progress is None else progress)
            targets.append(target)
        return tuple(targets)

    def _launch_view(self) -> ReplayLaunchViewModel:
        return ReplayLaunchViewModel(
            label=self._config.launch_label,
            config_paths=self._config.launch_config_paths,
            config_name=self._config.launch_config_name,
            data_domain_id=self._config.launch_data_domain_id,
            admin_domain_id=self._config.launch_admin_domain_id,
            monitoring_domain_id=self._config.launch_monitoring_domain_id,
            database_path=self._config.launch_database_path,
            storage_format=self._config.launch_storage_format,
            playback_rate=self._config.playback_rate,
            loop=self._config.loop,
            time_window=self._config.time_window,
            topic_allow=self._config.launch_topic_allow,
            topic_deny=self._config.launch_topic_deny,
            qos_file_path=self._config.qos_file_path,
            participant_qos_profile=self._config.participant_qos_profile,
            writer_qos_profile=self._config.writer_qos_profile,
            verbosity=self._config.launch_verbosity,
            executable=self._config.launch_executable,
            working_dir=self._config.launch_working_dir,
            extra_args=self._config.launch_extra_args,
        )

    def _apply_action_payload(self, payload: Mapping[str, object]) -> ReplayTargetRow:
        target_id = str(payload.get("target_id") or self._config.selected_target_id)
        control_name = str(payload.get("control_name") or "").strip()
        if target_id:
            try:
                self.select_target(target_id)
            except ValueError:
                if control_name:
                    self.select_target(control_name)
                else:
                    raise
        database_path = str(payload.get("database_path") or self._config.database_path)
        if not database_path.strip():
            raise ValueError("replay.start requires a recording database path")
        playback_rate = float(payload.get("playback_rate", self._config.playback_rate))
        loop = bool(payload.get("loop", self._config.loop))
        time_window = str(payload.get("time_window") or self._config.time_window)
        qos_file_path = str(payload.get("qos_file_path") or self._config.qos_file_path)
        participant_qos_profile = str(payload.get("participant_qos_profile") or self._config.participant_qos_profile)
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
        targets = self._all_targets()
        if not target_id and targets:
            target_id = targets[0].target_id
            self._config = replace(self._config, selected_target_id=target_id)
        return self._target_by_id(target_id)

    def _selected_candidate_for_target(self, target_id: str):
        selection = self._last_selection
        if not selection.candidates:
            self._runtime_targets()
            selection = self._last_selection
        for candidate in selection.candidates:
            if candidate.candidate_id == target_id or candidate.launch_id == target_id:
                return candidate
        if selection.selected_candidate is not None:
            return selection.selected_candidate
        target = self._target_by_id(target_id)
        service = self._config.service or ServiceInstanceRef(
            ServiceKind.REPLAY,
            target.control_name,
            admin_domain_id=self._config.launch_admin_domain_id,
            monitoring_domain_id=self._config.launch_monitoring_domain_id,
            config_paths=self._config.launch_config_paths,
        )
        resource_name = self._config.launch_config_name or target.control_name
        return ServiceProcessCandidate(
            candidate_id=target.target_id,
            service=service,
            source="monitoring",
            display_label=target.label,
            hostname=target.hostname,
            observed_state=target.state,
            details={"admin_resource_name": resource_name},
            alive=True,
            owns_process=target.owned,
            confidence=1.0,
            first_seen_at=self._clock(),
            last_seen_at=self._clock(),
        )

    def _target_by_id(self, target_id: str) -> ReplayTargetRow:
        for target in self._all_targets():
            if target.target_id == target_id or target.control_name == target_id:
                return target
        raise ValueError(f"Unknown Replay target: {target_id}")

    def _all_targets(self) -> Tuple[ReplayTargetRow, ...]:
        return self._runtime_targets() + self._targets

    def _set_target_state(self, target_id: str, state: str, progress: str = None) -> None:
        updated = []
        for target in self._targets:
            if target.target_id == target_id:
                updated.append(replace(target, state=str(state), progress=target.progress if progress is None else str(progress)))
            else:
                updated.append(target)
        self._targets = tuple(updated)


def _command_result(command: AppCommand, message: str, target: ReplayTargetRow) -> CommandResult:
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


def _relaunch_required_for_start(target: ReplayTargetRow) -> bool:
    return bool(target.owned) and str(target.state).strip().lower() in {"stopped", "shutdown", "exited", "start_failed"}


def _target_from_candidate(candidate, now: float) -> ReplayTargetRow:
    details = dict(candidate.details)
    age_sec = max(0.0, float(now) - float(candidate.last_seen_at))
    return ReplayTargetRow(
        target_id=candidate.candidate_id,
        candidate_id=candidate.candidate_id,
        label=candidate.display_label or "Replay Service",
        control_name=candidate.service.name,
        source=candidate.source.value,
        hostname=candidate.hostname,
        state=_normalized_replay_state(candidate.observed_state),
        progress=str(candidate.metrics.get("progress", "")),
        pid="" if candidate.pid is None else str(candidate.pid),
        owned=candidate.owns_process,
        age=f"{age_sec:.1f}s",
        confidence=f"{candidate.confidence:.2f}",
        output_path=str(details.get("output_path", "")),
        output_tail=str(details.get("output_tail", "")),
    )


def _stabilize_replay_target_state(target: ReplayTargetRow, candidate: ServiceProcessCandidate) -> ReplayTargetRow:
    """Prefer a stable running state over generic monitoring lifecycle markers.

    Replay monitoring periodic/config snapshots may report generic states such as
    OBSERVED/CONFIGURED while the locally launched process is healthy. For GUI
    readability, avoid flipping between RUNNING and OBSERVED for owned, alive
    processes.
    """
    normalized = str(target.state).strip().upper()
    if normalized not in {"OBSERVED", "CONFIGURED"}:
        return target
    if not candidate.owns_process or not candidate.alive:
        return target
    progress = target.progress or "running"
    return replace(target, state="RUNNING", progress=progress)


def _normalized_replay_state(state: object) -> str:
    normalized = str(state or "").strip()
    if not normalized:
        return "unknown"
    return normalized.upper()


def _config_paths_from_value(value: object) -> Tuple[str, ...]:
    if isinstance(value, str):
        parts = value.replace("\n", ";").split(";")
    else:
        try:
            parts = list(value)  # type: ignore[arg-type]
        except TypeError:
            parts = []
    return tuple(str(part).strip() for part in parts if str(part).strip())


def _extra_args_from_value(value: object) -> Tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split() if part.strip())
    try:
        return tuple(str(part).strip() for part in value if str(part).strip())  # type: ignore[union-attr]
    except TypeError:
        return ()


def _int_payload(payload: Mapping[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    return int(str(value).strip())


def _operator_extra_args(extra_args: Tuple[str, ...]) -> Tuple[str, ...]:
    managed_arg_prefixes = (
        "-DREPLAY_DOMAIN_ID=",
        "-DREPLAY_ADMIN_DOMAIN_ID=",
        "-DREPLAY_MON_DOMAIN_ID=",
        "-DREPLAY_STORAGE_FORMAT=",
        "-DREPLAY_DATABASE_DIR=",
        "-DREPLAY_XCDR_STORAGE_FORMAT=",
        "-DREPLAY_XCDR_DATABASE_DIR=",
        "-DREPLAY_JSON_STORAGE_FORMAT=",
        "-DREPLAY_JSON_DATABASE_DIR=",
        "-DREPLAY_PLAYBACK_RATE=",
        "-DREPLAY_ENABLE_LOOPING=",
        "-DREPLAY_TOPIC_ALLOW=",
        "-DREPLAY_TOPIC_DENY=",
        "-DDOMAIN_ID=",
    )
    return tuple(arg for arg in extra_args if not any(arg.startswith(prefix) for prefix in managed_arg_prefixes))


def _storage_variable_prefix(config_name: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in config_name.upper()).strip("_")
    if normalized in {"", "XCDR"}:
        return "REPLAY_XCDR"
    if normalized == "JSON":
        return "REPLAY_JSON"
    return f"REPLAY_{normalized}"


def _admin_resource_parameters(candidate) -> dict:
    resource_name = str(candidate.details.get("admin_resource_name", ""))
    return {"admin_resource_name": resource_name} if resource_name else {}


def _merge_monitoring_details(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    merged.update(dict(override))
    return merged


def _readiness_text(readiness: Optional[AdminReadiness]) -> str:
    if readiness is None:
        return "not checked"
    if readiness.ready:
        return "request+reply matched"
    return readiness.message or readiness.status.value
