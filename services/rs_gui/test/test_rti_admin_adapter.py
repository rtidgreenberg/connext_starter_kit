#!/usr/bin/env python3
"""Unit tests for the rs_gui_v2 RTI Service Admin adapter.

These tests use fake Connext modules so they can validate adapter encoding and
outcome mapping without starting DDS.
"""

import os
import sys
import tempfile
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import CommandStatus
from app_core.services import ServiceCommand, ServiceCommandRequest, ServiceInstanceRef, ServiceKind
from app_core.services.rti_admin import (
    ACTION_DELETE,
    ACTION_UPDATE,
    COMMAND_REPLY_TOPIC_NAME,
    COMMAND_REQUEST_TOPIC_NAME,
    ENTITY_STATE_PAUSED,
    ENTITY_STATE_RUNNING,
    ENTITY_STATE_STOPPED,
    ENTITY_STATE_TYPE_NAME,
    RETCODE_ERROR,
    RETCODE_OK,
    RtiServiceAdminClient,
    RtiServiceAdminConfig,
    cdr_buffer_to_octets,
    recording_service_resource,
    recording_service_state_resource,
    recording_service_tag_resource,
    replay_service_state_resource,
    replay_service_resource,
    service_shutdown_resource,
)


class FakeStatus:
    def __init__(self, current_count=1, total_count=1):
        self.current_count = current_count
        self.total_count = total_count


class FakeEndpoint:
    def __init__(self, current_count=1):
        self.publication_matched_status = FakeStatus(current_count=current_count)
        self.subscription_matched_status = FakeStatus(current_count=current_count)


class FakeSampleInfo:
    def __init__(self, valid=True):
        self.valid = valid


class FakeSample:
    def __init__(self, retcode=RETCODE_OK, native_retcode=0, string_body="ok", valid=True):
        self.info = FakeSampleInfo(valid=valid)
        self.data = {
            "retcode": retcode,
            "native_retcode": native_retcode,
            "string_body": string_body,
        }


class FakeDynamicData:
    instances = []

    def __init__(self, type_name):
        self.type_name = type_name
        self.fields = {}
        FakeDynamicData.instances.append(self)

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, key):
        return self.fields[key]

    def to_cdr_buffer(self):
        if self.type_name == ENTITY_STATE_TYPE_NAME:
            return bytes([self.fields["state"]])
        tag_name = self.fields.get("tag_name", "")
        return tag_name.encode("utf-8")


class FakeQosProvider:
    def __init__(self, path):
        self.path = path

    def type(self, type_name):
        return type_name

    def datawriter_qos_from_profile(self, profile):
        return f"writer:{profile}"

    def datareader_qos_from_profile(self, profile):
        return f"reader:{profile}"


class FakeDuration:
    @staticmethod
    def from_seconds(seconds):
        return seconds


class FakeParticipant:
    def __init__(self, domain_id):
        self.domain_id = domain_id
        self.closed = False

    def close(self):
        self.closed = True


class FakeDdsModule:
    QosProvider = FakeQosProvider
    DynamicData = FakeDynamicData
    DomainParticipant = FakeParticipant
    Duration = FakeDuration


class FakeRequester:
    def __init__(self, reply_samples=None, wait_for_replies=True, match_count=1, **kwargs):
        self.kwargs = kwargs
        self.reply_samples = reply_samples if reply_samples is not None else [FakeSample()]
        self.wait_result = wait_for_replies
        self.request_datawriter = FakeEndpoint(match_count)
        self.reply_datareader = FakeEndpoint(match_count)
        self.sent_requests = []
        self.closed = False

    def send_request(self, command_data):
        self.sent_requests.append(command_data)
        return "request-id"

    def wait_for_replies(self, timeout, min_count, related_request_id):
        self.last_wait = (timeout, min_count, related_request_id)
        return self.wait_result

    def take_replies(self, request_id):
        self.last_take_request_id = request_id
        return self.reply_samples

    def close(self):
        self.closed = True


class FakeRequestModule:
    def __init__(self, reply_samples=None, wait_for_replies=True, match_count=1):
        self.reply_samples = reply_samples
        self.wait_for_replies = wait_for_replies
        self.match_count = match_count
        self.requesters = []

    def Requester(self, **kwargs):
        requester = FakeRequester(
            reply_samples=self.reply_samples,
            wait_for_replies=self.wait_for_replies,
            match_count=self.match_count,
            **kwargs,
        )
        self.requesters.append(requester)
        return requester


class TestRtiServiceAdminResources(unittest.TestCase):
    def test_recording_service_resource_paths(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")

        self.assertEqual(recording_service_resource(service), "/recording_services/deploy")
        self.assertEqual(recording_service_state_resource(service), "/recording_services/deploy/state")
        self.assertEqual(
            recording_service_tag_resource(service),
            "/recording_services/deploy/storage/sqlite:tag_timestamp",
        )

    def test_replay_service_resource_paths(self):
        recording = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        replay = ServiceInstanceRef(ServiceKind.REPLAY, "xcdr")

        self.assertEqual(replay_service_resource(replay), "/replay_services/xcdr")
        self.assertEqual(service_shutdown_resource(recording), "/recording_services/deploy")
        self.assertEqual(service_shutdown_resource(replay), "/replay_services/xcdr")
        self.assertEqual(service_shutdown_resource(replay, "json"), "/replay_services/json")

    def test_cdr_buffer_to_octets_accepts_bytes_and_strings(self):
        self.assertEqual(cdr_buffer_to_octets(b"\x00\x01"), [0, 1])
        self.assertEqual(cdr_buffer_to_octets(["\x02", 3]), [2, 3])


class TestRtiServiceAdminClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeDynamicData.instances = []
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for filename in ("ServiceAdmin.xml", "ServiceCommon.xml", "RecordingServiceTypes.xml"):
            open(os.path.join(self.temp_dir.name, filename), "w", encoding="utf-8").close()
        self.qos_file = os.path.join(self.temp_dir.name, "DDS_QOS_PROFILES.xml")
        open(self.qos_file, "w", encoding="utf-8").close()
        self.config = RtiServiceAdminConfig(
            xml_types_dir=self.temp_dir.name,
            qos_file=self.qos_file,
            discovery_timeout_sec=0.0,
            reply_timeout_sec=7.0,
        )
        self.service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy", admin_domain_id=54)

    async def test_check_readiness_reports_request_and_reply_matches(self):
        request_module = FakeRequestModule(match_count=2)
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)

        readiness = await client.check_readiness(self.service)

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.matched_request_writers, 2)
        self.assertEqual(readiness.matched_reply_readers, 2)
        self.assertEqual(request_module.requesters[0].kwargs["request_topic"], COMMAND_REQUEST_TOPIC_NAME)
        self.assertEqual(request_module.requesters[0].kwargs["reply_topic"], COMMAND_REPLY_TOPIC_NAME)

    async def test_pause_encodes_state_resource_and_entity_state_octets(self):
        request_module = FakeRequestModule(reply_samples=[FakeSample(string_body="paused")])
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.PAUSE, timeout_sec=2.0)

        outcome = await client.send_command(request)

        requester = request_module.requesters[0]
        command_data = requester.sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, CommandStatus.ACKNOWLEDGED)
        self.assertEqual(outcome.message, "paused")
        self.assertEqual(outcome.resource_path, "/recording_services/deploy/state")
        self.assertEqual(command_data["application_name"], "deploy")
        self.assertEqual(command_data["action"], ACTION_UPDATE)
        self.assertEqual(command_data["resource_identifier"], "/recording_services/deploy/state")
        self.assertEqual(command_data["octet_body"], [ENTITY_STATE_PAUSED])
        self.assertEqual(requester.last_wait, (2.0, 1, "request-id"))

    async def test_resume_encodes_running_state(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.RESUME)

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(command_data["octet_body"], [ENTITY_STATE_RUNNING])

    async def test_shutdown_encodes_delete_resource(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.SHUTDOWN)

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(command_data["action"], ACTION_DELETE)
        self.assertEqual(command_data["resource_identifier"], "/recording_services/deploy")

    async def test_replay_shutdown_encodes_delete_resource(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        service = ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_v2_replay_1234", admin_domain_id=54)
        request = ServiceCommandRequest(
            service,
            ServiceCommand.SHUTDOWN,
            parameters={"admin_resource_name": "xcdr"},
        )

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(command_data["application_name"], "rs_gui_v2_replay_1234")
        self.assertEqual(command_data["action"], ACTION_DELETE)
        self.assertEqual(command_data["resource_identifier"], "/replay_services/xcdr")

    async def test_replay_custom_state_update_encodes_state_resource(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        service = ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_v2_replay_1234", admin_domain_id=54)
        request = ServiceCommandRequest(
            service,
            ServiceCommand.CUSTOM,
            parameters={
                "action": ACTION_UPDATE,
                "resource_path": replay_service_state_resource(service, "xcdr"),
                "entity_state_value": ENTITY_STATE_STOPPED,
            },
        )

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(command_data["application_name"], "rs_gui_v2_replay_1234")
        self.assertEqual(command_data["action"], ACTION_UPDATE)
        self.assertEqual(command_data["resource_identifier"], "/replay_services/xcdr/state")
        self.assertEqual(command_data["octet_body"], [ENTITY_STATE_STOPPED])

    async def test_shutdown_can_target_app_name_with_separate_xml_resource(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        service = ServiceInstanceRef(ServiceKind.RECORDING, "rs_gui_v2_churn_1234", admin_domain_id=54)
        request = ServiceCommandRequest(
            service,
            ServiceCommand.SHUTDOWN,
            parameters={"admin_resource_name": "deploy"},
        )

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(command_data["application_name"], "rs_gui_v2_churn_1234")
        self.assertEqual(command_data["resource_identifier"], "/recording_services/deploy")

    async def test_pause_can_target_app_name_with_separate_xml_resource(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        service = ServiceInstanceRef(ServiceKind.RECORDING, "rs_gui_v2_churn_1234", admin_domain_id=54)
        request = ServiceCommandRequest(
            service,
            ServiceCommand.PAUSE,
            parameters={"admin_resource_name": "deploy"},
        )

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        self.assertTrue(outcome.ok)
        self.assertEqual(command_data["application_name"], "rs_gui_v2_churn_1234")
        self.assertEqual(command_data["resource_identifier"], "/recording_services/deploy/state")

    async def test_tag_encodes_tag_resource_and_payload(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(
            self.service,
            ServiceCommand.TAG,
            parameters={"tag_name": "alpha", "description": "first"},
        )

        outcome = await client.send_command(request)

        command_data = request_module.requesters[0].sent_requests[0]
        tag_data = [item for item in FakeDynamicData.instances if item.fields.get("tag_name") == "alpha"][0]
        self.assertTrue(outcome.ok)
        self.assertEqual(
            command_data["resource_identifier"],
            "/recording_services/deploy/storage/sqlite:tag_timestamp",
        )
        self.assertEqual(command_data["octet_body"], list(b"alpha"))
        self.assertEqual(tag_data.fields["tag_description"], "first")
        self.assertEqual(tag_data.fields["timestamp_offset"], 0.0)

    async def test_rejected_reply_maps_to_rejected_outcome(self):
        request_module = FakeRequestModule(reply_samples=[
            FakeSample(retcode=RETCODE_ERROR, native_retcode=12, string_body="rejected")
        ])
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.PAUSE)

        outcome = await client.send_command(request)

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, CommandStatus.REJECTED)
        self.assertEqual(outcome.native_retcode, 12)
        self.assertEqual(outcome.payload["retcode"], RETCODE_ERROR)

    async def test_reply_timeout_maps_to_timeout_outcome(self):
        request_module = FakeRequestModule(wait_for_replies=False)
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.PAUSE)

        outcome = await client.send_command(request)

        self.assertEqual(outcome.status, CommandStatus.TIMEOUT)
        self.assertIn("No Service Admin reply", outcome.message)

    async def test_unmatched_admin_endpoints_map_to_timeout_outcome(self):
        request_module = FakeRequestModule(match_count=0)
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.PAUSE)

        outcome = await client.send_command(request)

        self.assertEqual(outcome.status, CommandStatus.TIMEOUT)
        self.assertIn("Timed out waiting for Service Admin endpoints", outcome.message)

    async def test_request_timeout_caps_admin_readiness_wait(self):
        config = RtiServiceAdminConfig(
            xml_types_dir=self.temp_dir.name,
            qos_file=self.qos_file,
            discovery_timeout_sec=60.0,
            discovery_poll_sec=0.001,
            reply_timeout_sec=7.0,
        )
        request_module = FakeRequestModule(match_count=0)
        client = RtiServiceAdminClient(config, FakeDdsModule, request_module)
        request = ServiceCommandRequest(self.service, ServiceCommand.SHUTDOWN, timeout_sec=0.0)

        outcome = await client.send_command(request)

        self.assertEqual(outcome.status, CommandStatus.TIMEOUT)
        self.assertIn("after 0.0s", outcome.message)
        self.assertEqual(request_module.requesters[0].sent_requests, [])

    async def test_close_releases_requesters_and_participants(self):
        request_module = FakeRequestModule()
        client = RtiServiceAdminClient(self.config, FakeDdsModule, request_module)

        await client.check_readiness(self.service)
        session = client._sessions[self.service.admin_domain_id]
        await client.close()

        self.assertTrue(session.requester.closed)
        self.assertTrue(session.participant.closed)
        self.assertEqual(client._sessions, {})


if __name__ == "__main__":
    unittest.main()