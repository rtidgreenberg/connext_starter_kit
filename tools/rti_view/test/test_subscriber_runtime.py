#!/usr/bin/env python3
"""Subscriber runtime tests for rti_view."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

from rti_view.discovery import DiscoveredEndpoint
from rti_view.subscriber import FieldSampleBuffer, find_field, pump_reader_once, setup_matched_reader
from fakes import FakeDynamicType, FakeInfo, FakeMember, FakeReader


class TestSubscriberRuntime(unittest.TestCase):
    def test_buffer_keeps_bounded_messages_and_numeric_points(self):
        buffer = FieldSampleBuffer(max_messages=2, max_points=2)

        buffer.append(1.0, 10)
        buffer.append(2.0, "text")
        buffer.append(3.0, 12.5)

        self.assertEqual([row.value for row in buffer.messages], ["text", 12.5])
        self.assertEqual([point.value for point in buffer.points], [10.0, 12.5])
        self.assertEqual(buffer.skipped_non_numeric, 1)

    def test_pump_reader_once_accepts_valid_samples(self):
        reader = FakeReader([
            ({"x": 1.5}, FakeInfo(valid=True)),
            ({"x": 2.5}, FakeInfo(valid=True)),
            ({"x": 9.0}, FakeInfo(valid=False)),
        ])
        buffer = FieldSampleBuffer()

        accepted = pump_reader_once(reader, "x", buffer, clock=lambda: 100.0)

        self.assertEqual(accepted, 2)
        self.assertEqual([row.value for row in buffer.messages], [1.5, 2.5])
        self.assertEqual(buffer.skipped_invalid, 1)

    def test_missing_dynamic_type_returns_diagnostic(self):
        endpoint = DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="Telemetry",
            dynamic_type=None,
            kind="Writer",
        )

        result = setup_matched_reader(participant=object(), endpoint=endpoint)

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostic.code, "type_unavailable")

    def test_find_field_returns_descriptor(self):
        data_type = FakeDynamicType("STRUCTURE_TYPE", "Telemetry", (
            FakeMember("temperature", FakeDynamicType("FLOAT_64_TYPE")),
            FakeMember("status", FakeDynamicType("STRING_TYPE")),
        ))
        endpoint = DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="Telemetry",
            dynamic_type=data_type,
            kind="Writer",
        )

        temperature = find_field(endpoint, "temperature")
        status = find_field(endpoint, "status")

        self.assertTrue(temperature.plottable)
        self.assertFalse(status.plottable)
        self.assertIsNone(find_field(endpoint, "missing"))


if __name__ == "__main__":
    unittest.main()
