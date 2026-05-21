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
Tests for recording_service_control.py

Test layers:
  1. Pure logic tests — constants, helper functions, CLI arg parsing
  2. Construction tests — require rti.connextdds + XML types

Run:
    python3 test/test_control.py            # all tests
    python3 test/test_control.py -v         # verbose

Or as part of the full suite:
    python3 test/run_all_tests.py
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the parent directory (recording_service_gui/) is on the path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from recording_service_control import (
    ACTION_CREATE,
    ACTION_GET,
    ACTION_UPDATE,
    ACTION_DELETE,
    RETCODE_OK,
    RETCODE_ERROR,
    COMMAND_REQUEST_TOPIC_NAME,
    COMMAND_REPLY_TOPIC_NAME,
    DEFAULT_DOMAIN_ID,
    DEFAULT_SERVICE_NAME,
    DEFAULT_REPLY_TIMEOUT_SEC,
    ENTITY_STATE_RUNNING,
    ENTITY_STATE_PAUSED,
    _action_name,
    _serialize_entity_state,
    RecordingServiceController,
    main,
)


class FakeStatus:
    def __init__(self, current_count=0, current_count_change=0,
                 total_count=0, total_count_change=0, last_policy_id=0):
        self.current_count = current_count
        self.current_count_change = current_count_change
        self.total_count = total_count
        self.total_count_change = total_count_change
        self.last_policy_id = last_policy_id


# ===================================================================
# Layer 1: Pure Logic Tests (no DDS)
# ===================================================================

class TestConstants(unittest.TestCase):
    """Verify IDL-derived constants match expected values."""

    def test_action_values(self):
        self.assertEqual(ACTION_CREATE, 0)
        self.assertEqual(ACTION_GET, 1)
        self.assertEqual(ACTION_UPDATE, 2)
        self.assertEqual(ACTION_DELETE, 3)

    def test_retcode_values(self):
        self.assertEqual(RETCODE_OK, 0)
        self.assertEqual(RETCODE_ERROR, 1)

    def test_topic_names(self):
        self.assertEqual(COMMAND_REQUEST_TOPIC_NAME,
                         "rti/service/admin/command_request")
        self.assertEqual(COMMAND_REPLY_TOPIC_NAME,
                         "rti/service/admin/command_reply")

    def test_defaults(self):
        self.assertEqual(DEFAULT_DOMAIN_ID, 0)
        self.assertEqual(DEFAULT_SERVICE_NAME, "remote_admin")
        self.assertGreater(DEFAULT_REPLY_TIMEOUT_SEC, 0)


class TestActionName(unittest.TestCase):
    """Test the _action_name helper."""

    def test_known_actions(self):
        self.assertEqual(_action_name(ACTION_CREATE), "CREATE")
        self.assertEqual(_action_name(ACTION_GET), "GET")
        self.assertEqual(_action_name(ACTION_UPDATE), "UPDATE")
        self.assertEqual(_action_name(ACTION_DELETE), "DELETE")

    def test_unknown_action(self):
        self.assertEqual(_action_name(999), "UNKNOWN(999)")


class TestCLIParsing(unittest.TestCase):
    """Test CLI argument parsing via main()."""

    @patch("recording_service_control.RecordingServiceController")
    def test_pause_command(self, mock_cls):
        """CLI 'pause' creates controller and calls pause()."""
        mock_ctrl = MagicMock()
        mock_cls.return_value = mock_ctrl

        with patch("sys.argv", ["prog", "pause"]):
            result = main()

        mock_ctrl.pause.assert_called_once()
        mock_ctrl.close.assert_called_once()
        self.assertEqual(result, 0)

    @patch("recording_service_control.RecordingServiceController")
    def test_start_command(self, mock_cls):
        """CLI 'start' calls start()."""
        mock_ctrl = MagicMock()
        mock_cls.return_value = mock_ctrl

        with patch("sys.argv", ["prog", "start"]):
            main()

        mock_ctrl.start.assert_called_once()

    @patch("recording_service_control.RecordingServiceController")
    def test_shutdown_command(self, mock_cls):
        """CLI 'shutdown' calls shutdown()."""
        mock_ctrl = MagicMock()
        mock_cls.return_value = mock_ctrl

        with patch("sys.argv", ["prog", "shutdown"]):
            main()

        mock_ctrl.shutdown.assert_called_once()

    @patch("recording_service_control.RecordingServiceController")
    def test_tag_command(self, mock_cls):
        """CLI 'tag' with name and description calls tag_timestamp()."""
        mock_ctrl = MagicMock()
        mock_cls.return_value = mock_ctrl

        with patch("sys.argv",
                   ["prog", "tag", "my_tag", "-td", "A description"]):
            main()

        mock_ctrl.tag_timestamp.assert_called_once_with(
            "my_tag", "A description")

    @patch("recording_service_control.RecordingServiceController")
    def test_custom_domain_and_service(self, mock_cls):
        """CLI --domain-id and --service-name pass through."""
        mock_ctrl = MagicMock()
        mock_cls.return_value = mock_ctrl

        with patch("sys.argv",
                   ["prog", "pause", "-d", "42", "-s", "my_recorder"]):
            main()

        mock_cls.assert_called_once_with(
            domain_id=42, service_name="my_recorder")

    def test_tag_without_name_exits(self):
        """CLI 'tag' without a tag_name should exit with error."""
        with patch("sys.argv", ["prog", "tag"]):
            with self.assertRaises(SystemExit):
                main()

    @patch("recording_service_control.RecordingServiceController")
    def test_controller_exception_returns_1(self, mock_cls):
        """If controller raises, main() returns 1."""
        mock_cls.side_effect = RuntimeError("connection failed")

        with patch("sys.argv", ["prog", "pause"]):
            result = main()

        self.assertEqual(result, 1)


class TestResourcePaths(unittest.TestCase):
    """Test that command methods build correct resource identifiers."""

    def _controller_with_discovery_status(self, writer_match_count,
                                          reader_match_count):
        ctrl = object.__new__(RecordingServiceController)
        ctrl._domain_id = 42
        ctrl._service_name = "test_svc"
        ctrl._qos_file = "/tmp/DDS_QOS_PROFILES.xml"

        writer = MagicMock()
        writer.publication_matched_status = FakeStatus(
            current_count=writer_match_count, total_count=writer_match_count)
        writer.offered_incompatible_qos_status = FakeStatus(
            total_count=1, last_policy_id=7)

        reader = MagicMock()
        reader.subscription_matched_status = FakeStatus(
            current_count=reader_match_count, total_count=reader_match_count)
        reader.requested_incompatible_qos_status = FakeStatus(
            total_count=2, last_policy_id=11)

        ctrl._requester = MagicMock()
        ctrl._requester.request_datawriter = writer
        ctrl._requester.reply_datareader = reader
        return ctrl

    def test_request_writer_timeout_includes_discovery_diagnostics(self):
        """Writer-side discovery timeouts include actionable DDS status."""
        ctrl = self._controller_with_discovery_status(
            writer_match_count=0, reader_match_count=0)

        with patch("recording_service_control.time.time",
                   side_effect=[0, 999]):
            with self.assertRaises(TimeoutError) as ctx:
                ctrl._wait_for_match()

        msg = str(ctx.exception)
        self.assertIn("request writer", msg)
        self.assertIn("admin_domain_id: 42", msg)
        self.assertIn("service_name: test_svc", msg)
        self.assertIn(COMMAND_REQUEST_TOPIC_NAME, msg)
        self.assertIn("current_count=0", msg)
        self.assertIn("offered incompatible QoS", msg)
        self.assertIn("last_policy_id=7", msg)
        self.assertIn("admin domain ID mismatch", msg)

    def test_reply_reader_timeout_includes_discovery_diagnostics(self):
        """Reader-side discovery timeouts include matched and QoS status."""
        ctrl = self._controller_with_discovery_status(
            writer_match_count=1, reader_match_count=0)

        with patch("recording_service_control.time.time",
                   side_effect=[0, 999]):
            with self.assertRaises(TimeoutError) as ctx:
                ctrl._wait_for_match()

        msg = str(ctx.exception)
        self.assertIn("reply reader", msg)
        self.assertIn(COMMAND_REPLY_TOPIC_NAME, msg)
        self.assertIn("request writer publication matched: current_count=1", msg)
        self.assertIn("reply reader requested incompatible QoS", msg)
        self.assertIn("last_policy_id=11", msg)

    def test_send_command_targets_application_name(self):
        """CommandRequest includes application_name for service targeting."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "test_svc"
        ctrl._request_type = MagicMock()
        ctrl._wait_for_match = MagicMock()
        ctrl._requester = MagicMock()
        ctrl._requester.send_request.return_value = "request-id"
        ctrl._requester.wait_for_replies.return_value = True
        ctrl._requester.take_replies.return_value = []
        cmd = MagicMock()

        with patch("recording_service_control.dds.DynamicData",
                   return_value=cmd):
            ctrl._send_command(ACTION_UPDATE, "/resource", "body")

        cmd.__setitem__.assert_any_call("application_name", "test_svc")
        ctrl._requester.send_request.assert_called_once_with(cmd)

    def test_start_resource_uses_entity_state_octets(self):
        """start() should send serialized RUNNING state in octet_body."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "test_svc"
        ctrl._entity_state_type = "EntityStateType"
        ctrl._send_command = MagicMock(return_value={"retcode": 0})

        with patch("recording_service_control._serialize_entity_state",
                   return_value=[1, 2, 3]) as serialize:
            ctrl.start()

        serialize.assert_called_once_with(
            "EntityStateType", ENTITY_STATE_RUNNING)
        ctrl._send_command.assert_called_once_with(
            ACTION_UPDATE,
            "/recording_services/test_svc/state",
            "",
            octet_body=[1, 2, 3],
        )

    def test_pause_resource_uses_entity_state_octets(self):
        """pause() should send serialized PAUSED state in octet_body."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "test_svc"
        ctrl._entity_state_type = "EntityStateType"
        ctrl._send_command = MagicMock(return_value={"retcode": 0})

        with patch("recording_service_control._serialize_entity_state",
                   return_value=[4, 5, 6]) as serialize:
            ctrl.pause()

        serialize.assert_called_once_with(
            "EntityStateType", ENTITY_STATE_PAUSED)
        ctrl._send_command.assert_called_once_with(
            ACTION_UPDATE,
            "/recording_services/test_svc/state",
            "",
            octet_body=[4, 5, 6],
        )

    def test_entity_state_serialization(self):
        """EntityState octet_body is produced by DynamicData serialization."""
        state_data = MagicMock()
        state_data.to_cdr_buffer.return_value = b"\x00\x01\x02"

        with patch("recording_service_control.dds.DynamicData",
                   return_value=state_data) as dynamic_data:
            octets = _serialize_entity_state(
                "EntityStateType", ENTITY_STATE_PAUSED)

        dynamic_data.assert_called_once_with("EntityStateType")
        state_data.__setitem__.assert_called_once_with(
            "state", ENTITY_STATE_PAUSED)
        self.assertEqual(
            octets,
            [0, 1, 2],
        )

    def test_shutdown_resource(self):
        """shutdown() should use DELETE on /recording_services/<name>."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "my_recorder"
        ctrl._send_command = MagicMock(return_value={"retcode": 0})

        ctrl.shutdown()

        ctrl._send_command.assert_called_once_with(
            ACTION_DELETE,
            "/recording_services/my_recorder",
            "",
        )

    def test_tag_resource(self):
        """tag_timestamp() should use UPDATE on the sqlite:tag_timestamp resource."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "test_svc"
        ctrl._data_tag_type = MagicMock()
        ctrl._send_command = MagicMock(return_value={"retcode": 0})

        # Mock DynamicData construction
        mock_tag_data = MagicMock()
        mock_tag_data.to_cdr_buffer.return_value = b"\x00\x01\x02"
        with patch("recording_service_control.dds.DynamicData",
                   return_value=mock_tag_data):
            ctrl.tag_timestamp("marker_1", "test description")

        call_args = ctrl._send_command.call_args
        self.assertEqual(call_args[0][0], ACTION_UPDATE)
        self.assertIn("sqlite:tag_timestamp", call_args[0][1])
        self.assertIn("test_svc", call_args[0][1])
        self.assertIsNotNone(call_args[1].get("octet_body"))


# ===================================================================
# Layer 2: DDS Construction Tests (require rti.connextdds)
# ===================================================================

class TestDDSConstruction(unittest.TestCase):
    """
    Tests that create real DDS objects.
    Skipped if rti.connextdds or XML type files are unavailable.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import rti.connextdds  # noqa: F401
            import rti.request  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("rti.connextdds or rti.request not available")

        xml_types_dir = os.path.join(PARENT_DIR, "xml_types")
        if not os.path.isfile(
                os.path.join(xml_types_dir, "ServiceAdmin.xml")):
            raise unittest.SkipTest(
                "ServiceAdmin XML types not generated (run setup.sh)")

        qos_file = os.path.normpath(os.path.join(
            PARENT_DIR, "..", "..", "dds", "qos", "DDS_QOS_PROFILES.xml"))
        if not os.path.isfile(qos_file):
            raise unittest.SkipTest(
                f"QoS file not found: {qos_file}")

    def test_controller_creates_successfully(self):
        """RecordingServiceController initializes with DDS objects."""
        ctrl = RecordingServiceController(
            domain_id=97,  # High domain to avoid conflicts
            service_name="test_controller",
        )
        try:
            self.assertIsNotNone(ctrl._participant)
            self.assertIsNotNone(ctrl._requester)
            self.assertIsNotNone(ctrl._request_type)
            self.assertIsNotNone(ctrl._reply_type)
            self.assertIsNotNone(ctrl._data_tag_type)
        finally:
            ctrl.close()

    def test_close_is_idempotent(self):
        """Calling close() twice does not raise."""
        ctrl = RecordingServiceController(
            domain_id=96,
            service_name="test_close",
        )
        ctrl.close()
        ctrl.close()  # Should not raise

    def test_missing_xml_types_raises(self):
        """Passing a nonexistent xml_types_dir raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            RecordingServiceController(
                domain_id=95,
                xml_types_dir="/nonexistent/path",
            )


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
