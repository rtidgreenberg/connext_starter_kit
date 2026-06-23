"""Compose service process candidates from launch, discovery, and monitoring evidence."""

from dataclasses import replace
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ..discovery import DiscoveredEndpoint
from .control import (
    ServiceCandidateSelection,
    ServiceCandidateSource,
    ServiceControlIdentity,
    ServiceProcessCandidate,
    service_admin_target_key,
)
from .models import MonitoringSnapshot, ServiceInstanceRef


SYS_INFO_HOSTNAME = "dds.sys_info.hostname"
SYS_INFO_PROCESS_ID = "dds.sys_info.process_id"
SYS_INFO_USERNAME = "dds.sys_info.username"
SYS_INFO_EXECUTABLE = "dds.sys_info.executable_filepath"
SYS_INFO_TARGET = "dds.sys_info.target"


def candidate_from_control_identity(
        identity: ServiceControlIdentity,
        launch_id: str = "",
        pid: Optional[int] = None,
        hostname: str = "",
        observed_state: str = "starting",
        metrics: Optional[Mapping[str, Any]] = None,
        details: Optional[Mapping[str, Any]] = None,
        observed_at: Optional[float] = None,
) -> ServiceProcessCandidate:
    """Build a GUI-launched service candidate from its runtime control identity."""

    candidate_id = launch_id or f"launch:{identity.service_ref.key}"
    candidate_details = {
        "control_name": identity.control_name,
        "session_guid": identity.session_guid,
    }
    candidate_details.update(dict(details or {}))
    timestamp = time.time() if observed_at is None else float(observed_at)
    return ServiceProcessCandidate(
        candidate_id=candidate_id,
        service=identity.service_ref,
        source=ServiceCandidateSource.GUI_LAUNCH,
        display_label=identity.intent.label,
        launch_id=launch_id,
        pid=pid,
        hostname=hostname,
        config_paths=identity.intent.config_paths,
        observed_state=observed_state,
        metrics=metrics or {},
        details=candidate_details,
        owns_process=True,
        confidence=1.0,
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    )


def candidate_from_monitoring_snapshot(
        snapshot: MonitoringSnapshot,
        display_label: str = "",
) -> ServiceProcessCandidate:
    """Build a service candidate from normalized RTI service monitoring data."""

    details = dict(snapshot.details)
    application_guid = str(details.get("application_guid", ""))
    process_id = _optional_int(details.get("process_id"))
    hostname = str(details.get("host_name", ""))
    identity = application_guid or _host_pid_key(hostname, process_id) or snapshot.service.key
    return ServiceProcessCandidate(
        candidate_id=f"monitoring:{service_admin_target_key(snapshot.service)}:{identity}",
        service=snapshot.service,
        source=ServiceCandidateSource.MONITORING,
        display_label=display_label,
        pid=process_id,
        hostname=hostname,
        application_guid=application_guid,
        config_paths=snapshot.service.config_paths,
        observed_state=snapshot.state,
        metrics=snapshot.metrics,
        details=details,
        alive=_state_is_alive(snapshot.state),
        confidence=0.85 if application_guid or process_id is not None else 0.5,
        first_seen_at=snapshot.observed_at,
        last_seen_at=snapshot.observed_at,
    )


def candidates_from_discovered_endpoints(
        service: ServiceInstanceRef,
        endpoints: Iterable[DiscoveredEndpoint],
        display_label: str = "",
) -> Tuple[ServiceProcessCandidate, ...]:
    """Aggregate discovered endpoints into process candidates by participant key."""

    grouped: Dict[str, list] = {}
    for endpoint in endpoints:
        if not endpoint.alive:
            continue
        key = endpoint.participant_key or endpoint.endpoint_key
        grouped.setdefault(key, []).append(endpoint)

    candidates = []
    for key, endpoint_group in sorted(grouped.items()):
        endpoints_tuple = tuple(endpoint_group)
        first = endpoints_tuple[0]
        properties = dict(first.participant_properties)
        process_id = _optional_int(properties.get(SYS_INFO_PROCESS_ID))
        hostname = str(properties.get(SYS_INFO_HOSTNAME, ""))
        details = {
            "endpoint_count": len(endpoints_tuple),
            "endpoint_keys": sorted(endpoint.endpoint_key for endpoint in endpoints_tuple),
            "topic_names": sorted({endpoint.topic_name for endpoint in endpoints_tuple}),
            "participant_properties": properties,
        }
        candidates.append(ServiceProcessCandidate(
            candidate_id=f"discovery:{service_admin_target_key(service)}:{key}",
            service=service,
            source=ServiceCandidateSource.DISCOVERY,
            display_label=display_label,
            pid=process_id,
            hostname=hostname,
            participant_key=first.participant_key,
            participant_name=first.participant_name,
            config_paths=service.config_paths,
            observed_state="discovered",
            details=details,
            alive=True,
            confidence=0.7 if hostname or process_id is not None else 0.4,
            first_seen_at=min(endpoint.observed_at for endpoint in endpoints_tuple),
            last_seen_at=max(endpoint.observed_at for endpoint in endpoints_tuple),
        ))
    return tuple(candidates)


def build_service_candidate_selection(
        service: ServiceInstanceRef,
        launch_candidates: Iterable[ServiceProcessCandidate] = (),
        monitoring_snapshots: Iterable[MonitoringSnapshot] = (),
        discovery_endpoints: Iterable[DiscoveredEndpoint] = (),
        selected_candidate_id: str = "",
        display_label: str = "",
) -> ServiceCandidateSelection:
    """Merge available evidence into a selector snapshot for one logical service.

    Candidate Merge Heuristics
    --------------------------
    Evidence arrives from three independent sources, processed in this order:

    1. Monitoring — primary authority for instance name, state, PID, and metrics.
    2. Discovery — supplies participant identity and endpoint-level details.
    3. GUI launch — enriches matching rows with ownership and local process state.

    Two candidates are considered the same process if they share ANY identity
    key: launch_id, host+PID pair, participant_key, or application_guid
    (see ``_identity_keys``).

    Field precedence when combining (``_combine_candidates``):
    - PID, launch_id, config_paths: prefer the first non-None source.
        - observed_state: local exit wins unconditionally; otherwise monitoring
            lifecycle states win over generic monitoring/discovery/local process
            states; otherwise the most-recent non-"unknown" value wins.
    - alive: False if ANY evidence reports a locally-owned exit.
    - confidence: max of all sources.
    - metrics/details: dict-merge; later sources overwrite earlier keys.
    - timestamps: first_seen_at = min, last_seen_at = max across all evidence.

    If evidence has no overlapping identity keys but exactly one candidate for
    the same service target exists, it is merged into that row
    (``allow_unique_service_target`` fallback).

    Final ordering: alive first, then descending confidence, descending
    last_seen_at, then candidate_id for stability.
    """

    candidates = []
    for snapshot in monitoring_snapshots:
        if _same_service_target(snapshot.service, service):
            candidates = _merge_candidate(
                candidates,
                candidate_from_monitoring_snapshot(snapshot, display_label=display_label),
                allow_unique_service_target=True,
            )
    for candidate in candidates_from_discovered_endpoints(
            service,
            discovery_endpoints,
            display_label=display_label,
    ):
        candidates = _merge_candidate(candidates, candidate)
    for candidate in launch_candidates:
        if _same_service_target(candidate.service, service):
            candidates = _merge_candidate(
                candidates,
                candidate,
                allow_unique_service_target=True,
            )

    ordered = tuple(sorted(
        candidates,
        key=lambda candidate: (
            not candidate.alive,
            -candidate.confidence,
            -candidate.last_seen_at,
            candidate.candidate_id,
        ),
    ))
    return ServiceCandidateSelection(
        candidates=ordered,
        selected_candidate_id=selected_candidate_id,
    )


def _merge_candidate(
        candidates: Iterable[ServiceProcessCandidate],
        incoming: ServiceProcessCandidate,
        allow_unique_service_target: bool = False,
) -> list:
    merged = list(candidates)
    incoming_keys = _identity_keys(incoming)
    for index, existing in enumerate(merged):
        if incoming_keys.intersection(_identity_keys(existing)):
            merged[index] = _combine_candidates(existing, incoming)
            return merged
    if allow_unique_service_target:
        target_indexes = [
            index for index, existing in enumerate(merged)
            if _same_service_target(existing.service, incoming.service)
            and not (
                existing.source == ServiceCandidateSource.GUI_LAUNCH
                and incoming.source == ServiceCandidateSource.GUI_LAUNCH
            )
        ]
        if len(target_indexes) == 1:
            index = target_indexes[0]
            merged[index] = _combine_candidates(merged[index], incoming)
            return merged
    merged.append(incoming)
    return merged


def _combine_candidates(
        existing: ServiceProcessCandidate,
        incoming: ServiceProcessCandidate,
) -> ServiceProcessCandidate:
    latest = incoming if incoming.last_seen_at >= existing.last_seen_at else existing
    local_exit = _local_exit_candidate(existing, incoming)
    monitoring_state = _monitoring_state_candidate(existing, incoming)
    metrics = dict(existing.metrics)
    metrics.update(dict(incoming.metrics))
    details = dict(existing.details)
    details.update(dict(incoming.details))
    sources = sorted({
        str(existing.source.value),
        str(incoming.source.value),
        *details.get("evidence_sources", ()),
    })
    details["evidence_sources"] = sources
    return replace(
        existing,
        display_label=existing.display_label or incoming.display_label,
        launch_id=existing.launch_id or incoming.launch_id,
        pid=_preferred_pid(existing, incoming),
        hostname=existing.hostname or incoming.hostname,
        participant_key=existing.participant_key or incoming.participant_key,
        participant_name=existing.participant_name or incoming.participant_name,
        application_guid=existing.application_guid or incoming.application_guid,
        config_paths=existing.config_paths or incoming.config_paths,
        observed_state=(
            local_exit.observed_state
            if local_exit is not None
            else
            monitoring_state.observed_state
            if monitoring_state is not None
            else
            latest.observed_state
            if latest.observed_state != "unknown"
            else existing.observed_state
        ),
        metrics=metrics,
        details=details,
        alive=False if local_exit is not None else latest.alive,
        owns_process=existing.owns_process or incoming.owns_process,
        confidence=max(existing.confidence, incoming.confidence),
        first_seen_at=min(existing.first_seen_at, incoming.first_seen_at),
        last_seen_at=max(existing.last_seen_at, incoming.last_seen_at),
    )


def _preferred_pid(
        existing: ServiceProcessCandidate,
        incoming: ServiceProcessCandidate,
) -> Optional[int]:
    for candidate in (incoming, existing):
        if candidate.owns_process and candidate.pid is not None:
            return candidate.pid
    if existing.pid is not None:
        return existing.pid
    return incoming.pid


def _local_exit_candidate(
        existing: ServiceProcessCandidate,
        incoming: ServiceProcessCandidate,
) -> Optional[ServiceProcessCandidate]:
    for candidate in (incoming, existing):
        if candidate.owns_process and not candidate.alive:
            return candidate
    return None


def _monitoring_state_candidate(
        existing: ServiceProcessCandidate,
        incoming: ServiceProcessCandidate,
) -> Optional[ServiceProcessCandidate]:
    candidates = tuple(
        candidate for candidate in (existing, incoming)
        if candidate.source == ServiceCandidateSource.MONITORING
        and _state_rank(candidate.observed_state) > 0
    )
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (_state_rank(candidate.observed_state), candidate.last_seen_at))


def _state_rank(state: str) -> int:
    normalized = str(state).strip().upper()
    if normalized in {"ENABLED", "STARTED", "RUNNING", "PAUSED", "STOPPED", "DISABLED", "INVALID"}:
        return 2
    if normalized in {"CONFIGURED", "OBSERVED"}:
        return 1
    return 0


def _identity_keys(candidate: ServiceProcessCandidate) -> set:
    keys = {candidate.candidate_id}
    if candidate.launch_id:
        keys.add(f"launch:{candidate.launch_id}")
    if candidate.application_guid:
        keys.add(f"app-guid:{candidate.application_guid}")
    if candidate.participant_key:
        keys.add(f"participant:{candidate.participant_key}")
    host_pid = _host_pid_key(candidate.hostname, candidate.pid)
    if host_pid:
        keys.add(host_pid)
    return keys


def _host_pid_key(hostname: str, pid: Optional[int]) -> str:
    if not hostname or pid is None:
        return ""
    return f"host-pid:{hostname.lower()}:{int(pid)}"


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _same_service_target(left: ServiceInstanceRef, right: ServiceInstanceRef) -> bool:
    return service_admin_target_key(left) == service_admin_target_key(right)


def _state_is_alive(state: str) -> bool:
    return str(state).strip().lower() not in {"stopped", "deleted", "not_alive", "dead"}
