#!/usr/bin/env python3
"""Unit tests for the rs_gui_v2 live service churn gate."""

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

from service_churn import (  # noqa: E402
    ChurnIterationResult,
    ServiceChurnConfig,
    ServiceChurnReport,
    build_launch_request,
    evaluate_churn,
    parse_args,
    write_report,
)


class TestServiceChurnConfig(unittest.TestCase):
    def test_parse_args_builds_churn_config(self):
        config = parse_args([
            "--iterations", "3",
            "--admin-domain-id", "71",
            "--monitoring-domain-id", "72",
            "--data-domain-id", "73",
            "--allow-admin-unready",
            "--require-admin-shutdown",
            "--admin-resource-name", "deploy",
        ])

        self.assertEqual(config.iterations, 3)
        self.assertEqual(config.admin_domain_id, 71)
        self.assertEqual(config.monitoring_domain_id, 72)
        self.assertEqual(config.data_domain_id, 73)
        self.assertFalse(config.require_admin_ready)
        self.assertTrue(config.require_admin_shutdown)
        self.assertEqual(config.admin_resource_name, "deploy")

    def test_default_output_lives_under_rs_gui_live_reports(self):
        config = parse_args([])

        self.assertEqual(
            config.output_path,
            os.path.join(PARENT_DIR, "live_reports", "service_churn_report.json"),
        )

    def test_launch_request_uses_service_configs_domains_and_unique_label(self):
        config = ServiceChurnConfig(admin_domain_id=81, monitoring_domain_id=82, data_domain_id=83)

        request = build_launch_request(config, iteration=4)

        self.assertEqual(request.intent.kind.value, "recording")
        self.assertEqual(request.intent.admin_domain_id, 81)
        self.assertEqual(request.intent.monitoring_domain_id, 82)
        self.assertEqual(request.config_name, "deploy")
        self.assertTrue(request.executable.endswith("rtirecordingservice"))
        self.assertIn("recording_service_config.xml", request.intent.config_paths[0])
        self.assertIn("DDS_QOS_PROFILES.xml", request.intent.config_paths[1])
        self.assertEqual(request.environment["DOMAIN_ID"], "83")
        self.assertEqual(request.environment["ADMIN_DOMAIN_ID"], "81")
        self.assertIn("-DDOMAIN_ID=83", request.extra_args)
        self.assertIn("-DADMIN_DOMAIN_ID=81", request.extra_args)


class TestServiceChurnEvaluation(unittest.TestCase):
    def test_evaluate_churn_passes_for_unique_exited_ready_iterations(self):
        config = ServiceChurnConfig(iterations=2, require_admin_ready=True)
        results = (
            ChurnIterationResult(
                iteration=0,
                launch_id="launch-a",
                control_name="record_a",
                pid=10,
                command_line=("rtirecordingservice",),
                admin_resource_name="deploy",
                readiness={"status": "ready"},
                final_state="exited",
            ),
            ChurnIterationResult(
                iteration=1,
                launch_id="launch-b",
                control_name="record_b",
                pid=11,
                command_line=("rtirecordingservice",),
                admin_resource_name="deploy",
                readiness={"status": "ready"},
                final_state="exited",
            ),
        )

        self.assertEqual(evaluate_churn(config, results), ())

    def test_evaluate_churn_reports_reused_name_unready_and_live_final_state(self):
        config = ServiceChurnConfig(iterations=2, require_admin_ready=True, require_admin_shutdown=True)
        results = (
            ChurnIterationResult(
                iteration=0,
                launch_id="launch-a",
                control_name="record_a",
                pid=10,
                command_line=("rtirecordingservice",),
                admin_resource_name="deploy",
                readiness={"status": "timeout"},
                admin_shutdown_status="timeout",
                final_state="running",
                issues=("custom issue",),
            ),
            ChurnIterationResult(
                iteration=1,
                launch_id="launch-b",
                control_name="record_a",
                pid=11,
                command_line=("rtirecordingservice",),
                admin_resource_name="deploy",
                readiness=None,
                admin_shutdown_status="not_attempted",
                final_state="exited",
            ),
        )

        issues = evaluate_churn(config, results)

        self.assertTrue(any("control names were reused" in issue for issue in issues))
        self.assertTrue(any("custom issue" in issue for issue in issues))
        self.assertTrue(any("final state is running" in issue for issue in issues))
        self.assertTrue(any("admin readiness status is timeout" in issue for issue in issues))
        self.assertTrue(any("admin shutdown status is timeout" in issue for issue in issues))

    def test_report_writer_creates_json_file(self):
        config = ServiceChurnConfig(iterations=1)
        result = ChurnIterationResult(
            iteration=0,
            launch_id="launch-a",
            control_name="record_a",
            pid=10,
            command_line=("rtirecordingservice",),
            admin_resource_name="deploy",
            readiness={"status": "ready"},
            final_state="exited",
        )
        report = ServiceChurnReport(passed=True, issues=(), config=config, iterations=(result,))

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "service_churn.json")
            write_report(report, path)

            with open(path, "r", encoding="utf-8") as report_file:
                text = report_file.read()
            self.assertIn('"passed": true', text)
            self.assertIn('"control_name": "record_a"', text)


if __name__ == "__main__":
    unittest.main()