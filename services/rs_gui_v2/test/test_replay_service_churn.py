#!/usr/bin/env python3
"""Unit tests for the explicit Replay Service GUI churn gate."""

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

from replay_service_churn import (  # noqa: E402
    ReplayServiceChurnConfig,
    ReplayServiceChurnReport,
    ReplayServiceChurnResult,
    _button_callback,
    discover_default_database_dir,
    evaluate_result,
    parse_args,
    write_report,
)
from fakes import FakeDpg  # noqa: E402


class TestReplayServiceChurnConfig(unittest.TestCase):
    def test_parse_args_builds_config(self):
        config = parse_args([
            "--admin-domain-id", "91",
            "--monitoring-domain-id", "92",
            "--data-domain-id", "93",
            "--config-name", "json",
            "--database-dir", "log_dir/recording_1",
            "--startup-timeout-sec", "2.5",
            "--shutdown-timeout-sec", "3.5",
            "--poll-interval-sec", "0.05",
            "--allow-missing-monitoring",
            "--output", "test_output/replay.json",
        ])

        self.assertEqual(config.admin_domain_id, 91)
        self.assertEqual(config.monitoring_domain_id, 92)
        self.assertEqual(config.data_domain_id, 93)
        self.assertEqual(config.config_name, "json")
        self.assertEqual(config.database_dir, "log_dir/recording_1")
        self.assertEqual(config.startup_timeout_sec, 2.5)
        self.assertEqual(config.shutdown_timeout_sec, 3.5)
        self.assertEqual(config.poll_interval_sec, 0.05)
        self.assertFalse(config.require_monitoring_update)
        self.assertEqual(config.output_path, "test_output/replay.json")

    def test_default_output_lives_under_rs_gui_live_reports(self):
        config = parse_args([])

        self.assertEqual(
            config.output_path,
            os.path.join(PARENT_DIR, "live_reports", "replay_service_churn_report.json"),
        )

    def test_discover_default_database_dir_uses_latest_recording(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "log_dir")
            os.makedirs(log_dir, exist_ok=True)
            older = os.path.join(log_dir, "recording_1")
            newer = os.path.join(log_dir, "recording_2")
            os.makedirs(older, exist_ok=True)
            os.makedirs(newer, exist_ok=True)
            with open(os.path.join(older, "metadata.db"), "w", encoding="utf-8"):
                pass
            with open(os.path.join(newer, "metadata.db"), "w", encoding="utf-8"):
                pass
            with open(os.path.join(older, "data_0.db"), "w", encoding="utf-8"):
                pass
            with open(os.path.join(newer, "data_0.db"), "w", encoding="utf-8"):
                pass
            os.utime(older, (1, 1))
            os.utime(newer, None)

            discovered = discover_default_database_dir(tmpdir)

            self.assertEqual(discovered, newer)

    def test_button_callback_finds_named_button(self):
        fake = FakeDpg()
        callback = lambda: True
        fake.add_button(label="Launch Replay Service", callback=callback)

        self.assertIs(_button_callback(fake, "Launch Replay Service"), callback)


class TestReplayServiceChurnEvaluation(unittest.TestCase):
    def test_evaluate_result_passes_for_clean_gui_replay_run(self):
        config = ReplayServiceChurnConfig(database_dir="log_dir/recording_1")
        result = ReplayServiceChurnResult(
            launch_id="launch-1",
            control_name="replay_gate",
            selected_target_id="launch-1",
            pid=1234,
            candidate_source="gui_launch",
            observed_state="running",
            monitoring_resource_id="/replay_services/xcdr",
            monitoring_service_name="replay_gate",
            admin_shutdown_ok=True,
            process_exit_observed=True,
            final_state="exited",
            returncode=0,
        )

        self.assertEqual(evaluate_result(config, result), ())

    def test_evaluate_result_reports_missing_monitoring_and_exit(self):
        config = ReplayServiceChurnConfig(database_dir="log_dir/recording_1")
        result = ReplayServiceChurnResult(
            launch_id="",
            pid=None,
            observed_state="",
            admin_shutdown_ok=False,
            process_exit_observed=False,
            final_state="running",
            issues=("custom issue",),
        )

        issues = evaluate_result(config, result)

        self.assertIn("custom issue", issues)
        self.assertTrue(any("launch id" in issue for issue in issues))
        self.assertTrue(any("PID" in issue for issue in issues))
        self.assertTrue(any("monitoring update" in issue for issue in issues))
        self.assertTrue(any("admin shutdown" in issue for issue in issues))
        self.assertTrue(any("process exit" in issue for issue in issues))
        self.assertTrue(any("final Replay process state is running" in issue for issue in issues))

    def test_report_writer_creates_json_file(self):
        config = ReplayServiceChurnConfig(database_dir="log_dir/recording_1")
        result = ReplayServiceChurnResult(
            launch_id="launch-1",
            control_name="replay_gate",
            pid=1234,
            observed_state="running",
            monitoring_resource_id="/replay_services/xcdr",
            admin_shutdown_ok=True,
            process_exit_observed=True,
            final_state="exited",
            returncode=0,
        )
        report = ReplayServiceChurnReport(True, (), config, result)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "replay_service_churn.json")
            write_report(report, path)

            with open(path, "r", encoding="utf-8") as report_file:
                text = report_file.read()
            self.assertIn('"passed": true', text)
            self.assertIn('"control_name": "replay_gate"', text)


if __name__ == "__main__":
    unittest.main()