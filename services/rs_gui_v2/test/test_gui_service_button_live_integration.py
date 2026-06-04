#!/usr/bin/env python3
"""Live integration tests for GUI button-driven Recording and Replay flows."""

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

from app_core.connext_environment import detect_nddshome, ensure_rti_license
from fakes import FakeDpg
from gui import GuiShellSessionFactoryConfig, GuiShellSessionMode, build_gui_shell_assembly
from gui.main_window import DearPyGuiShell


def _record_live_requirements():
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
    for path in (
            os.path.join(REPO_ROOT, "services", "recording_service_config.xml"),
            os.path.join(REPO_ROOT, "dds", "qos", "recording_service.xml"),
            os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml"),
    ):
        if not os.path.isfile(path):
            return f"required Recording Service config is missing: {path}", ""
    return "", executable


def _discover_replay_database_dir(root: str = REPO_ROOT) -> str:
    log_root = os.path.join(root, "log_dir")
    if not os.path.isdir(log_root):
        return ""
    candidates = []
    for entry in os.listdir(log_root):
        path = os.path.join(log_root, entry)
        if not os.path.isdir(path) or not entry.startswith("recording_"):
            continue
        if not os.path.isfile(os.path.join(path, "metadata.db")):
            continue
        if not os.path.isfile(os.path.join(path, "data_0.db")):
            continue
        candidates.append(path)
    if not candidates:
        return ""
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def _replay_live_requirements():
    nddshome = detect_nddshome()
    if not nddshome:
        return "NDDSHOME or an RTI Connext installation is required", "", ""
    if importlib.util.find_spec("rti.connextdds") is None:
        return "RTI Connext Python API is required", "", ""
    if importlib.util.find_spec("rti.request") is None:
        return "RTI request/reply Python API is required", "", ""
    executable = os.path.join(nddshome, "bin", "rtireplayservice")
    if not os.path.isfile(executable):
        return f"rtireplayservice not found at {executable}", "", ""
    license_file = ensure_rti_license(nddshome)
    if not license_file:
        return "RTI_LICENSE_FILE or a discoverable RTI license is required", "", ""
    for path in (
            os.path.join(REPO_ROOT, "services", "replay_service_config.xml"),
            os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml"),
    ):
        if not os.path.isfile(path):
            return f"required Replay Service config is missing: {path}", "", ""
    database_dir = _discover_replay_database_dir(REPO_ROOT)
    if not database_dir:
        return "an existing recording database directory is required", "", ""
    return "", executable, database_dir


_LIVE_RECORD_SKIP_REASON, _LIVE_RECORD_EXECUTABLE = _record_live_requirements()
_LIVE_REPLAY_SKIP_REASON, _LIVE_REPLAY_EXECUTABLE, _LIVE_REPLAY_DATABASE_DIR = _replay_live_requirements()


def _enabled_button_callbacks(fake: FakeDpg, label: str):
    callbacks = []
    for name, args, kwargs in fake.calls:
        if name != "add_button" or not kwargs.get("enabled", True):
            continue
        button_label = kwargs.get("label") or (args[0] if args else "")
        if button_label == label:
            callbacks.append(kwargs["callback"])
    if not callbacks:
        raise AssertionError(f"Enabled button not rendered: {label}")
    return callbacks


def _render_shell(view, command_sink, close_handler=None):
    fake = FakeDpg()
    shell = DearPyGuiShell(
        view_provider=lambda: view,
        command_sink=command_sink,
        close_handler=close_handler,
        dpg_module=fake,
    )
    shell.render_once()
    return fake


def _matching_button_index(view, label: str, matcher, close_handler=None) -> int:
    captured = []
    fake = _render_shell(
        view,
        command_sink=lambda command: captured.append(command) or True,
        close_handler=close_handler,
    )
    for index, callback in enumerate(_enabled_button_callbacks(fake, label)):
        captured.clear()
        callback()
        if captured and matcher(captured[-1]):
            return index
    raise AssertionError(f"No enabled {label!r} button matched the expected command")


def _has_matching_button(view, label: str, matcher, close_handler=None) -> bool:
    try:
        _matching_button_index(view, label, matcher, close_handler=close_handler)
        return True
    except AssertionError:
        return False


async def _invoke_matching_button(session, view, label: str, matcher):
    index = _matching_button_index(view, label, matcher, close_handler=session.handle_close_request)
    fake = _render_shell(
        view,
        command_sink=session.command_sink,
        close_handler=session.handle_close_request,
    )
    _enabled_button_callbacks(fake, label)[index]()
    return await session.next_view_async()


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


async def _wait_for_pid_exit(pid, timeout_sec=12.0):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return True
        await asyncio.sleep(0.1)
    return not _pid_is_running(pid)


async def _wait_for_record_view(session, predicate, timeout_sec=12.0, poll_sec=0.1):
    deadline = time.monotonic() + timeout_sec
    last_view = await session.next_view_async(process_commands=False)
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        selected = last_view.record_tab.selected_candidate
        if predicate(last_view, selected):
            return last_view
        await asyncio.sleep(poll_sec)
    state = getattr(last_view.record_tab.selected_candidate, "state", last_view.record_tab.observed_state)
    raise AssertionError(f"Timed out waiting for Record view; last observed state={state!r}")


async def _wait_for_replay_view(session, predicate, timeout_sec=12.0, poll_sec=0.1):
    deadline = time.monotonic() + timeout_sec
    last_view = await session.next_view_async(process_commands=False)
    while time.monotonic() < deadline:
        last_view = await session.next_view_async(process_commands=False)
        selected = last_view.replay_tab.selected_target
        if predicate(last_view, selected):
            return last_view
        await asyncio.sleep(poll_sec)
    state = getattr(last_view.replay_tab.selected_target, "state", last_view.replay_tab.observed_state)
    raise AssertionError(f"Timed out waiting for Replay view; last observed state={state!r}")


async def _wait_for_admin_ready(admin_client, service, timeout_sec=12.0, poll_sec=0.1):
    deadline = time.monotonic() + timeout_sec
    readiness = None
    while time.monotonic() < deadline:
        readiness = await admin_client.check_readiness(service)
        if getattr(readiness, "ready", False):
            return readiness
        await asyncio.sleep(poll_sec)
    return readiness


def _event_messages(view):
    return tuple(entry.message for entry in view.event_log)


@unittest.skipIf(_LIVE_RECORD_SKIP_REASON, _LIVE_RECORD_SKIP_REASON)
class TestRecordingGuiButtonLiveIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_recording_buttons_pause_resume_and_shutdown(self):
        run_id = f"record_button_flow_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(REPO_ROOT, "test_output", "rs_gui_v2", "button_flows", run_id)
        os.makedirs(run_dir, exist_ok=True)
        admin_domain_id = 340 + (os.getpid() % 40)
        data_domain_id = admin_domain_id + 1
        assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.LIVE,
            workspace_name="Record Button Flow",
            recording_working_dir=run_dir,
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=admin_domain_id,
            topics_domain_id=data_domain_id,
            start_runtime=True,
        ))
        session = assembly.session
        pid = None
        try:
            view = await session.next_view_async(process_commands=False)
            await _invoke_matching_button(
                session,
                view,
                "Launch Recording Service",
                lambda command: command.command_type == "service.launch_recording",
            )

            running_view = await _wait_for_record_view(
                session,
                lambda current, selected: (
                    selected is not None
                    and selected.pid
                    and _has_matching_button(
                        current,
                        "Pause",
                        lambda command: command.command_type == "service.pause"
                        and command.payload.get("candidate_id") == current.record_tab.selected_candidate_id,
                        close_handler=session.handle_close_request,
                    )
                ),
            )
            selected = running_view.record_tab.selected_candidate
            self.assertIsNotNone(selected)
            pid = int(selected.pid)
            self.assertGreater(pid, 0)
            readiness = await _wait_for_admin_ready(
                assembly.admin_client,
                assembly.record_controller.last_selection.selected_candidate.service,
            )
            self.assertTrue(getattr(readiness, "ready", False), getattr(readiness, "message", ""))

            running_view = await _wait_for_record_view(
                session,
                lambda current, current_selected: (
                    current_selected is not None
                    and any(message == "Recording Service monitoring event: STARTED" for message in _event_messages(current))
                    and _has_matching_button(
                        current,
                        "Pause",
                        lambda command: command.command_type == "service.pause"
                        and command.payload.get("candidate_id") == current.record_tab.selected_candidate_id,
                        close_handler=session.handle_close_request,
                    )
                ),
            )

            selected = running_view.record_tab.selected_candidate
            self.assertIsNotNone(selected)
            pid = int(selected.pid)
            self.assertGreater(pid, 0)

            selected_id = running_view.record_tab.selected_candidate_id

            await _invoke_matching_button(
                session,
                running_view,
                "Pause",
                lambda command: command.command_type == "service.pause" and command.payload.get("candidate_id") == selected_id,
            )
            paused_view = await _wait_for_record_view(
                session,
                lambda current, current_selected: (
                    current_selected is not None
                    and _has_matching_button(
                        current,
                        "Resume",
                        lambda command: command.command_type == "service.resume"
                        and command.payload.get("candidate_id") == current.record_tab.selected_candidate_id,
                        close_handler=session.handle_close_request,
                    )
                ),
            )
            self.assertEqual(paused_view.record_tab.command_history[0].command, "pause")
            self.assertEqual(str(paused_view.record_tab.selected_candidate.state).upper(), "PAUSED")
            paused_selected_id = paused_view.record_tab.selected_candidate_id

            await _invoke_matching_button(
                session,
                paused_view,
                "Resume",
                lambda command: command.command_type == "service.resume" and command.payload.get("candidate_id") == paused_selected_id,
            )
            resumed_view = await _wait_for_record_view(
                session,
                lambda current, current_selected: (
                    current_selected is not None
                        and str(current.record_tab.selected_candidate.state).upper() == "RUNNING"
                    and _has_matching_button(
                        current,
                        "Pause",
                        lambda command: command.command_type == "service.pause"
                        and command.payload.get("candidate_id") == current.record_tab.selected_candidate_id,
                        close_handler=session.handle_close_request,
                    )
                ),
            )
            self.assertEqual(resumed_view.record_tab.command_history[-1].command, "resume")
            self.assertIn(str(resumed_view.record_tab.selected_candidate.state).upper(), {"RUNNING", "STARTED"})
            resumed_selected_id = resumed_view.record_tab.selected_candidate_id

            await _invoke_matching_button(
                session,
                resumed_view,
                "Shutdown",
                lambda command: command.command_type == "service.shutdown" and command.payload.get("candidate_id") == resumed_selected_id,
            )
            exited_view = await _wait_for_record_view(
                session,
                lambda current, current_selected: (
                    current_selected is not None
                    and current_selected.candidate_id == current.record_tab.selected_candidate_id
                    and str(current_selected.state).lower() in {"exited", "shutdown"}
                ),
                timeout_sec=15.0,
            )

            self.assertTrue(await _wait_for_pid_exit(pid, timeout_sec=15.0))
            self.assertEqual(exited_view.record_tab.command_history[-1].command, "shutdown")
            messages = _event_messages(exited_view)
            self.assertTrue(any(message == "Dispatched service.pause" for message in messages))
            self.assertTrue(any(message == "Dispatched service.resume" for message in messages))
            self.assertTrue(any(message == "Dispatched service.shutdown" for message in messages))
        finally:
            close = getattr(assembly.admin_client, "close", None)
            if callable(close):
                await close()
            close = getattr(assembly.monitoring_client, "close", None)
            if callable(close):
                await close()
            if pid is not None and _pid_is_running(pid):
                _kill_pid(pid)


@unittest.skipIf(_LIVE_REPLAY_SKIP_REASON, _LIVE_REPLAY_SKIP_REASON)
class TestReplayGuiButtonLiveIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_replay_buttons_pause_resume_stop_start_and_shutdown(self):
        run_id = f"replay_button_flow_{os.getpid()}_{int(time.time() * 1000)}"
        run_dir = os.path.join(REPO_ROOT, "test_output", "rs_gui_v2", "button_flows", run_id)
        os.makedirs(run_dir, exist_ok=True)
        admin_domain_id = 420 + (os.getpid() % 40)
        data_domain_id = admin_domain_id + 1
        assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.LIVE,
            workspace_name="Replay Button Flow",
            replay_database_path=_LIVE_REPLAY_DATABASE_DIR,
            replay_working_dir=run_dir,
            admin_domain_id=admin_domain_id,
            monitoring_domain_id=admin_domain_id,
            topics_domain_id=data_domain_id,
            start_runtime=True,
        ))
        assembly.replay_controller._config = replace(assembly.replay_controller._config, loop=True)
        session = assembly.session
        pid = None
        try:
            view = await session.next_view_async(process_commands=False)
            await _invoke_matching_button(
                session,
                view,
                "Launch Replay Service",
                lambda command: command.command_type == "service.launch_replay",
            )

            running_view = await _wait_for_replay_view(
                session,
                lambda current, selected: (
                    selected is not None
                    and selected.pid
                    and _has_matching_button(
                        current,
                        "Pause",
                        lambda command: command.command_type == "replay.pause"
                        and command.payload.get("target_id") == current.replay_tab.selected_target_id,
                        close_handler=session.handle_close_request,
                    )
                ),
                timeout_sec=15.0,
            )
            selected = running_view.replay_tab.selected_target
            self.assertIsNotNone(selected)
            pid = int(selected.pid)
            self.assertGreater(pid, 0)
            target_id = running_view.replay_tab.selected_target_id
            readiness = await _wait_for_admin_ready(
                assembly.admin_client,
                assembly.replay_controller.last_selection.selected_candidate.service,
            )
            self.assertTrue(getattr(readiness, "ready", False), getattr(readiness, "message", ""))

            running_view = await _wait_for_replay_view(
                session,
                lambda current, current_selected: (
                    current_selected is not None
                    and any(message == "Replay Service monitoring event: STARTED" for message in _event_messages(current))
                    and _has_matching_button(
                        current,
                        "Pause",
                        lambda command: command.command_type == "replay.pause"
                        and command.payload.get("target_id") == current.replay_tab.selected_target_id,
                        close_handler=session.handle_close_request,
                    )
                ),
                timeout_sec=15.0,
            )
            selected = running_view.replay_tab.selected_target
            self.assertIsNotNone(selected)
            pid = int(selected.pid)
            self.assertGreater(pid, 0)
            target_id = running_view.replay_tab.selected_target_id

            paused_view = await _invoke_matching_button(
                session,
                running_view,
                "Pause",
                lambda command: command.command_type == "replay.pause" and command.payload.get("target_id") == target_id,
            )
            self.assertEqual(str(paused_view.replay_tab.observed_state).upper(), "PAUSED")
            paused_target_id = paused_view.replay_tab.selected_target_id

            resumed_view = await _invoke_matching_button(
                session,
                paused_view,
                "Resume",
                lambda command: command.command_type == "replay.resume" and command.payload.get("target_id") == paused_target_id,
            )
            self.assertEqual(str(resumed_view.replay_tab.observed_state).upper(), "RUNNING")
            resumed_target_id = resumed_view.replay_tab.selected_target_id

            stopped_view = await _invoke_matching_button(
                session,
                resumed_view,
                "Stop",
                lambda command: command.command_type == "replay.stop" and command.payload.get("target_id") == resumed_target_id,
            )
            self.assertEqual(str(stopped_view.replay_tab.observed_state).upper(), "STOPPED")
            stopped_target_id = stopped_view.replay_tab.selected_target_id

            rerun_view = await _invoke_matching_button(
                session,
                stopped_view,
                "Start",
                lambda command: command.command_type == "replay.start" and command.payload.get("target_id") == stopped_target_id,
            )
            self.assertEqual(str(rerun_view.replay_tab.observed_state).upper(), "RUNNING")
            rerun_selected = rerun_view.replay_tab.selected_target
            self.assertIsNotNone(rerun_selected)
            pid = int(rerun_selected.pid)
            self.assertGreater(pid, 0)
            rerun_target_id = rerun_view.replay_tab.selected_target_id

            await _invoke_matching_button(
                session,
                rerun_view,
                "Shutdown",
                lambda command: command.command_type == "replay.shutdown" and command.payload.get("target_id") == rerun_target_id,
            )
            final_view = await _wait_for_replay_view(
                session,
                lambda current, current_selected: (
                    (current_selected is None or current_selected.target_id == current.replay_tab.selected_target_id)
                    and str(current.replay_tab.observed_state).upper() in {"EXITED", "STOPPED", "SHUTDOWN"}
                ),
                timeout_sec=15.0,
            )

            self.assertTrue(await _wait_for_pid_exit(pid, timeout_sec=15.0))
            messages = _event_messages(final_view)
            self.assertTrue(any(message == "Dispatched replay.pause" for message in messages))
            self.assertTrue(any(message == "Dispatched replay.resume" for message in messages))
            self.assertTrue(any(message == "Dispatched replay.stop" for message in messages))
            self.assertTrue(any(message == "Dispatched replay.start" for message in messages))
            self.assertTrue(any(message == "Dispatched replay.shutdown" for message in messages))
        finally:
            close = getattr(assembly.admin_client, "close", None)
            if callable(close):
                await close()
            close = getattr(assembly.monitoring_client, "close", None)
            if callable(close):
                await close()
            if pid is not None and _pid_is_running(pid):
                _kill_pid(pid)


if __name__ == "__main__":
    unittest.main()