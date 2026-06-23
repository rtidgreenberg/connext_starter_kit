#!/usr/bin/env python3
"""Live integration tests for GUI-owned Recording Service lifecycle."""

import asyncio
from dataclasses import replace
import importlib.util
import os
import signal
import sys
import time
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand, AppRuntime
from app_core.connext_environment import detect_nddshome, ensure_rti_license
from app_core.services import (
    RtiServiceAdminClient,
    RtiServiceMonitoringClient,
    ServiceAdminFacade,
    ServiceMonitoringFacade,
    ServiceProcessManager,
    SubprocessServiceProcessSpawner,
    default_rti_service_admin_config,
    default_rti_service_monitoring_config,
)
from gui import GuiShellSession, UiFrameScheduler
from gui.factory import GuiShellSessionFactoryConfig, GuiShellSessionMode, build_gui_shell_assembly
from gui.tabs import RecordTabController, RecordTabControllerConfig
from gui.tabs.record_tab import build_record_launch_command


def _live_requirements():
    nddshome = detect_nddshome()
    if not nddshome:
        return "NDDSHOME or an RTI Connext installation is required", ""
    if importlib.util.find_spec("rti.connextdds") is None:
        return "RTI Connext Python API is required", ""
    if importlib.util.find_spec("rti.request") is None:
        return "RTI request/reply Python API is required", ""
    executable = os.path.join(nddshome, "bin", "rtirecordingservice")
    if not os.path.isfile(executable):
        return f"rtirecordingservice not found at {executable}", ""
    license_file = ensure_rti_license(nddshome)
    if not license_file:
        return "RTI_LICENSE_FILE or a discoverable RTI license is required", ""
    service_config = os.path.join(REPO_ROOT, "services", "recording_service_config.xml")
    default_recording_config = os.path.join(REPO_ROOT, "dds", "qos", "recording_service.xml")
    qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
    for path in (service_config, default_recording_config, qos_file):
        if not os.path.isfile(path):
            return f"required Recording Service config is missing: {path}", ""
    return "", executable


_LIVE_SKIP_REASON, _LIVE_EXECUTABLE = _live_requirements()


class _LiveDynamicPublisher:
    """Tiny DynamicData publisher used by live recording integration tests."""

    def __init__(self, domain_id: int, topic_name: str, type_name: str) -> None:
        import rti.connextdds as dds

        self._dds = dds
        self._index = 0
        dynamic_type = dds.StructType(type_name)
        dynamic_type.add_member(dds.Member("source_id", dds.StringType(64)))
        dynamic_type.add_member(dds.Member("index", dds.Int32Type()))
        dynamic_type.add_member(dds.Member("value", dds.Float64Type()))

        participant = dds.DomainParticipant(int(domain_id))
        topic = dds.DynamicData.Topic(participant, topic_name, dynamic_type)
        writer = dds.DynamicData.DataWriter(participant.implicit_publisher, topic)

        self._participant = participant
        self._writer = writer

    def publish(self, count: int) -> None:
        for _ in range(max(0, int(count))):
            sample = self._writer.create_data()
            sample["source_id"] = "gui-live-integration"
            sample["index"] = int(self._index)
            sample["value"] = float(self._index)
            self._writer.write(sample)
            self._index += 1

    def close(self) -> None:
        close_contained = getattr(self._participant, "close_contained_entities", None)
        if callable(close_contained):
            close_contained()
        close_participant = getattr(self._participant, "close", None)
        if callable(close_participant):
            close_participant()


async def _wait_for_state(session, expected_state, timeout_sec=8.0):
    deadline = time.monotonic() + timeout_sec
    last_view = None
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        if last_view.record_tab.observed_state == expected_state:
            return last_view
        await asyncio.sleep(0.1)
    return last_view


async def _wait_for_candidate_state(
        session,
        expected_state,
        candidate_id="",
        control_name="",
        pid="",
        timeout_sec=8.0,
):
    deadline = time.monotonic() + timeout_sec
    last_view = None
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        candidate = _candidate_by_identity(last_view, candidate_id, control_name, pid)
        if candidate is not None and candidate.state == expected_state:
            return last_view
        await asyncio.sleep(0.1)
    return last_view


def _candidate_by_id(view, candidate_id):
    for candidate in view.record_tab.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def _candidate_by_identity(view, candidate_id="", control_name="", pid=""):
    for candidate in view.record_tab.candidates:
        if candidate_id and candidate.candidate_id == candidate_id:
            return candidate
        if control_name and candidate.control_name == control_name:
            return candidate
        if pid and candidate.pid == str(pid):
            return candidate
    return None


def _terminate_pid(pid):
    if not pid:
        return
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            return


def _kill_pid(pid):
    if not pid:
        return
    try:
        os.killpg(int(pid), signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            return


def _pid_is_running(pid):
    if not pid:
        return False
    stat_path = os.path.join("/proc", str(int(pid)), "stat")
    try:
        with open(stat_path, "r", encoding="utf-8") as stat_file:
            stat_fields = stat_file.read().split()
        if len(stat_fields) > 2 and stat_fields[2] == "Z":
            return False
    except FileNotFoundError:
        return False
    except Exception:
        pass
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def _wait_for_pid_exit(pid, timeout_sec=8.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return True
        await asyncio.sleep(0.1)
    return not _pid_is_running(pid)


async def _wait_for_current_file(session, timeout_sec=12.0, on_retry=None):
    deadline = time.monotonic() + timeout_sec
    last_view = None
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        selected = last_view.record_tab.selected_candidate
        if selected is not None and selected.current_file:
            return last_view
        if on_retry is not None:
            on_retry()
        await asyncio.sleep(0.1)
    return last_view


async def _wait_for_live_monitoring_state(session, timeout_sec=12.0):
    deadline = time.monotonic() + timeout_sec
    last_view = None
    live_states = {"ENABLED", "STARTED", "RUNNING", "PAUSED"}
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        selected = last_view.record_tab.selected_candidate
        if selected is not None and selected.state in live_states:
            return last_view
        await asyncio.sleep(0.1)
    return last_view


async def _wait_for_file_growth(path: str, baseline_size: int, timeout_sec=10.0, on_retry=None):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            current_size = os.path.getsize(path)
        except OSError:
            current_size = -1
        if current_size > baseline_size:
            return current_size
        if on_retry is not None:
            on_retry()
        await asyncio.sleep(0.2)
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


@unittest.skipIf(_LIVE_SKIP_REASON, _LIVE_SKIP_REASON)
class TestGuiSessionLiveIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_live_publisher_recording_file_size_increases(self):
        run_id = f"gui_record_growth_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(PARENT_DIR, "service_churn", "integration_tests", run_id)
        os.makedirs(run_dir, exist_ok=True)
        admin_domain_id = 360 + (os.getpid() % 30)
        data_domain_id = admin_domain_id + 1
        recording_config = os.path.join(REPO_ROOT, "dds", "qos", "recording_service.xml")
        qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
        assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.LIVE,
            workspace_name="Live Recording Growth",
            recording_working_dir=run_dir,
            recording_config_paths=(recording_config, qos_file),
            recording_config_name="template",
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=admin_domain_id,
            topics_domain_id=data_domain_id,
            start_runtime=True,
        ))
        session = assembly.session
        pid = None
        publisher = None
        try:
            initial_view = await session.next_view_async(process_commands=False)
            launch_command = build_record_launch_command(initial_view.record_tab.launch)
            launch_payload = dict(launch_command.payload)
            launch_payload.update({
                "data_domain_id": data_domain_id,
                "admin_domain_id": admin_domain_id,
                "monitoring_domain_id": admin_domain_id,
                "working_dir": run_dir,
                "topic_allow": "RsGuiV2Growth*",
                "topic_deny": "rti/*",
            })
            session.command_sink(AppCommand(
                command_type=launch_command.command_type,
                target=launch_command.target,
                payload=launch_payload,
                command_id="launch-live-record-growth",
                created_at=time.time(),
            ))

            launch_view = await session.next_view_async()
            selected = launch_view.record_tab.selected_candidate
            self.assertIsNotNone(selected)
            pid = int(selected.pid)
            self.assertGreater(pid, 0)

            publisher = _LiveDynamicPublisher(
                domain_id=data_domain_id,
                topic_name="RsGuiV2GrowthTelemetry",
                type_name="RsGuiV2GrowthTelemetryType",
            )
            publisher.publish(300)

            monitored_view = await _wait_for_current_file(
                session,
                timeout_sec=15.0,
                on_retry=lambda: publisher.publish(100),
            )
            selected = monitored_view.record_tab.selected_candidate
            self.assertIsNotNone(selected)
            self.assertTrue(selected.current_file)

            resolved_current_file = selected.current_file
            if not os.path.isabs(resolved_current_file):
                resolved_current_file = os.path.join(run_dir, resolved_current_file)
            self.assertTrue(os.path.exists(resolved_current_file), selected.current_file)

            initial_size = os.path.getsize(resolved_current_file)
            publisher.publish(600)
            grown_size = await _wait_for_file_growth(
                resolved_current_file,
                initial_size,
                timeout_sec=12.0,
                on_retry=lambda: publisher.publish(100),
            )
            self.assertGreater(
                grown_size,
                initial_size,
                f"recording file did not grow: path={resolved_current_file} initial={initial_size} final={grown_size}",
            )

            await session.handle_close_request_async(
                "shutdown_gui_launched",
                (f"record:{monitored_view.record_tab.selected_candidate_id}",),
            )
            self.assertTrue(await _wait_for_pid_exit(pid))
        finally:
            if publisher is not None:
                publisher.close()
            close = getattr(assembly.admin_client, "close", None)
            if callable(close):
                await close()
            close = getattr(assembly.monitoring_client, "close", None)
            if callable(close):
                await close()
            if pid is not None and _pid_is_running(pid):
                _kill_pid(pid)

    async def test_default_gui_launch_receives_live_monitoring_current_file(self):
        run_id = f"gui_default_monitoring_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(PARENT_DIR, "service_churn", "integration_tests", run_id)
        os.makedirs(run_dir, exist_ok=True)
        admin_domain_id = 330 + (os.getpid() % 40)
        data_domain_id = admin_domain_id + 1
        recording_config = os.path.join(REPO_ROOT, "dds", "qos", "recording_service.xml")
        qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
        assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.LIVE,
            workspace_name="Live Default Monitoring",
            recording_working_dir=run_dir,
            recording_config_paths=(recording_config, qos_file),
            recording_config_name="template",
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=admin_domain_id,
            topics_domain_id=data_domain_id,
            start_runtime=True,
        ))
        session = assembly.session
        pid = None
        try:
            initial_view = await session.next_view_async(process_commands=False)
            launch_command = build_record_launch_command(initial_view.record_tab.launch)
            launch_payload = dict(launch_command.payload)
            launch_payload.update({
                "data_domain_id": data_domain_id,
                "admin_domain_id": admin_domain_id,
                "monitoring_domain_id": admin_domain_id,
                "working_dir": run_dir,
            })
            session.command_sink(AppCommand(
                command_type=launch_command.command_type,
                target=launch_command.target,
                payload=launch_payload,
                command_id="launch-default-live-monitoring-recording",
                created_at=time.time(),
            ))

            launch_view = await session.next_view_async()
            selected = launch_view.record_tab.selected_candidate
            self.assertIsNotNone(selected)
            pid = int(selected.pid)
            self.assertGreater(pid, 0)
            self.assertTrue(selected.control_name.startswith("recording_service_"))
            self.assertNotEqual(selected.control_name, "template")

            monitored_view = await _wait_for_current_file(session)
            selected = monitored_view.record_tab.selected_candidate
            self.assertIsNotNone(selected)
            self.assertEqual(selected.control_name, launch_view.record_tab.selected_candidate.control_name)
            self.assertEqual(selected.source, "monitoring")
            self.assertTrue(selected.current_file, monitored_view.record_tab.monitoring_summary)
            self.assertIn(("current_file", selected.current_file), monitored_view.record_tab.monitoring_summary)
            self.assertTrue(any(
                entry.event_type == "service.monitoring_update"
                and entry.payload["service"]["name"] == selected.control_name
                for entry in monitored_view.event_log
            ))
            live_state_view = await _wait_for_live_monitoring_state(session)
            live_state = live_state_view.record_tab.selected_candidate.state
            self.assertIn(live_state, {"ENABLED", "STARTED", "RUNNING", "PAUSED"})
            self.assertEqual(live_state_view.record_tab.observed_state, live_state)
            resolved_current_file = selected.current_file
            if not os.path.isabs(resolved_current_file):
                resolved_current_file = os.path.join(run_dir, resolved_current_file)
            self.assertTrue(os.path.exists(resolved_current_file), selected.current_file)

            await session.handle_close_request_async(
                "shutdown_gui_launched",
                (f"record:{monitored_view.record_tab.selected_candidate_id}",),
            )

            self.assertTrue(await _wait_for_pid_exit(pid))
        finally:
            close = getattr(assembly.admin_client, "close", None)
            if callable(close):
                await close()
            close = getattr(assembly.monitoring_client, "close", None)
            if callable(close):
                await close()
            if pid is not None and _pid_is_running(pid):
                _kill_pid(pid)

    async def test_real_recording_service_exit_updates_next_gui_view(self):
        executable = _LIVE_EXECUTABLE
        run_id = f"gui_session_live_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(PARENT_DIR, "service_churn", "integration_tests", run_id)
        os.makedirs(run_dir, exist_ok=True)
        service_config = os.path.join(REPO_ROOT, "services", "recording_service_config.xml")
        qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
        admin_domain_id = 100 + (os.getpid() % 80)
        data_domain_id = admin_domain_id + 1
        runtime = AppRuntime()
        manager = ServiceProcessManager(
            spawner=SubprocessServiceProcessSpawner(),
            hostname="dev-host",
        )
        controller = RecordTabController(
            manager,
            admin_facade=None,
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=50),
            record_controller=controller,
        )
        pid = None
        try:
            session.command_sink(AppCommand(
                command_type="service.launch_recording",
                target="recording",
                payload={
                    "label": "Live Integration Recorder",
                    "config_paths": [service_config, qos_file],
                    "config_name": "deploy",
                    "data_domain_id": data_domain_id,
                    "admin_domain_id": admin_domain_id,
                    "monitoring_domain_id": admin_domain_id,
                    "verbosity": "ERROR:ERROR",
                    "executable": executable,
                    "working_dir": run_dir,
                },
                command_id="launch-live-recording",
                created_at=time.time(),
            ))

            await session.next_view_async()
            running_view = await _wait_for_state(session, "running")
            self.assertIsNotNone(running_view)
            self.assertEqual(running_view.record_tab.observed_state, "running")
            self.assertIsNotNone(running_view.record_tab.selected_candidate)
            pid = int(running_view.record_tab.selected_candidate.pid)
            self.assertGreater(pid, 0)
            selected_candidate = session.record_controller.last_selection.selected_candidate
            self.assertIsNotNone(selected_candidate)
            command_line = selected_candidate.details["command_line"]
            output_path = selected_candidate.details["output_path"]
            self.assertEqual(command_line[0], executable)
            self.assertTrue(os.path.isfile(output_path))

            _terminate_pid(pid)
            exited_view = await _wait_for_state(session, "exited")

            self.assertIsNotNone(exited_view)
            self.assertEqual(exited_view.record_tab.selected_candidate.pid, str(pid))
            self.assertEqual(exited_view.record_tab.observed_state, "exited")
            exit_event = next(
                entry for entry in exited_view.event_log
                if entry.message == "Recording Service process observed: exited"
            )
            self.assertEqual(exit_event.level, "error")
            self.assertIn("returncode", exit_event.payload["candidate"]["details"])
        finally:
            if pid is not None:
                final_view = await _wait_for_state(session, "exited", timeout_sec=1.0)
                if final_view is None or final_view.record_tab.observed_state != "exited":
                    _kill_pid(pid)

    async def test_real_admin_shutdown_with_monitoring_updates_exited_gui_view(self):
        executable = _LIVE_EXECUTABLE
        run_id = f"gui_session_admin_shutdown_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(PARENT_DIR, "service_churn", "integration_tests", run_id)
        os.makedirs(run_dir, exist_ok=True)
        service_config = os.path.join(REPO_ROOT, "services", "recording_service_config.xml")
        qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
        admin_domain_id = 190 + (os.getpid() % 50)
        data_domain_id = admin_domain_id + 1
        admin_config = replace(
            default_rti_service_admin_config(),
            discovery_timeout_sec=5.0,
            reply_timeout_sec=5.0,
        )
        monitoring_config = replace(
            default_rti_service_monitoring_config(),
            poll_interval_sec=0.1,
        )
        admin_client = RtiServiceAdminClient(admin_config)
        monitoring_client = RtiServiceMonitoringClient(monitoring_config)
        runtime = AppRuntime()
        manager = ServiceProcessManager(
            spawner=SubprocessServiceProcessSpawner(),
            hostname="dev-host",
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(admin_client),
            monitoring_facade=ServiceMonitoringFacade(monitoring_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=80),
            record_controller=controller,
        )
        pid = None
        try:
            session.command_sink(AppCommand(
                command_type="service.launch_recording",
                target="recording",
                payload={
                    "label": "Live Integration Admin Recorder",
                    "config_paths": [service_config, qos_file],
                    "config_name": "deploy",
                    "data_domain_id": data_domain_id,
                    "admin_domain_id": admin_domain_id,
                    "monitoring_domain_id": admin_domain_id,
                    "verbosity": "ERROR:ERROR",
                    "executable": executable,
                    "working_dir": run_dir,
                },
                command_id="launch-live-admin-recording",
                created_at=time.time(),
            ))

            await session.next_view_async()
            running_view = await _wait_for_state(session, "running")
            if running_view.record_tab.observed_state != "running":
                running_view = await session.next_view_async(process_commands=False)
            self.assertIsNotNone(running_view.record_tab.selected_candidate)
            pid = int(running_view.record_tab.selected_candidate.pid)
            self.assertGreater(pid, 0)

            deadline = time.monotonic() + 8.0
            monitored_view = running_view
            while time.monotonic() < deadline:
                monitored_view = await session.next_view_async(process_commands=False)
                if any(entry.event_type == "service.monitoring_update" for entry in monitored_view.event_log):
                    break
                await asyncio.sleep(0.1)
            self.assertTrue(any(
                entry.event_type == "service.monitoring_update"
                for entry in monitored_view.event_log
            ))
            monitored_pid = int(monitored_view.record_tab.selected_candidate.pid)
            monitored_candidate_id = monitored_view.record_tab.selected_candidate_id
            monitored_control_name = monitored_view.record_tab.selected_candidate.control_name
            self.assertGreater(monitored_pid, 0)

            session.command_sink(AppCommand(
                command_type="service.shutdown",
                target="recording",
                payload={"candidate_id": monitored_candidate_id},
                command_id="shutdown-live-admin-recording",
                created_at=time.time(),
                timeout_sec=5.0,
            ))
            await session.next_view_async()
            exited_view = await _wait_for_candidate_state(
                session,
                "exited",
                candidate_id=monitored_candidate_id,
                control_name=monitored_control_name,
                pid=str(monitored_pid),
                timeout_sec=8.0,
            )

            self.assertIsNotNone(exited_view)
            exited_candidate = _candidate_by_identity(
                exited_view,
                candidate_id=monitored_candidate_id,
                control_name=monitored_control_name,
                pid=str(monitored_pid),
            )
            self.assertIsNotNone(exited_candidate)
            self.assertEqual(exited_candidate.pid, str(monitored_pid))
            self.assertEqual(exited_candidate.state, "exited")
            self.assertTrue(any(
                entry.message == "Recording Service process observed: exited"
                for entry in exited_view.event_log
            ))
        finally:
            await admin_client.close()
            await monitoring_client.close()
            if pid is not None:
                final_view = await _wait_for_state(session, "exited", timeout_sec=1.0)
                if final_view is None or final_view.record_tab.observed_state != "exited":
                    _kill_pid(pid)

    async def test_real_close_request_shutdowns_gui_launched_recording_service(self):
        executable = _LIVE_EXECUTABLE
        run_id = f"gui_session_close_x_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(PARENT_DIR, "service_churn", "integration_tests", run_id)
        os.makedirs(run_dir, exist_ok=True)
        service_config = os.path.join(REPO_ROOT, "services", "recording_service_config.xml")
        qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
        admin_domain_id = 250 + (os.getpid() % 40)
        data_domain_id = admin_domain_id + 1
        admin_config = replace(
            default_rti_service_admin_config(),
            discovery_timeout_sec=5.0,
            reply_timeout_sec=5.0,
        )
        admin_client = RtiServiceAdminClient(admin_config)
        runtime = AppRuntime()
        manager = ServiceProcessManager(
            spawner=SubprocessServiceProcessSpawner(),
            hostname="dev-host",
        )
        controller = RecordTabController(
            manager,
            admin_facade=ServiceAdminFacade(admin_client),
            config=RecordTabControllerConfig(local_hostnames=("dev-host",)),
        )
        session = GuiShellSession(
            runtime=runtime,
            scheduler=UiFrameScheduler(runtime, max_event_log=80),
            record_controller=controller,
        )
        pid = None
        try:
            session.command_sink(AppCommand(
                command_type="service.launch_recording",
                target="recording",
                payload={
                    "label": "Live Integration Close X Recorder",
                    "config_paths": [service_config, qos_file],
                    "config_name": "deploy",
                    "data_domain_id": data_domain_id,
                    "admin_domain_id": admin_domain_id,
                    "monitoring_domain_id": admin_domain_id,
                    "verbosity": "ERROR:ERROR",
                    "executable": executable,
                    "working_dir": run_dir,
                },
                command_id="launch-live-close-x-recording",
                created_at=time.time(),
            ))

            await session.next_view_async()
            running_view = await _wait_for_state(session, "running")
            self.assertIsNotNone(running_view.record_tab.selected_candidate)
            pid = int(running_view.record_tab.selected_candidate.pid)
            self.assertGreater(pid, 0)
            item_id = f"record:{running_view.record_tab.selected_candidate_id}"

            await session.handle_close_request_async("shutdown_gui_launched", (item_id,))

            self.assertTrue(await _wait_for_pid_exit(pid))
            events = runtime.drain_events()
            self.assertTrue(any(
                event.event_type == "gui.close_requested"
                and event.payload["action"] == "shutdown_gui_launched"
                for event in events
            ))
            close_completed = next(event for event in events if event.event_type == "gui.close_completed")
            self.assertEqual(close_completed.payload["action"], "shutdown_gui_launched")
            cleanup_result = close_completed.payload["cleanup_results"][0]
            self.assertEqual(cleanup_result["candidate_id"], running_view.record_tab.selected_candidate_id)
            self.assertTrue(cleanup_result["process_exit_observed"])
            if cleanup_result["local_termination"] is not None:
                self.assertEqual(cleanup_result["local_termination"]["status"], "requested")
        finally:
            await admin_client.close()
            if pid is not None and _pid_is_running(pid):
                _kill_pid(pid)


if __name__ == "__main__":
    unittest.main()
