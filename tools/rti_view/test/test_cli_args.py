#!/usr/bin/env python3
"""CLI argument tests for rti_view."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rti_view.__main__ import parse_args


class TestCliArgs(unittest.TestCase):
    def test_interactive_defaults(self):
        args = parse_args([])

        self.assertEqual(args.domain, 0)
        self.assertIsNone(args.topic)
        self.assertIsNone(args.field)
        self.assertEqual(args.mode, "text")

    def test_direct_view_args(self):
        args = parse_args(["-d", "7", "-t", "Telemetry", "-f", "position.x", "-m", "plot"])

        self.assertEqual(args.domain, 7)
        self.assertEqual(args.topic, "Telemetry")
        self.assertEqual(args.field, "position.x")
        self.assertEqual(args.mode, "plot")

    def test_topic_requires_field(self):
        with self.assertRaises(SystemExit):
            parse_args(["-t", "Telemetry"])

    def test_field_requires_topic(self):
        with self.assertRaises(SystemExit):
            parse_args(["-f", "position.x"])


if __name__ == "__main__":
    unittest.main()
