#!/usr/bin/env python3
"""Pure unit tests for rs_gui_v2 service facades and fakes."""

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
    FakeServiceAdminClient,
    FakeServiceMonitoringClient,
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceAdminFacade,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceInstanceRef,
    ServiceKind,
    ServiceMonitoringFacade,
)


class TestServiceAdminFacade(unittest.IsolatedAsyncioTestCase):
    async def test_default_fake_readiness_is_ready(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        client = FakeServiceAdminClient()
        facade = ServiceAdminFacade(client)

        readiness = await facade.readiness(service)

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.matched_request_writers, 1)
        self.assertEqual(readiness.matched_reply_readers, 1)

    async def test_configured_readiness_is_returned(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        client = FakeServiceAdminClient()
        client.set_readiness(AdminReadiness(
            service=service,
            status=AdminReadinessStatus.UNAVAILABLE,
            message="no match",
        ))
        facade = ServiceAdminFacade(client)

        readiness = await facade.readiness(service)

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, AdminReadinessStatus.UNAVAILABLE)
        self.assertEqual(readiness.message, "no match")

    async def test_facade_methods_create_typed_requests(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        client = FakeServiceAdminClient()
        facade = ServiceAdminFacade(client)

        pause_result = await facade.pause(service, timeout_sec=3.0)
        tag_result = await facade.tag(service, "alpha", description="first tag")

        self.assertTrue(pause_result.ok)
        self.assertTrue(tag_result.ok)
        self.assertEqual([request.command for request in client.requests], [
            ServiceCommand.PAUSE,
            ServiceCommand.TAG,
        ])
        self.assertEqual(client.requests[0].timeout_sec, 3.0)
        self.assertEqual(client.requests[1].parameters["tag_name"], "alpha")
        self.assertEqual(client.requests[1].parameters["description"], "first tag")

    async def test_queued_command_outcome_can_reject_command(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        request = ServiceCommandRequest(service=service, command=ServiceCommand.SHUTDOWN)
        client = FakeServiceAdminClient()
        client.queue_outcome(ServiceCommandOutcome(
            request=request,
            status=CommandStatus.REJECTED,
            message="not allowed",
        ))
        facade = ServiceAdminFacade(client)

        outcome = await facade.shutdown(service)

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, CommandStatus.REJECTED)
        self.assertEqual(outcome.message, "not allowed")


class TestServiceMonitoringFacade(unittest.IsolatedAsyncioTestCase):
    async def test_latest_state_defaults_when_no_snapshot_exists(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        facade = ServiceMonitoringFacade(FakeServiceMonitoringClient())

        state = await facade.latest_state(service)

        self.assertEqual(state.observed_state, "unknown")
        self.assertEqual(state.last_monitoring_kind, MonitoringSnapshotKind.SYNTHETIC)

    async def test_latest_state_uses_latest_snapshot(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        client = FakeServiceMonitoringClient()
        client.push_snapshot(MonitoringSnapshot(
            service=service,
            kind=MonitoringSnapshotKind.CONFIG,
            state="STARTED",
            observed_at=1.0,
        ))
        client.push_snapshot(MonitoringSnapshot(
            service=service,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="RUNNING",
            metrics={"memory_kb": 1234},
            observed_at=2.0,
        ))
        facade = ServiceMonitoringFacade(client)

        state = await facade.latest_state(service)

        self.assertEqual(state.observed_state, "RUNNING")
        self.assertEqual(state.last_monitoring_kind, MonitoringSnapshotKind.PERIODIC)
        self.assertEqual(state.metrics["memory_kb"], 1234)
        self.assertEqual(state.updated_at, 2.0)

    async def test_snapshots_are_yielded_in_order(self):
        service = ServiceInstanceRef(ServiceKind.RECORDING, "deploy")
        client = FakeServiceMonitoringClient()
        first = MonitoringSnapshot(service, MonitoringSnapshotKind.EVENT, state="PAUSED")
        second = MonitoringSnapshot(service, MonitoringSnapshotKind.EVENT, state="RUNNING")
        client.push_snapshot(first)
        client.push_snapshot(second)
        facade = ServiceMonitoringFacade(client)

        observed = []
        async for snapshot in facade.snapshots(service):
            observed.append(snapshot)

        self.assertEqual(observed, [first, second])


if __name__ == "__main__":
    unittest.main()