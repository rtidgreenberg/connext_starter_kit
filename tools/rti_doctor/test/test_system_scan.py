"""Unit tests for passive issue aggregation and immutable scan snapshots."""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import discovery, engine, findings as f, records  # noqa: E402
from rti_doctor import report, system_scan, topology  # noqa: E402


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

  def test_topic_wide_condition_is_one_issue_not_one_per_endpoint(self):
    """A type-name conflict belongs to the topic, not to each endpoint on it."""
    registry = registry_with_reliability_fault()
    registry.endpoints["reader-guid"].type_name = "sensors::TelemetryType"
    snapshot = system_scan.scan(
        registry, own_qos=None, type_lookup_settings={"request_types_filter": "*"},
        domain_id=7, captured_at=123.0)

    conflicts = [item for item in snapshot.issues
                 if "type.name_conflict" in item.finding_ids]
    self.assertEqual(len(conflicts), 1)
    self.assertEqual(conflicts[0].scope, "topic")
    self.assertEqual(conflicts[0].topic_name, "Telemetry")
    # Endpoint identity is deliberately absent: it is what would have split one
    # condition into one issue per endpoint.
    self.assertEqual(conflicts[0].writer_keys, ())
    self.assertEqual(conflicts[0].reader_keys, ())

  def test_participant_wide_condition_is_one_issue_not_one_per_endpoint(self):
    """Neither endpoint advertises locators, so both fall back to the participant."""
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    locators = [item for item in snapshot.issues
                if "locator.unroutable" in item.finding_ids]
    self.assertEqual(len(locators), 2)  # one per participant, not one per endpoint
    self.assertEqual({item.scope for item in locators}, {"participant"})
    self.assertEqual({key for item in locators for key in item.participant_keys},
                     {"participant-w", "participant-r"})

  def test_no_type_info_error_is_never_raised_against_a_reader(self):
    """Its title and remedy name a writer; pointed at a reader they mislead."""
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    missing = [item for item in snapshot.issues
               if "type.no_type_info" in item.finding_ids]
    self.assertEqual(len(missing), 1)
    self.assertEqual(missing[0].writer_keys, ("writer-guid",))
    self.assertEqual(missing[0].reader_keys, ())


class TestNothingToReport(unittest.TestCase):
  """A quiet domain must produce no issues at all.

  Doctor pointed at a domain with no DDS on it used to emit blind.empty_domain
  at ERROR: an issue list, a red count, and a nonzero exit code, with nothing
  wrong anywhere. Finding nothing is the answer to the question, not a fault.
  """

  def _empty_snapshot(self):
    return system_scan.scan(
        discovery.DiscoveryRegistry(type_wait=0.0), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)

  def test_an_empty_domain_produces_no_issues(self):
    snapshot = self._empty_snapshot()
    self.assertEqual(
        [item.finding_ids for item in snapshot.issues], [],
        "a domain with no DDS on it must not manufacture issues")
    self.assertEqual(snapshot.topology["participants"], 0)

  def test_the_guidance_is_still_reported(self):
    """Silenced as an issue, not deleted: a report still explains the emptiness."""
    text = report.render_system_text(self._empty_snapshot(), 7, environment={
        "argv": "rti_doctor", "host": "t", "os": "Linux", "machine": "x86_64",
        "connext": "7.7.0", "nddshome": "/opt/rti", "python": "3.x"})
    self.assertIn("No DDS participants were discovered on domain 7", text)
    self.assertNotIn("No active issues in this snapshot", text)

  def test_an_empty_domain_is_not_called_healthy(self):
    """"No issues" over nothing observed would be a clean bill of health."""
    text = report.render_system_text(self._empty_snapshot(), 7, environment={
        "argv": "rti_doctor", "host": "t", "os": "Linux", "machine": "x86_64",
        "connext": "7.7.0", "nddshome": "/opt/rti", "python": "3.x"})
    self.assertIn("not a clean bill of health", text)


class TestScanUnderConcurrentDiscovery(unittest.TestCase):
  """The registry is mutated by other threads for the whole of a scan.

  Connext receive threads call upsert_endpoint/remove_endpoint from the builtin
  listeners, and the TUI's 2s timer calls refresh_participants on the event-loop
  thread, while system_scan runs in an asyncio.to_thread worker. A registry
  query that comprehends over a live dict raises "dictionary changed size during
  iteration" mid-walk.

  The symptom is not a crash. run_checks catches the exception per check and
  converts it to an internal.check_failed INFO, so the operator sees a scan that
  silently dropped findings and reported a clean domain. Measured against the
  pre-fix code, 6 of 122 scans lost at least one check this way.

  The churn deliberately does NOT call remove_participant: that cascades to the
  participant's endpoints, and an earlier draft of this test emptied the
  registry within the first fraction of a second, leaving later scans nothing to
  race over. test_the_churn_keeps_the_registry_populated exists so that cannot
  happen again unnoticed.
  """

  PARTICIPANTS = 60
  DURATION = 1.5

  def setUp(self):
    # Force frequent thread switches. Without this the race is real but
    # infrequent, and a regression guard that only usually fires is not one.
    self._switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    self.addCleanup(sys.setswitchinterval, self._switch_interval)

    self.registry = discovery.DiscoveryRegistry(type_wait=0.0)
    for index in range(self.PARTICIPANTS):
      participant = records.ParticipantRecord(key=f"p{index}", name=f"app-{index}")
      self.registry.participants[participant.key] = participant
      for kind in ("Writer", "Reader"):
        endpoint = records.EndpointRecord(
            key=f"{kind}-{index}", kind=kind, participant_key=participant.key,
            topic_name=f"Topic{index % 7}", type_name="T",
            reliability=Policy("RELIABLE"), type_state=records.TYPE_RESOLVED,
            first_seen=1.0)
        self.registry.endpoints[endpoint.key] = endpoint
    self.baseline = len(self.registry.endpoints)

    self._stop = threading.Event()
    self.churn_error = []
    self.mutations = 0
    self._thread = threading.Thread(target=self._churn, daemon=True)
    self._thread.start()
    self.addCleanup(self._join)

  def _churn(self):
    """Stand in for the builtin listeners: endpoints arriving and departing."""
    index = 0
    try:
      while not self._stop.is_set():
        self.registry.upsert_endpoint(records.EndpointRecord(
            key=f"Writer-churn-{index}", kind="Writer", participant_key="p0",
            topic_name=f"Topic{index % 7}", type_name="T",
            type_state=records.TYPE_RESOLVED, first_seen=1.0))
        self.registry.remove_endpoint(f"Writer-churn-{max(index - 3, 0)}")
        index += 1
        self.mutations = index
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
      self.churn_error.append(error)

  def _join(self):
    self._stop.set()
    self._thread.join(timeout=5)

  def _run_for(self, work):
    deadline = time.monotonic() + self.DURATION
    runs = 0
    while time.monotonic() < deadline:
      work()
      runs += 1
    self.assertFalse(self.churn_error,
                     f"the mutating thread itself failed: {self.churn_error}")
    self.assertGreater(self.mutations, 100, "the mutating thread barely ran")
    return runs

  def test_the_churn_keeps_the_registry_populated(self):
    """Guards the guard: a scan over an empty registry cannot race."""
    self._run_for(lambda: time.sleep(0.05))
    self.assertGreaterEqual(len(self.registry.endpoints), self.baseline)

  def test_no_check_is_silently_lost_while_endpoints_arrive_and_depart(self):
    lost = []

    def scan_once():
      snapshot = system_scan.scan(
          self.registry, own_qos=None,
          type_lookup_settings={"request_types_filter": "*"}, domain_id=7)
      lost.extend(issue for issue in snapshot.issues
                  if "internal.check_failed" in issue.finding_ids)

    scans = self._run_for(scan_once)
    self.assertGreater(scans, 1, "the scan never ran often enough to race")
    if lost:
      checks = sorted({issue.title for issue in lost})
      self.fail(
          f"{len(lost)} check(s) raised during concurrent discovery across "
          f"{scans} scans, so the scan silently dropped findings and would "
          f"report a cleaner domain than it saw.\\n  "
          + "\\n  ".join(checks)
          + f"\\n  {lost[0].observed}")

  def test_topology_snapshot_survives_the_same_churn(self):
    """topology.snapshot is outside run_checks, so its failure propagates."""
    self._run_for(lambda: topology.snapshot(self.registry, 7))


if __name__ == "__main__":
  unittest.main()