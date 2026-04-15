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
Tests for Recording Service GUI.

Three test layers:
  1. Pure logic tests — no tkinter, no DDS
  2. Widget tests — tkinter (headless), no DDS
  3. Integration smoke tests — tkinter + DDS (optional)

Run:
    python3 -m pytest test_gui.py -v              # all tests
    python3 -m pytest test_gui.py -v -k "not integration"  # skip DDS tests
    python3 test_gui.py                            # unittest runner
"""

import os
import sys
import time
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

# Ensure the script directory is on the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from recording_service_gui import (
    detect_nddshome,
    parse_config_names,
    build_launch_command,
    detect_terminal_emulator,
    format_file_size,
    format_uptime,
    STATE_INVALID,
    STATE_ENABLED,
    STATE_RUNNING,
    STATE_PAUSED,
    STATE_STOPPED,
    DEFAULT_DOMAIN_ID,
    DEFAULT_ADMIN_DOMAIN_ID,
    DEFAULT_VERBOSITY,
    NO_SERVICE_TIMEOUT_S,
)


# ===================================================================
# Layer 1: Pure Logic Tests (no tkinter, no DDS)
# ===================================================================

class TestParseConfigNames(unittest.TestCase):
    """Test parse_config_names helper."""

    def test_parse_real_config(self):
        """Parse the actual recording_service_config.xml."""
        cfg = os.path.join(SCRIPT_DIR, "..", "recording_service_config.xml")
        names = parse_config_names(cfg)
        self.assertIn("deploy", names)
        self.assertIn("debug", names)

    def test_parse_external_types_config(self):
        """Parse recording_service_config_external_types.xml."""
        cfg = os.path.join(
            SCRIPT_DIR, "..", "recording_service_config_external_types.xml")
        if os.path.isfile(cfg):
            names = parse_config_names(cfg)
            self.assertIn("xcdr", names)

    def test_parse_missing_file(self):
        """Missing file returns empty list."""
        names = parse_config_names("/nonexistent/file.xml")
        self.assertEqual(names, [])

    def test_parse_invalid_xml(self):
        """Invalid XML returns empty list."""
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False) as f:
            f.write("<<<not valid xml>>>")
            f.flush()
            names = parse_config_names(f.name)
        os.unlink(f.name)
        self.assertEqual(names, [])

    def test_parse_disappearing_file(self):
        """File open races are handled and return empty list."""
        with patch("os.path.isfile", return_value=True), \
                patch("xml.etree.ElementTree.parse",
                      side_effect=FileNotFoundError):
            names = parse_config_names("/tmp/disappearing.xml")
        self.assertEqual(names, [])

    def test_parse_xml_no_recording_service(self):
        """Valid XML without recording_service elements returns empty list."""
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False) as f:
            f.write('<?xml version="1.0"?><dds></dds>')
            f.flush()
            names = parse_config_names(f.name)
        os.unlink(f.name)
        self.assertEqual(names, [])

    def test_parse_xml_multiple_configs(self):
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


class TestBuildLaunchCommand(unittest.TestCase):
    """Test build_launch_command helper."""

    def test_basic_command(self):
        cmd = build_launch_command(
            "/opt/rti", "config.xml", "deploy", 1, 0, "ERROR:ERROR")
        self.assertEqual(cmd[0], "/opt/rti/bin/rtirecordingservice")
        self.assertIn("-cfgFile", cmd)
        self.assertEqual(cmd[cmd.index("-cfgFile") + 1], "config.xml")
        self.assertIn("-cfgName", cmd)
        self.assertEqual(cmd[cmd.index("-cfgName") + 1], "deploy")
        self.assertIn("-DDOMAIN_ID=1", cmd)
        self.assertIn("-DADMIN_DOMAIN_ID=0", cmd)
        self.assertIn("-verbosity", cmd)
        self.assertEqual(cmd[cmd.index("-verbosity") + 1], "ERROR:ERROR")

    def test_custom_domain_ids(self):
        cmd = build_launch_command(
            "/opt/rti", "f.xml", "test", 42, 7, "SILENT")
        self.assertIn("-DDOMAIN_ID=42", cmd)
        self.assertIn("-DADMIN_DOMAIN_ID=7", cmd)

    def test_command_is_list(self):
        cmd = build_launch_command(
            "/opt/rti", "f.xml", "test", 0, 0, "SILENT")
        self.assertIsInstance(cmd, list)
        self.assertTrue(all(isinstance(c, str) for c in cmd))


class TestDetectTerminalEmulator(unittest.TestCase):
    """Test detect_terminal_emulator helper."""

    @patch("shutil.which")
    def test_gnome_terminal_first(self, mock_which):
        """gnome-terminal should be preferred."""
        mock_which.side_effect = lambda x: "/usr/bin/" + x
        result = detect_terminal_emulator()
        self.assertEqual(result, ["gnome-terminal", "--"])

    @patch("shutil.which")
    def test_fallback_to_xterm(self, mock_which):
        """Falls back to xterm when gnome/xfce not available."""
        def side_effect(x):
            if x == "xterm":
                return "/usr/bin/xterm"
            return None
        mock_which.side_effect = side_effect
        result = detect_terminal_emulator()
        self.assertEqual(result, ["xterm", "-e"])

    @patch("shutil.which")
    def test_no_terminal(self, mock_which):
        """Returns empty list when no terminal found."""
        mock_which.return_value = None
        result = detect_terminal_emulator()
        self.assertEqual(result, [])


class TestFormatFileSize(unittest.TestCase):
    """Test format_file_size helper."""

    def test_bytes(self):
        self.assertEqual(format_file_size(500), "500 B")

    def test_kilobytes(self):
        result = format_file_size(2048)
        self.assertIn("KB", result)

    def test_megabytes(self):
        result = format_file_size(5 * 1024 * 1024)
        self.assertIn("MB", result)

    def test_gigabytes(self):
        result = format_file_size(3 * 1024 * 1024 * 1024)
        self.assertIn("GB", result)

    def test_zero(self):
        self.assertEqual(format_file_size(0), "0 B")


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
        result = detect_nddshome()
        self.assertIsInstance(result, str)

    @patch.dict(os.environ, {"NDDSHOME": "/test/rti_path"})
    @patch("os.path.isdir", return_value=True)
    def test_uses_env_var(self, _):
        result = detect_nddshome()
        self.assertEqual(result, "/test/rti_path")


# ===================================================================
# Layer 2: Widget Tests (tkinter, no DDS)
# ===================================================================

class TestWidgets(unittest.TestCase):
    """
    Test GUI widget interactions.

    Creates a tk.Tk() root but never calls mainloop().
    Uses root.update() for synchronous event processing.
    """

    @classmethod
    def setUpClass(cls):
        """Create a single Tk root for all widget tests."""
        try:
            cls.root = __import__("tkinter").Tk()
            cls.root.withdraw()  # Hide the window
        except Exception:
            raise unittest.SkipTest("tkinter display not available")

    @classmethod
    def tearDownClass(cls):
        """Destroy the Tk root."""
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        """Create a fresh GUI instance for each test."""
        from recording_service_gui import RecordingServiceGUI
        self.monitoring_patcher = patch(
            "recording_service_gui.MonitoringSubscriber")
        self.mock_monitoring_cls = self.monitoring_patcher.start()
        self.mock_monitoring = MagicMock()
        self.mock_monitoring_cls.return_value = self.mock_monitoring

        self.gui = RecordingServiceGUI(self.root)
        self.root.update()

    def tearDown(self):
        self.gui.close()
        self.root.update_idletasks()
        self.monitoring_patcher.stop()

    def test_config_file_populates_dropdown(self):
        """Selecting a config XML file populates the Config Name combobox."""
        cfg = os.path.join(SCRIPT_DIR, "..", "recording_service_config.xml")
        self.gui._config_file_var.set(cfg)
        self.root.update()
        values = list(self.gui._config_name_combo["values"])
        self.assertIn("deploy", values)
        self.assertIn("debug", values)

    def test_domain_id_spinbox_range(self):
        """Domain ID spinbox exists and has numeric value."""
        val = self.gui._domain_id_var.get()
        self.assertIsInstance(val, int)
        self.assertEqual(val, DEFAULT_DOMAIN_ID)

    def test_launch_button_builds_command(self):
        """Launch button produces correct command."""
        cmd = self.gui.get_launch_command()
        self.assertIsInstance(cmd, list)
        self.assertTrue(cmd[0].endswith("rtirecordingservice"))

    def test_button_states_no_service(self):
        """Before service detected: Launch=enabled, others=disabled."""
        self.gui._service_detected = False
        self.gui._service_state = STATE_INVALID
        self.gui._update_button_states()
        self.root.update()

        self.assertEqual(str(self.gui._launch_btn["state"]), "normal")
        self.assertEqual(str(self.gui._pause_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._resume_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._shutdown_btn["state"]), "disabled")

    def test_button_states_running(self):
        """When RUNNING: Pause=enabled, Resume=disabled."""
        self.gui._service_detected = True
        self.gui.set_service_state(STATE_RUNNING)
        self.root.update()

        self.assertEqual(str(self.gui._launch_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._pause_btn["state"]), "normal")
        self.assertEqual(str(self.gui._resume_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._shutdown_btn["state"]), "normal")

    def test_button_states_paused(self):
        """When PAUSED: Resume=enabled, Pause=disabled."""
        self.gui._service_detected = True
        self.gui.set_service_state(STATE_PAUSED)
        self.root.update()

        self.assertEqual(str(self.gui._launch_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._pause_btn["state"]), "disabled")
        self.assertEqual(str(self.gui._resume_btn["state"]), "normal")
        self.assertEqual(str(self.gui._shutdown_btn["state"]), "normal")

    def test_tag_adds_to_history(self):
        """After adding a tag, it appears in the treeview."""
        self.gui.add_tag_to_history("test_tag", "12:00:00", "A test tag")
        self.root.update()

        items = self.gui._tag_tree.get_children()
        self.assertEqual(len(items), 1)
        values = self.gui._tag_tree.item(items[0], "values")
        self.assertEqual(values[0], "test_tag")
        self.assertEqual(values[2], "A test tag")

    def test_log_panel_append(self):
        """Log messages are appended with timestamps."""
        self.gui.append_log("Test message one")
        self.gui.append_log("Test message two")
        self.root.update()

        content = self.gui._log_text.get("1.0", "end").strip()
        self.assertIn("Test message one", content)
        self.assertIn("Test message two", content)

    def test_set_service_state_updates_label(self):
        """set_service_state updates the state label text."""
        self.gui.set_service_state(STATE_RUNNING)
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "RUNNING")

        self.gui.set_service_state(STATE_PAUSED)
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "PAUSED")

    def test_monitoring_starts_automatically(self):
        """GUI starts DDS monitoring immediately on the admin domain."""
        self.mock_monitoring_cls.assert_called_once_with(
            admin_domain_id=DEFAULT_ADMIN_DOMAIN_ID,
            xml_types_dir=self.gui._xml_types_dir,
            qos_file=self.gui._qos_file,
            on_update=self.gui._on_monitor_update,
        )

    def test_monitoring_restarts_when_admin_domain_changes(self):
        """Changing admin domain restarts monitoring on the new domain."""
        first_monitor = self.mock_monitoring
        second_monitor = MagicMock()
        self.mock_monitoring_cls.side_effect = [first_monitor, second_monitor]

        self.gui.close()
        self.root.update_idletasks()

        from recording_service_gui import RecordingServiceGUI
        self.gui = RecordingServiceGUI(self.root)
        self.root.update()

        self.gui._admin_domain_id_var.set(DEFAULT_ADMIN_DOMAIN_ID + 1)
        self.root.update()

        first_monitor.close.assert_called_once()
        self.assertIs(self.gui._monitoring, second_monitor)
        self.assertEqual(self.gui._monitoring_domain_id,
                         DEFAULT_ADMIN_DOMAIN_ID + 1)

    def test_monitor_queue_updates_ui(self):
        """Callback-fed monitoring updates are applied on the tkinter thread."""
        self.gui._on_monitor_update({
            "kind": "config",
            "service_detected": True,
            "service_name": "Recorder",
            "db_directory": "/tmp/recording",
            "topics": ["Square"],
        })
        self.gui._on_monitor_update({
            "kind": "event",
            "service_detected": True,
            "state_int": STATE_RUNNING,
            "rollover_count": 2,
            "events": ["Service state changed to: RUNNING"],
        })
        self.gui._on_monitor_update({
            "kind": "periodic",
            "service_detected": True,
            "uptime": 65,
            "cpu": 3.5,
            "memory_kb": 2048,
            "db_file": "/tmp/recording/test.db",
            "db_file_size": 1024,
        })

        self.gui._poll_monitor_events()
        self.root.update()

        self.assertEqual(self.gui._name_label["text"], "Recorder")
        self.assertEqual(self.gui._dbdir_label["text"], "/tmp/recording")
        self.assertEqual(self.gui._topics_label["text"], "1 topics")
        self.assertEqual(self.gui._state_label["text"], "RUNNING")
        self.assertEqual(self.gui._rollover_label["text"], "2")
        self.assertEqual(self.gui._uptime_label["text"], "1m 5s")
        self.assertEqual(self.gui._cpu_label["text"], "3.5%")
        self.assertEqual(self.gui._memory_label["text"], "2048 KB")
        self.assertEqual(self.gui._dbfile_label["text"], "test.db")
        self.assertIn("Service state changed to: RUNNING",
                      self.gui._log_text.get("1.0", "end"))

    @patch("subprocess.Popen")
    @patch("recording_service_gui.detect_terminal_emulator")
    @patch("os.path.isfile", return_value=True)
    def test_launch_quotes_paths_with_spaces(
            self, _mock_isfile, mock_terminal, mock_popen):
        """Launch command passed through bash is shell-safe for spaced paths."""
        mock_terminal.return_value = ["xterm", "-e"]

        self.gui._nddshome_var.set("/tmp/rti install")
        self.gui._config_file_var.set("/tmp/config dir/config file.xml")
        self.gui._config_name_var.set("deploy")

        self.gui._on_launch()

        args, kwargs = mock_popen.call_args
        full_cmd = args[0]
        bash_cmd = full_cmd[-1]
        expected = shlex.join(self.gui.get_launch_command())

        self.assertIn(expected, bash_cmd)
        self.assertEqual(kwargs["start_new_session"], True)

    def test_close_cancels_scheduled_callbacks(self):
        """close() clears scheduled tkinter callbacks to avoid teardown errors."""
        self.assertIsNotNone(self.gui._result_after_id)
        self.assertIsNotNone(self.gui._monitor_queue_after_id)

        self.gui.close()

        self.assertTrue(self.gui._closed)
        self.assertIsNone(self.gui._result_after_id)
        self.assertIsNone(self.gui._monitor_queue_after_id)

    def test_repoll_cancels_previous_monitor_callback(self):
        """Repeated queue polling cancels the previous scheduled callback."""
        with patch.object(self.gui.root, "after_cancel",
                          wraps=self.gui.root.after_cancel) as mock_cancel:
            first_id = self.gui._monitor_queue_after_id
            self.gui._poll_monitor_events()

        self.assertIsNotNone(first_id)
        mock_cancel.assert_called_with(first_id)


class TestServiceNotDetected(unittest.TestCase):
    """
    Tests for the automatic monitoring timeout path in _poll_monitor_events.
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

    def _detected_status(self, state_int=None):
        """Return an event-driven update with a detected service."""
        if state_int is None:
            state_int = STATE_RUNNING
        return {
            "kind": "event",
            "service_detected": True,
            "state_int": state_int,
            "rollover_count": 0,
            "events": [],
        }

    def setUp(self):
        from recording_service_gui import RecordingServiceGUI

        self.monitoring_patcher = patch(
            "recording_service_gui.MonitoringSubscriber")
        self.mock_monitoring_cls = self.monitoring_patcher.start()
        self.mock_monitoring_cls.return_value = MagicMock()

        self.gui = RecordingServiceGUI(self.root)
        self.root.update()

    def tearDown(self):
        self.gui.close()
        self.root.update_idletasks()
        self.monitoring_patcher.stop()

    def test_no_warning_before_timeout(self):
        """Before timeout elapses, no 'Service Not Detected' warning."""
        self.gui._launch_time = time.time()  # just launched

        self.gui._poll_monitor_events()
        self.root.update()

        self.assertNotEqual(self.gui._state_label["text"], "Service Not Detected")

    def test_warning_after_timeout_with_launch(self):
        """After timeout with GUI launch, 'Service Not Detected' shown."""
        self.gui._launch_time = time.time() - NO_SERVICE_TIMEOUT_S - 1

        self.gui._poll_monitor_events()
        self.root.update()

        self.assertEqual(self.gui._state_label["text"], "Service Not Detected")
        self.assertEqual(str(self.gui._state_label["foreground"]), "red")

    def test_no_warning_without_launch(self):
        """Passive monitoring alone does not show the timeout warning."""
        self.gui._launch_time = None

        self.gui._poll_monitor_events()
        self.root.update()

        self.assertNotEqual(self.gui._state_label["text"], "Service Not Detected")

    def test_no_warning_when_service_detected(self):
        """If service is detected, no timeout warning even after timeout."""
        self.gui._launch_time = time.time() - NO_SERVICE_TIMEOUT_S - 100
        self.gui._on_monitor_update(self._detected_status())

        self.gui._poll_monitor_events()
        self.root.update()

        self.assertNotEqual(self.gui._state_label["text"], "Service Not Detected")
        self.assertEqual(self.gui._state_label["text"], "RUNNING")
        self.assertTrue(self.gui._service_detected)

    def test_warning_clears_once_service_appears(self):
        """Service Not Detected clears when a service later appears."""
        self.gui._launch_time = time.time() - NO_SERVICE_TIMEOUT_S - 1
        self.gui._poll_monitor_events()
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "Service Not Detected")

        self.gui._on_monitor_update(self._detected_status())
        self.gui._poll_monitor_events()
        self.root.update()
        self.assertEqual(self.gui._state_label["text"], "RUNNING")
        self.assertTrue(self.gui._service_detected)


# ===================================================================
# Layer 3: Integration Smoke Tests (tkinter + DDS)
# ===================================================================

class TestIntegration(unittest.TestCase):
    """
    Integration tests that require DDS.
    Skipped if rti.connextdds is not importable or XML types are missing.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import rti.connextdds  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("rti.connextdds not available")

        xml_types_dir = os.path.join(SCRIPT_DIR, "xml_types")
        if not os.path.isfile(
                os.path.join(xml_types_dir, "ServiceMonitoring.xml")):
            raise unittest.SkipTest(
                "Monitoring XML types not generated (run setup.sh)")

        cls.nddshome = detect_nddshome()
        cls.recorder_exe = os.path.join(
            cls.nddshome, "bin", "rtirecordingservice")
        if not os.path.isfile(cls.recorder_exe):
            raise unittest.SkipTest("rtirecordingservice executable not found")

    @staticmethod
    def _find_free_domain():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return 200 + (sock.getsockname()[1] % 200)

    def _create_temp_recorder_config(self, app_domain_id, admin_domain_id):
        workspace_dir = tempfile.mkdtemp(prefix="recording_service_test_")
        config_text = f'''<?xml version="1.0"?>
<dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation="https://community.rti.com/schema/7.3.0/rti_recording_service.xsd">
    <recording_service name="auto_monitor_test">
        <administration>
            <domain_id>{admin_domain_id}</domain_id>
        </administration>
        <monitoring>
            <status_publication_period>
                <sec>1</sec>
                <nanosec>0</nanosec>
            </status_publication_period>
            <statistics_sampling_period>
                <sec>0</sec>
                <nanosec>500000000</nanosec>
            </statistics_sampling_period>
        </monitoring>
        <storage>
            <sqlite>
                <storage_format>JSON_SQLITE</storage_format>
                <fileset>
                    <workspace_dir>{workspace_dir}</workspace_dir>
                    <execution_dir_expression>run</execution_dir_expression>
                    <filename_expression>test_data.db</filename_expression>
                </fileset>
            </sqlite>
        </storage>
        <domain_participant name="Participant0">
            <domain_id>{app_domain_id}</domain_id>
        </domain_participant>
        <session name="DefaultSession">
            <topic_group name="RecordAll" participant_ref="Participant0">
                <allow_topic_name_filter>*</allow_topic_name_filter>
                <deny_topic_name_filter>rti/*</deny_topic_name_filter>
            </topic_group>
        </session>
    </recording_service>
</dds>
'''
        config_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False)
        with config_file:
            config_file.write(config_text)
        return config_file.name, workspace_dir

    def _terminate_process(self, process):
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def test_integration_monitoring_readers_created(self):
        """DomainParticipant and three DataReaders are created."""
        from recording_service_gui import MonitoringSubscriber
        qos_file = os.path.join(
            SCRIPT_DIR, "MonitoringSubscriber_QOS_PROFILES.xml")
        xml_types_dir = os.path.join(SCRIPT_DIR, "xml_types")

        sub = MonitoringSubscriber(
            admin_domain_id=99,  # Use high domain to avoid conflicts
            xml_types_dir=xml_types_dir,
            qos_file=qos_file,
        )
        try:
            self.assertIsNotNone(sub._config_reader)
            self.assertIsNotNone(sub._event_reader)
            self.assertIsNotNone(sub._periodic_reader)
        finally:
            sub.close()

    def test_integration_controller_initialization(self):
        """RecordingServiceController initializes with XML types loaded."""
        from recording_service_control import RecordingServiceController
        xml_types_dir = os.path.join(SCRIPT_DIR, "xml_types")
        qos_file = os.path.join(SCRIPT_DIR, "ServiceAdmin_QOS_PROFILES.xml")

        controller = RecordingServiceController(
            domain_id=98,  # Use high domain to avoid conflicts
            service_name="test_instance",
            xml_types_dir=xml_types_dir,
            qos_file=qos_file,
        )
        try:
            self.assertIsNotNone(controller._requester)
        finally:
            controller.close()

    def test_integration_monitoring_receives_updates_after_launch(self):
        """Launching Recording Service produces callback-driven monitoring data."""
        from recording_service_gui import MonitoringSubscriber

        qos_file = os.path.join(
            SCRIPT_DIR, "MonitoringSubscriber_QOS_PROFILES.xml")
        xml_types_dir = os.path.join(SCRIPT_DIR, "xml_types")
        app_domain_id = self._find_free_domain()
        admin_domain_id = app_domain_id + 1
        config_file, workspace_dir = self._create_temp_recorder_config(
            app_domain_id, admin_domain_id)
        updates = []
        update_event = threading.Event()

        def on_update(update):
            updates.append(update)
            if update.get("service_detected"):
                update_event.set()

        sub = MonitoringSubscriber(
            admin_domain_id=admin_domain_id,
            xml_types_dir=xml_types_dir,
            qos_file=qos_file,
            on_update=on_update,
        )
        process = subprocess.Popen(
            [
                self.recorder_exe,
                "-cfgFile", config_file,
                "-cfgName", "auto_monitor_test",
                f"-DDOMAIN_ID={app_domain_id}",
                f"-DADMIN_DOMAIN_ID={admin_domain_id}",
                "-verbosity", "WARNING",
            ],
            cwd=SCRIPT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        try:
            self.assertTrue(
                update_event.wait(timeout=20),
                f"No monitoring updates received; collected updates: {updates}")
            time.sleep(2)
            detected_kinds = {update.get("kind") for update in updates}
            self.assertIn("config", detected_kinds)
            self.assertTrue(
                detected_kinds & {"event", "periodic"},
                f"Expected event or periodic updates, got: {updates}")
            self.assertTrue(any(update.get("service_detected")
                                for update in updates))
        finally:
            sub.close()
            self._terminate_process(process)
            os.unlink(config_file)
            shutil.rmtree(workspace_dir, ignore_errors=True)


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
