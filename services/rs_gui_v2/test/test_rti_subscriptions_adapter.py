#!/usr/bin/env python3
"""Fake-Connext tests for the rs_gui_v2 RTI subscription adapter."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import SubscriptionStatus, TopicSubscriptionRequest
from app_core.rti_subscriptions import (
    RtiSubscriptionClient,
    envelope_from_dynamic_sample,
    sample_info_snapshot,
)
from app_core.rti_types import DynamicTypeLookup
from app_core.types import TypeResolution


class FakeDynamicType:
    def __init__(self, name="TelemetryType"):
        self.name = name


class FakeTypeRegistry:
    def __init__(self, lookups=None):
        self.lookups = lookups or {}
        self.requested = []

    def lookup(self, type_name):
        self.requested.append(type_name)
        lookup = self.lookups.get(type_name)
        if lookup is not None:
            return lookup
        return DynamicTypeLookup(
            resolution=TypeResolution(type_name=type_name, status="available", candidates=(type_name,)),
            dynamic_type=FakeDynamicType(type_name),
        )


class FakeTimestamp:
    def __init__(self, sec, nanosec=0):
        self.sec = sec
        self.nanosec = nanosec


class FakeInfo:
    def __init__(self, valid=True):
        self.valid = valid
        self.source_timestamp = FakeTimestamp(10, 500000000)
        self.reception_timestamp = 11.25
        self.instance_state = "ALIVE"
        self.view_state = "NEW"
        self.sample_state = "NOT_READ"
        self.sample_rank = 3


class FakeReader:
    def __init__(self):
        self.samples = []
        self.closed = False

    def take(self):
        samples = list(self.samples)
        self.samples.clear()
        return samples

    def close(self):
        self.closed = True


class FakeParticipant:
    def __init__(self):
        self.close_contained_entities_called = False
        self.closed = False

    def close_contained_entities(self):
        self.close_contained_entities_called = True

    def close(self):
        self.closed = True


class FakeDynamicDataModule:
    def __init__(self):
        self.topics = []
        self.readers = []

    def Topic(self, participant, topic_name, dynamic_type):
        topic = {"participant": participant, "name": topic_name, "type": dynamic_type}
        self.topics.append(topic)
        return topic

    def DataReader(self, participant, topic):
        reader = FakeReader()
        self.readers.append({"participant": participant, "topic": topic, "reader": reader})
        return reader


class FakeDdsModule:
    def __init__(self):
        self.DynamicData = FakeDynamicDataModule()
        self.participants = []

    def DomainParticipant(self, domain_id):
        participant = FakeParticipant()
        participant.domain_id = domain_id
        self.participants.append(participant)
        return participant


class TestSampleMapping(unittest.TestCase):
    def test_sample_info_snapshot_normalizes_timestamps_and_states(self):
        snapshot = sample_info_snapshot(FakeInfo(valid=True))

        self.assertTrue(snapshot.valid)
        self.assertEqual(snapshot.source_timestamp, 10.5)
        self.assertEqual(snapshot.reception_timestamp, 11.25)
        self.assertEqual(snapshot.instance_state, "ALIVE")
        self.assertEqual(snapshot.rank, 3)

    def test_envelope_maps_valid_and_invalid_samples(self):
        request = TopicSubscriptionRequest(4, "Telemetry", "TelemetryType")

        valid = envelope_from_dynamic_sample(request, ({"x": 1}, FakeInfo(True)))
        invalid = envelope_from_dynamic_sample(request, ({"x": 2}, FakeInfo(False)))

        self.assertEqual(valid.data, {"x": 1})
        self.assertTrue(valid.valid)
        self.assertIsNone(invalid.data)
        self.assertFalse(invalid.valid)


class TestRtiSubscriptionClient(unittest.IsolatedAsyncioTestCase):
    async def test_subscribe_creates_participant_topic_and_reader(self):
        dds = FakeDdsModule()
        registry = FakeTypeRegistry()
        client = RtiSubscriptionClient(type_registry=registry, dds_module=dds)
        request = TopicSubscriptionRequest(5, "Telemetry", "TelemetryType")

        state = await client.subscribe(request)

        self.assertEqual(state.status, SubscriptionStatus.READER_CREATED)
        self.assertEqual(registry.requested, ["TelemetryType"])
        self.assertEqual(dds.participants[0].domain_id, 5)
        self.assertEqual(dds.DynamicData.topics[0]["name"], "Telemetry")
        self.assertEqual(dds.DynamicData.topics[0]["type"].name, "TelemetryType")
        self.assertEqual(len(dds.DynamicData.readers), 1)

    async def test_unresolved_type_returns_state_without_creating_reader(self):
        dds = FakeDdsModule()
        registry = FakeTypeRegistry({
            "MissingType": DynamicTypeLookup(
                resolution=TypeResolution(
                    type_name="MissingType",
                    status="missing",
                    message="not in catalog",
                ),
            )
        })
        client = RtiSubscriptionClient(type_registry=registry, dds_module=dds)
        request = TopicSubscriptionRequest(5, "Telemetry", "MissingType")

        state = await client.subscribe(request)
        samples = await client.take_available(request)

        self.assertEqual(state.status, SubscriptionStatus.UNRESOLVED_TYPE)
        self.assertEqual(state.message, "not in catalog")
        self.assertEqual(samples, ())
        self.assertEqual(dds.participants, [])

    async def test_take_available_returns_samples_and_updates_state(self):
        dds = FakeDdsModule()
        client = RtiSubscriptionClient(type_registry=FakeTypeRegistry(), dds_module=dds)
        request = TopicSubscriptionRequest(5, "Telemetry", "TelemetryType")
        await client.subscribe(request)
        reader = dds.DynamicData.readers[0]["reader"]
        reader.samples.extend([
            ({"x": 1}, FakeInfo(True)),
            ({"x": 2}, FakeInfo(False)),
        ])

        samples = await client.take_available(request)

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].data, {"x": 1})
        self.assertIsNone(samples[1].data)
        session = client._sessions[request.key]
        self.assertEqual(session.state.status, SubscriptionStatus.RECEIVING)
        self.assertEqual(session.state.received_samples, 1)
        self.assertEqual(session.state.invalid_samples, 1)

    async def test_unsubscribe_and_close_release_participants(self):
        dds = FakeDdsModule()
        client = RtiSubscriptionClient(type_registry=FakeTypeRegistry(), dds_module=dds)
        first = TopicSubscriptionRequest(5, "Telemetry", "TelemetryType")
        second = TopicSubscriptionRequest(6, "Command", "CommandType")

        await client.subscribe(first)
        await client.subscribe(second)
        first_state = await client.unsubscribe(first)
        await client.close()

        self.assertEqual(first_state.status, SubscriptionStatus.STOPPED)
        self.assertTrue(dds.DynamicData.readers[0]["reader"].closed)
        self.assertTrue(dds.participants[0].close_contained_entities_called)
        self.assertTrue(dds.participants[0].closed)
        self.assertTrue(dds.DynamicData.readers[1]["reader"].closed)
        self.assertTrue(dds.participants[1].closed)


if __name__ == "__main__":
    unittest.main()