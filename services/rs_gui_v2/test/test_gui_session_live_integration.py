#!/usr/bin/env python3
"""Live integration tests for GUI-owned Recording Service lifecycle."""

import asyncio
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
from app_core.services import ServiceProcessManager, SubprocessServiceProcessSpawner
from gui import GuiShellSession, UiFrameScheduler
from gui.tabs import RecordTabController, RecordTabControllerConfig


def _live_requirements():
    nddshome = detect_nddshome()
    if not nddshome:
        return "NDDSHOME or an RTI Connext installation is required", ""
    executable = os.path.join(nddshome, "bin", "rtirecordingservice")
    if not os.path.isfile(executable):
        return f"rtirecordingservice not found at {executable}", ""
    license_file = ensure_rti_license(nddshome)
    if not license_file:
        return "RTI_LICENSE_FILE or a discoverable RTI license is required", ""
    service_config = os.path.join(REPO_ROOT, "services", "recording_service_config.xml")
    qos_file = os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml")
    for path in (service_config, qos_file):
        if not os.path.isfile(path):
            return f"required Recording Service config is missing: {path}", ""
    return "", executable


_LIVE_SKIP_REASON, _LIVE_EXECUTABLE = _live_requirements()


async def _wait_for_state(session, expected_state, timeout_sec=8.0):
    deadline = time.monotonic() + timeout_sec
    last_view = None
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        if last_view.record_tab.observed_state == expected_state:
            return last_view
        await asyncio.sleep(0.1)
    return last_view


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


@unittest.skipIf(_LIVE_SKIP_REASON, _LIVE_SKIP_REASON)
class TestGuiSessionLiveIntegration(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
