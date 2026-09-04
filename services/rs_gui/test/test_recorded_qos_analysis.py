"""Unit tests for DDS-free recorded endpoint QoS analysis."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.recorded_discovery import RecordedEndpointLifetime
from app_core.recorded_qos_analysis import QosCompatibilityStatus, compare_recorded_endpoints


def _endpoint(kind, **qos):
    return RecordedEndpointLifetime(
        key=kind.lower(),
        kind=kind,
        participant_key="participant",
        topic_name="Example",
        type_name="ExampleType",
        domain_id=42,
        started_at_ns=0,
        ended_at_ns=None,
        qos=tuple(qos.items()),
    )


class TestRecordedQosAnalysis(unittest.TestCase):
    def test_accepts_compatible_offered_and_requested_policies(self):
        writer = _endpoint(
            "Writer",
            reliability_kind=1,
            durability_kind=2,
            deadline_period=10,
            latency_budget_duration=20,
            liveliness_kind=2,
            liveliness_lease_duration=30,
            ownership_kind=1,
            destination_order_kind=1,
            presentation_access_scope=2,
            presentation_coherent_access=1,
            presentation_ordered_access=1,
            partition="alpha-*",
        )
        reader = _endpoint(
            "Reader",
            reliability_kind=0,
            durability_kind=1,
            deadline_period=20,
            latency_budget_duration=30,
            liveliness_kind=1,
            liveliness_lease_duration=40,
            ownership_kind=1,
            destination_order_kind=1,
            presentation_access_scope=1,
            presentation_coherent_access=1,
            presentation_ordered_access=1,
            partition="alpha-east",
        )

        result = compare_recorded_endpoints(writer, reader)

        self.assertEqual(result.status, QosCompatibilityStatus.COMPATIBLE)
        self.assertTrue(result.is_compatible)
        self.assertTrue(all(policy.status is QosCompatibilityStatus.COMPATIBLE for policy in result.policies))

    def test_reports_policy_mismatches_and_partition_wildcard_overlap(self):
        writer = _endpoint(
            "Writer",
            reliability_kind=0,
            durability_kind=0,
            deadline_period=50,
            latency_budget_duration=50,
            liveliness_kind=0,
            liveliness_lease_duration=50,
            ownership_kind=0,
            destination_order_kind=0,
            presentation_access_scope=0,
            presentation_coherent_access=0,
            presentation_ordered_access=0,
            partition="control-?",
        )
        reader = _endpoint(
            "Reader",
            reliability_kind=1,
            durability_kind=1,
            deadline_period=20,
            latency_budget_duration=20,
            liveliness_kind=1,
            liveliness_lease_duration=20,
            ownership_kind=1,
            destination_order_kind=1,
            presentation_access_scope=1,
            presentation_coherent_access=1,
            presentation_ordered_access=1,
            partition="control-a",
        )

        result = compare_recorded_endpoints(writer, reader)

        self.assertEqual(result.status, QosCompatibilityStatus.MISMATCH)
        statuses = {policy.name: policy.status for policy in result.policies}
        self.assertEqual(statuses["partition"], QosCompatibilityStatus.COMPATIBLE)
        self.assertEqual(statuses["reliability"], QosCompatibilityStatus.MISMATCH)
        self.assertEqual(statuses["presentation"], QosCompatibilityStatus.MISMATCH)

    def test_marks_missing_or_invalid_flattened_values_as_unevaluated(self):
        writer = _endpoint("Writer", reliability_kind=1, deadline_period="unknown", partition="")
        reader = _endpoint("Reader", reliability_kind=0)

        result = compare_recorded_endpoints(writer, reader)

        self.assertEqual(result.status, QosCompatibilityStatus.UNEVALUATED)
        policies = {policy.name: policy for policy in result.policies}
        self.assertEqual(policies["reliability"].status, QosCompatibilityStatus.COMPATIBLE)
        self.assertEqual(policies["deadline"].status, QosCompatibilityStatus.UNEVALUATED)
        self.assertIn("invalid writer value", policies["deadline"].reason)
        self.assertEqual(policies["partition"].status, QosCompatibilityStatus.UNEVALUATED)
        self.assertIn("missing reader value", policies["partition"].reason)


if __name__ == "__main__":
    unittest.main()