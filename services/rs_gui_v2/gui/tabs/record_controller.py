"""Record tab controller that wires app-core service snapshots to GUI views."""

from dataclasses import dataclass, field, replace
import os
import time
import xml.etree.ElementTree as ET
from typing import Iterable, Mapping, Optional, Tuple

from app_core.events import CommandStatus
from app_core.services import (
    AdminReadiness,
    AdminReadinessStatus,
    MonitoringSnapshot,
    ServiceAdminFacade,
    ServiceCandidateSelection,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceMonitoringFacade,
    ServiceProcessLaunch,
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
        "services/recording_service_config.xml",
        "dds/qos/DDS_QOS_PROFILES.xml",
    )
    launch_config_name: str = "deploy"
    launch_data_domain_id: int = 0
    launch_admin_domain_id: int = 0
    launch_monitoring_domain_id: int = 0
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
        object.__setattr__(self, "launch_extra_args", tuple(str(arg) for arg in self.launch_extra_args if str(arg).strip()))


class RecordTabController:
    """Build Record tab snapshots and dispatch selected service actions."""

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
        self._latest_monitoring: Tuple[MonitoringSnapshot, ...] = ()
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

    def set_tag_value(self, value: str) -> None:
        self._config = replace(self._config, tag_value=str(value))

    def select_candidate(self, candidate_id: str) -> None:
        self._config = replace(self._config, selected_candidate_id=str(candidate_id))

    def set_service(self, service: ServiceInstanceRef) -> None:
        self._config = replace(self._config, service=service)

    async def refresh_view(self) -> RecordTabViewModel:
        """Collect latest app-core snapshots and return a Record-tab view."""

        service = self._target_service()
        monitoring_snapshot = await self._latest_monitoring_snapshot(service)
        monitoring_snapshots = (monitoring_snapshot,) if monitoring_snapshot else ()
        self._latest_monitoring = monitoring_snapshots
        readiness = await self._readiness(service)
        self._last_readiness = readiness
        selection = self._selection(service, monitoring_snapshots)
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
        data_domain_id = _int_payload(payload, "data_domain_id", self._config.launch_data_domain_id)
        admin_domain_id = _int_payload(payload, "admin_domain_id", self._config.launch_admin_domain_id)
        monitoring_domain_id = _int_payload(payload, "monitoring_domain_id", self._config.launch_monitoring_domain_id)
        verbosity = str(payload.get("verbosity", self._config.launch_verbosity)).strip() or "ERROR:ERROR"
        executable = str(payload.get("executable", self._config.launch_executable)).strip()
        working_dir = str(payload.get("working_dir", self._config.launch_working_dir)).strip()
        extra_args = _extra_args_from_value(payload.get("extra_args", self._config.launch_extra_args))
        launch_extra_args = (
            f"-DDOMAIN_ID={data_domain_id}",
            f"-DADMIN_DOMAIN_ID={admin_domain_id}",
        ) + extra_args
        environment = {
            "DOMAIN_ID": str(data_domain_id),
            "ADMIN_DOMAIN_ID": str(admin_domain_id),
        }
        nddshome = os.environ.get("NDDSHOME", "")
        if nddshome:
            environment["NDDSHOME"] = nddshome
        license_file = os.environ.get("RTI_LICENSE_FILE", "")
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
            launch_data_domain_id=data_domain_id,
            launch_admin_domain_id=admin_domain_id,
            launch_monitoring_domain_id=monitoring_domain_id,
            launch_verbosity=verbosity,
            launch_executable=executable,
            launch_working_dir=working_dir,
            launch_extra_args=extra_args,
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

        self._append_history(outcome)
        if action_id == "shutdown":
            self._graceful_shutdown_failed = not outcome.ok
        return outcome

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
        return self._process_manager.candidate_selection(
            service,
            monitoring_snapshots=monitoring_snapshots,
            selected_candidate_id=self._config.selected_candidate_id,
            display_label=self._config.display_label,
        )

    async def _latest_monitoring_snapshot(
            self,
            service: ServiceInstanceRef,
    ) -> Optional[MonitoringSnapshot]:
        if self._monitoring_facade is None or not service.name:
            return None
        return await self._monitoring_facade.latest_snapshot(service)

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
            data_domain_id=self._config.launch_data_domain_id,
            admin_domain_id=self._config.launch_admin_domain_id,
            monitoring_domain_id=self._config.launch_monitoring_domain_id,
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
