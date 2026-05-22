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
    AppCommand,
    CommandStatus,
    DataSessionSnapshot,
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
from gui import (
    TopicsTabController,
    TopicsTabControllerConfig,
    topics_inputs_from_data_session_snapshot,
)


class FailingDiscoveryClient:
    async def scan(self, domain_id: int, include_internal: bool = False):
        raise RuntimeError(f"scan failed for domain {domain_id}")

    async def topics(self, domain_id: int, include_internal: bool = False):
        return
        yield


class FailingDataSessionSnapshotProvider:
    def __call__(self):
        raise RuntimeError("snapshot unavailable")


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

    async def test_data_session_snapshot_provider_populates_samples(self):
        client = _fake_discovery_client()
        snapshot = _data_session_snapshot()
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(client),
            field_catalogs={"Robot::Telemetry": FieldCatalog(
                type_name="Robot::Telemetry",
                fields=(FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),),
            )},
            data_session_snapshot_provider=lambda: snapshot,
            config=TopicsTabControllerConfig(domain_id=7, selected_topic_key="7:RobotTelemetry"),
        )

        view = await controller.refresh_view()

        self.assertEqual(view.selected_topic.subscription_status, SubscriptionStatus.RECEIVING.value)
        self.assertEqual(view.selected_topic.sample_count, 2)
        self.assertEqual([row.value for row in view.sample_rows], ["7.5"])
        self.assertEqual(view.fields[0].path, "pose.x")

    async def test_data_session_snapshot_failure_is_reported(self):
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(_fake_discovery_client()),
            data_session_snapshot_provider=FailingDataSessionSnapshotProvider(),
            config=TopicsTabControllerConfig(domain_id=7),
        )

        view = await controller.refresh_view()

        self.assertTrue(view.diagnostics[0].startswith("Data session snapshot failed: snapshot unavailable"))

    async def test_subscribe_and_unsubscribe_commands_update_subscription_state(self):
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(_fake_discovery_client()),
            field_catalogs={"Robot::Telemetry": FieldCatalog(
                type_name="Robot::Telemetry",
                fields=(FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),),
            )},
            config=TopicsTabControllerConfig(domain_id=7, selected_topic_key="7:RobotTelemetry"),
            clock=lambda: 80.0,
        )

        subscribe = controller.handle_command(AppCommand(
            command_type="topics.subscribe",
            payload={
                "domain_id": 7,
                "topic_name": "RobotTelemetry",
                "type_name": "Robot::Telemetry",
                "selected_fields": ("pose.x",),
            },
            command_id="subscribe-robot",
            created_at=1.0,
        ))
        subscribed = await controller.refresh_view()

        self.assertEqual(subscribe.status, CommandStatus.ACKNOWLEDGED)
        self.assertEqual(subscribed.selected_topic.subscription_status, SubscriptionStatus.READER_CREATED.value)
        self.assertTrue(subscribed.action_by_id["unsubscribe"].enabled)
        self.assertTrue(subscribed.fields[0].selected)

        unsubscribe = controller.handle_command(AppCommand(
            command_type="topics.unsubscribe",
            payload={
                "domain_id": 7,
                "topic_name": "RobotTelemetry",
                "type_name": "Robot::Telemetry",
            },
            command_id="unsubscribe-robot",
            created_at=2.0,
        ))
        stopped = await controller.refresh_view()

        self.assertEqual(unsubscribe.status, CommandStatus.ACKNOWLEDGED)
        self.assertEqual(stopped.selected_topic.subscription_status, SubscriptionStatus.STOPPED.value)
        self.assertFalse(stopped.action_by_id["unsubscribe"].enabled)
        self.assertTrue(stopped.action_by_id["subscribe"].enabled)

    async def test_data_session_subscription_overrides_survive_snapshot_refresh(self):
        snapshot = _data_session_snapshot()
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(_fake_discovery_client()),
            data_session_snapshot_provider=lambda: snapshot,
            config=TopicsTabControllerConfig(domain_id=7, selected_topic_key="7:RobotTelemetry"),
            clock=lambda: 90.0,
        )
        await controller.refresh_view()

        controller.handle_command(AppCommand(
            command_type="topics.unsubscribe",
            payload={
                "domain_id": 7,
                "topic_name": "RobotTelemetry",
                "type_name": "Robot::Telemetry",
            },
        ))
        view = await controller.refresh_view()

        self.assertEqual(view.selected_topic.subscription_status, SubscriptionStatus.STOPPED.value)
        self.assertEqual(view.selected_topic.sample_count, 2)

    async def test_filter_internal_and_field_commands_update_controller_state(self):
        controller = TopicsTabController(
            discovery_facade=TopicDiscoveryFacade(_fake_discovery_client()),
            field_catalogs={"Robot::Telemetry": FieldCatalog(
                type_name="Robot::Telemetry",
                fields=(
                    FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),
                    FieldDescriptor("velocity", "velocity", "float32", scalar_kind="float"),
                ),
            )},
            config=TopicsTabControllerConfig(domain_id=7, selected_topic_key="7:RobotTelemetry"),
        )

        controller.handle_command(AppCommand("topics.set_search", payload={"search_text": "robot"}))
        controller.handle_command(AppCommand("topics.set_include_internal", payload={"include_internal": True}))
        controller.handle_command(AppCommand(
            "topics.set_field_selected",
            payload={
                "domain_id": 7,
                "topic_name": "RobotTelemetry",
                "type_name": "Robot::Telemetry",
                "field_path": "pose.x",
                "selected": True,
            },
        ))
        controller.handle_command(AppCommand(
            "topics.set_plot_field_selected",
            payload={
                "domain_id": 7,
                "topic_name": "RobotTelemetry",
                "type_name": "Robot::Telemetry",
                "field_path": "velocity",
                "selected": True,
            },
        ))
        view = await controller.refresh_view()

        self.assertEqual(view.search_text, "robot")
        self.assertTrue(view.include_internal)
        fields = {field.path: field for field in view.fields}
        self.assertTrue(fields["pose.x"].selected)
        self.assertTrue(fields["velocity"].plot_selected)


class TestDataSessionSnapshotBridge(unittest.TestCase):
    def test_extracts_subscription_states_and_samples_in_stable_order(self):
        snapshot = _data_session_snapshot()

        states, samples = topics_inputs_from_data_session_snapshot(snapshot)

        self.assertEqual([state.request.key for state in states], ["7:RobotTelemetry:Robot::Telemetry"])
        self.assertEqual([sample.data["pose"]["x"] for sample in samples], [7.0, 7.5])


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


def _data_session_snapshot():
    request = TopicSubscriptionRequest(7, "RobotTelemetry", "Robot::Telemetry")
    samples = (
        SampleEnvelope(
            subscription_key=request.key,
            domain_id=7,
            topic_name="RobotTelemetry",
            type_name="Robot::Telemetry",
            data={"pose": {"x": 7.0}},
        ),
        SampleEnvelope(
            subscription_key=request.key,
            domain_id=7,
            topic_name="RobotTelemetry",
            type_name="Robot::Telemetry",
            data={"pose": {"x": 7.5}},
        ),
    )
    return DataSessionSnapshot(
        workspace_name="Data Session",
        subscriptions=(TopicSubscriptionState(
            request=request,
            status=SubscriptionStatus.RECEIVING,
            received_samples=2,
        ),),
        samples={request.key: samples},
        updated_at=20.0,
    )


if __name__ == "__main__":
    unittest.main()
