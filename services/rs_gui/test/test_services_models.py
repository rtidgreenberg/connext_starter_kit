#!/usr/bin/env python3
"""Pure unit tests for rs_gui_v2 service DTOs."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import CommandStatus
from app_core.services import (
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


class TestServiceInstanceRef(unittest.TestCase):
    def test_service_ref_round_trip_and_key(self):
        service = ServiceInstanceRef(
            kind="recording",
            name="deploy",
            admin_domain_id="54",
            monitoring_domain_id="55",
            config_paths=["record.xml", "qos.xml"],
        )

        self.assertEqual(service.kind, ServiceKind.RECORDING)
        self.assertEqual(service.admin_domain_id, 54)
        self.assertEqual(service.monitoring_domain_id, 55)
        self.assertEqual(service.config_paths, ("record.xml", "qos.xml"))
        self.assertEqual(service.key, "recording:deploy:admin=54:monitor=55")
        self.assertEqual(ServiceInstanceRef.from_dict(service.to_dict()), service)


class TestAdminReadiness(unittest.TestCase):
    def test_readiness_ready_property_and_round_trip(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        readiness = AdminReadiness(
            service=service,
            status="ready",
            matched_request_writers="1",
            matched_reply_readers="2",
            message="matched",
            checked_at=123.0,
        )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, AdminReadinessStatus.READY)
        self.assertEqual(readiness.matched_request_writers, 1)
        self.assertEqual(readiness.matched_reply_readers, 2)
        self.assertEqual(AdminReadiness.from_dict(readiness.to_dict()), readiness)


class TestServiceCommandModels(unittest.TestCase):
    def test_command_request_copies_parameters_and_round_trips(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        parameters = {"tag_name": "alpha"}
        request = ServiceCommandRequest(
            service=service,
            command="tag",
            parameters=parameters,
            command_id="cmd-1",
            created_at=123.0,
            timeout_sec=5.0,
        )

        parameters["tag_name"] = "changed"

        self.assertEqual(request.command, ServiceCommand.TAG)
        self.assertEqual(request.parameters["tag_name"], "alpha")
        with self.assertRaises(TypeError):
            request.parameters["new"] = "blocked"
        self.assertEqual(ServiceCommandRequest.from_dict(request.to_dict()), request)

    def test_command_outcome_ok_payload_and_round_trip(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        request = ServiceCommandRequest(service, ServiceCommand.PAUSE, command_id="cmd-1")
        payload = {"reply": "accepted"}
        outcome = ServiceCommandOutcome(
            request=request,
            status="acknowledged",
            message="accepted",
            native_retcode="0",
            resource_path="/recording_services/deploy/state",
            payload=payload,
            created_at=456.0,
        )

        payload["reply"] = "changed"

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, CommandStatus.ACKNOWLEDGED)
        self.assertEqual(outcome.native_retcode, 0)
        self.assertEqual(outcome.payload["reply"], "accepted")
        with self.assertRaises(TypeError):
            outcome.payload["new"] = "blocked"
        self.assertEqual(ServiceCommandOutcome.from_dict(outcome.to_dict()), outcome)


class TestMonitoringModels(unittest.TestCase):
    def test_monitoring_snapshot_updates_service_state(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        snapshot = MonitoringSnapshot(
            service=service,
            kind="periodic",
            state="RUNNING",
            metrics={"cpu_percent": 1.5},
            details={"host": "localhost"},
            observed_at=789.0,
        )
        state = ServiceStateSnapshot(service=service).with_monitoring(snapshot)

        self.assertEqual(snapshot.kind, MonitoringSnapshotKind.PERIODIC)
        self.assertEqual(MonitoringSnapshot.from_dict(snapshot.to_dict()), snapshot)
        self.assertEqual(state.observed_state, "RUNNING")
        self.assertEqual(state.last_monitoring_kind, MonitoringSnapshotKind.PERIODIC)
        self.assertEqual(state.metrics["cpu_percent"], 1.5)
        with self.assertRaises(TypeError):
            state.metrics["new"] = "blocked"
        self.assertEqual(ServiceStateSnapshot.from_dict(state.to_dict()), state)


if __name__ == "__main__":
    unittest.main()