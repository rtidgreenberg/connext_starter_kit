#!/usr/bin/env python3
"""Widget-level tests for the Tk Replay tab slice."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from gui import build_mock_shell_view_model
from tk_gui.main_window import TkinterUnavailable, _tk_modules
from tk_gui.tabs import ReplayTabAdapter, TkReplayTab


class TestTkReplayTab(unittest.TestCase):
    def test_replay_tab_renders_mock_snapshot(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        try:
            widget = TkReplayTab(root, ttk, tk)
            view = build_mock_shell_view_model().replay_tab

            widget.render(view)

            self.assertEqual(len(widget.target_combo["values"]), 2)
            self.assertEqual(widget.frame.grid_slaves(row=0, column=0)[0]["text"], "Launch Replay Service")
            self.assertEqual(widget.frame.grid_slaves(row=1, column=0)[0]["text"], "Targets And Actions")
            self.assertEqual(widget.frame.grid_slaves(row=2, column=0)[0]["text"], "Replay Status")
            self.assertEqual(int(widget.timeline_text.cget("height")), 3)
            self.assertIn("STOPPED", widget.state_var.get())
            self.assertIn("robot_run_03", widget.database_var.get())
            self.assertIn("Robot run", widget.timeline_text.get("1.0", "end-1c"))
            self.assertTrue(widget.action_buttons["start"].instate(("!disabled",)))
            self.assertFalse(widget.action_buttons["pause"].instate(("!disabled",)))
        finally:
            root.destroy()

    def test_replay_tab_forwards_launch_and_action_commands(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        captured = {"select": [], "launch": [], "action": []}
        adapter = ReplayTabAdapter(
            command_sink=lambda command: captured["launch" if command.command_type == "service.launch_replay" else "action"].append(command) or True,
            select_target=lambda target_id: captured["select"].append(target_id) or target_id,
        )
        try:
            widget = TkReplayTab(root, ttk, tk, adapter=adapter)
            view = build_mock_shell_view_model().replay_tab
            widget.render(view)

            first_value = widget.target_combo["values"][0]
            widget.target_select_var.set(first_value)
            widget.topic_allow_var.set("Square,Triangle")
            widget.topic_deny_var.set("rti/*,internal/*")
            widget.data_domain_var.set("7")
            widget.admin_domain_var.set("8")
            widget.monitoring_domain_var.set("9")
            widget._on_target_selected()
            widget.launch_button.invoke()
            widget.action_buttons["start"].invoke()

            self.assertTrue(captured["select"])
            self.assertEqual(captured["launch"][0].command_type, "service.launch_replay")
            self.assertEqual(captured["launch"][0].payload["topic_allow"], "Square,Triangle")
            self.assertEqual(captured["launch"][0].payload["topic_deny"], "rti/*,internal/*")
            self.assertEqual(captured["launch"][0].payload["data_domain_id"], 7)
            self.assertEqual(captured["launch"][0].payload["admin_domain_id"], 8)
            self.assertEqual(captured["launch"][0].payload["monitoring_domain_id"], 9)
            self.assertEqual(captured["action"][0].command_type, "replay.start")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()