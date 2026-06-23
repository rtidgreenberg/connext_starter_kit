#!/usr/bin/env python3
"""Smoke tests for the minimal rs_gui Tk shell scaffold."""

import asyncio
import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand
from gui import GuiShellSessionFactoryConfig, GuiShellSessionMode, build_default_gui_shell_session
from rs_gui_app import main
from tk_gui import TkinterUnavailable, build_tk_placeholder_shell, build_tk_session_shell


class TestTkShellSmoke(unittest.TestCase):
    def test_tk_gui_check_returns_success(self):
        result = main(["--tk-gui-check"])
        if result == 2:
            self.skipTest("Tk widgets are unavailable in the current environment")
        self.assertEqual(result, 0)

    def test_session_shell_bootstrap_uses_session_workspace_name(self):
        session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.MOCK,
            workspace_name="Session Bootstrap Regression",
        ))
        try:
            shell = build_tk_session_shell(session)
        except TkinterUnavailable as exc:
            asyncio.run(session.runtime.shutdown())
            self.skipTest(str(exc))
        try:
            shell.refresh_once()
            self.assertIn("Session Bootstrap Regression", shell.root.title())
        finally:
            shell.destroy()
            asyncio.run(session.runtime.shutdown())

    def test_placeholder_shell_has_recording_replay_and_debug_tabs(self):
        try:
            shell = build_tk_placeholder_shell(workspace_name="Slice0 Smoke")
        except TkinterUnavailable as exc:
            self.skipTest(str(exc))
        try:
            self.assertEqual(shell.tab_titles(), ("Recording", "Replay", "Debug"))
            self.assertIn("Slice0 Smoke", shell.root.title())
        finally:
            shell.destroy()

    def test_session_backed_shell_refreshes_title_and_forwards_commands(self):
        session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.MOCK,
        ))
        try:
            shell = build_tk_placeholder_shell(
                workspace_name="Slice1 Smoke",
                view_provider=session.next_view,
                command_sink=session.command_sink,
            )
        except TkinterUnavailable as exc:
            asyncio.run(session.runtime.shutdown())
            self.skipTest(str(exc))
        try:
            view = shell.refresh_once()
            self.assertIn("Robot Run 03", shell.root.title())
            self.assertIn("Runtime:", shell.status_text())
            self.assertIn("Event log:", shell.debug_text())
            self.assertGreaterEqual(len(view.record_tab.candidates), 1)
            self.assertNotEqual(view.record_tab.observed_state, "no service")

            command = AppCommand(
                command_type="service.pause",
                target="recording",
                payload={"candidate_id": "launch-recording-main"},
            )
            self.assertTrue(shell.submit_command(command))
        finally:
            shell.destroy()
            asyncio.run(session.runtime.shutdown())


if __name__ == "__main__":
    unittest.main()