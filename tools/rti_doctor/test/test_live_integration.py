"""Live integration tests: real participants, real probes, real fixtures.

Gated on Connext being importable and a license being resolvable. These are the
tests that would catch a check firing on a healthy system, or a probe leaking
entities, neither of which a unit test can see.

Run:
  PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
      -m unittest tools/rti_doctor/test/test_live_integration.py
"""

import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)

# domains lives beside this file. Without this the import resolved only when
# some OTHER test module had already put the test directory on sys.path,
# so the suite passed in a full run and failed when run on its own.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E402
import doctor_e2e  # noqa: E402
import domains  # noqa: E402

try:
  import rti.connextdds  # noqa: F401
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False

if CONNEXT_AVAILABLE:
  from rti_doctor import compat, discovery, engine, findings as f, records, report

FIXTURE = os.path.join(HERE, "fixture_publisher.py")


def _domain():
  """Deterministic per suite and port-safe; see test/domains.py."""
  return domains.for_suite("test_live_integration")


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
    return {x.id for x in data.findings}


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
    errors = [x.id for x in data.findings if x.severity >= f.Severity.ERROR]
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

  def test_interactive_report_sections_are_split_by_concern(self):
    sections = report.render_view_sections(self.diagnose())
    self.assertEqual(set(sections), {"overview", "findings", "type", "probe",
                                     "data", "wire", "config"})
    self.assertIn("VERDICT", sections["overview"])
    self.assertIn("FINDINGS", sections["findings"])
    self.assertIn("DISCOVERED TYPE", sections["type"])

  def test_selecting_the_data_tab_streams_live_samples_and_closes_the_reader(self):
    """The live feed, end to end against the real fixture writer.

    Worth a live test rather than a stub: everything that could be wrong here is
    in the parts a stub replaces - that a reader built from the DISCOVERED type
    matches the writer, that `take()` yields samples this fast, and above all
    that leaving the tab actually closes the entity. The last assertion is the
    one that matters: this is the only reader in the tool that outlives the call
    that created it.
    """
    import asyncio

    from textual.app import App
    from textual.widgets import TabbedContent

    from rti_doctor.views.report_screen import ReportScreen

    writer = self.registry.find_writer(self.TOPIC)
    screen = ReportScreen(self.session, endpoint=writer, probe=False)

    class Harness(App):
      def on_mount(self):
        self.push_screen(screen)

    seen = {}

    async def drive():
      app = Harness()
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        seen["before"] = screen.live
        screen.query_one("#report_tabs", TabbedContent).active = "data"
        await pilot.pause()
        seen["opened"] = screen.live
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not screen.live_samples:
          await pilot.pause(0.2)
        seen["samples"] = len(screen.live_samples)
        seen["received"] = screen.live.received
        seen["body"] = str(screen.bodies["data"].render())
        screen.query_one("#report_tabs", TabbedContent).active = "probe"
        await pilot.pause()
        seen["after"] = screen.live
        seen["closed"] = seen["opened"].closed

    asyncio.run(drive())
    self.assertIsNone(seen["before"], "a reader existed before the tab was opened")
    self.assertGreater(seen["samples"], 0,
                       "no live sample arrived from the fixture writer")
    self.assertGreater(seen["received"], 0)
    self.assertIn("STREAMING", seen["body"])
    self.assertIn("sample-", seen["body"],
                  "the feed rendered no member of the received sample")
    self.assertIsNone(seen["after"])
    self.assertTrue(seen["closed"], "leaving the Data tab left the reader open")

  def test_the_live_feed_leaves_no_reader_behind(self):
    """The invariant the probe has always had, now for an entity it does not own.

    Counted on the participant rather than taken from the screen: a feed that
    dropped its reference without closing would satisfy every assertion above
    and still leave a subscription on the topic.
    """
    import asyncio

    from textual.app import App
    from textual.widgets import TabbedContent

    from rti_doctor.views.report_screen import ReportScreen

    if not hasattr(self.participant, "find_subscribers"):
      self.skipTest("this binding cannot enumerate subscribers")
    before = len(self.participant.find_subscribers())
    writer = self.registry.find_writer(self.TOPIC)

    for _ in range(3):
      screen = ReportScreen(self.session, endpoint=writer, probe=False)

      class Harness(App):
        def on_mount(self):
          self.push_screen(screen)

      async def drive():
        app = Harness()
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          screen.query_one("#report_tabs", TabbedContent).active = "data"
          await pilot.pause(0.4)
          screen.query_one("#report_tabs", TabbedContent).active = "overview"
          await pilot.pause()

      asyncio.run(drive())

    self.assertEqual(len(self.participant.find_subscribers()), before,
                     "the live feed leaked a subscriber")

  def test_the_data_tab_shows_the_payload_it_received(self):
    """The Data tab prints what the probe's reader actually took.

    Worth asserting live rather than on a stub: the text can only be there if a
    DynamicData reader built from the DISCOVERED type deserialized a real
    sample from the separate fixture process. `sample-N` is `populate_rich`'s
    label member, so finding it here means the payload survived the round trip
    and not merely that a section rendered.
    """
    sections = report.render_view_sections(self.diagnose())
    self.assertIn("SAMPLE DATA", sections["data"])
    self.assertIn("sample 1", sections["data"])
    self.assertIn("sample-", sections["data"],
                  "the Data tab rendered no member of the received sample")

  def test_report_counters_are_real_not_na(self):
    """Regression: EventCount64 counters rendered as 'not available'."""
    text = report.render_text(self.diagnose())
    line = [l for l in text.splitlines() if "received_sample_count" in l]
    self.assertTrue(line, "received_sample_count missing from the report")
    self.assertNotIn("n/a", line[0], "a real counter was reported as unavailable")

  def test_the_report_can_be_read_back_by_the_e2e_harness(self):
    """The text report is the only output contract, so it must parse.

    `--format json` used to be the machine-readable path and this test parsed
    it. The vendor suites now read the text report through
    `doctor_e2e.parse_report`, so that is what has to survive a real run.
    """
    data = self.diagnose()
    completed = subprocess.CompletedProcess(
        ["doctor"], 0, report.render_text(data), "")
    parsed = doctor_e2e.parse_report(completed)
    self.assertTrue(parsed["verdict"])
    self.assertEqual({item["id"] for item in parsed["findings"]}, self.ids(data))

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

  def test_reports_missing_type_and_links_the_consequence(self):
    data = self.diagnose()
    reported = self.ids(data)
    self.assertIn("type.no_type_info", reported)
    # Both are reported. The consequence is annotated with its likely cause
    # rather than removed: hiding it also removed it from the counts.
    self.assertIn("probe.not_created", reported)
    links = {x.id: x.explained_by for x in data.findings}
    self.assertIn("type.no_type_info", links.get("probe.not_created", ()))

  def test_verdict_says_not_probed(self):
    self.assertIn("not probed", self.diagnose().verdict)


class TestLargeData(LiveFixtureTest):
  MODE = "large_data"

  def test_fragmentation_is_reported_without_a_false_error(self):
    data = self.diagnose()
    fragmentation = [x for x in data.findings
                     if x.id == "data.fragmentation"]
    self.assertTrue(fragmentation, "large data did not report fragmentation at all")
    self.assertEqual(fragmentation[0].severity, f.Severity.INFO,
                     "healthy large data must not be reported as an error")

  def test_large_sample_still_deserializes(self):
    """A 200000-element sequence<octet> is read whole, and says so.

    The walk reads a primitive collection with one bulk read that covers every
    element however long it is, so exceeding MAX_ELEMENTS_PER_COLLECTION must
    not mark the walk truncated - only the aggregate-element branch, which
    genuinely stops at the cap, can do that. Marking it truncated here reported
    a fully-read healthy large-data topic as payload PARTIAL.
    """
    data = self.diagnose()
    self.assertIn("payload FULL", data.verdict)
    self.assertFalse(data.probe_result.walk.truncated,
                     "a bulk-read primitive collection was not actually truncated")


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
    finding = [x for x in data.findings if x.id == "qos.rxo_mismatch"][0]
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
    from rti_doctor.views.browse import EndpointListScreen
    from rti_doctor.views.system_overview import (IssueListScreen,
                IssueSeverityScreen,
                            SystemOverviewScreen,
                            TopologyHealthScreen)

    app = RTIDoctorApp(self.session, interval=1.0)
    seen = []

    async def drive():
      async with app.run_test() as pilot:
        await pilot.pause(0.8)
        seen.append(type(app.screen))
        await pilot.press("enter")
        await pilot.pause(0.5)
        seen.append(type(app.screen))
        await pilot.press("enter")
        await pilot.pause(0.5)
        seen.append(type(app.screen))
        self.selected_issue_severity = app.screen.severity
        await pilot.press("b")
        await pilot.pause(0.3)
        seen.append(type(app.screen))
        await pilot.press("b")
        await pilot.pause(0.3)
        seen.append(type(app.screen))
        await pilot.press("down", "enter")
        await pilot.pause(0.5)
        seen.append(type(app.screen))
        await pilot.press("enter")
        await pilot.pause(0.3)
        seen.append(type(app.screen))

    asyncio.run(drive())
    self.assertEqual(
        seen,
        [SystemOverviewScreen, IssueSeverityScreen, IssueListScreen,
         IssueSeverityScreen, SystemOverviewScreen,
         TopologyHealthScreen, EndpointListScreen],
        f"navigation went off course: {[c.__name__ for c in seen]}")
    self.assertEqual(self.selected_issue_severity, f.Severity.ERROR)

  def test_opening_a_report_renders_it_and_asks_before_capturing(self):
    """Drill all the way to ReportScreen and confirm it renders.

    The navigation test stops at EndpointListScreen, so nothing exercised
    ReportScreen's own body. Deleting SweepScreen from that module took
    `import asyncio` with it while ReportScreen still used it for
    `asyncio.to_thread`, and the whole suite stayed green - the screen would
    have raised NameError the first time an operator opened a report.

    `o` on the topology screen opens a *probing* report, so it is also the
    live check on the entry flow: the static findings are rendered before the
    capture question is asked, the picker is what the operator lands on, and
    dismissing it leaves a report rather than a dead end.
    """
    import asyncio

    from rti_doctor.views.report_screen import (CaptureInterfaceScreen,
                                                ReportScreen)

    from rti_doctor.app import RTIDoctorApp

    app = RTIDoctorApp(self.session, interval=1.0)
    seen = {}

    async def drive():
      async with app.run_test() as pilot:
        await pilot.pause(0.8)
        await pilot.press("down", "enter")     # DDS Topology & Health
        await pilot.pause(0.6)
        await pilot.press("3")                 # writers
        await pilot.pause(0.4)

        # `o` is the cheap look: a report, no probe, no capture, no question.
        await pilot.press("o")
        await pilot.pause(1.5)
        seen["passive"] = type(app.screen)
        seen["passive_body"] = str(app.screen.body.render())
        await pilot.press("escape")
        await pilot.pause(0.5)

        # Enter is the full diagnostic, so it asks first - on top of a report
        # whose static findings are already rendered.
        await pilot.press("enter")
        await pilot.pause(1.5)
        seen["asked"] = type(app.screen)
        seen["body_behind_the_picker"] = str(app.screen_stack[-2].body.render())
        await pilot.press("escape")            # dismissal is not an answer
        await pilot.pause(0.5)
        seen["screen"] = type(app.screen)
        seen["answered"] = self.session.capture_choice_made

    asyncio.run(drive())
    self.assertIs(seen["passive"], ReportScreen)
    self.assertIs(seen["asked"], CaptureInterfaceScreen)
    self.assertIs(seen["screen"], ReportScreen)
    self.assertFalse(seen["answered"])
    for body in (seen["passive_body"], seen["body_behind_the_picker"]):
      self.assertIn("RTI DOCTOR INTEROP REPORT", body)
      self.assertIn("VERDICT", body)
      self.assertNotIn("Static checks failed", body)

  def test_refresh_and_metrics_survive_navigating_away_mid_scan(self):
    """The refresh actions used to be bare asyncio.create_task.

    A bare task is only weakly referenced by the loop and nothing cancels it
    when the screen is popped, so a scan that finished after the operator
    navigated away wrote into unmounted widgets. Popping immediately after
    pressing `r` is the case that exposed it.
    """
    import asyncio

    from rti_doctor.app import RTIDoctorApp
    from rti_doctor.views.system_overview import (MetricsScreen,
                                                  SystemOverviewScreen)

    app = RTIDoctorApp(self.session, interval=1.0)
    seen = {}

    async def drive():
      async with app.run_test() as pilot:
        await pilot.pause(0.8)
        await pilot.press("m")
        await pilot.pause(0.5)
        seen["metrics"] = type(app.screen)
        seen["body"] = str(app.screen.body.render())
        # Refresh, then leave before it can finish.
        await pilot.press("r")
        await pilot.press("b")
        await pilot.pause(0.8)
        seen["after"] = type(app.screen)
        # The overview must still be usable afterwards.
        await pilot.press("r")
        await pilot.pause(0.8)
        seen["final"] = type(app.screen)

    asyncio.run(drive())
    self.assertIs(seen["metrics"], MetricsScreen)
    self.assertIn("Observed Domain Metrics", seen["body"])
    self.assertIn("Remote DataWriters", seen["body"])
    self.assertIs(seen["after"], SystemOverviewScreen)
    self.assertIs(seen["final"], SystemOverviewScreen)


if __name__ == "__main__":
  unittest.main()
