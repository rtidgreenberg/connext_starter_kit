#!/usr/bin/env python3
"""Headless tests for Record tab live snapshot wiring."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


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
from fakes import FakeHandle, FakeSpawner


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

    async def test_monitoring_updates_merge_into_gui_launch_and_retain_latest_kinds(self):
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
        monitoring_client = FakeServiceMonitoringClient()
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.CONFIG,
            state="configured",
            details={
                "application_guid": "app-guid-1",
                "process_id": 9001,
                "host_name": "dev-host",
                "topics": ["Square"],
            },
            observed_at=20.0,
        ))
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.CONFIG,
            state="configured",
            details={
                "application_guid": "app-guid-1",
                "process_id": 9001,
                "host_name": "dev-host",
                "topics": ["Circle"],
            },
            observed_at=20.5,
        ))
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="observed",
            metrics={"cpu_percent": 3.5},
            details={"db_file": "log_dir/recording/data_0.db"},
            observed_at=21.0,
        ))
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 22.0,
        )

        first_view = await controller.refresh_view()
        first_update_count = len(controller.last_monitoring_updates)
        second_view = await controller.refresh_view()

        self.assertEqual(len(first_view.candidates), 1)
        self.assertTrue(first_view.selected_candidate_id.startswith("monitoring:"))
        self.assertEqual(first_view.selected_candidate.pid, "9001")
        self.assertEqual(first_view.observed_state, "observed")
        self.assertEqual(first_view.selected_candidate.current_file, "log_dir/recording/data_0.db")
        self.assertIn(("current_file", "log_dir/recording/data_0.db"), first_view.monitoring_summary)
        self.assertIn(("topics", "['Square', 'Circle']"), first_view.monitoring_summary)
        self.assertNotIn(("cpu_percent", "3.5"), first_view.monitoring_summary)
        self.assertEqual(first_update_count, 3)
        self.assertEqual(len(controller.last_monitoring_updates), 0)
        self.assertEqual(second_view.selected_candidate_id, first_view.selected_candidate_id)
        self.assertNotIn(("cpu_percent", "3.5"), second_view.monitoring_summary)
        self.assertIn(("topics", "['Square', 'Circle']"), second_view.monitoring_summary)

    async def test_monitoring_updates_are_taken_for_each_spawned_recording_service(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(4218), FakeHandle(4219)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        first = manager.launch(
            launch_request(label="Recorder A"),
            launch_id="launch-a",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        second = manager.launch(
            launch_request(label="Recorder B"),
            launch_id="launch-b",
            session_guid="22222222-3333-4444-5555-666666666666",
        )
        monitoring_client = FakeServiceMonitoringClient()
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=first.identity.service_ref,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="observed",
            metrics={"cpu_percent": 1.0},
            observed_at=20.0,
        ))
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=second.identity.service_ref,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="observed",
            metrics={"cpu_percent": 2.0},
            observed_at=21.0,
        ))
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",), selected_candidate_id="launch-a"),
            clock=lambda: 22.0,
        )

        await controller.refresh_view()

        updated_services = {snapshot.service.name for snapshot in controller.last_monitoring_updates}
        self.assertEqual(updated_services, {
            first.identity.service_ref.name,
            second.identity.service_ref.name,
        })

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

    async def test_launch_recording_uses_operator_fields_and_selects_new_candidate(self):
        spawner = FakeSpawner(FakeHandle(5001))
        manager = ServiceProcessManager(
            spawner=spawner,
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )

        launch = controller.launch_recording({
            "label": "Manual Recorder",
            "config_paths": ["record.xml", "qos.xml"],
            "config_name": "manual_deploy",
            "data_domain_id": 63,
            "admin_domain_id": 61,
            "monitoring_domain_id": 62,
            "log_directory": "test_output/recording_logs",
            "topic_allow": "Square,Robot*",
            "topic_deny": "rti/*,internal/*",
            "verbosity": "WARN:WARN",
            "executable": "/opt/rti/bin/rtirecordingservice",
            "working_dir": "services/rs_gui/manual",
            "extra_args": ["-DDB_DIR=test_output/db", "-DREC_SESSION_NAME=Manual Recorder Session"],
        })
        view = await controller.refresh_view()

        self.assertEqual(launch.request.config_name, "manual_deploy")
        self.assertEqual(launch.identity.intent.config_paths, ("record.xml", "qos.xml"))
        self.assertEqual(launch.identity.intent.admin_domain_id, 61)
        self.assertEqual(launch.identity.intent.monitoring_domain_id, 62)
        self.assertIn("-appName", spawner.calls[0])
        self.assertIn("-DDOMAIN_ID=63", spawner.calls[0])
        self.assertIn("-DADMIN_DOMAIN_ID=61", spawner.calls[0])
        self.assertIn("-DREC_STATUS_PERIOD_SEC=0", spawner.calls[0])
        self.assertIn("-DREC_STATUS_PERIOD_NSEC=500000000", spawner.calls[0])
        self.assertIn("-DREC_FILENAME_EXPR=data_xcdr_%auto:0-9%.db", spawner.calls[0])
        self.assertIn("-DREC_LOG_DIR=test_output/recording_logs/xcdr", spawner.calls[0])
        self.assertIn("-DREC_TOPIC_ALLOW=Square,Robot*", spawner.calls[0])
        self.assertIn("-DREC_TOPIC_DENY=rti/*,internal/*", spawner.calls[0])
        self.assertIn("-DDB_DIR=test_output/db", spawner.calls[0])
        self.assertIn("-DREC_SESSION_NAME=Manual_Recorder_Session", spawner.calls[0])
        self.assertNotIn("-DREC_SESSION_NAME=Manual Recorder Session", spawner.calls[0])
        self.assertEqual(launch.request.environment["REC_FILENAME_EXPR"], "data_xcdr_%auto:0-9%.db")
        self.assertEqual(launch.request.environment["REC_LOG_DIR"], "test_output/recording_logs/xcdr")
        self.assertEqual(launch.request.environment["REC_TOPIC_ALLOW"], "Square,Robot*")
        self.assertEqual(launch.request.environment["REC_TOPIC_DENY"], "rti/*,internal/*")
        self.assertEqual(view.selected_candidate_id, launch.launch_id)
        self.assertEqual(view.selected_candidate.pid, "5001")
        self.assertEqual(view.launch.config_name, "manual_deploy")
        self.assertEqual(view.launch.data_domain_id, 63)
        self.assertEqual(view.launch.log_directory, "test_output/recording_logs/xcdr")
        self.assertEqual(view.launch.topic_allow, "Square,Robot*")
        self.assertEqual(view.launch.topic_deny, "rti/*,internal/*")

    async def test_launch_recording_json_format_updates_filename_and_log_directory(self):
        spawner = FakeSpawner(FakeHandle(5001))
        manager = ServiceProcessManager(
            spawner=spawner,
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )

        launch = controller.launch_recording({
            "config_paths": ["record.xml"],
            "config_name": "template",
            "storage_format": "JSON",
            "log_directory": "test_output/recording_logs",
        })

        self.assertIn("-DREC_STORAGE_FORMAT=JSON_SQLITE", spawner.calls[0])
        self.assertIn("-DREC_FILENAME_EXPR=data_json_%auto:0-9%.db", spawner.calls[0])
        self.assertIn("-DREC_LOG_DIR=test_output/recording_logs/json", spawner.calls[0])
        self.assertEqual(launch.request.environment["REC_FILENAME_EXPR"], "data_json_%auto:0-9%.db")
        self.assertEqual(launch.request.environment["REC_LOG_DIR"], "test_output/recording_logs/json")

    async def test_launch_recording_uses_detected_nddshome_when_environment_is_unset(self):
        spawner = FakeSpawner(FakeHandle(5001))
        manager = ServiceProcessManager(
            spawner=spawner,
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )

        with patch.dict(os.environ, {"NDDSHOME": "", "RTI_LICENSE_FILE": ""}, clear=False), \
                patch("gui.tabs.record_controller.detect_nddshome", return_value="/opt/rti"), \
                patch("gui.tabs.record_controller.ensure_rti_license", return_value="/opt/rti/rti_license.dat"):
            launch = controller.launch_recording({
                "config_paths": ["record.xml"],
                "config_name": "manual_deploy",
            })

        self.assertEqual(launch.request.environment["NDDSHOME"], "/opt/rti")
        self.assertEqual(launch.request.environment["RTI_LICENSE_FILE"], "/opt/rti/rti_license.dat")
        self.assertEqual(spawner.calls[0][0], "/opt/rti/bin/rtirecordingservice")

    async def test_launch_view_parses_recording_service_names_from_xml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as temp:
            temp.write("<dds><recording_service name='alpha'/><recording_service name='beta'/></dds>")
            config_path = temp.name
        self.addCleanup(lambda: os.path.exists(config_path) and os.remove(config_path))
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(5001)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(
                local_hostnames=("dev-host",),
                launch_config_paths=(config_path,),
                launch_config_name="alpha",
            ),
            clock=lambda: 12.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(view.launch.available_config_names, ("alpha", "beta"))
        self.assertEqual(view.launch.config_paths, (config_path,))

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

    async def test_successful_shutdown_reaps_gui_owned_process_promptly(self):
        class ShutdownExitingAdminClient(FakeServiceAdminClient):
            def __init__(self, handle):
                super().__init__()
                self._handle = handle

            async def send_command(self, request):
                if request.command == ServiceCommand.SHUTDOWN:
                    self._handle.returncode = 0
                return await super().send_command(request)

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
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(ShutdownExitingAdminClient(handle)),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        await controller.refresh_view()

        shutdown_outcome = await controller.execute_action("shutdown")
        refreshed = manager.refresh(launch.launch_id)

        self.assertTrue(shutdown_outcome.ok)
        self.assertTrue(shutdown_outcome.payload["process_exit_observed"])
        self.assertEqual(refreshed.state.value, "exited")
        self.assertEqual(refreshed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
