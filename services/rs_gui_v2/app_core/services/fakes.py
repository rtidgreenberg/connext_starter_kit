"""Deterministic fake service clients for rs_gui_v2 headless tests."""

from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from ..events import CommandStatus
from .models import (
    AdminReadiness,
    AdminReadinessStatus,
    MonitoringSnapshot,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
)


class FakeServiceAdminClient:
    """In-memory admin client with configurable readiness and command outcomes."""

    def __init__(self) -> None:
        self.requests: List[ServiceCommandRequest] = []
        self._readiness: Dict[str, AdminReadiness] = {}
        self._outcomes: Dict[str, Deque[ServiceCommandOutcome]] = defaultdict(deque)

    def set_readiness(self, readiness: AdminReadiness) -> None:
        self._readiness[readiness.service.key] = readiness

    def queue_outcome(self, outcome: ServiceCommandOutcome) -> None:
        key = self._outcome_key(outcome.request)
        self._outcomes[key].append(outcome)

    async def check_readiness(self, service: ServiceInstanceRef) -> AdminReadiness:
        return self._readiness.get(
            service.key,
            AdminReadiness(
                service=service,
                status=AdminReadinessStatus.READY,
                matched_request_writers=1,
                matched_reply_readers=1,
                message="fake admin ready",
            ),
        )

    async def send_command(self, request: ServiceCommandRequest) -> ServiceCommandOutcome:
        self.requests.append(request)
        queued = self._outcomes.get(self._outcome_key(request))
        if queued:
            return queued.popleft()
        return ServiceCommandOutcome(
            request=request,
            status=CommandStatus.ACKNOWLEDGED,
            message="fake command acknowledged",
        )

    @staticmethod
    def _outcome_key(request: ServiceCommandRequest) -> str:
        return f"{request.service.key}:{request.command.value}"


class FakeServiceMonitoringClient:
    """In-memory monitoring client with ordered snapshots per service."""

    def __init__(self) -> None:
        self._snapshots: Dict[str, Deque[MonitoringSnapshot]] = defaultdict(deque)

    def push_snapshot(self, snapshot: MonitoringSnapshot) -> None:
        self._snapshots[snapshot.service.key].append(snapshot)

    async def latest_snapshot(self, service: ServiceInstanceRef) -> Optional[MonitoringSnapshot]:
        snapshots = self._snapshots.get(service.key)
        if not snapshots:
            return None
        return snapshots[-1]

    async def snapshots(self, service: ServiceInstanceRef):
        snapshots = self._snapshots.get(service.key, deque())
        while snapshots:
            yield snapshots.popleft()