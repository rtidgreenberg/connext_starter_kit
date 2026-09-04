"""Tests for pairing historical QoS observations by overlap."""

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.historical_qos_analysis import _process_label, analyze_discovery
from app_core.recorded_discovery import RecordedDiscovery, RecordedEndpointLifetime


def _endpoint(key, kind, start, end, reliability, type_name="ExampleType", qos=None):
    qos = qos if qos is not None else (
        ("reliability_kind", reliability), ("durability_kind", 0),
        ("deadline_period", 0), ("latency_budget_duration", 0),
        ("liveliness_kind", 0), ("liveliness_lease_duration", 0),
        ("ownership_kind", 0), ("destination_order_kind", 0),
        ("presentation_access_scope", 0), ("presentation_coherent_access", 0),
        ("presentation_ordered_access", 0), ("partition", ""),
    )
    return RecordedEndpointLifetime(
        key=key, kind=kind, participant_key="participant", topic_name="Example",
        type_name=type_name, domain_id=42, started_at_ns=start, ended_at_ns=end,
        qos=qos,
    )


class TestHistoricalQosAnalysis(unittest.TestCase):
    def test_process_label_parses_connext_system_properties(self):
        properties = (
            "dds.sys_info.hostname\x1fdev-host\x1f1\x1e"
            "dds.sys_info.process_id\x1f49452\x1f1\x1e"
            "dds.sys_info.executable_filepath\x1f/usr/bin/python3.11\x1f1"
        )

        self.assertEqual(_process_label(properties), "python3.11 (pid 49452 on dev-host)")

    def test_reports_only_mismatched_pairs_that_overlapped(self):
        discovery = RecordedDiscovery((), (
            _endpoint("writer", "Writer", 1, 10, 0),
            _endpoint("reader-overlap", "Reader", 5, 12, 1),
            _endpoint("reader-later", "Reader", 10, None, 1),
        ))

        analysis = analyze_discovery(discovery)

        self.assertEqual(analysis.comparison_count, 1)
        self.assertEqual(len(analysis.issues), 1)
        self.assertEqual(analysis.issues[0].reader_key, "reader-overlap")
        self.assertEqual(analysis.issues[0].mismatches[0].name, "reliability")
        self.assertEqual(analysis.issues[0].writer_participant_name, "unknown participant")
        self.assertEqual(analysis.issues[0].writer_process, "unknown process")

    def test_reports_type_mismatches_for_overlapping_topic_endpoints(self):
        discovery = RecordedDiscovery((), (
            _endpoint("writer", "Writer", 1, None, 1, type_name="WriterType"),
            _endpoint("reader", "Reader", 2, None, 1, type_name="ReaderType"),
        ))

        analysis = analyze_discovery(discovery)

        self.assertEqual(analysis.comparison_count, 1)
        self.assertEqual(analysis.issues[0].mismatches[0].name, "type")

    def test_reports_unevaluated_overlapping_pairs(self):
        discovery = RecordedDiscovery((), (
            _endpoint("writer", "Writer", 1, None, 1, qos=()),
            _endpoint("reader", "Reader", 2, None, 1, qos=()),
        ))

        analysis = analyze_discovery(discovery)

        self.assertEqual(analysis.comparison_count, 1)
        self.assertEqual(analysis.issues[0].mismatches, ())
        self.assertEqual(analysis.issues[0].unevaluated[0].name, "reliability")


if __name__ == "__main__":
    unittest.main()