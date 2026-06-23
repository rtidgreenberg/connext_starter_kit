#!/usr/bin/env python3
"""Headless tests for rs_gui Plots tab view models."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import PlotBufferSnapshot, PlotSamplePoint, PlotSeriesSnapshot
from gui.tabs.plots_tab import build_mock_plots_tab_view_model, build_plots_tab_view_model


class TestPlotsTabViewModel(unittest.TestCase):
    def test_mock_plots_tab_contains_series_and_recent_points(self):
        view = build_mock_plots_tab_view_model(now=120.0)

        self.assertEqual(view.selected_plot_name, "Robot Motion")
        self.assertEqual(view.visible_plot_count, 1)
        self.assertEqual(view.rows[0].point_count, 8)
        self.assertEqual([row.label for row in view.series], ["Velocity", "Pose X"])
        self.assertEqual(view.series[0].latest_value, "1.55")
        self.assertEqual(view.series[0].status, "accepted")
        self.assertEqual(view.action_by_id["pause"].label, "Pause")
        self.assertGreater(len(view.point_rows), 0)
        self.assertEqual(view.diagnostics, ())

    def test_empty_plots_tab_reports_diagnostic_and_disabled_actions(self):
        view = build_plots_tab_view_model(now=10.0)

        self.assertEqual(view.visible_plot_count, 0)
        self.assertEqual(view.total_point_count, 0)
        self.assertIn("No plot buffers are configured", view.diagnostics)
        self.assertFalse(view.action_by_id["pause"].enabled)
        self.assertFalse(view.action_by_id["clear"].enabled)

    def test_selects_requested_plot_and_limits_recent_point_rows(self):
        first = self._plot("Alpha", values=(1.0, 2.0, 3.0))
        second = self._plot("Beta", values=(10.0, 11.0, 12.0))

        view = build_plots_tab_view_model(
            plots=(first, second),
            selected_plot_name="Beta",
            paused=True,
            now=20.0,
            max_point_rows=2,
        )

        self.assertEqual(view.selected_plot_name, "Beta")
        self.assertEqual([row.name for row in view.rows], ["Alpha", "Beta"])
        self.assertFalse(view.rows[0].selected)
        self.assertTrue(view.rows[1].selected)
        self.assertEqual(view.action_by_id["resume"].label, "Resume")
        self.assertEqual(len(view.point_rows), 2)
        self.assertEqual([row.value for row in view.point_rows], ["12", "11"])

    def test_missing_requested_plot_falls_back_to_first_available_plot(self):
        view = build_plots_tab_view_model(
            plots=(self._plot("Zulu", values=(5.0,)), self._plot("Alpha", values=(1.0,))),
            selected_plot_name="Missing",
        )

        self.assertEqual(view.selected_plot_name, "Alpha")
        self.assertTrue(view.rows[0].selected)

    def _plot(self, name, values):
        points = tuple(
            PlotSamplePoint(timestamp=100.0 + index, value=value, source_timestamp=100.0 + index)
            for index, value in enumerate(values)
        )
        return PlotBufferSnapshot(
            name=name,
            history_seconds=10.0,
            max_points=100,
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


if __name__ == "__main__":
    unittest.main()