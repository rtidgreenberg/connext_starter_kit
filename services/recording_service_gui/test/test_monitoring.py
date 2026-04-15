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
Tests for recording_service_monitor.py

Test layers:
  1. Pure parsing tests — mock typed samples, no DDS required
  2. Callback plumbing tests — verify emit/error behavior
  3. Integration tests — require rti.connextdds + generated Python types

Run:
    python3 test/test_monitoring.py            # all tests
    python3 test/test_monitoring.py -v         # verbose
"""

import os
import sys
import unittest
from unittest.mock import MagicMock
from enum import IntEnum

# Ensure the parent directory (recording_service_gui/) is on the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# Add python_types to path so generated modules can be imported
PYTHON_TYPES_DIR = os.path.join(PARENT_DIR, "python_types")
if os.path.isdir(PYTHON_TYPES_DIR) and PYTHON_TYPES_DIR not in sys.path:
    sys.path.insert(0, PYTHON_TYPES_DIR)

from recording_service_monitor import RecordingServiceMonitor


# ---------------------------------------------------------------------------
# Try to import the real enum types; fall back to local stubs for CI
# environments where the generated types may not exist.
# ---------------------------------------------------------------------------
try:
    from ServiceCommon import RTI as _RTI
    ResourceKind = _RTI.Service.Monitoring.ResourceKind
    EntityStateKind = _RTI.Service.EntityStateKind
except ImportError:
    # Stub enums that mirror the IDL values for unit-only runs
    class ResourceKind(IntEnum):
        RECORDING_SERVICE = 20000
        RECORDING_SESSION = 20001
        RECORDING_TOPIC_GROUP = 20002
        RECORDING_TOPIC = 20003

    class EntityStateKind(IntEnum):
        INVALID = 0
        ENABLED = 1
        DISABLED = 2
        STARTED = 3
        STOPPED = 4
        RUNNING = 5
        PAUSED = 6


# ===================================================================
# Helpers — fake typed-sample objects for parsing tests
# ===================================================================

class FakeObj:
    """Simple namespace object — attribute access mirrors generated types."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def make_sample(discriminator, branch_key, branch_data):
    """
    Build a fake top-level monitoring sample matching the typed API:
        sample.data.value.discriminator  → ResourceKind enum member
        sample.data.value.<branch_key>   → FakeObj with branch_data
    """
    branch_obj = _make_obj(branch_data)
    value = FakeObj(discriminator=discriminator, **{branch_key: branch_obj})
    return FakeObj(value=value)


def _make_obj(d):
    """Recursively convert a dict into nested FakeObj instances."""
    if isinstance(d, dict):
        return FakeObj(**{k: _make_obj(v) for k, v in d.items()})
    return d


def _parser():
    """Create a bare RecordingServiceMonitor without DDS, with enum refs."""
    p = object.__new__(RecordingServiceMonitor)
    p._ResourceKind = ResourceKind
    p._EntityStateKind = EntityStateKind
    return p


# ===================================================================
# Layer 1: Config Sample Parsing
# ===================================================================

class TestParseConfigSample(unittest.TestCase):
    """Test RecordingServiceMonitor._parse_config_sample with fake data."""

    def setUp(self):
        self.parser = _parser()

    def test_recording_service_config(self):
        """Service-level config sample → service_name and db_directory."""
        data = make_sample(
            ResourceKind.RECORDING_SERVICE,
            "recording_service",
            {
                "application_name": "my_recorder",
                "builtin_sqlite": {"db_directory": "/tmp/recording"},
            },
        )
        result = self.parser._parse_config_sample(data)

        self.assertEqual(result["kind"], "config")
        self.assertTrue(result["service_detected"])
        self.assertEqual(result["service_name"], "my_recorder")
        self.assertEqual(result["db_directory"], "/tmp/recording")
        self.assertEqual(result["topics"], [])

    def test_recording_topic_config(self):
        """Topic-level config sample → topic name in topics list."""
        data = make_sample(
            ResourceKind.RECORDING_TOPIC,
            "recording_topic",
            {"topic_name": "Square"},
        )
        result = self.parser._parse_config_sample(data)

        self.assertEqual(result["kind"], "config")
        self.assertTrue(result["service_detected"])
        self.assertEqual(result["topics"], ["Square"])

    def test_unrelated_resource_kind(self):
        """Session-level config → returns None (ignored)."""
        data = make_sample(
            ResourceKind.RECORDING_SESSION,
            "recording_session",
            {},
        )
        result = self.parser._parse_config_sample(data)
        self.assertIsNone(result)

    def test_missing_sqlite_fields(self):
        """Service config without builtin_sqlite → db_directory defaults empty."""
        svc = FakeObj(application_name="recorder", builtin_sqlite=None)
        value = FakeObj(
            discriminator=ResourceKind.RECORDING_SERVICE,
            recording_service=svc,
        )
        data = FakeObj(value=value)
        result = self.parser._parse_config_sample(data)

        self.assertEqual(result["service_name"], "recorder")
        self.assertEqual(result["db_directory"], "")


# ===================================================================
# Layer 1: Event Sample Parsing
# ===================================================================

class TestParseEventSample(unittest.TestCase):
    """Test RecordingServiceMonitor._parse_event_sample with fake data."""

    def setUp(self):
        self.parser = _parser()

    def test_state_change_running(self):
        """Service event with RUNNING state → correct state_int and event text."""
        data = make_sample(
            ResourceKind.RECORDING_SERVICE,
            "recording_service",
            {
                "state": EntityStateKind.RUNNING,
                "builtin_sqlite": {"rollover_count": 3},
            },
        )
        result = self.parser._parse_event_sample(data)

        self.assertEqual(result["kind"], "event")
        self.assertTrue(result["service_detected"])
        self.assertEqual(result["state_int"], EntityStateKind.RUNNING.value)
        self.assertEqual(result["rollover_count"], 3)
        self.assertIn("RUNNING", result["events"][0])

    def test_state_change_paused(self):
        """Service event with PAUSED state."""
        data = make_sample(
            ResourceKind.RECORDING_SERVICE,
            "recording_service",
            {"state": EntityStateKind.PAUSED, "builtin_sqlite": None},
        )
        result = self.parser._parse_event_sample(data)

        self.assertEqual(result["state_int"], EntityStateKind.PAUSED.value)
        self.assertIn("PAUSED", result["events"][0])
        self.assertEqual(result["rollover_count"], -1)

    def test_non_service_resource_ignored(self):
        """Event for a non-service resource → None."""
        data = make_sample(
            ResourceKind.RECORDING_SESSION,
            "recording_session",
            {"state": EntityStateKind.RUNNING},
        )
        result = self.parser._parse_event_sample(data)
        self.assertIsNone(result)


# ===================================================================
# Layer 1: Periodic Sample Parsing
# ===================================================================

class TestParsePeriodicSample(unittest.TestCase):
    """Test RecordingServiceMonitor._parse_periodic_sample with fake data."""

    def setUp(self):
        self.parser = _parser()

    def test_full_stats(self):
        """Periodic sample with all fields populated."""
        data = make_sample(
            ResourceKind.RECORDING_SERVICE,
            "recording_service",
            {
                "process": {
                    "uptime_sec": 3661,
                    "cpu_usage_percentage": {
                        "publication_period_metrics": {"mean": 5.5},
                    },
                    "physical_memory_kb": {
                        "publication_period_metrics": {"mean": 2048.0},
                    },
                },
                "builtin_sqlite": {
                    "current_file": "/tmp/rec/data.db",
                    "current_file_size": 1048576,
                },
            },
        )
        result = self.parser._parse_periodic_sample(data)

        self.assertEqual(result["kind"], "periodic")
        self.assertTrue(result["service_detected"])
        self.assertEqual(result["uptime"], 3661)
        self.assertAlmostEqual(result["cpu"], 5.5)
        self.assertAlmostEqual(result["memory_kb"], 2048.0)
        self.assertEqual(result["db_file"], "/tmp/rec/data.db")
        self.assertEqual(result["db_file_size"], 1048576)

    def test_missing_process(self):
        """Periodic sample without process info → defaults to -1."""
        svc = FakeObj(process=None, builtin_sqlite=None)
        value = FakeObj(
            discriminator=ResourceKind.RECORDING_SERVICE,
            recording_service=svc,
        )
        data = FakeObj(value=value)
        result = self.parser._parse_periodic_sample(data)

        self.assertEqual(result["uptime"], -1)
        self.assertEqual(result["cpu"], -1.0)
        self.assertEqual(result["memory_kb"], -1.0)
        self.assertEqual(result["db_file"], "")
        self.assertEqual(result["db_file_size"], -1)

    def test_non_service_resource_ignored(self):
        """Periodic sample for non-service resource → None."""
        data = make_sample(
            ResourceKind.RECORDING_TOPIC_GROUP,
            "recording_topic_group",
            {},
        )
        result = self.parser._parse_periodic_sample(data)
        self.assertIsNone(result)


# ===================================================================
# Layer 2: Callback Plumbing
# ===================================================================

class TestEmitCallback(unittest.TestCase):
    """Test the _emit method and error swallowing."""

    def setUp(self):
        self.parser = _parser()

    def test_callback_receives_update(self):
        """on_update callback is called with the update dict."""
        received = []
        self.parser._on_update = lambda u: received.append(u)

        self.parser._emit({"kind": "config", "service_detected": True})

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["kind"], "config")

    def test_callback_exception_swallowed(self):
        """If on_update raises, _emit does not propagate the exception."""
        self.parser._on_update = MagicMock(side_effect=RuntimeError("boom"))

        # Should not raise
        self.parser._emit({"kind": "error", "error": "test"})

    def test_on_data_available_emits_error_on_take_failure(self):
        """If reader.take() raises, an error update is emitted."""
        received = []
        self.parser._on_update = lambda u: received.append(u)

        mock_reader = MagicMock()
        mock_reader.take.side_effect = RuntimeError("take failed")

        self.parser._on_data_available("config", mock_reader)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["kind"], "error")
        self.assertIn("take failed", received[0]["error"])

    def test_on_data_available_skips_invalid_samples(self):
        """Invalid samples (disposed/unregistered) are skipped."""
        received = []
        self.parser._on_update = lambda u: received.append(u)

        invalid_sample = MagicMock()
        invalid_sample.info.valid = False

        mock_reader = MagicMock()
        mock_reader.take.return_value = [invalid_sample]

        self.parser._on_data_available("config", mock_reader)

        self.assertEqual(len(received), 0)


# ===================================================================
# Layer 3: Integration Tests (require rti.connextdds)
# ===================================================================

class TestIntegration(unittest.TestCase):
    """
    Integration tests requiring rti.connextdds and generated Python types.
    Skipped if either is unavailable.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import rti.connextdds  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("rti.connextdds not available")

        python_types_dir = os.path.join(PARENT_DIR, "python_types")
        if not os.path.isfile(
                os.path.join(python_types_dir, "ServiceMonitoring.py")):
            raise unittest.SkipTest(
                "Monitoring Python types not generated (run setup.sh)")

    def test_readers_created(self):
        """RecordingServiceMonitor creates 3 DataReaders on init."""
        qos_file = os.path.normpath(os.path.join(
            PARENT_DIR, "..", "..", "dds", "qos", "DDS_QOS_PROFILES.xml"))
        python_types_dir = os.path.join(PARENT_DIR, "python_types")

        sub = RecordingServiceMonitor(
            domain_id=99,  # High domain to avoid conflicts
            python_types_dir=python_types_dir,
            qos_file=qos_file,
        )
        try:
            self.assertIsNotNone(sub._config_reader)
            self.assertIsNotNone(sub._event_reader)
            self.assertIsNotNone(sub._periodic_reader)
        finally:
            sub.close()

    def test_close_is_idempotent(self):
        """Calling close() twice does not raise."""
        qos_file = os.path.normpath(os.path.join(
            PARENT_DIR, "..", "..", "dds", "qos", "DDS_QOS_PROFILES.xml"))
        python_types_dir = os.path.join(PARENT_DIR, "python_types")

        sub = RecordingServiceMonitor(
            domain_id=98,
            python_types_dir=python_types_dir,
            qos_file=qos_file,
        )
        sub.close()
        sub.close()  # Should not raise


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
