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
End-to-end test: GUI → launch Recording Service → verify monitoring updates.

Exercises the full monitoring pipeline:
  1. Create the Recording Service GUI (with DDS enabled)
  2. Launch Recording Service directly (not via terminal emulator)
  3. Wait for DDS monitoring topics to arrive
  4. Verify that the GUI status labels are updated by monitoring data
  5. Shut down Recording Service and clean up

This verifies the integration between:
  - RecordingServiceMonitor (DDS listeners → queue)
  - RecordingServiceGUI._poll_monitor_queue (queue → tkinter labels)

Prerequisites:
  - $NDDSHOME set (rtirecordingservice)
  - Generated XML type files (setup.sh)
    - Virtual environment with rti.connext == 7.6.0
  - tkinter display (headless OK with Xvfb)

Run standalone:
    cd services/recording_service_gui
    python3 test/test_e2e_gui_monitoring.py -v

Or as part of the suite (auto-skipped if prerequisites missing):
    python3 test/run_all_tests.py -v
"""

import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)  # recording_service_gui/
REPO_ROOT = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from recording_service_environment import detect_nddshome, ensure_rti_license

NDDSHOME = detect_nddshome()
ensure_rti_license(NDDSHOME)

RECORDER_BIN = os.path.join(NDDSHOME, "bin", "rtirecordingservice")
SERVICES_DIR = os.path.dirname(PARENT_DIR)  # services/
RECORDER_CONFIG = os.path.join(SERVICES_DIR, "recording_service_config.xml")
QOS_FILE = os.path.normpath(
    os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml"))
XML_TYPES_DIR = os.path.join(PARENT_DIR, "xml_types")

# Use domain 0 for test isolation (override config variables via -D flags)
TEST_DOMAIN = 0
TEST_ADMIN_DOMAIN = 0
TEST_CONFIG_NAME = "deploy"

# Recording output dir (deploy config writes to log_dir/ relative to cwd)
RECORDING_DIR = os.path.join(SERVICES_DIR, "log_dir")

# Timing
RECORDER_STARTUP_SEC = 5
MONITORING_TIMEOUT_SEC = 20
POLL_STEP_MS = 100  # ms between tkinter event loop pumps
SHUTDOWN_WAIT_SEC = 10


def _skip_reason():
    """Return a skip reason string, or None if all prerequisites are met."""
    if not os.path.isfile(RECORDER_BIN):
        return f"rtirecordingservice not found: {RECORDER_BIN}"
    if not os.path.isfile(RECORDER_CONFIG):
        return f"recording_service_config.xml not found: {RECORDER_CONFIG}"
    if not os.path.isfile(QOS_FILE):
        return f"DDS_QOS_PROFILES.xml not found: {QOS_FILE}"
    if not os.path.isfile(os.path.join(XML_TYPES_DIR, "ServiceMonitoring.xml")):
        return f"xml_types/ not generated (run setup.sh): {XML_TYPES_DIR}"
    try:
        import rti.connextdds  # noqa: F401
    except ImportError:
        return "rti.connextdds not available"
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
    except Exception:
        return "tkinter display not available"
    return None


def _kill_process(proc, label="process"):
    """Send SIGTERM, wait, SIGKILL if needed."""
    if proc and proc.poll() is None:
        print(f"[GUI E2E] Sending SIGTERM to {label}...")
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=SHUTDOWN_WAIT_SEC)
        except subprocess.TimeoutExpired:
            print(f"[GUI E2E] Force-killing {label}...")
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)
        print(f"[GUI E2E] {label} stopped (rc={proc.returncode})")


def _pump_tk(root, duration_sec, step_ms=POLL_STEP_MS):
    """Pump the tkinter event loop for the given duration.

    This processes all pending events including after() callbacks,
    which is how the GUI drains the monitor queue.
    """
    deadline = time.time() + duration_sec
    while time.time() < deadline:
        try:
            root.update_idletasks()
            root.update()
        except Exception:
            break
        time.sleep(step_ms / 1000.0)


def _wait_for_gui_state(root, gui, expected_states, description,
                        timeout_sec=10):
    """Pump tkinter until the GUI-visible service state reaches a target."""
    from recording_service_gui import STATE_NAMES

    expected_states = set(expected_states)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        _pump_tk(root, 0.2)
        if gui._service_state in expected_states:
            state_name = STATE_NAMES.get(gui._service_state, "?")
            print(f"[GUI E2E] {description}: {state_name}")
            return

    state_name = STATE_NAMES.get(gui._service_state, "?")
    expected_names = ", ".join(
        STATE_NAMES.get(state, str(state)) for state in sorted(expected_states))
    log_tail = gui._log_text.get("1.0", "end").strip()[-800:]
    raise AssertionError(
        f"Timed out waiting for {description}; expected one of "
        f"{expected_names}, got {gui._service_state} ({state_name}). "
        f"Recent GUI log:\n{log_tail}")


@unittest.skipIf(_skip_reason(), _skip_reason() or "")
class TestE2EGUIMonitoring(unittest.TestCase):
    """
    End-to-end test verifying that a launched Recording Service's
    monitoring topics update the GUI status labels.
    """

    _recorder_proc = None
    _gui = None
    _root = None

    @classmethod
    def setUpClass(cls):
        """Start Recording Service and create the GUI."""
        # Clean previous recording output
        if os.path.isdir(RECORDING_DIR):
            shutil.rmtree(RECORDING_DIR)
            print(f"[GUI E2E] Cleaned: {RECORDING_DIR}")

        # Launch Recording Service exactly as the GUI does:
        # real config + centralized QoS via semicolons, -D domain overrides.
        from recording_service_gui import build_launch_command
        cmd = build_launch_command(
            nddshome=NDDSHOME,
            config_file=RECORDER_CONFIG,
            config_name=TEST_CONFIG_NAME,
            domain_id=TEST_DOMAIN,
            admin_domain_id=TEST_ADMIN_DOMAIN,
            verbosity="WARN",
            qos_file=QOS_FILE,
        )
        print(f"[GUI E2E] Launch command: {' '.join(cmd)}")

        env = os.environ.copy()
        env["NDDSHOME"] = NDDSHOME
        cls._recorder_proc = subprocess.Popen(
            cmd,
            cwd=SERVICES_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        print(f"[GUI E2E] Recording Service started (pid={cls._recorder_proc.pid})")

        # Wait for recorder to initialize
        print(f"[GUI E2E] Waiting {RECORDER_STARTUP_SEC}s for startup...")
        time.sleep(RECORDER_STARTUP_SEC)

        if cls._recorder_proc.poll() is not None:
            stdout = cls._recorder_proc.stdout.read().decode(errors="replace")
            raise unittest.SkipTest(
                f"Recording Service exited during startup "
                f"(rc={cls._recorder_proc.returncode}): "
                f"{stdout[-500:]}")

        # Create tkinter root and the GUI
        import tkinter as tk
        cls._root = tk.Tk()
        cls._root.withdraw()  # hide window — headless test

        from recording_service_gui import RecordingServiceGUI
        # Set admin domain to match the recorder's admin domain
        cls._gui = RecordingServiceGUI(cls._root, nddshome=NDDSHOME,
                                       _skip_dds=False)
        cls._gui._admin_domain_id_var.set(TEST_ADMIN_DOMAIN)

        # Force monitoring restart on the correct domain
        cls._gui._ensure_monitoring_started(force_restart=True)

        print(f"[GUI E2E] GUI created, monitoring on domain "
              f"{cls._gui._monitoring_domain_id}")

        # Pump tkinter to process initial callbacks
        _pump_tk(cls._root, 2)

    @classmethod
    def tearDownClass(cls):
        """Stop Recording Service and destroy GUI."""
        if cls._gui is not None:
            try:
                cls._gui.close()
            except Exception:
                pass

        if cls._root is not None:
            try:
                cls._root.destroy()
            except Exception:
                pass

        _kill_process(cls._recorder_proc, "Recording Service")

        # Clean recording output
        if os.path.isdir(RECORDING_DIR):
            shutil.rmtree(RECORDING_DIR)
            print(f"[GUI E2E] Cleaned: {RECORDING_DIR}")

    # ==================================================================
    # Tests (ordered for logical flow but each is independently valid)
    # ==================================================================

    def test_1_monitoring_is_active(self):
        """RecordingServiceMonitor is running on the admin domain."""
        gui = self.__class__._gui
        self.assertIsNotNone(gui._monitoring,
                             "Monitoring not started")
        self.assertEqual(gui._monitoring_domain_id, TEST_ADMIN_DOMAIN,
                         f"Monitoring on wrong domain: "
                         f"{gui._monitoring_domain_id}")

    def test_2_service_detected(self):
        """GUI detects the Recording Service via monitoring topics."""
        gui = self.__class__._gui
        root = self.__class__._root

        # Pump the event loop until service is detected or timeout
        deadline = time.time() + MONITORING_TIMEOUT_SEC
        while time.time() < deadline:
            _pump_tk(root, 1)
            if gui._service_detected:
                break

        self.assertTrue(
            gui._service_detected,
            "GUI did not detect the Recording Service within "
            f"{MONITORING_TIMEOUT_SEC}s. Monitor queue size: "
            f"{gui._monitor_queue.qsize()}")

        print(f"[GUI E2E] Service detected: {gui._service_detected}")

    def test_3_state_label_updated(self):
        """GUI state label shows an active service after monitoring updates."""
        gui = self.__class__._gui
        root = self.__class__._root

        # Pump to ensure event updates are processed
        _pump_tk(root, 3)

        state_text = gui._state_label.cget("text")
        print(f"[GUI E2E] State label: '{state_text}'")

        from recording_service_gui import ACTIVE_SERVICE_STATES, STATE_NAMES
        self.assertIn(
            gui._service_state, ACTIVE_SERVICE_STATES,
            f"Expected active service state, got {gui._service_state} "
            f"({STATE_NAMES.get(gui._service_state, '?')})")

        self.assertIn(state_text.upper(), {"STARTED", "RUNNING"},
                      f"State label doesn't show an active state: "
                      f"'{state_text}'")

    def test_4_service_name_label_updated(self):
        """GUI shows the service name from config monitoring."""
        gui = self.__class__._gui
        root = self.__class__._root

        _pump_tk(root, 2)

        name_text = gui._name_label.cget("text")
        print(f"[GUI E2E] Service name label: '{name_text}'")

        # The config name is "deploy" in recording_service_config.xml
        self.assertNotEqual(name_text, "\u2014",
                            "Service name label was never updated")
        self.assertIn(TEST_CONFIG_NAME, name_text,
                      f"Expected '{TEST_CONFIG_NAME}' in service name, "
                      f"got '{name_text}'")

    def test_5_periodic_stats_updated(self):
        """GUI shows uptime and other periodic stats."""
        gui = self.__class__._gui
        root = self.__class__._root

        # Periodic monitoring publishes every ~1s, allow time for delivery
        _pump_tk(root, 5)

        uptime_text = gui._uptime_label.cget("text")
        print(f"[GUI E2E] Uptime label: '{uptime_text}'")

        # Uptime should be a non-default value (not the "—" placeholder)
        self.assertNotEqual(uptime_text, "\u2014",
                            "Uptime label was never updated from default")

        # CPU label should also be set
        cpu_text = gui._cpu_label.cget("text")
        print(f"[GUI E2E] CPU label: '{cpu_text}'")
        self.assertNotEqual(cpu_text, "\u2014",
                            "CPU label was never updated from default")

        # Memory label should be set
        mem_text = gui._memory_label.cget("text")
        print(f"[GUI E2E] Memory label: '{mem_text}'")
        self.assertNotEqual(mem_text, "\u2014",
                            "Memory label was never updated from default")

    def test_6_button_states_correct(self):
        """Buttons reflect a running service (pause enabled, launch disabled)."""
        gui = self.__class__._gui
        root = self.__class__._root

        _pump_tk(root, 1)

        # When service is running:
        # - Launch should be disabled (service already detected)
        # - Pause should be enabled
        # - Resume should be disabled (not paused)
        # - Shutdown should be enabled
        self.assertEqual(
            str(gui._pause_btn.cget("state")), "normal",
            "Pause button should be enabled when service is RUNNING")
        self.assertEqual(
            str(gui._resume_btn.cget("state")), "disabled",
            "Resume button should be disabled when service is RUNNING")
        self.assertEqual(
            str(gui._shutdown_btn.cget("state")), "normal",
            "Shutdown button should be enabled when service is detected")
        self.assertEqual(
            str(gui._launch_btn.cget("state")), "disabled",
            "Launch button should be disabled when service is detected")

    def test_7_pause_resume_controls_update_state(self):
        """Pause and resume through GUI controls and observe GUI state."""
        gui = self.__class__._gui
        root = self.__class__._root

        from recording_service_gui import (
            ACTIVE_SERVICE_STATES,
            STATE_PAUSED,
        )

        _wait_for_gui_state(
            root, gui, ACTIVE_SERVICE_STATES, "initial active state")

        self.assertEqual(
            str(gui._pause_btn.cget("state")), "normal",
            "Pause button should be enabled before pause command")

        gui._pause_btn.invoke()
        _wait_for_gui_state(root, gui, {STATE_PAUSED}, "paused state")

        self.assertEqual(gui._state_label.cget("text"), "PAUSED")
        self.assertEqual(str(gui._pause_btn.cget("state")), "disabled")
        self.assertEqual(str(gui._resume_btn.cget("state")), "normal")

        gui._resume_btn.invoke()
        _wait_for_gui_state(
            root, gui, ACTIVE_SERVICE_STATES, "resumed active state")

        self.assertIn(gui._state_label.cget("text"), {"STARTED", "RUNNING"})
        self.assertEqual(str(gui._pause_btn.cget("state")), "normal")
        self.assertEqual(str(gui._resume_btn.cget("state")), "disabled")

    def test_8_log_panel_has_entries(self):
        """Log panel contains monitoring-related entries."""
        gui = self.__class__._gui
        root = self.__class__._root

        _pump_tk(root, 1)

        log_text = gui._log_text.get("1.0", "end").strip()
        print(f"[GUI E2E] Log panel ({len(log_text)} chars):")
        # Show last 500 chars
        if log_text:
            print(f"  ...{log_text[-500:]}")

        self.assertGreater(len(log_text), 0,
                           "Log panel is empty")
        # Should contain monitoring startup message
        self.assertIn("Monitoring active",
                      log_text,
                      "Log panel missing monitoring startup message")


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
