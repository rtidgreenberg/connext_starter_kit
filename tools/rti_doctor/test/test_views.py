"""Unit tests for the system screens' shared refresh-failure convention.

These drive real Textual screens headlessly against a stub session, so they need
no Connext license and no DDS domain: the behaviour under test is what the
screen does when `session.system_scan` raises, which is independent of why it
raised.
"""

import asyncio
import logging
import os
import sys
import time
import unittest
from unittest import mock

from textual.app import App

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import engine, findings, records, report, system_scan  # noqa: E402
from rti_doctor.views import browse, report_screen, system_overview  # noqa: E402

TOPOLOGY = {
    "participants": 2, "readers": 1, "writers": 1, "topic_count": 1,
    "topics": ["Telemetry"], "source": "discovery registry",
    "completion_note": "observed passively",
}


def snapshot(captured_at=1000.0):
  return system_scan.SystemScanSnapshot(
      captured_at=captured_at, topology=TOPOLOGY, issues=())


def empty_snapshot_with_error(captured_at=1000.0):
  issue = system_scan.SystemIssue(
      key="domain:blind.domain_tag",
      severity=findings.Severity.ERROR,
      finding_ids=("blind.domain_tag",),
  title="Domain tag blocks discovery",
  observed="The participant has domain tag prod.",
  root_cause="Tagged and untagged participants do not discover each other.",
  recommendation="Use the same domain tag on all participants.",
  topic_name=None,
  scope="domain",
  writer_keys=(),
  reader_keys=(),
  participant_keys=(),
  evidence={})
  topology = dict(TOPOLOGY, participants=0, readers=0, writers=0,
                  topic_count=0, topics=[])
  return system_scan.SystemScanSnapshot(
      captured_at=captured_at, topology=topology, issues=(issue,))


class StubRegistry:
  """Only what `TopologyHealthScreen._render_table` reaches for."""

  endpoints = {}
  participants = {}

  def participant_list(self):
    return []

  def endpoints_for(self, key):
    return []

  def readers(self):
    return []

  def writers(self):
    return []

  def topic_names(self):
    return []

  def endpoints_on_topic(self, topic):
    return []


class StubSession:
  """A session whose scan can be made to fail on demand."""

  def __init__(self):
    self.domain_id = 7
    self.registry = StubRegistry()
    self.fail = None
    self.calls = 0

  def system_scan(self, scope=None, max_age=0.0):
    self.calls += 1
    if self.fail is not None:
      raise self.fail
    return snapshot()


class Harness(App):
  """Hosts one screen so it can be driven by key press, as an operator would."""

  def __init__(self, screen):
    super().__init__()
    self._target = screen

  def on_mount(self):
    self.push_screen(self._target)


SCREENS = (
    ("SystemOverviewScreen", system_overview.SystemOverviewScreen),
    ("IssueSeverityScreen", system_overview.IssueSeverityScreen),
    ("IssueListScreen", system_overview.IssueListScreen),
    ("TopologyHealthScreen", system_overview.TopologyHealthScreen),
    ("MetricsScreen", system_overview.MetricsScreen),
)


def status_text(screen):
  return str(screen.status.render())


class TestRefreshFailureIsVisible(unittest.TestCase):

  def test_empty_domain_with_active_issue_shows_its_error_count(self):
    """A discovery blind spot is the report, not an empty state."""
    session = StubSession()
    active_snapshot = empty_snapshot_with_error()
    session.system_scan = lambda captured_at=None, max_age=0.0: active_snapshot
    collected = {}

    async def run():
      for name, screen in (
          ("summary", system_overview.SystemOverviewScreen(session)),
          ("issues", system_overview.IssueListScreen(session, active_snapshot)),
      ):
        app = Harness(screen)
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          collected[name] = (
              str(screen.summary.render()) if name == "summary"
              else status_text(screen))

    asyncio.run(run())
    self.assertIn("No DDS discovered", collected["summary"])
    self.assertIn("1 Errors", collected["summary"])
    self.assertIn("No DDS discovered", collected["issues"])
    self.assertIn("1 Errors", collected["issues"])

  def test_issue_screens_do_not_offer_deep_diagnosis(self):
    for screen_class in (system_overview.IssueListScreen,
                         system_overview.IssueDetailScreen):
      actions = {binding[1] for binding in screen_class.BINDINGS}
      self.assertNotIn("debug", actions)

  def setUp(self):
    # Every test here provokes the error path on purpose, and the screens log
    # it. Keep that out of the suite's output; one test below asserts the log
    # record is still emitted.
    logging.disable(logging.CRITICAL)
    self.addCleanup(logging.disable, logging.NOTSET)

  def drive(self, screen_class, steps):
    """Mount `screen_class`, run `steps(pilot, session, screen)`, return results."""
    session = StubSession()
    collected = {}

    async def run():
      screen = screen_class(session)
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await steps(pilot, session, screen, collected)

    asyncio.run(run())
    return collected

  async def _press_refresh(self, pilot, app=None):
    await pilot.press("r")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()

  def test_a_failed_refresh_says_so_on_every_system_screen(self):
    """Stale data with no marker is the failure mode this closes.

    `_spawn` runs refreshes with `exit_on_error=False` so one failure cannot
    tear down the app. Without a status convention that also made the failure
    invisible: the worker died, the screen kept its last render, and a scan that
    had been failing for minutes looked exactly like one that found nothing to
    change.
    """
    for name, screen_class in SCREENS:
      with self.subTest(screen=name):
        async def steps(pilot, session, screen, out):
          out["before"] = status_text(screen)
          out["good"] = screen.snapshot
          session.fail = RuntimeError("participant handle is closed")
          await self._press_refresh(pilot)
          out["after"] = status_text(screen)
          out["kept"] = screen.snapshot

        result = self.drive(screen_class, steps)
        self.assertNotIn("Scan failed", result["before"])
        self.assertIn("Scan failed", result["after"])
        self.assertIn("participant handle is closed", result["after"])
        # The last good data stays on screen, labelled as old rather than
        # blanked - and it is still the snapshot from before the failure.
        self.assertIn("still showing the snapshot from", result["after"])
        self.assertIsNotNone(result["kept"])
        self.assertIs(result["kept"], result["good"])

  def test_the_first_scan_failing_does_not_claim_stale_data_it_never_had(self):
    session_failure = RuntimeError("domain 7 is unreachable")

    class FailingSession(StubSession):
      def __init__(self):
        super().__init__()
        self.fail = session_failure

    collected = {}

    async def run():
      screen = system_overview.IssueListScreen(FailingSession())
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        collected["status"] = status_text(screen)
        collected["snapshot"] = screen.snapshot

    asyncio.run(run())
    self.assertIn("Scan failed", collected["status"])
    self.assertIn("domain 7 is unreachable", collected["status"])
    self.assertIn("no data has been collected yet", collected["status"])
    self.assertIsNone(collected["snapshot"])

  def test_the_marker_clears_when_the_scan_recovers(self):
    """A transient failure must not leave a permanent red line."""
    for name, screen_class in SCREENS:
      with self.subTest(screen=name):
        async def steps(pilot, session, screen, out):
          session.fail = RuntimeError("transient")
          await self._press_refresh(pilot)
          out["failed"] = status_text(screen)
          session.fail = None
          await self._press_refresh(pilot)
          out["recovered"] = status_text(screen)
          out["error"] = screen.scan_error
          out["snapshot"] = screen.snapshot

        result = self.drive(screen_class, steps)
        self.assertIn("Scan failed", result["failed"])
        self.assertNotIn("Scan failed", result["recovered"])
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["snapshot"])

  def test_a_refresh_that_fails_after_the_scan_is_reported_too(self):
    """The scan is not the only thing a refresh does.

    `_scan` covers the scan itself; `_spawn`'s guard covers everything else the
    refresh coroutine touches, so a rendering failure cannot be silent either.
    """
    async def steps(pilot, session, screen, out):
      def explode(*args, **kwargs):
        raise ValueError("row key vanished")

      screen._render_snapshot = explode
      await self._press_refresh(pilot)
      out["status"] = status_text(screen)

    result = self.drive(system_overview.IssueListScreen, steps)
    self.assertIn("Scan failed", result["status"])
    self.assertIn("row key vanished", result["status"])

  def test_the_failure_is_logged_as_well_as_shown(self):
    """The status line is for the operator; the log is for the bug report."""
    logging.disable(logging.NOTSET)
    self.addCleanup(logging.disable, logging.CRITICAL)

    async def steps(pilot, session, screen, out):
      session.fail = RuntimeError("scan thread died")
      await self._press_refresh(pilot)

    with self.assertLogs(level="ERROR") as captured:
      self.drive(system_overview.MetricsScreen, steps)
    self.assertTrue(any("MetricsScreen" in line and "scan thread died" in line
                        for line in captured.output), captured.output)


class TestOpenReportMeansOneThing(unittest.TestCase):
  """`o` is the cheap look on every screen that has it; Enter is the full one.

  On the topology screen `o` was bound to the same action `Enter` already
  called, so it was both a duplicate and - uniquely - the *probing* one, while
  `EndpointListScreen` and `TopicEndpointsScreen` have always used `o` for a
  `probe=False` report. That left the one screen an operator skims endpoints on
  with no way into a report that does not probe, which matters more now that
  entering also asks about capturing.
  """

  def bindings(self, screen_class):
    return {key: action for key, action, *_ in screen_class.BINDINGS}

  def test_o_never_opens_a_probing_report(self):
    for screen_class, action in (
        (system_overview.TopologyHealthScreen, "passive_report"),
        (system_overview.TopicEndpointsScreen, "open_report"),
        (browse.EndpointListScreen, "open_report")):
      with self.subTest(screen=screen_class.__name__):
        self.assertEqual(self.bindings(screen_class).get("o"), action)

  def test_o_and_enter_are_different_actions_on_the_topology_screen(self):
    """The duplicate: `o` used to resolve to what row-selection already did."""
    self.assertNotEqual(
        self.bindings(system_overview.TopologyHealthScreen).get("o"),
        "open_report")

  def fake_app(self):
    """`Screen.app` is a read-only property, so it is patched on the class."""
    app = mock.Mock()
    patcher = mock.patch.object(system_overview.TopologyHealthScreen, "app",
                                new_callable=mock.PropertyMock,
                                return_value=app)
    patcher.start()
    self.addCleanup(patcher.stop)
    return app

  def test_o_opens_a_passive_report_for_a_selected_writer(self):
    session = StubSession()
    session.registry = StubRegistry()
    endpoint = FakeEndpoint("w1", "Writer")
    session.registry.endpoints = {"w1": endpoint}
    screen = system_overview.TopologyHealthScreen(session)
    screen.mode = "writers"
    screen.selected_key = "w1"
    app = self.fake_app()

    with mock.patch.object(system_overview, "ReportScreen") as report_screen_cls:
      screen.action_passive_report()

    report_screen_cls.assert_called_once_with(session, endpoint=endpoint,
                                              probe=False)
    app.push_screen.assert_called_once()

  def test_o_on_a_participant_or_topic_row_says_what_it_applies_to(self):
    """Those rows are navigation, not endpoints; Enter still drills into them."""
    app = self.fake_app()
    for mode in ("participants", "topics"):
      with self.subTest(mode=mode):
        screen = system_overview.TopologyHealthScreen(StubSession())
        screen.mode = mode
        screen.selected_key = "p1"
        screen.status = mock.Mock()

        screen.action_passive_report()

        app.push_screen.assert_not_called()
        self.assertIn("reader or writer row",
                      str(screen.status.update.call_args[0][0]))


class TestTopologyBeforeAFirstSuccessfulScan(unittest.TestCase):
  """H5: `snapshot is None` is a reachable, documented state on this screen.

  A failed first scan leaves it None and tells the operator to press `r`. Every
  key that reads the snapshot used to raise `AttributeError` from inside a
  Textual action handler, which kills the interaction with nothing on screen
  saying why - and `s` left a zero-byte report file, because the file was opened
  before the raise.
  """

  def setUp(self):
    logging.disable(logging.CRITICAL)
    self.addCleanup(logging.disable, logging.NOTSET)

  def _press(self, keys, tmp_path=None):
    session = StubSession()
    session.fail = RuntimeError("domain 7 is unreachable")
    collected = {}

    async def run():
      screen = system_overview.TopologyHealthScreen(session)
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        collected["first_scan"] = screen.snapshot
        for key in keys:
          await pilot.press(key)
          await app.workers.wait_for_complete()
          await pilot.pause()
        collected["status"] = status_text(screen)
        collected["screens"] = len(app.screen_stack)

    asyncio.run(run())
    return collected

  def test_no_view_key_raises_and_each_says_why(self):
    for key in ("1", "2", "3", "4"):
      with self.subTest(key=key):
        result = self._press([key])
        self.assertIsNone(result["first_scan"])
        self.assertIn("No topology has been collected yet", result["status"])
        self.assertIn("Press r to retry", result["status"])

  def test_linked_issues_does_not_push_an_empty_screen(self):
    result = self._press(["i"])
    self.assertIn("No topology has been collected yet", result["status"])
    # Harness screen + the topology screen, and nothing pushed on top: an issue
    # list built from no snapshot would be an empty list presented as a result.
    self.assertEqual(result["screens"], 2)

  def test_save_writes_no_file_at_all(self):
    with mock.patch("builtins.open", side_effect=AssertionError(
        "a report was opened with no snapshot to write into it")) as opened:
      result = self._press(["s"])
    opened.assert_not_called()
    self.assertIn("No topology has been collected yet", result["status"])

  def test_the_scan_error_is_still_named(self):
    """The operator needs the reason, not just that there is no data."""
    result = self._press(["1"])
    self.assertIn("domain 7 is unreachable", result["status"])

  def test_a_recovered_scan_renders_normally(self):
    """Guards the guard: the message must not outlive the failure."""
    session = StubSession()
    session.fail = RuntimeError("domain 7 is unreachable")
    collected = {}

    async def run():
      screen = system_overview.TopologyHealthScreen(session)
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        session.fail = None
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        collected["status"] = status_text(screen)
        collected["snapshot"] = screen.snapshot

    asyncio.run(run())
    self.assertIsNotNone(collected["snapshot"])
    self.assertIn("View: Writers", collected["status"])
    self.assertNotIn("No topology has been collected yet", collected["status"])


class FakeEndpoint:
  def __init__(self, key, kind, topic_name="Telemetry", type_name="TelemetryType"):
    self.key = key
    self.kind = kind
    self.topic_name = topic_name
    self.type_name = type_name
    # What the report's PEER section reads off an endpoint. A stub missing
    # these renders as an exception the screen catches, so a test asserting on
    # the rendered text would be asserting on the failure message instead.
    self.type = None
    self.type_state = records.TYPE_UNAVAILABLE
    self.type_resolution_delay = None
    self.representation = ()
    self.unicast_locators = ()

  @property
  def is_writer(self):
    return self.kind == "Writer"


def issue_with(writer_keys=(), reader_keys=(), evidence=None):
  return system_scan.SystemIssue(
      key="issue", severity=findings.Severity.ERROR,
      finding_ids=("qos.rxo_mismatch",),
      title="QoS incompatible (RELIABILITY): writer-app -> reader-app",
      observed="", root_cause="", recommendation="",
      topic_name="Telemetry", scope="pair",
      writer_keys=writer_keys, reader_keys=reader_keys, participant_keys=(),
      evidence=evidence or {})


class TestPairedIssueOpensAReport(unittest.TestCase):
  """`o` on an issue that names two endpoints.

  `qos.rxo_mismatch` always names a writer AND a reader, and the detail screen
  required exactly one across both roles - so the flagship ERROR could never
  open a report at all, while the list screen silently opened the writer and
  hid the reader-driven constraint.
  """

  def setUp(self):
    self.session = StubSession()
    self.session.registry = StubRegistry()
    self.session.registry.endpoints = {
        "w1": FakeEndpoint("w1", "Writer"),
        "r1": FakeEndpoint("r1", "Reader"),
    }

  def _choices(self, issue):
    return system_overview._issue_endpoints(self.session, issue)

  def test_a_pair_offers_both_sides_with_their_rxo_roles(self):
    choices = self._choices(issue_with(
        writer_keys=("w1",), reader_keys=("r1",),
        evidence={"writer": "writer-app w1", "reader": "reader-app r1"}))
    self.assertEqual([role for role, _, _ in choices],
                     ["Writer (offers)", "Reader (requests)"])
    self.assertEqual([label for _, label, _ in choices],
                     ["writer-app w1", "reader-app r1"])
    self.assertEqual([endpoint.key for _, _, endpoint in choices], ["w1", "r1"])

  def test_a_single_endpoint_issue_needs_no_choice(self):
    self.assertEqual(len(self._choices(issue_with(writer_keys=("w1",)))), 1)

  def test_an_endpoint_that_departed_is_not_offered(self):
    """The snapshot is a moment in time; the registry has moved on."""
    choices = self._choices(issue_with(writer_keys=("w1",), reader_keys=("gone",)))
    self.assertEqual([endpoint.key for _, _, endpoint in choices], ["w1"])

  def _opened(self, issue):
    """What `_open_issue_report` pushes, and what it says if it pushes nothing.

    `Screen.app` is read-only in Textual, so this drives the routing through a
    stand-in with the two attributes the function touches - which is the reason
    the routing is a module function and not a method on one screen.
    """
    screen = mock.Mock()
    system_overview._open_issue_report(screen, self.session, issue)
    pushed = (screen.app.push_screen.call_args[0][0]
              if screen.app.push_screen.call_args else None)
    said = (screen.status.update.call_args[0][0]
            if screen.status.update.call_args else "")
    return pushed, said

  def test_an_issue_naming_no_live_endpoint_says_so(self):
    pushed, said = self._opened(issue_with(writer_keys=("gone",)))
    self.assertIsNone(pushed)
    self.assertIn("no endpoint still in discovery", said)

  def test_a_pair_asks_rather_than_defaulting_to_the_writer(self):
    pushed, _ = self._opened(
        issue_with(writer_keys=("w1",), reader_keys=("r1",)))
    self.assertIsInstance(pushed, system_overview.EndpointChoiceScreen)
    self.assertEqual([role for role, _, _ in pushed.choices],
                     ["Writer (offers)", "Reader (requests)"])

  def test_one_endpoint_opens_its_report_directly(self):
    pushed, _ = self._opened(issue_with(writer_keys=("w1",)))
    self.assertNotIsInstance(pushed, system_overview.EndpointChoiceScreen)

  def test_both_issue_screens_route_through_the_same_action(self):
    """The list screen used to open the writer while the detail screen refused.

    Two answers to `o` on the same row is the half of this the operator
    actually notices.
    """
    issue = issue_with(writer_keys=("w1",), reader_keys=("r1",))
    detail = system_overview.IssueDetailScreen(self.session, snapshot(), issue)
    listing = system_overview.IssueListScreen(self.session, snapshot())
    listing._selected_issue = lambda: issue

    with mock.patch.object(system_overview, "_open_issue_report") as opened:
      detail.action_open_report()
      listing.action_open_report()
    self.assertEqual([call[0][2] for call in opened.call_args_list],
                     [issue, issue])


class CaptureStubSession(StubSession):
  """Records what a report asked of it; creates no DDS entity and no tshark.

  `capture_interface` is the answered-up-front case (`--capture-interface`);
  leaving it None is the unanswered case, where a report opening will ask.
  """

  def __init__(self, capture_interface=None):
    super().__init__()
    self.probe_timeout = 10.0
    self.capture_interface = capture_interface
    self.capture_choice_made = capture_interface is not None
    self.capture_off_reason = None
    self.pass_deadline = 0.0
    self.capture_artifacts = []
    self.retained_artifacts = set()
    self.calls = []
    self.wire_evidence = {"source": "/tmp/rti_doctor_captures/one.pcapng",
                          "packets": 12}

  def record_capture_choice(self, interface):
    self.capture_interface = interface
    self.capture_choice_made = True
    self.capture_off_reason = None

  def disable_capture(self, reason):
    self.capture_off_reason = reason
    self.capture_interface = None
    self.capture_choice_made = True

  def retain_capture(self, path):
    if path:
      self.retained_artifacts.add(path)

  def claim_pass(self, seconds):
    self.pass_deadline = time.monotonic() + seconds

  def release_pass(self):
    self.pass_deadline = 0.0

  def pass_in_flight(self):
    return time.monotonic() < self.pass_deadline

  def capture_path(self, timestamp=None):
    return "/tmp/rti_doctor_captures/one.pcapng"

  def diagnose_endpoint(self, endpoint, probe=True, capture_interface=None,
                        capture_seconds=None, capture_path=None):
    self.calls.append({"endpoint": endpoint.key, "probe": probe,
                       "capture_interface": capture_interface,
                       "capture_seconds": capture_seconds,
                       "capture_path": capture_path})
    if capture_interface:
      self.capture_artifacts.append(capture_path)
    return report.ReportData(
        domain_id=7, scope=f"topic '{endpoint.topic_name}'", all_findings=[],
        endpoint=endpoint,
        wire_evidence=self.wire_evidence if capture_interface else None,
        capture_interface=capture_interface)


class TestReportCaptureIsAnOperatorAction(unittest.TestCase):
  """H8, amended: capture is consented to on entry, never assumed.

  Every writer report used to pass `"any"` straight into `diagnose_endpoint`, so
  navigating to a report spawned `tshark -i any` - undisclosed, unconditional,
  privileged, one PCAPNG and one log per report, seconds of added wall clock,
  and on a host without capture rights a wire-evidence error in every report.
  A report now offers the full diagnostic on entry, which is not that: it names
  the interface first, takes Skip for an answer, and remembers either.
  """

  def drive(self, session, endpoint, steps, probe=True):
    collected = {}

    async def run():
      screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=probe)
      app = Harness(screen)
      # The picker can now open during on_mount, and it enumerates through
      # `tshark -D`. Patched for every test in this class so none of them
      # shells out, and so the ones that never reach the picker cannot start
      # doing so silently.
      with mock.patch.object(report_screen.wire, "capture_interfaces",
                             return_value=((("1", "lo"), ("2", "eth0")), None)):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          await steps(pilot, screen, collected)

    asyncio.run(run())
    return collected

  async def _choose(self, pilot, label):
    """Pick the picker row with this label, and wait for what it starts."""
    picker = pilot.app.screen
    row = [index for index, choice in enumerate(picker.choices)
           if choice[1] == label]
    picker.table.move_cursor(row=row[0])
    await pilot.press("enter")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()

  async def _settle(self, pilot, screen, out):
    """Take the finished state of a report that ran its pass on entry."""
    await pilot.pause()
    out["said"] = status_text(screen)
    out["screen"] = pilot.app.screen

  async def _press_capture(self, pilot, screen, out):
    # Every status line the capture produced, in order. The announcement and
    # the result both land on one widget, and the worker can finish before the
    # test regains control, so reading the widget alone would only ever see the
    # last of them - and what this has to prove is that the operator was told
    # what was about to happen *before* tshark ran.
    said = []
    original = screen.status.update

    def record(text):
      said.append(str(text))
      return original(text)

    screen.status.update = record
    out["said"] = said
    await pilot.press("c")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    out["announced"] = said[0] if said else ""
    out["after"] = said[-1] if said else ""

  def test_opening_a_report_asks_before_capturing_anything(self):
    """The consent, before any tshark: a report with no answer yet must ask."""
    session = CaptureStubSession()

    async def steps(pilot, screen, out):
      out["screen"] = pilot.app.screen

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertIsInstance(result["screen"], report_screen.CaptureInterfaceScreen)
    # Only the static pass ran while the question is still open.
    self.assertEqual(session.calls,
                     [{"endpoint": "w1", "probe": False,
                       "capture_interface": None, "capture_seconds": None,
                       "capture_path": None}])

  def test_an_answered_report_captures_on_entry_in_one_pass(self):
    """The point of the change: one pass, and it carries both halves.

    Capture used to be a second `diagnose_endpoint` with `probe=True`, because
    a capture with nothing on the wire is an empty file - so the full report
    cost two probes, one on mount and one under the capture.
    """
    session = CaptureStubSession(capture_interface="eth0")
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertEqual(probing[0]["capture_interface"], "eth0")
    self.assertEqual(probing[0]["capture_seconds"], 10.0)
    # The file named on screen is the file the capture is told to write.
    self.assertEqual(probing[0]["capture_path"],
                     os.path.abspath("/tmp/rti_doctor_captures/one.pcapng"))
    self.assertIn("Full diagnostic complete", result["said"])
    self.assertIn("12 matching frames", result["said"])

  def test_the_entry_announcement_names_what_is_about_to_run(self):
    """Said before tshark is spawned: where, for how long, and onto what disk.

    A pure helper rather than an intercepted widget: this text is written
    during `on_mount`, before a test could install a recorder on the status.
    """
    session = CaptureStubSession("eth0")
    screen = report_screen.ReportScreen(session, endpoint=FakeEndpoint("w1", "Writer"))
    said = screen._pass_announcement("eth0", True, 10.0, "/tmp/one.pcapng")
    for expected in ("eth0", "/tmp/one.pcapng", "10s", ".tshark.log",
                     "privileges", "probing"):
      self.assertIn(expected, said)

  def test_a_reader_report_probes_on_entry_too(self):
    """The reader probe existed and was unreachable from the TUI.

    `probe_endpoint` already dispatches a non-writer to `probe_reader_endpoint`,
    and the engine already picks the right checks for the result; the
    `is_writer` gate on this screen was the only thing in the way. A reader
    probe answers what no static check can - does anything match this reader.
    """
    session = CaptureStubSession("lo")

    async def steps(pilot, screen, out):
      out["said"] = screen._pass_announcement("lo", True, 10.0, "/x")

    result = self.drive(session, FakeEndpoint("r1", "Reader"), steps)
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertEqual(probing[0]["capture_interface"], "lo")
    # A reader probe creates a writer that never publishes, so the copy must
    # not promise user data the Wire tab will then contradict.
    self.assertIn("creating a writer", result["said"])

  def test_a_capture_that_never_started_turns_capture_off_for_the_session(self):
    """One tshark refusal, not one per report.

    The harm is report content: a failed capture attaches a wire-evidence error
    to every report that tries, in reports nobody asked to include one in.
    """
    session = CaptureStubSession("lo")
    session.wire_evidence = {"source": "one.pcapng", "error_stage": "start",
                             "error": "you don't have permission to capture"}
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    self.assertIn("no packet evidence", result["said"])
    self.assertIn("permission", result["said"])
    self.assertIn("off for this session", result["said"])
    self.assertIsNotNone(session.capture_off_reason)
    self.assertIsNone(session.capture_interface)

    # The next report probes and carries no wire evidence at all.
    session.calls = []
    self.drive(session, FakeEndpoint("w2", "Writer"), self._settle)
    self.assertEqual([call["capture_interface"] for call in session.calls],
                     [None, None])
    self.assertTrue([call for call in session.calls if call["probe"]])

  def test_a_capture_that_ran_and_then_failed_stays_this_report_s_problem(self):
    """The opposite mistake: one bad ending must not disable a working host.

    `stop` covers "tshark did not exit after termination and was killed" and a
    non-zero exit part-way through - transient, and no statement about whether
    the next capture will work. Only a capture that never started is a property
    of the host.
    """
    session = CaptureStubSession("lo")
    session.wire_evidence = {
        "source": "one.pcapng", "error_stage": "stop",
        "error": "tshark did not exit after termination and was killed"}
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    self.assertIn("no packet evidence", result["said"])
    self.assertIn("Press c to try again", result["said"])
    self.assertNotIn("off for this session", result["said"])
    self.assertIsNone(session.capture_off_reason)
    self.assertEqual(session.capture_interface, "lo")

    # And the next report still captures on the interface it was given.
    session.calls = []
    self.drive(session, FakeEndpoint("w2", "Writer"), self._settle)
    self.assertEqual([call["capture_interface"] for call in session.calls
                      if call["probe"]], ["lo"])

  def test_a_finished_pass_never_leaves_the_session_latched(self):
    """A latch left set dead-ends every later report, `c` and `C` included.

    It is cleared inside the worker thread so a cancelled worker still releases
    it, which means the coroutine's own `finally` is the only thing covering a
    coroutine cancelled before the thread is dispatched.
    """
    session = CaptureStubSession("lo")
    self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    self.assertFalse(session.pass_in_flight())

    # Including when the pass raises rather than returning.
    session.diagnose_endpoint = mock.Mock(side_effect=RuntimeError("boom"))
    result = self.drive(session, FakeEndpoint("w2", "Writer"), self._settle)
    self.assertIn("Diagnostic pass failed", result["said"])
    self.assertFalse(session.pass_in_flight())

  def test_a_second_c_while_capturing_does_not_start_another(self):
    session = CaptureStubSession("lo")

    async def steps(pilot, screen, out):
      screen.capturing = True
      session.calls = []
      await pilot.press("c")
      await pilot.pause()
      out["said"] = status_text(screen)

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertIn("already running", result["said"])
    self.assertEqual(session.calls, [])

  def test_c_during_the_pass_waits_rather_than_racing_it(self):
    """Two probes on one topic would each observe the other's traffic."""
    session = CaptureStubSession("lo")

    async def steps(pilot, screen, out):
      screen.probing = True
      session.calls = []
      await pilot.press("c")
      await pilot.pause()
      out["said"] = status_text(screen)

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertIn("still running", result["said"])
    self.assertEqual(session.calls, [])

  def test_a_pass_running_on_another_report_blocks_this_one(self):
    """Workers survive navigation, so the guard has to outlive the screen.

    `asyncio.to_thread` cannot be cancelled: popping a report leaves its pass
    running, tshark and all. A per-screen flag cannot see that.
    """
    session = CaptureStubSession("lo")
    session.claim_pass(60.0)
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    self.assertIn("another report", result["said"])
    self.assertEqual([call for call in session.calls if call["probe"]], [])

  def test_a_passive_report_neither_probes_nor_asks(self):
    """`o` and the issue-driven pushes must stay a keypress-cheap screen."""
    session = CaptureStubSession("lo")

    async def steps(pilot, screen, out):
      out["screen"] = pilot.app.screen
      await self._press_capture(pilot, screen, out)

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps, probe=False)
    self.assertIsInstance(result["screen"], report_screen.ReportScreen)
    # `c` still collects evidence, and still does not upgrade it to a probe.
    requested = [call for call in session.calls if call["capture_interface"]]
    self.assertEqual(len(requested), 1)
    self.assertFalse(requested[0]["probe"])
    self.assertEqual(requested[0]["capture_seconds"],
                     engine.DEFAULT_CAPTURE_SECONDS)

  def test_choosing_an_interface_remembers_it_and_runs_the_pass(self):
    """CAP-2's acceptance: capture on `lo` from a TUI launched with no flags."""
    session = CaptureStubSession()

    async def steps(pilot, screen, out):
      await self._choose(pilot, "lo")
      out["interface"] = session.capture_interface

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertEqual(result["interface"], "lo")
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertEqual(probing[0]["capture_interface"], "lo")

    # Remembered: a second report captures on `lo` without asking again.
    session.calls = []
    self.drive(session, FakeEndpoint("w2", "Writer"), self._settle)
    self.assertEqual([call["capture_interface"] for call in session.calls
                      if call["probe"]], ["lo"])

  def test_skip_is_an_answer_and_is_remembered(self):
    """Skip means probe without capturing - and stops the asking."""
    session = CaptureStubSession()

    async def steps(pilot, screen, out):
      await self._choose(pilot, report_screen.SKIP_CAPTURE)
      out["said"] = status_text(screen)

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertTrue(session.capture_choice_made)
    self.assertIsNone(session.capture_interface)
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertIsNone(probing[0]["capture_interface"])
    self.assertIn("Probe complete", result["said"])

    # A second report probes without re-prompting.
    session.calls = []
    result = self.drive(session, FakeEndpoint("w2", "Writer"), self._settle)
    self.assertIsInstance(result["screen"], report_screen.ReportScreen)
    self.assertEqual([call["probe"] for call in session.calls], [False, True])

  def test_dismissing_the_picker_probes_and_asks_again_next_time(self):
    """Escape is not an answer; remembering it would make the Skip row a lie."""
    session = CaptureStubSession()

    async def steps(pilot, screen, out):
      said = []
      original = screen.status.update
      screen.status.update = lambda text: (said.append(str(text)),
                                           original(text))[1]
      await pilot.press("escape")
      await pilot.app.workers.wait_for_complete()
      await pilot.pause()
      out["announced"] = said[0] if said else ""
      out["said"] = status_text(screen)

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertFalse(session.capture_choice_made)
    # The announcement, not the result: it says why nothing was captured, and
    # the pass that follows it overwrites the line.
    self.assertIn("No interface chosen", result["announced"])
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertIsNone(probing[0]["capture_interface"])

    # Asked again on the next report, rather than silently opted out.
    result = self.drive(session, FakeEndpoint("w2", "Writer"), self._settle)
    self.assertIsInstance(result["screen"],
                          report_screen.CaptureInterfaceScreen)

  def test_capital_c_turns_capture_back_on_after_a_failure(self):
    """Choosing again is how an operator says the reason no longer applies."""
    session = CaptureStubSession("lo")
    session.disable_capture("you don't have permission to capture")

    async def steps(pilot, screen, out):
      await pilot.press("C")
      await pilot.pause()
      await self._choose(pilot, "eth0")

    self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertIsNone(session.capture_off_reason)
    self.assertEqual(session.capture_interface, "eth0")
    self.assertEqual([call["capture_interface"] for call in session.calls
                      if call["capture_interface"]], ["eth0"])

  def test_the_picker_offers_skip_first_and_any_last(self):
    """N3, both ends: the reflexive Enter must land on the least privileged row.

    `any` needs the broadest privileges of any choice, so it is pushed to the
    bottom; Skip captures nothing at all, so it sits under the cursor. tshark -D
    lists `any` on some hosts and not others, so it is appended unconditionally
    and filtered out of the enumerated rows to avoid a duplicate.
    """
    session = CaptureStubSession()
    screen = report_screen.CaptureInterfaceScreen(session, lambda _: None)
    screen.interfaces = (("1", "any (Pseudo-device that captures on all interfaces)"),
                         ("2", "lo"))
    self.assertEqual([label for _, label, _, _ in screen._choices()],
                     [report_screen.SKIP_CAPTURE, "lo", "any"])
    # What is shown and what reaches tshark are separate: Skip is not a name.
    self.assertEqual([iface for _, _, _, iface in screen._choices()],
                     [None, "lo", "any"])

  def test_the_picker_still_offers_any_when_tshark_cannot_enumerate(self):
    """A picker that cannot list must not become a dead end."""
    session = CaptureStubSession()
    screen = report_screen.CaptureInterfaceScreen(session, lambda _: None)
    screen.interfaces, screen.error = (), "tshark was not found on PATH"
    self.assertEqual([label for _, label, _, _ in screen._choices()],
                     [report_screen.SKIP_CAPTURE, "any"])

  def test_the_picker_does_not_enumerate_on_the_event_loop(self):
    """`tshark -D` runs extcap helpers, so it must not block construction.

    Constructing the screen is done from `action_capture`, on the Textual event
    loop. Enumerating there froze the whole TUI for as long as tshark took.
    """
    session = CaptureStubSession()
    with mock.patch.object(report_screen.wire, "capture_interfaces") as listed:
      report_screen.CaptureInterfaceScreen(session, lambda _: None)
    listed.assert_not_called()

  def test_a_participant_report_says_capture_needs_an_endpoint(self):
    session = CaptureStubSession()
    collected = {}

    async def run():
      screen = report_screen.ReportScreen(
          session, participant=records.ParticipantRecord(key="p1", name="app"))
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.press("c")
        await pilot.pause()
        collected["said"] = status_text(screen)

    session.diagnose_participant = lambda participant: report.ReportData(
        domain_id=7, scope="participant 'app'", all_findings=[],
        participant=participant)
    asyncio.run(run())
    self.assertIn("needs an endpoint", collected["said"])

  def test_the_wire_tab_says_how_to_get_packet_evidence(self):
    """H8/H9: an unasked question must not render as a settled one."""
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer")))
    self.assertIn(report.CAPTURE_PLACEHOLDER, sections["wire"])
    self.assertIn("Press c", sections["wire"])

  def test_the_overview_tab_shows_what_a_capture_produced(self):
    """The operator who pressed `c` is the one who must see the result.

    The capture summary went into the saved report first and not into
    `render_view_sections`, so in the TUI the version landed in the Wire tab
    and Overview showed nothing - the interactive path, which is the only way
    to press `c` at all, was the one that did not report it.
    """
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer"),
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"]}))
    self.assertIn("CAPTURE EVIDENCE", sections["overview"])
    self.assertIn("3.6.2.0", sections["overview"])

  def test_capture_headline_names_the_version_even_with_no_user_data(self):
    """The fastdds-no-type-info case: zero frames, version still recovered.

    This is the shape that made the old status line useless. It reported "0
    matching frames" for a capture that had in fact read the peer's product
    version out of parameter 0x8000, so the operator who pressed `c` was told
    the capture found nothing.
    """
    headline = report.capture_headline(report.ReportData(
        domain_id=7, scope="topic 'T'", all_findings=[],
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"]}))
    self.assertIn("Fast DDS version 3.6.2.0", headline)
    self.assertIn("no user DATA", headline)
    self.assertIn("0 matching frames", headline)

  def test_capture_headline_names_the_representation_it_parsed(self):
    headline = report.capture_headline(report.ReportData(
        domain_id=7, scope="topic 'T'", all_findings=[],
        wire_evidence={"source": "c.pcapng", "packets": 4, "data_packets": 4,
                       "encapsulation_ids": ["0x0001"]},
        discovery_evidence={"fastdds_product_versions": []}))
    self.assertIn("representation XCDR1", headline)
    self.assertIn("no Fast DDS version advertised", headline)
    self.assertIn("4 matching frames", headline)

  def test_capture_headline_singularizes_one_frame(self):
    headline = report.capture_headline(report.ReportData(
        domain_id=7, scope="topic 'T'", all_findings=[],
        wire_evidence={"source": "c.pcapng", "packets": 1}))
    self.assertIn("1 matching frame;", headline + ";")
    self.assertNotIn("1 matching frames", headline)

  def test_the_overview_tab_is_unchanged_without_a_capture(self):
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer")))
    self.assertNotIn("CAPTURE EVIDENCE", sections["overview"])


if __name__ == "__main__":
  unittest.main()
