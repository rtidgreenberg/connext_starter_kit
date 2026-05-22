#!/usr/bin/env python3
"""Fake-Connext tests for the rs_gui_v2 RTI discovery adapter."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import TopicDiscoveryState, TypeCatalog
from app_core.discovery import EndpointDirection
from app_core.rti_discovery import RtiTopicDiscoveryClient, endpoint_from_builtin_sample


class FakeInfo:
    def __init__(self, valid=True):
        self.valid = valid


class FakeKey:
    def __init__(self, value):
        self.value = value


class FakePartition:
    def __init__(self, name=()):
        self.name = tuple(name)


class FakeQosPolicy:
    def __init__(self, kind):
        self.kind = kind


class FakeBuiltinData:
    def __init__(
            self,
            topic_name="TelemetryTopic",
            type_name="Telemetry",
            key=(1, 2, 3),
            participant_key=(4, 5, 6),
            partition=(),
            type_object=None,
    ):
        self.topic_name = topic_name
        self.type_name = type_name
        self.key = FakeKey(key)
        self.participant_key = FakeKey(participant_key)
        self.partition = FakePartition(partition)
        self.type = type_object
        self.reliability = FakeQosPolicy("RELIABLE")
        self.durability = FakeQosPolicy("VOLATILE")


class FakeReader:
    def __init__(self, samples=()):
        self.samples = list(samples)

    def take(self):
        samples = list(self.samples)
        self.samples.clear()
        return samples


class FakeParticipant:
    def __init__(self, publication_samples=(), subscription_samples=()):
        self.publication_reader = FakeReader(publication_samples)
        self.subscription_reader = FakeReader(subscription_samples)
        self.close_contained_entities_called = False
        self.closed = False

    def close_contained_entities(self):
        self.close_contained_entities_called = True

    def close(self):
        self.closed = True


class FakeDdsModule:
    def __init__(self, participants):
        self.participants = participants
        self.created_domains = []

    def DomainParticipant(self, domain_id):
        self.created_domains.append(domain_id)
        return self.participants[domain_id]


class TestRtiDiscoverySampleMapping(unittest.TestCase):
    def test_endpoint_from_builtin_sample_normalizes_metadata(self):
        sample = (
            FakeBuiltinData(
                topic_name="TelemetryTopic",
                type_name="Telemetry",
                key=(10, 20, 30),
                participant_key=(1, 2, 3),
                partition=("alpha", "beta"),
                type_object=object(),
            ),
            FakeInfo(valid=True),
        )

        endpoint = endpoint_from_builtin_sample(11, EndpointDirection.WRITER, sample)

        self.assertEqual(endpoint.domain_id, 11)
        self.assertEqual(endpoint.topic_name, "TelemetryTopic")
        self.assertEqual(endpoint.type_name, "Telemetry")
        self.assertEqual(endpoint.endpoint_key, "10:20:30")
        self.assertEqual(endpoint.participant_key, "1:2:3")
        self.assertEqual(endpoint.partitions, ("alpha", "beta"))
        self.assertTrue(endpoint.type_available)
        self.assertEqual(endpoint.qos["reliability"], "RELIABLE")

    def test_invalid_sample_without_key_is_ignored(self):
        endpoint = endpoint_from_builtin_sample(11, EndpointDirection.WRITER, (None, FakeInfo(False)))

        self.assertIsNone(endpoint)


class TestRtiTopicDiscoveryClient(unittest.IsolatedAsyncioTestCase):
    async def test_scan_creates_participant_and_reads_publications_and_subscriptions(self):
        catalog = TypeCatalog()
        catalog.register_type("Command", source="commands.xml")
        participant = FakeParticipant(
            publication_samples=[(
                FakeBuiltinData(
                    topic_name="TelemetryTopic",
                    type_name="Telemetry",
                    key=(1,),
                    type_object=object(),
                ),
                FakeInfo(True),
            ), (
                FakeBuiltinData(
                    topic_name="rti/service/admin/command_request",
                    type_name="RTI::Service::Admin::CommandRequest",
                    key=(2,),
                ),
                FakeInfo(True),
            )],
            subscription_samples=[(
                FakeBuiltinData(
                    topic_name="CommandTopic",
                    type_name="Command",
                    key=(3,),
                    partition=("ops",),
                ),
                FakeInfo(True),
            )],
        )
        dds = FakeDdsModule({42: participant})
        client = RtiTopicDiscoveryClient(type_catalog=catalog, dds_module=dds)

        visible = await client.scan(42)
        with_internal = await client.scan(42, include_internal=True)

        self.assertEqual(dds.created_domains, [42])
        self.assertEqual([topic.topic_name for topic in visible], [
            "CommandTopic",
            "TelemetryTopic",
        ])
        self.assertEqual(visible[0].state, TopicDiscoveryState.TYPE_AVAILABLE)
        self.assertEqual(visible[0].reader_count, 1)
        self.assertEqual(visible[0].partitions, ("ops",))
        self.assertEqual(visible[1].writer_count, 1)
        self.assertEqual(visible[1].state, TopicDiscoveryState.TYPE_AVAILABLE)
        self.assertEqual([topic.topic_name for topic in with_internal], [
            "CommandTopic",
            "TelemetryTopic",
            "rti/service/admin/command_request",
        ])

    async def test_invalid_sample_removes_endpoint_from_inventory(self):
        participant = FakeParticipant(
            publication_samples=[(
                FakeBuiltinData(topic_name="TelemetryTopic", type_name="Telemetry", key=(1,)),
                FakeInfo(True),
            )],
        )
        client = RtiTopicDiscoveryClient(dds_module=FakeDdsModule({43: participant}))

        first = await client.scan(43)
        participant.publication_reader.samples.append((
            FakeBuiltinData(topic_name="TelemetryTopic", type_name="Telemetry", key=(1,)),
            FakeInfo(False),
        ))
        second = await client.scan(43)

        self.assertEqual([topic.topic_name for topic in first], ["TelemetryTopic"])
        self.assertEqual(second, ())

    async def test_topics_yields_current_scan_results_once_with_fake_client(self):
        participant = FakeParticipant(
            publication_samples=[(
                FakeBuiltinData(topic_name="TelemetryTopic", type_name="Telemetry", key=(1,)),
                FakeInfo(True),
            )],
        )
        client = RtiTopicDiscoveryClient(dds_module=FakeDdsModule({44: participant}))

        observed = []
        async for topic in client.topics(44):
            observed.append(topic)
            break

        self.assertEqual([topic.topic_name for topic in observed], ["TelemetryTopic"])

    async def test_close_releases_participants(self):
        participant = FakeParticipant()
        client = RtiTopicDiscoveryClient(dds_module=FakeDdsModule({45: participant}))

        await client.scan(45)
        await client.close()

        self.assertTrue(participant.close_contained_entities_called)
        self.assertTrue(participant.closed)


if __name__ == "__main__":
    unittest.main()