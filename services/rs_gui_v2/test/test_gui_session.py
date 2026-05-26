#!/usr/bin/env python3
"""Headless tests for runtime-backed GUI shell sessions."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    AppCommand,
    AppRuntime,
    FieldCatalog,
    FieldDescriptor,
    RuntimeConfig,
    SubscriptionStatus,
    TopicDiscoveryFacade,
)
from app_core.services import (
    FakeServiceAdminClient,
    ServiceAdminFacade,
    ServiceCommand,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceProcessLaunchRequest,
    ServiceProcessManager,
)
from gui import GuiShellSession, GuiShellSessionConfig, UiFrameScheduler
from gui.main_window import DearPyGuiShell
from gui.tabs import (
    ConvertTabController,
    RecordTabController,
    RecordTabControllerConfig,
    ReplayTabController,
    TopicsTabController,
    TopicsTabControllerConfig,
)
from test_gui_shell import FakeDpg
from test_gui_topics_controller import _fake_discovery_client


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

    def start(self, command_line, working_dir="", environment=None):
        if not self.handles:
            raise RuntimeError("no fake handles queued")
        return self.handles.pop(0)


def launch_request():
    return ServiceProcessLaunchRequest(
        intent=ServiceLaunchIntent(
            kind=ServiceKind.RECORDING,
            label="Recording Service",
            admin_domain_id=0,
            monitoring_domain_id=0,
            config_paths=("record.xml", "qos.xml"),
        ),
        config_name="deploy",
        executable="/opt/rti/bin/rtirecordingservice",
    )


def build_session(runtime=None, admin_client=None, convert_controller=None, replay_controller=None, topics_controller=None):
    runtime = runtime or AppRuntime()
    manager = ServiceProcessManager(
        spawner=FakeSpawner(FakeHandle(4218), FakeHandle(5002)),
        hostname="dev-host",
        clock=lambda: 10.0,
    )
    launch = manager.launch(
        launch_request(),
        launch_id="launch-main",
        session_guid="11111111-2222-3333-4444-555555555555",
    )
    admin_client = admin_client or FakeServiceAdminClient()
    controller = RecordTabController(
        manager,
        admin_facade=ServiceAdminFacade(admin_client),
        config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
        clock=lambda: 12.0,
    )
    session = GuiShellSession(
        runtime=runtime,
        scheduler=UiFrameScheduler(runtime, max_event_log=20),
        record_controller=controller,
        convert_controller=convert_controller,
        replay_controller=replay_controller,
        topics_controller=topics_controller,
        config=GuiShellSessionConfig(workspace_name="Robot Run 03", unsaved=True),
    )
    return session, admin_client, launch


def build_topics_controller():
    return TopicsTabController(
        discovery_facade=TopicDiscoveryFacade(_fake_discovery_client()),
        field_catalogs={"Robot::Telemetry": FieldCatalog(
            type_name="Robot::Telemetry",
            fields=(FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),),
        )},
        config=TopicsTabControllerConfig(domain_id=7, selected_topic_key="7:RobotTelemetry"),
        clock=lambda: 20.0,
    )


class TestGuiShellSession(unittest.IsolatedAsyncioTestCase):
    async def test_next_view_uses_record_controller_and_scheduler(self):
        runtime = AppRuntime()
        runtime.start()
        session, _admin_client, launch = build_session(runtime=runtime)

        view = await session.next_view_async(process_commands=False)

        self.assertIn("Robot Run 03", view.title)
        self.assertTrue(view.title.endswith("*"))
        self.assertEqual(view.record_tab.selected_candidate_id, "launch-main")
        self.assertEqual(view.record_tab.selected_candidate.control_name, launch.identity.service_ref.name)
        self.assertTrue(any(entry.message == "Lifecycle stopped -> starting" for entry in view.event_log))

    async def test_command_sink_queues_and_dispatches_pause(self):
        session, admin_client, _launch = build_session()
        await session.next_view_async(process_commands=False)
        command = AppCommand(
            command_type="service.pause",
            target="recording",
            payload={"candidate_id": "launch-main"},
            command_id="pause-command",
            created_at=1.0,
        )

        self.assertTrue(session.command_sink(command))
        view = await session.next_view_async()

        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.PAUSE])
        self.assertEqual(view.record_tab.command_history[0].command, "pause")
        self.assertTrue(any(entry.message == "Queued service.pause" for entry in view.event_log))
        self.assertTrue(any(entry.message == "Dispatched service.pause" for entry in view.event_log))

    async def test_launch_recording_command_dispatches_to_process_manager(self):
        session, _admin_client, _launch = build_session()
        await session.next_view_async(process_commands=False)
        session.command_sink(AppCommand(
            command_type="service.launch_recording",
            target="recording",
            payload={
                "label": "Manual Recorder",
                "config_paths": ["manual_record.xml", "manual_qos.xml"],
                "config_name": "manual_deploy",
                "data_domain_id": 63,
                "admin_domain_id": 61,
                "monitoring_domain_id": 62,
                "verbosity": "WARN:WARN",
                "executable": "/opt/rti/bin/rtirecordingservice",
            },
            command_id="launch-recording",
            created_at=1.5,
        ))

        view = await session.next_view_async()

        self.assertEqual(view.record_tab.selected_candidate.pid, "5002")
        self.assertEqual(view.record_tab.launch.config_name, "manual_deploy")
        self.assertEqual(view.record_tab.launch.data_domain_id, 63)
        self.assertEqual(view.record_tab.admin_domain, 61)
        self.assertEqual(view.record_tab.monitoring_domain, 62)
        self.assertTrue(any(entry.message == "Dispatched service.launch_recording" for entry in view.event_log))

    async def test_tag_command_updates_controller_tag_state(self):
        session, admin_client, _launch = build_session()
        await session.next_view_async(process_commands=False)
        command = AppCommand(
            command_type="service.tag",
            target="recording",
            payload={
                "candidate_id": "launch-main",
                "tag_name": "night_run",
                "description": "operator tag",
            },
            command_id="tag-command",
            created_at=2.0,
        )

        session.command_sink(command)
        view = await session.next_view_async()

        self.assertEqual(admin_client.requests[0].command, ServiceCommand.TAG)
        self.assertEqual(admin_client.requests[0].parameters["tag_name"], "night_run")
        self.assertEqual(view.record_tab.tag_value, "night_run")
        self.assertEqual(view.record_tab.command_history[0].command, "tag")

    async def test_unsupported_command_reports_event_failure(self):
        session, admin_client, _launch = build_session()
        session.command_sink(AppCommand(
            command_type="convert.start",
            command_id="unsupported",
            created_at=3.0,
        ))

        view = await session.next_view_async()

        self.assertEqual(admin_client.requests, [])
        self.assertTrue(any(entry.level == "error" for entry in view.event_log))
        self.assertTrue(any("Unsupported GUI command type" in entry.message for entry in view.event_log))

    async def test_topics_commands_route_to_topics_controller(self):
        session, _admin_client, _launch = build_session(topics_controller=build_topics_controller())
        await session.next_view_async(process_commands=False)
        session.command_sink(AppCommand(
            command_type="topics.subscribe",
            payload={
                "domain_id": 7,
                "topic_name": "RobotTelemetry",
                "type_name": "Robot::Telemetry",
                "selected_fields": ("pose.x",),
            },
            command_id="subscribe-topic",
            created_at=4.0,
        ))

        view = await session.next_view_async()

        self.assertEqual(view.topics_tab.selected_topic.subscription_status, SubscriptionStatus.READER_CREATED.value)
        self.assertTrue(view.topics_tab.action_by_id["unsubscribe"].enabled)
        self.assertTrue(any(entry.message == "Dispatched topics.subscribe" for entry in view.event_log))

    async def test_replay_commands_route_to_replay_controller(self):
        session, _admin_client, _launch = build_session(replay_controller=ReplayTabController.mock())
        await session.next_view_async(process_commands=False)
        session.command_sink(AppCommand(
            command_type="replay.start",
            payload={
                "target_id": "launch-replay-main",
                "database_path": "services/replay_input/robot_run_03",
                "playback_rate": 2.0,
            },
            command_id="start-replay",
            created_at=4.5,
        ))

        view = await session.next_view_async()

        self.assertEqual(view.replay_tab.observed_state, "RUNNING")
        self.assertEqual(view.replay_tab.playback_rate, 2.0)
        self.assertTrue(view.replay_tab.action_by_id["pause"].enabled)
        self.assertTrue(any(entry.message == "Dispatched replay.start" for entry in view.event_log))

    async def test_topics_filter_command_updates_next_shell_snapshot(self):
        session, _admin_client, _launch = build_session(topics_controller=build_topics_controller())
        session.command_sink(AppCommand(
            command_type="topics.set_search",
            payload={"search_text": "robot"},
            command_id="filter-topics",
            created_at=5.0,
        ))

        view = await session.next_view_async()

        self.assertEqual(view.topics_tab.search_text, "robot")
        self.assertEqual([row.topic_name for row in view.topics_tab.rows], ["RobotTelemetry"])

    async def test_topics_command_without_controller_reports_failure(self):
        session, _admin_client, _launch = build_session()
        session.command_sink(AppCommand(
            command_type="topics.set_search",
            payload={"search_text": "robot"},
            command_id="filter-without-controller",
            created_at=6.0,
        ))

        view = await session.next_view_async()

        self.assertTrue(any(entry.level == "error" for entry in view.event_log))
        self.assertTrue(any("Unsupported GUI command type: topics.set_search" in entry.message for entry in view.event_log))

    async def test_convert_commands_route_to_convert_controller(self):
        convert_controller = ConvertTabController.mock()
        session, _admin_client, _launch = build_session(convert_controller=convert_controller)
        await session.next_view_async(process_commands=False)
        initial_job_count = len(session.convert_controller.last_view.jobs)
        session.command_sink(AppCommand(
            command_type="convert.run",
            payload={
                "config_name": "sqlite_to_json",
                "input_storage": {"path": "services/input"},
                "output_storage": {"path": "services/output"},
                "output_format": "JSON_SQLITE",
            },
            command_id="start-convert",
            created_at=4.5,
        ))

        view = await session.next_view_async()

        self.assertEqual(len(view.convert_tab.jobs), initial_job_count + 1)
        new_job = view.convert_tab.jobs[-1]
        self.assertEqual(new_job.state, "queued")
        self.assertTrue(view.convert_tab.action_by_id["cancel"].enabled)
        self.assertTrue(any(entry.message == "Dispatched convert.run" for entry in view.event_log))

    async def test_convert_cancel_updates_job_state_in_next_view(self):
        convert_controller = ConvertTabController.mock()
        session, _admin_client, _launch = build_session(convert_controller=convert_controller)
        await session.next_view_async(process_commands=False)

        # Create a new job
        session.command_sink(AppCommand(
            command_type="convert.run",
            payload={
                "config_name": "sqlite_to_json",
                "input_storage": {"path": "services/input"},
                "output_storage": {"path": "services/output"},
            },
            command_id="start-convert",
            created_at=4.5,
        ))
        view = await session.next_view_async()
        new_job = view.convert_tab.jobs[-1]  # Get the last (newest) job
        job_id = new_job.job_id
        self.assertEqual(new_job.state, "queued")

        # Cancel that specific job
        session.command_sink(AppCommand(
            command_type="convert.cancel",
            payload={"job_id": job_id},
            command_id="cancel-convert",
            created_at=5.0,
        ))
        view = await session.next_view_async()

        # Find the job again and verify state changed
        cancelled_job = next((j for j in view.convert_tab.jobs if j.job_id == job_id), None)
        self.assertIsNotNone(cancelled_job)
        self.assertEqual(cancelled_job.state, "cancel_requested")
        self.assertTrue(any(entry.message == "Dispatched convert.cancel" for entry in view.event_log))

    async def test_convert_command_without_controller_reports_failure(self):
        session, _admin_client, _launch = build_session()
        session.command_sink(AppCommand(
            command_type="convert.run",
            payload={
                "config_name": "sqlite_to_json",
                "input_storage": {"path": "services/input"},
                "output_storage": {"path": "services/output"},
            },
            command_id="convert-no-controller",
            created_at=6.0,
        ))

        view = await session.next_view_async()

        self.assertTrue(any(entry.level == "error" for entry in view.event_log))
        self.assertTrue(any("Unsupported GUI command type: convert.run" in entry.message for entry in view.event_log))

    async def test_command_queue_backpressure_is_reported(self):
        runtime = AppRuntime(RuntimeConfig(command_queue_max_size=1, event_queue_max_size=10))
        session, _admin_client, _launch = build_session(runtime=runtime)

        first = session.command_sink(AppCommand(command_type="service.pause", command_id="first", created_at=1.0))
        second = session.command_sink(AppCommand(command_type="service.resume", command_id="second", created_at=2.0))
        view = await session.next_view_async(process_commands=False)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(any(entry.message == "Dropped service.resume" for entry in view.event_log))


class TestGuiShellSessionRenderer(unittest.TestCase):
    def test_dearpygui_shell_renders_session_view_provider(self):
        session, _admin_client, _launch = build_session()
        fake = FakeDpg()
        shell = DearPyGuiShell(
            view_provider=session.next_view,
            command_sink=session.command_sink,
            dpg_module=fake,
        )

        view = shell.render_once()

        self.assertEqual(view.record_tab.selected_candidate_id, "launch-main")
        self.assertTrue(fake.context_created)
        self.assertTrue(fake.context_destroyed)


if __name__ == "__main__":
    unittest.main()
