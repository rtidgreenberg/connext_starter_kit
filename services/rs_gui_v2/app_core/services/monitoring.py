"""DDS-free service monitoring protocols and facade for rs_gui_v2."""

from typing import AsyncIterator, Optional, Protocol

from .models import MonitoringSnapshot, ServiceInstanceRef, ServiceStateSnapshot


class ServiceMonitoringClient(Protocol):
    """Transport-specific monitoring client contract used by the facade."""

    async def latest_snapshot(self, service: ServiceInstanceRef) -> Optional[MonitoringSnapshot]:
        """Return the latest normalized monitoring snapshot, if one is available."""

    async def snapshots(self, service: ServiceInstanceRef) -> AsyncIterator[MonitoringSnapshot]:
        """Yield normalized monitoring snapshots for a service."""


class ServiceMonitoringFacade:
    """Monitoring facade that composes normalized snapshots into service state."""

    def __init__(self, client: ServiceMonitoringClient) -> None:
        self._client = client

    async def latest_snapshot(
            self, service: ServiceInstanceRef
    ) -> Optional[MonitoringSnapshot]:
        return await self._client.latest_snapshot(service)

    async def latest_state(self, service: ServiceInstanceRef) -> ServiceStateSnapshot:
        state = ServiceStateSnapshot(service=service)
        snapshot = await self.latest_snapshot(service)
        if snapshot is None:
            return state
        return state.with_monitoring(snapshot)

    async def snapshots(self, service: ServiceInstanceRef) -> AsyncIterator[MonitoringSnapshot]:
        async for snapshot in self._client.snapshots(service):
            yield snapshot