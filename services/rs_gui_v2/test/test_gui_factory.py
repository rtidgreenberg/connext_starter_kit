#!/usr/bin/env python3
"""Headless tests for default GUI shell session assembly."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand, LifecyclePhase
from app_core.services import ServiceCommand
from gui import (
    GuiShellSessionFactoryConfig,
    GuiShellSessionMode,
    build_default_gui_shell_session,
    build_gui_shell_assembly,
)
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


class TestGuiShellFactory(unittest.TestCase):
    def test_mock_assembly_builds_controller_backed_session(self):
        assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
            workspace_name="Factory Workspace",
            unsaved=True,
            start_runtime=True,
        ))

        view = assembly.session.next_view()

        self.assertEqual(assembly.runtime.lifecycle, LifecyclePhase.RUNNING)
        self.assertIsNotNone(assembly.admin_client)
        self.assertIsNotNone(assembly.monitoring_client)
        self.assertIsNotNone(assembly.discovery_client)
        self.assertIn("Factory Workspace", view.title)
        self.assertTrue(view.title.endswith("*"))
        self.assertEqual(view.record_tab.selected_candidate_id, "launch-recording-main")
        self.assertEqual(view.record_tab.selected_candidate.control_name, "recording_service_8f4f2a1c")
        self.assertIn(("memory_mb", "180"), view.record_tab.monitoring_summary)
        self.assertEqual(view.topics_tab.selected_topic.topic_name, "RobotTelemetry")
        self.assertEqual(view.plots_tab.selected_plot_name, "Robot Motion")
        self.assertEqual(view.plots_tab.total_point_count, 8)
        self.assertEqual(assembly.discovery_client.scans, [(0, False)])

    def test_default_session_dispatches_commands_through_fake_admin(self):
        assembly = build_gui_shell_assembly()
        assembly.session.next_view()
        command = AppCommand(
            command_type="service.pause",
            payload={"candidate_id": "launch-recording-main"},
            command_id="pause-from-factory",
            created_at=1.0,
        )

        self.assertTrue(assembly.session.command_sink(command))
        view = assembly.session.next_view()

        self.assertEqual([request.command for request in assembly.admin_client.requests], [
            ServiceCommand.PAUSE,
        ])
        self.assertEqual(view.record_tab.command_history[0].command, "pause")
        self.assertTrue(any(entry.message == "Dispatched service.pause" for entry in view.event_log))

    def test_headless_assembly_has_no_mock_launch_or_fake_clients(self):
        assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.HEADLESS,
            workspace_name="Headless Wiring",
        ))

        view = assembly.session.next_view()

        self.assertIsNone(assembly.admin_client)
        self.assertIsNone(assembly.monitoring_client)
        self.assertIsNone(assembly.discovery_client)
        self.assertEqual(assembly.process_manager.launches(), ())
        self.assertEqual(view.record_tab.candidates, ())
        self.assertEqual(view.record_tab.target_label, "No Recording Service")
        self.assertEqual(view.topics_tab.rows, ())
        self.assertEqual(view.plots_tab.rows, ())

    def test_default_session_convenience_returns_session_only(self):
        session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(
            workspace_name="Session Only",
        ))

        view = session.next_view()

        self.assertIn("Session Only", view.title)
        self.assertEqual(view.record_tab.selected_candidate_id, "launch-recording-main")

    def test_shell_can_render_factory_session_with_injected_dearpygui(self):
        assembly = build_gui_shell_assembly()
        fake = FakeDpg()
        shell = assembly.shell(dpg_module=fake)

        view = shell.render_once()

        self.assertEqual(view.record_tab.selected_candidate_id, "launch-recording-main")
        self.assertTrue(fake.context_created)
        self.assertTrue(fake.context_destroyed)


class TestGuiFactoryEntrypoint(unittest.TestCase):
    def test_mock_gui_check_uses_factory_session(self):
        self.assertEqual(main(["--mock-gui-check"]), 0)


if __name__ == "__main__":
    unittest.main()
