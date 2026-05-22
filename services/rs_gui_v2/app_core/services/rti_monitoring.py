"""RTI infrastructure service monitoring adapter for rs_gui_v2.

This module owns the Connext DDS readers for service monitoring topics. The
DDS-free protocol and facade remain in `monitoring.py`.
"""

import asyncio
from dataclasses import dataclass
import importlib
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..connext_environment import (
    detect_nddshome,
    ensure_rti_license,
    license_setup_message,
    validate_generated_types,
)
from .models import MonitoringSnapshot, MonitoringSnapshotKind, ServiceInstanceRef


MONITORING_CONFIG_TOPIC = "rti/service/monitoring/config"
MONITORING_EVENT_TOPIC = "rti/service/monitoring/event"
MONITORING_PERIODIC_TOPIC = "rti/service/monitoring/periodic"

CONFIG_TYPE_NAME = "RTI::Service::Monitoring::Config"
EVENT_TYPE_NAME = "RTI::Service::Monitoring::Event"
PERIODIC_TYPE_NAME = "RTI::Service::Monitoring::Periodic"

CONFIG_QOS_PROFILE = "RecordingServiceMonitorProfiles::config_Profile"
EVENT_QOS_PROFILE = "RecordingServiceMonitorProfiles::event_Profile"
PERIODIC_QOS_PROFILE = "RecordingServiceMonitorProfiles::periodic_Profile"

RESOURCE_RECORDING_SERVICE = 20000
RESOURCE_RECORDING_TOPIC = 20003

ENTITY_STATE_NAMES = {
    0: "INVALID",
    1: "ENABLED",
    2: "DISABLED",
    3: "STARTED",
    4: "STOPPED",
    5: "RUNNING",
    6: "PAUSED",
}

_NO_DEFAULT = object()
_MISSING = object()


@dataclass(frozen=True)
class RtiServiceMonitoringConfig:
    """Filesystem and polling inputs for the RTI monitoring adapter."""

    xml_types_dir: str
    qos_file: str
    poll_interval_sec: float = 0.25


@dataclass
class _MonitoringTypes:
    config_type: Any
    event_type: Any
    periodic_type: Any
    config_qos: Any
    event_qos: Any
    periodic_qos: Any


@dataclass
class _MonitoringSession:
    participant: Any
    subscriber: Any
    readers: Dict[MonitoringSnapshotKind, Any]


class RtiServiceMonitoringClient:
    """Connext DDS implementation of the `ServiceMonitoringClient` protocol."""

    def __init__(
            self,
            config: Optional[RtiServiceMonitoringConfig] = None,
            dds_module: Any = None,
    ) -> None:
        self.config = config or default_rti_service_monitoring_config()
        self._dds = dds_module
        self._uses_real_connext = dds_module is None
        self._types: Optional[_MonitoringTypes] = None
        self._sessions: Dict[int, _MonitoringSession] = {}

    async def latest_snapshot(self, service: ServiceInstanceRef) -> Optional[MonitoringSnapshot]:
        snapshots = await self.take_available(service)
        return snapshots[-1] if snapshots else None

    async def snapshots(self, service: ServiceInstanceRef):
        while True:
            for snapshot in await self.take_available(service):
                yield snapshot
            await asyncio.sleep(self.config.poll_interval_sec)

    async def take_available(self, service: ServiceInstanceRef) -> List[MonitoringSnapshot]:
        return await self._run_blocking(self._take_available_sync, service)

    async def close(self) -> None:
        await self._run_blocking(self.close_sync)

    def close_sync(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            _safe_close(session.subscriber)
            participant = session.participant
            try:
                close_contained = getattr(participant, "close_contained_entities", None)
                if close_contained is not None:
                    close_contained()
            finally:
                _safe_close(participant)

    async def _run_blocking(self, function, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: function(*args))

    def _take_available_sync(self, service: ServiceInstanceRef) -> List[MonitoringSnapshot]:
        session = self._session_for_domain(service.monitoring_domain_id)
        snapshots: List[MonitoringSnapshot] = []
        for kind in (
                MonitoringSnapshotKind.CONFIG,
                MonitoringSnapshotKind.EVENT,
                MonitoringSnapshotKind.PERIODIC,
        ):
            reader = session.readers[kind]
            for sample in _reader_take(reader):
                snapshot = normalize_monitoring_sample(service, kind, sample)
                if snapshot is not None:
                    snapshots.append(snapshot)
        return snapshots

    def _session_for_domain(self, domain_id: int) -> _MonitoringSession:
        domain_id = int(domain_id)
        session = self._sessions.get(domain_id)
        if session is not None:
            return session

        self._load_connext_module()
        self._prepare_runtime_environment()
        self._configure_xtypes_policy()
        types = self._load_types()
        try:
            participant = self._dds.DomainParticipant(domain_id)
        except Exception as exc:
            nddshome = detect_nddshome()
            raise RuntimeError(
                f"Failed to create DDS DomainParticipant on domain {domain_id}. "
                f"{license_setup_message(nddshome)}"
            ) from exc

        dynamic_data = self._dds.DynamicData
        config_topic = dynamic_data.Topic(participant, MONITORING_CONFIG_TOPIC, types.config_type)
        event_topic = dynamic_data.Topic(participant, MONITORING_EVENT_TOPIC, types.event_type)
        periodic_topic = dynamic_data.Topic(
            participant, MONITORING_PERIODIC_TOPIC, types.periodic_type
        )
        subscriber = self._dds.Subscriber(participant)
        session = _MonitoringSession(
            participant=participant,
            subscriber=subscriber,
            readers={
                MonitoringSnapshotKind.CONFIG: dynamic_data.DataReader(
                    subscriber, config_topic, types.config_qos
                ),
                MonitoringSnapshotKind.EVENT: dynamic_data.DataReader(
                    subscriber, event_topic, types.event_qos
                ),
                MonitoringSnapshotKind.PERIODIC: dynamic_data.DataReader(
                    subscriber, periodic_topic, types.periodic_qos
                ),
            },
        )
        self._sessions[domain_id] = session
        return session

    def _load_types(self) -> _MonitoringTypes:
        if self._types is not None:
            return self._types
        self._load_connext_module()
        self._prepare_runtime_environment()
        service_monitoring_xml = os.path.join(self.config.xml_types_dir, "ServiceMonitoring.xml")
        if not os.path.isfile(service_monitoring_xml):
            raise FileNotFoundError(
                f"Required monitoring XML not found: {service_monitoring_xml}. "
                "Run services/rs_gui_v2/setup.sh."
            )
        if not os.path.isfile(self.config.qos_file):
            raise FileNotFoundError(f"Required QoS XML not found: {self.config.qos_file}")

        type_provider = self._dds.QosProvider(service_monitoring_xml)
        qos_provider = self._dds.QosProvider(self.config.qos_file)
        self._types = _MonitoringTypes(
            config_type=type_provider.type(CONFIG_TYPE_NAME),
            event_type=type_provider.type(EVENT_TYPE_NAME),
            periodic_type=type_provider.type(PERIODIC_TYPE_NAME),
            config_qos=qos_provider.datareader_qos_from_profile(CONFIG_QOS_PROFILE),
            event_qos=qos_provider.datareader_qos_from_profile(EVENT_QOS_PROFILE),
            periodic_qos=qos_provider.datareader_qos_from_profile(PERIODIC_QOS_PROFILE),
        )
        return self._types

    def _load_connext_module(self) -> None:
        if self._dds is None:
            import rti.connextdds as dds
            self._dds = dds

    def _prepare_runtime_environment(self) -> None:
        if not self._uses_real_connext:
            return
        nddshome = detect_nddshome()
        ensure_rti_license(nddshome)
        validate_generated_types(self.config.xml_types_dir, nddshome)

    def _configure_xtypes_policy(self) -> None:
        if not self._uses_real_connext:
            return
        compliance = importlib.import_module("rti.connextdds.compliance")

        mask = compliance.get_xtypes_mask()
        mask = mask | compliance.XTypesMask.ACCEPT_UNKNOWN_DISCRIMINATOR_BIT
        mask = mask & compliance.XTypesMask.SELECT_DEFAULT_DISCRIMINATOR_BIT.flip()
        compliance.set_xtypes_mask(mask)


def default_rti_service_monitoring_config() -> RtiServiceMonitoringConfig:
    root_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    repo_root = os.path.normpath(os.path.join(root_dir, "..", ".."))
    return RtiServiceMonitoringConfig(
        xml_types_dir=os.path.join(root_dir, "xml_types"),
        qos_file=os.path.join(repo_root, "dds", "qos", "DDS_QOS_PROFILES.xml"),
    )


def normalize_monitoring_sample(
        service: ServiceInstanceRef,
        kind: MonitoringSnapshotKind,
        sample: Any,
) -> Optional[MonitoringSnapshot]:
    data, info = _sample_data_and_info(sample)
    if not getattr(info, "valid", False):
        return None
    if kind == MonitoringSnapshotKind.CONFIG:
        return _parse_config_sample(service, data)
    if kind == MonitoringSnapshotKind.EVENT:
        return _parse_event_sample(service, data)
    if kind == MonitoringSnapshotKind.PERIODIC:
        return _parse_periodic_sample(service, data)
    return None


def _parse_config_sample(service: ServiceInstanceRef, data: Any) -> Optional[MonitoringSnapshot]:
    union_value = _field(data, "value")
    resource_kind = _union_discriminator(union_value)
    if resource_kind == RESOURCE_RECORDING_SERVICE:
        recording_service = _selected_union_value(union_value, "recording_service")
        details = {
            "resource_kind": resource_kind,
            "service_detected": True,
            "service_name": _to_text(_field(recording_service, "application_name", service.name)),
        }
        application_guid = _guid_to_text(_field(recording_service, "application_guid", None))
        if application_guid:
            details["application_guid"] = application_guid
        process = _field(recording_service, "process", None)
        if process is not None:
            process_id = _to_int(_field(process, "id", -1), -1)
            if process_id >= 0:
                details["process_id"] = process_id
        host = _field(recording_service, "host", None)
        if host is not None:
            host_name = _to_text(_field(host, "name", ""))
            if host_name:
                details["host_name"] = host_name
            host_id = _to_int(_field(host, "id", -1), -1)
            if host_id >= 0:
                details["host_id"] = host_id
            host_target = _to_text(_field(host, "target", ""))
            if host_target:
                details["host_target"] = host_target
        sqlite = _field(recording_service, "builtin_sqlite", None)
        if sqlite is not None:
            details["db_directory"] = _to_text(_field(sqlite, "db_directory", ""))
        return MonitoringSnapshot(
            service=service,
            kind=MonitoringSnapshotKind.CONFIG,
            state="configured",
            details=details,
        )
    if resource_kind == RESOURCE_RECORDING_TOPIC:
        topic = _selected_union_value(union_value, "recording_topic")
        return MonitoringSnapshot(
            service=service,
            kind=MonitoringSnapshotKind.CONFIG,
            state="configured",
            details={
                "resource_kind": resource_kind,
                "service_detected": True,
                "topics": [_to_text(_field(topic, "topic_name", ""))],
            },
        )
    return None


def _parse_event_sample(service: ServiceInstanceRef, data: Any) -> Optional[MonitoringSnapshot]:
    union_value = _field(data, "value")
    resource_kind = _union_discriminator(union_value)
    if resource_kind != RESOURCE_RECORDING_SERVICE:
        return None
    event = _selected_union_value(union_value, "recording_service")
    state = _field(event, "state")
    state_int = _to_int(state)
    state_name = getattr(state, "name", ENTITY_STATE_NAMES.get(state_int, str(state)))
    metrics = {}
    sqlite = _field(event, "builtin_sqlite", None)
    if sqlite is not None:
        metrics["rollover_count"] = _to_int(_field(sqlite, "rollover_count", -1), -1)
    return MonitoringSnapshot(
        service=service,
        kind=MonitoringSnapshotKind.EVENT,
        state=state_name,
        metrics=metrics,
        details={"resource_kind": resource_kind, "state_int": state_int},
    )


def _parse_periodic_sample(service: ServiceInstanceRef, data: Any) -> Optional[MonitoringSnapshot]:
    union_value = _field(data, "value")
    resource_kind = _union_discriminator(union_value)
    if resource_kind != RESOURCE_RECORDING_SERVICE:
        return None
    periodic = _selected_union_value(union_value, "recording_service")
    metrics = {
        "uptime_sec": -1,
        "cpu_percent": -1.0,
        "memory_kb": -1.0,
        "db_file_size": -1,
    }
    details = {"resource_kind": resource_kind, "db_file": ""}
    process = _field(periodic, "process", None)
    host = _field(periodic, "host", None)
    if process is not None:
        metrics["uptime_sec"] = _to_int(_field(process, "uptime_sec", -1), -1)
        metrics["cpu_percent"] = _metric_mean(_field(process, "cpu_usage_percentage", None))
        metrics["memory_kb"] = _metric_mean(_field(process, "physical_memory_kb", None))
    if host is not None:
        if metrics["uptime_sec"] < 0:
            metrics["uptime_sec"] = _to_int(_field(host, "uptime_sec", -1), -1)
        if metrics["cpu_percent"] < 0:
            metrics["cpu_percent"] = _metric_mean(_field(host, "cpu_usage_percentage", None))
        if metrics["memory_kb"] < 0:
            metrics["memory_kb"] = _metric_mean(_field(host, "free_memory_kb", None))
    sqlite = _field(periodic, "builtin_sqlite", None)
    if sqlite is not None:
        details["db_file"] = _to_text(_field(sqlite, "current_file", ""))
        metrics["db_file_size"] = _to_int(_field(sqlite, "current_file_size", -1), -1)
    return MonitoringSnapshot(
        service=service,
        kind=MonitoringSnapshotKind.PERIODIC,
        state="observed",
        metrics=metrics,
        details=details,
    )


def _sample_data_and_info(sample: Any) -> Tuple[Any, Any]:
    try:
        return sample.data, sample.info
    except AttributeError:
        return sample


def _reader_take(reader: Any) -> Iterable[Any]:
    take = getattr(reader, "take", None)
    if take is not None:
        return take()
    read = getattr(reader, "read", None)
    if read is not None:
        return read()
    return ()


def _field(obj: Any, name: str, default=_NO_DEFAULT) -> Any:
    if obj is None:
        if default is _NO_DEFAULT:
            raise AttributeError(name)
        return default
    try:
        return getattr(obj, name)
    except AttributeError:
        pass
    try:
        return obj[name]
    except Exception:
        if default is _NO_DEFAULT:
            raise
        return default


def _selected_union_value(union_value: Any, branch_name: str) -> Any:
    selected = _field(union_value, "value", _MISSING)
    if selected is None:
        raise ValueError(f"Union discriminator {_union_discriminator(union_value)} selects no member")
    return _field(union_value, branch_name)


def _union_discriminator(union_value: Any) -> int:
    for attr in ("discriminator", "discriminator_value"):
        try:
            value = getattr(union_value, attr)
            if callable(value):
                value = value()
            return _to_int_required(value)
        except Exception:
            pass
    return _to_int_required(_field(union_value, "discriminator"))


def _metric_mean(metric: Any, default: float = -1.0) -> float:
    try:
        metrics = _field(metric, "publication_period_metrics")
        return float(_field(metrics, "mean"))
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if hasattr(value, "value"):
            return int(value.value)
        return int(value)
    except Exception:
        return default


def _to_int_required(value: Any) -> int:
    if hasattr(value, "value"):
        value = value.value
    return int(value)


def _to_text(value: Any, default: str = "") -> str:
    if value is None or value is _MISSING:
        return default
    return str(value)


def _guid_to_text(value: Any) -> str:
    if value is None or value is _MISSING:
        return ""
    raw = _field(value, "value", None)
    if raw is None:
        return _to_text(value)
    try:
        return "".join(f"{int(item) & 0xff:02x}" for item in raw)
    except Exception:
        return _to_text(raw)


def _safe_close(entity: Any) -> None:
    close = getattr(entity, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            pass