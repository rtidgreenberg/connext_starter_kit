#!/usr/bin/env python3
"""Widget-level tests for the Tk Replay tab slice."""

import os
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from gui import build_mock_shell_view_model
from tk_gui.main_window import TkinterUnavailable, _tk_modules
from tk_gui.tabs import ReplayTabAdapter, TkReplayTab
from tk_gui.tabs.replay_tab import _extract_tag_windows, _resolve_database_dialog_initialdir


class TestTkReplayTab(unittest.TestCase):
    def test_extract_tag_windows_parses_time_ranges(self):
        output = """
tag_alpha: 00:00:01.000 -> 00:00:03.000
tag_beta: 00:01:10 -> 00:01:12
"""
        windows = _extract_tag_windows(output)
        self.assertEqual(
            windows,
            (
                ("00:00:01.000", "00:00:03.000", "tag_alpha"),
                ("00:01:10", "00:01:12", "tag_beta"),
            ),
        )

    def test_extract_tag_windows_parses_multiline_begin_end_format(self):
        output = """
Tag: tag_gamma
Begin Time: 2026-06-08T10:00:00.000Z
End Time: 2026-06-08T10:00:05.000Z
"""
        windows = _extract_tag_windows(output)
        self.assertEqual(
            windows,
            (
                ("2026-06-08T10:00:00.000Z", "2026-06-08T10:00:05.000Z", "tag_gamma"),
            ),
        )

    def test_extract_tag_windows_parses_timestamp_ms_table_format(self):
        output = """
tag_name    timestamp_ms   tag_description
----------  -------------  ---------------
1234        1780954070802
232323      1780954074684
121         1780954077545
"""
        windows = _extract_tag_windows(output)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0][2], "1234")
        self.assertEqual(windows[1][2], "232323")
        self.assertTrue(windows[0][0].endswith("Z"))
        self.assertTrue(windows[0][1].endswith("Z"))

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
            self.assertEqual(widget.content_frame.grid_slaves(row=0, column=0)[0]["text"], "Launch Replay Service")
            self.assertEqual(widget.content_frame.grid_slaves(row=1, column=0)[0]["text"], "Targets And Actions")
            self.assertEqual(widget.content_frame.grid_slaves(row=2, column=0)[0]["text"], "Replay Status")
            self.assertEqual(int(widget.monitoring_text.cget("height")), 5)
            self.assertIn("request+reply matched", widget.readiness_var.get())
            self.assertIn("State: stopped", widget.state_var.get())
            self.assertIn("robot_run_03", widget.database_var.get())
            monitoring_text = widget.monitoring_text.get("1.0", "end-1c")
            self.assertIn("playback_rate", monitoring_text)
            self.assertIn("database", monitoring_text)
            self.assertIn("events", monitoring_text)
            self.assertIn("Robot run", monitoring_text)
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
            widget.service_verbosity_var.set("WARN")
            widget.api_verbosity_var.set("ALL")
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
            self.assertEqual(captured["launch"][0].payload["service_verbosity"], "WARN")
            self.assertEqual(captured["launch"][0].payload["api_verbosity"], "ALL")
            self.assertEqual(captured["launch"][0].payload["verbosity"], "WARN:ALL")
            self.assertEqual(captured["launch"][0].payload["data_domain_id"], 7)
            self.assertEqual(captured["launch"][0].payload["admin_domain_id"], 8)
            self.assertEqual(captured["launch"][0].payload["monitoring_domain_id"], 9)
            self.assertEqual(captured["action"][0].command_type, "replay.start")
        finally:
            root.destroy()

    def test_replay_launch_normalizes_selected_database_file_to_directory(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        captured = {"launch": []}
        adapter = ReplayTabAdapter(
            command_sink=lambda command: captured["launch"].append(command) or True,
            select_target=lambda target_id: target_id,
        )
        try:
            widget = TkReplayTab(root, ttk, tk, adapter=adapter)
            view = build_mock_shell_view_model().replay_tab
            widget.render(view)

            widget.database_path_var.set("/tmp/recording_01/metadata.db")
            widget.launch_button.invoke()

            self.assertEqual(
                captured["launch"][0].payload["database_path"],
                "/tmp/recording_01",
            )
        finally:
            root.destroy()

    def test_replay_launch_defaults_writer_qos_to_transient_local_profile(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        captured = {"launch": []}
        adapter = ReplayTabAdapter(
            command_sink=lambda command: captured["launch"].append(command) or True,
            select_target=lambda target_id: target_id,
        )
        try:
            widget = TkReplayTab(root, ttk, tk, adapter=adapter)
            view = build_mock_shell_view_model().replay_tab
            widget.render(view)

            widget.writer_qos_var.set("")
            widget.writer_transient_local_var.set(True)
            widget.launch_button.invoke()

            self.assertEqual(
                captured["launch"][0].payload["writer_qos_profile"],
                "DataPatternsLibrary::replay_writer_transient_local",
            )
        finally:
            root.destroy()

    def test_replay_browse_uses_current_database_path_as_initialdir(self):
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

            expected_initialdir = _resolve_database_dialog_initialdir(widget.database_path_var.get())
            calls = {}

            def _fake_dialog(**kwargs):
                calls.update(kwargs)
                return ""

            with patch("tkinter.filedialog.askopenfilename", side_effect=_fake_dialog):
                widget._on_browse_database_file()

            self.assertEqual(calls.get("initialdir"), expected_initialdir)
        finally:
            root.destroy()

    def test_replay_launch_preview_is_collapsed_by_default_and_toggleable(self):
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
            root.update_idletasks()

            self.assertEqual(widget.launch_preview_toggle.cget("text"), "> Launch preview")
            self.assertEqual(widget.launch_preview_text.winfo_manager(), "")

            widget.launch_preview_toggle.invoke()
            root.update_idletasks()
            self.assertEqual(widget.launch_preview_toggle.cget("text"), "v Launch preview")
            self.assertEqual(widget.launch_preview_text.winfo_manager(), "grid")

            widget.launch_preview_toggle.invoke()
            root.update_idletasks()
            self.assertEqual(widget.launch_preview_toggle.cget("text"), "> Launch preview")
            self.assertEqual(widget.launch_preview_text.winfo_manager(), "")
        finally:
            root.destroy()

    def test_go_to_tag_sets_time_window_and_dispatches_selected_tag(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        captured = {"launch": [], "action": []}
        adapter = ReplayTabAdapter(
            command_sink=lambda command: captured["launch" if command.command_type == "service.launch_replay" else "action"].append(command) or True,
            select_target=lambda target_id: target_id,
        )
        try:
            widget = TkReplayTab(root, ttk, tk, adapter=adapter)
            view = build_mock_shell_view_model().replay_tab
            widget.render(view)

            widget._tag_windows = (("00:00:10", "00:00:20", "tag_a"),)
            widget._tag_names = ("tag_a",)
            widget._refresh_next_tag_button_state()
            self.assertEqual(widget.go_to_tag_var.get(), "tag_a")
            widget._on_go_to_tag_clicked()

            self.assertEqual(widget.time_window_var.get(), "00:00:10 - 00:00:20")
            self.assertEqual(captured["action"][0].command_type, "replay.next_tag")
            self.assertEqual(captured["action"][0].payload["tag_name"], "tag_a")
            self.assertEqual(captured["action"][0].payload["time_window"], "00:00:10 - 00:00:20")
            self.assertEqual(widget.go_to_tag_var.get(), "tag_a")
        finally:
            root.destroy()

    def test_replay_monitoring_details_toggle_show_hide(self):
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
            root.update_idletasks()

            self.assertEqual(widget.monitoring_toggle.cget("text"), "v Monitoring details")
            self.assertEqual(widget.monitoring_frame.winfo_manager(), "grid")

            widget.monitoring_toggle.invoke()
            root.update_idletasks()
            self.assertEqual(widget.monitoring_toggle.cget("text"), "> Monitoring details")
            self.assertEqual(widget.monitoring_frame.winfo_manager(), "")

            widget.monitoring_toggle.invoke()
            root.update_idletasks()
            self.assertEqual(widget.monitoring_toggle.cget("text"), "v Monitoring details")
            self.assertEqual(widget.monitoring_frame.winfo_manager(), "grid")
        finally:
            root.destroy()

    def test_replay_list_tags_runs_for_selected_database_without_auto_expand(self):
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
            widget.database_path_var.set("services/rs_gui/log_data/xcdr")

            calls = {}

            def _fake_run(cmd, check=False, capture_output=True, text=True):
                calls["cmd"] = cmd
                calls["capture_output"] = capture_output
                calls["text"] = text
                return SimpleNamespace(returncode=0, stdout="TagA\nTagB\n", stderr="")

            with patch("tk_gui.tabs.replay_tab.os.path.isdir", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._has_replay_db_files", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._resolve_list_tags_executable", return_value="/opt/rti/bin/rtirecordingservice_list_tags"), \
                 patch("tk_gui.tabs.replay_tab.subprocess.run", side_effect=_fake_run):
                widget._on_list_tags_clicked()

            self.assertEqual(calls["cmd"][0], "/opt/rti/bin/rtirecordingservice_list_tags")
            self.assertEqual(calls["cmd"][1], "-d")
            self.assertIn("services/rs_gui/log_data/xcdr", calls["cmd"][2])
            self.assertIn("TagA", widget._tags_output_cache)
            self.assertIn("TagB", widget._tags_output_cache)
            self.assertTrue(widget.next_tag_button.instate(("!disabled",)))
            self.assertEqual(widget.go_to_tag_combo["values"], ("TagA", "TagB"))
            self.assertEqual(widget.go_to_tag_var.get(), "TagA")
        finally:
            root.destroy()

    def test_replay_list_tags_enables_next_tag_when_windows_present(self):
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
            widget.database_path_var.set("services/rs_gui/log_data/xcdr")

            def _fake_run(_cmd, check=False, capture_output=True, text=True):
                return SimpleNamespace(
                    returncode=0,
                    stdout="tag_a: 00:00:10 -> 00:00:20\n",
                    stderr="",
                )

            with patch("tk_gui.tabs.replay_tab.os.path.isdir", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._has_replay_db_files", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._resolve_list_tags_executable", return_value="/opt/rti/bin/rtirecordingservice_list_tags"), \
                 patch("tk_gui.tabs.replay_tab.subprocess.run", side_effect=_fake_run):
                widget._on_list_tags_clicked()

            self.assertTrue(bool(widget._tag_windows))
            self.assertTrue(widget.next_tag_button.instate(("!disabled",)))
            self.assertEqual(widget.go_to_tag_var.get(), "tag_a")
        finally:
            root.destroy()

    def test_replay_auto_lists_tags_on_tab_load(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        try:
            calls = {"count": 0}

            def _fake_run(cmd, check=False, capture_output=True, text=True):
                calls["count"] += 1
                calls["cmd"] = cmd
                return SimpleNamespace(returncode=0, stdout="TagLoad 2026-06-08T10:00:00Z", stderr="")

            with patch("tk_gui.tabs.replay_tab.os.path.isdir", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._has_replay_db_files", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._resolve_list_tags_executable", return_value="/opt/rti/bin/rtirecordingservice_list_tags"), \
                 patch("tk_gui.tabs.replay_tab.subprocess.run", side_effect=_fake_run):
                widget = TkReplayTab(root, ttk, tk)
                view = build_mock_shell_view_model().replay_tab
                widget.render(view)

            self.assertGreaterEqual(calls["count"], 1)
            self.assertEqual(calls["cmd"][0], "/opt/rti/bin/rtirecordingservice_list_tags")
            self.assertEqual(widget.tags_status_var.get(), "Tags: found")
            self.assertIn("TagLoad", widget._tags_output_cache)
        finally:
            root.destroy()

    def test_replay_auto_lists_tags_on_new_file_select(self):
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        try:
            widget = TkReplayTab(root, ttk, tk)
            view = build_mock_shell_view_model().replay_tab
            with patch("tk_gui.tabs.replay_tab.os.path.isdir", return_value=False):
                widget.render(view)

            calls = {"count": 0}

            def _fake_run(cmd, check=False, capture_output=True, text=True):
                calls["count"] += 1
                calls["cmd"] = cmd
                return SimpleNamespace(returncode=0, stdout="TagBrowse 2026-06-08T12:00:00Z", stderr="")

            with patch("tkinter.filedialog.askopenfilename", return_value="/tmp/run_42/metadata.db"), \
                 patch("tk_gui.tabs.replay_tab.os.path.isdir", return_value=True), \
                  patch("tk_gui.tabs.replay_tab._has_replay_db_files", return_value=True), \
                 patch("tk_gui.tabs.replay_tab._resolve_list_tags_executable", return_value="/opt/rti/bin/rtirecordingservice_list_tags"), \
                 patch("tk_gui.tabs.replay_tab.subprocess.run", side_effect=_fake_run):
                widget._on_browse_database_file()

            self.assertGreaterEqual(calls["count"], 1)
            self.assertEqual(calls["cmd"][1], "-d")
            self.assertEqual(calls["cmd"][2], "/tmp/run_42")
            self.assertEqual(widget.tags_status_var.get(), "Tags: found")
            self.assertIn("TagBrowse", widget._tags_output_cache)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()