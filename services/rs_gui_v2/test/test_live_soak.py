#!/usr/bin/env python3
"""Unit tests for the rs_gui_v2 live soak gate."""

import os
import sys
import tempfile
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from live_soak import (  # noqa: E402
    LiveSoakConfig,
    LiveSoakMetrics,
    build_live_soak_workspace,
    evaluate_soak,
    parse_args,
    write_report,
    build_report,
)
from app_core import RuntimeCounters  # noqa: E402


class TestLiveSoakConfig(unittest.TestCase):
    def test_parse_args_builds_config(self):
        config = parse_args([
            "--domain-id", "42",
            "--duration-sec", "1.5",
            "--max-samples", "16",
            "--plot-max-points", "32",
            "--no-publisher",
        ])

        self.assertEqual(config.domain_id, 42)
        self.assertEqual(config.duration_sec, 1.5)
        self.assertEqual(config.max_samples, 16)
        self.assertEqual(config.plot_max_points, 32)
        self.assertFalse(config.start_publisher)

    def test_default_output_lives_under_rs_gui_live_reports(self):
        config = parse_args([])

        self.assertEqual(
            config.output_path,
            os.path.join(PARENT_DIR, "live_reports", "live_soak_report.json"),
        )

    def test_workspace_uses_bounded_subscription_and_plot_limits(self):
        config = LiveSoakConfig(max_samples=12, plot_max_points=34, duration_sec=2.0)

        workspace = build_live_soak_workspace(config)

        self.assertEqual(workspace.subscriptions[0].max_samples, 12)
        self.assertEqual(workspace.subscriptions[0].selected_fields, ("value",))
        self.assertEqual(workspace.plots[0].max_points, 34)
        self.assertEqual(workspace.plots[0].series[0].field_path, "value")


class TestLiveSoakEvaluation(unittest.TestCase):
    def test_evaluate_soak_passes_when_bounds_hold(self):
        config = LiveSoakConfig(max_samples=10, plot_max_points=20, min_samples=5)
        metrics = LiveSoakMetrics(samples_received=5, cached_samples=10, plot_points=20)

        self.assertEqual(evaluate_soak(config, metrics), ())

    def test_evaluate_soak_reports_gate_failures(self):
        config = LiveSoakConfig(
            max_samples=10,
            plot_max_points=20,
            min_samples=5,
            memory_growth_limit_mb=1.0,
        )
        metrics = LiveSoakMetrics(
            samples_received=4,
            cached_samples=11,
            plot_points=21,
            rss_start_kb=100,
            rss_end_kb=1300,
            errors=("runtime error",),
        )

        issues = evaluate_soak(config, metrics)

        self.assertIn("runtime error", issues)
        self.assertTrue(any("expected at least 5" in issue for issue in issues))
        self.assertTrue(any("sample cache exceeded" in issue for issue in issues))
        self.assertTrue(any("plot buffer exceeded" in issue for issue in issues))
        self.assertTrue(any("RSS growth exceeded" in issue for issue in issues))

    def test_report_writer_creates_json_file(self):
        config = LiveSoakConfig(min_samples=1)
        metrics = LiveSoakMetrics(samples_received=1)
        report = build_report(config, metrics, RuntimeCounters(samples_received=1))

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "report.json")
            write_report(report, path)

            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as report_file:
                text = report_file.read()
            self.assertIn('"passed": true', text)
            self.assertIn('"samples_received": 1', text)


if __name__ == "__main__":
    unittest.main()