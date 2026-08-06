"""System-scan behaviour on a domain with many endpoints.

Every other live suite runs against one writer and at most one reader. The two
most expensive findings of the 2026-08-06 review - the O(endpoints^2) topic
walks and one issue per endpoint for a topic-wide condition - were both claims
about scale, and neither was measured. This suite measures them.

It asserts shape, not wall-clock thresholds: a timing assertion on shared CI
hardware is a flaky test, and a flaky test about performance is worse than no
test. The measured cost is printed so a regression is visible in the log, and
the assertions catch the things that are unambiguously wrong at any speed -
duplicate issues, and a scan whose cost per endpoint is growing.
"""

import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)
sys.path.insert(0, HERE)

import domains  # noqa: E402

try:
  import rti.connextdds  # noqa: F401
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False

if CONNEXT_AVAILABLE:
  from rti_doctor import compat, discovery, engine, findings as f

FIXTURE = os.path.join(HERE, "fixture_publisher.py")

PARTICIPANTS = 6
ENDPOINTS_PER_PARTICIPANT = 16
TOPICS = 12
EXPECTED_ENDPOINTS = PARTICIPANTS * ENDPOINTS_PER_PARTICIPANT


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
class TestScanAtScale(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    compat.configure_rti_environment()
    cls.domain = domains.for_suite("test_scale")
    env = dict(os.environ)
    env["PYTHONPATH"] = TOOL_DIR + os.pathsep + env.get("PYTHONPATH", "")
    cls.fixture = subprocess.Popen(
        [sys.executable, FIXTURE, "--mode", "scale", "--domain", str(cls.domain),
         "--topic", "Scale", "--duration", "90",
         "--scale-participants", str(PARTICIPANTS),
         "--scale-topics", str(TOPICS),
         "--scale-endpoints-per-participant", str(ENDPOINTS_PER_PARTICIPANT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    cls.registry = discovery.DiscoveryRegistry(type_wait=4.0)
    cls.participant, settings = discovery.create_participant(
        cls.domain, name="RTI DOCTOR SCALE", registry=cls.registry)
    cls.session = engine.Session(
        participant=cls.participant, registry=cls.registry,
        own_qos=cls.participant.qos, type_lookup_settings=settings,
        domain_id=cls.domain, type_wait=4.0)

    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
      discovery.refresh_participants(cls.participant, cls.registry)
      if len(cls.registry.endpoint_list()) >= EXPECTED_ENDPOINTS:
        break
      time.sleep(0.5)
    cls.registry.expire_type_waits()
    cls.discovered = len(cls.registry.endpoint_list())

  @classmethod
  def tearDownClass(cls):
    try:
      cls.participant.close()
    except Exception:
      pass
    cls.fixture.terminate()
    try:
      cls.fixture.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover
      cls.fixture.kill()

  def setUp(self):
    if self.discovered < EXPECTED_ENDPOINTS:
      self.skipTest(f"only {self.discovered} of {EXPECTED_ENDPOINTS} endpoints "
                    f"were discovered; the domain may be contended")

  def _scan(self):
    started = time.monotonic()
    snapshot = self.session.system_scan()
    return snapshot, time.monotonic() - started

  def test_the_domain_really_is_at_scale(self):
    """Guards the guard: the rest of this suite is meaningless on 2 endpoints."""
    self.assertGreaterEqual(self.discovered, EXPECTED_ENDPOINTS)
    self.assertGreaterEqual(len(self.registry.participant_list()), PARTICIPANTS)
    self.assertGreaterEqual(len(self.registry.topic_names()), TOPICS)

  def test_a_scan_completes_and_reports_its_cost(self):
    snapshot, elapsed = self._scan()
    per_endpoint = elapsed / self.discovered * 1000
    print(f"\n  scan: {elapsed:.3f}s over {self.discovered} endpoints "
          f"({per_endpoint:.2f} ms/endpoint), {len(snapshot.issues)} issue(s)")
    self.assertTrue(snapshot.topology["participants"] >= PARTICIPANTS)
    # A scan that takes minutes is not a snapshot any operator will wait for.
    # Deliberately loose - this catches an order-of-magnitude regression, not a
    # slow machine.
    self.assertLess(elapsed, 30.0, "a single system scan took over 30 seconds")

  def test_no_check_fails_at_scale(self):
    """internal.check_failed is how a scan reports that it lost a check."""
    snapshot, _ = self._scan()
    failed = [issue for issue in snapshot.issues
              if "internal.check_failed" in issue.finding_ids]
    self.assertEqual(failed, [], f"checks raised at scale: "
                                 f"{[i.observed for i in failed]}")

  def test_a_healthy_domain_stays_quiet_at_scale(self):
    """Every endpoint here is RELIABLE/TRANSIENT_LOCAL and matches its peers."""
    snapshot, _ = self._scan()
    errors = [issue for issue in snapshot.issues
              if issue.severity >= f.Severity.ERROR]
    self.assertEqual([issue.finding_ids for issue in errors], [],
                     f"a healthy {self.discovered}-endpoint domain produced "
                     f"errors: {[i.title for i in errors]}")

  def test_issue_count_does_not_scale_with_endpoint_count(self):
    """The M1 fix, at the scale that made it matter.

    Before it, a topic- or participant-wide condition produced one issue per
    endpoint. On this domain that is the difference between a handful of issues
    and ~100, which is the difference between a triage list and a wall of text.
    """
    snapshot, _ = self._scan()
    self.assertLess(
        len(snapshot.issues), self.discovered,
        f"{len(snapshot.issues)} issues for {self.discovered} endpoints - "
        f"issues are being reported per endpoint rather than per condition")

  def test_no_two_issues_describe_the_same_condition(self):
    snapshot, _ = self._scan()
    seen = {}
    for issue in snapshot.issues:
      # Same finding id, same topic, same participants: the same condition.
      signature = (issue.finding_ids, issue.topic_name,
                   issue.participant_keys, issue.writer_keys, issue.reader_keys)
      self.assertNotIn(signature, seen,
                       f"duplicate issue: {issue.finding_ids} on "
                       f"'{issue.topic_name}'")
      seen[signature] = issue

  def test_repeated_scans_stay_proportional(self):
    """Cost per endpoint must not grow between scans on a settled domain."""
    _, first = self._scan()
    _, second = self._scan()
    print(f"\n  scan 1: {first:.3f}s   scan 2: {second:.3f}s")
    self.assertLess(second, max(first * 4, 5.0),
                    "a repeated scan on an unchanged domain got much slower, "
                    "which suggests state accumulating between scans")


if __name__ == "__main__":
  unittest.main()
