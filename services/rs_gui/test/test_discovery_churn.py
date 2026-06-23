#!/usr/bin/env python3
"""Unit tests for the rs_gui live discovery churn gate."""

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

from discovery_churn import (  # noqa: E402
    DiscoveryChurnConfig,
    DiscoveryChurnIteration,
    DiscoveryChurnMetrics,
    build_report,
    evaluate_churn,
    live_topics_in_namespace,
    parse_args,
    write_report,
)


class FakeTopic:
    def __init__(self, topic_name, endpoint_count):
        self.topic_name = topic_name
        self.endpoint_count = endpoint_count


class TestDiscoveryChurnConfig(unittest.TestCase):
    def test_parse_args_builds_config(self):
        config = parse_args([
            "--domain-id", "72",
            "--iterations", "3",
            "--namespace", "/demo/churn/",
            "--observe-timeout-sec", "1.5",
            "--settle-timeout-sec", "2.5",
            "--poll-interval-sec", "0.05",
            "--stale-endpoint-sec", "1.25",
            "--min-observed-ratio", "0.75",
            "--output", "test_output/custom.json",
        ])

        self.assertEqual(config.domain_id, 72)
        self.assertEqual(config.iterations, 3)
        self.assertEqual(config.namespace, "demo/churn")
        self.assertEqual(config.observe_timeout_sec, 1.5)
        self.assertEqual(config.settle_timeout_sec, 2.5)
        self.assertEqual(config.poll_interval_sec, 0.05)
        self.assertEqual(config.stale_endpoint_sec, 1.25)
        self.assertEqual(config.min_observed_ratio, 0.75)
        self.assertEqual(config.output_path, "test_output/custom.json")

    def test_default_output_lives_under_rs_gui_live_reports(self):
        config = parse_args([])

        self.assertEqual(
            config.output_path,
            os.path.join(PARENT_DIR, "live_reports", "discovery_churn_report.json"),
        )

    def test_config_clamps_bounds(self):
        config = DiscoveryChurnConfig(
            iterations=0,
            namespace="/",
            observe_timeout_sec=0.0,
            settle_timeout_sec=0.0,
            poll_interval_sec=0.0,
            stale_endpoint_sec=-1.0,
            min_observed_ratio=2.0,
        )

        self.assertEqual(config.iterations, 1)
        self.assertEqual(config.namespace, "RsGuiV2DiscoveryChurn")
        self.assertGreaterEqual(config.observe_timeout_sec, 0.1)
        self.assertGreaterEqual(config.settle_timeout_sec, 0.1)
        self.assertGreaterEqual(config.poll_interval_sec, 0.01)
        self.assertEqual(config.stale_endpoint_sec, 0.0)
        self.assertEqual(config.min_observed_ratio, 1.0)


class TestDiscoveryChurnEvaluation(unittest.TestCase):
    def test_live_topics_in_namespace_filters_to_active_run_topics(self):
        topics = (
            FakeTopic("run/a/0", 2),
            FakeTopic("run/a/1", 0),
            FakeTopic("run/b/0", 1),
            FakeTopic("other", 4),
        )

        live = live_topics_in_namespace(topics, "run/a")

        self.assertEqual([topic.topic_name for topic in live], ["run/a/0"])

    def test_evaluate_churn_passes_when_observed_and_cleaned_up(self):
        config = DiscoveryChurnConfig(iterations=2, min_observed_ratio=1.0)
        metrics = DiscoveryChurnMetrics(expected_topics=2, observed_topics=2)
        iterations = (
            DiscoveryChurnIteration(0, "run/0", True, 1, 1),
            DiscoveryChurnIteration(1, "run/1", True, 1, 1),
        )

        self.assertEqual(evaluate_churn(config, metrics, iterations), ())

    def test_evaluate_churn_reports_observation_cleanup_and_iteration_failures(self):
        config = DiscoveryChurnConfig(iterations=4, min_observed_ratio=0.75)
        metrics = DiscoveryChurnMetrics(
            expected_topics=4,
            observed_topics=2,
            final_live_topics=1,
            final_live_topic_names=("run/ghost",),
            errors=("dds error",),
        )
        iterations = (
            DiscoveryChurnIteration(0, "run/0", False, issues=("not discovered",)),
        )

        issues = evaluate_churn(config, metrics, iterations)

        self.assertIn("dds error", issues)
        self.assertIn("not discovered", issues)
        self.assertTrue(any("observed 2/4" in issue for issue in issues))
        self.assertTrue(any("run/ghost" in issue for issue in issues))

    def test_report_writer_creates_json_file(self):
        config = DiscoveryChurnConfig(iterations=1)
        metrics = DiscoveryChurnMetrics(expected_topics=1, observed_topics=1)
        iteration = DiscoveryChurnIteration(0, "run/0", True, 1, 1)
        report = build_report(config, metrics, (iteration,))

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "report.json")
            write_report(report, path)

            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as report_file:
                text = report_file.read()
            self.assertIn('"passed": true', text)
            self.assertIn('"observed_topics": 1', text)
            self.assertIn('"observed_ratio": 1.0', text)


if __name__ == "__main__":
    unittest.main()
