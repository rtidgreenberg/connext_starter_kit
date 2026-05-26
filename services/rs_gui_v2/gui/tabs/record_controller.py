"""Record tab controller that wires app-core service snapshots to GUI views."""

from dataclasses import dataclass, field, replace
import time
from typing import Iterable, Optional, Tuple

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
    ServiceMonitoringFacade,
    ServiceProcessManager,
)

from .record_tab import RecordTabViewModel, build_record_tab_view_model


@dataclass(frozen=True)
class RecordTabControllerConfig:
    """Runtime wiring options for the Record tab controller."""

    service: Optional[ServiceInstanceRef] = None
    display_label: str = "Recording Service"
    local_hostnames: Tuple[str, ...] = field(default_factory=tuple)
    selected_candidate_id: str = ""
    tag_value: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hostnames", tuple(str(name) for name in self.local_hostnames))


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
            now=self._clock(),
        )

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
