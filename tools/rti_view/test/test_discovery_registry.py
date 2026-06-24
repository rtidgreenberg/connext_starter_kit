#!/usr/bin/env python3
"""Discovery registry tests for rti_view."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

import rti.connextdds as dds

from rti_view.discovery import (
    configure_type_lookup_qos,
    DiscoveredEndpoint,
    DiscoveryRegistry,
    endpoint_from_builtin_data,
    participant_from_builtin_data,
)
from fakes import FakeEndpointData, FakeParticipantData


class TestDiscoveryRegistry(unittest.TestCase):
    def test_participant_label_uses_name(self):
        participant = participant_from_builtin_data(FakeParticipantData(name="SensorPublisher"), observed_at=1.0)

        self.assertEqual(participant.key, "(1, 2, 3, 4)")
        self.assertEqual(participant.label, "SensorPublisher")
        self.assertEqual(participant.ip, "127.0.0.1")

    def test_endpoint_grouping_by_participant_and_topic(self):
        registry = DiscoveryRegistry()
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="Telemetry",
            dynamic_type=object(),
            kind="Writer",
        ))
        registry.add_endpoint(DiscoveredEndpoint(
            key="reader-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="Telemetry",
            kind="Reader",
        ))
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-2",
            participant_key="participant-2",
            topic_name="Other",
            type_name="Other",
            dynamic_type=object(),
            kind="Writer",
        ))

        self.assertEqual([ep.key for ep in registry.writers_for_participant("participant-1")], ["writer-1"])
        self.assertEqual([ep.key for ep in registry.writers_for_topic("Telemetry")], ["writer-1"])
        self.assertEqual(registry.topics_for_participant("participant-1"), ("Telemetry",))

    def test_direct_topic_selection_diagnoses_multiple_writers(self):
        registry = DiscoveryRegistry()
        registry.add_endpoint(DiscoveredEndpoint("a", "Telemetry", "Telemetry", None, "Writer", "p1"))
        registry.add_endpoint(DiscoveredEndpoint("b", "Telemetry", "Telemetry", object(), "Writer", "p2"))

        endpoint, diagnostics = registry.select_writer_for_topic("Telemetry")

        self.assertEqual(endpoint.key, "b")
        self.assertEqual([diag.code for diag in diagnostics], ["multiple_writers"])

    def test_endpoint_update_preserves_resolved_type(self):
        registry = DiscoveryRegistry()
        dynamic_type = object()
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=dynamic_type,
            kind="Writer",
            observed_at=1.0,
        ))
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=None,
            kind="Writer",
            observed_at=2.0,
        ))

        endpoint = registry.writers_for_topic("Telemetry")[0]

        self.assertIs(endpoint.dynamic_type, dynamic_type)
        self.assertEqual(endpoint.observed_at, 2.0)

    def test_writer_by_topic_for_participant_prefers_resolved_type(self):
        registry = DiscoveryRegistry()
        typed = object()
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=None,
            kind="Writer",
            observed_at=3.0,
        ))
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-b",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=typed,
            kind="Writer",
            observed_at=1.0,
        ))

        by_topic = registry.writer_by_topic_for_participant("participant-1")

        self.assertEqual(by_topic["Telemetry"].key, "writer-b")
        self.assertIs(by_topic["Telemetry"].dynamic_type, typed)

    def test_builtin_endpoint_conversion(self):
        data = FakeEndpointData((10, 20), (1, 2), dynamic_type=object())

        endpoint = endpoint_from_builtin_data(data, "Writer", observed_at=2.0)

        self.assertEqual(endpoint.key, "(10, 20)")
        self.assertEqual(endpoint.participant_key, "(1, 2)")
        self.assertTrue(endpoint.type_available)
        self.assertTrue(any(line.startswith("type_name=") for line in endpoint.type_debug))

    def test_byte_participant_key_conversion(self):
        key_bytes = b"\x88\xa6\x01\x01{\xb77\xb3\xc2\x19\"\x9c\xc1\x01\x00\x00"
        participant = participant_from_builtin_data(FakeParticipantData(key=key_bytes), observed_at=1.0)

        self.assertEqual(participant.key, "88a601017bb737b3c219229cc1010000")
        self.assertEqual(participant.rtps_host_id, int.from_bytes(key_bytes[0:4], byteorder="big"))
        self.assertEqual(participant.rtps_app_id, int.from_bytes(key_bytes[4:8], byteorder="big"))

    def test_byte_endpoint_participant_key_matches_participant_key(self):
        participant_key = b"\x88\xa6\x01\x01{\xb77\xb3\xc2\x19\"\x9c\xc1\x01\x00\x00"
        endpoint_key = b"\x88\xa6\x01\x01{\xb77\xb3\xc2\x19\"\x9c\xc2\x01\x00\x00"
        participant = participant_from_builtin_data(FakeParticipantData(key=participant_key), observed_at=1.0)
        endpoint = endpoint_from_builtin_data(FakeEndpointData(endpoint_key, participant_key), "Writer", observed_at=1.0)

        self.assertEqual(endpoint.participant_key, participant.key)
        self.assertEqual(endpoint.key, "88a601017bb737b3c219229cc2010000")

    def test_type_lookup_qos_is_enabled_when_supported(self):
        qos = dds.DomainParticipantQos()

        configured = configure_type_lookup_qos(qos)

        self.assertTrue(configured)
        self.assertEqual(
            str(qos.discovery_config.enabled_builtin_channels),
            str(dds.DiscoveryConfigBuiltinChannelKindMask.ALL),
        )
        self.assertEqual(qos.discovery_config.endpoint_type_object_lb_serialization_threshold, -1)


if __name__ == "__main__":
    unittest.main()
