#!/usr/bin/env python3
"""Headless tests for rs_gui Replay tab controller wiring."""

import os
import sys
import tempfile
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
    AdminReadiness,
    AdminReadinessStatus,
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
from app_core.services.rti_admin import ACTION_UPDATE, ENTITY_STATE_PAUSED, ENTITY_STATE_RUNNING, ENTITY_STATE_STOPPED
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
        return AdminReadiness(
            service=service,
            status=AdminReadinessStatus.READY,
            matched_request_writers=1,
            matched_reply_readers=1,
            message="request+reply matched",
        )

    async def send_command(self, request):
        self.requests.append(request)
        return ServiceCommandOutcome(
            request=request,
            status=CommandStatus.ACKNOWLEDGED,
            message="ack",
        )


class TestReplayTabController(unittest.IsolatedAsyncioTestCase):
    def _make_replay_database_dir(self) -> str:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        metadata_path = os.path.join(tempdir.name, "metadata.db")
        data_path = os.path.join(tempdir.name, "data_0.db")
        with open(metadata_path, "w", encoding="utf-8"):
            pass
        with open(data_path, "w", encoding="utf-8"):
            pass
        return tempdir.name

    def test_replay_service_xml_consumes_launch_variables(self):
        xml_path = os.path.abspath(
            os.path.join(SCRIPT_DIR, "..", "..", "..", "dds", "qos", "replay_service_config.xml")
        )
        root = ET.parse(xml_path).getroot()
        xml_text = ET.tostring(root, encoding="unicode")

        for config_name in ("template", "xcdr", "json"):
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
            config_paths=("dds/qos/replay_service_config.xml", "dds/qos/DDS_QOS_PROFILES.xml"),
            config_name="json",
            data_domain_id=63,
            admin_domain_id=61,
            monitoring_domain_id=62,
            database_path="services/rs_gui/log_data/xcdr",
            playback_rate=2.5,
            loop=True,
            topic_allow="Robot*",
            topic_deny="Debug*",
            verbosity="WARN:WARN",
            executable="/opt/rti/bin/rtireplayservice",
            working_dir="services/rs_gui/manual",
            extra_args=("-DUSER_FLAG=1",),
        ))

        self.assertEqual(command.command_type, "service.launch_replay")
        self.assertEqual(command.target, "replay")
        self.assertEqual(command.payload["label"], "Manual Replay")
        self.assertEqual(command.payload["config_paths"], [
            "dds/qos/replay_service_config.xml",
            "dds/qos/DDS_QOS_PROFILES.xml",
        ])
        self.assertEqual(command.payload["config_name"], "json")
        self.assertEqual(command.payload["data_domain_id"], 63)
        self.assertEqual(command.payload["admin_domain_id"], 61)
        self.assertEqual(command.payload["monitoring_domain_id"], 62)
        self.assertEqual(command.payload["database_path"], "services/rs_gui/log_data/xcdr")
        self.assertEqual(command.payload["service_verbosity"], "WARN")
        self.assertEqual(command.payload["api_verbosity"], "WARN")
        self.assertEqual(command.payload["verbosity"], "WARN:WARN")
        self.assertEqual(command.payload["extra_args"], ["-DUSER_FLAG=1"])

    def test_launch_replay_accepts_split_service_and_api_verbosity(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(4218)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        replay_db = self._make_replay_database_dir()
        controller = ReplayTabController(
            process_manager=manager,
            config=ReplayTabControllerConfig(launch_database_path=replay_db),
            clock=lambda: 12.0,
        )

        launch = controller.launch_replay({
            "database_path": replay_db,
            "service_verbosity": "WARN",
            "api_verbosity": "ALL",
        })

        self.assertEqual(launch.request.verbosity, "WARN:ALL")

    async def test_mock_controller_refreshes_seeded_replay_view(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        view = await controller.refresh_view()

        self.assertEqual(view.selected_target.control_name, "replay_service_2d91c4a0")
        self.assertEqual(view.readiness, "not checked")
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
                control_name="rs_gui_replay_1234",
                source="monitoring",
                hostname="dev-host",
                state="PAUSED",
                progress="",
            ),),
            config=ReplayTabControllerConfig(
                service=ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", admin_domain_id=61, monitoring_domain_id=62),
                selected_target_id="monitoring:replay:xcdr",
                database_path="services/replay_input/robot_run_03",
            ),
            clock=lambda: 10.0,
        )
        controller._last_selection = ServiceCandidateSelection(
            candidates=(ServiceProcessCandidate(
                candidate_id="monitoring:replay:xcdr",
                service=ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", admin_domain_id=61, monitoring_domain_id=62),
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
            "/replay_services/template/state",
            "/replay_services/template/state",
            "/replay_services/template/state",
            "/replay_services/template/state",
        ])
        self.assertEqual([request.parameters["entity_state_value"] for request in admin_client.requests], [
            ENTITY_STATE_RUNNING,
            ENTITY_STATE_PAUSED,
            ENTITY_STATE_RUNNING,
            ENTITY_STATE_STOPPED,
        ])

    async def test_next_tag_dispatches_replay_current_tag_admin_update(self):
        admin_client = FakeServiceAdminClient()
        controller = ReplayTabController(
            admin_facade=ServiceAdminFacade(admin_client),
            targets=(ReplayTargetRow(
                target_id="monitoring:replay:xcdr",
                label="Replay",
                control_name="rs_gui_replay_1234",
                source="monitoring",
                hostname="dev-host",
                state="RUNNING",
                progress="running",
            ),),
            config=ReplayTabControllerConfig(
                service=ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", admin_domain_id=61, monitoring_domain_id=62),
                selected_target_id="monitoring:replay:xcdr",
                database_path="services/replay_input/robot_run_03",
            ),
            clock=lambda: 10.0,
        )
        controller._last_selection = ServiceCandidateSelection(
            candidates=(ServiceProcessCandidate(
                candidate_id="monitoring:replay:xcdr",
                service=ServiceInstanceRef(ServiceKind.REPLAY, "rs_gui_replay_1234", admin_domain_id=61, monitoring_domain_id=62),
                source="monitoring",
                display_label="Replay",
                launch_id="launch-id",
                pid=7007,
                hostname="dev-host",
                observed_state="RUNNING",
                details={
                    "admin_resource_name": "template",
                    "resource_id": "/replay_services/template",
                },
                alive=True,
                owns_process=False,
                confidence=1.0,
                first_seen_at=1.0,
                last_seen_at=2.0,
            ),),
            selected_candidate_id="monitoring:replay:xcdr",
        )

        result = await controller.handle_command(AppCommand(
            "replay.next_tag",
            payload={
                "target_id": "monitoring:replay:xcdr",
                "database_path": "services/replay_input/robot_run_03",
                "tag_name": "tag_alpha",
            },
            command_id="next-tag",
            created_at=5.0,
        ))

        self.assertTrue(result.ok)
        self.assertEqual(len(admin_client.requests), 1)
        request = admin_client.requests[0]
        self.assertEqual(request.command, ServiceCommand.CUSTOM)
        self.assertEqual(request.parameters["action"], ACTION_UPDATE)
        self.assertEqual(request.parameters["resource_path"], "/replay_services/template/playback/current_tag")
        self.assertEqual(request.parameters["string_body"], "tag_alpha")

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
        database_dir = self._make_replay_database_dir()
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
            "config_paths": ["dds/qos/replay_service_config.xml", "dds/qos/DDS_QOS_PROFILES.xml"],
            "config_name": "json",
            "data_domain_id": 63,
            "admin_domain_id": 61,
            "monitoring_domain_id": 62,
            "database_path": database_dir,
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
        self.assertEqual(view.selected_target.state, "RUNNING")
        command_line = " ".join(launch.command_line)
        repo_root = os.path.dirname(os.path.dirname(PARENT_DIR))
        self.assertIn("/opt/rti/bin/rtireplayservice", command_line)
        self.assertIn("-appName", command_line)
        self.assertIn("-remoteAdministrationDomainId 61", command_line)
        self.assertIn("-remoteMonitoringDomainId 62", command_line)
        self.assertIn(f"-DREPLAY_DATABASE_DIR={database_dir}", command_line)
        self.assertIn(f"-DREPLAY_JSON_DATABASE_DIR={database_dir}", command_line)
        self.assertIn("-DREPLAY_JSON_STORAGE_FORMAT=XCDR", command_line)
        self.assertIn("-DREPLAY_ENABLE_LOOPING=true", command_line)
        self.assertIn("-DUSER_FLAG=1", command_line)
        self.assertNotIn("-DREPLAY_DATABASE_DIR=ignored", command_line)
        self.assertNotIn("-DREPLAY_JSON_DATABASE_DIR=ignored", command_line)

    async def test_owned_replay_does_not_toggle_to_observed_with_monitoring_updates(self):
        database_dir = self._make_replay_database_dir()
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(7007)),
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
            "database_path": database_dir,
            "executable": "/opt/rti/bin/rtireplayservice",
        })
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="observed",
            observed_at=13.0,
        ))

        view = await controller.refresh_view()

        self.assertTrue(view.selected_target.owned)
        self.assertEqual(view.selected_target.state, "RUNNING")
        self.assertEqual(view.observed_state, "RUNNING")

    async def test_launch_replay_rejects_database_dir_without_replay_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            manager = ServiceProcessManager(
                spawner=FakeSpawner(FakeHandle(7007)),
                hostname="dev-host",
                clock=lambda: 10.0,
            )
            controller = ReplayTabController(
                process_manager=manager,
                config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
                clock=lambda: 12.0,
            )

            with self.assertRaisesRegex(ValueError, "metadata\.db and at least one data_\*\.db"):
                controller.launch_replay({
                    "config_name": "xcdr",
                    "database_path": tempdir,
                    "executable": "/opt/rti/bin/rtireplayservice",
                })

    async def test_shutdown_dispatches_replay_admin_command(self):
        database_dir = self._make_replay_database_dir()
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
            "database_path": database_dir,
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
        database_dir = self._make_replay_database_dir()
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
            "database_path": database_dir,
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
        self.assertEqual(view.readiness, "Service Admin facade is not configured")
        self.assertTrue(view.selected_target_id.startswith("monitoring:replay:"))
        self.assertEqual(controller.last_selection.selected_candidate.launch_id, launch.launch_id)
        self.assertEqual(controller.last_selection.selected_candidate.details["resource_id"], "/replay_services/xcdr")

    async def test_replay_monitoring_cache_keeps_state_between_refreshes(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(7007)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        monitoring_client = FakeServiceMonitoringClient()
        controller = ReplayTabController(
            process_manager=manager,
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=ReplayTabControllerConfig(
                launch_admin_domain_id=61,
                launch_monitoring_domain_id=62,
                database_path="services/replay_input/robot_run_03",
            ),
            clock=lambda: 12.0,
        )
        discovered_service = ServiceInstanceRef(
            ServiceKind.REPLAY,
            "template",
            admin_domain_id=61,
            monitoring_domain_id=62,
        )
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=discovered_service,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="running",
            metrics={"progress": "64%"},
            details={
                "admin_resource_name": "template",
                "resource_id": "/replay_services/template",
                "host_name": "dev-host",
            },
            observed_at=13.0,
        ))

        first = await controller.refresh_view()
        second = await controller.refresh_view()

        self.assertEqual(first.target_count, 1)
        self.assertEqual(second.target_count, 1)
        self.assertEqual(first.selected_target.control_name, "template")
        self.assertEqual(second.selected_target.control_name, "template")
        self.assertEqual(first.selected_target.progress, "64%")
        self.assertEqual(second.selected_target.progress, "64%")


if __name__ == "__main__":
    unittest.main()
