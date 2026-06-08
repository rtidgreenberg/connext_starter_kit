#!/usr/bin/env python3
"""Widget-level tests for the Tk Record tab slice."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from gui import build_mock_shell_view_model
from tk_gui.main_window import TkinterUnavailable, _tk_modules
from tk_gui.tabs import RecordTabAdapter, TkRecordTab


class FakeCandidate:
    def __init__(self, candidate_id: str):
        self.candidate_id = candidate_id
        self.launch_id = candidate_id
        self.pid = 1234
        self.hostname = "dev-host"
        self.service = type("Service", (), {"key": "recording:key", "to_dict": lambda self: {"key": "recording:key"}})()


class TestTkRecordTab(unittest.TestCase):
    def test_record_tab_renders_mock_snapshot(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        try:
            widget = TkRecordTab(root, ttk, tk)
            view = build_mock_shell_view_model().record_tab

            widget.render(view)

            self.assertEqual(len(widget.candidate_combo["values"]), 2)
            self.assertEqual(widget.frame.grid_slaves(row=0, column=0)[0]["text"], "Launch Recording Service")
            self.assertEqual(widget.frame.grid_slaves(row=1, column=0)[0]["text"], "Candidates And Actions")
            self.assertEqual(widget.frame.grid_slaves(row=2, column=0)[0]["text"], "Record Status")
            self.assertEqual(int(widget.monitoring_text.cget("height")), 3)
            self.assertIn("request+reply matched", widget.readiness_var.get())
            self.assertIn("memory_mb", widget.monitoring_text.get("1.0", "end-1c"))
            self.assertIn("pause: pause acknowledged", widget.command_history.get(0))
            self.assertFalse(widget.action_buttons["terminate_local"].instate(("!disabled",)))
            self.assertTrue(widget.action_buttons["pause"].instate(("!disabled",)))
        finally:
            root.destroy()

    def test_record_tab_forwards_launch_and_action_commands(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        captured = {"select": [], "tag": [], "launch": [], "action": []}
        adapter = RecordTabAdapter(
            command_sink=lambda command: captured["launch" if command.command_type == "service.launch_recording" else "action"].append(command) or True,
            select_candidate=lambda candidate_id: captured["select"].append(candidate_id),
            set_tag_value=lambda value: captured["tag"].append(value),
            resolve_candidate=lambda candidate_id: FakeCandidate(candidate_id),
        )
        try:
            widget = TkRecordTab(root, ttk, tk, adapter=adapter)
            view = build_mock_shell_view_model().record_tab
            widget.render(view)

            first_value = widget.candidate_combo["values"][0]
            widget.candidate_var.set(first_value)
            widget._on_candidate_selected()
            widget.tag_var.set("slice2_tag")
            widget.topic_allow_var.set("Robot*,Square")
            widget.topic_deny_var.set("rti/*,internal/*")
            widget.launch_button.invoke()
            widget.action_buttons["tag"].invoke()

            self.assertTrue(captured["select"])
            self.assertIn("slice2_tag", captured["tag"])
            self.assertEqual(captured["launch"][0].command_type, "service.launch_recording")
            self.assertEqual(captured["launch"][0].payload["topic_allow"], "Robot*,Square")
            self.assertEqual(captured["launch"][0].payload["topic_deny"], "rti/*,internal/*")
            self.assertEqual(captured["action"][0].command_type, "service.tag")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()