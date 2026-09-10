# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Facade for live Converter Service interaction via app-core."""

from dataclasses import dataclass
from typing import Optional, Protocol

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
)


class ConverterServiceMonitoringClient(Protocol):
    """Protocol for monitoring Converter Service state (via RtiDdsMonitoring or fakes)."""

    async def get_monitoring_snapshot(
            self,
            service_ref: ServiceInstanceRef,
    ) -> Optional[MonitoringSnapshot]:
        """Fetch latest monitoring snapshot from Converter Service."""
        ...


@dataclass(frozen=True)
class ConverterServiceConfig:
    """Configuration for interacting with live Converter Service."""

    service: Optional[ServiceInstanceRef] = None
    admin_domain_id: int = 0
    monitoring_domain_id: int = 0


class ConverterServiceFacade:
    """Provides live Converter Service admin and monitoring capabilities."""

    def __init__(
            self,
            admin_facade: Optional[ServiceAdminFacade] = None,
            monitoring_facade: Optional[ServiceMonitoringFacade] = None,
            config: Optional[ConverterServiceConfig] = None,
    ) -> None:
        self._admin_facade = admin_facade
        self._monitoring_facade = monitoring_facade
        self._config = config or ConverterServiceConfig()

    @property
    def service(self) -> Optional[ServiceInstanceRef]:
        return self._config.service

    async def is_service_ready(self) -> bool:
        """Check if Converter Service Admin endpoint is ready."""
        if not self._admin_facade or not self._config.service:
            return False
        readiness = await self._admin_facade.get_readiness(self._config.service)
        return readiness.status == AdminReadinessStatus.READY

    async def get_monitoring_snapshot(self) -> Optional[MonitoringSnapshot]:
        """Fetch latest monitoring snapshot from Converter Service."""
        if not self._monitoring_facade or not self._config.service:
            return None
        return await self._monitoring_facade.get_latest_snapshot(self._config.service)

    async def send_command(
            self,
            command: ServiceCommand,
            parameters: dict,
    ) -> ServiceCommandOutcome:
        """Send a command to the Converter Service and capture the response."""
        if not self._admin_facade or not self._config.service:
            raise ValueError("Converter Service not available")
        request = ServiceCommandRequest(
            command=command,
            parameters=parameters,
            timeout_sec=30.0,
        )
        return await self._admin_facade.execute_command(
            self._config.service,
            request,
        )
