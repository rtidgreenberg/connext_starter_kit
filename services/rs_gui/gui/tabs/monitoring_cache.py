"""Shared monitoring-cache helpers for Record and Replay tab controllers."""

from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from app_core.services import MonitoringSnapshot, MonitoringSnapshotKind, ServiceInstanceRef


MonitoringCache = Dict[str, Dict[MonitoringSnapshotKind, MonitoringSnapshot]]
MonitoringDetailMerger = Callable[[Mapping[str, Any], Mapping[str, Any]], Dict[str, Any]]


async def take_monitoring_updates(monitoring_facade, services: Iterable[ServiceInstanceRef]) -> Tuple[MonitoringSnapshot, ...]:
    if monitoring_facade is None:
        return ()
    updates = []
    for service in services:
        updates.extend(await monitoring_facade.take_available(service))
    return tuple(updates)


def cache_monitoring_updates(
        cache: MonitoringCache,
        updates: Iterable[MonitoringSnapshot],
        merge_details: MonitoringDetailMerger,
) -> None:
    for snapshot in updates:
        by_kind = cache.setdefault(snapshot.service.key, {})
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
                details=merge_details(older.details, newer.details),
                observed_at=newer.observed_at,
            )
            continue
        if snapshot.observed_at >= current.observed_at:
            by_kind[snapshot.kind] = snapshot


def discover_service_from_cache(
        cache: MonitoringCache,
        probe: ServiceInstanceRef,
) -> Optional[ServiceInstanceRef]:
    for cached_by_kind in cache.values():
        if not cached_by_kind:
            continue
        sample = next(iter(cached_by_kind.values()))
        if sample.service.kind != probe.kind:
            continue
        if sample.service.monitoring_domain_id != probe.monitoring_domain_id:
            continue
        if sample.service.name:
            return sample.service
    return None


def monitoring_snapshots_for_service(
        cache: MonitoringCache,
        service: ServiceInstanceRef,
) -> Tuple[MonitoringSnapshot, ...]:
    by_kind = cache.get(service.key, {})
    remap_service = False
    if not by_kind and service.name:
        for cached_by_kind in cache.values():
            if not cached_by_kind:
                continue
            sample = next(iter(cached_by_kind.values()))
            if (sample.service.kind == service.kind
                    and sample.service.monitoring_domain_id == service.monitoring_domain_id):
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
                kind=snapshot.kind,
                state=snapshot.state,
                metrics=snapshot.metrics,
                details=snapshot.details,
                observed_at=snapshot.observed_at,
            )
            for snapshot in snapshots
        )
    return snapshots