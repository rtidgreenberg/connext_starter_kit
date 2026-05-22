#!/usr/bin/env python3
"""Headless tests for Topics-tab controller discovery wiring."""

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
    FieldCatalog,
    FieldDescriptor,
    SampleEnvelope,
    SubscriptionStatus,
    TopicDiscoveryFacade,
    TopicSelection,
    TopicSelectionState,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
    TypeCatalog,
)
from gui import TopicsTabController, TopicsTabControllerConfig


class FailingDiscoveryClient:
    async def scan(self, domain_id: int, include_internal: bool = False):
        raise RuntimeError(f"scan failed for domain {domain_id}")

    async def topics(self, domain_id: int, include_internal: bool = False):
        return
        yield


class TestTopicsTabController(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_scans_discovery_facade_and_builds_topic_rows(self):
        client = _fake_discovery_client()
        facade = TopicDiscoveryFacade(client, selections=TopicSelectionState().select(TopicSelection(
            domain_id=7,
            topic_name="RobotTelemetry",
            type_name="Robot::Telemetry",
            selected_fields=("pose.x",),
        )))
        request = TopicSubscriptionRequest(7, "RobotTelemetry", "Robot::Telemetry")
        controller = TopicsTabController(
            discovery_facade=facade,
            field_catalogs={"Robot::Telemetry": FieldCatalog(
                type_name="Robot::Telemetry",
                fields=(FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),),
            )},
            subscription_states=(TopicSubscriptionState(
                request=request,
                status=SubscriptionStatus.RECEIVING,
                received_samples=5,
            ),),
            samples=(SampleEnvelope(
                subscription_key=request.key,
                domain_id=7,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                data={"pose": {"x": 4.25}},
            ),),
            config=TopicsTabControllerConfig(domain_id=7),
            clock=lambda: 50.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(client.scans, [(7, False)])
        self.assertEqual(view.selected_topic.topic_name, "RobotTelemetry")
        self.assertEqual(view.selected_topic.subscription_status, SubscriptionStatus.RECEIVING.value)
        self.assertEqual(view.selected_topic.sample_count, 5)
        self.assertEqual(view.fields[0].path, "pose.x")
        self.assertTrue(view.fields[0].selected)
        self.assertEqual(view.sample_rows[0].value, "4.25")
        self.assertEqual(controller.selected_topic_key, "7:RobotTelemetry")

    async def test_include_internal_and_filter_are_passed_to_scan_and_view(self):
        client = _fake_discovery_client()
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(client),
            config=TopicsTabControllerConfig(domain_id=7),
        )

        controller.set_include_internal(True)
        controller.set_search_text("monitoring")
        view = await controller.refresh_view()

        self.assertEqual(client.scans, [(7, True)])
        self.assertTrue(view.include_internal)
        self.assertEqual(view.search_text, "monitoring")
        self.assertEqual([row.topic_name for row in view.rows], ["rti/service/monitoring/periodic"])

    async def test_headless_controller_without_facade_returns_empty_view(self):
        controller = TopicsTabController(config=TopicsTabControllerConfig(domain_id=9))

        view = await controller.refresh_view()

        self.assertEqual(view.domain_id, 9)
        self.assertEqual(view.rows, ())
        self.assertIn("No topic selected", view.diagnostics)

    async def test_discovery_scan_failure_is_reported_as_diagnostic(self):
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(FailingDiscoveryClient()),
            config=TopicsTabControllerConfig(domain_id=11),
        )

        view = await controller.refresh_view()

        self.assertTrue(view.diagnostics[0].startswith("Discovery scan failed: scan failed for domain 11"))
        self.assertEqual(view.rows, ())


def _fake_discovery_client():
    catalog = TypeCatalog()
    catalog.register_type("Robot::Telemetry", source="fixture.xml", kind="struct")
    catalog.register_type("RTI::Service::Monitoring::Periodic", source="monitoring.xml", kind="struct")
    client = FakeTopicDiscoveryClient(type_catalog=catalog)
    client.apply(DiscoveredEndpoint(
        domain_id=7,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        direction=EndpointDirection.WRITER,
        endpoint_key="writer-telemetry",
        partitions=("/robot",),
    ))
    client.apply(DiscoveredEndpoint(
        domain_id=7,
        topic_name="RobotTelemetry",
        type_name="Robot::Telemetry",
        direction=EndpointDirection.READER,
        endpoint_key="reader-telemetry",
        partitions=("/robot",),
    ))
    client.apply(DiscoveredEndpoint(
        domain_id=7,
        topic_name="rti/service/monitoring/periodic",
        type_name="RTI::Service::Monitoring::Periodic",
        direction=EndpointDirection.WRITER,
        endpoint_key="writer-monitoring",
    ))
    return client


if __name__ == "__main__":
    unittest.main()
