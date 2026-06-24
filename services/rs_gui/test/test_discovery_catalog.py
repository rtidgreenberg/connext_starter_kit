#!/usr/bin/env python3
"""Pure unit tests for rs_gui topic discovery and selection models."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    DiscoveredEndpoint,
    EndpointDirection,
    FakeTopicDiscoveryClient,
    TopicDiscoveryFacade,
    TopicDiscoveryState,
    TopicSelection,
    TopicSelectionState,
    TypeAvailabilityStatus,
    TypeCatalog,
    TypeResolution,
)
from app_core.types import type_sources_from_xml_text


class TestTypeCatalog(unittest.TestCase):
    def test_type_catalog_resolves_exact_missing_and_ambiguous_names(self):
        catalog = TypeCatalog()
        catalog.register_type("Telemetry", source="fixture.xml")
        catalog.register_type("vehicle::Pose", source="pose_a.xml")
        catalog.register_type("robot::Pose", source="pose_b.xml")

        self.assertTrue(catalog.resolve("Telemetry").available)
        self.assertEqual(catalog.resolve("Missing").status, TypeAvailabilityStatus.MISSING)

        ambiguous = catalog.resolve("Pose")
        self.assertEqual(ambiguous.status, TypeAvailabilityStatus.AMBIGUOUS)
        self.assertEqual(ambiguous.candidates, ("vehicle::Pose", "robot::Pose"))
        self.assertEqual(TypeCatalog.from_dict(catalog.to_dict()).resolve("Telemetry").source,
                         "fixture.xml")

    def test_type_resolution_round_trips(self):
        resolution = TypeResolution(
            type_name="Telemetry",
            status="available",
            source="fixture.xml",
            candidates=["Telemetry"],
            message="loaded",
        )

        self.assertEqual(TypeResolution.from_dict(resolution.to_dict()), resolution)

        def test_xml_type_sources_are_parsed_with_module_names(self):
                xml_text = """
                <dds>
                    <types>
                        <module name="RTI">
                            <module name="Demo">
                                <struct name="Pose"/>
                                <enum name="Mode"/>
                                <typedef name="Alias" type="int32"/>
                            </module>
                        </module>
                    </types>
                </dds>
                """

                sources = type_sources_from_xml_text(xml_text, source="fixture.xml")
                catalog = TypeCatalog()
                for source in sources:
                        catalog.register_source(source)

                self.assertEqual(
                        [(source.type_name, source.kind) for source in sources],
                        [
                                ("RTI::Demo::Pose", "struct"),
                                ("RTI::Demo::Mode", "enum"),
                                ("RTI::Demo::Alias", "typedef"),
                        ],
                )
                resolved = catalog.resolve("Pose")
                self.assertTrue(resolved.available)
                self.assertEqual(resolved.resolved_type_name, "RTI::Demo::Pose")
                self.assertEqual(resolved.source, "fixture.xml")


class TestTopicInventory(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_groups_endpoints_and_hides_internal_topics(self):
        catalog = TypeCatalog()
        catalog.register_type("Telemetry", source="fixture.xml")
        client = FakeTopicDiscoveryClient(type_catalog=catalog)
        client.apply(DiscoveredEndpoint(
            domain_id=7,
            topic_name="TelemetryTopic",
            type_name="Telemetry",
            direction=EndpointDirection.WRITER,
            endpoint_key="writer-1",
            partitions=("alpha",),
        ))
        client.apply(DiscoveredEndpoint(
            domain_id=7,
            topic_name="TelemetryTopic",
            type_name="Telemetry",
            direction=EndpointDirection.READER,
            endpoint_key="reader-1",
            partitions=("beta",),
        ))
        client.apply(DiscoveredEndpoint(
            domain_id=7,
            topic_name="rti/service/monitoring/periodic",
            type_name="RTI::Service::Monitoring::Periodic",
            direction=EndpointDirection.WRITER,
            endpoint_key="writer-internal",
        ))
        facade = TopicDiscoveryFacade(client)

        visible = await facade.scan(7)
        with_internal = await facade.scan(7, include_internal=True)

        self.assertEqual([topic.topic_name for topic in visible], ["TelemetryTopic"])
        self.assertEqual(visible[0].writer_count, 1)
        self.assertEqual(visible[0].reader_count, 1)
        self.assertEqual(visible[0].partitions, ("alpha", "beta"))
        self.assertEqual(visible[0].state, TopicDiscoveryState.TYPE_AVAILABLE)
        self.assertEqual([topic.topic_name for topic in with_internal], [
            "TelemetryTopic",
            "rti/service/monitoring/periodic",
        ])
        self.assertEqual(client.scans, [(7, False), (7, True)])

    async def test_participant_invalid_sample_removes_owned_endpoints(self):
        client = FakeTopicDiscoveryClient()
        client.apply(DiscoveredEndpoint(
            domain_id=47,
            topic_name="TelemetryTopic",
            type_name="Telemetry",
            direction=EndpointDirection.WRITER,
            endpoint_key="writer-1",
            participant_key="9:9:9",
        ))

        first = await client.scan(47)
        client.inventory.remove_participant("9:9:9", domain_id=47)
        second = await client.scan(47)

        self.assertEqual([topic.topic_name for topic in first], ["TelemetryTopic"])
        self.assertEqual(second, ())

    async def test_inventory_can_prune_stale_endpoints_by_domain(self):
        client = FakeTopicDiscoveryClient()
        client.apply(DiscoveredEndpoint(
            domain_id=47,
            topic_name="OldTopic",
            type_name="Telemetry",
            direction=EndpointDirection.WRITER,
            endpoint_key="old-writer",
            observed_at=10.0,
        ))
        client.apply(DiscoveredEndpoint(
            domain_id=48,
            topic_name="OtherDomainTopic",
            type_name="Telemetry",
            direction=EndpointDirection.WRITER,
            endpoint_key="other-writer",
            observed_at=10.0,
        ))

        removed = client.inventory.remove_stale(now=20.0, max_age_sec=5.0, domain_id=47)

        self.assertEqual(removed, 1)
        self.assertEqual(await client.scan(47), ())
        self.assertEqual([topic.topic_name for topic in await client.scan(48)], ["OtherDomainTopic"])

    async def test_inventory_reports_unresolved_and_ambiguous_topics(self):
        client = FakeTopicDiscoveryClient()
        client.apply(DiscoveredEndpoint(
            domain_id=8,
            topic_name="UnknownTopic",
            type_name="UnknownType",
            direction="writer",
            endpoint_key="writer-1",
        ))
        client.apply(DiscoveredEndpoint(
            domain_id=8,
            topic_name="MixedTopic",
            type_name="TypeA",
            direction="writer",
            endpoint_key="writer-2",
        ))
        client.apply(DiscoveredEndpoint(
            domain_id=8,
            topic_name="MixedTopic",
            type_name="TypeB",
            direction="reader",
            endpoint_key="reader-2",
        ))
        facade = TopicDiscoveryFacade(client)

        topics = {topic.topic_name: topic for topic in await facade.scan(8)}

        self.assertEqual(topics["UnknownTopic"].state, TopicDiscoveryState.UNRESOLVED)
        self.assertEqual(topics["MixedTopic"].state, TopicDiscoveryState.AMBIGUOUS)

    async def test_facade_yields_topics_from_fake_client(self):
        client = FakeTopicDiscoveryClient()
        client.apply(DiscoveredEndpoint(
            domain_id=9,
            topic_name="Pose",
            type_name="PoseType",
            direction="writer",
            endpoint_key="writer-1",
            type_available=True,
        ))
        facade = TopicDiscoveryFacade(client)

        observed = []
        async for topic in facade.topics(9):
            observed.append(topic)

        self.assertEqual([topic.topic_name for topic in observed], ["Pose"])
        self.assertEqual(observed[0].state, TopicDiscoveryState.TYPE_AVAILABLE)


class TestTopicSelectionState(unittest.TestCase):
    def test_selection_state_persists_selected_and_plot_fields(self):
        state = TopicSelectionState(include_internal=True)
        selection = TopicSelection(
            domain_id=3,
            topic_name="TelemetryTopic",
            type_name="Telemetry",
            selected_fields=["position.x", "position.y"],
            plot_fields=["position.x"],
            created_at=10.0,
            updated_at=11.0,
        )

        selected = state.select(selection)
        restored = TopicSelectionState.from_dict(selected.to_dict())
        deselected = restored.deselect(3, "TelemetryTopic")

        self.assertIsNone(state.selected_for(3, "TelemetryTopic"))
        self.assertEqual(restored.selected_for(3, "TelemetryTopic"), selection)
        self.assertEqual(restored.selected_for(3, "TelemetryTopic").plot_fields,
                         ("position.x",))
        self.assertTrue(restored.include_internal)
        self.assertIsNone(deselected.selected_for(3, "TelemetryTopic"))


if __name__ == "__main__":
    unittest.main()