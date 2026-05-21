"""DDS-free service admin protocols and facade for rs_gui_v2."""

from typing import Any, Mapping, Optional, Protocol

from .models import (
    AdminReadiness,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
)


class ServiceAdminClient(Protocol):
    """Transport-specific admin client contract used by the facade."""

    async def check_readiness(self, service: ServiceInstanceRef) -> AdminReadiness:
        """Return the current request/reply readiness for a service."""

    async def send_command(self, request: ServiceCommandRequest) -> ServiceCommandOutcome:
        """Dispatch a service command request and return its outcome."""


class ServiceAdminFacade:
    """Operator command facade independent of any DDS implementation module."""

    def __init__(self, client: ServiceAdminClient) -> None:
        self._client = client

    async def readiness(self, service: ServiceInstanceRef) -> AdminReadiness:
        return await self._client.check_readiness(service)

    async def execute(
            self,
            service: ServiceInstanceRef,
            command: ServiceCommand,
            parameters: Optional[Mapping[str, Any]] = None,
            timeout_sec: Optional[float] = None,
    ) -> ServiceCommandOutcome:
        request = ServiceCommandRequest(
            service=service,
            command=command,
            parameters=parameters or {},
            timeout_sec=timeout_sec,
        )
        return await self._client.send_command(request)

    async def pause(
            self, service: ServiceInstanceRef, timeout_sec: Optional[float] = None
    ) -> ServiceCommandOutcome:
        return await self.execute(service, ServiceCommand.PAUSE, timeout_sec=timeout_sec)

    async def resume(
            self, service: ServiceInstanceRef, timeout_sec: Optional[float] = None
    ) -> ServiceCommandOutcome:
        return await self.execute(service, ServiceCommand.RESUME, timeout_sec=timeout_sec)

    async def shutdown(
            self, service: ServiceInstanceRef, timeout_sec: Optional[float] = None
    ) -> ServiceCommandOutcome:
        return await self.execute(service, ServiceCommand.SHUTDOWN, timeout_sec=timeout_sec)

    async def tag(
            self,
            service: ServiceInstanceRef,
            tag_name: str,
            description: str = "",
            timeout_sec: Optional[float] = None,
    ) -> ServiceCommandOutcome:
        return await self.execute(
            service,
            ServiceCommand.TAG,
            parameters={"tag_name": tag_name, "description": description},
            timeout_sec=timeout_sec,
        )