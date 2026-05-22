#!/usr/bin/env python3
"""Headless tests for the rs_gui_v2 Dear PyGui shell bridge."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppEvent, AppRuntime, CommandStatus
from app_core.services import (
    ServiceCandidateSelection,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceControlIdentity,
    ServiceKind,
    ServiceLaunchIntent,
    candidate_from_control_identity,
)
from gui import UiFrameScheduler, build_mock_shell_view_model
from gui.main_window import DearPyGuiShell
from gui.tabs.record_tab import build_record_action_command, build_record_tab_view_model
from rs_gui_v2_app import main


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDpg:
    def __init__(self):
        self.calls = []
        self.context_created = False
        self.context_destroyed = False

    def create_context(self):
        self.context_created = True
        self.calls.append(("create_context", (), {}))

    def destroy_context(self):
        self.context_destroyed = True
        self.calls.append(("destroy_context", (), {}))

    def window(self, *args, **kwargs):
        self.calls.append(("window", args, kwargs))
        return FakeContext()

    def tab_bar(self, *args, **kwargs):
        self.calls.append(("tab_bar", args, kwargs))
        return FakeContext()

    def tab(self, *args, **kwargs):
        self.calls.append(("tab", args, kwargs))
        return FakeContext()

    def group(self, *args, **kwargs):
        self.calls.append(("group", args, kwargs))
        return FakeContext()

    def table(self, *args, **kwargs):
        self.calls.append(("table", args, kwargs))
        return FakeContext()

    def table_row(self, *args, **kwargs):
        self.calls.append(("table_row", args, kwargs))
        return FakeContext()

    def add_text(self, *args, **kwargs):
        self.calls.append(("add_text", args, kwargs))

    def add_combo(self, *args, **kwargs):
        self.calls.append(("add_combo", args, kwargs))

    def add_button(self, *args, **kwargs):
        self.calls.append(("add_button", args, kwargs))

    def add_input_text(self, *args, **kwargs):
        self.calls.append(("add_input_text", args, kwargs))

    def add_separator(self, *args, **kwargs):
        self.calls.append(("add_separator", args, kwargs))

    def add_table_column(self, *args, **kwargs):
        self.calls.append(("add_table_column", args, kwargs))


class TestMockShellViewModel(unittest.TestCase):
    def test_mock_shell_contains_record_selector_and_history(self):
        view = build_mock_shell_view_model(now=120.0)

        self.assertEqual(view.active_tab, "Record")
        self.assertIn("Robot Run 03", view.title)
        self.assertEqual(view.record_tab.selected_candidate.control_name, "recording_service_8f4f2a1c")
        self.assertEqual(len(view.record_tab.candidates), 2)
        self.assertEqual(view.record_tab.command_history[0].command_id, "pause-21")
        self.assertTrue(view.record_tab.action_by_id["pause"].enabled)
        self.assertFalse(view.record_tab.action_by_id["terminate_local"].enabled)
        self.assertEqual(view.plots_tab.selected_plot_name, "Robot Motion")
        self.assertEqual(view.plots_tab.total_point_count, 8)

    def test_record_actions_disable_admin_for_duplicate_live_targets(self):
        intent = ServiceLaunchIntent(ServiceKind.RECORDING, "Recorder")
        identity = ServiceControlIdentity(
            intent=intent,
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        first = candidate_from_control_identity(identity, launch_id="launch-1", observed_at=1.0)
        second = candidate_from_control_identity(identity, launch_id="launch-2", observed_at=2.0)
        selection = ServiceCandidateSelection(
            candidates=(first, second),
            selected_candidate_id="launch-1",
        )

        record = build_record_tab_view_model(selection, now=3.0)

        self.assertTrue(record.candidates[0].conflict)
        self.assertFalse(record.action_by_id["pause"].enabled)
        self.assertIn("duplicate service admin target", record.diagnostics)

    def test_record_action_command_preserves_target_and_tag_payload(self):
        view = build_mock_shell_view_model()
        candidate = candidate_from_control_identity(
            ServiceControlIdentity(
                ServiceLaunchIntent(ServiceKind.RECORDING, "Recorder"),
                session_guid="11111111-2222-3333-4444-555555555555",
            ),
            launch_id="launch-1",
            pid=10,
            hostname="dev-host",
            observed_at=1.0,
        )

        command = build_record_action_command(
            "tag",
            candidate,
            tag_name="night_run",
            description="operator tag",
        )

        self.assertEqual(command.command_type, "service.tag")
        self.assertEqual(command.target, candidate.service.key)
        self.assertEqual(command.payload["tag_name"], "night_run")
        self.assertEqual(command.payload["candidate_id"], "launch-1")
        self.assertTrue(view.record_tab.action_by_id["tag"].enabled)
        with self.assertRaises(ValueError):
            build_record_action_command("tag", candidate)


class TestUiFrameScheduler(unittest.TestCase):
    def test_scheduler_drains_events_into_bounded_log(self):
        runtime = AppRuntime()
        runtime.publish_event(AppEvent(
            event_type="test.event",
            source="test",
            payload={"message": "first", "level": "debug"},
            created_at=1.0,
        ))
        runtime.publish_event(AppEvent(
            event_type="test.event",
            source="test",
            payload={"message": "second", "level": "info"},
            created_at=2.0,
        ))
        scheduler = UiFrameScheduler(runtime, max_event_log=1)

        view = scheduler.next_view()

        self.assertEqual(len(view.event_log), 1)
        self.assertEqual(view.event_log[0].message, "second")
        self.assertEqual(runtime.drain_events(), [])


class TestDearPyGuiRenderer(unittest.TestCase):
    def test_render_once_uses_injected_dearpygui_module(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(dpg_module=fake)

        view = shell.render_once()

        call_names = [name for name, _args, _kwargs in fake.calls]
        self.assertTrue(fake.context_created)
        self.assertTrue(fake.context_destroyed)
        self.assertIn("window", call_names)
        self.assertIn("tab_bar", call_names)
        self.assertIn("add_button", call_names)
        self.assertEqual(view.record_tab.selected_candidate.control_name, "recording_service_8f4f2a1c")


class TestGuiEntrypoint(unittest.TestCase):
    def test_mock_gui_check_returns_success(self):
        self.assertEqual(main(["--mock-gui-check"]), 0)


if __name__ == "__main__":
    unittest.main()
