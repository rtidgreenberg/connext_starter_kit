#!/usr/bin/env python3
"""CLI argument tests for rti_view."""

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rti_view.__main__ import parse_args
import rti_view.__main__ as main_module


class TestCliArgs(unittest.TestCase):
    def test_interactive_defaults(self):
        args = parse_args([])

        self.assertEqual(args.domain, 0)
        self.assertIsNone(args.topic)
        self.assertIsNone(args.field)
        self.assertEqual(args.mode, "text")

    def test_direct_view_args(self):
        args = parse_args(["-d", "7", "-t", "Telemetry", "-f", "position.x", "-m", "plot", "--direct-view"])

        self.assertEqual(args.domain, 7)
        self.assertEqual(args.topic, "Telemetry")
        self.assertEqual(args.field, "position.x")
        self.assertEqual(args.mode, "plot")
        self.assertTrue(args.direct_view)

    def test_topic_requires_field(self):
        with self.assertRaises(SystemExit):
            parse_args(["-t", "Telemetry"])

    def test_field_requires_topic(self):
        with self.assertRaises(SystemExit):
            parse_args(["-f", "position.x"])

    def test_direct_view_requires_topic_and_field(self):
        with self.assertRaises(SystemExit):
            parse_args(["--direct-view"])

    def test_main_routes_direct_args_into_shell_view(self):
        args = parse_args(["-d", "7", "-t", "Telemetry", "-f", "position.x", "-m", "plot", "--history", "45"])

        with patch.object(main_module, "parse_args", return_value=args), \
             patch("rti_view.views.main_window.run_interactive") as run_interactive:
            main_module.main()

        run_interactive.assert_called_once_with(
            domain_id=7,
            topic_name="Telemetry",
            field_path="position.x",
            mode="plot",
            history_seconds=45,
        )

    def test_main_routes_direct_view_args_into_direct_runner(self):
        args = parse_args([
            "-d", "7", "-t", "Telemetry", "-f", "position.x", "-m", "plot",
            "--history", "45", "--timeout", "12", "--direct-view",
        ])

        with patch.object(main_module, "parse_args", return_value=args), \
             patch("rti_view.subscriber.run_direct_view") as run_direct_view:
            main_module.main()

        run_direct_view.assert_called_once_with(
            domain_id=7,
            topic_name="Telemetry",
            field_path="position.x",
            mode="plot",
            history_seconds=45,
            timeout=12.0,
        )


if __name__ == "__main__":
    unittest.main()
