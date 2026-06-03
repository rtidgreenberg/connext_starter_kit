#!/usr/bin/env python3
"""Headless tests for rs_gui_v2 Replay tab controller wiring."""

import os
import sys
import unittest
import xml.etree.ElementTree as ET


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand
from app_core import CommandStatus
from app_core.services import ServiceCommandOutcome
from app_core.services import (
    FakeServiceMonitoringClient,
    MonitoringSnapshot,
    MonitoringSnapshotKind,
    ServiceAdminFacade,
    ServiceCandidateSelection,
    ServiceCommand,
    ServiceInstanceRef,
    ServiceKind,
    ServiceMonitoringFacade,
    ServiceProcessCandidate,
    ServiceProcessManager,
)
from app_core.services.rti_admin import ENTITY_STATE_PAUSED, ENTITY_STATE_RUNNING, ENTITY_STATE_STOPPED
from gui.tabs import (
    ReplayLaunchViewModel,
    ReplayTabController,
    ReplayTabControllerConfig,
    ReplayTargetRow,
    build_replay_launch_command,
)
from fakes import FakeHandle, FakeSpawner


class FakeServiceAdminClient:
    def __init__(self):
        self.requests = []

    async def check_readiness(self, service):
        raise AssertionError("readiness is not used by these tests")

    async def send_command(self, request):
        self.requests.append(request)
        return ServiceCommandOutcome(
            request=request,
            status=CommandStatus.ACKNOWLEDGED,
            message="ack",
        )


class TestReplayTabController(unittest.IsolatedAsyncioTestCase):
    def test_replay_service_xml_consumes_launch_variables(self):
        xml_path = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "replay_service_config.xml"))
        root = ET.parse(xml_path).getroot()
        xml_text = ET.tostring(root, encoding="unicode")

        for config_name in ("xcdr", "json"):
            self.assertIsNotNone(root.find(f"./replay_service[@name='{config_name}']"))
        for variable_name in (
                "REPLAY_DOMAIN_ID",
                "REPLAY_ADMIN_DOMAIN_ID",
                "REPLAY_MON_DOMAIN_ID",
                "REPLAY_XCDR_STORAGE_FORMAT",
                "REPLAY_XCDR_DATABASE_DIR",
                "REPLAY_JSON_STORAGE_FORMAT",
                "REPLAY_JSON_DATABASE_DIR",
                "REPLAY_PLAYBACK_RATE",
                "REPLAY_ENABLE_LOOPING",
                "REPLAY_TOPIC_ALLOW",
                "REPLAY_TOPIC_DENY",
        ):
            self.assertIn(f"$({variable_name})", xml_text)

    def test_replay_launch_command_preserves_operator_fields(self):
        command = build_replay_launch_command(ReplayLaunchViewModel(
            label="Manual Replay",
            config_paths=("services/replay_service_config.xml", "dds/qos/DDS_QOS_PROFILES.xml"),
            config_name="json",
            data_domain_id=63,
            admin_domain_id=61,
            monitoring_domain_id=62,
            database_path="log_dir/xcdr",
            playback_rate=2.5,
            loop=True,
            topic_allow="Robot*",
            topic_deny="Debug*",
            verbosity="WARN:WARN",
            executable="/opt/rti/bin/rtireplayservice",
            working_dir="services/rs_gui_v2/manual",
            extra_args=("-DUSER_FLAG=1",),
        ))

        self.assertEqual(command.command_type, "service.launch_replay")
        self.assertEqual(command.target, "replay")
        self.assertEqual(command.payload["label"], "Manual Replay")
        self.assertEqual(command.payload["config_paths"], [
            "services/replay_service_config.xml",
            "dds/qos/DDS_QOS_PROFILES.xml",
        ])
        self.assertEqual(command.payload["config_name"], "json")
        self.assertEqual(command.payload["data_domain_id"], 63)
        self.assertEqual(command.payload["admin_domain_id"], 61)
        self.assertEqual(command.payload["monitoring_domain_id"], 62)
        self.assertEqual(command.payload["database_path"], "log_dir/xcdr")
        self.assertEqual(command.payload["extra_args"], ["-DUSER_FLAG=1"])

    async def test_mock_controller_refreshes_seeded_replay_view(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        view = await controller.refresh_view()

        self.assertEqual(view.selected_target.control_name, "replay_service_2d91c4a0")
        self.assertTrue(view.action_by_id["start"].enabled)
        self.assertFalse(view.action_by_id["pause"].enabled)

    async def test_start_pause_resume_and_stop_update_replay_state(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        start = await controller.handle_command(AppCommand(
            command_type="replay.start",
            payload={
                "target_id": "launch-replay-main",
                "database_path": "services/replay_input/robot_run_03",
                "playback_rate": 2.0,
                "loop": True,
                "time_window": "00:00:00 - 00:01:00",
                "qos_file_path": "dds/qos/custom_qos.xml",
                "participant_qos_profile": "MyLib::MyParticipant",
                "writer_qos_profile": "MyLib::MyWriter",
            },
            command_id="start-replay",
            created_at=1.0,
        ))
        running_view = await controller.refresh_view()

        self.assertTrue(start.ok)
        self.assertEqual(start.payload["state"], "RUNNING")
        self.assertEqual(running_view.observed_state, "RUNNING")
        self.assertEqual(running_view.playback_rate, 2.0)
        self.assertTrue(running_view.loop)
        self.assertEqual(running_view.qos_file_path, "dds/qos/custom_qos.xml")
        self.assertEqual(running_view.participant_qos_profile, "MyLib::MyParticipant")
        self.assertEqual(running_view.writer_qos_profile, "MyLib::MyWriter")
        self.assertTrue(running_view.action_by_id["pause"].enabled)

        pause = await controller.handle_command(AppCommand("replay.pause", command_id="pause-replay", created_at=2.0))
        paused_view = await controller.refresh_view()
        resume = await controller.handle_command(AppCommand("replay.resume", command_id="resume-replay", created_at=3.0))
        resumed_view = await controller.refresh_view()
        stop = await controller.handle_command(AppCommand("replay.stop", command_id="stop-replay", created_at=4.0))
        stopped_view = await controller.refresh_view()

        self.assertEqual(pause.payload["state"], "PAUSED")
        self.assertTrue(paused_view.action_by_id["resume"].enabled)
        self.assertEqual(resume.payload["state"], "RUNNING")
        self.assertEqual(resumed_view.observed_state, "RUNNING")
        self.assertEqual(stop.payload["state"], "STOPPED")
        self.assertEqual(stopped_view.observed_state, "STOPPED")

    async def test_playback_commands_dispatch_replay_admin_custom_state_updates(self):
        admin_client = FakeServiceAdminClient()
        controller = ReplayTabController(
            admin_facade=ServiceAdminFacade(admin_client),
            targets=(ReplayTargetRow(
                target_id="monitoring:replay:xcdr",
                label="Replay",
                control_name="rs_gui_v2_replay_1234",
                source="monitoring",
                hostname="dev-host",
                state="PAUSED",
                progress="",
            ),),
            config=ReplayTabControllerConfig(
                service=ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_v2_replay_1234", admin_domain_id=61, monitoring_domain_id=62),
                selected_target_id="monitoring:replay:xcdr",
                database_path="services/replay_input/robot_run_03",
            ),
            clock=lambda: 10.0,
        )
        controller._last_selection = ServiceCandidateSelection(
            candidates=(ServiceProcessCandidate(
                candidate_id="monitoring:replay:xcdr",
                service=ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_v2_replay_1234", admin_domain_id=61, monitoring_domain_id=62),
                source="monitoring",
                display_label="Replay",
                launch_id="launch-id",
                pid=7007,
                hostname="dev-host",
                observed_state="PAUSED",
                details={
                    "admin_resource_name": "xcdr",
                    "resource_id": "/replay_services/xcdr",
                },
                alive=True,
                owns_process=False,
                confidence=1.0,
                first_seen_at=1.0,
                last_seen_at=2.0,
            ),),
            selected_candidate_id="monitoring:replay:xcdr",
        )

        start = await controller.handle_command(AppCommand(
            "replay.start",
            payload={"database_path": "services/replay_input/robot_run_03"},
            command_id="start-replay",
            created_at=1.0,
        ))
        pause = await controller.handle_command(AppCommand("replay.pause", command_id="pause-replay", created_at=2.0))
        resume = await controller.handle_command(AppCommand("replay.resume", command_id="resume-replay", created_at=3.0))
        stop = await controller.handle_command(AppCommand("replay.stop", command_id="stop-replay", created_at=4.0))

        self.assertTrue(start.ok)
        self.assertTrue(pause.ok)
        self.assertTrue(resume.ok)
        self.assertTrue(stop.ok)
        self.assertEqual([request.command for request in admin_client.requests], [
            ServiceCommand.CUSTOM,
            ServiceCommand.CUSTOM,
            ServiceCommand.CUSTOM,
            ServiceCommand.CUSTOM,
        ])
        self.assertEqual([request.parameters["resource_path"] for request in admin_client.requests], [
            "/replay_services/xcdr/state",
            "/replay_services/xcdr/state",
            "/replay_services/xcdr/state",
            "/replay_services/xcdr/state",
        ])
        self.assertEqual([request.parameters["octet_body"] for request in admin_client.requests], [
            [ENTITY_STATE_RUNNING],
            [ENTITY_STATE_PAUSED],
            [ENTITY_STATE_RUNNING],
            [ENTITY_STATE_STOPPED],
        ])

    async def test_select_target_updates_selected_row(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        result = await controller.handle_command(AppCommand(
            command_type="replay.select_target",
            payload={"target_id": "discovery:replay:archive"},
            command_id="select-replay",
            created_at=5.0,
        ))
        view = await controller.refresh_view()

        self.assertTrue(result.ok)
        self.assertEqual(view.selected_target_id, "discovery:replay:archive")
        self.assertEqual(view.selected_target.control_name, "replay_archive_external")
        selected = {row.control_name: row.selected for row in view.targets}
        self.assertFalse(selected["replay_service_2d91c4a0"])
        self.assertTrue(selected["replay_archive_external"])

    async def test_start_without_database_reports_validation_error(self):
        controller = ReplayTabController(
            targets=(ReplayTargetRow(
                target_id="target",
                label="Replay",
                control_name="replay_service_empty",
                source="local",
                hostname="dev-host",
                state="STOPPED",
                progress="0%",
            ),),
            config=ReplayTabControllerConfig(selected_target_id="target"),
        )

        with self.assertRaisesRegex(ValueError, "recording database path"):
            await controller.handle_command(AppCommand("replay.start"))

    async def test_launch_replay_builds_process_request_and_view_row(self):
        handle = FakeHandle(7007)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        controller = ReplayTabController(
            process_manager=manager,
            config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )

        launch = controller.launch_replay({
            "label": "Manual Replay",
            "config_paths": ["services/replay_service_config.xml", "dds/qos/DDS_QOS_PROFILES.xml"],
            "config_name": "json",
            "data_domain_id": 63,
            "admin_domain_id": 61,
            "monitoring_domain_id": 62,
            "database_path": "log_dir/xcdr",
            "playback_rate": 2.0,
            "loop": True,
            "topic_allow": "Robot*",
            "topic_deny": "Debug*",
            "executable": "/opt/rti/bin/rtireplayservice",
            "extra_args": ["-DREPLAY_DATABASE_DIR=ignored", "-DREPLAY_JSON_DATABASE_DIR=ignored", "-DUSER_FLAG=1"],
        })
        view = await controller.refresh_view()

        self.assertEqual(launch.identity.intent.kind, ServiceKind.REPLAY)
        self.assertEqual(launch.pid, 7007)
        self.assertEqual(launch.request.config_name, "json")
        self.assertEqual(launch.identity.intent.admin_domain_id, 61)
        self.assertEqual(launch.identity.intent.monitoring_domain_id, 62)
        self.assertEqual(view.selected_target_id, launch.launch_id)
        self.assertEqual(view.selected_target.pid, "7007")
        self.assertEqual(view.selected_target.source, "gui_launch")
        self.assertTrue(view.selected_target.owned)
        self.assertEqual(view.selected_target.state, "running")
        command_line = " ".join(launch.command_line)
        self.assertIn("/opt/rti/bin/rtireplayservice", command_line)
        self.assertIn("-appName", command_line)
        self.assertIn("-remoteAdministrationDomainId 61", command_line)
        self.assertIn("-remoteMonitoringDomainId 62", command_line)
        self.assertIn("-DREPLAY_DATABASE_DIR=log_dir/xcdr", command_line)
        self.assertIn("-DREPLAY_JSON_DATABASE_DIR=log_dir/xcdr", command_line)
        self.assertIn("-DREPLAY_JSON_STORAGE_FORMAT=XCDR", command_line)
        self.assertIn("-DREPLAY_ENABLE_LOOPING=true", command_line)
        self.assertIn("-DUSER_FLAG=1", command_line)
        self.assertNotIn("-DREPLAY_DATABASE_DIR=ignored", command_line)
        self.assertNotIn("-DREPLAY_JSON_DATABASE_DIR=ignored", command_line)

    async def test_shutdown_dispatches_replay_admin_command(self):
        handle = FakeHandle(7007)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        admin_client = FakeServiceAdminClient()
        controller = ReplayTabController(
            process_manager=manager,
            admin_facade=ServiceAdminFacade(admin_client),
            config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        launch = controller.launch_replay({
            "config_name": "xcdr",
            "admin_domain_id": 61,
            "monitoring_domain_id": 62,
            "executable": "/opt/rti/bin/rtireplayservice",
        })
        await controller.refresh_view()

        outcome = await controller.execute_action("shutdown", timeout_sec=2.0)

        self.assertTrue(outcome.ok)
        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.SHUTDOWN])
        self.assertEqual(admin_client.requests[0].service, launch.identity.service_ref)
        self.assertEqual(admin_client.requests[0].parameters["admin_resource_name"], "xcdr")
        self.assertEqual(admin_client.requests[0].timeout_sec, 2.0)

    async def test_refresh_merges_replay_monitoring_with_gui_launch(self):
        handle = FakeHandle(7007)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        monitoring_client = FakeServiceMonitoringClient()
        controller = ReplayTabController(
            process_manager=manager,
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        launch = controller.launch_replay({
            "config_name": "xcdr",
            "admin_domain_id": 61,
            "monitoring_domain_id": 62,
            "executable": "/opt/rti/bin/rtireplayservice",
        })
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.CONFIG,
            state="configured",
            details={
                "application_guid": "abc123",
                "admin_resource_name": "xcdr",
                "resource_id": "/replay_services/xcdr",
                "process_id": 7007,
                "host_name": "dev-host",
                "db_directory": "log_dir/recording_1780085154",
            },
        ))

        view = await controller.refresh_view()

        self.assertEqual(len(view.targets), 1)
        self.assertEqual(view.selected_target.pid, "7007")
        self.assertEqual(view.selected_target.confidence, "1.00")
        self.assertTrue(view.selected_target_id.startswith("monitoring:replay:"))
        self.assertEqual(controller.last_selection.selected_candidate.launch_id, launch.launch_id)
        self.assertEqual(controller.last_selection.selected_candidate.details["resource_id"], "/replay_services/xcdr")


if __name__ == "__main__":
    unittest.main()
