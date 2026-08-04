"""Live integration tests: real participants, real probes, real fixtures.

Gated on Connext being importable and a license being resolvable. These are the
tests that would catch a check firing on a healthy system, or a probe leaking
entities, neither of which a unit test can see.

Run:
  PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
      -m unittest tools/rti_doctor/test/test_live_integration.py
"""

import os
import random
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)

try:
  import rti.connextdds  # noqa: F401
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False

if CONNEXT_AVAILABLE:
  from rti_doctor import compat, discovery, engine, findings as f, records, report

FIXTURE = os.path.join(HERE, "fixture_publisher.py")
#: High domain ids, randomised per run, so tests do not collide with each other
#: or with whatever else is on the machine.
DOMAIN_BASE = 20


def _domain():
  return DOMAIN_BASE + random.randint(1, 100)


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
class LiveFixtureTest(unittest.TestCase):
  """Base class that runs a fixture publisher and a diagnostic session."""

  MODE = "healthy"
  TOPIC = "DoctorTopic"
  SETTLE = 2.0
  TYPE_WAIT = 4.0
  PROBE_TIMEOUT = 6.0

  @classmethod
  def setUpClass(cls):
    compat.configure_rti_environment()
    cls.domain = _domain()
    env = dict(os.environ)
    env["PYTHONPATH"] = TOOL_DIR + os.pathsep + env.get("PYTHONPATH", "")
    cls.publisher = subprocess.Popen(
        [sys.executable, FIXTURE, "--mode", cls.MODE, "--domain", str(cls.domain),
         "--topic", cls.TOPIC, "--duration", "60"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    time.sleep(4.0)

    cls.registry = discovery.DiscoveryRegistry(type_wait=cls.TYPE_WAIT)
    cls.participant, settings = discovery.create_participant(
        cls.domain, name="RTI DOCTOR TEST", registry=cls.registry)
    cls.session = engine.Session(
        participant=cls.participant, registry=cls.registry,
        own_qos=cls.participant.qos, type_lookup_settings=settings,
        domain_id=cls.domain, type_wait=cls.TYPE_WAIT,
        probe_timeout=cls.PROBE_TIMEOUT)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
      discovery.refresh_participants(cls.participant, cls.registry)
      writer = cls.registry.find_writer(cls.TOPIC)
      if writer is not None and writer.type is not None:
        break
      cls.registry.expire_type_waits()
      if writer is not None and writer.type_state == records.TYPE_UNAVAILABLE:
        break
      time.sleep(0.25)
    cls.registry.expire_type_waits()

  @classmethod
  def tearDownClass(cls):
    try:
      cls.participant.close()
    except Exception:
      pass
    cls.publisher.terminate()
    try:
      cls.publisher.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
      cls.publisher.kill()

  def diagnose(self, probe=True):
    writer = self.registry.find_writer(self.TOPIC)
    self.assertIsNotNone(writer, f"fixture writer on '{self.TOPIC}' was not discovered")
    return self.session.diagnose_endpoint(writer, probe=probe)

  def ids(self, data):
    return {x.id for x in f.active(data.findings)}


class TestHealthy(LiveFixtureTest):
  MODE = "healthy"

  def test_discovers_the_fixture(self):
    self.assertGreaterEqual(len(self.registry.participants), 1)
    self.assertIsNotNone(self.registry.find_writer(self.TOPIC))

  def test_verdict_is_full_payload(self):
    data = self.diagnose()
    self.assertIn("payload FULL", data.verdict, data.verdict)

  def test_no_unexpected_errors_on_a_healthy_system(self):
    """The single most important assertion: a healthy system must be quiet."""
    data = self.diagnose()
    errors = [x.id for x in f.active(data.findings) if x.severity >= f.Severity.ERROR]
    self.assertEqual(errors, [], f"healthy system produced errors: {errors}")

  def test_every_member_of_the_rich_type_is_readable(self):
    data = self.diagnose()
    walk = data.probe_result.walk
    self.assertIsNotNone(walk)
    self.assertEqual(walk.failed, [], f"unreadable: {walk.failed_paths}")
    # nested struct, sequence-of-struct, union, enum, array, optional
    paths = {r.path for r in walk.results}
    for expected in ("nested.n_id", "kids[0].n_id", "choice_d", "color", "fixed[*]"):
      self.assertIn(expected, paths, f"walker never visited {expected}")

  def test_optional_absent_member_is_not_a_failure(self):
    data = self.diagnose()
    absent = {r.path for r in data.probe_result.walk.absent}
    self.assertIn("maybe", absent)

  def test_report_contains_required_sections(self):
    text = report.render_text(self.diagnose())
    for heading in ("RTI DOCTOR INTEROP REPORT", "VERDICT", "PEER", "FINDINGS",
                    "APPENDIX A", "APPENDIX B", "APPENDIX C"):
      self.assertIn(heading, text)

  def test_report_counters_are_real_not_na(self):
    """Regression: EventCount64 counters rendered as 'not available'."""
    text = report.render_text(self.diagnose())
    line = [l for l in text.splitlines() if "received_sample_count" in l]
    self.assertTrue(line, "received_sample_count missing from the report")
    self.assertNotIn("n/a", line[0], "a real counter was reported as unavailable")

  def test_json_report_parses(self):
    import json
    payload = json.loads(report.render_json(self.diagnose()))
    self.assertTrue(payload["unstable_schema"])
    self.assertIn("verdict", payload)

  def test_probe_closes_its_entities(self):
    """A diagnostic must not leak readers into the system it measures."""
    before = len(self.participant.find_datareaders()) if hasattr(
        self.participant, "find_datareaders") else None
    for _ in range(3):
      self.diagnose()
    if before is not None:
      after = len(self.participant.find_datareaders())
      self.assertEqual(before, after, "probe leaked a DataReader")


class TestNoTypeInfo(LiveFixtureTest):
  MODE = "no_type_info"

  def test_reports_missing_type_and_suppresses_the_consequence(self):
    data = self.diagnose()
    active = self.ids(data)
    self.assertIn("type.no_type_info", active)
    suppressed = {x.id: x.suppressed_by for x in f.suppressed(data.findings)}
    self.assertEqual(suppressed.get("probe.not_created"), "type.no_type_info",
                     "the unusable-reader finding should be explained by the "
                     "missing type, not reported as a separate problem")

  def test_verdict_says_not_probed(self):
    self.assertIn("not probed", self.diagnose().verdict)


class TestLargeData(LiveFixtureTest):
  MODE = "large_data"

  def test_fragmentation_is_reported_without_a_false_error(self):
    data = self.diagnose()
    fragmentation = [x for x in f.active(data.findings)
                     if x.id == "data.fragmentation"]
    self.assertTrue(fragmentation, "large data did not report fragmentation at all")
    self.assertEqual(fragmentation[0].severity, f.Severity.INFO,
                     "healthy large data must not be reported as an error")

  def test_large_sample_still_deserializes(self):
    self.assertIn("payload FULL", self.diagnose().verdict)


class TestPartition(LiveFixtureTest):
  MODE = "partition"

  def test_probe_mirrors_the_partition_and_matches(self):
    data = self.diagnose()
    self.assertIn("matched", data.verdict)
    self.assertIn("partition", data.probe_result.applied_reader_qos)


class TestBadPair(LiveFixtureTest):
  """Two live endpoints on one topic that can never match - the core use case."""

  MODE = "bad_pair"

  def test_rxo_mismatch_between_discovered_endpoints(self):
    data = self.diagnose()
    self.assertIn("qos.rxo_mismatch", self.ids(data))

  def test_names_the_offending_policies(self):
    data = self.diagnose()
    finding = [x for x in f.active(data.findings) if x.id == "qos.rxo_mismatch"][0]
    self.assertIn("RELIABILITY", finding.title)
    self.assertIn("OWNERSHIP", finding.title)
    self.assertIn("BEST_EFFORT", finding.observed)


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
class TestTui(LiveFixtureTest):
  """Drive the Textual UI headlessly through every screen."""

  MODE = "healthy"

  def test_navigation_reaches_every_screen(self):
    import asyncio

    from rti_doctor.app import RTIDoctorApp
    from rti_doctor.views.browse import EndpointListScreen, ParticipantListScreen
    from rti_doctor.views.report_screen import ReportScreen, SweepScreen

    app = RTIDoctorApp(self.session, interval=1.0)
    seen = []

    async def drive():
      async with app.run_test() as pilot:
        await pilot.pause(0.8)
        seen.append(type(app.screen))
        await pilot.press("enter")
        await pilot.pause(0.5)
        seen.append(type(app.screen))
        await pilot.press("b")
        await pilot.pause(0.3)
        seen.append(type(app.screen))
        await pilot.press("d")
        await pilot.pause(1.5)
        seen.append(type(app.screen))
        await pilot.press("b")
        await pilot.pause(0.3)
        await pilot.press("D")
        await pilot.pause(8.0)
        seen.append(type(app.screen))
        self.sweep_rows = getattr(app.screen, "rows", None)

    asyncio.run(drive())
    self.assertEqual(
        seen,
        [ParticipantListScreen, EndpointListScreen, ParticipantListScreen,
         ReportScreen, SweepScreen],
        f"navigation went off course: {[c.__name__ for c in seen]}")
    self.assertTrue(self.sweep_rows, "sweep produced no rows")


if __name__ == "__main__":
  unittest.main()
