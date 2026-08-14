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


def registry_with_fastdds_peers():
  """Three Fast DDS peers whose keys yield distinct RTPS GUID prefixes.

  Participant keys are `str(data.key.value)` over a four-word BuiltinTopicKey,
  and `wire.record_guid_prefix` reads the first three words - so the fixture has
  to use that real key shape for the wire-to-registry match to be exercised at
  all.
  """
  registry = discovery.DiscoveryRegistry(type_wait=0.0)
  peers = {}
  for name, words in (("old", (1, 1, 1, 1)), ("older", (2, 2, 2, 2)),
                      ("current", (3, 3, 3, 3))):
    record = records.ParticipantRecord(key=str(list(words)), name=f"fastdds-{name}")
    registry.participants[record.key] = record
    peers[name] = "".join(f"{word:08x}" for word in words[:3])
  return registry, peers


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

  def test_a_scan_never_starts_or_reads_a_packet_capture(self):
    """H9: the scan is DDS-level and passive. It used to stop and re-parse one."""
    registry = discovery.DiscoveryRegistry(type_wait=0.0)
    registry.participants["fastdds"] = records.ParticipantRecord(
        key="fastdds", vendor_id=type("Vendor", (), {"value": [1, 15]})())
    session = engine.Session(
        participant=object(), registry=registry, own_qos=None,
        type_lookup_settings={}, domain_id=7, type_wait=0.0)

    def fail(*args, **kwargs):
      self.fail("the system scan ran tshark")

    with mock.patch.object(engine.wire, "LiveCapture", fail), \
         mock.patch.object(engine.wire, "inspect_discovery_pcap", fail):
      snapshot = session.system_scan(captured_at=123.0)
    self.assertEqual(snapshot.fastdds_product_versions, ())

  def test_capture_evidence_reaches_the_next_scan(self):
    """The version evidence an explicit capture collected is what the scan reports."""
    registry, peers = registry_with_fastdds_peers()
    session = engine.Session(
        participant=object(), registry=registry, own_qos=None,
        type_lookup_settings={}, domain_id=7, type_wait=0.0)
    first = session.system_scan(captured_at=123.0)
    self.assertEqual(first.fastdds_product_versions, ())

    session.record_wire_discovery({
        "fastdds_product_versions": ["3.5.4.0"],
        "fastdds_participant_versions": [[peers["old"], "3.5.4.0"]]})
    # A stale cached scan must not keep reporting the versions as unknown.
    second = session.system_scan(captured_at=124.0, max_age=3600.0)
    self.assertEqual(second.fastdds_product_versions, ("3.5.4.0",))
    self.assertTrue(any("environment.fastdds_version_older_than_validated"
                        in issue.finding_ids for issue in second.issues))

  def test_a_failed_capture_records_nothing(self):
    """An unreadable capture is not evidence that no old version is present."""
    session = engine.Session(
        participant=object(), registry=discovery.DiscoveryRegistry(type_wait=0.0),
        own_qos=None, type_lookup_settings={}, domain_id=7, type_wait=0.0)
    session.record_wire_discovery(
        {"error": "tshark was not found on PATH",
         "fastdds_product_versions": ["3.5.4.0"]})
    self.assertEqual(session.system_scan(captured_at=123.0)
                     .fastdds_product_versions, ())

  def test_an_independent_failure_is_never_removed_by_another(self):
    """The suppression regression: one ERROR deleted an unrelated symptom.

    Suppression matched on finding id across the whole run, with no topic,
    endpoint or pair scope, so an unresolved type on one topic removed a real
    RxO failure on another from the issue list, the counts and the exit code.
    """
    registry = registry_with_reliability_fault()
    # A second, unrelated topic whose type never resolved.
    other = records.ParticipantRecord(key="participant-o", name="other-app")
    registry.participants[other.key] = other
    registry.endpoints["other-writer"] = records.EndpointRecord(
        key="other-writer", kind="Writer", participant_key=other.key,
        topic_name="Alarms", type_name="AlarmType",
        type_state=records.TYPE_UNAVAILABLE, first_seen=1.0)

    snapshot = system_scan.scan(
        registry, own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)

    reported = {item for issue in snapshot.issues for item in issue.finding_ids}
    self.assertIn("qos.rxo_mismatch", reported)
    self.assertIn("type.no_type_info", reported)
    worst = max(issue.severity for issue in snapshot.issues)
    self.assertEqual(worst, f.Severity.ERROR)

  def test_a_likely_cause_travels_with_the_issue_as_context(self):
    registry = registry_with_reliability_fault()
    snapshot = system_scan.scan(
        registry, own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    # Whatever links exist, they must never be the reason an issue is absent.
    for issue in snapshot.issues:
      self.assertIsInstance(issue.explained_by, tuple)

  def test_the_report_records_our_own_configuration(self):
    """Every report states how the measurement was made, stage one included."""
    snapshot = system_scan.scan(
        registry_with_reliability_fault(), own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    text = report.render_system_text(
        snapshot, 7, environment={
            "argv": "rti_doctor", "host": "test", "os": "Linux",
            "machine": "x86_64", "connext": "7.7.0", "nddshome": "/opt/rti",
            "python": "3.x"},
        type_lookup_settings={"request_types_filter": "*"})
    self.assertIn("RTI_DOCTOR OWN CONFIGURATION", text)
    self.assertIn("request_types_filter", text)

  def test_no_system_report_line_exceeds_the_report_width(self):
    """The system report has its own renderer, so it needs its own guard.

    The endpoint report's width test would not have caught this one: the capture
    hint is appended by `render_system_text` alone, and it went out as a single
    131-character line. Single unbreakable tokens - a path, a GUID, the command
    line - are exempt, as they are everywhere else in the report.
    """
    snapshot = system_scan.scan(
        registry_with_fastdds_peers()[0], own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0)
    text = report.render_system_text(
        snapshot, 7, environment={
            "argv": "rti_doctor --domain 7", "host": "test", "os": "Linux",
            "machine": "x86_64", "connext": "7.7.0", "nddshome": "/opt/rti",
            "python": "3.x"},
        type_lookup_settings={"request_types_filter": "*"})
    too_wide = [line for line in text.splitlines()
                if len(line) > report.WIDTH
                and max((len(word) for word in line.split()), default=0)
                < report.WIDTH // 2]
    self.assertEqual(too_wide, [], "a system report line ran past the width")

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

  def test_the_system_report_says_a_version_needs_a_capture(self):
    """H8/H9: "nobody looked" must not render the same as "nothing is there".

    Fast DDS advertises its product version only in RTPS discovery packets, and
    nothing captures packets now unless an operator asks. Dropping the section
    when no capture had run left the report silently certifying a question it
    had never put.
    """
    snapshot = system_scan.scan(
        registry_with_fastdds_peers()[0], own_qos=None,
        type_lookup_settings={}, domain_id=7, captured_at=123.0)
    text = report.render_system_text(snapshot, 7, environment={
        "argv": "rti_doctor", "host": "test", "os": "Linux", "machine": "x86_64",
        "connext": "7.7.0", "nddshome": "/opt/rti", "python": "3.x"})
    self.assertIn("FAST DDS VERSION EVIDENCE", text)
    self.assertIn(report.CAPTURE_PLACEHOLDER, text)
    self.assertIn("press c", text)

  def test_an_observed_version_replaces_the_placeholder(self):
    registry, peers = registry_with_fastdds_peers()
    snapshot = system_scan.scan(
        registry, own_qos=None, type_lookup_settings={}, domain_id=7,
        captured_at=123.0, fastdds_product_versions=("3.5.4.0",),
        fastdds_participant_versions=((peers["old"], "3.5.4.0"),))
    text = report.render_system_text(snapshot, 7, environment={
        "argv": "rti_doctor", "host": "test", "os": "Linux", "machine": "x86_64",
        "connext": "7.7.0", "nddshome": "/opt/rti", "python": "3.x"})
    self.assertIn("3.5.4.0", text)
    self.assertNotIn(report.CAPTURE_PLACEHOLDER, text)

  def test_older_fastdds_version_produces_warning(self):
    registry, peers = registry_with_fastdds_peers()
    snapshot = system_scan.scan(
        registry, own_qos=None,
        type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
        captured_at=123.0,
        fastdds_participant_versions=((peers["old"], "3.5.4.0"),
                                      (peers["current"], "3.6.2.0")))
    warning = next(item for item in snapshot.issues
                   if item.finding_ids ==
                   ("environment.fastdds_version_older_than_validated",))
    self.assertEqual(warning.severity, f.Severity.WARN)
    self.assertIn("3.5.4.0", warning.observed)
    self.assertNotIn("3.6.2.0", warning.observed)


class TestFastDdsVersionFindings(unittest.TestCase):
  """C1a-C1c: the version WARN must be per participant, linked, and transient."""

  def _scan(self, registry, pairs):
    return system_scan.scan(
        registry, own_qos=None, type_lookup_settings={"request_types_filter": "*"},
        domain_id=7, captured_at=123.0, fastdds_participant_versions=pairs)

  def test_two_out_of_baseline_versions_are_two_issues(self):
    """C1a: every identity slot was empty, so N versions hashed to one key."""
    registry, peers = registry_with_fastdds_peers()
    snapshot = self._scan(registry, ((peers["old"], "3.5.4.0"),
                                     (peers["older"], "2.14.0.0")))
    warnings = [item for item in snapshot.issues
                if "environment.fastdds_version_older_than_validated"
                in item.finding_ids]
    self.assertEqual(len(warnings), 2)
    self.assertEqual(len({item.key for item in warnings}), 2)
    observed = " ".join(item.observed for item in warnings)
    self.assertIn("3.5.4.0", observed)
    self.assertIn("2.14.0.0", observed)

  def test_the_warning_names_the_participant_it_describes(self):
    """C1b: it declares RUNG_PARTICIPANT, so Health and `i` need its key."""
    registry, peers = registry_with_fastdds_peers()
    snapshot = self._scan(registry, ((peers["old"], "3.5.4.0"),))
    warning = next(item for item in snapshot.issues
                   if "environment.fastdds_version_older_than_validated"
                   in item.finding_ids)
    self.assertEqual(warning.scope, "participant")
    self.assertEqual(warning.participant_keys, ("[1, 1, 1, 1]",))
    self.assertIn("fastdds-old", warning.observed)

  def test_a_departed_participant_stops_producing_the_warning(self):
    """C1c: the version list outlived the peer, so the WARN never stopped."""
    registry, peers = registry_with_fastdds_peers()
    pairs = ((peers["old"], "3.5.4.0"),)
    self.assertTrue([item for item in self._scan(registry, pairs).issues
                     if "environment.fastdds_version_older_than_validated"
                     in item.finding_ids])

    registry.remove_participant("[1, 1, 1, 1]")
    self.assertFalse([item for item in self._scan(registry, pairs).issues
                      if "environment.fastdds_version_older_than_validated"
                      in item.finding_ids])

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

  def test_the_census_does_not_describe_type_extensibility(self):
    """One shared type must not put one note per endpoint in the issue list.

    check_extensibility describes how a type is declared - the same answer for
    every endpoint using it - so 96 endpoints sharing one FINAL type produced
    96 byte-identical entries. It belongs to targeted diagnosis, where the
    type map is the point, and it is asserted absent here so it cannot drift
    back in.
    """
    registry = discovery.DiscoveryRegistry(type_wait=0.0)
    participant = records.ParticipantRecord(key="p")
    registry.participants = {participant.key: participant}
    # A resolved type on every endpoint: check_extensibility returns early on
    # `type is None`, so a fixture without one passes whether or not the check
    # still runs in the census.
    registry.endpoints = {
        f"w{n}": records.EndpointRecord(
            key=f"w{n}", kind="Writer", participant_key="p",
            topic_name="Telemetry", type_name="TelemetryType",
            type=object(), type_state=records.TYPE_RESOLVED, first_seen=1.0)
        for n in range(8)}

    with mock.patch("rti_doctor.typewalk.extensibility_map",
                    return_value={"TelemetryType": "FINAL"}):
      snapshot = system_scan.scan(
          registry, own_qos=None,
          type_lookup_settings={"request_types_filter": "*"}, domain_id=7,
          captured_at=123.0)

    self.assertEqual([item for item in snapshot.issues
                      if "type.extensibility" in item.finding_ids], [])

  def test_a_topic_wide_condition_still_names_every_endpoint_it_involves(self):
    """One issue, but reachable from each endpoint and participant in it.

    Withholding identity was how topic scope kept the dedup honest, and it
    also emptied the Health column and the `i` filter for both participants:
    a conflict existed and every row involved in it rendered "OK". The
    linkage keys are carried separately from the identity the issue key is
    built from, so the issue stays single and is still findable.
    """
    registry = registry_with_reliability_fault()
    registry.endpoints["reader-guid"].type_name = "sensors::TelemetryType"
    snapshot = system_scan.scan(
        registry, own_qos=None, type_lookup_settings={"request_types_filter": "*"},
        domain_id=7, captured_at=123.0)

    conflict = next(item for item in snapshot.issues
                    if "type.name_conflict" in item.finding_ids)
    self.assertEqual(conflict.writer_keys, ("writer-guid",))
    self.assertEqual(conflict.reader_keys, ("reader-guid",))
    self.assertEqual(conflict.participant_keys,
                     ("participant-r", "participant-w"))

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
    """The census reports one unresolved schema once, at its publisher.

    The check itself is role-aware now, so a reader would be described
    correctly - but reporting the same missing schema again once per
    subscriber would multiply one condition across the issue list.
    """
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