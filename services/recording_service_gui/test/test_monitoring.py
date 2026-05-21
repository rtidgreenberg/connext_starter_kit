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
    3. Integration tests — require rti.connextdds + generated XML types

Run:
    python3 test/test_monitoring.py            # all tests
    python3 test/test_monitoring.py -v         # verbose
"""

import os
import sys
import unittest
from unittest.mock import MagicMock
import asyncio
import tempfile
from enum import IntEnum
import rti.connextdds.compliance as compliance

# Ensure the parent directory (recording_service_gui/) is on the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from recording_service_monitor import (
    RecordingServiceMonitor,
    _field,
    _selected_union_value,
    _union_discriminator,
)
from recording_service_environment import (
    configure_recording_service_xtypes_policy,
    connext_version_from_nddshome,
    ensure_rti_license,
    read_generated_types_stamp,
    validate_generated_types,
    write_generated_types_stamp,
)


# Enum values mirrored from the RTI service IDL. The monitor uses XML
# DynamicData and does not require generated Python type modules.
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


class BrokenFieldObj:
    """Object that simulates an unexpected DynamicData access failure."""

    def __getattr__(self, _name):
        raise AttributeError(_name)

    def __getitem__(self, name):
        raise RuntimeError(f"unexpected access failure for {name}")


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


class TestGeneratedTypesStamp(unittest.TestCase):
    """Test metadata tying generated XML types to a Connext install."""

    def setUp(self):
        repo_root = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))
        output_root = os.path.join(repo_root, "test_output")
        os.makedirs(output_root, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(
            prefix="recording_service_types_", dir=output_root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_connext_version_from_nddshome(self):
        self.assertEqual(
            connext_version_from_nddshome("/opt/rti_connext_dds-7.6.0"),
            "7.6.0",
        )

    def test_generated_types_stamp_validates_matching_install(self):
        xml_types_dir = os.path.join(self._tmp.name, "xml_types")
        nddshome = os.path.join(self._tmp.name, "rti_connext_dds-7.6.0")
        os.makedirs(nddshome, exist_ok=True)

        write_generated_types_stamp(xml_types_dir, nddshome)

        metadata = validate_generated_types(xml_types_dir, nddshome)

        self.assertEqual(metadata["nddshome"], os.path.realpath(nddshome))
        self.assertEqual(metadata["version"], "7.6.0")

    def test_generated_types_stamp_rejects_mismatched_install(self):
        xml_types_dir = os.path.join(self._tmp.name, "xml_types")
        generated_home = os.path.join(self._tmp.name, "rti_connext_dds-7.6.0")
        active_home = os.path.join(self._tmp.name, "rti_connext_dds-7.7.0")
        os.makedirs(generated_home, exist_ok=True)
        os.makedirs(active_home, exist_ok=True)
        write_generated_types_stamp(xml_types_dir, generated_home)

        with self.assertRaisesRegex(RuntimeError, "different Connext install"):
            validate_generated_types(xml_types_dir, active_home)

    def test_generated_types_stamp_requires_metadata_file(self):
        xml_types_dir = os.path.join(self._tmp.name, "xml_types")
        os.makedirs(xml_types_dir, exist_ok=True)

        with self.assertRaisesRegex(RuntimeError, "metadata not found"):
            validate_generated_types(xml_types_dir, self._tmp.name)

    def test_read_generated_types_stamp(self):
        xml_types_dir = os.path.join(self._tmp.name, "xml_types")
        nddshome = os.path.join(self._tmp.name, "rti_connext_dds-7.6.0")
        os.makedirs(nddshome, exist_ok=True)

        write_generated_types_stamp(xml_types_dir, nddshome)
        metadata = read_generated_types_stamp(xml_types_dir)

        self.assertEqual(metadata["version"], "7.6.0")


class TestUnionHelpers(unittest.TestCase):
    """Test helpers used to parse monitoring union values."""

    def test_field_default_does_not_hide_unexpected_access_errors(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected access failure"):
            _field(BrokenFieldObj(), "missing", "fallback")

    def test_union_discriminator_prefers_discriminator(self):
        union_value = FakeObj(
            discriminator=ResourceKind.RECORDING_SERVICE,
            discriminator_value=ResourceKind.RECORDING_TOPIC,
        )

        self.assertEqual(
            _union_discriminator(union_value),
            ResourceKind.RECORDING_SERVICE.value,
        )

    def test_union_discriminator_accepts_compatibility_fallback(self):
        union_value = FakeObj(discriminator_value=ResourceKind.RECORDING_TOPIC)

        self.assertEqual(
            _union_discriminator(union_value),
            ResourceKind.RECORDING_TOPIC.value,
        )

    def test_union_discriminator_rejects_missing_discriminator(self):
        with self.assertRaisesRegex(ValueError, "Unable to read"):
            _union_discriminator(FakeObj())

    def test_union_discriminator_rejects_non_numeric_discriminator(self):
        with self.assertRaisesRegex(ValueError, "Unable to read"):
            _union_discriminator(FakeObj(discriminator="not-an-int"))

    def test_selected_union_value_rejects_no_selected_member(self):
        union_value = FakeObj(
            discriminator=ResourceKind.RECORDING_SERVICE,
            value=None,
        )

        with self.assertRaisesRegex(ValueError, "selects no member"):
            _selected_union_value(union_value, "recording_service")


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

    def test_missing_optional_metric_defaults_without_error(self):
        """Missing optional metric internals do not fail the whole sample."""
        metric_without_mean = FakeObj(publication_period_metrics=FakeObj())
        svc = FakeObj(
            process=FakeObj(
                uptime_sec=12,
                cpu_usage_percentage=metric_without_mean,
                physical_memory_kb=None,
            ),
            host=None,
            builtin_sqlite=None,
        )
        data = FakeObj(value=FakeObj(
            discriminator=ResourceKind.RECORDING_SERVICE,
            recording_service=svc,
        ))

        result = self.parser._parse_periodic_sample(data)

        self.assertEqual(result["uptime"], 12)
        self.assertEqual(result["cpu"], -1.0)
        self.assertEqual(result["memory_kb"], -1.0)

    def test_unexpected_optional_field_error_is_reported(self):
        """Unexpected field-access errors are not silently swallowed."""
        received = []
        self.parser._on_update = lambda u: received.append(u)
        sample = FakeObj(
            info=FakeObj(valid=True),
            data=FakeObj(value=FakeObj(
                discriminator=ResourceKind.RECORDING_SERVICE,
                recording_service=FakeObj(
                    process=BrokenFieldObj(),
                    host=None,
                    builtin_sqlite=None,
                ),
            )),
        )

        self.parser._process_sample("periodic", sample)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["kind"], "error")
        self.assertIn("periodic parse error", received[0]["error"])
        self.assertIn("unexpected access failure", received[0]["error"])

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

    def test_process_sample_emits_parse_errors(self):
        """If sample parsing raises, an error update is emitted."""
        received = []
        self.parser._on_update = lambda u: received.append(u)

        sample = MagicMock()
        sample.info.valid = True
        sample.data = FakeObj(value=FakeObj(discriminator="bad"))

        self.parser._process_sample("config", sample)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["kind"], "error")
        self.assertIn("config parse error", received[0]["error"])

    def test_process_sample_skips_invalid_samples(self):
        """Invalid samples (disposed/unregistered) are skipped."""
        received = []
        self.parser._on_update = lambda u: received.append(u)

        invalid_sample = MagicMock()
        invalid_sample.info.valid = False

        self.parser._process_sample("config", invalid_sample)

        self.assertEqual(len(received), 0)


# ===================================================================
# Layer 2: Compliance Mask Configuration
# ===================================================================

class TestXTypesCompliance(unittest.TestCase):
    """Test process-wide unknown union discriminator configuration."""

    def test_recording_service_xtypes_policy_sets_required_bits(self):
        original_mask = compliance.get_xtypes_mask()
        accept_unknown = (
            compliance.XTypesMask.ACCEPT_UNKNOWN_DISCRIMINATOR_BIT)
        select_default = (
            compliance.XTypesMask.SELECT_DEFAULT_DISCRIMINATOR_BIT)

        try:
            compliance.set_xtypes_mask(original_mask | select_default)
            configure_recording_service_xtypes_policy()
            updated_mask = compliance.get_xtypes_mask()

            self.assertEqual(updated_mask & accept_unknown, accept_unknown)
            self.assertNotEqual(updated_mask & select_default, select_default)
        finally:
            compliance.set_xtypes_mask(original_mask)

    def test_recording_service_xtypes_policy_is_idempotent(self):
        original_mask = compliance.get_xtypes_mask()
        accept_unknown = (
            compliance.XTypesMask.ACCEPT_UNKNOWN_DISCRIMINATOR_BIT)
        select_default = (
            compliance.XTypesMask.SELECT_DEFAULT_DISCRIMINATOR_BIT)
        expected_mask = (original_mask | accept_unknown) & select_default.flip()

        try:
            compliance.set_xtypes_mask(original_mask)
            first_mask = configure_recording_service_xtypes_policy()
            second_mask = configure_recording_service_xtypes_policy()

            self.assertEqual(first_mask, expected_mask)
            self.assertEqual(second_mask, expected_mask)
            self.assertEqual(compliance.get_xtypes_mask(), expected_mask)
        finally:
            compliance.set_xtypes_mask(original_mask)


# ===================================================================
# Layer 2: Lifecycle
# ===================================================================

class TestLifecycle(unittest.TestCase):
    """Test monitor resource teardown helpers without real DDS entities."""

    def test_close_without_loop_closes_participant_once(self):
        monitor = object.__new__(RecordingServiceMonitor)
        monitor._closed = False
        monitor._loop = None
        monitor._thread = None
        monitor._config_reader = MagicMock()
        monitor._event_reader = MagicMock()
        monitor._periodic_reader = MagicMock()
        monitor._subscriber = MagicMock()
        participant = MagicMock()
        monitor._participant = participant

        monitor.close()
        monitor.close()

        participant.close.assert_called_once()
        participant.close_contained_entities.assert_called_once()
        self.assertTrue(monitor._closed)


class TestAsyncLifecycle(unittest.IsolatedAsyncioTestCase):
    """Test async shutdown behavior without real DDS entities."""

    async def test_shutdown_cancels_reader_tasks_before_participant_close(self):
        monitor = object.__new__(RecordingServiceMonitor)
        participant = MagicMock()
        task = asyncio.create_task(asyncio.sleep(60))
        monitor._reader_tasks = [task]
        monitor._config_reader = MagicMock()
        monitor._event_reader = MagicMock()
        monitor._periodic_reader = MagicMock()
        monitor._subscriber = MagicMock()
        monitor._participant = participant

        await monitor._shutdown_async()

        self.assertTrue(task.cancelled())
        self.assertEqual(monitor._reader_tasks, [])
        participant.close_contained_entities.assert_called_once()
        participant.close.assert_called_once()
        self.assertIsNone(monitor._participant)


# ===================================================================
# Layer 3: Integration Tests (require rti.connextdds)
# ===================================================================

class TestIntegration(unittest.TestCase):
    """
    Integration tests requiring rti.connextdds and generated XML types.
    Skipped if either is unavailable.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import rti.connextdds as dds
        except ImportError:
            raise unittest.SkipTest("rti.connextdds not available")
        ensure_rti_license(os.environ.get("NDDSHOME"))
        try:
            participant = dds.DomainParticipant(97)
            participant.close()
        except Exception as exc:
            raise unittest.SkipTest(
                f"DDS DomainParticipant unavailable: {exc}")

        xml_types_dir = os.path.join(PARENT_DIR, "xml_types")
        if not os.path.isfile(
            os.path.join(xml_types_dir, "ServiceMonitoring.xml")):
            raise unittest.SkipTest(
            "Monitoring XML types not generated (run setup.sh)")

    def test_readers_created(self):
        """RecordingServiceMonitor creates 3 DataReaders on init."""
        qos_file = os.path.normpath(os.path.join(
            PARENT_DIR, "..", "..", "dds", "qos", "DDS_QOS_PROFILES.xml"))
        xml_types_dir = os.path.join(PARENT_DIR, "xml_types")

        sub = RecordingServiceMonitor(
            domain_id=99,  # High domain to avoid conflicts
            xml_types_dir=xml_types_dir,
            qos_file=qos_file,
        )
        try:
            self.assertIsNotNone(sub._config_reader)
            self.assertIsNotNone(sub._event_reader)
            self.assertIsNotNone(sub._periodic_reader)
            self.assertIsNotNone(sub._subscriber)
        finally:
            sub.close()

    def test_xml_dynamicdata_union_discriminator_is_readable(self):
        """XML-loaded monitoring unions expose readable discriminators."""
        import rti.connextdds as dds

        xml_file = os.path.join(PARENT_DIR, "xml_types", "ServiceMonitoring.xml")
        provider = dds.QosProvider(xml_file)
        config_type = provider.type("RTI::Service::Monitoring::Config")
        sample = dds.DynamicData(config_type)
        union_value = sample["value"]
        recording_member = next(
            member for member in union_value.type.members()
            if member.name == "recording_service")
        service_config = dds.DynamicData(recording_member.type)

        service_config["application_name"] = "deploy"
        union_value["recording_service"] = service_config
        sample["value"] = union_value
        union_value = sample["value"]

        self.assertEqual(
            _union_discriminator(union_value),
            ResourceKind.RECORDING_SERVICE.value,
        )
        result = RecordingServiceMonitor._parse_config_sample(
            _parser(), sample)
        self.assertEqual(result["service_name"], "deploy")

    def test_close_is_idempotent(self):
        """Calling close() twice does not raise."""
        qos_file = os.path.normpath(os.path.join(
            PARENT_DIR, "..", "..", "dds", "qos", "DDS_QOS_PROFILES.xml"))
        xml_types_dir = os.path.join(PARENT_DIR, "xml_types")

        sub = RecordingServiceMonitor(
            domain_id=98,
            xml_types_dir=xml_types_dir,
            qos_file=qos_file,
        )
        sub.close()
        sub.close()  # Should not raise


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
