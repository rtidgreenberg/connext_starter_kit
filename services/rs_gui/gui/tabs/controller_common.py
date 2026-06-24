"""Shared controller helpers for Record and Replay tabs."""

import asyncio
from typing import Dict, Iterable, Optional, Tuple

from app_core.services import (
    AdminReadiness,
    AdminReadinessStatus,
    ServiceCandidateSelection,
    ServiceInstanceRef,
    ServiceKind,
    ServiceProcessLaunchState,
    ServiceProcessCandidate,
)


def candidate_display_fields(
        candidate: ServiceProcessCandidate,
        now: float,
        default_label: str = "",
        precise_age: bool = False,
) -> Dict[str, object]:
    return {
        "label": candidate.display_label or default_label or candidate.service.name,
        "control_name": candidate.service.name,
        "source": candidate.source.value,
        "pid": "" if candidate.pid is None else str(candidate.pid),
        "hostname": candidate.hostname,
        "age": _candidate_age_text(now, candidate.last_seen_at, precise=precise_age),
        "confidence": f"{candidate.confidence:.2f}",
        "owned": candidate.owns_process,
    }


def candidate_has_duplicate_admin_target(
        selection: ServiceCandidateSelection,
        candidate_id: str,
        local_hostnames: Iterable[str],
        graceful_shutdown_failed: bool,
) -> bool:
    availability = selection.select(candidate_id).control_availability(
        local_hostnames=local_hostnames,
        graceful_shutdown_failed=graceful_shutdown_failed,
    )
    return availability.duplicate_admin_target


def resolve_target_service(
        configured_service: Optional[ServiceInstanceRef],
        process_manager,
        service_kind: ServiceKind,
        admin_domain_id: int = 0,
        monitoring_domain_id: int = 0,
        config_paths: Iterable[str] = (),
) -> ServiceInstanceRef:
    if configured_service is not None:
        return configured_service
    if process_manager is not None:
        for launch in process_manager.launches():
            if launch.identity.intent.kind == service_kind:
                return launch.identity.service_ref
    return ServiceInstanceRef(
        service_kind,
        "",
        admin_domain_id=admin_domain_id,
        monitoring_domain_id=monitoring_domain_id,
        config_paths=tuple(config_paths),
    )


def monitoring_services(
        service: ServiceInstanceRef,
        process_manager,
        service_kind: ServiceKind,
        admin_domain_id: int = 0,
        monitoring_domain_id: int = 0,
) -> Tuple[ServiceInstanceRef, ...]:
    services = []
    if service.name:
        services.append(service)
    if process_manager is not None:
        for launch in process_manager.launches():
            if launch.identity.intent.kind == service_kind:
                services.append(launch.identity.service_ref)
    if not services:
        services.append(ServiceInstanceRef(
            kind=service_kind,
            name="",
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=monitoring_domain_id,
        ))
    unique = {}
    for item in services:
        unique.setdefault(item.key, item)
    return tuple(unique.values())


async def readiness_for_service(admin_facade, service: ServiceInstanceRef, clock) -> Optional[AdminReadiness]:
    if not service.name:
        return None
    if admin_facade is None:
        return AdminReadiness(
            service=service,
            status=AdminReadinessStatus.UNKNOWN,
            message="Service Admin facade is not configured",
            checked_at=clock(),
        )
    return await admin_facade.readiness(service)


async def wait_for_local_shutdown_exit(
        process_manager,
        selected: ServiceProcessCandidate,
        timeout_sec: float,
        poll_sec: float,
) -> bool:
    if not selected.owns_process or process_manager is None:
        return False
    launch_id = selected.launch_id or selected.candidate_id
    if not launch_id:
        return False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec
    while True:
        launch = process_manager.refresh(launch_id)
        if launch is None:
            return True
        if launch.state in {ServiceProcessLaunchState.EXITED, ServiceProcessLaunchState.START_FAILED}:
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(poll_sec)


def _candidate_age_text(now: float, last_seen_at: float, precise: bool) -> str:
    if now <= 0 or last_seen_at <= 0:
        return "unknown"
    age = max(0.0, now - last_seen_at)
    if precise:
        return f"{age:.1f}s"
    if age < 1.0:
        return "now"
    if age < 60.0:
        return f"{int(age)}s"
    minutes = int(age // 60)
    return f"{minutes}m"