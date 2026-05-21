#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

"""
Tests for recording_service_gui.py

Three test layers:
  1. Pure logic tests — no tkinter, no DDS
  2. Widget tests — tkinter (headless), mock DDS
  3. Integration smoke tests — tkinter + DDS (optional, requires rti.connextdds)

Run:
    python3 test/test_gui.py                        # all tests
    python3 test/test_gui.py -v                     # verbose
    python3 -m pytest test/test_gui.py -v -k "not Integration"  # skip DDS
"""

import os
import sys
import shlex
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure the parent directory (recording_service_gui/) is on the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from recording_service_gui import (
    detect_nddshome,
    parse_config_names,
    build_launch_command,
    detect_terminal_emulator,
    format_file_size,
    format_uptime,
    STATE_INVALID,
    STATE_RUNNING,
    STATE_PAUSED,
    DEFAULT_DOMAIN_ID,
    DEFAULT_ADMIN_DOMAIN_ID,
    FG_GREEN,
    FG_ORANGE,
    FG_RED,
    FG_DIM,
    FG_TEXT,
)


# ===================================================================
# Layer 1: Pure Logic Tests (no tkinter, no DDS)
# ===================================================================

class TestParseConfigNames(unittest.TestCase):
    """Test parse_config_names helper."""

    def test_parse_real_config(self):
        """Parse the actual recording_service_config.xml."""
        cfg = os.path.join(PARENT_DIR, "..", "recording_service_config.xml")
        names = parse_config_names(cfg)
        self.assertIn("deploy", names)
        self.assertIn("debug", names)

    def test_parse_missing_file(self):
        """Missing file returns empty list."""
        self.assertEqual(parse_config_names("/nonexistent/file.xml"), [])

    def test_parse_invalid_xml(self):
        """Invalid XML returns empty list."""
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False) as f:
            f.write("<<<not valid xml>>>")
            f.flush()
            names = parse_config_names(f.name)
        os.unlink(f.name)
        self.assertEqual(names, [])

    def test_parse_no_recording_service(self):
        """Valid XML without recording_service elements → empty list."""
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False) as f:
            f.write('<?xml version="1.0"?><dds></dds>')
            f.flush()
            names = parse_config_names(f.name)
        os.unlink(f.name)
        self.assertEqual(names, [])

    def test_parse_multiple_configs(self):
        """XML with multiple recording_service elements."""
        xml = '''<?xml version="1.0"?>
        <dds>
            <recording_service name="alpha"/>
            <recording_service name="beta"/>
            <recording_service name="gamma"/>
        </dds>'''
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False) as f:
            f.write(xml)
            f.flush()
            names = parse_config_names(f.name)
        os.unlink(f.name)
        self.assertEqual(names, ["alpha", "beta", "gamma"])

    def test_parse_disappearing_file(self):
        """File open race is handled gracefully."""
        with patch("os.path.isfile", return_value=True), \
                patch("xml.etree.ElementTree.parse",
                      side_effect=FileNotFoundError):
            self.assertEqual(parse_config_names("/tmp/gone.xml"), [])


class TestBuildLaunchCommand(unittest.TestCase):
    """Test build_launch_command helper."""

    def test_basic_command(self):
        cmd = build_launch_command(
            "/opt/rti", "config.xml", "deploy", 1, 1, "ERROR:ERROR")
        self.assertEqual(cmd[0], "/opt/rti/bin/rtirecordingservice")
        self.assertEqual(cmd[cmd.index("-cfgFile") + 1], "config.xml")
        self.assertEqual(cmd[cmd.index("-cfgName") + 1], "deploy")
        self.assertIn("-DDOMAIN_ID=1", cmd)
        self.assertIn("-DADMIN_DOMAIN_ID=1", cmd)
        self.assertEqual(cmd[cmd.index("-verbosity") + 1], "ERROR:ERROR")

    def test_custom_domain_ids(self):
        cmd = build_launch_command("/opt/rti", "f.xml", "t", 42, 7, "SILENT")
        self.assertIn("-DDOMAIN_ID=42", cmd)
        self.assertIn("-DADMIN_DOMAIN_ID=7", cmd)

    def test_returns_list_of_strings(self):
        cmd = build_launch_command("/opt/rti", "f.xml", "t", 0, 0, "SILENT")
        self.assertIsInstance(cmd, list)
        self.assertTrue(all(isinstance(c, str) for c in cmd))

    def test_qos_file_appended(self):
        cmd = build_launch_command(
            "/opt/rti", "config.xml", "deploy", 1, 0, "ERROR:ERROR",
            qos_file="/path/to/qos.xml")
        cfg_value = cmd[cmd.index("-cfgFile") + 1]
        self.assertEqual(cfg_value, "config.xml;/path/to/qos.xml")

    def test_no_qos_file_when_none(self):
        cmd = build_launch_command(
            "/opt/rti", "config.xml", "deploy", 1, 0, "ERROR:ERROR")
        cfg_value = cmd[cmd.index("-cfgFile") + 1]
        self.assertEqual(cfg_value, "config.xml")

    def test_no_qos_file_when_empty(self):
        cmd = build_launch_command(
            "/opt/rti", "config.xml", "deploy", 1, 0, "ERROR:ERROR",
            qos_file="")
        cfg_value = cmd[cmd.index("-cfgFile") + 1]
        self.assertEqual(cfg_value, "config.xml")


class TestDetectTerminalEmulator(unittest.TestCase):
    """Test detect_terminal_emulator helper."""

    @patch("shutil.which")
    def test_gnome_terminal_preferred(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/" + x
        self.assertEqual(detect_terminal_emulator(), ["gnome-terminal", "--"])

    @patch("shutil.which")
    def test_fallback_to_xterm(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/xterm" if x == "xterm" else None)
        self.assertEqual(detect_terminal_emulator(), ["xterm", "-e"])

    @patch("shutil.which")
    def test_no_terminal(self, mock_which):
        mock_which.return_value = None
        self.assertEqual(detect_terminal_emulator(), [])


class TestFormatFileSize(unittest.TestCase):
    """Test format_file_size helper."""

    def test_bytes(self):
        self.assertEqual(format_file_size(500), "500 B")

    def test_kilobytes(self):
        self.assertIn("KB", format_file_size(2048))

    def test_megabytes(self):
        self.assertIn("MB", format_file_size(5 * 1024 * 1024))

    def test_gigabytes(self):
        self.assertIn("GB", format_file_size(3 * 1024 * 1024 * 1024))

    def test_zero(self):
        self.assertEqual(format_file_size(0), "0 B")

    def test_negative(self):
        self.assertEqual(format_file_size(-1), "N/A")


class TestFormatUptime(unittest.TestCase):
    """Test format_uptime helper."""

    def test_seconds_only(self):
        self.assertEqual(format_uptime(45), "45s")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_uptime(125), "2m 5s")

    def test_hours_minutes_seconds(self):
        self.assertEqual(format_uptime(3661), "1h 1m 1s")

    def test_negative(self):
        self.assertEqual(format_uptime(-1), "N/A")

    def test_zero(self):
        self.assertEqual(format_uptime(0), "0s")


class TestDetectNddshome(unittest.TestCase):
    """Test detect_nddshome helper."""

    def test_returns_string(self):
        self.assertIsInstance(detect_nddshome(), str)

    @patch.dict(os.environ, {"NDDSHOME": "/test/rti_path"})
    @patch("os.path.isdir", return_value=True)
    def test_uses_env_var(self, _):
        self.assertEqual(detect_nddshome(), "/test/rti_path")


# ===================================================================
# Layer 2: Widget Tests (tkinter, mock DDS)
# ===================================================================

class TestWidgets(unittest.TestCase):
    """
    Test GUI widget interactions.

    Uses _skip_dds=True to avoid requiring DDS libraries.
    Creates a single hidden Tk root for all tests.
    """

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = __import__("tkinter").Tk()
            cls.root.withdraw()
        except Exception:
            raise unittest.SkipTest("tkinter display not available")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        from recording_service_gui import RecordingServiceGUI
        self.gui = RecordingServiceGUI(self.root, _skip_dds=True)
        self.root.update()

    def tearDown(self):
        self.gui.close()
        self.root.update_idletasks()

    # --- Config panel -------------------------------------------------------

    def test_config_file_populates_dropdown(self):
        """Selecting a config XML populates the Config Name combobox."""
        cfg = os.path.join(PARENT_DIR, "..", "recording_service_config.xml")
        self.gui._config_file_var.set(cfg)
        self.root.update()
        values = list(self.gui._config_name_combo["values"])
        self.assertIn("deploy", values)

    def test_domain_id_default(self):
        """Domain ID spinbox defaults correctly."""
        self.assertEqual(self.gui._domain_id_var.get(), DEFAULT_DOMAIN_ID)

    def test_admin_domain_default(self):
        """Admin Domain ID spinbox defaults correctly."""
        self.assertEqual(
            self.gui._admin_domain_id_var.get(), DEFAULT_ADMIN_DOMAIN_ID)

    # --- Launch command -----------------------------------------------------

    def test_launch_button_builds_command(self):
        """get_launch_command() produces correct command list."""
        cmd = self.gui.get_launch_command()
        self.assertIsInstance(cmd, list)
        self.assertTrue(cmd[0].endswith("rtirecordingservice"))

    @patch("subprocess.Popen")
    @patch("recording_service_gui.detect_terminal_emulator")
    @patch("os.path.isfile", return_value=True)
    def test_launch_quotes_paths_with_spaces(
            self, _mock_isfile, mock_terminal, mock_popen):
        """Launch command is shell-safe for paths with spaces."""
        mock_terminal.return_value = ["xterm", "-e"]
        self.gui._nddshome_var.set("/tmp/rti install")
        self.gui._config_file_var.set("/tmp/config dir/config.xml")
        self.gui._config_name_var.set("deploy")

        self.gui._on_launch()

        args, kwargs = mock_popen.call_args
        bash_cmd = args[0][-1]
        expected = shlex.join(self.gui.get_launch_command())
        self.assertIn(expected, bash_cmd)
        self.assertTrue(kwargs["start_new_session"])

    # --- Button states ------------------------------------------------------

    def test_button_states_no_service(self):
        """Before service detected: Launch=normal, controls=disabled."""
        self.gui._service_detected = False
        self.gui._service_state = STATE_INVALID
        self.gui._update_button_states()
        self.root.update()

        self.assertEqual(str(self.gui._launch_btn["state"]), "normal")
        self.assertEqual(str(self.gui._pause_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._resume_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._shutdown_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._tag_btn["state"]), "disabled")

    def test_button_states_running(self):
        """When RUNNING: Pause=normal, Resume=disabled."""
        self.gui._service_detected = True
        self.gui.set_service_state(STATE_RUNNING)
        self.root.update()

        self.assertEqual(str(self.gui._launch_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._pause_btn["state"]), "normal")
        self.assertEqual(str(self.gui._resume_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._shutdown_btn["state"]), "normal")

    def test_button_states_paused(self):
        """When PAUSED: Resume=normal, Pause=disabled."""
        self.gui._service_detected = True
        self.gui.set_service_state(STATE_PAUSED)
        self.root.update()

        self.assertEqual(str(self.gui._launch_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._pause_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._resume_btn["state"]), "normal")
        self.assertEqual(str(self.gui._shutdown_btn["state"]), "normal")

    # --- State display / dark theme colours ---------------------------------

    def test_set_service_state_running(self):
        """set_service_state(RUNNING) → label text and green colour."""
        self.gui.set_service_state(STATE_RUNNING)
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "RUNNING")
        self.assertEqual(str(self.gui._state_label["foreground"]), FG_GREEN)

    def test_set_service_state_paused(self):
        """set_service_state(PAUSED) → label text and orange colour."""
        self.gui.set_service_state(STATE_PAUSED)
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "PAUSED")
        self.assertEqual(str(self.gui._state_label["foreground"]), FG_ORANGE)

    def test_set_service_state_unknown(self):
        """Unknown state → red colour and UNKNOWN(N) text."""
        self.gui.set_service_state(999)
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "UNKNOWN(999)")
        self.assertEqual(str(self.gui._state_label["foreground"]), FG_RED)

    # --- Tags ---------------------------------------------------------------

    def test_tag_adds_to_history(self):
        """Tags appear in the treeview."""
        self.gui.add_tag_to_history("mk_1", "12:05:00", "Test marker")
        self.root.update()

        items = self.gui._tag_tree.get_children()
        self.assertEqual(len(items), 1)
        values = self.gui._tag_tree.item(items[0], "values")
        self.assertEqual(values[0], "mk_1")
        self.assertEqual(values[2], "Test marker")

    # --- Log ----------------------------------------------------------------

    def test_log_panel_append(self):
        """Log messages are appended with timestamps."""
        self.gui.append_log("Alpha message")
        self.gui.append_log("Beta message")
        self.root.update()
        content = self.gui._log_text.get("1.0", "end").strip()
        self.assertIn("Alpha message", content)
        self.assertIn("Beta message", content)

    # --- Apply update methods -----------------------------------------------

    def test_apply_config_update(self):
        """_apply_config_update sets service name, db_directory, topics."""
        self.gui._apply_config_update({
            "service_name": "Recorder",
            "db_directory": "/tmp/recording",
            "topics": ["Square"],
        })
        self.root.update()
        self.assertEqual(self.gui._name_label["text"], "Recorder")
        self.assertEqual(self.gui._dbdir_label["text"], "/tmp/recording")
        self.assertEqual(self.gui._topics_label["text"], "1 topic")

    def test_apply_config_update_accumulates_topics(self):
        """Successive config updates accumulate topics."""
        self.gui._apply_config_update({"topics": ["Square"]})
        self.gui._apply_config_update({"topics": ["Triangle"]})
        self.root.update()
        self.assertEqual(len(self.gui._known_topics), 2)
        self.assertEqual(self.gui._topics_label["text"], "2 topics")

    def test_apply_event_update(self):
        """_apply_event_update sets state and logs events."""
        self.gui._apply_event_update({
            "state_int": STATE_RUNNING,
            "rollover_count": 3,
            "events": ["Service state: RUNNING"],
        })
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "RUNNING")
        self.assertEqual(self.gui._rollover_label["text"], "3")
        self.assertIn("Service state: RUNNING",
                      self.gui._log_text.get("1.0", "end"))

    def test_apply_periodic_update(self):
        """_apply_periodic_update sets uptime, CPU, memory, DB info."""
        self.gui._apply_periodic_update({
            "uptime": 3661,
            "cpu": 5.5,
            "memory_kb": 2048.0,
            "db_file": "/tmp/rec/data.db",
            "db_file_size": 1048576,
        })
        self.root.update()
        self.assertEqual(self.gui._uptime_label["text"], "1h 1m 1s")
        self.assertEqual(self.gui._cpu_label["text"], "5.5%")
        self.assertEqual(self.gui._memory_label["text"], "2048 KB")
        self.assertEqual(self.gui._dbfile_label["text"], "data.db")
        self.assertIn("MB", self.gui._dbsize_label["text"])

    # --- Queue drain --------------------------------------------------------

    def test_poll_monitor_queue_drains_all_kinds(self):
        """_poll_monitor_queue processes config, event, and periodic."""
        self.gui._monitor_queue.put({
            "kind": "config", "service_detected": True,
            "service_name": "MySvc", "db_directory": "",
            "topics": ["Square"],
        })
        self.gui._monitor_queue.put({
            "kind": "event", "service_detected": True,
            "state_int": STATE_RUNNING, "rollover_count": 0,
            "events": ["Service state: RUNNING"],
        })
        self.gui._monitor_queue.put({
            "kind": "periodic", "service_detected": True,
            "uptime": 10, "cpu": 1.0, "memory_kb": 512.0,
            "db_file": "", "db_file_size": -1,
        })

        self.gui._poll_monitor_queue()
        self.root.update()

        self.assertTrue(self.gui._service_detected)
        self.assertEqual(self.gui._name_label["text"], "MySvc")
        self.assertEqual(self.gui._state_label["text"], "RUNNING")
        self.assertEqual(self.gui._uptime_label["text"], "10s")

    def test_poll_monitor_queue_handles_error(self):
        """Error updates are logged."""
        self.gui._monitor_queue.put({
            "kind": "error", "error": "parse failed",
        })
        self.gui._poll_monitor_queue()
        self.root.update()
        self.assertIn("parse failed",
                      self.gui._log_text.get("1.0", "end"))

    # --- Lifecycle ----------------------------------------------------------

    def test_close_cancels_callbacks(self):
        """close() clears scheduled tkinter callbacks."""
        self.assertIsNotNone(self.gui._result_after_id)
        self.assertIsNotNone(self.gui._monitor_after_id)

        self.gui.close()

        self.assertTrue(self.gui._closed)
        self.assertIsNone(self.gui._result_after_id)
        self.assertIsNone(self.gui._monitor_after_id)

    def test_close_is_idempotent(self):
        """Calling close() twice does not raise."""
        self.gui.close()
        self.gui.close()

    # --- Result queue -------------------------------------------------------

    def test_poll_results_cmd_ok(self):
        """Successful command results are logged."""
        self.gui._result_queue.put(
            ("cmd_ok", "Pause", {"retcode": 0, "string_body": ""}))
        self.gui._poll_results()
        self.root.update()
        self.assertIn("Pause: OK", self.gui._log_text.get("1.0", "end"))
        self.assertEqual(self.gui._service_state, STATE_PAUSED)

    def test_poll_results_resume_updates_local_state(self):
        """Successful Resume command updates GUI state optimistically."""
        self.gui._service_state = STATE_PAUSED
        self.gui._result_queue.put(
            ("cmd_ok", "Resume", {"retcode": 0, "string_body": ""}))
        self.gui._poll_results()
        self.root.update()
        self.assertIn("Resume: OK", self.gui._log_text.get("1.0", "end"))
        self.assertEqual(self.gui._service_state, STATE_RUNNING)

    def test_poll_results_cmd_err(self):
        """Failed command results are logged."""
        self.gui._result_queue.put(("cmd_err", "Resume", "timeout"))
        self.gui._poll_results()
        self.root.update()
        self.assertIn("Resume ERROR: timeout",
                      self.gui._log_text.get("1.0", "end"))

    def test_admin_commands_are_queued(self):
        """Only one queued admin command is submitted at a time."""
        submitted = []
        self.gui._executor.shutdown(wait=False)
        self.gui._executor = MagicMock()
        self.gui._executor.submit.side_effect = lambda worker: submitted.append(worker)

        first = MagicMock(return_value={"retcode": 0, "string_body": ""})
        second = MagicMock(return_value={"retcode": 0, "string_body": ""})

        self.gui._run_command_async(first, "First")
        self.gui._run_command_async(second, "Second")

        self.assertEqual(len(submitted), 1)
        self.assertTrue(self.gui._command_in_progress)
        second.assert_not_called()

        submitted[0]()
        self.gui._poll_results()

        self.assertEqual(len(submitted), 2)
        first.assert_called_once_with()
        second.assert_not_called()

        submitted[1]()
        self.gui._poll_results()

        second.assert_called_once_with()
        self.assertFalse(self.gui._command_in_progress)


# ===================================================================
# Layer 3: Integration Tests (require rti.connextdds)
# ===================================================================

class TestIntegration(unittest.TestCase):
    """
    Integration tests that create real DDS objects.
    Skipped if rti.connextdds is unavailable.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import rti.connextdds  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("rti.connextdds not available")
        try:
            cls.root = __import__("tkinter").Tk()
            cls.root.withdraw()
        except Exception:
            raise unittest.SkipTest("tkinter display not available")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_monitoring_starts_on_init(self):
        """GUI creates a RecordingServiceMonitor on init."""
        from recording_service_gui import RecordingServiceGUI
        gui = RecordingServiceGUI(self.root, _skip_dds=False)
        try:
            self.assertIsNotNone(gui._monitoring)
            self.assertEqual(gui._monitoring_domain_id,
                             DEFAULT_ADMIN_DOMAIN_ID)
        finally:
            gui.close()

    def test_monitoring_restarts_on_domain_change(self):
        """Changing admin domain restarts monitoring."""
        from recording_service_gui import RecordingServiceGUI
        gui = RecordingServiceGUI(self.root, _skip_dds=False)
        try:
            first_monitoring = gui._monitoring
            gui._admin_domain_id_var.set(DEFAULT_ADMIN_DOMAIN_ID + 50)
            self.root.update()
            self.assertIsNot(gui._monitoring, first_monitoring)
            self.assertEqual(gui._monitoring_domain_id,
                             DEFAULT_ADMIN_DOMAIN_ID + 50)
        finally:
            gui.close()


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
