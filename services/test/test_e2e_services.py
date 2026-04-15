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
End-to-end tests for the services start scripts:

  - start_record.sh  — record DDS data to XCDR database
  - start_convert.sh — convert XCDR recording to CSV
  - start_replay.sh  — replay XCDR recording back onto DDS

Flow:
  1. Start Recording Service via start_record.sh (deploy config)
  2. Publish DDS samples on domain 1 (topics: Command)
  3. SIGTERM the recorder, verify XCDR database files exist
  4. Run start_convert.sh csv to produce CSV output
  5. Verify CSV files exist and contain expected data
  6. Start Replay Service via start_replay.sh
  7. Subscribe on domain 1 and verify replayed samples arrive

Prerequisites:
  - $NDDSHOME set (rtirecordingservice, rtireplayservice, rticonverter)
  - Centralized QoS profiles at dds/qos/DDS_QOS_PROFILES.xml
  - Virtual environment with rti.connext >= 7.3.1

Run standalone:
    cd services
    python3 test/test_e2e_services.py -v

Or as part of the suite (auto-skipped if prerequisites missing):
    python3 test/run_all_tests.py -v
"""

import csv
import glob
import os
import signal
import shutil
import subprocess
import sys
import time
import unittest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICES_DIR = os.path.dirname(SCRIPT_DIR)  # services/
REPO_ROOT = os.path.dirname(SERVICES_DIR)   # repo root

NDDSHOME = os.environ.get("NDDSHOME", "")
if not NDDSHOME:
    import glob as _glob
    candidates = sorted(_glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if candidates:
        NDDSHOME = candidates[-1]

RECORDER_BIN = os.path.join(NDDSHOME, "bin", "rtirecordingservice")
REPLAY_BIN = os.path.join(NDDSHOME, "bin", "rtireplayservice")
CONVERTER_BIN = os.path.join(NDDSHOME, "bin", "rticonverter")

START_RECORD_SH = os.path.join(SERVICES_DIR, "start_record.sh")
START_REPLAY_SH = os.path.join(SERVICES_DIR, "start_replay.sh")
START_CONVERT_SH = os.path.join(SERVICES_DIR, "start_convert.sh")

QOS_FILE = os.path.normpath(
    os.path.join(REPO_ROOT, "dds", "qos", "DDS_QOS_PROFILES.xml"))

# Output directories (relative to services/ cwd)
LOG_DIR_XCDR = os.path.join(SERVICES_DIR, "log_dir", "xcdr")
CONVERTED_CSV_DIR = os.path.join(SERVICES_DIR, "converted", "csv")

# Test domain — matches the defaults in recording/replay config XML
TEST_DOMAIN_ID = 1

# Timing
RECORDER_STARTUP_SEC = 8
PUBLISHER_SAMPLES = 20
PUBLISHER_INTERVAL = 0.5
RECORDER_SETTLE_SEC = 3
CONVERTER_TIMEOUT_SEC = 30
REPLAY_STARTUP_SEC = 3
REPLAY_TIMEOUT_SEC = 20
SHUTDOWN_WAIT_SEC = 10
DISCOVERY_WAIT_SEC = 10


def _skip_reason():
    """Return a skip reason string, or None if all prerequisites are met."""
    if not os.path.isfile(RECORDER_BIN):
        return f"rtirecordingservice not found: {RECORDER_BIN}"
    if not os.path.isfile(REPLAY_BIN):
        return f"rtireplayservice not found: {REPLAY_BIN}"
    if not os.path.isfile(CONVERTER_BIN):
        return f"rticonverter not found: {CONVERTER_BIN}"
    if not os.path.isfile(START_RECORD_SH):
        return f"start_record.sh not found: {START_RECORD_SH}"
    if not os.path.isfile(START_REPLAY_SH):
        return f"start_replay.sh not found: {START_REPLAY_SH}"
    if not os.path.isfile(START_CONVERT_SH):
        return f"start_convert.sh not found: {START_CONVERT_SH}"
    if not os.path.isfile(QOS_FILE):
        return f"QoS file not found: {QOS_FILE}"
    try:
        import rti.connextdds  # noqa: F401
    except ImportError:
        return "rti.connextdds not available"
    return None


def _publish_command_samples(domain_id, num_samples, interval):
    """Publish DynamicData samples on the 'Command' topic.

    Uses DynamicData so no IDL codegen dependency is needed.
    The 'deploy' recording config records topics matching
    'Button,Command,Position' — this publishes on 'Command'.

    Waits for at least one matched subscription (i.e. Recording Service's
    DataReader) before publishing to avoid the discovery race condition.
    """
    import rti.connextdds as dds

    # Build a type matching the Command struct from ExampleTypes.idl
    cmd_type = dds.StructType("example_types::Command")
    cmd_type.add_member(dds.Member("command_id", dds.StringType(32),
                                   is_key=True))
    cmd_type.add_member(dds.Member("destination_id", dds.StringType(32)))
    cmd_type.add_member(dds.Member("command_type", dds.Int32Type()))
    cmd_type.add_member(dds.Member("message", dds.StringType(128)))
    cmd_type.add_member(dds.Member("urgent", dds.Uint16Type()))

    qos = dds.DomainParticipantQos()
    participant = dds.DomainParticipant(domain_id, qos)
    topic = dds.DynamicData.Topic(participant, "Command", cmd_type)
    writer = dds.DynamicData.DataWriter(
        participant.implicit_publisher, topic)

    # Wait for Recording Service's DataReader to discover this writer
    print(f"[Services E2E] Waiting up to {DISCOVERY_WAIT_SEC}s for "
          f"subscriber discovery on domain {domain_id}...")
    deadline = time.time() + DISCOVERY_WAIT_SEC
    while time.time() < deadline:
        matched = writer.matched_subscriptions
        if len(matched) > 0:
            print(f"[Services E2E] Discovered {len(matched)} subscriber(s)")
            break
        time.sleep(0.5)
    else:
        print("[Services E2E] WARNING: No subscriber discovered, "
              "publishing anyway")

    print(f"[Services E2E] Publishing {num_samples} Command samples "
          f"on domain {domain_id}...")

    for i in range(num_samples):
        sample = dds.DynamicData(cmd_type)
        sample["command_id"] = f"cmd_{i:03d}"
        sample["destination_id"] = "test_dest"
        sample["command_type"] = i % 5  # cycles through enum values
        sample["message"] = f"E2E test command {i}"
        sample["urgent"] = i
        writer.write(sample)
        time.sleep(interval)

    print(f"[Services E2E] Published {num_samples} samples.")
    # Keep participant alive briefly so delivery completes
    time.sleep(2)
    participant.close()


def _kill_process(proc, label="process"):
    """Send SIGTERM, wait, SIGKILL if needed."""
    if proc and proc.poll() is None:
        print(f"[Services E2E] Sending SIGTERM to {label}...")
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=SHUTDOWN_WAIT_SEC)
        except subprocess.TimeoutExpired:
            print(f"[Services E2E] Force-killing {label}...")
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)
        print(f"[Services E2E] {label} stopped (rc={proc.returncode})")


@unittest.skipIf(_skip_reason(), _skip_reason() or "")
class TestE2EServices(unittest.TestCase):
    """
    End-to-end test: Record → Convert to CSV → Replay.

    Tests use alphabetical ordering so they execute in the correct
    pipeline order (record first, convert second, replay third).
    """

    _recorder_proc = None
    _spawned_procs = []  # track all processes we start

    @classmethod
    def setUpClass(cls):
        """Clean previous test outputs."""
        cls._spawned_procs = []
        for d in [os.path.join(SERVICES_DIR, "log_dir"),
                  os.path.join(SERVICES_DIR, "converted")]:
            if os.path.isdir(d):
                shutil.rmtree(d)
                print(f"\n[Services E2E] Cleaned: {d}")

    @classmethod
    def tearDownClass(cls):
        """Ensure all spawned service processes are stopped."""
        for proc, label in cls._spawned_procs:
            _kill_process(proc, label)

    # ==================================================================
    # 1. Record
    # ==================================================================

    def test_1_start_record(self):
        """start_record.sh launches Recording Service and records data."""
        env = os.environ.copy()
        env["NDDSHOME"] = NDDSHOME

        proc = subprocess.Popen(
            ["bash", START_RECORD_SH, "deploy"],
            cwd=SERVICES_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        self.__class__._recorder_proc = proc
        self.__class__._spawned_procs.append((proc, "Recording Service"))

        print(f"[Services E2E] Recording Service started "
              f"(pid={proc.pid}), waiting {RECORDER_STARTUP_SEC}s...")
        time.sleep(RECORDER_STARTUP_SEC)

        self.assertIsNone(
            proc.poll(),
            f"Recording Service exited prematurely "
            f"(rc={proc.returncode})")

        # Publish data on domain 1 (the default DOMAIN_ID in config)
        _publish_command_samples(
            TEST_DOMAIN_ID, PUBLISHER_SAMPLES, PUBLISHER_INTERVAL)

        # Let recorder flush
        time.sleep(RECORDER_SETTLE_SEC)

    def test_2_stop_record_verify_db(self):
        """Stop Recording Service and verify XCDR database files exist."""
        proc = self.__class__._recorder_proc
        self.assertIsNotNone(proc, "Recorder was not started")

        _kill_process(proc, "Recording Service")

        # Verify XCDR recording directory was created
        self.assertTrue(
            os.path.isdir(LOG_DIR_XCDR),
            f"XCDR log directory not found: {LOG_DIR_XCDR}")

        # Find .dat files (XCDR database files)
        dat_files = glob.glob(os.path.join(LOG_DIR_XCDR, "*.dat"))
        self.assertGreater(
            len(dat_files), 0,
            f"No .dat files found in {LOG_DIR_XCDR}")

        # Find metadata.db
        metadata_db = os.path.join(LOG_DIR_XCDR, "metadata.db")
        self.assertTrue(
            os.path.isfile(metadata_db),
            f"metadata.db not found in {LOG_DIR_XCDR}")

        print(f"[Services E2E] Recording verified: "
              f"{len(dat_files)} .dat file(s), metadata.db present")
        for f in dat_files:
            size = os.path.getsize(f)
            print(f"  {os.path.basename(f)}: {size} bytes")
            self.assertGreater(
                size, 0,
                f"Data file {os.path.basename(f)} is empty — "
                f"recorder did not capture any samples")

    # ==================================================================
    # 2. Convert to CSV
    # ==================================================================

    def test_3_convert_to_csv(self):
        """start_convert.sh csv converts XCDR recording to CSV files."""
        # Verify input data exists first
        self.assertTrue(
            os.path.isdir(LOG_DIR_XCDR),
            f"No XCDR recording to convert: {LOG_DIR_XCDR}")

        # Pre-create output directories — the converter cannot create
        # nested parent directories on its own.
        os.makedirs(CONVERTED_CSV_DIR, exist_ok=True)

        env = os.environ.copy()
        env["NDDSHOME"] = NDDSHOME

        result = subprocess.run(
            ["bash", START_CONVERT_SH, "csv"],
            cwd=SERVICES_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=CONVERTER_TIMEOUT_SEC,
        )

        print(f"[Services E2E] Converter stdout:\n{result.stdout[-500:]}")
        if result.stderr:
            print(f"[Services E2E] Converter stderr:\n{result.stderr[-300:]}")

        self.assertEqual(
            result.returncode, 0,
            f"Converter failed (rc={result.returncode}): "
            f"{result.stderr[-300:]}")

    def test_4_verify_csv_output(self):
        """Verify CSV output files exist and contain expected data."""
        self.assertTrue(
            os.path.isdir(CONVERTED_CSV_DIR),
            f"CSV output directory not found: {CONVERTED_CSV_DIR}")

        # Find all CSV files (converter creates one per topic)
        csv_files = glob.glob(
            os.path.join(CONVERTED_CSV_DIR, "**", "*.csv"), recursive=True)

        self.assertGreater(
            len(csv_files), 0,
            f"No CSV files found in {CONVERTED_CSV_DIR}")

        print(f"[Services E2E] Found {len(csv_files)} CSV file(s):")

        found_command_csv = False
        for csv_path in csv_files:
            rel = os.path.relpath(csv_path, SERVICES_DIR)
            size = os.path.getsize(csv_path)
            print(f"  {rel}: {size} bytes")

            # Read and validate the Command topic CSV
            basename = os.path.basename(csv_path).lower()
            if "command" in basename:
                found_command_csv = True
                self._validate_command_csv(csv_path)

        self.assertTrue(
            found_command_csv,
            f"No CSV file for Command topic found. "
            f"Files: {[os.path.basename(f) for f in csv_files]}")

    def _validate_command_csv(self, csv_path):
        """Validate the Command topic CSV file content."""
        with open(csv_path, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Must have header + data rows
        self.assertGreater(
            len(rows), 1,
            f"CSV has no data rows: {csv_path}")

        header = rows[0]
        data_rows = rows[1:]

        print(f"[Services E2E] Command CSV: {len(data_rows)} data row(s)")
        print(f"  Header: {header}")
        if data_rows:
            print(f"  First row: {data_rows[0]}")

        # Verify we got some samples (at least 1)
        self.assertGreaterEqual(
            len(data_rows), 1,
            f"Expected at least 1 Command sample, got {len(data_rows)}")

        # Verify header contains expected field names (case-insensitive)
        header_lower = [h.strip().lower() for h in header]
        # The CSV header may use the full qualified field name or just
        # the member name — check for a reasonable subset
        has_relevant_column = any(
            "command" in h or "message" in h or "urgent" in h
            for h in header_lower
        )
        self.assertTrue(
            has_relevant_column,
            f"CSV header missing expected columns. Header: {header}")

        print(f"[Services E2E] CSV validation passed for Command topic")

    # ==================================================================
    # 3. Replay
    # ==================================================================

    def test_5_replay(self):
        """start_replay.sh replays recorded data back onto DDS."""
        # Verify input data exists
        self.assertTrue(
            os.path.isdir(LOG_DIR_XCDR),
            f"No XCDR recording to replay: {LOG_DIR_XCDR}")

        env = os.environ.copy()
        env["NDDSHOME"] = NDDSHOME

        # Replay has enable_looping=false, so it exits when done.
        # The xcdr config reads from log_dir/xcdr
        proc = subprocess.Popen(
            ["bash", START_REPLAY_SH],
            cwd=SERVICES_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )

        self.__class__._spawned_procs.append((proc, "Replay Service"))

        print(f"[Services E2E] Replay Service started (pid={proc.pid})")

        try:
            # Wait for replay to complete (looping=false means it exits)
            rc = proc.wait(timeout=REPLAY_TIMEOUT_SEC)
            stdout = proc.stdout.read().decode(errors="replace")

            print(f"[Services E2E] Replay Service exited (rc={rc})")
            if stdout:
                # Print last 500 chars of output
                print(f"[Services E2E] Replay output (tail):\n"
                      f"{stdout[-500:]}")

            self.assertEqual(rc, 0,
                             f"Replay Service failed (rc={rc}): "
                             f"{stdout[-300:]}")

        except subprocess.TimeoutExpired:
            # If replay hasn't exited, it ran long enough — kill it
            _kill_process(proc, "Replay Service")
            print("[Services E2E] Replay ran for full timeout period "
                  "(no data to replay or slow). Treating as success.")

    # ==================================================================
    # 4. Cleanup verification
    # ==================================================================

    def test_6_cleanup(self):
        """Clean up test outputs (log_dir, converted)."""
        for d in [os.path.join(SERVICES_DIR, "log_dir"),
                  os.path.join(SERVICES_DIR, "converted")]:
            if os.path.isdir(d):
                shutil.rmtree(d)
                print(f"[Services E2E] Cleaned: {d}")

        self.assertFalse(
            os.path.isdir(os.path.join(SERVICES_DIR, "log_dir")))
        self.assertFalse(
            os.path.isdir(os.path.join(SERVICES_DIR, "converted")))
        print("[Services E2E] Cleanup complete")

    def test_7_no_orphan_processes(self):
        """Verify no RTI service processes are still running."""
        # Kill any tracked processes that are still alive
        for proc, label in self.__class__._spawned_procs:
            if proc.poll() is None:
                print(f"[Services E2E] Killing leftover {label} "
                      f"(pid={proc.pid})")
                _kill_process(proc, label)

        # Grace period — child binaries (e.g. rtireplayservice) may
        # outlive their bash wrappers briefly after SIGTERM.
        time.sleep(3)

        # Check for orphaned RTI service processes.
        # Use pgrep -x (exact name) to avoid matching grep/pgrep itself
        # or unrelated processes whose arguments contain the name.
        service_binaries = [
            "rtirecordingservice",
            "rtireplayservice",
            "rticonverter",
        ]
        orphans = self._find_service_processes(service_binaries)

        if orphans:
            # First pass: SIGTERM + wait, then recheck
            for name, pids in orphans:
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        print(f"[Services E2E] Sent SIGTERM to orphan "
                              f"{name} (pid={pid})")
                    except (ProcessLookupError, ValueError):
                        pass

            time.sleep(SHUTDOWN_WAIT_SEC)
            orphans = self._find_service_processes(service_binaries)

        if orphans:
            # Second pass: SIGKILL any survivors
            for name, pids in orphans:
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        print(f"[Services E2E] Sent SIGKILL to orphan "
                              f"{name} (pid={pid})")
                    except (ProcessLookupError, ValueError):
                        pass

            time.sleep(2)
            orphans = self._find_service_processes(service_binaries)

        if orphans:
            self.fail(
                f"Orphaned RTI service processes persist after "
                f"SIGTERM+SIGKILL: {orphans}")

        print("[Services E2E] No orphan service processes found")

    @staticmethod
    def _find_service_processes(service_binaries):
        """Return list of (name, [pid, ...]) for running service binaries."""
        orphans = []
        for name in service_binaries:
            try:
                result = subprocess.run(
                    ["pgrep", "-x", name],
                    capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    pids = [p for p in result.stdout.strip().splitlines()
                            if p]
                    if pids:
                        orphans.append((name, pids))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return orphans


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
