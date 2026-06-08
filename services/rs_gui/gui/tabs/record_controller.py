"""Record tab controller that wires app-core service snapshots to GUI views."""

import asyncio
from dataclasses import dataclass, field, replace
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app_core.debug_log import dbg, dbg_exc
from app_core.events import CommandStatus
from app_core.connext_environment import detect_nddshome, ensure_rti_license
from app_core.services import (
    AdminReadiness,
    AdminReadinessStatus,
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceAdminFacade,
    ServiceCandidateSelection,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceMonitoringFacade,
    ServiceProcessCandidate,
    ServiceProcessLaunch,
    ServiceProcessLaunchState,
    ServiceProcessLaunchRequest,
    ServiceProcessManager,
)

from .record_tab import RecordLaunchViewModel, RecordTabViewModel, build_record_tab_view_model


@dataclass(frozen=True)
class RecordTabControllerConfig:
    """Runtime wiring options for the Record tab controller."""

    service: Optional[ServiceInstanceRef] = None
    display_label: str = "Recording Service"
    local_hostnames: Tuple[str, ...] = field(default_factory=tuple)
    selected_candidate_id: str = ""
    tag_value: str = ""
    launch_label: str = "Recording Service"
    launch_config_paths: Tuple[str, ...] = (
        "dds/qos/recording_service.xml",
        "dds/qos/DDS_QOS_PROFILES.xml",
    )
    launch_config_name: str = "template"
    launch_storage_format: str = "XCDR"
    launch_data_domain_id: int = 0
    launch_admin_domain_id: int = 0
    launch_monitoring_domain_id: int = 0
    launch_topic_allow: str = "*"
    launch_topic_deny: str = "rti/*"
    launch_log_directory: str = "services/rs_gui/log_data"
    launch_verbosity: str = "ERROR:ERROR"
    launch_executable: str = ""
    launch_working_dir: str = ""
    launch_extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hostnames", tuple(str(name) for name in self.local_hostnames))
        object.__setattr__(self, "launch_config_paths", tuple(str(path) for path in self.launch_config_paths if str(path).strip()))
        object.__setattr__(self, "launch_data_domain_id", int(self.launch_data_domain_id))
        object.__setattr__(self, "launch_admin_domain_id", int(self.launch_admin_domain_id))
        object.__setattr__(self, "launch_monitoring_domain_id", int(self.launch_monitoring_domain_id))
        object.__setattr__(self, "launch_storage_format", _record_storage_format_ui(self.launch_storage_format))
        object.__setattr__(self, "launch_topic_allow", str(self.launch_topic_allow).strip() or "*")
        object.__setattr__(self, "launch_topic_deny", str(self.launch_topic_deny).strip())
        object.__setattr__(self, "launch_extra_args", tuple(str(arg) for arg in self.launch_extra_args if str(arg).strip()))


class RecordTabController:
    """Build Record tab snapshots and dispatch selected service actions."""

    _LOCAL_SHUTDOWN_REAP_TIMEOUT_SEC = 1.0
    _LOCAL_SHUTDOWN_REAP_POLL_SEC = 0.05

    def __init__(
            self,
            process_manager: ServiceProcessManager,
            admin_facade: Optional[ServiceAdminFacade] = None,
            monitoring_facade: Optional[ServiceMonitoringFacade] = None,
            config: Optional[RecordTabControllerConfig] = None,
            clock=time.time,
    ) -> None:
        self._process_manager = process_manager
        self._admin_facade = admin_facade
        self._monitoring_facade = monitoring_facade
        self._config = config or RecordTabControllerConfig()
        self._clock = clock
        self._command_history: Tuple[ServiceCommandOutcome, ...] = ()
        self._latest_monitoring_by_service: Dict[str, Dict[MonitoringSnapshotKind, MonitoringSnapshot]] = {}
        self._latest_monitoring: Tuple[MonitoringSnapshot, ...] = ()
        self._last_monitoring_updates: Tuple[MonitoringSnapshot, ...] = ()
        self._last_selection = ServiceCandidateSelection()
        self._last_readiness: Optional[AdminReadiness] = None
        self._graceful_shutdown_failed = False

    @property
    def command_history(self) -> Tuple[ServiceCommandOutcome, ...]:
        return self._command_history

    @property
    def selected_candidate_id(self) -> str:
        return self._config.selected_candidate_id

    @property
    def tag_value(self) -> str:
        return self._config.tag_value

    @property
    def last_selection(self) -> ServiceCandidateSelection:
        return self._last_selection

    @property
    def last_monitoring_updates(self) -> Tuple[MonitoringSnapshot, ...]:
        return self._last_monitoring_updates

    def set_tag_value(self, value: str) -> None:
        self._config = replace(self._config, tag_value=str(value))

    def select_candidate(self, candidate_id: str) -> None:
        self._config = replace(self._config, selected_candidate_id=str(candidate_id))

    def set_service(self, service: ServiceInstanceRef) -> None:
        self._config = replace(self._config, service=service)

    def mark_graceful_shutdown_failed(self) -> None:
        self._graceful_shutdown_failed = True

    async def refresh_view(self) -> RecordTabViewModel:
        """Collect latest app-core snapshots and return a Record-tab view."""

        service = self._target_service()
        dbg("record", f"refresh_view service={service.name!r} kind={service.kind.value} mon_domain={service.monitoring_domain_id}")
        mon_services = self._monitoring_services(service)
        dbg("record", f"monitoring_services count={len(mon_services)}",
            keys=[s.key for s in mon_services])
        monitoring_updates = await self._take_monitoring_updates(mon_services)
        dbg("record", f"monitoring_updates count={len(monitoring_updates)}")
        self._last_monitoring_updates = monitoring_updates
        self._cache_monitoring_updates(monitoring_updates)
        # If we discovered a service via monitoring but didn't have one yet,
        # adopt the discovered identity so subsequent frames track it properly.
        if not service.name:
            discovered = self._discover_service_from_cache(service)
            if discovered is not None:
                dbg("record", f"discovered service={discovered.name!r} from monitoring")
                service = discovered
                self._config = replace(self._config, service=discovered)
        monitoring_snapshots = self._monitoring_snapshots_for_service(service)
        dbg("record", f"monitoring_snapshots count={len(monitoring_snapshots)}",
            kinds=[s.kind.value for s in monitoring_snapshots])
        self._latest_monitoring = monitoring_snapshots
        readiness = await self._readiness(service)
        self._last_readiness = readiness
        dbg("record", f"readiness={readiness.status.value if readiness else None}")
        selection = self._selection(service, monitoring_snapshots)
        selection = _apply_command_state_override(selection, self._command_history)
        self._last_selection = selection
        selected = selection.selected_candidate
        if selected and not self._config.selected_candidate_id:
            self._config = replace(self._config, selected_candidate_id=selected.candidate_id)
        return build_record_tab_view_model(
            selection,
            readiness=readiness,
            command_history=self._command_history,
            local_hostnames=self._config.local_hostnames,
            graceful_shutdown_failed=self._graceful_shutdown_failed,
            tag_value=self._config.tag_value,
            launch=self._launch_view(),
            now=self._clock(),
        )

    def launch_recording(self, payload: Mapping[str, object]) -> ServiceProcessLaunch:
        """Launch Recording Service from Record-tab operator fields."""

        config_paths = _config_paths_from_value(
            payload.get("config_paths", self._config.launch_config_paths)
        )
        label = str(payload.get("label", self._config.launch_label)).strip() or "Recording Service"
        config_name = str(payload.get("config_name", self._config.launch_config_name)).strip()
        storage_format = _record_storage_format_ui(payload.get("storage_format", self._config.launch_storage_format))
        storage_format_env = _record_storage_format_env(storage_format)
        data_domain_id = _int_payload(payload, "data_domain_id", self._config.launch_data_domain_id)
        admin_domain_id = _int_payload(payload, "admin_domain_id", self._config.launch_admin_domain_id)
        monitoring_domain_id = _int_payload(payload, "monitoring_domain_id", self._config.launch_monitoring_domain_id)
        topic_allow = str(payload.get("topic_allow", self._config.launch_topic_allow)).strip() or "*"
        topic_deny = str(payload.get("topic_deny", self._config.launch_topic_deny)).strip()
        log_directory = str(payload.get("log_directory", self._config.launch_log_directory)).strip() or "services/rs_gui/log_data"
        effective_log_directory = _record_log_directory(log_directory, storage_format_env)
        verbosity = str(payload.get("verbosity", self._config.launch_verbosity)).strip() or "ERROR:ERROR"
        executable = str(payload.get("executable", self._config.launch_executable)).strip()
        working_dir = str(payload.get("working_dir", self._config.launch_working_dir)).strip()
        extra_args = _extra_args_from_value(payload.get("extra_args", self._config.launch_extra_args))
        # Emit REC_* overrides for the variable-driven template and keep legacy
        # DOMAIN_* flags for backward compatibility with older configs.
        managed_arg_prefixes = (
            "-DREC_DOMAIN_ID=",
            "-DREC_ADMIN_DOMAIN_ID=",
            "-DREC_MON_DOMAIN_ID=",
            "-DREC_STATUS_PERIOD_SEC=",
            "-DREC_STATUS_PERIOD_NSEC=",
            "-DREC_STORAGE_FORMAT=",
            "-DREC_FILENAME_EXPR=",
            "-DREC_LOG_DIR=",
            "-DREC_WORKSPACE_DIR=",
            "-DREC_TOPIC_ALLOW=",
            "-DREC_TOPIC_DENY=",
            "-DDOMAIN_ID=",
            "-DADMIN_DOMAIN_ID=",
        )
        operator_extra_args = tuple(
            _normalize_record_extra_arg(arg) for arg in extra_args
            if not any(arg.startswith(prefix) for prefix in managed_arg_prefixes)
        )
        launch_extra_args = (
            f"-DREC_DOMAIN_ID={data_domain_id}",
            f"-DREC_ADMIN_DOMAIN_ID={admin_domain_id}",
            f"-DREC_MON_DOMAIN_ID={monitoring_domain_id}",
            "-DREC_STATUS_PERIOD_SEC=0",
            "-DREC_STATUS_PERIOD_NSEC=500000000",
            f"-DREC_FILENAME_EXPR={_record_filename_expression(storage_format_env)}",
            f"-DREC_LOG_DIR={effective_log_directory}",
            f"-DREC_WORKSPACE_DIR={effective_log_directory}",
            f"-DREC_STORAGE_FORMAT={storage_format_env}",
            f"-DREC_TOPIC_ALLOW={topic_allow}",
            f"-DREC_TOPIC_DENY={topic_deny}",
            f"-DDOMAIN_ID={data_domain_id}",
            f"-DADMIN_DOMAIN_ID={admin_domain_id}",
        ) + operator_extra_args
        environment = {
            "REC_DOMAIN_ID": str(data_domain_id),
            "REC_ADMIN_DOMAIN_ID": str(admin_domain_id),
            "REC_MON_DOMAIN_ID": str(monitoring_domain_id),
            "REC_FILENAME_EXPR": _record_filename_expression(storage_format_env),
            "REC_LOG_DIR": effective_log_directory,
            "REC_WORKSPACE_DIR": effective_log_directory,
            "REC_STORAGE_FORMAT": storage_format_env,
            "REC_TOPIC_ALLOW": topic_allow,
            "REC_TOPIC_DENY": topic_deny,
            "DOMAIN_ID": str(data_domain_id),
            "ADMIN_DOMAIN_ID": str(admin_domain_id),
        }
        nddshome = os.environ.get("NDDSHOME", "") or detect_nddshome()
        if nddshome:
            environment["NDDSHOME"] = nddshome
        license_file = os.environ.get("RTI_LICENSE_FILE", "") or ensure_rti_license(nddshome)
        if license_file:
            environment["RTI_LICENSE_FILE"] = license_file

        request = ServiceProcessLaunchRequest(
            intent=ServiceLaunchIntent(
                kind=ServiceKind.RECORDING,
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
            launch_label=label,
            launch_config_paths=config_paths,
            launch_config_name=config_name,
            launch_storage_format=storage_format,
            launch_data_domain_id=data_domain_id,
            launch_admin_domain_id=admin_domain_id,
            launch_monitoring_domain_id=monitoring_domain_id,
            launch_topic_allow=topic_allow,
            launch_topic_deny=topic_deny,
            launch_log_directory=effective_log_directory,
            launch_verbosity=verbosity,
            launch_executable=executable,
            launch_working_dir=working_dir,
            launch_extra_args=operator_extra_args,
            selected_candidate_id=launch.launch_id,
            service=launch.identity.service_ref,
        )
        self._graceful_shutdown_failed = False
        return launch

    async def execute_action(
            self,
            action_id: str,
            tag_name: str = "",
            description: str = "",
            timeout_sec: Optional[float] = None,
    ):
        """Dispatch a Record tab action for the selected candidate."""

        service = self._target_service()
        selection = self._selection(service, self._latest_monitoring)
        if self._config.selected_candidate_id:
            selection = selection.select(self._config.selected_candidate_id)
        selected = selection.selected_candidate
        if selected is None:
            raise ValueError("No Recording Service candidate is selected")

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

        if self._admin_facade is None:
            outcome = _failed_outcome(
                selected.service,
                _service_command_for_action(action_id),
                f"No Service Admin facade is configured for {action_id}",
                timeout_sec=timeout_sec,
            )
        elif action_id == "pause":
            outcome = await self._admin_facade.execute(
                selected.service,
                ServiceCommand.PAUSE,
                parameters=_admin_resource_parameters(selected),
                timeout_sec=timeout_sec,
            )
        elif action_id == "resume":
            outcome = await self._admin_facade.execute(
                selected.service,
                ServiceCommand.RESUME,
                parameters=_admin_resource_parameters(selected),
                timeout_sec=timeout_sec,
            )
        elif action_id == "shutdown":
            outcome = await self._admin_facade.execute(
                selected.service,
                ServiceCommand.SHUTDOWN,
                parameters=_admin_resource_parameters(selected),
                timeout_sec=timeout_sec,
            )
        elif action_id == "tag":
            tag = (tag_name or self._config.tag_value).strip()
            if not tag:
                raise ValueError("tag_name is required for Record tag commands")
            parameters = dict(_admin_resource_parameters(selected))
            parameters.update({"tag_name": tag, "description": description})
            outcome = await self._admin_facade.execute(
                selected.service,
                ServiceCommand.TAG,
                parameters=parameters,
                timeout_sec=timeout_sec,
            )
        else:
            raise ValueError(f"Unsupported Record tab action: {action_id}")

        observed_state = _observed_state_for_action(action_id)
        if outcome.ok and observed_state:
            payload = dict(outcome.payload)
            payload["observed_state"] = observed_state
            if action_id == "shutdown":
                payload["process_exit_observed"] = await self._wait_for_local_shutdown_exit(selected)
            outcome = replace(outcome, payload=payload)

        self._append_history(outcome)
        if action_id == "shutdown":
            self._graceful_shutdown_failed = not outcome.ok
        return outcome

    async def _wait_for_local_shutdown_exit(self, selected: ServiceProcessCandidate) -> bool:
        if not selected.owns_process:
            return False
        launch_id = selected.launch_id or selected.candidate_id
        if not launch_id:
            return False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._LOCAL_SHUTDOWN_REAP_TIMEOUT_SEC
        while True:
            launch = self._process_manager.refresh(launch_id)
            if launch is None:
                return True
            if launch.state in {ServiceProcessLaunchState.EXITED, ServiceProcessLaunchState.START_FAILED}:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(self._LOCAL_SHUTDOWN_REAP_POLL_SEC)

    def _append_history(self, outcome: ServiceCommandOutcome) -> None:
        self._command_history = self._command_history + (outcome,)

    def _target_service(self) -> ServiceInstanceRef:
        if self._config.service is not None:
            return self._config.service
        launches = self._process_manager.launches()
        for launch in launches:
            if launch.identity.intent.kind == ServiceKind.RECORDING:
                return launch.identity.service_ref
        return ServiceInstanceRef(ServiceKind.RECORDING, "", 0, 0)

    def _selection(
            self,
            service: ServiceInstanceRef,
            monitoring_snapshots: Iterable[MonitoringSnapshot],
    ) -> ServiceCandidateSelection:
        if not service.name:
            return ServiceCandidateSelection()
        primary = self._process_manager.candidate_selection(
            service,
            monitoring_snapshots=monitoring_snapshots,
            selected_candidate_id=self._config.selected_candidate_id,
            display_label=self._config.display_label,
        )
        # Include candidates from other Recording Services discovered via
        # monitoring on the same domain so ALL instances appear in the dropdown.
        # Determine which cache keys are already represented by the primary
        # service (direct key OR the fallback key used by domain-matching).
        seen_keys = self._primary_service_cache_keys(service)
        extra_candidates: List = []
        for cached_key, cached_by_kind in self._latest_monitoring_by_service.items():
            if cached_key in seen_keys or not cached_by_kind:
                continue
            sample = next(iter(cached_by_kind.values()))
            if (sample.service.kind != ServiceKind.RECORDING
                    or sample.service.monitoring_domain_id != service.monitoring_domain_id):
                continue
            seen_keys.add(cached_key)
            extra_snapshots = tuple(cached_by_kind.values())
            extra_sel = self._process_manager.candidate_selection(
                sample.service,
                monitoring_snapshots=extra_snapshots,
                selected_candidate_id="",
                display_label=self._config.display_label,
            )
            extra_candidates.extend(extra_sel.candidates)
        if not extra_candidates:
            return primary
        all_candidates = list(primary.candidates) + extra_candidates
        all_candidates.sort(key=lambda c: (not c.alive, -c.confidence, -c.last_seen_at, c.candidate_id))
        return ServiceCandidateSelection(
            candidates=tuple(all_candidates),
            selected_candidate_id=self._config.selected_candidate_id,
        )

    def _primary_service_cache_keys(self, service: ServiceInstanceRef) -> set:
        """Return cache keys that represent the primary tracked service.

        Includes the direct key and any fallback key used by the domain-matching
        logic in _monitoring_snapshots_for_service.
        """
        keys = {service.key}
        # If the direct key has no data, find which cache key the fallback uses.
        if not self._latest_monitoring_by_service.get(service.key):
            for cached_key, cached_by_kind in self._latest_monitoring_by_service.items():
                if not cached_by_kind:
                    continue
                sample = next(iter(cached_by_kind.values()))
                if (sample.service.kind == service.kind
                        and sample.service.monitoring_domain_id == service.monitoring_domain_id):
                    keys.add(cached_key)
                    break
        return keys

    def _monitoring_services(self, service: ServiceInstanceRef) -> Tuple[ServiceInstanceRef, ...]:
        services: List[ServiceInstanceRef] = []
        if service.name:
            services.append(service)
        for launch in self._process_manager.launches():
            if launch.identity.intent.kind == ServiceKind.RECORDING:
                services.append(launch.identity.service_ref)
        # When no named service is known, create a discovery probe on the
        # configured monitoring domain so we can detect externally-launched
        # Recording Services via their monitoring publications.
        if not services:
            probe = ServiceInstanceRef(
                kind=ServiceKind.RECORDING,
                name="",
                admin_domain_id=self._config.launch_admin_domain_id,
                monitoring_domain_id=self._config.launch_monitoring_domain_id,
            )
            services.append(probe)
        unique: Dict[str, ServiceInstanceRef] = {}
        for item in services:
            unique.setdefault(item.key, item)
        return tuple(unique.values())

    async def _take_monitoring_updates(
            self,
            services: Iterable[ServiceInstanceRef],
    ) -> Tuple[MonitoringSnapshot, ...]:
        if self._monitoring_facade is None:
            return ()
        updates: List[MonitoringSnapshot] = []
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

    def _discover_service_from_cache(
            self,
            probe: ServiceInstanceRef,
    ) -> Optional[ServiceInstanceRef]:
        """Find a Recording Service identity from cached monitoring data.

        When the GUI starts without a known service, monitoring data arriving
        on the configured domain reveals externally-launched services.  This
        returns the first discovered Recording Service ref so the controller
        can adopt it for subsequent operations.
        """
        for cached_key, cached_by_kind in self._latest_monitoring_by_service.items():
            if not cached_by_kind:
                continue
            sample = next(iter(cached_by_kind.values()))
            if sample.service.kind != ServiceKind.RECORDING:
                continue
            if sample.service.monitoring_domain_id != probe.monitoring_domain_id:
                continue
            # Found a Recording Service on the expected monitoring domain.
            if sample.service.name:
                return sample.service
        return None

    def _monitoring_snapshots_for_service(self, service: ServiceInstanceRef) -> Tuple[MonitoringSnapshot, ...]:
        by_kind = self._latest_monitoring_by_service.get(service.key, {})
        remap_service = False
        if not by_kind and service.name:
            # Monitoring data may be cached under the service's actual reported
            # name (e.g. the RS config name "template") rather than the
            # GUI control name ("RecordingService_<guid>").  Fall back to
            # matching by kind + monitoring domain and remap the service ref so
            # downstream candidate selection sees the correct identity.
            for cached_key, cached_by_kind in self._latest_monitoring_by_service.items():
                if not cached_by_kind:
                    continue
                sample_snapshot = next(iter(cached_by_kind.values()))
                if (sample_snapshot.service.kind == service.kind
                        and sample_snapshot.service.monitoring_domain_id == service.monitoring_domain_id):
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

    def _launch_view(self) -> RecordLaunchViewModel:
        return RecordLaunchViewModel(
            label=self._config.launch_label,
            config_paths=self._config.launch_config_paths,
            available_config_names=_recording_config_names(self._config.launch_config_paths),
            config_name=self._config.launch_config_name,
            storage_format=self._config.launch_storage_format,
            data_domain_id=self._config.launch_data_domain_id,
            admin_domain_id=self._config.launch_admin_domain_id,
            monitoring_domain_id=self._config.launch_monitoring_domain_id,
            topic_allow=self._config.launch_topic_allow,
            topic_deny=self._config.launch_topic_deny,
            log_directory=self._config.launch_log_directory,
            verbosity=self._config.launch_verbosity,
            executable=self._config.launch_executable,
            working_dir=self._config.launch_working_dir,
            extra_args=self._config.launch_extra_args,
        )


def _service_command_for_action(action_id: str) -> ServiceCommand:
    if action_id == "pause":
        return ServiceCommand.PAUSE
    if action_id == "resume":
        return ServiceCommand.RESUME
    if action_id == "shutdown":
        return ServiceCommand.SHUTDOWN
    if action_id == "tag":
        return ServiceCommand.TAG
    raise ValueError(f"Unsupported Record tab action: {action_id}")


def _observed_state_for_action(action_id: str) -> str:
    if action_id == "pause":
        return "PAUSED"
    if action_id == "resume":
        return "RUNNING"
    if action_id == "shutdown":
        return "SHUTDOWN"
    return ""


def _apply_command_state_override(
        selection: ServiceCandidateSelection,
        command_history: Tuple[ServiceCommandOutcome, ...],
) -> ServiceCandidateSelection:
    if not selection.candidates or not command_history:
        return selection
    latest = command_history[-1]
    if not latest.ok:
        return selection
    observed_state = str(latest.payload.get("observed_state", "")).strip()
    if not observed_state:
        return selection
    request_service = latest.request.service
    updated = []
    changed = False
    for candidate in selection.candidates:
        if candidate.service.key == request_service.key:
            if (
                    observed_state.upper() == "SHUTDOWN"
                    and candidate.owns_process
                    and not candidate.alive
                    and str(candidate.observed_state).strip().lower() in {"exited", "start_failed"}
            ):
                updated.append(candidate)
            else:
                updated.append(replace(candidate, observed_state=observed_state))
            changed = True
        else:
            updated.append(candidate)
    if not changed:
        return selection
    return ServiceCandidateSelection(
        candidates=tuple(updated),
        selected_candidate_id=selection.selected_candidate_id,
    )


def _admin_resource_parameters(candidate) -> dict:
    resource_name = str(candidate.details.get("admin_resource_name", ""))
    return {"admin_resource_name": resource_name} if resource_name else {}


def _failed_outcome(
        service: ServiceInstanceRef,
        command: ServiceCommand,
        message: str,
        timeout_sec: Optional[float] = None,
) -> ServiceCommandOutcome:
    return ServiceCommandOutcome(
        request=ServiceCommandRequest(
            service=service,
            command=command,
            timeout_sec=timeout_sec,
        ),
        status=CommandStatus.FAILED,
        message=message,
    )


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


def _normalize_record_extra_arg(arg: str) -> str:
    prefix = "-DREC_SESSION_NAME="
    text = str(arg).strip()
    if not text.startswith(prefix):
        return text
    session_name = re.sub(r"[^0-9A-Za-z_]+", "_", text[len(prefix):].strip())
    session_name = re.sub(r"_+", "_", session_name).strip("_") or "recording_session"
    return f"{prefix}{session_name}"


def _record_storage_format_ui(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"JSON", "JSON_SQLITE"}:
        return "JSON"
    return "XCDR"


def _record_storage_format_env(value: object) -> str:
    return "JSON_SQLITE" if _record_storage_format_ui(value) == "JSON" else "XCDR_AUTO"


def _record_filename_expression(storage_format_env: str) -> str:
    format_tag = "json" if str(storage_format_env).strip().upper() == "JSON_SQLITE" else "xcdr"
    return f"data_{format_tag}_%auto:0-9%.db"


def _record_log_directory(base_log_directory: str, storage_format_env: str) -> str:
    format_tag = "json" if str(storage_format_env).strip().upper() == "JSON_SQLITE" else "xcdr"
    normalized = str(base_log_directory).strip() or "services/rs_gui/log_data"
    trimmed = normalized.rstrip("/\\")
    if os.path.basename(trimmed) == format_tag:
        return trimmed
    return os.path.join(trimmed, format_tag)


def _merge_monitoring_details(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if key == "topics":
            merged[key] = _merge_topics(merged.get(key), value)
            continue
        merged[key] = value
    return merged


def _merge_topics(existing: Any, incoming: Any) -> List[str]:
    def _to_topic_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            raw_values = value
        else:
            raw_values = (value,)
        return [str(item).strip() for item in raw_values if str(item).strip()]

    combined: List[str] = []
    seen = set()
    for topic_name in _to_topic_list(existing) + _to_topic_list(incoming):
        if topic_name in seen:
            continue
        seen.add(topic_name)
        combined.append(topic_name)
    return combined


def _int_payload(payload: Mapping[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    return int(str(value).strip())


def _recording_config_names(config_paths: Iterable[str]) -> Tuple[str, ...]:
    names = []
    seen = set()
    for path in config_paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        for element in root.iter():
            tag = str(element.tag).split("}")[-1]
            if tag != "recording_service":
                continue
            name = str(element.get("name", "")).strip()
            if name and name not in seen:
                names.append(name)
                seen.add(name)
    return tuple(names)
