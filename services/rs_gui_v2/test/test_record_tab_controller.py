#!/usr/bin/env python3
"""Headless tests for Record tab live snapshot wiring."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.events import CommandStatus
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
    ServiceKind,
    ServiceLaunchIntent,
    ServiceMonitoringFacade,
    ServiceProcessLaunchRequest,
    ServiceProcessManager,
)
from gui.tabs.record_controller import RecordTabController, RecordTabControllerConfig


class FakeHandle:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.terminate_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1


class FakeSpawner:
    def __init__(self, *handles):
        self.handles = list(handles)
        self.calls = []

    def start(self, command_line, working_dir="", environment=None):
        self.calls.append(tuple(command_line))
        if not self.handles:
            raise RuntimeError("no fake handles queued")
        return self.handles.pop(0)


def launch_request(label="Recording Service"):
    return ServiceProcessLaunchRequest(
        intent=ServiceLaunchIntent(
            kind=ServiceKind.RECORDING,
            label=label,
            admin_domain_id=0,
            monitoring_domain_id=0,
            config_paths=("record.xml", "qos.xml"),
        ),
        config_name="deploy",
        executable="/opt/rti/bin/rtirecordingservice",
    )


class TestRecordTabController(unittest.IsolatedAsyncioTestCase):
    async def test_launched_process_appears_in_record_selector(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(4218)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        launch = manager.launch(
            launch_request(),
            launch_id="launch-main",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(view.selected_candidate_id, "launch-main")
        self.assertEqual(view.candidates[0].control_name, launch.identity.service_ref.name)
        self.assertEqual(view.candidates[0].pid, "4218")
        self.assertEqual(view.candidates[0].hostname, "dev-host")
        self.assertEqual(view.observed_state, "running")
        self.assertTrue(view.action_by_id["pause"].enabled)

    async def test_readiness_and_monitoring_enrich_record_view(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(4218)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        launch = manager.launch(
            launch_request(),
            launch_id="launch-main",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        admin_client = FakeServiceAdminClient()
        admin_client.set_readiness(AdminReadiness(
            service=launch.identity.service_ref,
            status=AdminReadinessStatus.READY,
            matched_request_writers=1,
            matched_reply_readers=1,
            message="ready",
            checked_at=11.0,
        ))
        monitoring_client = FakeServiceMonitoringClient()
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.CONFIG,
            state="PAUSED",
            metrics={"memory_mb": 200},
            details={"process_id": 4218, "host_name": "dev-host", "sessions": 1},
            observed_at=20.0,
        ))
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(admin_client),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 22.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(view.readiness, "request+reply matched")
        self.assertEqual(view.observed_state, "PAUSED")
        self.assertIn(("memory_mb", "200"), view.monitoring_summary)
        self.assertIn(("sessions", "1"), view.monitoring_summary)
        self.assertFalse(view.action_by_id["pause"].enabled)
        self.assertTrue(view.action_by_id["resume"].enabled)

    async def test_service_admin_actions_update_command_history(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(4218)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        manager.launch(
            launch_request(),
            launch_id="launch-main",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        admin_client = FakeServiceAdminClient()
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(admin_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",), tag_value="night_run"),
            clock=lambda: 12.0,
        )
        await controller.refresh_view()

        pause_outcome = await controller.execute_action("pause")
        tag_outcome = await controller.execute_action("tag", description="operator tag")
        view = await controller.refresh_view()

        self.assertTrue(pause_outcome.ok)
        self.assertTrue(tag_outcome.ok)
        self.assertEqual([request.command for request in admin_client.requests], [
            ServiceCommand.PAUSE,
            ServiceCommand.TAG,
        ])
        self.assertEqual(admin_client.requests[1].parameters["tag_name"], "night_run")
        self.assertEqual(len(controller.command_history), 2)
        self.assertEqual([row.command for row in view.command_history], ["pause", "tag"])

    async def test_duplicate_live_candidates_disable_admin_actions(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(4218), FakeHandle(4219)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        manager.launch(
            launch_request(),
            launch_id="launch-a",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        manager.launch(
            launch_request(),
            launch_id="launch-b",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",), selected_candidate_id="launch-a"),
            clock=lambda: 12.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(len(view.candidates), 2)
        self.assertTrue(all(row.conflict for row in view.candidates))
        self.assertFalse(view.action_by_id["pause"].enabled)
        self.assertIn("duplicate service admin target", view.diagnostics)

    async def test_failed_shutdown_enables_guarded_local_termination(self):
        handle = FakeHandle(4218)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        launch = manager.launch(
            launch_request(),
            launch_id="launch-main",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        admin_client = FakeServiceAdminClient()
        admin_client.queue_outcome(ServiceCommandOutcome(
            request=ServiceCommandRequest(
                service=launch.identity.service_ref,
                command=ServiceCommand.SHUTDOWN,
                command_id="shutdown-timeout",
                created_at=11.0,
            ),
            status=CommandStatus.TIMEOUT,
            message="shutdown timed out",
            created_at=12.0,
        ))
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(admin_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 13.0,
        )
        await controller.refresh_view()

        shutdown_outcome = await controller.execute_action("shutdown")
        view = await controller.refresh_view()
        terminate_outcome = await controller.execute_action("terminate_local")

        self.assertEqual(shutdown_outcome.status, CommandStatus.TIMEOUT)
        self.assertTrue(view.action_by_id["terminate_local"].enabled)
        self.assertTrue(terminate_outcome.requested)
        self.assertEqual(handle.terminate_calls, 1)


if __name__ == "__main__":
    unittest.main()
