#!/usr/bin/env python3
"""Headless tests for runtime-backed GUI shell sessions."""

import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    AppCommand,
    AppRuntime,
    CommandStatus,
    FieldCatalog,
    FieldDescriptor,
    RuntimeConfig,
    SubscriptionStatus,
    TopicDiscoveryFacade,
)
from app_core.services import (
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
from gui import GuiShellSession, GuiShellSessionConfig, UiFrameScheduler
from gui.main_window import DearPyGuiShell
from gui.tabs import (
    ConvertTabController,
    RecordTabController,
    RecordTabControllerConfig,
    ReplayLaunchViewModel,
    ReplayTabController,
    ReplayTabControllerConfig,
    TopicsTabController,
    TopicsTabControllerConfig,
)
from gui.tabs.convert_controller import ConvertJobSubmission
from gui.tabs.convert_tab import ConvertJobRow
from gui.tabs.record_tab import build_record_launch_command
from gui.tabs.replay_tab import build_replay_launch_command
from test_gui_shell import FakeDpg, NoViewportCloseFakeDpg
from test_gui_topics_controller import _fake_discovery_client
from fakes import FakeHandle, FakeSpawner


class FakeTerminatingConvertProcess:
    def __init__(self):
        self.returncode = None
        self.terminate_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -15


class ShutdownExitingAdminClient(FakeServiceAdminClient):
    def __init__(self, handle):
        super().__init__()
        self._handle = handle

    async def send_command(self, request):
        if request.command == ServiceCommand.SHUTDOWN:
            self._handle.returncode = 0
        return await super().send_command(request)


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
        config=GuiShellSessionConfig(
            workspace_name="Robot Run 03",
            unsaved=True,
            close_shutdown_exit_timeout_sec=0.0,
        ),
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


class TestGuiShellSessionBridge(unittest.TestCase):
    def test_shell_exit_callback_invokes_session_close_cleanup_without_viewport_callback(self):
        runtime = AppRuntime()
        handle = FakeHandle(4218)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
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
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
            config=GuiShellSessionConfig(close_shutdown_exit_timeout_sec=0.0),
        )
        fake = NoViewportCloseFakeDpg()
        shell = DearPyGuiShell(
            view_provider=session.next_view,
            dpg_module=fake,
            close_handler=session.handle_close_request,
        )

        shell.run()

        self.assertTrue(any(name == "set_exit_callback" for name, _args, _kwargs in fake.calls))
        self.assertFalse(any(name == "set_viewport_close_callback" for name, _args, _kwargs in fake.calls))
        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.SHUTDOWN])
        self.assertEqual(handle.terminate_calls, 1)
        events = runtime.drain_events()
        close_completed = next(event for event in events if event.event_type == "gui.close_completed")
        self.assertEqual(close_completed.payload["action"], "shutdown_gui_launched")
        self.assertEqual(close_completed.payload["cleanup_results"][0]["candidate_id"], "launch-main")
        self.assertIsNotNone(close_completed.payload["cleanup_results"][0]["local_termination"])


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

    async def test_next_view_publishes_live_monitoring_update_events(self):
        runtime = AppRuntime()
        runtime.start()
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
            kind=MonitoringSnapshotKind.PERIODIC,
            state="observed",
            metrics={"cpu_percent": 2.0},
            details={"db_file": "data_0.db"},
            observed_at=20.0,
        ))
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 21.0,
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
        )

        view = await session.next_view_async()

        monitoring_entry = next(entry for entry in view.event_log if entry.event_type == "service.monitoring_update")
        self.assertEqual(monitoring_entry.message, "Recording Service monitoring periodic: observed")

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
        queued = next(entry for entry in view.event_log if entry.message == "Queued service.pause")
        self.assertEqual(queued.payload["command"]["payload"]["candidate_id"], "launch-main")
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

    async def test_spawned_recording_process_exit_updates_next_gui_view(self):
        runtime = AppRuntime()
        handle = FakeHandle(4218)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
        )
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

        running_view = await session.next_view_async()
        handle.returncode = -15
        exited_view = await session.next_view_async(process_commands=False)

        self.assertEqual(running_view.record_tab.selected_candidate.pid, "4218")
        self.assertEqual(running_view.record_tab.observed_state, "running")
        self.assertEqual(exited_view.record_tab.selected_candidate.pid, "4218")
        self.assertEqual(exited_view.record_tab.observed_state, "exited")
        exit_event = next(
            entry for entry in exited_view.event_log
            if entry.message == "Recording Service process observed: exited"
        )
        self.assertEqual(exit_event.level, "error")
        self.assertEqual(exit_event.payload["candidate"]["details"]["returncode"], -15)

    async def test_spawned_recording_exit_wins_over_stale_monitoring_update(self):
        runtime = AppRuntime()
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
        monitoring_client = FakeServiceMonitoringClient()
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
        )
        await session.next_view_async(process_commands=False)
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="observed",
            metrics={"cpu_percent": 2.0},
            details={"process_id": 4218, "host_name": "dev-host"},
            observed_at=20.0,
        ))

        handle.returncode = 0
        view = await session.next_view_async(process_commands=False)

        self.assertEqual(view.record_tab.selected_candidate.pid, "4218")
        self.assertEqual(view.record_tab.observed_state, "exited")
        exit_event = next(entry for entry in view.event_log if entry.message == "Recording Service process observed: exited")
        self.assertEqual(exit_event.level, "error")

    async def test_default_launch_command_populates_record_dropdown_model(self):
        session, _admin_client, _launch = build_session()
        initial_view = await session.next_view_async(process_commands=False)

        session.command_sink(build_record_launch_command(initial_view.record_tab.launch))
        view = await session.next_view_async()

        self.assertTrue(view.record_tab.candidates)
        self.assertEqual(view.record_tab.selected_candidate.pid, "5002")
        self.assertEqual(view.record_tab.selected_candidate_id, view.record_tab.selected_candidate.candidate_id)
        self.assertTrue(any(entry.message == "Dispatched service.launch_recording" for entry in view.event_log))

    async def test_launch_replay_command_dispatches_to_process_manager(self):
        replay_manager = ServiceProcessManager(
            spawner=FakeSpawner(FakeHandle(7007)),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        replay_controller = ReplayTabController(
            process_manager=replay_manager,
            config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        session, _admin_client, _launch = build_session(replay_controller=replay_controller)
        await session.next_view_async(process_commands=False)
        session.command_sink(build_replay_launch_command(ReplayLaunchViewModel(
            label="Manual Replay",
            config_paths=("services/replay_service_config.xml",),
            config_name="xcdr",
            data_domain_id=63,
            admin_domain_id=61,
            monitoring_domain_id=62,
            database_path="log_dir/xcdr",
            executable="/opt/rti/bin/rtireplayservice",
        )))

        view = await session.next_view_async()

        self.assertEqual(view.replay_tab.selected_target.pid, "7007")
        self.assertEqual(view.replay_tab.selected_target.source, "gui_launch")
        self.assertEqual(view.replay_tab.observed_state, "running")
        self.assertTrue(any(entry.message == "Dispatched service.launch_replay" for entry in view.event_log))
        self.assertTrue(any(entry.message == "Replay Service process observed: running" for entry in view.event_log))

    async def test_close_request_leave_running_does_not_shutdown_services(self):
        session, admin_client, _launch = build_session()
        await session.next_view_async(process_commands=False)

        await session.handle_close_request_async("leave_running", ())

        self.assertEqual(admin_client.requests, [])

    async def test_close_request_shutdowns_selected_gui_launched_recording(self):
        session, admin_client, _launch = build_session()
        await session.next_view_async(process_commands=False)

        await session.handle_close_request_async("shutdown_gui_launched", ("record:launch-main",))

        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.SHUTDOWN])

    async def test_close_request_terminates_selected_gui_launched_replay(self):
        handle = FakeHandle(7007)
        replay_manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        admin_client = FakeServiceAdminClient()
        replay_controller = ReplayTabController(
            process_manager=replay_manager,
            admin_facade=ServiceAdminFacade(admin_client),
            config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        launch = replay_controller.launch_replay({
            "label": "Manual Replay",
            "config_paths": ["services/replay_service_config.xml"],
            "config_name": "xcdr",
            "database_path": "log_dir/xcdr",
            "executable": "/opt/rti/bin/rtireplayservice",
        })
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime, replay_controller=replay_controller)
        await session.next_view_async(process_commands=False)

        await session.handle_close_request_async("shutdown_gui_launched", (f"replay:{launch.launch_id}",))

        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.SHUTDOWN])
        self.assertEqual(admin_client.requests[0].parameters["admin_resource_name"], "xcdr")
        self.assertEqual(handle.terminate_calls, 1)
        events = runtime.drain_events()
        close_completed = next(event for event in events if event.event_type == "gui.close_completed")
        cleanup = close_completed.payload["cleanup_results"][0]
        self.assertEqual(cleanup["kind"], "replay")
        self.assertEqual(cleanup["candidate_id"], launch.launch_id)
        self.assertTrue(cleanup["admin_shutdown_ok"])
        self.assertIsNotNone(cleanup["local_termination"])

    async def test_close_request_terminates_local_process_after_shutdown_failure(self):
        handle = FakeHandle(4218)
        runtime = AppRuntime()
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
            request=ServiceCommandRequest(launch.identity.service_ref, ServiceCommand.SHUTDOWN),
            status=CommandStatus.TIMEOUT,
            message="admin unavailable",
        ))
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
        )
        await session.next_view_async(process_commands=False)

        await session.handle_close_request_async("shutdown_gui_launched", ("record:launch-main",))

        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.SHUTDOWN])
        self.assertEqual(handle.terminate_calls, 1)

    async def test_close_request_requires_process_exit_after_admin_shutdown_ack(self):
        handle = FakeHandle(4218)
        runtime = AppRuntime()
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
        monitoring_client = FakeServiceMonitoringClient()
        monitoring_client.push_snapshot(MonitoringSnapshot(
            service=launch.identity.service_ref,
            kind=MonitoringSnapshotKind.PERIODIC,
            state="STOPPED",
            metrics={},
            details={"process_id": 4218, "host_name": "dev-host"},
            observed_at=20.0,
        ))
        admin_client = FakeServiceAdminClient()
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(admin_client),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
            config=GuiShellSessionConfig(close_shutdown_exit_timeout_sec=0.0),
        )
        view = await session.next_view_async(process_commands=False)

        await session.handle_close_request_async(
            "shutdown_gui_launched",
            (f"record:{view.record_tab.selected_candidate_id}",),
        )

        self.assertEqual([request.command for request in admin_client.requests], [ServiceCommand.SHUTDOWN])
        self.assertEqual(handle.terminate_calls, 1)
        events = runtime.drain_events()
        close_completed = next(event for event in events if event.event_type == "gui.close_completed")
        cleanup = close_completed.payload["cleanup_results"][0]
        self.assertIsNotNone(cleanup["local_termination"])
        self.assertEqual(cleanup["local_termination"]["status"], "requested")

    async def test_close_request_prints_verified_recording_shutdown_summary(self):
        runtime = AppRuntime()
        handle = FakeHandle(4218)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        manager.launch(
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
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
            config=GuiShellSessionConfig(close_shutdown_exit_timeout_sec=0.0),
        )
        await session.next_view_async(process_commands=False)
        output = StringIO()

        with redirect_stdout(output):
            await session.handle_close_request_async("shutdown_gui_launched", ("record:launch-main",))

        text = output.getvalue()
        self.assertIn("[INFO] SHUTDOWN_RECORDING: Recording Service launch-main exited", text)
        self.assertIn("[INFO] SHUTDOWN_SUMMARY: All GUI-spawned local processes have exited (1 process(es))", text)

    async def test_close_request_verifies_converter_process_exit(self):
        job_id = "convert-1234"
        process = FakeTerminatingConvertProcess()
        convert_controller = ConvertTabController()
        convert_controller._jobs = (ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        ),)
        convert_controller._submissions[job_id] = ConvertJobSubmission(
            job_id=job_id,
            submitted_at=0.0,
            process_pid=4321,
        )
        convert_controller._processes[4321] = process
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime, convert_controller=convert_controller)

        await session.handle_close_request_async("shutdown_gui_launched", (f"convert:{job_id}",))

        self.assertEqual(process.terminate_calls, 1)
        events = runtime.drain_events()
        close_completed = next(event for event in events if event.event_type == "gui.close_completed")
        cleanup = close_completed.payload["cleanup_results"][0]
        self.assertEqual(cleanup["kind"], "convert")
        self.assertEqual(cleanup["job_id"], job_id)
        self.assertEqual(cleanup["process_pid"], 4321)
        self.assertTrue(cleanup["process_exit_observed"])
        self.assertNotIn(4321, convert_controller._processes)

    async def test_close_request_prints_verified_converter_shutdown_summary(self):
        job_id = "convert-1234"
        process = FakeTerminatingConvertProcess()
        convert_controller = ConvertTabController()
        convert_controller._jobs = (ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        ),)
        convert_controller._submissions[job_id] = ConvertJobSubmission(
            job_id=job_id,
            submitted_at=0.0,
            process_pid=4321,
        )
        convert_controller._processes[4321] = process
        session, _admin_client, _launch = build_session(convert_controller=convert_controller)
        output = StringIO()

        with redirect_stdout(output):
            await session.handle_close_request_async("shutdown_gui_launched", (f"convert:{job_id}",))

        text = output.getvalue()
        self.assertIn("[INFO] SHUTDOWN_CONVERTER: Converter job convert-1234 pid 4321 exited", text)
        self.assertIn("[INFO] SHUTDOWN_SUMMARY: All GUI-spawned local processes have exited (1 process(es))", text)

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

    async def test_failed_controller_result_reports_error_console_event(self):
        runtime = AppRuntime()
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
        controller = RecordTabController(
            manager,
            admin_facade=None,
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
        )

        session.command_sink(AppCommand(
            command_type="service.shutdown",
            target="recording",
            payload={"candidate_id": "launch-main"},
            command_id="shutdown-without-admin",
            created_at=3.0,
        ))
        view = await session.next_view_async()

        failure = next(entry for entry in view.event_log if entry.event_type == "gui.command_failed")
        self.assertEqual(failure.level, "error")
        self.assertIn("No Service Admin facade", failure.message)
        self.assertEqual(failure.payload["result"]["status"], "failed")

    async def test_process_exit_refresh_reports_console_event_with_log_tail(self):
        output_dir = os.path.join("test_output", "rs_gui_v2", "gui_session_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "recording_exit.log")
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write("startup failed in service\n")
        handle = FakeHandle(4218)
        handle.output_path = output_path
        runtime = AppRuntime()
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        manager.launch(
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
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=20),
            record_controller=controller,
        )
        await session.next_view_async(process_commands=False)

        handle.returncode = 7
        view = await session.next_view_async(process_commands=False)

        exit_event = next(entry for entry in view.event_log if entry.message == "Recording Service process observed: exited")
        self.assertEqual(exit_event.level, "error")
        self.assertEqual(exit_event.payload["candidate"]["details"]["output_path"], output_path)
        self.assertIn("startup failed", exit_event.payload["candidate"]["details"]["output_tail"])

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
