#!/usr/bin/env python3
"""Pure unit tests for rs_gui_v2 headless data session coordination."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    AppRuntime,
    DataSessionConfig,
    DataSessionCoordinator,
    FakeTopicSubscriptionClient,
    SampleEnvelope,
    SampleInfoSnapshot,
    SubscriptionStatus,
    TopicSelection,
    TopicSelectionState,
    TopicSubscriptionRequest,
    TypeAvailabilityStatus,
    TypeCatalog,
    WorkspaceDocument,
    WorkspacePlotDefinition,
    WorkspacePlotSeries,
    build_workspace_subscription_requests,
)


class TestWorkspaceSubscriptionRequests(unittest.TestCase):
    def test_builds_requests_from_subscriptions_selections_and_plots(self):
        workspace = self._workspace()

        requests = build_workspace_subscription_requests(workspace)

        self.assertEqual([request.key for request in requests], [
            "0:Missing:MissingType",
            "0:Telemetry:TelemetryType",
        ])
        telemetry = requests[1]
        self.assertEqual(telemetry.selected_fields, ("pose.y", "pose.x"))
        self.assertEqual(telemetry.max_samples, 2)

    def test_disabled_topic_selections_and_plots_do_not_create_requests(self):
        disabled_selection = TopicSelection(
            domain_id=0,
            topic_name="DisabledTopic",
            type_name="TelemetryType",
            enabled=False,
        )
        disabled_plot = WorkspacePlotDefinition(
            name="DisabledPlot",
            enabled=False,
            series=(WorkspacePlotSeries(
                domain_id=0,
                topic_name="DisabledPlotTopic",
                type_name="TelemetryType",
                field_path="pose.x",
            ),),
        )
        workspace = WorkspaceDocument(
            topic_selections=TopicSelectionState(selections={disabled_selection.key: disabled_selection}),
            plots=(disabled_plot,),
        )

        self.assertEqual(build_workspace_subscription_requests(workspace), ())

    def _workspace(self):
        return WorkspaceDocument(
            name="Data Session",
            topic_selections=TopicSelectionState(selections={
                "0:Missing": TopicSelection(
                    domain_id=0,
                    topic_name="Missing",
                    type_name="MissingType",
                    selected_fields=("value",),
                ),
            }),
            subscriptions=(TopicSubscriptionRequest(
                domain_id=0,
                topic_name="Telemetry",
                type_name="TelemetryType",
                selected_fields=("pose.y",),
                max_samples=2,
            ),),
            plots=(WorkspacePlotDefinition(
                name="Pose",
                series=(WorkspacePlotSeries(
                    domain_id=0,
                    topic_name="Telemetry",
                    type_name="TelemetryType",
                    field_path="pose.x",
                ),),
            ),),
        )


class TestDataSessionCoordinator(unittest.IsolatedAsyncioTestCase):
    async def test_start_subscribes_available_types_and_surfaces_unresolved_types(self):
        workspace = self._workspace(include_missing=True)
        client = FakeTopicSubscriptionClient()
        session = DataSessionCoordinator(
            workspace,
            client,
            type_catalog=self._type_catalog(),
        )

        snapshot = await session.start()

        states = {state.request.key: state for state in snapshot.subscriptions}
        self.assertEqual(states["0:Telemetry:TelemetryType"].status, SubscriptionStatus.READER_CREATED)
        self.assertEqual(states["0:Missing:MissingType"].status, SubscriptionStatus.UNRESOLVED_TYPE)
        self.assertIn("not available", states["0:Missing:MissingType"].message)
        self.assertEqual([request.key for request in client.subscribed_requests], ["0:Telemetry:TelemetryType"])
        self.assertEqual(
            snapshot.type_resolutions["0:Telemetry:TelemetryType"].status,
            TypeAvailabilityStatus.AVAILABLE,
        )
        self.assertEqual(
            snapshot.type_resolutions["0:Missing:MissingType"].status,
            TypeAvailabilityStatus.MISSING,
        )

    async def test_poll_caches_samples_updates_state_and_feeds_plots(self):
        workspace = self._workspace(max_samples=2)
        client = FakeTopicSubscriptionClient()
        session = DataSessionCoordinator(
            workspace,
            client,
            type_catalog=self._type_catalog(),
            config=DataSessionConfig(plot_min_interval_seconds=0.0),
        )
        await session.start()
        client.queue_samples([
            self._sample(index=0, value=1.0),
            self._sample(index=1, value=2.0),
            self._sample(index=2, value=3.0),
        ])

        update = await session.poll_once()
        snapshot = session.snapshot()
        state = snapshot.subscription_state("0:Telemetry:TelemetryType")

        self.assertEqual(update.sample_count, 3)
        self.assertEqual(update.dropped_sample_count, 1)
        self.assertEqual(state.status, SubscriptionStatus.RECEIVING)
        self.assertEqual(state.received_samples, 3)
        self.assertEqual(state.dropped_samples, 1)
        self.assertEqual([sample.data["index"] for sample in snapshot.samples[state.request.key]], [1, 2])
        self.assertEqual(snapshot.plots[0].point_count, 3)
        self.assertEqual([point.value for point in snapshot.plots[0].series[0].points], [1.0, 2.0, 3.0])
        self.assertEqual(snapshot.to_dict()["plots"][0]["series"][0]["accepted_samples"], 3)

    async def test_invalid_samples_are_counted_and_reported_to_plot_buffers(self):
        workspace = self._workspace()
        client = FakeTopicSubscriptionClient()
        session = DataSessionCoordinator(workspace, client, type_catalog=self._type_catalog())
        await session.start()
        client.queue_sample(self._sample(index=0, value=1.0, valid=False))

        await session.poll_once()
        snapshot = session.snapshot()
        state = snapshot.subscription_state("0:Telemetry:TelemetryType")

        self.assertEqual(state.invalid_samples, 1)
        self.assertEqual(state.received_samples, 0)
        self.assertEqual(snapshot.plots[0].point_count, 0)
        self.assertEqual(snapshot.plots[0].series[0].skipped_samples, 1)

    async def test_telemetry_burst_bounds_cache_plot_buffers_and_runtime_counters(self):
        workspace = self._workspace(max_samples=32, plot_max_points=64, plot_history_seconds=1000.0)
        client = FakeTopicSubscriptionClient()
        runtime = AppRuntime()
        session = DataSessionCoordinator(
            workspace,
            client,
            type_catalog=self._type_catalog(),
            config=DataSessionConfig(plot_min_interval_seconds=0.0),
        )
        await session.start()

        update = session.apply_samples([
            self._sample(index=index, value=float(index))
            for index in range(500)
        ])
        runtime.record_data_session_update(update)
        snapshot = session.snapshot()
        state = snapshot.subscription_state("0:Telemetry:TelemetryType")
        series = snapshot.plots[0].series[0]

        self.assertEqual(update.sample_count, 500)
        self.assertEqual(update.dropped_sample_count, 468)
        self.assertEqual(runtime.counters.samples_received, 500)
        self.assertEqual(runtime.counters.samples_dropped, 468)
        self.assertEqual(state.received_samples, 500)
        self.assertEqual(state.dropped_samples, 468)
        self.assertEqual(len(snapshot.samples[state.request.key]), 32)
        self.assertEqual(snapshot.plots[0].point_count, 64)
        self.assertEqual(series.accepted_samples, 500)
        self.assertEqual(series.dropped_points, 436)
        self.assertEqual([sample.data["index"] for sample in snapshot.samples[state.request.key]][0], 468)
        self.assertEqual(series.points[0].value, 436.0)

    async def test_config_default_max_samples_applies_to_derived_requests(self):
        selection = TopicSelection(
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            selected_fields=("pose.x",),
        )
        workspace = WorkspaceDocument(
            topic_selections=TopicSelectionState(selections={selection.key: selection}),
        )
        client = FakeTopicSubscriptionClient()
        session = DataSessionCoordinator(
            workspace,
            client,
            type_catalog=self._type_catalog(),
            config=DataSessionConfig(default_max_samples=3),
        )

        self.assertEqual(session.requests[0].max_samples, 3)

    async def test_stop_unsubscribes_active_subscriptions_and_close_closes_client(self):
        workspace = self._workspace(include_missing=True)
        client = FakeTopicSubscriptionClient()
        session = DataSessionCoordinator(workspace, client, type_catalog=self._type_catalog())
        await session.start()

        snapshot = await session.stop()
        await session.close()

        states = {state.request.key: state for state in snapshot.subscriptions}
        self.assertEqual(states["0:Telemetry:TelemetryType"].status, SubscriptionStatus.STOPPED)
        self.assertEqual(states["0:Missing:MissingType"].status, SubscriptionStatus.UNRESOLVED_TYPE)
        self.assertEqual([request.key for request in client.unsubscribed_requests], ["0:Telemetry:TelemetryType"])
        self.assertTrue(client.closed)

    def _workspace(
            self,
            max_samples=4,
            include_missing=False,
            plot_max_points=10,
            plot_history_seconds=60.0,
    ):
        selections = {}
        if include_missing:
            selection = TopicSelection(
                domain_id=0,
                topic_name="Missing",
                type_name="MissingType",
                selected_fields=("value",),
            )
            selections[selection.key] = selection
        return WorkspaceDocument(
            name="Data Session",
            topic_selections=TopicSelectionState(selections=selections),
            subscriptions=(TopicSubscriptionRequest(
                domain_id=0,
                topic_name="Telemetry",
                type_name="TelemetryType",
                selected_fields=("pose.x",),
                max_samples=max_samples,
            ),),
            plots=(WorkspacePlotDefinition(
                name="Pose",
                history_seconds=plot_history_seconds,
                max_points=plot_max_points,
                series=(WorkspacePlotSeries(
                    domain_id=0,
                    topic_name="Telemetry",
                    type_name="TelemetryType",
                    field_path="pose.x",
                    label="X",
                ),),
            ),),
        )

    def _type_catalog(self):
        catalog = TypeCatalog()
        catalog.register_type("TelemetryType", source="test", kind="struct")
        return catalog

    def _sample(self, index, value, valid=True):
        return SampleEnvelope(
            subscription_key="0:Telemetry:TelemetryType",
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            data={"index": index, "pose": {"x": value}} if valid else None,
            info=SampleInfoSnapshot(valid=valid, source_timestamp=float(index)),
            observed_at=100.0 + index,
        )


if __name__ == "__main__":
    unittest.main()