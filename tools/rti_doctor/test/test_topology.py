"""Unit tests for per-run observed DDS topology metrics."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import records, report, topology  # noqa: E402


class FakeRegistry:
  def __init__(self):
    self._participants = [records.ParticipantRecord(key="p1"),
                          records.ParticipantRecord(key="p2")]
    self._writers = [
        records.EndpointRecord(key="w1", kind="Writer", topic_name="Status"),
        records.EndpointRecord(key="w2", kind="Writer", topic_name="Status"),
    ]
    self._readers = [
        records.EndpointRecord(key="r1", kind="Reader", topic_name="Commands"),
        records.EndpointRecord(key="r2", kind="Reader", topic_name=""),
    ]

  def participant_list(self):
    return list(self._participants)

  def writers(self):
    return list(self._writers)

  def readers(self):
    return list(self._readers)


class TestTopologySnapshot(unittest.TestCase):

  def test_counts_remote_entities_and_unique_topics(self):
    snapshot = topology.snapshot(
        FakeRegistry(), selected_domain_id=7, active_domain_ids={2, 7},
        domain_scan_ran=True)
    self.assertEqual(snapshot["domain_ids"], [2, 7])
    self.assertTrue(snapshot["domain_scan_ran"])
    self.assertEqual(snapshot["participants"], 2)
    self.assertEqual(snapshot["writers"], 2)
    self.assertEqual(snapshot["readers"], 2)
    self.assertEqual(snapshot["topics"], ["Commands", "Status"])
    self.assertEqual(snapshot["topic_count"], 2)
    self.assertFalse(snapshot["complete"])

  def test_renderers_include_topology(self):
    snapshot = topology.snapshot(FakeRegistry(), selected_domain_id=7)
    data = report.ReportData(
        domain_id=7, scope="domain audit", all_findings=[], topology=snapshot)
    self.assertIn("OBSERVED TOPOLOGY", report.render_text(data))
    payload = json.loads(report.render_json(data))
    self.assertEqual(payload["topology"]["participants"], 2)
    self.assertEqual(payload["topology"]["topics"], ["Commands", "Status"])


if __name__ == "__main__":
  unittest.main()