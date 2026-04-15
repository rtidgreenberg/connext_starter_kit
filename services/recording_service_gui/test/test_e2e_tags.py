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
End-to-end test: start Recording Service, publish data, set tags, verify.

Flow:
  1. Clean any previous test_recording/ database
  2. Start Recording Service (background process)
  3. Publish a few DDS samples so the recorder has data
  4. Send tag commands via RecordingServiceController
  5. Shut down Recording Service
  6. Verify tags in SQLite using rtirecordingservice_list_tags and sqlite3

See test/README.md for additional details and the equivalent manual procedure.

Prerequisites:
  - $NDDSHOME set (rtirecordingservice, rtirecordingservice_list_tags)
  - Generated XML type files (run setup.sh)
  - Virtual environment with rti.connext >= 7.3.1

Run standalone:
    cd services/recording_service_gui
    python3 test/test_e2e_tags.py -v

Or as part of the suite (skipped if prerequisites are missing):
    python3 test/run_all_tests.py -v
"""

import os
import sys
import time
import shutil
import signal
import sqlite3
import subprocess
import unittest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

NDDSHOME = os.environ.get("NDDSHOME", "")
if not NDDSHOME:
    # Auto-detect like run_gui.sh does
    import glob
    candidates = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if candidates:
        NDDSHOME = candidates[-1]

RECORDER_BIN = os.path.join(NDDSHOME, "bin", "rtirecordingservice")
LIST_TAGS_BIN = os.path.join(NDDSHOME, "bin", "rtirecordingservice_list_tags")
RECORDER_CONFIG = os.path.join(SCRIPT_DIR, "test_recorder_config.xml")
RECORDING_DIR = os.path.join(SCRIPT_DIR, "test_recording")
METADATA_DB = os.path.join(RECORDING_DIR, "metadata.db")
XML_TYPES_DIR = os.path.join(PARENT_DIR, "xml_types")
QOS_FILE = os.path.normpath(
    os.path.join(PARENT_DIR, "..", "..", "dds", "qos", "DDS_QOS_PROFILES.xml"))

# Recording Service needs some time to start and discover
RECORDER_STARTUP_SEC = 5
PUBLISHER_SAMPLES = 5
PUBLISHER_INTERVAL = 0.2
TAG_SETTLE_SEC = 2
SHUTDOWN_WAIT_SEC = 10

# Tags to create and verify
TEST_TAGS = [
    ("e2e_tag_alpha", "First automated E2E tag"),
    ("e2e_tag_beta", "Second automated E2E tag"),
]


def _skip_reason():
    """Return a skip reason string, or None if all prerequisites are met."""
    if not os.path.isfile(RECORDER_BIN):
        return f"rtirecordingservice not found: {RECORDER_BIN}"
    if not os.path.isfile(LIST_TAGS_BIN):
        return f"rtirecordingservice_list_tags not found: {LIST_TAGS_BIN}"
    if not os.path.isfile(RECORDER_CONFIG):
        return f"Test recorder config not found: {RECORDER_CONFIG}"
    if not os.path.isfile(os.path.join(XML_TYPES_DIR, "ServiceAdmin.xml")):
        return "XML type files not generated (run setup.sh)"
    if not os.path.isfile(QOS_FILE):
        return f"QoS file not found: {QOS_FILE}"
    try:
        import rti.connextdds  # noqa: F401
        import rti.request  # noqa: F401
    except ImportError:
        return "rti.connextdds or rti.request not available"
    return None


@unittest.skipIf(_skip_reason(), _skip_reason() or "")
class TestE2ETags(unittest.TestCase):
    """
    End-to-end test: Recording Service + tag commands + database verification.

    Follows the manual procedure from the upstream python_control README:
    https://github.com/rtidgreenberg/connext_starter_kit/tree/main/services/python_control#end-to-end-test
    """

    _recorder_proc = None

    @classmethod
    def setUpClass(cls):
        """Clean previous recording and start Recording Service."""
        # ── Clean previous recording database ───────────────────────────
        if os.path.isdir(RECORDING_DIR):
            shutil.rmtree(RECORDING_DIR)
            print(f"\n[E2E] Cleaned previous recording: {RECORDING_DIR}")

        # ── Start Recording Service in background ───────────────────────
        cmd = [
            RECORDER_BIN,
            "-cfgFile", RECORDER_CONFIG,
            "-cfgName", "remote_admin",
            "-verbosity", "WARN",
        ]
        print(f"[E2E] Starting Recording Service...")
        print(f"      {' '.join(cmd)}")

        cls._recorder_proc = subprocess.Popen(
            cmd,
            cwd=SCRIPT_DIR,  # so test_recording/ is created under test/
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )

        # Give the recorder time to start and enable remote administration
        print(f"[E2E] Waiting {RECORDER_STARTUP_SEC}s for startup...")
        time.sleep(RECORDER_STARTUP_SEC)

        if cls._recorder_proc.poll() is not None:
            # Recorder exited prematurely — read output for diagnostics
            out = cls._recorder_proc.stdout.read().decode(errors="replace")
            raise unittest.SkipTest(
                f"Recording Service exited immediately (rc="
                f"{cls._recorder_proc.returncode}):\n{out[:1000]}"
            )

        print("[E2E] Recording Service is running "
              f"(pid={cls._recorder_proc.pid})")

    @classmethod
    def tearDownClass(cls):
        """Stop Recording Service if still running."""
        if cls._recorder_proc and cls._recorder_proc.poll() is None:
            print("\n[E2E] Sending SIGTERM to Recording Service...")
            try:
                os.killpg(os.getpgid(cls._recorder_proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                cls._recorder_proc.wait(timeout=SHUTDOWN_WAIT_SEC)
            except subprocess.TimeoutExpired:
                print("[E2E] Force-killing Recording Service...")
                os.killpg(os.getpgid(cls._recorder_proc.pid), signal.SIGKILL)
                cls._recorder_proc.wait(timeout=5)
            print("[E2E] Recording Service stopped")

    # ------------------------------------------------------------------
    # Tests — run in order via alphabetical naming
    # ------------------------------------------------------------------

    def test_1_publish_data(self):
        """Publish DDS samples so Recording Service has data to record."""
        from test_publisher import publish_test_data

        publish_test_data(
            domain_id=0,
            num_samples=PUBLISHER_SAMPLES,
            interval=PUBLISHER_INTERVAL,
        )

        # Give the recorder a moment to flush
        time.sleep(1)

    def test_2_send_tags(self):
        """Send tag commands via RecordingServiceController."""
        from recording_service_control import RecordingServiceController

        ctrl = RecordingServiceController(
            domain_id=0,
            service_name="remote_admin",
            xml_types_dir=XML_TYPES_DIR,
            qos_file=QOS_FILE,
        )
        try:
            for tag_name, tag_desc in TEST_TAGS:
                result = ctrl.tag_timestamp(tag_name, tag_desc)
                self.assertIsNotNone(result, f"No reply for tag '{tag_name}'")
                self.assertEqual(
                    result["retcode"], 0,
                    f"Tag '{tag_name}' failed: {result}"
                )
                print(f"[E2E] Tag '{tag_name}' set successfully")
        finally:
            ctrl.close()

        # Let the service persist the tags
        time.sleep(TAG_SETTLE_SEC)

    def test_3_shutdown_recorder(self):
        """Shut down Recording Service via DDS admin command."""
        from recording_service_control import RecordingServiceController

        ctrl = RecordingServiceController(
            domain_id=0,
            service_name="remote_admin",
            xml_types_dir=XML_TYPES_DIR,
            qos_file=QOS_FILE,
        )
        try:
            result = ctrl.shutdown()
            self.assertIsNotNone(result, "No reply for shutdown")
            self.assertEqual(result["retcode"], 0,
                             f"Shutdown failed: {result}")
            print("[E2E] Shutdown command accepted")
        finally:
            ctrl.close()

        # Wait for the process to actually exit
        proc = self.__class__._recorder_proc
        if proc:
            try:
                proc.wait(timeout=SHUTDOWN_WAIT_SEC)
                print(f"[E2E] Recording Service exited "
                      f"(rc={proc.returncode})")
            except subprocess.TimeoutExpired:
                self.fail("Recording Service did not exit after shutdown")

    def test_4_verify_tags_sqlite(self):
        """Verify tags in the SQLite database directly."""
        self.assertTrue(
            os.path.isfile(METADATA_DB),
            f"Metadata database not found: {METADATA_DB}"
        )

        conn = sqlite3.connect(METADATA_DB)
        try:
            rows = conn.execute(
                "SELECT tag_name, tag_description "
                "FROM SymbolicTimestamps "
                "ORDER BY tag_name"
            ).fetchall()
        finally:
            conn.close()

        tag_names = [r[0] for r in rows]
        tag_descs = [r[1] for r in rows]

        for tag_name, tag_desc in TEST_TAGS:
            self.assertIn(tag_name, tag_names,
                          f"Tag '{tag_name}' not found in database. "
                          f"Found: {tag_names}")
            idx = tag_names.index(tag_name)
            self.assertEqual(tag_descs[idx], tag_desc,
                             f"Description mismatch for tag '{tag_name}'")

        print(f"[E2E] Verified {len(TEST_TAGS)} tags in SQLite database")

    def test_5_verify_tags_list_utility(self):
        """Verify tags using rtirecordingservice_list_tags utility."""
        result = subprocess.run(
            [LIST_TAGS_BIN, "-d", RECORDING_DIR],
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0,
                         f"list_tags failed: {result.stderr}")

        output = result.stdout
        print(f"[E2E] rtirecordingservice_list_tags output:\n{output}")

        for tag_name, tag_desc in TEST_TAGS:
            self.assertIn(tag_name, output,
                          f"Tag '{tag_name}' not in list_tags output")

        print(f"[E2E] Verified {len(TEST_TAGS)} tags via "
              "rtirecordingservice_list_tags")


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
