#!/usr/bin/env python3
"""Pure unit tests for rs_gui plotting buffers."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    PlotSamplePoint,
    PlotSeriesBuffer,
    WorkspacePlotDefinition,
    WorkspacePlotSeries,
    SampleEnvelope,
    SampleInfoSnapshot,
    build_plot_buffer_sets,
)


class TestPlotSeriesBuffer(unittest.TestCase):
    def test_updates_from_numeric_sample_field(self):
        buffer = PlotSeriesBuffer(self._series("pose.x"), history_seconds=60.0, max_points=10)
        sample = self._sample(data={"pose": {"x": 1.25}}, source_timestamp=100.0)

        result = buffer.update_from_sample(sample)
        snapshot = buffer.snapshot()

        self.assertTrue(result.accepted)
        self.assertFalse(result.skipped)
        self.assertEqual(snapshot.accepted_samples, 1)
        self.assertEqual(snapshot.skipped_samples, 0)
        self.assertEqual(snapshot.points[0].timestamp, 100.0)
        self.assertEqual(snapshot.points[0].value, 1.25)

    def test_skips_invalid_missing_and_nonnumeric_samples(self):
        buffer = PlotSeriesBuffer(self._series("pose.x"))

        invalid = buffer.update_from_sample(self._sample(
            data={"pose": {"x": 1}},
            valid=False,
        ))
        missing = buffer.update_from_sample(self._sample(data={"pose": {}}))
        text = buffer.update_from_sample(self._sample(data={"pose": {"x": "fast"}}))

        self.assertTrue(invalid.skipped)
        self.assertTrue(missing.skipped)
        self.assertTrue(text.skipped)
        self.assertEqual(buffer.snapshot().points, ())
        self.assertEqual(buffer.snapshot().skipped_samples, 3)
        self.assertIn("not numeric", buffer.snapshot().last_message)

    def test_ignores_samples_for_other_topic_or_type(self):
        buffer = PlotSeriesBuffer(self._series("pose.x"))

        domain = buffer.update_from_sample(self._sample(domain_id=1, data={"pose": {"x": 1}}))
        topic = buffer.update_from_sample(self._sample(topic_name="Other", data={"pose": {"x": 1}}))
        type_name = buffer.update_from_sample(self._sample(type_name="OtherType", data={"pose": {"x": 1}}))

        self.assertTrue(domain.skipped)
        self.assertTrue(topic.skipped)
        self.assertTrue(type_name.skipped)
        self.assertEqual(buffer.snapshot().accepted_samples, 0)

    def test_prunes_by_history_window(self):
        buffer = PlotSeriesBuffer(self._series("pose.x"), history_seconds=5.0, max_points=10)

        for timestamp in (100.0, 103.0, 106.0):
            buffer.update_from_sample(self._sample(data={"pose": {"x": timestamp}}, source_timestamp=timestamp))

        snapshot = buffer.snapshot()
        self.assertEqual([point.timestamp for point in snapshot.points], [103.0, 106.0])
        self.assertEqual(snapshot.dropped_points, 1)

    def test_prunes_by_max_points(self):
        buffer = PlotSeriesBuffer(self._series("pose.x"), history_seconds=60.0, max_points=2)

        for timestamp in (1.0, 2.0, 3.0):
            buffer.update_from_sample(self._sample(data={"pose": {"x": timestamp}}, source_timestamp=timestamp))

        snapshot = buffer.snapshot()
        self.assertEqual([point.value for point in snapshot.points], [2.0, 3.0])
        self.assertEqual(snapshot.dropped_points, 1)

    def test_decimation_replaces_point_inside_min_interval(self):
        buffer = PlotSeriesBuffer(
            self._series("pose.x"),
            history_seconds=60.0,
            max_points=10,
            min_interval_seconds=0.5,
        )

        first = buffer.update_from_sample(self._sample(data={"pose": {"x": 1.0}}, source_timestamp=10.0))
        second = buffer.update_from_sample(self._sample(data={"pose": {"x": 2.0}}, source_timestamp=10.2))
        third = buffer.update_from_sample(self._sample(data={"pose": {"x": 3.0}}, source_timestamp=10.8))

        snapshot = buffer.snapshot()
        self.assertFalse(first.decimated)
        self.assertTrue(second.decimated)
        self.assertFalse(third.decimated)
        self.assertEqual([point.value for point in snapshot.points], [2.0, 3.0])
        self.assertEqual(snapshot.accepted_samples, 3)
        self.assertEqual(snapshot.decimated_points, 1)

    def test_point_round_trip_and_snapshot_dict(self):
        point = PlotSamplePoint(
            timestamp=1.0,
            value=2.0,
            source_timestamp=1.0,
            reception_timestamp=1.1,
            observed_at=1.2,
        )
        buffer = PlotSeriesBuffer(self._series("pose.x"))
        buffer.append(point)

        self.assertEqual(PlotSamplePoint.from_dict(point.to_dict()), point)
        self.assertEqual(buffer.snapshot().to_dict()["points"][0]["value"], 2.0)

    def _series(self, field_path, enabled=True):
        return WorkspacePlotSeries(
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            field_path=field_path,
            label="Telemetry field",
            enabled=enabled,
        )

    def _sample(
            self,
            data,
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            source_timestamp=None,
            valid=True,
    ):
        return SampleEnvelope(
            subscription_key=f"{domain_id}:{topic_name}:{type_name}",
            domain_id=domain_id,
            topic_name=topic_name,
            type_name=type_name,
            data=data,
            info=SampleInfoSnapshot(valid=valid, source_timestamp=source_timestamp),
            observed_at=200.0,
        )


class TestPlotBufferSet(unittest.TestCase):
    def test_builds_plot_buffer_sets_and_snapshots_matching_series(self):
        plot = WorkspacePlotDefinition(
            name="Pose",
            history_seconds=20.0,
            max_points=5,
            series=(
                WorkspacePlotSeries(
                    domain_id=0,
                    topic_name="Telemetry",
                    type_name="TelemetryType",
                    field_path="pose.x",
                    label="X",
                ),
                WorkspacePlotSeries(
                    domain_id=0,
                    topic_name="Telemetry",
                    type_name="TelemetryType",
                    field_path="pose.y",
                    label="Y",
                ),
            ),
        )
        buffers = build_plot_buffer_sets((plot,), min_interval_seconds=0.0)

        results = buffers[0].update_from_sample(SampleEnvelope(
            subscription_key="0:Telemetry:TelemetryType",
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            data={"pose": {"x": 1.0, "y": 2.0}},
            info=SampleInfoSnapshot(source_timestamp=5.0),
        ))
        snapshot = buffers[0].snapshot()

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.accepted for result in results))
        self.assertEqual(snapshot.name, "Pose")
        self.assertEqual(snapshot.point_count, 2)
        self.assertEqual([series.points[0].value for series in snapshot.series], [1.0, 2.0])
        self.assertEqual(snapshot.to_dict()["series"][0]["label"], "X")

    def test_disabled_plot_is_not_built(self):
        plot = WorkspacePlotDefinition(
            name="Disabled",
            enabled=False,
            series=(WorkspacePlotSeries(
                domain_id=0,
                topic_name="Telemetry",
                type_name="TelemetryType",
                field_path="pose.x",
            ),),
        )

        self.assertEqual(build_plot_buffer_sets((plot,)), ())

    def test_nonmatching_sample_does_not_increment_series_skip_counts(self):
        plot = WorkspacePlotDefinition(
            name="Pose",
            series=(WorkspacePlotSeries(
                domain_id=0,
                topic_name="Telemetry",
                type_name="TelemetryType",
                field_path="pose.x",
            ),),
        )
        buffers = build_plot_buffer_sets((plot,))

        results = buffers[0].update_from_sample(SampleEnvelope(
            subscription_key="0:Other:TelemetryType",
            domain_id=0,
            topic_name="Other",
            type_name="TelemetryType",
            data={"pose": {"x": 1.0}},
            info=SampleInfoSnapshot(source_timestamp=5.0),
        ))

        self.assertEqual(results, ())
        self.assertEqual(buffers[0].snapshot().series[0].skipped_samples, 0)


if __name__ == "__main__":
    unittest.main()