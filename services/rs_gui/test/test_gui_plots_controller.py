#!/usr/bin/env python3
"""Headless tests for rs_gui Plots tab controller wiring."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import DataSessionSnapshot, PlotBufferSnapshot, PlotSamplePoint, PlotSeriesSnapshot
from gui.tabs.plots_controller import (
    PlotsTabController,
    PlotsTabControllerConfig,
    plots_inputs_from_data_session_snapshot,
)


class FailingDataSessionSnapshotProvider:
    def __call__(self):
        raise RuntimeError("snapshot unavailable")


class TestPlotsTabController(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_uses_static_plot_snapshots(self):
        controller = PlotsTabController(
            plot_snapshots=(self._plot("Static", values=(1.0, 2.0)),),
            config=PlotsTabControllerConfig(selected_plot_name="Static"),
            clock=lambda: 50.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(view.selected_plot_name, "Static")
        self.assertEqual(view.total_point_count, 2)
        self.assertEqual(view.updated_at, 50.0)
        self.assertEqual(controller.last_view, view)

    async def test_data_session_snapshot_provider_populates_plot_series(self):
        snapshot = DataSessionSnapshot(
            workspace_name="Workspace",
            plots=(self._plot("Provider Plot", values=(3.0, 4.0, 5.0)),),
            updated_at=10.0,
        )
        controller = PlotsTabController(
            data_session_snapshot_provider=lambda: snapshot,
            clock=lambda: 55.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(view.selected_plot_name, "Provider Plot")
        self.assertEqual(view.series[0].latest_value, "5")
        self.assertEqual(view.total_point_count, 3)
        self.assertEqual(controller.selected_plot_name, "Provider Plot")

    async def test_data_session_snapshot_failure_is_reported(self):
        controller = PlotsTabController(
            data_session_snapshot_provider=FailingDataSessionSnapshotProvider(),
            clock=lambda: 60.0,
        )

        view = await controller.refresh_view()

        self.assertEqual(view.rows, ())
        self.assertIn("Data session snapshot failed: snapshot unavailable", view.diagnostics)

    async def test_controller_can_pause_and_select_plot(self):
        controller = PlotsTabController(
            plot_snapshots=(self._plot("Alpha", values=(1.0,)), self._plot("Beta", values=(2.0,))),
        )
        controller.select_plot("Beta")
        controller.set_paused(True)

        view = await controller.refresh_view()

        self.assertEqual(view.selected_plot_name, "Beta")
        self.assertTrue(view.paused)
        self.assertEqual(view.action_by_id["resume"].label, "Resume")

    def _plot(self, name, values):
        points = tuple(
            PlotSamplePoint(timestamp=100.0 + index, value=value, source_timestamp=100.0 + index)
            for index, value in enumerate(values)
        )
        return PlotBufferSnapshot(
            name=name,
            series=(PlotSeriesSnapshot(
                series_key=f"0:Telemetry:{name}",
                label=name,
                domain_id=0,
                topic_name="Telemetry",
                type_name="TelemetryType",
                field_path="value",
                points=points,
                accepted_samples=len(points),
                last_message="accepted",
            ),),
        )


class TestDataSessionSnapshotBridge(unittest.TestCase):
    def test_extracts_plot_snapshots_from_data_session_snapshot(self):
        plots = (
            PlotBufferSnapshot(name="Alpha"),
            PlotBufferSnapshot(name="Beta"),
        )
        snapshot = DataSessionSnapshot(plots=plots)

        self.assertEqual(plots_inputs_from_data_session_snapshot(snapshot), plots)


if __name__ == "__main__":
    unittest.main()