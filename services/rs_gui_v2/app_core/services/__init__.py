"""Service-facing models and facades owned by rs_gui_v2."""

from .admin import ServiceAdminClient, ServiceAdminFacade
from .candidates import (
    build_service_candidate_selection,
    candidate_from_control_identity,
    candidate_from_monitoring_snapshot,
    candidates_from_discovered_endpoints,
)
from .control import (
    ServiceCandidateSelection,
    ServiceCandidateSource,
    ServiceControlAvailability,
    ServiceControlIdentity,
    ServiceLaunchIntent,
    ServiceProcessCandidate,
    service_admin_target_key,
    service_label_prefix,
)
from .fakes import FakeServiceAdminClient, FakeServiceMonitoringClient
from .models import (
    AdminReadiness,
    AdminReadinessStatus,
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
    ServiceKind,
    ServiceStateSnapshot,
)
from .monitoring import ServiceMonitoringClient, ServiceMonitoringFacade

__all__ = [
    "AdminReadiness",
    "AdminReadinessStatus",
    "FakeServiceAdminClient",
    "FakeServiceMonitoringClient",
    "MonitoringSnapshot",
    "MonitoringSnapshotKind",
    "ServiceAdminClient",
    "ServiceAdminFacade",
    "ServiceCandidateSelection",
    "ServiceCandidateSource",
    "ServiceCommand",
    "ServiceCommandOutcome",
    "ServiceCommandRequest",
    "ServiceControlAvailability",
    "ServiceControlIdentity",
    "ServiceInstanceRef",
    "ServiceKind",
    "ServiceLaunchIntent",
    "ServiceMonitoringClient",
    "ServiceMonitoringFacade",
    "ServiceProcessCandidate",
    "ServiceStateSnapshot",
    "build_service_candidate_selection",
    "candidate_from_control_identity",
    "candidate_from_monitoring_snapshot",
    "candidates_from_discovered_endpoints",
    "service_admin_target_key",
    "service_label_prefix",
]