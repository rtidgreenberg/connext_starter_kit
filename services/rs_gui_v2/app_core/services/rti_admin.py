"""RTI Service Admin request/reply adapter for rs_gui_v2.

This module is the only service-admin module that imports Connext DDS. The
DDS-free `ServiceAdminFacade` and DTOs stay in `admin.py` and `models.py`.
"""

import asyncio
from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from ..connext_environment import (
    detect_nddshome,
    ensure_rti_license,
    license_setup_message,
    validate_generated_types,
)
from ..debug_log import dbg, dbg_exc
from ..events import CommandStatus
from .models import (
    AdminReadiness,
    AdminReadinessStatus,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
)


COMMAND_REQUEST_TOPIC_NAME = "rti/service/admin/command_request"
COMMAND_REPLY_TOPIC_NAME = "rti/service/admin/command_reply"

COMMAND_REQUEST_TYPE_NAME = "RTI::Service::Admin::CommandRequest"
COMMAND_REPLY_TYPE_NAME = "RTI::Service::Admin::CommandReply"
DATA_TAG_PARAMS_TYPE_NAME = "RTI::RecordingService::DataTagParams"
ENTITY_STATE_TYPE_NAME = "RTI::Service::EntityState"

SERVICE_ADMIN_QOS_PROFILE = "ServiceAdministrationProfiles::ServiceAdminRequesterProfile"

ACTION_CREATE = 0
ACTION_GET = 1
ACTION_UPDATE = 2
ACTION_DELETE = 3

RETCODE_OK = 0
RETCODE_ERROR = 1

ENTITY_STATE_RUNNING = 5
ENTITY_STATE_PAUSED = 6

DEFAULT_REPLY_TIMEOUT_SEC = 60.0
DEFAULT_DISCOVERY_TIMEOUT_SEC = 60.0
DEFAULT_DISCOVERY_POLL_SEC = 0.05


@dataclass(frozen=True)
class RtiServiceAdminConfig:
    """Filesystem and timing inputs for the RTI Service Admin adapter."""

    xml_types_dir: str
    qos_file: str
    discovery_timeout_sec: float = DEFAULT_DISCOVERY_TIMEOUT_SEC
    discovery_poll_sec: float = DEFAULT_DISCOVERY_POLL_SEC
    reply_timeout_sec: float = DEFAULT_REPLY_TIMEOUT_SEC


@dataclass
class _AdminTypes:
    request_type: Any
    reply_type: Any
    data_tag_type: Any
    entity_state_type: Any
    writer_qos: Any
    reader_qos: Any


@dataclass
class _AdminSession:
    participant: Any
    requester: Any


class RtiServiceAdminClient:
    """Connext DDS implementation of the `ServiceAdminClient` protocol."""

    def __init__(
            self,
            config: Optional[RtiServiceAdminConfig] = None,
            dds_module: Any = None,
            request_module: Any = None,
    ) -> None:
        self.config = config or default_rti_service_admin_config()
        self._dds = dds_module
        self._request = request_module
        self._uses_real_connext = dds_module is None or request_module is None
        self._types: Optional[_AdminTypes] = None
        self._sessions: Dict[int, _AdminSession] = {}

    async def check_readiness(self, service: ServiceInstanceRef) -> AdminReadiness:
        return await self._run_blocking(self._check_readiness_sync, service)

    async def send_command(self, request: ServiceCommandRequest) -> ServiceCommandOutcome:
        return await self._run_blocking(self._send_command_sync, request)

    async def close(self) -> None:
        await self._run_blocking(self.close_sync)

    def close_sync(self) -> None:
        """Close requesters and participants owned by this adapter."""
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            _safe_close(session.requester)
            _safe_close(session.participant)

    async def _run_blocking(self, function, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: function(*args))

    def _check_readiness_sync(self, service: ServiceInstanceRef) -> AdminReadiness:
        dbg("admin", f"check_readiness service={service.name!r} admin_domain={service.admin_domain_id}")
        session = self._session_for_domain(service.admin_domain_id)
        result = self._readiness_from_session(service, session)
        dbg("admin", f"readiness result={result.status.value} msg={result.message!r}")
        return result

    def _send_command_sync(self, request: ServiceCommandRequest) -> ServiceCommandOutcome:
        dbg("admin", f"send_command service={request.service.name!r} cmd={request.command.value} timeout={request.timeout_sec}")
        try:
            session = self._session_for_domain(request.service.admin_domain_id)
            readiness = self._wait_for_readiness(
                request.service,
                session,
                timeout_sec=request.timeout_sec,
            )
            if not readiness.ready:
                return ServiceCommandOutcome(
                    request=request,
                    status=CommandStatus.TIMEOUT,
                    message=readiness.message,
                    payload={"readiness": readiness.to_dict()},
                )

            command_data, action, resource_path = self._build_command_data(request)
            request_id = session.requester.send_request(command_data)
            timeout_sec = request.timeout_sec or self.config.reply_timeout_sec
            got_reply = session.requester.wait_for_replies(
                self._dds.Duration.from_seconds(timeout_sec),
                min_count=1,
                related_request_id=request_id,
            )
            if not got_reply:
                return ServiceCommandOutcome(
                    request=request,
                    status=CommandStatus.TIMEOUT,
                    message=f"No Service Admin reply after {timeout_sec:.1f}s",
                    resource_path=resource_path,
                    payload={"action": _action_name(action)},
                )

            replies = session.requester.take_replies(request_id)
            return self._outcome_from_replies(request, resource_path, action, replies)
        except Exception as exc:
            return ServiceCommandOutcome(
                request=request,
                status=CommandStatus.FAILED,
                message=str(exc),
            )

    def _build_command_data(
            self, request: ServiceCommandRequest
    ) -> Tuple[Any, int, str]:
        types = self._load_types()
        action, resource_path, string_body, octet_body = self._encode_command(request, types)

        command_data = self._dds.DynamicData(types.request_type)
        command_data["instance_id"] = 0
        command_data["application_name"] = request.service.name
        command_data["action"] = action
        command_data["resource_identifier"] = resource_path
        command_data["string_body"] = string_body
        if octet_body is not None:
            command_data["octet_body"] = octet_body
        return command_data, action, resource_path

    def _encode_command(
            self, request: ServiceCommandRequest, types: _AdminTypes
    ) -> Tuple[int, str, str, Optional[list]]:
        if request.command == ServiceCommand.PAUSE:
            return (
                ACTION_UPDATE,
                recording_service_state_resource(request.service, _admin_resource_name(request)),
                "",
                self._serialize_entity_state(types.entity_state_type, ENTITY_STATE_PAUSED),
            )
        if request.command == ServiceCommand.RESUME:
            return (
                ACTION_UPDATE,
                recording_service_state_resource(request.service, _admin_resource_name(request)),
                "",
                self._serialize_entity_state(types.entity_state_type, ENTITY_STATE_RUNNING),
            )
        if request.command == ServiceCommand.SHUTDOWN:
            return ACTION_DELETE, recording_service_resource(request.service, _admin_resource_name(request)), "", None
        if request.command == ServiceCommand.TAG:
            return (
                ACTION_UPDATE,
                recording_service_tag_resource(request.service, _admin_resource_name(request)),
                "",
                self._serialize_tag_params(request, types.data_tag_type),
            )
        if request.command == ServiceCommand.CUSTOM:
            return self._encode_custom_command(request)
        raise ValueError(f"Unsupported Service Admin command: {request.command}")

    def _encode_custom_command(
            self, request: ServiceCommandRequest
    ) -> Tuple[int, str, str, Optional[list]]:
        action = int(request.parameters.get("action", ACTION_UPDATE))
        resource_path = str(request.parameters["resource_path"])
        string_body = str(request.parameters.get("string_body", ""))
        octet_body = request.parameters.get("octet_body")
        if octet_body is not None:
            octet_body = [int(value) for value in octet_body]
        return action, resource_path, string_body, octet_body

    def _serialize_entity_state(self, entity_state_type: Any, state_value: int) -> list:
        state_data = self._dds.DynamicData(entity_state_type)
        state_data["state"] = state_value
        return cdr_buffer_to_octets(state_data.to_cdr_buffer())

    def _serialize_tag_params(self, request: ServiceCommandRequest, data_tag_type: Any) -> list:
        tag_name = str(request.parameters.get("tag_name", ""))
        if not tag_name:
            raise ValueError("TAG command requires parameter 'tag_name'")
        tag_data = self._dds.DynamicData(data_tag_type)
        tag_data["timestamp_offset"] = float(request.parameters.get("timestamp_offset", 0.0))
        tag_data["tag_name"] = tag_name
        tag_data["tag_description"] = str(request.parameters.get("description", ""))
        return cdr_buffer_to_octets(tag_data.to_cdr_buffer())

    def _wait_for_readiness(
            self,
            service: ServiceInstanceRef,
            session: _AdminSession,
            timeout_sec: Optional[float] = None,
    ) -> AdminReadiness:
        discovery_timeout_sec = self.config.discovery_timeout_sec
        if timeout_sec is not None:
            discovery_timeout_sec = min(discovery_timeout_sec, max(0.0, float(timeout_sec)))
        deadline = time.time() + discovery_timeout_sec
        readiness = self._readiness_from_session(service, session)
        while not readiness.ready and time.time() < deadline:
            time.sleep(self.config.discovery_poll_sec)
            readiness = self._readiness_from_session(service, session)
        if readiness.ready:
            return readiness
        return AdminReadiness(
            service=service,
            status=AdminReadinessStatus.TIMEOUT,
            matched_request_writers=readiness.matched_request_writers,
            matched_reply_readers=readiness.matched_reply_readers,
            message=self._discovery_timeout_message(service, session, readiness, discovery_timeout_sec),
        )

    def _readiness_from_session(
            self, service: ServiceInstanceRef, session: _AdminSession
    ) -> AdminReadiness:
        writer = session.requester.request_datawriter
        reader = session.requester.reply_datareader
        writer_matches = _status_count(writer, "publication_matched_status")
        reader_matches = _status_count(reader, "subscription_matched_status")
        ready = writer_matches > 0 and reader_matches > 0
        return AdminReadiness(
            service=service,
            status=AdminReadinessStatus.READY if ready else AdminReadinessStatus.DISCOVERING,
            matched_request_writers=writer_matches,
            matched_reply_readers=reader_matches,
            message="Service Admin request/reply matched" if ready else "Waiting for Service Admin endpoints",
        )

    def _outcome_from_replies(
            self,
            request: ServiceCommandRequest,
            resource_path: str,
            action: int,
            replies,
    ) -> ServiceCommandOutcome:
        for sample in replies:
            if not getattr(sample.info, "valid", False):
                continue
            retcode = int(sample.data["retcode"])
            native_retcode = int(sample.data["native_retcode"])
            string_body = str(sample.data["string_body"])
            return ServiceCommandOutcome(
                request=request,
                status=CommandStatus.ACKNOWLEDGED if retcode == RETCODE_OK else CommandStatus.REJECTED,
                message=string_body,
                native_retcode=native_retcode,
                resource_path=resource_path,
                payload={
                    "action": _action_name(action),
                    "retcode": retcode,
                    "string_body": string_body,
                },
            )
        return ServiceCommandOutcome(
            request=request,
            status=CommandStatus.FAILED,
            message="Service Admin reply contained no valid samples",
            resource_path=resource_path,
            payload={"action": _action_name(action)},
        )

    def _session_for_domain(self, domain_id: int) -> _AdminSession:
        domain_id = int(domain_id)
        session = self._sessions.get(domain_id)
        if session is not None:
            return session

        self._load_connext_modules()
        self._prepare_runtime_environment()
        types = self._load_types()
        try:
            participant = self._dds.DomainParticipant(domain_id)
        except Exception as exc:
            nddshome = detect_nddshome()
            raise RuntimeError(
                f"Failed to create DDS DomainParticipant on domain {domain_id}. "
                f"{license_setup_message(nddshome)}"
            ) from exc
        requester = self._request.Requester(
            request_type=types.request_type,
            reply_type=types.reply_type,
            participant=participant,
            request_topic=COMMAND_REQUEST_TOPIC_NAME,
            reply_topic=COMMAND_REPLY_TOPIC_NAME,
            datawriter_qos=types.writer_qos,
            datareader_qos=types.reader_qos,
            require_matching_service_on_send_request=False,
        )
        session = _AdminSession(participant=participant, requester=requester)
        self._sessions[domain_id] = session
        return session

    def _load_types(self) -> _AdminTypes:
        if self._types is not None:
            return self._types
        self._load_connext_modules()
        self._prepare_runtime_environment()
        admin_xml, common_xml, recording_xml = self._required_xml_type_files()
        for path in (admin_xml, common_xml, recording_xml, self.config.qos_file):
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Required Service Admin adapter file not found: {path}")

        admin_provider = self._dds.QosProvider(admin_xml)
        recording_provider = self._dds.QosProvider(recording_xml)
        common_provider = self._dds.QosProvider(common_xml)
        qos_provider = self._dds.QosProvider(self.config.qos_file)
        self._types = _AdminTypes(
            request_type=admin_provider.type(COMMAND_REQUEST_TYPE_NAME),
            reply_type=admin_provider.type(COMMAND_REPLY_TYPE_NAME),
            data_tag_type=recording_provider.type(DATA_TAG_PARAMS_TYPE_NAME),
            entity_state_type=common_provider.type(ENTITY_STATE_TYPE_NAME),
            writer_qos=qos_provider.datawriter_qos_from_profile(SERVICE_ADMIN_QOS_PROFILE),
            reader_qos=qos_provider.datareader_qos_from_profile(SERVICE_ADMIN_QOS_PROFILE),
        )
        return self._types

    def _load_connext_modules(self) -> None:
        if self._dds is None:
            import rti.connextdds as dds
            self._dds = dds
        if self._request is None:
            import rti.request as request
            self._request = request

    def _prepare_runtime_environment(self) -> None:
        if not self._uses_real_connext:
            return
        nddshome = detect_nddshome()
        ensure_rti_license(nddshome)
        validate_generated_types(self.config.xml_types_dir, nddshome)

    def _required_xml_type_files(self) -> Tuple[str, str, str]:
        return (
            os.path.join(self.config.xml_types_dir, "ServiceAdmin.xml"),
            os.path.join(self.config.xml_types_dir, "ServiceCommon.xml"),
            os.path.join(self.config.xml_types_dir, "RecordingServiceTypes.xml"),
        )

    def _discovery_timeout_message(
            self,
            service: ServiceInstanceRef,
            session: _AdminSession,
            readiness: AdminReadiness,
            timeout_sec: Optional[float] = None,
    ) -> str:
        effective_timeout_sec = self.config.discovery_timeout_sec if timeout_sec is None else float(timeout_sec)
        return "\n".join((
            f"Timed out waiting for Service Admin endpoints after "
            f"{effective_timeout_sec:.1f}s.",
            f"service_name: {service.name}",
            f"admin_domain_id: {service.admin_domain_id}",
            f"request_topic: {COMMAND_REQUEST_TOPIC_NAME}",
            f"reply_topic: {COMMAND_REPLY_TOPIC_NAME}",
            f"request writer matches: {readiness.matched_request_writers}",
            f"reply reader matches: {readiness.matched_reply_readers}",
            "request writer status: " + _format_status_fields(
                _safe_attr(session.requester.request_datawriter, "publication_matched_status"),
                ("current_count", "total_count"),
            ),
            "reply reader status: " + _format_status_fields(
                _safe_attr(session.requester.reply_datareader, "subscription_matched_status"),
                ("current_count", "total_count"),
            ),
        ))


def default_rti_service_admin_config() -> RtiServiceAdminConfig:
    root_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    repo_root = os.path.normpath(os.path.join(root_dir, "..", ".."))
    return RtiServiceAdminConfig(
        xml_types_dir=os.path.join(root_dir, "xml_types"),
        qos_file=os.path.join(repo_root, "dds", "qos", "DDS_QOS_PROFILES.xml"),
    )


def recording_service_resource(service: ServiceInstanceRef, resource_name: str = "") -> str:
    return f"/recording_services/{resource_name or service.name}"


def recording_service_state_resource(service: ServiceInstanceRef, resource_name: str = "") -> str:
    return f"{recording_service_resource(service, resource_name)}/state"


def recording_service_tag_resource(service: ServiceInstanceRef, resource_name: str = "") -> str:
    return f"{recording_service_resource(service, resource_name)}/storage/sqlite:tag_timestamp"


def _admin_resource_name(request: ServiceCommandRequest) -> str:
    return str(request.parameters.get("admin_resource_name", ""))


def cdr_buffer_to_octets(cdr_buffer) -> list:
    return [ord(value) if isinstance(value, str) else int(value) for value in cdr_buffer]


def _action_name(action: int) -> str:
    names = {
        ACTION_CREATE: "CREATE",
        ACTION_GET: "GET",
        ACTION_UPDATE: "UPDATE",
        ACTION_DELETE: "DELETE",
    }
    return names.get(action, f"UNKNOWN({action})")


def _safe_close(entity: Any) -> None:
    close = getattr(entity, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            pass


def _safe_attr(obj: Any, name: str, default: Any = "unavailable") -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _status_count(entity: Any, status_name: str) -> int:
    status = _safe_attr(entity, status_name, None)
    return int(_safe_attr(status, "current_count", 0))


def _format_status_fields(status: Any, fields: Tuple[str, ...]) -> str:
    if status == "unavailable" or status is None:
        return "unavailable"
    parts = []
    for field in fields:
        value = _safe_attr(status, field)
        if value != "unavailable":
            parts.append(f"{field}={value}")
    return ", ".join(parts) if parts else "unavailable"