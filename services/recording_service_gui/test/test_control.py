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
    _action_name,
    RecordingServiceController,
    main,
)


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

    def test_start_resource(self):
        """start() should use UPDATE on /recording_services/<name>/state."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "test_svc"
        ctrl._send_command = MagicMock(return_value={"retcode": 0})

        ctrl._send_state_command("running")

        ctrl._send_command.assert_called_once_with(
            ACTION_UPDATE,
            "/recording_services/test_svc/state",
            "running",
        )

    def test_pause_resource(self):
        """pause() should send 'paused' state."""
        ctrl = object.__new__(RecordingServiceController)
        ctrl._service_name = "test_svc"
        ctrl._send_state_command = MagicMock()

        ctrl.pause()

        ctrl._send_state_command.assert_called_once_with("paused")

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
