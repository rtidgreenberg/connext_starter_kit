"""Unit tests for passive issue aggregation and immutable scan snapshots."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import discovery, engine, findings as f, records, report, system_scan  # noqa: E402


class Policy:
  def __init__(self, kind):
    self.kind = kind


def registry_with_reliability_fault():
  registry = discovery.DiscoveryRegistry(type_wait=0.0)
  writer_participant = records.ParticipantRecord(key="participant-w", name="writer-app")
  reader_participant = records.ParticipantRecord(key="participant-r", name="reader-app")
  registry.participants = {
      writer_participant.key: writer_participant,
      reader_participant.key: reader_participant,
  }
  writer = records.EndpointRecord(
      key="writer-guid", kind="Writer", participant_key=writer_participant.key,
      topic_name="Telemetry", type_name="TelemetryType",
      reliability=Policy("BEST_EFFORT"), type_state=records.TYPE_UNAVAILABLE,
      first_seen=1.0)
  reader = records.EndpointRecord(
      key="reader-guid", kind="Reader", participant_key=reader_participant.key,
      topic_name="Telemetry", type_name="TelemetryType",
      reliability=Policy("RELIABLE"), type_state=records.TYPE_UNAVAILABLE,
      first_seen=1.0)
  registry.endpoints = {writer.key: writer, reader.key: reader}
  return registry


class TestSystemScan(unittest.TestCase):

  def test_rxo_fault_has_one_identity_bearing_issue(self):
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)

    rxo = [item for item in snapshot.issues if item.finding_ids == ("qos.rxo_mismatch",)]
    self.assertEqual(len(rxo), 1)
    issue = rxo[0]
    self.assertEqual(issue.severity, f.Severity.ERROR)
    self.assertEqual(issue.scope, "pair")
    self.assertEqual(issue.topic_name, "Telemetry")
    self.assertEqual(issue.writer_keys, ("writer-guid",))
    self.assertEqual(issue.reader_keys, ("reader-guid",))
    self.assertEqual(issue.participant_keys, ("participant-r", "participant-w"))
    self.assertIn("RELIABILITY", issue.evidence["mismatches"][0]["policy"])

  def test_snapshot_topology_and_evidence_are_immutable(self):
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    self.assertEqual(snapshot.captured_at, 123.0)
    self.assertEqual(snapshot.topology["participants"], 2)
    with self.assertRaises(TypeError):
      snapshot.topology["participants"] = 99
    rxo = next(item for item in snapshot.issues if item.finding_ids == ("qos.rxo_mismatch",))
    with self.assertRaises(TypeError):
      rxo.evidence["writer_key"] = "other"

  def test_session_scan_is_passive(self):
    session = engine.Session(
        participant=object(), registry=registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        type_wait=0.0)
    snapshot = session.system_scan(captured_at=123.0)
    self.assertTrue(snapshot.issues)
    self.assertEqual(snapshot.topology["writers"], 1)

  def test_system_report_contains_metrics_and_issue_relationships(self):
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    text = report.render_system_text(snapshot, 7, environment={
        "argv": "rti_doctor", "host": "test", "os": "Linux", "machine": "x86_64",
        "connext": "7.7.0", "nddshome": "/opt/rti", "python": "3.x"})
    self.assertIn("RTI DOCTOR SYSTEM REPORT", text)
    self.assertIn("Participants", text)
    self.assertIn("writer-guid", text)
    self.assertIn("reader-guid", text)
    self.assertIn("Recommendation Change RELIABILITY", text)

  @mock.patch("rti_doctor.compat.connext_version", return_value="7.3.1")
  def test_connext_7_3_produces_upgrade_note(self, _version):
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    note = next(item for item in snapshot.issues
                if item.finding_ids == ("environment.connext_7_3_upgrade",))
    self.assertEqual(note.severity, f.Severity.INFO)
    self.assertIn("Connext 7.7", note.recommendation)


if __name__ == "__main__":
  unittest.main()