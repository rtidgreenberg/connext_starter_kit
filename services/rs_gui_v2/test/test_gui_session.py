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
from gui.tabs import RecordTabController, RecordTabControllerConfig, TopicsTabController, TopicsTabControllerConfig
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


def build_session(runtime=None, admin_client=None, topics_controller=None):
    runtime = runtime or AppRuntime()
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
            command_type="workspace.save",
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
