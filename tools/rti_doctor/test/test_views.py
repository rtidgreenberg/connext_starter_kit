"""Unit tests for the system screens' shared refresh-failure convention.

These drive real Textual screens headlessly against a stub session, so they need
no Connext license and no DDS domain: the behaviour under test is what the
screen does when `session.system_scan` raises, which is independent of why it
raised.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from textual.app import App

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import (engine, findings, livedata, probe,  # noqa: E402
                        records, report, system_scan, vendors)
from rti_doctor.views import (browse, issue_marks, report_screen,  # noqa: E402
                              system_overview)

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
    self.probe_default = True
    # The Data tab reads both when opening a feed, so every session stub needs
    # them or `_start_live` fails as "the live feed could not create a reader".
    self.isolate_probe = True
    self.type_object_v1_only = False
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

  def test_issue_list_labels_its_save_as_system_wide(self):
    save_binding = next(binding for binding in system_overview.IssueListScreen.BINDINGS
                        if binding[0] == "s")
    self.assertEqual(save_binding[2], "Save system report")

  def test_deep_navigation_screens_omit_redundant_global_controls(self):
    issue_keys = {binding[0] for binding in system_overview.IssueListScreen.BINDINGS}
    topology_keys = {binding[0] for binding in system_overview.TopologyHealthScreen.BINDINGS}
    self.assertNotIn("m", issue_keys)
    self.assertNotIn("m", topology_keys)
    self.assertNotIn("s", topology_keys)

  def test_topology_omits_the_redundant_open_report_key(self):
    keys = {binding[0] for binding in system_overview.TopologyHealthScreen.BINDINGS}
    self.assertNotIn("o", keys)

  def test_topology_finding_summary_labels_count_and_worst_severity(self):
    issue = mock.Mock(participant_keys=("p1",), writer_keys=(), reader_keys=(),
                      topic_name=None, severity=findings.Severity.ERROR)
    screen = system_overview.TopologyHealthScreen(StubSession())
    screen.snapshot = mock.Mock(issues=(issue,))
    summary = screen._finding_summary(participant_key="p1")
    self.assertEqual(str(summary), "1 finding (worst: ERROR)")
    self.assertEqual(str(summary.spans[0].style), "bold red")

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
    self.assertIn("save the full system report", collected["issues"])

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


class TestEndpointNavigation(unittest.TestCase):
  """Enter opens endpoint reports; Topology also links to Findings with f."""

  def bindings(self, screen_class):
    return {key: action for key, action, *_ in screen_class.BINDINGS}

  def test_endpoint_lists_have_no_redundant_open_report_key(self):
    for screen_class in (system_overview.TopologyHealthScreen,
                         system_overview.TopicEndpointsScreen,
                         browse.EndpointListScreen):
      with self.subTest(screen=screen_class.__name__):
        self.assertNotIn("o", self.bindings(screen_class))

  def fake_app(self):
    """`Screen.app` is a read-only property, so it is patched on the class."""
    app = mock.Mock()
    patcher = mock.patch.object(system_overview.TopologyHealthScreen, "app",
                                new_callable=mock.PropertyMock,
                                return_value=app)
    patcher.start()
    self.addCleanup(patcher.stop)
    return app

  def test_finding_endpoint_choice_uses_the_session_probe_default(self):
    session = StubSession()
    session.probe_default = False
    endpoint = FakeEndpoint("w1", "Writer")
    chooser = system_overview.EndpointChoiceScreen(
        session, issue_with(writer_keys=("w1",)),
        [("Writer (offers)", "writer-app", endpoint)])
    app = mock.Mock()
    patcher = mock.patch.object(system_overview.EndpointChoiceScreen, "app",
                                new_callable=mock.PropertyMock, return_value=app)
    patcher.start()
    self.addCleanup(patcher.stop)

    with mock.patch.object(system_overview, "ReportScreen") as report_screen_cls:
      asyncio.run(chooser.on_data_table_row_selected(
          mock.Mock(row_key=mock.Mock(value="0"))))

    report_screen_cls.assert_called_once_with(session, endpoint=endpoint,
                                              probe=False)

  def test_f_opens_linked_findings_for_a_topology_row(self):
    session = StubSession()
    session.registry = StubRegistry()
    endpoint = FakeEndpoint("w1", "Writer")
    session.registry.endpoints = {"w1": endpoint}
    issue = issue_with(writer_keys=("w1",))
    screen = system_overview.TopologyHealthScreen(session)
    screen.mode = "writers"
    screen.selected_key = "w1"
    screen.snapshot = mock.Mock(issues=(issue,))
    app = self.fake_app()

    screen.action_findings()

    pushed = app.push_screen.call_args.args[0]
    self.assertIsInstance(pushed, system_overview.IssueListScreen)
    self.assertEqual(pushed.issue_keys, {issue.key})

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

  def test_linked_findings_does_not_push_an_empty_screen(self):
    result = self._press(["f"])
    self.assertIn("No topology has been collected yet", result["status"])
    # Harness screen + the topology screen, and nothing pushed on top: a finding
    # list built from no snapshot would be an empty list presented as a result.
    self.assertEqual(result["screens"], 2)

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
    self.vendor_name = "RTI Connext"

  @property
  def is_writer(self):
    return self.kind == "Writer"


def vendor_id(second_octet, first=0x01):
  """An RTPS vendor id; `first` is only ever changed to build 00.00."""
  return type("Vendor", (), {"value": [first, second_octet]})()


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

  def test_issue_detail_prioritizes_endpoint_pages_over_raw_identifiers(self):
    issue = issue_with(
        writer_keys=("w1",), reader_keys=("r1",),
        evidence={"writer": "Writer in 'writer-app'", "reader": "Reader in 'reader-app'"})
    text = system_overview._issue_endpoint_navigation(self.session, issue)
    self.assertIn("Writer (offers): Writer in 'writer-app'", text)
    self.assertIn("Reader (requests): Reader in 'reader-app'", text)
    self.assertIn("[bold]Endpoint pages[/bold]", text)
    self.assertIn("Press [bold]o[/bold] to choose an endpoint page.", text)
    technical_ids = system_overview._issue_technical_ids(issue)
    self.assertIn("[bold]Technical identifiers[/bold]", technical_ids)
    self.assertIn("Writers: w1", technical_ids)
    self.assertIn("Readers: r1", technical_ids)

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
  """Records automatic probe and RTI Network Capture requests."""

  def __init__(self, capture_interface=None, network_capture=True):
    super().__init__()
    self.probe_timeout = 10.0
    self.type_wait = 5.0
    self.settle = 3.0
    # Retained only for old test fixtures that construct this stub with the
    # removed option. Production Session has no interface capture state.
    self.capture_interface = capture_interface
    # RTI Network Capture is a launch-time answer, so a stub models it as a
    # constructor argument rather than something a screen can change.
    self.network_capture = network_capture
    self.pass_deadline = 0.0
    self.capture_artifacts = []
    self.retained_artifacts = set()
    self.calls = []
    self.wire_evidence = {"source": "/tmp/rti_doctor_captures/one.pcapng",
                          "packets": 12}

  def retain_capture(self, path):
    if path:
      self.retained_artifacts.add(path)

  def claim_pass(self, seconds):
    self.pass_deadline = time.monotonic() + seconds

  def release_pass(self):
    self.pass_deadline = 0.0

  def pass_in_flight(self):
    return time.monotonic() < self.pass_deadline

  def diagnose_endpoint(self, endpoint, probe=True, write_samples=False):
    self.calls.append({"endpoint": endpoint.key, "probe": probe,
                       "write_samples": write_samples})
    return report.ReportData(
        domain_id=7, scope=f"topic '{endpoint.topic_name}'", all_findings=[],
        endpoint=endpoint,
        participant_evidence=self.wire_evidence if probe else None)


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

  def test_opening_a_report_records_its_probe_automatically(self):
    """An endpoint report starts its probe without choosing an interface."""
    session = CaptureStubSession()

    self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    self.assertEqual([call["probe"] for call in session.calls], [False, True])

  def test_a_report_probes_on_entry_in_one_pass(self):
    session = CaptureStubSession()
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self._settle)
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertIn("Probe complete", result["said"])

  def test_probe_completion_names_exclusive_writer_isolation(self):
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.ownership = type("Ownership", (), {
      "kind": type("Kind", (), {"name": "EXCLUSIVE"})()})()
    screen = report_screen.ReportScreen(CaptureStubSession(), endpoint=endpoint)
    probe_result = probe.ProbeResult()
    probe_result.isolated = True
    probe_result.ignored = [{"kind": "writer", "key": "w2"}]
    screen.data = report.ReportData(
      domain_id=7, scope="topic 'Telemetry'", all_findings=[], endpoint=endpoint,
      probe_result=probe_result,
      participant_evidence={"source": "p.pcap", "packets": 1})
    self.assertIn("ignoring 1 competing writer(s) to avoid EXCLUSIVE ownership "
            "arbitration, so it was probed exclusively",
            screen._pass_result_text(True))

  def test_the_entry_announcement_names_network_capture(self):
    session = CaptureStubSession()
    screen = report_screen.ReportScreen(session, endpoint=FakeEndpoint("w1", "Writer"))
    said = screen._pass_announcement(True, 10.0)
    for expected in ("10s", "probing", "RTI Network Capture", "shared memory"):
      self.assertIn(expected, said)

  def test_a_reader_report_probes_on_entry_too(self):
    """The reader probe existed and was unreachable from the TUI.

    `probe_endpoint` already dispatches a non-writer to `probe_reader_endpoint`,
    and the engine already picks the right checks for the result; the
    `is_writer` gate on this screen was the only thing in the way. A reader
    probe answers what no static check can - does anything match this reader.
    """
    session = CaptureStubSession()

    async def steps(pilot, screen, out):
      out["said"] = screen._pass_announcement(True, 10.0)

    result = self.drive(session, FakeEndpoint("r1", "Reader"), steps)
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    # A reader probe creates a writer that never publishes, so the copy must
    # not promise user data the Wire tab will then contradict.
    self.assertIn("creating a writer", result["said"])

  def test_a_foreign_writer_compatibility_command_uses_an_isolated_matrix(self):
    session = CaptureStubSession()
    session.type_wait = 4.0
    endpoint = FakeEndpoint("w1", "Writer", topic_name="FastTelemetry")
    endpoint.vendor_id = vendor_id(0x0F)
    screen = report_screen.ReportScreen(session, endpoint=endpoint)
    command = screen._compatibility_command("/tmp/matrix")
    self.assertEqual(command[:2], ["bash", os.path.join(
        report_screen.paths.TOOL_ROOT, "run_version_matrix.sh")])
    self.assertIn("--topic", command)
    self.assertEqual(command[command.index("--topic") + 1], "FastTelemetry")
    self.assertIn("--output-dir", command)
    self.assertEqual(command[command.index("--output-dir") + 1], "/tmp/matrix")

  def test_a_foreign_writer_report_advertises_the_compatibility_matrix(self):
    session = CaptureStubSession()
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.vendor_id = vendor_id(0x0F)
    screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    self.assertIn("press x", screen._compatibility_hint_text().lower())

  def test_matrix_progress_lines_from_the_runner_all_parse(self):
    """Every line `run_version_matrix.sh` emits, taken from the script itself.

    The runner reports a result verbatim, so a progress line has two tokens or
    seven. A fixed four-field split raised ValueError on the very first line -
    "MATRIX_PROGRESS preflight running" - and the worker died before any profile
    ran, leaving the screen on its "Preparing..." placeholder for good.
    """
    screen = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")
    screen.progress = mock.Mock()
    emitted = [
        "MATRIX_PROGRESS preflight running",
        "MATRIX_PROGRESS preflight complete",
        "MATRIX_PROGRESS default-v2 running",
        "MATRIX_PROGRESS default-v2 ERROR findings or startup failure",
        "MATRIX_PROGRESS vendor-v2 running",
        "MATRIX_PROGRESS vendor-v2 no ERROR findings",
    ]
    for line in emitted:
      screen._note_progress(line)
    self.assertEqual(screen.states["preflight"], "complete")
    self.assertEqual(screen.states["default-v2"],
                     "ERROR findings or startup failure")
    self.assertEqual(screen.states["vendor-v2"], "no ERROR findings")
    # An untouched profile keeps its placeholder rather than gaining a row of
    # mis-split tokens.
    self.assertEqual(screen.states["vendor-v1"], "waiting")
    self.assertEqual(set(screen.states),
                     {"preflight"} | set(report_screen.MATRIX_PROFILES))

  def test_the_runner_script_emits_only_progress_lines_the_screen_parses(self):
    """The script is the source of truth for the profile list and the prefix."""
    path = os.path.join(report_screen.paths.TOOL_ROOT, "run_version_matrix.sh")
    self.assertTrue(os.path.isfile(path), "the matrix runner must be present")
    with open(path, encoding="utf-8") as handle:
      script = handle.read()
    for profile in report_screen.MATRIX_PROFILES:
      self.assertIn(profile, script)

  def test_a_malformed_progress_line_does_not_stop_the_matrix(self):
    screen = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")
    screen.progress = mock.Mock()
    with self.assertLogs(level="WARNING"):
      screen._note_progress("MATRIX_PROGRESS preflight")
      screen._note_progress("MATRIX_PROGRESS not-a-profile running")
    self.assertEqual(screen.states["preflight"], "waiting")

  def test_leaving_the_matrix_screen_stops_the_child_observers(self):
    """Three child observers on the diagnosed domain must not outlive the screen."""
    screen = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")
    process = mock.Mock()
    process.pid = 4321
    process.poll.return_value = None
    screen.process = process
    with mock.patch.object(report_screen.os, "getpgid", return_value=4321), \
         mock.patch.object(report_screen.os, "killpg") as killpg:
      screen.on_unmount()
    killpg.assert_called_once_with(4321, report_screen.signal.SIGTERM)
    process.wait.assert_called_once()
    self.assertIsNone(screen.process)

  def test_a_wedged_matrix_runner_is_killed_rather_than_left_running(self):
    screen = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")
    process = mock.Mock()
    process.pid = 4321
    process.poll.return_value = None
    process.wait.side_effect = subprocess.TimeoutExpired("bash", 5.0)
    screen.process = process
    with mock.patch.object(report_screen.os, "getpgid", return_value=4321), \
         mock.patch.object(report_screen.os, "killpg") as killpg:
      screen.on_unmount()
    self.assertEqual([call.args[1] for call in killpg.call_args_list],
                     [report_screen.signal.SIGTERM, report_screen.signal.SIGKILL])

  def test_a_matrix_worker_failure_is_reported_on_screen(self):
    """`exit_on_error=False` keeps the TUI up, so the screen must say why."""
    screen = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")
    screen.detail = mock.Mock()
    with mock.patch.object(screen, "_stream_matrix",
                           side_effect=RuntimeError("popen exploded")), \
         self.assertLogs(level="ERROR"):
      asyncio.run(screen._run_matrix())
    self.assertIn("popen exploded", screen.detail.update.call_args[0][0])

  def test_the_matrix_is_offered_only_on_a_fastdds_writer(self):
    """The footer documents the keymap, so it must not advertise a refusal."""
    session = CaptureStubSession()
    fastdds = FakeEndpoint("w1", "Writer")
    fastdds.vendor_id = type("Vendor", (), {"value": [0x01, 0x0F]})()
    rti = FakeEndpoint("w2", "Writer")
    rti.vendor_id = type("Vendor", (), {"value": [0x01, 0x01]})()
    reader = FakeEndpoint("r1", "Reader")
    reader.vendor_id = type("Vendor", (), {"value": [0x01, 0x0F]})()
    for endpoint, offered in ((fastdds, True), (rti, False), (reader, False)):
      screen = report_screen.ReportScreen(session, endpoint=endpoint)
      self.assertEqual(screen.check_action("compatibility_matrix", ()), offered,
                       f"{endpoint.key} should{'' if offered else ' not'} offer x")
    participant = report_screen.ReportScreen(
        session, participant=records.ParticipantRecord(key="p1", name="app"))
    self.assertFalse(participant.check_action("compatibility_matrix", ()))

  def test_a_missing_runner_is_named_instead_of_reporting_an_empty_matrix(self):
    session = CaptureStubSession()
    endpoint = FakeEndpoint("w1", "Writer", topic_name="FastTelemetry")
    endpoint.vendor_id = type("Vendor", (), {"value": [0x01, 0x0F]})()
    screen = report_screen.ReportScreen(session, endpoint=endpoint)
    screen.status = mock.Mock()
    with mock.patch.object(report_screen.os.path, "isfile", return_value=False):
      # `self.app` raises off-app, so reaching the push at all fails this test.
      screen.action_compatibility_matrix()
    self.assertIn("runner is missing", screen.status.update.call_args[0][0])

  def test_the_matrix_never_settles_for_less_than_the_runner_default(self):
    """An interactive `--settle` tuned for a local RTI peer is too short here."""
    session = CaptureStubSession()
    session.settle = 3.0
    endpoint = FakeEndpoint("w1", "Writer", topic_name="FastTelemetry")
    endpoint.vendor_id = type("Vendor", (), {"value": [0x01, 0x0F]})()
    screen = report_screen.ReportScreen(session, endpoint=endpoint)
    command = screen._compatibility_command("/tmp/matrix")
    self.assertEqual(float(command[command.index("--settle") + 1]),
                     report_screen.MATRIX_MIN_SETTLE)
    # An operator who asked for longer gets what they asked for.
    session.settle = report_screen.MATRIX_MIN_SETTLE + 10.0
    command = screen._compatibility_command("/tmp/matrix")
    self.assertEqual(float(command[command.index("--settle") + 1]),
                     report_screen.MATRIX_MIN_SETTLE + 10.0)

  def test_publish_verification_is_available_only_for_readers(self):
    session = CaptureStubSession()
    writer = report_screen.ReportScreen(session, endpoint=FakeEndpoint("w1", "Writer"))
    reader = report_screen.ReportScreen(session, endpoint=FakeEndpoint("r1", "Reader"))
    self.assertFalse(writer.check_action("verify_delivery", ()))
    self.assertTrue(reader.check_action("verify_delivery", ()))

  def test_compatibility_matrix_rejects_an_rti_writer(self):
    session = CaptureStubSession()
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.vendor_id = type("Vendor", (), {"value": [0x01, 0x01]})()
    screen = report_screen.ReportScreen(session, endpoint=endpoint)
    screen.status = mock.Mock()
    screen.action_compatibility_matrix()
    self.assertIn("RTI Connext writer", screen.status.update.call_args[0][0])

  def _matrix_output_dir(self, profile, report_text):
    """One child profile report on disk, as the runner would leave it."""
    output_dir = os.path.join(os.path.dirname(__file__), "matrix_findings")
    report_dir = os.path.join(output_dir, profile)
    os.makedirs(report_dir, exist_ok=True)
    self.addCleanup(shutil.rmtree, output_dir, ignore_errors=True)
    with open(os.path.join(report_dir, "topic_report.txt"), "w",
              encoding="utf-8") as handle:
      handle.write(report_text)
    return output_dir

  def test_compatibility_matrix_extracts_profile_problem_titles(self):
    """Scraped from a real rendered report, rules and all.

    A hand-written fixture without the `report._section` rules passed while the
    scrape was returning the 80-dash rule as every profile's verdict, because
    the rule is exactly the line a real report puts after "VERDICT".
    """
    data = report.ReportData(
        domain_id=7, scope="topic 'Telemetry'",
        endpoint=FakeEndpoint("w1", "Writer"),
        all_findings=[findings.Finding(
            id="match.none", rung=4, severity=findings.Severity.ERROR,
            title="Reader never matched the writer",
            observed="No matched publication was observed.",
            root_cause="The reader saw no compatible writer.",
            remedy="Compare the requested and offered QoS.")])
    output_dir = self._matrix_output_dir("vendor-v1", report.render_text(data))
    screen = report_screen.CompatibilityMatrixScreen([], output_dir)
    text = screen._profile_findings()
    self.assertIn("match.none", text)
    self.assertIn("Reader never matched the writer", text)
    # The verdict, not the rule that `_section` puts under the heading.
    self.assertNotRegex(text, r"vendor-v1: -{5,}")
    self.assertIn(f"vendor-v1: {data.verdict}", text)

  @unittest.skip("interface capture was removed")
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

  @unittest.skip("interface capture was removed")
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
    self.assertNotIn("Press c", result["said"])
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

  def test_capture_keys_are_not_bound_after_the_entry_choice(self):
    keys = {binding[0] for binding in report_screen.ReportScreen.BINDINGS}
    self.assertNotIn("c", keys)
    self.assertNotIn("C", keys)

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

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps, probe=False)
    self.assertIsInstance(result["screen"], report_screen.ReportScreen)
    self.assertEqual([call["probe"] for call in session.calls], [False])

  @unittest.skip("interface capture was removed")
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

  @unittest.skip("interface capture was removed")
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

  @unittest.skip("interface capture was removed")
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

  @unittest.skip("interface capture was removed")
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

  @unittest.skip("interface capture was removed")
  def test_the_picker_still_offers_any_when_tshark_cannot_enumerate(self):
    """A picker that cannot list must not become a dead end."""
    session = CaptureStubSession()
    screen = report_screen.CaptureInterfaceScreen(session, lambda _: None)
    screen.interfaces, screen.error = (), "tshark was not found on PATH"
    self.assertEqual([label for _, label, _, _ in screen._choices()],
                     [report_screen.SKIP_CAPTURE, "any"])

  @unittest.skip("interface capture was removed")
  def test_the_picker_does_not_enumerate_on_the_event_loop(self):
    """`tshark -D` runs extcap helpers, so it must not block construction.

    The screen is constructed from `_offer_full_pass`, on the Textual event
    loop. Enumerating there froze the whole TUI for as long as tshark took.
    """
    session = CaptureStubSession()
    with mock.patch.object(report_screen.wire, "capture_interfaces") as listed:
      report_screen.CaptureInterfaceScreen(session, lambda _: None)
    listed.assert_not_called()

  def test_a_participant_report_has_no_capture_action(self):
    session = CaptureStubSession()
    collected = {}

    async def run():
      screen = report_screen.ReportScreen(
          session, participant=records.ParticipantRecord(key="p1", name="app"))
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        collected["said"] = status_text(screen)

    session.diagnose_participant = lambda participant: report.ReportData(
        domain_id=7, scope="participant 'app'", all_findings=[],
        participant=participant)
    asyncio.run(run())
    self.assertIn("participant report", collected["said"])

  def test_the_wire_tab_says_how_to_get_packet_evidence(self):
    """H8/H9: an unasked question must not render as a settled one."""
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer")))
    self.assertIn(report.CAPTURE_PLACEHOLDER, sections["wire"])
    self.assertIn("Run a diagnostic probe", sections["wire"])

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
        participant_evidence={"source": "p.pcap", "packets": 0, "data_packets": 0},
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
        participant_evidence={"source": "p.pcap", "packets": 4, "data_packets": 4,
                  "encapsulation_ids": ["0x0001"]},
        discovery_evidence={"fastdds_product_versions": []}))
    self.assertIn("representation XCDR1", headline)
    self.assertIn("no Fast DDS version advertised", headline)
    self.assertIn("4 matching frames", headline)

  def test_capture_headline_uses_network_capture_not_offline_pcap(self):
    headline = report.capture_headline(report.ReportData(
        domain_id=7, scope="topic 'T'", all_findings=[],
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        participant_evidence={"source": "p.pcap", "packets": 34,
                              "data_packets": 34}))
    self.assertIn("no user DATA", headline)
    self.assertNotIn("offline PCAP", headline)

  def test_capture_headline_singularizes_one_frame(self):
    headline = report.capture_headline(report.ReportData(
        domain_id=7, scope="topic 'T'", all_findings=[],
        participant_evidence={"source": "p.pcap", "packets": 1}))
    self.assertIn("1 matching frame;", headline + ";")
    self.assertNotIn("1 matching frames", headline)

  def test_the_overview_tab_is_unchanged_without_a_capture(self):
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer")))
    self.assertNotIn("CAPTURE EVIDENCE", sections["overview"])


class TestTheCompatibilityMatrixIsCrossVendor(unittest.TestCase):
  """`x` is offered for any non-RTI writer, and says so without naming one.

  The runner behind it starts fresh Connext observers under three XTypes and
  TypeObject profiles; every one of those is a property of the OBSERVER, and
  nothing in it is specific to a peer implementation. Gating the key on Fast DDS
  therefore hid it on exactly the peers it is most useful against - a Cyclone or
  OpenDDS writer whose type will not resolve - and titled the result after a
  vendor that was not in the run.
  """

  def screen(self, second_octet=None, kind="Writer"):
    endpoint = FakeEndpoint("w1", kind)
    if second_octet is not None:
      endpoint.vendor_id = vendor_id(second_octet)
    return report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=endpoint, probe=False)

  def test_the_key_is_offered_for_every_recognized_non_rti_vendor(self):
    for octet, name in ((0x02, "OpenSplice"), (0x03, "OpenDDS"),
                        (0x0F, "Fast DDS"), (0x10, "Cyclone")):
      with self.subTest(vendor=name):
        self.assertTrue(self.screen(octet).check_action("compatibility_matrix",
                                                        None))

  def test_an_unrecognized_but_readable_vendor_is_still_offered_it(self):
    """The profiles are ours, not the peer's, so an unknown foreign peer is a
    legitimate target - and its type failing to resolve is the usual reason to
    reach for this."""
    self.assertTrue(self.screen(0x7F).check_action("compatibility_matrix", None))

  def test_an_rti_writer_is_not_offered_it(self):
    self.assertFalse(self.screen(0x01).check_action("compatibility_matrix", None))

  def test_an_unreadable_vendor_id_is_not_offered_it(self):
    """The same misattribution guard the vendor module already applies: an
    experiment offered on the strength of a vendor we could not determine claims
    more than the evidence supports."""
    self.assertFalse(self.screen(None).check_action("compatibility_matrix", None))

  def test_a_reader_is_not_offered_it(self):
    self.assertFalse(
        self.screen(0x10, kind="Reader").check_action("compatibility_matrix",
                                                     None))

  def test_the_hint_names_the_vendor_it_found(self):
    self.assertIn("Eclipse Cyclone DDS writer detected",
                  self.screen(0x10)._compatibility_hint_text())
    self.assertIn("eProsima Fast DDS writer detected",
                  self.screen(0x0F)._compatibility_hint_text())

  def test_no_key_label_advertises_one_vendor(self):
    """The footer is where the keymap is documented, so it is where a
    vendor-specific name would be read as a vendor-specific feature."""
    labels = {binding[2] for binding in report_screen.ReportScreen.BINDINGS}
    self.assertIn("Cross-vendor compatibility", labels)
    self.assertNotIn("Fast DDS compatibility", labels)

  def test_the_matrix_screen_heading_names_the_peer_when_it_knows_it(self):
    named = report_screen.CompatibilityMatrixScreen(
        [], "/tmp/matrix", vendor="Eclipse Cyclone DDS")
    self.assertEqual(named._heading(),
                     "Cross-Vendor Compatibility Matrix - Eclipse Cyclone DDS writer")
    plain = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")
    self.assertEqual(plain._heading(), "Cross-Vendor Compatibility Matrix")
    self.assertNotIn("Fast DDS", plain._heading())

  def test_an_rti_writer_that_reaches_the_action_is_told_why_not(self):
    screen = self.screen(0x01)
    screen.status = mock.Mock()
    screen.action_compatibility_matrix()
    self.assertIn("no cross-vendor matrix is needed",
                  screen.status.update.call_args[0][0])

  def test_an_unreadable_vendor_that_reaches_the_action_is_told_why_not(self):
    screen = self.screen(None)
    screen.status = mock.Mock()
    screen.action_compatibility_matrix()
    said = screen.status.update.call_args[0][0]
    self.assertIn("vendor id could not be read", said)
    self.assertNotIn("Fast DDS", said)

  def test_the_evidence_directory_is_not_named_after_one_vendor(self):
    """Driven by the key, because `Screen.app` is read-only in Textual and the
    push is what carries the directory and the vendor label."""
    recorded = {}

    class Recorder(report_screen.Screen):
      """Stands in for the matrix screen so no runner is spawned."""

      def __init__(self, command, output_dir, vendor=None):
        super().__init__()
        recorded.update(command=command, output_dir=output_dir, vendor=vendor)

    screen = self.screen(0x10)

    async def run():
      app = Harness(screen)
      with mock.patch.object(report_screen, "CompatibilityMatrixScreen",
                             Recorder), \
           mock.patch.object(report_screen.os.path, "isfile",
                             return_value=True):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          await pilot.press("x")
          await pilot.pause()

    asyncio.run(run())
    self.assertIn("cross_vendor_compatibility", recorded["output_dir"])
    self.assertNotIn("fastdds", recorded["output_dir"])
    self.assertEqual(recorded["vendor"], "Eclipse Cyclone DDS")


class StubLive:
  """Stands in for `livedata.LiveSubscription` with no domain behind it.

  Records its own construction and closure, because the whole contract under
  test is a lifetime: opened by selecting the Data tab, closed by everything
  that means the operator has stopped looking at it.
  """

  opened = []

  def __init__(self, participant, endpoint, isolate=False, domain_id=None,
               type_object_v1_only=False):
    self.participant = participant
    self.endpoint = endpoint
    # What the view asked for, so a test can assert the session's setting
    # reaches the feed rather than the feed quietly defaulting.
    self.isolate_arg = isolate
    self.domain_id_arg = domain_id
    self.type_object_v1_only_arg = type_object_v1_only
    self.received = 0
    self.others = 0
    # Mirrors the real subscription's counters: the header reports what it is
    # NOT showing as well as what it is, so a stub missing one is a stub that
    # cannot catch the header regressing. `test_the_stub_mirrors_the_real
    # _subscription` keeps this list honest.
    self.dropped = 0
    self.correlated = True
    self.applied_qos = {}
    self.errors = 0
    self.last_error = ""
    # The isolation surface the header reads, mirroring the real subscription.
    self.isolation_requested = bool(isolate)
    self.isolated = bool(isolate)
    self.isolation_error = None
    self.isolation_elapsed = 0.0
    self.isolation_target_seen = bool(isolate)
    self.ignored = []
    self.ignore_failures = []
    self.closes = 0
    self.batches = []
    StubLive.opened.append(self)

  @property
  def closed(self):
    return self.closes > 0

  def poll(self):
    if not self.batches:
      return [], 0
    batch = self.batches.pop(0)
    self.received += len(batch)
    return batch, 0

  def close(self):
    self.closes += 1


def live_samples(count, first=1):
  return [livedata.LiveSample(number, 1700000000.5 + number,
                              '{"id":%d}' % number)
          for number in range(first, first + count)]


class TestTheDataTabStreamsWhileItIsOpen(unittest.TestCase):
  """A reader opens when the Data tab is selected and closes when it is not.

  The tab selection is the request, which makes this the one place in the report
  that creates a DDS entity without a keypress. That is only honest while the
  converse holds: every way of ceasing to look at the tab - another tab, another
  screen on top, leaving the report - has to close the reader. A subscription
  nobody can see is exactly what this tool tells other people not to leave
  behind.
  """

  def setUp(self):
    StubLive.opened = []

  def screen(self, endpoint=None, participant=None, session=None):
    session = session or CaptureStubSession("lo")
    session.participant = object()
    if endpoint is None and participant is None:
      endpoint = FakeEndpoint("w1", "Writer")
    if endpoint is not None:
      endpoint.type = object()
    return report_screen.ReportScreen(
        session, endpoint=endpoint, participant=participant, probe=False)

  def drive(self, screen, steps):
    collected = {}

    async def run():
      app = Harness(screen)
      with mock.patch.object(livedata, "LiveSubscription", StubLive):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          await steps(pilot, screen, collected)

    asyncio.run(run())
    return collected

  @staticmethod
  async def select(pilot, screen, tab_id):
    screen.query_one("#report_tabs",
                     report_screen.TabbedContent).active = tab_id
    await pilot.pause()

  def body(self, screen):
    return str(screen.bodies["data"].render())

  def test_nothing_is_open_until_the_data_tab_is_selected(self):
    async def steps(pilot, screen, out):
      out["before"] = screen.live

    result = self.drive(self.screen(), steps)
    self.assertIsNone(result["before"])
    self.assertEqual(StubLive.opened, [])

  def test_selecting_the_tab_opens_a_reader_and_starts_polling(self):
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      out["live"] = screen.live
      out["timer"] = screen.live_timer

    result = self.drive(self.screen(), steps)
    self.assertIsInstance(result["live"], StubLive)
    self.assertIsNotNone(result["timer"])
    self.assertEqual(len(StubLive.opened), 1)
    self.assertEqual(StubLive.opened[0].endpoint.key, "w1")

  def test_the_feed_inherits_the_session_s_isolation_setting(self):
    """The Data tab and the Probe tab describe one endpoint.

    If one excluded the topic's other writers and the other did not, the two
    would disagree about whether that endpoint delivers anything - which is the
    contradiction this whole change exists to remove.
    """
    for isolate in (True, False):
      StubLive.opened.clear()
      session = CaptureStubSession("lo")
      session.isolate_probe = isolate

      async def steps(pilot, screen, out):
        await self.select(pilot, screen, "data")

      self.drive(self.screen(session=session), steps)
      self.assertEqual(StubLive.opened[0].isolate_arg, isolate)
      self.assertEqual(StubLive.opened[0].domain_id_arg, session.domain_id)

  def test_leaving_the_tab_closes_the_reader(self):
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      out["opened"] = screen.live
      await self.select(pilot, screen, "probe")
      out["after"] = screen.live
      out["timer"] = screen.live_timer

    result = self.drive(self.screen(), steps)
    self.assertTrue(result["opened"].closed)
    self.assertIsNone(result["after"])
    self.assertIsNone(result["timer"], "the poll timer outlived its reader")

  def test_unmounting_the_report_closes_the_reader(self):
    """Back out of the report while streaming and the reader must not survive."""
    screen = self.screen()

    async def steps(pilot, target, out):
      await self.select(pilot, target, "data")
      out["live"] = target.live

    result = self.drive(screen, steps)
    # `run_test` exiting unmounts the screen, which is the operator leaving.
    self.assertTrue(result["live"].closed)

  def test_a_screen_pushed_on_top_suspends_the_feed(self):
    """A capture picker or the matrix screen leaves the report mounted.

    Without the suspend handler the reader would keep taking samples behind
    them, which is the invisible subscription this design exists not to have.
    """
    screen = self.screen()

    async def steps(pilot, target, out):
      await self.select(pilot, target, "data")
      first = target.live
      target.on_screen_suspend()
      await pilot.pause()
      out["suspended"] = (first.closed, target.live)
      target.on_screen_resume()
      await pilot.pause()
      out["resumed"] = target.live

    result = self.drive(screen, steps)
    self.assertEqual(result["suspended"][0], True)
    self.assertIsNone(result["suspended"][1])
    self.assertIsInstance(result["resumed"], StubLive,
                          "coming back to the tab did not reopen the reader")
    self.assertEqual(len(StubLive.opened), 2)

  def test_arriving_samples_are_rendered_newest_last(self):
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      screen.live.batches = [live_samples(2), live_samples(1, first=3)]
      screen._pump_live()
      screen._pump_live()
      out["body"] = self.body(screen)

    body = self.drive(self.screen(), steps)["body"]
    self.assertIn("STREAMING 'Telemetry'", body)
    self.assertIn("sample 1", body)
    self.assertIn("sample 3", body)
    self.assertLess(body.index("sample 1"), body.index("sample 3"))
    self.assertIn('{"id":3}', body)

  def test_the_feed_keeps_a_bounded_window(self):
    """A writer left running overnight must not be a memory leak."""
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      screen.live.batches = [
          live_samples(report_screen.LIVE_SAMPLE_HISTORY + 40)]
      screen._pump_live()
      out["kept"] = len(screen.live_samples)
      out["body"] = self.body(screen)

    result = self.drive(self.screen(), steps)
    self.assertEqual(result["kept"], report_screen.LIVE_SAMPLE_HISTORY)
    # The newest survive and the oldest are the ones dropped.
    self.assertIn(f"sample {report_screen.LIVE_SAMPLE_HISTORY + 40}",
                  result["body"])
    self.assertNotIn("sample 1  ", result["body"])

  def test_a_closed_feed_stops_claiming_to_be_streaming(self):
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      screen.live.batches = [live_samples(2)]
      screen._pump_live()
      await self.select(pilot, screen, "wire")
      out["body"] = self.body(screen)

    body = self.drive(self.screen(), steps)["body"]
    self.assertIn("FEED CLOSED", body)
    self.assertNotIn("STREAMING", body)
    # The samples already read stay readable; only the reader is gone.
    self.assertIn("sample 2", body)

  def test_a_reader_target_is_told_there_is_nothing_arriving(self):
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      out["live"] = screen.live
      out["body"] = self.body(screen)

    result = self.drive(self.screen(FakeEndpoint("r1", "Reader")), steps)
    self.assertIsNone(result["live"])
    self.assertEqual(StubLive.opened, [])
    self.assertIn("nothing arriving to show", result["body"])

  def test_a_writer_with_no_discovered_type_says_so_instead_of_streaming(self):
    endpoint = FakeEndpoint("w1", "Writer")
    screen = self.screen(endpoint)
    endpoint.type = None

    async def steps(pilot, target, out):
      await self.select(pilot, target, "data")
      out["live"] = target.live
      out["body"] = self.body(target)

    result = self.drive(screen, steps)
    self.assertIsNone(result["live"])
    self.assertIn("No type information reached discovery", result["body"])

  def test_a_participant_report_opens_nothing(self):
    screen = self.screen(
        participant=records.ParticipantRecord(key="p1", name="app"))

    async def steps(pilot, target, out):
      await self.select(pilot, target, "data")
      out["live"] = target.live

    self.assertIsNone(self.drive(screen, steps)["live"])
    self.assertEqual(StubLive.opened, [])

  def test_a_diagnostic_pass_takes_the_topic_back_and_gives_it_up_again(self):
    """One subscription at a time: the feed steps aside for a probe.

    A feed running through a pass is load the pass is trying to measure, and its
    frames would land in that pass's capture as if the application had sent
    them. It comes back afterwards because the operator is still on the tab.
    """
    session = CaptureStubSession("lo")

    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      out["first"] = screen.live
      await pilot.press("p")
      await pilot.app.workers.wait_for_complete()
      await pilot.pause()
      out["after"] = screen.live

    result = self.drive(self.screen(session=session), steps)
    self.assertTrue(result["first"].closed, "the feed ran through the probe")
    self.assertTrue([call for call in session.calls if call["probe"]])
    self.assertIsInstance(result["after"], StubLive)
    self.assertEqual(len(StubLive.opened), 2)

  def test_the_pass_result_does_not_overwrite_the_live_body(self):
    """`_update_sections` redraws every tab from the last snapshot.

    Without the guard it replaces a running stream with the probe's static
    section, so the feed appears to freeze the moment a pass finishes.
    """
    async def steps(pilot, screen, out):
      await self.select(pilot, screen, "data")
      screen.live.batches = [live_samples(1)]
      screen._pump_live()
      screen.data = report.ReportData(
          domain_id=7, scope="topic 'Telemetry'", all_findings=[],
          endpoint=screen.endpoint)
      screen._update_sections()
      out["body"] = self.body(screen)

    body = self.drive(self.screen(), steps)["body"]
    self.assertIn("STREAMING", body)
    self.assertIn("sample 1", body)


class TestWhyALiveFeedCannotRun(unittest.TestCase):
  """`livedata.why_not` keeps the refusals distinguishable.

  "This target is a reader" and "this writer's type never resolved" have
  different remedies, and an empty feed for either would read as a silent
  writer - the one conclusion neither supports.
  """

  def test_a_writer_with_a_discovered_type_can_stream(self):
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.type = object()
    self.assertIsNone(livedata.why_not(endpoint))

  def test_a_reader_cannot(self):
    endpoint = FakeEndpoint("r1", "Reader")
    endpoint.type = object()
    self.assertIn("is a reader", livedata.why_not(endpoint))

  def test_a_writer_without_a_type_cannot(self):
    self.assertIn("No type information",
                  livedata.why_not(FakeEndpoint("w1", "Writer")))

  def test_a_participant_report_cannot(self):
    self.assertIn("participant report", livedata.why_not(None))


class TestPayloadIsNeverParsedAsMarkup(unittest.TestCase):
  """A Static parses Rich markup, and report bodies carry peer-supplied text.

  Measured on this project's Textual 8.2.8: `update('{"x":"[/]"}')` raises
  MarkupError, and `[red]` silently eats the rest of its line. So a writer
  publishing a string field that happens to contain square brackets could crash
  the live feed's timer or quietly delete part of its own payload - and the
  payload is the one thing the Data tab exists to show verbatim.
  """

  HOSTILE = '{"label":"[/]","note":"[red]hidden","path":"a[0]"}'

  def test_textual_really_does_raise_on_a_closing_tag(self):
    """The premise, asserted rather than assumed.

    If a future Textual stops interpreting markup here, this test says so and
    the escaping below becomes belt-and-braces rather than load-bearing.
    """
    from textual.markup import MarkupError
    with self.assertRaises(MarkupError):
      report_screen.Static("").update(self.HOSTILE)

  def test_a_report_body_takes_its_text_literally(self):
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.sample_texts = [self.HOSTILE]
    result.samples_taken = 1

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        # After mount: `_render_static` replaces `data` with the session's.
        screen.data = report.ReportData(
            domain_id=7, scope="topic 'Telemetry'", all_findings=[],
            endpoint=screen.endpoint, probe_result=result)
        screen._update_sections()
        await pilot.pause()

    asyncio.run(run())
    body = str(screen.bodies["data"].render())
    self.assertIn("[/]", body)
    self.assertIn("[red]hidden", body, "markup ate part of the payload")

  def test_report_sections_style_status_without_parsing_markup(self):
    plain = "[ERROR] rung 4  match.none\n[WARN] rung 3  type.partial\n"
    styled = report_screen.ReportScreen._styled_section_text("findings", plain)
    self.assertEqual(str(styled), plain)
    self.assertEqual([str(span.style) for span in styled.spans],
                     ["bold red", "bold yellow"])

  def test_the_live_feed_takes_its_samples_literally(self):
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    screen.endpoint.type = object()
    screen.session.participant = object()
    StubLive.opened = []

    async def run():
      app = Harness(screen)
      with mock.patch.object(livedata, "LiveSubscription", StubLive):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          screen.query_one("#report_tabs",
                           report_screen.TabbedContent).active = "data"
          await pilot.pause()
          screen.live.batches = [[livedata.LiveSample(1, 1700000000.0,
                                                      self.HOSTILE)]]
          screen._pump_live()
          await pilot.pause()

    asyncio.run(run())
    body = str(screen.bodies["data"].render())
    self.assertIn("[/]", body)
    self.assertIn("[red]hidden", body)


class TestTheFeedHeaderAccountsForEverySample(unittest.TestCase):
  """What arrived, what is shown, and the difference between them.

  `take()` returns copies of everything available in one call, so a display cap
  cannot defer the surplus - it can only drop it. Dropping it silently would let
  the header describe this UI's refresh rate as the writer's rate.
  """

  def subscription(self, reader, endpoint):
    """A real `LiveSubscription`, with only the DDS constructors stubbed.

    The earlier version of this helper used `object.__new__` and set the fields
    by hand, which made the mirror test below vacuous: it could only compare the
    attributes the test itself remembered, so two the constructor really adds
    went unnoticed. Running the actual `__init__` is what makes that guard mean
    something.
    """
    with mock.patch.object(livedata, "dds") as dds, \
         mock.patch.object(livedata.probe, "build_subscriber",
                           return_value=(mock.Mock(), {})), \
         mock.patch.object(livedata.probe, "build_reader_qos",
                           return_value=(mock.Mock(), {})):
      dds.DynamicData.Topic.return_value = mock.Mock()
      dds.DynamicData.DataReader.return_value = reader
      return livedata.LiveSubscription(mock.Mock(), endpoint)

  def isolated_subscription(self, reader, endpoint, participant):
    """A real isolated `LiveSubscription` over a fake disposable participant.

    Only `create_probe_participant` and the DDS constructors are stubbed, so the
    isolation sweep, its bookkeeping and `close()`'s ownership of the
    participant are the production ones.
    """
    with mock.patch.object(livedata, "dds") as dds, \
         mock.patch.object(livedata.discovery, "create_probe_participant",
                           return_value=participant), \
         mock.patch.object(livedata.probe, "build_subscriber",
                           return_value=(mock.Mock(), {})), \
         mock.patch.object(livedata.probe, "build_reader_qos",
                           return_value=(mock.Mock(), {})):
      dds.DynamicData.Topic.return_value = mock.Mock()
      dds.DynamicData.DataReader.return_value = reader
      return livedata.LiveSubscription(mock.Mock(), endpoint, isolate=True,
                                       domain_id=7)

  class FakeReader:
    """Only what `poll` touches: matched publications and `take`."""

    def __init__(self, samples, publication_key="w1"):
        self.samples = samples
        self.publication_key = publication_key
        self.matched_publications = ["h1"]

    def matched_publication_data(self, handle):
      key = type("Value", (), {"value": self.publication_key})()
      return type("Data", (), {"key": key})()

    def take(self):
      taken, self.samples = self.samples, []
      return taken

  @staticmethod
  def sample(number, handle="h1", valid=True):
    info = type("Info", (), {"valid": valid, "publication_handle": handle})()
    data = type("Data", (), {"to_json": lambda self: '{"id":%d}' % number})()
    return type("Sample", (), {"info": info, "data": data})()

  def test_a_burst_past_the_display_cap_is_counted_not_hidden(self):
    burst = [self.sample(n) for n in range(livedata.BATCH_LIMIT + 25)]
    live = self.subscription(self.FakeReader(burst), FakeEndpoint("w1", "Writer"))
    samples, skipped = live.poll()
    self.assertEqual(len(samples), livedata.BATCH_LIMIT)
    self.assertEqual(live.received, livedata.BATCH_LIMIT + 25)
    self.assertEqual(live.dropped, 25)
    self.assertEqual(skipped, 0)
    # The newest survive, and their numbering stays continuous with `received`
    # so the operator can see the gap rather than infer it.
    self.assertEqual(samples[-1].number, live.received)

  def test_another_writer_s_samples_are_skipped_and_counted_separately(self):
    mixed = [self.sample(1), self.sample(2, handle="h9")]
    reader = self.FakeReader(mixed)
    live = self.subscription(reader, FakeEndpoint("w1", "Writer"))
    samples, skipped = live.poll()
    self.assertEqual(len(samples), 1)
    self.assertEqual(skipped, 1)
    self.assertEqual(live.others, 1)
    self.assertEqual(live.received, 1)

  def test_invalid_samples_are_neither_shown_nor_counted(self):
    live = self.subscription(
        self.FakeReader([self.sample(1, valid=False), self.sample(2)]),
        FakeEndpoint("w1", "Writer"))
    samples, _ = live.poll()
    self.assertEqual(len(samples), 1)
    self.assertEqual(live.received, 1)
    self.assertEqual(live.dropped, 0)

  def test_a_poll_that_raises_reports_nothing_rather_than_propagating(self):
    """The poll runs on a UI timer, where an exception kills the feed."""
    class Exploding(self.FakeReader):
      def take(self):
        raise RuntimeError("take exploded")

    live = self.subscription(Exploding([]), FakeEndpoint("w1", "Writer"))
    self.assertEqual(live.poll(), ([], 0))

  def test_a_closed_subscription_polls_nothing(self):
    live = self.subscription(self.FakeReader([self.sample(1)]),
                             FakeEndpoint("w1", "Writer"))
    live.close()
    self.assertEqual(live.poll(), ([], 0))
    self.assertTrue(live.closed)
    live.close()  # idempotent: the view closes on tab change AND on unmount

  class IsolationParticipant:
    """A disposable participant that records what the feed ignored."""

    def __init__(self, keys=(), topic_name="Telemetry"):
      samples = []
      for key in keys:
        info = type("Info", (), {"valid": True, "instance_handle": f"h-{key}"})()
        data = type("Data", (), {
            "key": type("K", (), {"value": key})(),
            "participant_key": type("K", (), {"value": "p1"})(),
            "topic_name": topic_name, "type_name": "TelemetryType"})()
        samples.append(type("S", (), {"info": info, "data": data})())
      # `take()`, consuming, as the real builtin reader does - see
      # test_checks.FakeBuiltinReader for why the fake models the consumption.
      def take(_self, box=samples):
        taken, box[:] = list(box), []
        return taken
      self.publication_reader = type("R", (), {"take": take})()
      self.ignored = []
      self.closes = 0

    def ignore_datawriter(self, handle):
      self.ignored.append(handle)

    def close(self):
      self.closes += 1

  def test_an_isolated_feed_ignores_the_other_writers_on_the_topic(self):
    """The Data tab used to show nothing for a writer losing EXCLUSIVE ownership.

    Its own correlation runs in `poll()`, downstream of ownership arbitration,
    so the starved writer's samples were discarded by the middleware before the
    feed could sort them. Ignoring the competitors is the only thing that fixes
    it, and it is the same sweep the probe runs.
    """
    participant = self.IsolationParticipant(keys=("w1", "w2", "w3"))
    live = self.isolated_subscription(
        self.FakeReader([]), FakeEndpoint("w1", "Writer"), participant)
    self.assertEqual(participant.ignored, ["h-w2", "h-w3"])
    self.assertEqual([r["key"] for r in live.ignored], ["w2", "w3"])
    self.assertTrue(live.isolated)
    self.assertTrue(live.isolation_target_seen)
    self.assertIsNone(live.isolation_error)

  def test_closing_an_isolated_feed_releases_its_participant(self):
    """The ignores last for the participant's life, so it must not outlive the tab."""
    participant = self.IsolationParticipant(keys=("w1", "w2"))
    live = self.isolated_subscription(
        self.FakeReader([]), FakeEndpoint("w1", "Writer"), participant)
    self.assertEqual(participant.closes, 0)
    live.close()
    self.assertEqual(participant.closes, 1)
    live.close()  # idempotent, as every other close on this object is
    self.assertEqual(participant.closes, 1)

  def test_a_feed_that_cannot_isolate_still_streams_and_says_why(self):
    """Same contract as the probe: never a silent downgrade to un-isolated."""
    with mock.patch.object(livedata, "dds") as dds, \
         mock.patch.object(livedata.discovery, "create_probe_participant",
                           side_effect=RuntimeError("no participant")), \
         mock.patch.object(livedata.probe, "build_subscriber",
                           return_value=(mock.Mock(), {})), \
         mock.patch.object(livedata.probe, "build_reader_qos",
                           return_value=(mock.Mock(), {})):
      dds.DynamicData.Topic.return_value = mock.Mock()
      dds.DynamicData.DataReader.return_value = self.FakeReader([])
      live = livedata.LiveSubscription(mock.Mock(), FakeEndpoint("w1", "Writer"),
                                       isolate=True, domain_id=7)
    self.assertTrue(live.isolation_requested)
    self.assertFalse(live.isolated)
    self.assertIn("no participant", live.isolation_error)
    self.assertIsNotNone(live._reader, "the feed must still stream")

  def test_the_stub_mirrors_the_real_subscription(self):
    """Every attribute the view reads must exist on both.

    Twice now the header grew a counter and the stub did not, which fails as an
    AttributeError inside a UI timer - a place where the real feed would simply
    stop updating.
    """
    real = {name for name in vars(self.subscription(
        self.FakeReader([]), FakeEndpoint("w1", "Writer")))
        if not name.startswith("_")}
    self.assertIn("correlated", real, "the helper no longer builds a real one")
    stub = {name for name in vars(StubLive(object(), FakeEndpoint("w1", "Writer")))
            if not name.startswith("_")}
    self.assertEqual(real - stub, set(),
                     "the stub is missing state the real subscription exposes")

  def test_an_uncorrelated_feed_says_its_samples_are_topic_wide(self):
    """The scan returning None means "cannot attribute", never "no match".

    The probe carries that into its report as a topic-scoped caveat; a feed that
    showed the same traffic under this endpoint's name with no caveat would be
    the false certainty the three-valued scan exists to prevent.
    """
    class Uncorrelatable(self.FakeReader):
      """The binding cannot report matched publications at all.

      Set in `__init__`, not as a class attribute: the base sets the instance
      attribute, which would shadow it and leave this fake correlatable.
      """

      def __init__(self, samples):
        super().__init__(samples)
        self.matched_publications = None

    live = self.subscription(Uncorrelatable([self.sample(1), self.sample(2, "h9")]),
                             FakeEndpoint("w1", "Writer"))
    samples, skipped = live.poll()
    self.assertFalse(live.correlated)
    # Nothing is filtered, because nothing can be attributed either way.
    self.assertEqual(len(samples), 2)
    self.assertEqual(skipped, 0)

    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    screen.live = live
    screen.live_samples.extend(samples)
    self.assertIn("TOPIC-WIDE", screen._live_header())

  def test_a_correlated_feed_carries_no_caveat(self):
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    screen.live = StubLive(object(), screen.endpoint)
    screen.live_samples.extend(live_samples(1))
    self.assertNotIn("TOPIC-WIDE", screen._live_header())

  def test_the_header_names_what_it_is_not_showing(self):
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    screen.live = StubLive(object(), screen.endpoint)
    screen.live.received, screen.live.dropped, screen.live.others = 4000, 3960, 7
    screen.live_samples.extend(live_samples(2))
    header = screen._live_header()
    self.assertIn("4000 sample(s) received", header)
    self.assertIn("3960 arrived faster", header)
    self.assertIn("7 from other writers", header)

  def _isolated_header(self, **fields):
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    screen.live = StubLive(object(), screen.endpoint, isolate=True)
    for name, value in fields.items():
      setattr(screen.live, name, value)
    return screen._live_header()

  def test_the_header_says_what_the_feed_ignored(self):
    """The Data tab has no findings section, so the header is the only place
    it can admit that it narrowed the topic."""
    header = self._isolated_header(ignored=[{"key": "w2"}, {"key": "w3"}])
    self.assertIn("isolated: 2 other writer(s) on this topic ignored", header)

  def test_ignoring_nothing_is_still_stated(self):
    """Otherwise "0 received" cannot be told from "0 received, and we hid two"."""
    self.assertIn("no other writer on this topic to ignore",
                  self._isolated_header())

  def test_a_feed_that_could_not_isolate_says_so_in_the_header(self):
    header = self._isolated_header(isolated=False,
                                   isolation_error="no participant")
    self.assertIn("NOT ISOLATED", header)
    self.assertIn("no participant", header)

  def test_a_partial_isolation_is_not_reported_as_a_clean_one(self):
    header = self._isolated_header(
        ignored=[{"key": "w2"}],
        ignore_failures=[{"key": "w3", "error": "refused"}])
    self.assertIn("1 could NOT be ignored", header)

  def test_the_header_does_not_claim_nothing_to_ignore_when_all_failed(self):
    """`ignored` was checked first, so the failure count was unreachable.

    With every ignore refused the header read "no other writer on this topic to
    ignore" while those writers were still delivering into this very feed.
    """
    header = self._isolated_header(
        ignore_failures=[{"key": "w2", "error": "refused"}])
    self.assertNotIn("no other writer on this topic to ignore", header)
    self.assertIn("INCOMPLETE", header)
    self.assertIn("1 could NOT be ignored", header)

  def test_the_header_reports_a_sweep_that_failed_mid_feed(self):
    header = self._isolated_header(ignored=[{"key": "w2"}],
                                   isolation_error="boom")
    self.assertIn("INCOMPLETE", header)
    self.assertIn("the sweep failed", header)

  def test_an_unisolated_feed_adds_nothing_to_the_header(self):
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)
    screen.live = StubLive(object(), screen.endpoint)
    self.assertNotIn("isolated", screen._live_header())


class TestTheFeedNoteDoesNotHideTheSnapshot(unittest.TestCase):
  """A feed that could not start is a reason to read the probe's samples.

  The note used to replace the SAMPLE DATA appendix and then persist for the
  life of the report, so one transient reader failure permanently hid the
  payload the probe had already captured.
  """

  def screen(self):
    session = CaptureStubSession("lo")
    session.participant = object()
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.type = object()
    return report_screen.ReportScreen(session, endpoint=endpoint, probe=False)

  @staticmethod
  def probed_data(endpoint):
    """A report whose probe captured one sample, as a real pass would leave."""
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.sample_texts = ['{"id":7}']
    result.samples_taken = 1
    return report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=endpoint, probe_result=result)

  def drive(self, screen, steps):
    collected = {}

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        # Assigned after mount: `_render_static` replaces `data` on the way in.
        screen.data = self.probed_data(screen.endpoint)
        screen._update_sections()
        await steps(pilot, screen, collected)

    asyncio.run(run())
    return collected

  def test_a_reader_that_will_not_open_still_shows_the_captured_samples(self):
    screen = self.screen()

    async def steps(pilot, target, out):
      with mock.patch.object(livedata, "LiveSubscription",
                             side_effect=RuntimeError("no reader for you")):
        target.query_one("#report_tabs",
                         report_screen.TabbedContent).active = "data"
        await pilot.pause()
      out["body"] = str(target.bodies["data"].render())

    body = self.drive(screen, steps)["body"]
    self.assertIn("could not create a reader", body)
    self.assertIn("SAMPLE DATA", body, "the note replaced the snapshot")
    self.assertIn('{"id":7}', body, "the probe's own samples were hidden")

  def test_the_note_does_not_outlive_the_attempt(self):
    screen = self.screen()

    async def steps(pilot, target, out):
      tabs = target.query_one("#report_tabs", report_screen.TabbedContent)
      with mock.patch.object(livedata, "LiveSubscription",
                             side_effect=RuntimeError("no reader for you")):
        tabs.active = "data"
        await pilot.pause()
      tabs.active = "probe"
      await pilot.pause()
      out["note"] = target.live_note
      target._update_sections()
      await pilot.pause()
      out["body"] = str(target.bodies["data"].render())

    result = self.drive(screen, steps)
    self.assertEqual(result["note"], "")
    self.assertNotIn("could not create a reader", result["body"])
    self.assertIn("SAMPLE DATA", result["body"])


class TestProbingWhileThisReportIsAlreadyProbing(unittest.TestCase):
  """`p` during this report's own pass must not misreport whose pass it is.

  `_offer_full_pass` only knows "a pass is in flight somewhere", so it blamed
  another report - and overwrote the pre-tshark announcement naming the
  interface, the duration and the capture file on its way out.
  """

  def test_it_names_this_report_and_leaves_the_announcement_alone(self):
    session = CaptureStubSession("lo")
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=False)
    said = []

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        # Mid-pass, exactly as an operator would find it.
        screen.probing = True
        original = screen.status.update
        screen.status.update = lambda text: (said.append(str(text)),
                                             original(text))[1]
        await pilot.press("p")
        await pilot.pause()
        screen.probing = False

    asyncio.run(run())
    self.assertEqual(len(said), 1, said)
    self.assertIn("This report's diagnostic pass", said[0])
    self.assertNotIn("another report", said[0])
    # And it did not start a second one.
    self.assertEqual([call for call in session.calls if call["probe"]], [])


class TestTheThirdReviewRound(unittest.TestCase):
  """Regressions for defects a review found that the tests above did not.

  Each one was reachable and none was caught by the suite that shipped with the
  feature, which is the reason they are grouped rather than scattered: this is
  the list to re-read before trusting this feature's coverage.
  """

  # --- The feed's rendering is bounded, not just its memory ------------------

  def test_a_burst_renders_only_what_it_will_show(self):
    """`sample_repr` serializes a whole payload, so rendering a 4000-sample
    burst and then keeping 40 would stall the UI timer it runs on."""
    helper = TestTheFeedHeaderAccountsForEverySample()
    burst = [helper.sample(n) for n in range(livedata.BATCH_LIMIT * 3)]
    live = helper.subscription(helper.FakeReader(burst),
                               FakeEndpoint("w1", "Writer"))
    renders = []
    original = livedata.probe.sample_repr
    with mock.patch.object(livedata.probe, "sample_repr",
                           side_effect=lambda data, limit=None: (
                               renders.append(1), original(data, limit or 800))[1]):
      samples, _ = live.poll()
    self.assertEqual(len(samples), livedata.BATCH_LIMIT)
    self.assertEqual(len(renders), livedata.BATCH_LIMIT,
                     "every sample in the burst was serialized to show 40")
    # And the count still reflects everything that arrived.
    self.assertEqual(live.received, livedata.BATCH_LIMIT * 3)
    self.assertEqual(live.dropped, livedata.BATCH_LIMIT * 2)

  # --- A restart is only promised where one can happen ----------------------

  def feed_screen(self):
    session = CaptureStubSession("lo")
    session.participant = object()
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.type = object()
    return report_screen.ReportScreen(session, endpoint=endpoint, probe=False)

  def test_this_report_s_own_pass_promises_the_feed_back(self):
    screen = self.feed_screen()
    screen.probing = True
    screen._start_live()
    self.assertIn("This report's diagnostic pass", screen.live_note)
    self.assertIn("starts when it finishes", screen.live_note)
    self.assertIsNone(screen.live)

  def test_another_report_s_pass_tells_the_operator_what_to_do(self):
    """Nothing calls back into this screen when the pass belongs elsewhere, so
    promising an automatic restart would leave a tab waiting forever."""
    screen = self.feed_screen()
    screen.session.claim_pass(60.0)
    screen._start_live()
    self.assertIn("another report", screen.live_note)
    self.assertIn("Select this tab again", screen.live_note)
    self.assertNotIn("starts when it finishes", screen.live_note)

  # --- A pass finishing must not reopen a feed on a screen that is gone -----

  def test_a_pass_finishing_under_another_screen_does_not_open_a_reader(self):
    """The pass's `finally` can run after the operator moved on.

    Modelled as another screen on top - the capture picker, the matrix screen -
    which is the case that matters and the one `is_current` does NOT detect:
    measured on this Textual, a screen under another still reports
    `is_current` True.
    """
    from textual.screen import Screen

    screen = self.feed_screen()
    StubLive.opened = []

    async def run():
      app = Harness(screen)
      with mock.patch.object(livedata, "LiveSubscription", StubLive):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          screen.query_one("#report_tabs",
                           report_screen.TabbedContent).active = "data"
          await pilot.pause()
          screen._stop_live()
          app.push_screen(Screen())
          await pilot.pause()
          # Exactly what `_run_pass`'s finally does.
          screen._start_live_if_active()
          await pilot.pause()

    asyncio.run(run())
    # One from selecting the tab, and none from the pass finishing.
    self.assertEqual(len(StubLive.opened), 1,
                     "a reader was opened for a screen nobody is looking at")

  def test_the_restart_hook_survives_a_torn_down_screen(self):
    """It is called from a `finally`, where raising is worse than doing
    nothing: reading `app` at all throws on a screen with no app."""
    screen = self.feed_screen()
    StubLive.opened = []
    with mock.patch.object(livedata, "LiveSubscription", StubLive):
      screen._start_live_if_active()   # never mounted: must not raise
    self.assertEqual(StubLive.opened, [])

  # --- Stale samples must not displace a fresher snapshot -------------------

  def test_a_closed_feed_s_samples_do_not_replace_a_new_snapshot(self):
    screen = self.feed_screen()
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.sample_texts = ['{"fresh":true}']
    result.samples_taken = 1
    StubLive.opened = []

    async def run():
      app = Harness(screen)
      with mock.patch.object(livedata, "LiveSubscription", StubLive):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          tabs = screen.query_one("#report_tabs", report_screen.TabbedContent)
          tabs.active = "data"
          await pilot.pause()
          screen.live.batches = [live_samples(1)]
          screen._pump_live()
          tabs.active = "probe"
          await pilot.pause()
          screen.data = report.ReportData(
              domain_id=7, scope="topic 'Telemetry'", all_findings=[],
              endpoint=screen.endpoint, probe_result=result)
          screen._update_sections()
          await pilot.pause()

    asyncio.run(run())
    body = str(screen.bodies["data"].render())
    self.assertIn('{"fresh":true}', body, "older feed samples hid the snapshot")
    self.assertNotIn("FEED CLOSED", body)

  # --- VENDORID_UNKNOWN is not a foreign vendor -----------------------------

  def test_an_unstated_vendor_id_is_not_offered_the_matrix(self):
    """00.00 is the wire saying "not stated", which is a vendor we do not know
    rather than a vendor that is not RTI."""
    self.assertFalse(vendors.is_foreign(vendor_id(0x00, first=0x00)))
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.vendor_id = vendor_id(0x00, first=0x00)
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=endpoint, probe=False)
    self.assertFalse(screen.check_action("compatibility_matrix", None))

  def test_a_stated_foreign_vendor_still_is(self):
    self.assertTrue(vendors.is_foreign(vendor_id(0x10)))
    self.assertFalse(vendors.is_foreign(vendor_id(0x01)))
    self.assertFalse(vendors.is_foreign(None))

  # --- A probe that created nothing says so first ---------------------------

  def test_a_reader_target_with_no_type_is_not_told_a_writer_was_created(self):
    """`probe_reader_endpoint` sets `probe_kind` before it discovers it cannot
    create anything, so the kind branch had to come second."""
    result = probe.ProbeResult()
    result.attempted = True
    result.probe_kind = "writer"
    result.create_error = "no type information available, cannot create a writer"
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("r1", "Reader"), probe_result=result))
    text = sections["data"]
    self.assertIn("No writer was created", text)
    self.assertIn("no type information available", text)
    self.assertNotIn("created a WRITER", text)

  def test_a_reader_target_that_did_create_a_writer_still_explains_itself(self):
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.probe_kind = "writer"
    result.samples_written = 3
    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("r1", "Reader"), probe_result=result))
    self.assertIn("created a WRITER", sections["data"])


class TestTheFourthReviewRound(unittest.TestCase):
  """Regressions for the fourth pass: what the feed says when nothing arrives."""

  def feed_screen(self):
    session = CaptureStubSession("lo")
    session.participant = object()
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.type = object()
    return report_screen.ReportScreen(session, endpoint=endpoint, probe=False)

  def open_feed(self, screen, steps):
    """Run `steps` with the feed open, and return the body AS IT WAS THEN.

    Read inside the app, not after it: unmounting runs `_stop_live`, which
    clears any note and redraws - so a body read after teardown is a different
    body, and an assertion on it is testing the teardown.
    """
    collected = {}

    async def run():
      app = Harness(screen)
      with mock.patch.object(livedata, "LiveSubscription", StubLive):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          screen.query_one("#report_tabs",
                           report_screen.TabbedContent).active = "data"
          await pilot.pause()
          await steps(pilot, screen)
          collected["body"] = str(screen.bodies["data"].render())

    asyncio.run(run())
    return collected["body"]

  def test_the_topic_wide_caveat_clears_once_correlation_resolves(self):
    """Correlation is unknown until the first poll, and a writer that never
    sends would otherwise carry "cannot attribute" for the whole session."""
    screen = self.feed_screen()

    async def steps(pilot, target):
      # As the real subscription starts: not yet polled, so not yet correlated.
      target.live.correlated = False
      target._render_live()
      self.assertIn("TOPIC-WIDE", str(target.bodies["data"].render()))
      # A poll that resolves correlation but brings nothing must still redraw.
      target.live.correlated = True
      target._pump_live()
      await pilot.pause()

    self.assertNotIn("TOPIC-WIDE", self.open_feed(screen, steps))

  def test_a_quiet_poll_that_changes_nothing_does_not_redraw(self):
    """The redraw is per changed header, not per tick: at the window's worst
    case it costs milliseconds, and an idle feed should cost none of them."""
    screen = self.feed_screen()
    renders = []

    async def steps(pilot, target):
      original = target.bodies["data"].update
      target.bodies["data"].update = lambda content: (
          renders.append(1), original(content))[1]
      target._pump_live()
      target._pump_live()
      await pilot.pause()
      # Counted here rather than after the app exits: teardown redraws.
      self.assertEqual(renders, [], "an idle feed redrew itself")

    self.open_feed(screen, steps)

  def test_a_reader_that_cannot_be_read_stops_and_says_so(self):
    """A failing poll returns nothing, and nothing looks exactly like a quiet
    writer - so the tool's own broken reader was reported as the peer's
    silence, five log lines a second, forever."""
    screen = self.feed_screen()

    async def steps(pilot, target):
      target.live.errors = report_screen.LIVE_ERROR_LIMIT
      target.live.last_error = "RuntimeError: take failed"
      opened = target.live
      target._pump_live()
      await pilot.pause()
      self.assertTrue(opened.closed, "the failing reader was left open")
      self.assertIsNone(target.live)
      self.assertIsNone(target.live_timer, "the poll timer kept running")

    body = self.open_feed(screen, steps)
    self.assertIn("stopped after", body)
    self.assertIn("take failed", body)
    self.assertNotIn("Waiting for the first sample", body)

  def test_one_failed_poll_is_not_enough_to_give_up(self):
    screen = self.feed_screen()

    async def steps(pilot, target):
      target.live.errors = 1
      target.live.last_error = "RuntimeError: transient"
      target._pump_live()
      await pilot.pause()
      self.assertIsNotNone(target.live, "one bad read closed the feed")

    self.open_feed(screen, steps)

  def test_the_subscription_counts_consecutive_failures_and_forgets_them(self):
    helper = TestTheFeedHeaderAccountsForEverySample()

    class Flaky(helper.FakeReader):
      def __init__(self, samples):
        super().__init__(samples)
        self.fail = True

      def take(self):
        if self.fail:
          raise RuntimeError("take failed")
        return super().take()

    reader = Flaky([helper.sample(1)])
    live = helper.subscription(reader, FakeEndpoint("w1", "Writer"))
    live.poll()
    live.poll()
    self.assertEqual(live.errors, 2)
    self.assertIn("take failed", live.last_error)
    reader.fail = False
    live.poll()
    self.assertEqual(live.errors, 0, "a good read did not clear the streak")
    self.assertEqual(live.last_error, "")

  def test_w_is_hidden_until_this_report_probes(self):
    """`action_verify_delivery` refuses a report that never probed, so the
    footer must not advertise the key - and `p` is what makes it real."""
    session = CaptureStubSession("lo")
    endpoint = FakeEndpoint("r1", "Reader")
    passive = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    self.assertFalse(passive.check_action("verify_delivery", None))
    probed = report_screen.ReportScreen(session, endpoint=endpoint, probe=True)
    self.assertTrue(probed.check_action("verify_delivery", None))
    writer = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=True)
    self.assertFalse(writer.check_action("verify_delivery", None))

  def test_the_refusals_point_at_p_rather_than_at_reopening(self):
    """The dead end this change set removed, still quoted in two places."""
    session = CaptureStubSession("lo")
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("r1", "Reader"), probe=False)
    screen.status = mock.Mock()
    screen.action_verify_delivery()
    said = screen.status.update.call_args[0][0]
    self.assertIn("Press p", said)
    self.assertNotIn("Open it for diagnosis", said)

    sections = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer")))
    self.assertIn("Press p", sections["data"])


class TestTheFifthReviewRound(unittest.TestCase):
  """Regressions for the fifth pass."""

  def test_rti_connext_micro_is_not_a_foreign_vendor(self):
    """01.0A is an RTI product, so a "cross-vendor" matrix against it would be
    a cross-vendor experiment against RTI.

    `docs/CODE_REVIEW_2026-08-04.md` recorded 01.0A as unmapped back when it was
    only a naming gap; `is_foreign` turned it into a wrong answer that drives a
    key.
    """
    micro = vendor_id(0x0A)
    self.assertFalse(vendors.is_foreign(micro))
    self.assertTrue(vendors.is_rti_family(micro))
    self.assertTrue(vendors.is_rti_family(vendor_id(0x01)))
    self.assertFalse(vendors.is_rti_family(vendor_id(0x10)))
    # And it is named rather than reported as an unrecognized id.
    self.assertEqual(vendors.vendor_name(micro), "RTI Connext DDS Micro")
    # Recognized is not the same as measured against.
    self.assertFalse(vendors.is_validated(micro))

  def test_the_matrix_key_is_hidden_on_a_micro_writer(self):
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.vendor_id = vendor_id(0x0A)
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=endpoint, probe=False)
    self.assertFalse(screen.check_action("compatibility_matrix", None))
    screen.status = mock.Mock()
    screen.action_compatibility_matrix()
    said = screen.status.update.call_args[0][0]
    self.assertIn("RTI Connext DDS Micro", said)
    self.assertIn("no cross-vendor matrix is needed", said)
    self.assertNotIn("could not be read", said)

  def test_a_participant_report_does_not_advertise_a_hidden_key(self):
    """`check_action` hides `p` with no endpoint, so the body must not name it."""
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"),
        participant=records.ParticipantRecord(key="p1", name="app"))
    self.assertFalse(screen.check_action("probe", None))
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="participant 'app'", all_findings=[]))["data"]
    self.assertIn("no endpoint to probe or stream", text)
    self.assertNotIn("Press p", text)

  def test_an_endpoint_report_still_names_the_key(self):
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer")))["data"]
    self.assertIn("Press p", text)

  def test_failure_text_with_brackets_does_not_crash_the_report(self):
    """Exception text is OS- and peer-supplied, and these Statics parse markup.

    The same hazard the body rendering was fixed for, in the except branch that
    reports it - where raising replaces a readable failure with a dead TUI.
    """
    session = CaptureStubSession("lo")
    session.diagnose_endpoint = mock.Mock(
        side_effect=RuntimeError("boom [/] at [red]offset"))
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=False)

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        return str(screen.bodies["overview"].render())

    said = asyncio.run(run())
    self.assertIn("Static checks failed", said)
    self.assertIn("boom", said)


class TestTheSixthReviewRound(unittest.TestCase):
  """Regressions for the sixth pass: one markup policy, and two honesty fixes.

  The markup findings kept recurring because the fix was per call site, so three
  rounds each found another unescaped sibling - and then an escaped one rendered
  its own backslashes. The policy now lives on the widgets, and these tests
  assert the property rather than any one call site.
  """

  HOSTILE = "boom [/] at [red]offset"

  def test_every_generated_text_widget_takes_its_content_literally(self):
    """The invariant, stated once: nothing that shows generated text parses it.

    Asserted on the widgets so a new `status.update` call site cannot reintroduce
    this, which is exactly how it kept coming back.
    """
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"), endpoint=FakeEndpoint("w1", "Writer"),
        probe=False)

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        literal = {name: widget._render_markup is False
                   for name, widget in
                   [("status", screen.status)]
                   + [(f"body:{tab}", body)
                      for tab, body in screen.bodies.items()]}
        return literal

    literal = asyncio.run(run())
    self.assertTrue(all(literal.values()),
                    f"these parse markup: "
                    f"{[k for k, v in literal.items() if not v]}")

  def test_the_matrix_detail_pane_keeps_report_severity_labels(self):
    """Report text uses "[ERROR]" labels, which markup silently swallows."""
    screen = report_screen.CompatibilityMatrixScreen([], "/tmp/matrix")

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        screen.detail.update("[ERROR] match.none  " + self.HOSTILE)
        await pilot.pause()
        return str(screen.detail.render())

    shown = asyncio.run(run())
    self.assertIn("[ERROR]", shown, "markup ate the severity label")
    self.assertIn("[red]offset", shown)
    self.assertIn("[/]", shown)

  def test_error_text_reaches_the_operator_without_backslashes(self):
    """The other half of the same mistake: escaping AND taking literally shows
    the escape characters to the operator."""
    session = CaptureStubSession("lo")
    session.diagnose_endpoint = mock.Mock(side_effect=RuntimeError(self.HOSTILE))
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=False)

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        return str(screen.bodies["overview"].render())

    shown = asyncio.run(run())
    self.assertIn(self.HOSTILE, shown)
    self.assertNotIn("\\[", shown, "the operator was shown escape characters")

  @unittest.skip("interface capture was removed")
  def test_p_during_the_capture_question_does_not_stack_a_second_picker(self):
    """`probing` and `capturing` are both False while the picker waits, so the
    entry offer and `p` could each push one - and the discarded answer still
    changed the interface the session remembers."""
    session = CaptureStubSession()          # no answer yet: it will ask
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=True)
    pushed = []

    async def run():
      app = Harness(screen)
      with mock.patch.object(report_screen.wire, "capture_interfaces",
                             return_value=((("1", "lo"),), None)):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          await pilot.pause()
          pushed.append(self.pickers(app))
          self.assertTrue(screen.asking)
          # The operator presses `p` while the question is open.
          screen.action_probe()
          await pilot.pause()
          pushed.append(self.pickers(app))
          out = status_text(screen)
      return out

    said = asyncio.run(run())
    # Counted in the stack, not just on top: a second picker pushed over the
    # first would still leave a picker on top and look correct.
    self.assertEqual(pushed, [1, 1], "`p` stacked a second capture picker")
    self.assertIn("Answer the capture question first", said)

  @unittest.skip("interface capture was removed")
  def test_the_entry_offer_does_not_stack_a_picker_over_an_open_one(self):
    """The other half, and the one the race actually goes through.

    `on_mount` awaits the static pass, and its trailing offer runs afterwards -
    by which time `p` may have opened the picker. The guard in `action_probe`
    cannot cover that direction, so this drives `_offer_full_pass` directly.
    """
    session = CaptureStubSession()
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=True)
    counted = []

    async def run():
      app = Harness(screen)
      with mock.patch.object(report_screen.wire, "capture_interfaces",
                             return_value=((("1", "lo"),), None)):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          await pilot.pause()
          counted.append(self.pickers(app))
          # Exactly what `on_mount` does after its await.
          screen._offer_full_pass()
          await pilot.pause()
          counted.append(self.pickers(app))

    asyncio.run(run())
    self.assertEqual(counted, [1, 1],
                     "the entry offer stacked a second capture picker")

  @staticmethod
  def pickers(app):
    return len([screen for screen in app.screen_stack
                if isinstance(screen, report_screen.CaptureInterfaceScreen)])

  @unittest.skip("interface capture was removed")
  def test_answering_the_picker_reopens_the_asking_window(self):
    """`asking` must not latch, or a declined pass locks the key out."""
    session = CaptureStubSession()
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=True)

    async def run():
      app = Harness(screen)
      with mock.patch.object(report_screen.wire, "capture_interfaces",
                             return_value=((("1", "lo"),), None)):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          await pilot.pause()
          picker = app.screen
          row = [index for index, choice in enumerate(picker.choices)
                 if choice[1] == report_screen.SKIP_CAPTURE]
          picker.table.move_cursor(row=row[0])
          await pilot.press("enter")
          await app.workers.wait_for_complete()
          await pilot.pause()
          return screen.asking

    self.assertFalse(asyncio.run(run()), "`asking` latched after an answer")

  def test_an_aborted_probe_is_not_reported_as_a_quiet_writer(self):
    """`error` is a failure AFTER the reader was created, so its window is not
    a window the writer was observed for."""
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.elapsed = 3.0
    result.error = "RuntimeError: status read failed"
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer"), probe_result=result))["data"]
    self.assertIn("the probe then failed", text)
    self.assertIn("status read failed", text)
    self.assertIn("probe rather than about the writer", text)
    self.assertNotIn("nothing to say", text)

  def test_a_clean_empty_window_still_reads_as_writer_silence(self):
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.elapsed = 3.0
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer"), probe_result=result))["data"]
    self.assertIn("nothing to say", text)


class TestTheSeventhReviewRound(unittest.TestCase):
  """Regressions for the seventh pass."""

  def test_a_report_that_cannot_stream_does_not_invite_streaming(self):
    """The refusal and the invitation were printed one after the other.

    A reader target and a writer with no resolved type both refuse the feed, so
    "select this tab to stream" was an invitation to re-read the refusal.
    """
    reader = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("r1", "Reader")))["data"]
    self.assertIn("Press p to probe", reader)
    # Asserted within one line: report prose is wrapped to the report width.
    self.assertIn("live feed is not available here", reader)
    self.assertNotIn("select this tab to stream", reader)

    typeless = FakeEndpoint("w1", "Writer")
    typeless.type = None
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=typeless))["data"]
    self.assertIn("No type information reached discovery", text)
    self.assertNotIn("select this tab to stream", text)

  def test_a_writer_that_can_stream_is_still_offered_it(self):
    streamable = FakeEndpoint("w1", "Writer")
    streamable.type = object()
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=streamable))["data"]
    self.assertIn("select this tab to stream", text)

  def test_the_payload_section_says_it_is_not_saved(self):
    """`s` writes every other tab. Dropping this one silently would let an
    operator believe the payload they just read is in the file."""
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.sample_texts = ['{"id":1}']
    result.samples_taken = 1
    data = report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer"), probe_result=result)
    self.assertIn("not written to the saved report",
                  report.render_view_sections(data)["data"])
    # And the saved report genuinely does not carry it, which is what that
    # sentence is promising.
    self.assertNotIn("SAMPLE DATA", report.render_text(data))

  def test_a_pass_started_from_the_data_tab_says_what_it_is_waiting_for(self):
    """`_stop_live` leaves "select this tab again to reopen", which is wrong for
    the length of a pass that hands the feed back by itself - and selecting the
    tab during one only earns a refusal."""
    session = CaptureStubSession("lo")          # answered: no picker is pushed
    session.participant = object()
    endpoint = FakeEndpoint("w1", "Writer")
    endpoint.type = object()
    screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    collected = {}

    async def run():
      app = Harness(screen)
      with mock.patch.object(livedata, "LiveSubscription", StubLive):
        async with app.run_test() as pilot:
          await pilot.pause()
          await app.workers.wait_for_complete()
          screen.query_one("#report_tabs",
                           report_screen.TabbedContent).active = "data"
          await pilot.pause()
          screen.live.batches = [live_samples(1)]
          screen._pump_live()
          await pilot.pause()
          # `p` from the Data tab, with the capture question already answered.
          screen.action_probe()
          collected["during"] = str(screen.bodies["data"].render())
          await app.workers.wait_for_complete()
          await pilot.pause()
          collected["after"] = str(screen.bodies["data"].render())

    asyncio.run(run())
    self.assertIn("diagnostic pass is running", collected["during"])
    self.assertNotIn("Select this tab again", collected["during"])
    # And the pass's finally hands it back, as that note promised.
    self.assertIn("STREAMING", collected["after"])


class TestTheEighthReviewRound(unittest.TestCase):
  """Regressions for the eighth pass."""

  def test_a_refused_probe_does_not_unlock_publishing(self):
    """`p` that starts nothing must not make the report claim it probes.

    `w` is gated on this report probing, and setting that flag before finding
    out whether the pass would run was enough to reach the publish consent from
    a report with no probe behind it.
    """
    session = CaptureStubSession("lo")
    session.claim_pass(60.0)                      # another report is mid-pass
    endpoint = FakeEndpoint("r1", "Reader")
    screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    screen.status = mock.Mock()
    self.assertFalse(screen.check_action("verify_delivery", None))

    screen.action_probe()
    self.assertFalse(screen.probe, "a refused probe still set the probe flag")
    self.assertFalse(screen.check_action("verify_delivery", None),
                     "a refused probe unlocked the publish key")
    # And the refusal is what it said, rather than silence.
    self.assertIn("another report", screen.status.update.call_args[0][0])

  def test_a_probe_that_runs_does_unlock_publishing(self):
    """The other direction: the flag has to arrive when a pass really starts."""
    session = CaptureStubSession("lo")            # answered, so no picker
    endpoint = FakeEndpoint("r1", "Reader")
    screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    unlocked = {}

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        screen.action_probe()
        unlocked["probe"] = screen.probe
        unlocked["w"] = screen.check_action("verify_delivery", None)
        await app.workers.wait_for_complete()
        await pilot.pause()

    asyncio.run(run())
    self.assertTrue(unlocked["probe"])
    self.assertTrue(unlocked["w"])

  def test_the_request_survives_a_refusal_so_p_can_be_pressed_again(self):
    session = CaptureStubSession("lo")
    session.claim_pass(60.0)
    screen = report_screen.ReportScreen(
        session, endpoint=FakeEndpoint("w1", "Writer"), probe=False)
    screen.status = mock.Mock()
    screen.action_probe()
    self.assertTrue(screen.probe_requested,
                    "the request was dropped, so `p` would go back to the "
                    "passive status line")
    self.assertFalse(screen.probe)

  def test_a_large_payload_is_not_serialized_twenty_times(self):
    """Each text costs a full to_json() before it is truncated, so a window of
    them on a large-data topic is paid inside the probe's timed window."""
    result = probe.ProbeResult()
    self.assertFalse(result.sample_texts_capped)

    renders = []
    big = "x" * (probe.DATA_SAMPLE_LIMIT * 4)

    class BigSample:
      def to_json(self):
        renders.append(1)
        return big

    # The product's own rule, not a copy of it: reimplementing the loop here
    # would pass with the cap removed.
    for _ in range(probe.DATA_SAMPLE_COUNT):
      probe.collect_sample_text(result, BigSample())
    self.assertEqual(len(renders), 1, "a large payload was serialized repeatedly")
    self.assertTrue(result.sample_texts_capped)

  def test_a_small_payload_still_fills_the_window(self):
    result = probe.ProbeResult()
    renders = []

    class SmallSample:
      def to_json(self):
        renders.append(1)
        return '{"id":1}'

    for _ in range(probe.DATA_SAMPLE_COUNT + 5):
      probe.collect_sample_text(result, SmallSample())
    self.assertEqual(len(result.sample_texts), probe.DATA_SAMPLE_COUNT)
    self.assertFalse(result.sample_texts_capped)

  def test_the_report_says_why_only_one_sample_is_shown(self):
    """"One sample" and "one sample because the rest were too expensive to
    render" are different statements about the writer."""
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.sample_texts = ["x" * probe.DATA_SAMPLE_LIMIT]
    result.samples_taken = 40
    result.sample_texts_capped = True
    text = report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer"), probe_result=result))["data"]
    self.assertIn("Only the sample(s) below were rendered", text)
    self.assertIn("1 of 40", text)

  def test_an_unstated_vendor_is_not_reported_as_an_unreadable_one(self):
    """`is_foreign` refuses both, and its docstring insists they differ: one is
    "we could not tell", the other is the peer saying "no vendor"."""
    session = CaptureStubSession("lo")

    stated = FakeEndpoint("w1", "Writer")
    stated.vendor_id = vendor_id(0x00, first=0x00)
    screen = report_screen.ReportScreen(session, endpoint=stated, probe=False)
    screen.status = mock.Mock()
    screen.action_compatibility_matrix()
    said = screen.status.update.call_args[0][0]
    self.assertIn("VENDORID_UNKNOWN", said)
    self.assertNotIn("could not be read", said)

    unreadable = FakeEndpoint("w2", "Writer")
    unreadable.vendor_id = None
    screen = report_screen.ReportScreen(session, endpoint=unreadable, probe=False)
    screen.status = mock.Mock()
    screen.action_compatibility_matrix()
    said = screen.status.update.call_args[0][0]
    self.assertIn("could not be read", said)
    self.assertNotIn("VENDORID_UNKNOWN", said)


class TestIssueEndpointsAreMarked(unittest.TestCase):
  """Endpoints a system issue names are orange in the endpoint lists.

  These lists are where a system is skimmed, and they used to say nothing about
  which rows the Issues screen was complaining about - so the walk from "1
  ERROR on this domain" to the endpoint behind it went through two screens and
  a by-eye comparison of 4-word instance handles.
  """

  def marks(self, issues):
    return issue_marks.severity_by_endpoint(
        system_scan.SystemScanSnapshot(captured_at=1.0, topology=TOPOLOGY,
                                       issues=tuple(issues)))

  def test_both_sides_of_a_pair_are_marked(self):
    """An RxO mismatch is a property of the pair, not of the writer.

    Marking only the writer would state that the reader is fine, and the reader
    is exactly where the requested QoS that cannot be satisfied lives.
    """
    marks = self.marks([issue_with(writer_keys=("w1",), reader_keys=("r1",))])
    self.assertEqual(set(marks), {"w1", "r1"})
    self.assertEqual(marks["w1"], findings.Severity.ERROR)
    self.assertEqual(marks["r1"], findings.Severity.ERROR)

  def test_notes_are_not_marked(self):
    """Measured, not assumed: a healthy single-writer domain always reports
    `qos.no_counterpart` as an INFO note against its writer, so marking notes
    would paint a healthy system orange and make the colour mean nothing."""
    note = system_scan.SystemIssue(
        key="issue", severity=findings.Severity.INFO,
        finding_ids=("qos.no_counterpart",), title="No counterpart",
        observed="", root_cause="", recommendation="", topic_name="Telemetry",
        scope="pair", writer_keys=("w1",), reader_keys=(), participant_keys=(),
        evidence={})
    self.assertEqual(self.marks([note]), {})

  def test_the_worst_severity_wins_for_an_endpoint_in_several_issues(self):
    warning = system_scan.SystemIssue(
        key="warn", severity=findings.Severity.WARN,
        finding_ids=("type.assignability",), title="Assignability",
        observed="", root_cause="", recommendation="", topic_name="Telemetry",
        scope="pair", writer_keys=("w1",), reader_keys=(), participant_keys=(),
        evidence={})
    marks = self.marks([warning, issue_with(writer_keys=("w1",))])
    self.assertEqual(marks["w1"], findings.Severity.ERROR)

  def test_cells_are_orange_only_when_the_row_is_marked(self):
    marked = issue_marks.cells(("Telemetry", "Writer"), findings.Severity.ERROR)
    plain = issue_marks.cells(("Telemetry", "Writer"), None)
    self.assertEqual([str(cell) for cell in marked], ["Telemetry", "Writer"])
    self.assertEqual({str(cell.style) for cell in marked}, {issue_marks.STYLE})
    self.assertEqual({str(cell.style) for cell in plain}, {""})

  def test_the_legend_counts_what_it_marked(self):
    text = issue_marks.legend([findings.Severity.ERROR, None,
                               findings.Severity.WARN])
    self.assertIn(issue_marks.STYLE, text)
    self.assertIn("1 in an ERROR", text)
    self.assertIn("1 in a WARNING", text)
    self.assertIn("2 of 3", text)

  def test_the_legend_says_so_when_nothing_here_is_named(self):
    """An operator who knows the domain has errors and sees no orange needs to
    read "not these endpoints", not wonder whether the marking ran."""
    text = issue_marks.legend([None, None])
    # Past tense and scoped: the marks come from a snapshot, the rows from the
    # live registry, so the claim is about when the scan ran.
    self.assertIn("No system finding named any of these 2", text)
    self.assertIn("as of the last system scan", text)

  def test_the_legend_dates_its_claim_to_the_scan(self):
    """The rows are live and the marks are a snapshot, so an endpoint that
    joined since the scan is listed unmarked - under a legend that must not
    read as a present-tense "no issues here"."""
    stamp = time.mktime((2026, 8, 24, 14, 30, 5, 0, 0, -1))
    quiet = issue_marks.legend([None, None], stamp)
    self.assertIn("14:30:05", quiet)
    marked = issue_marks.legend([findings.Severity.ERROR, None], stamp)
    self.assertIn("14:30:05", marked)

  def test_a_failed_scan_costs_the_colour_and_not_the_list(self):
    session = StubSession()
    session.system_scan = mock.Mock(side_effect=RuntimeError("scan exploded"))
    self.assertEqual(asyncio.run(issue_marks.marks_for(session)), {})

  def test_a_supplied_snapshot_is_used_without_scanning_again(self):
    """The topology screen these lists are reached from already scanned."""
    session = StubSession()
    session.system_scan = mock.Mock()
    marks = asyncio.run(issue_marks.marks_for(
        session, system_scan.SystemScanSnapshot(
            captured_at=1.0, topology=TOPOLOGY,
            issues=(issue_with(writer_keys=("w1",)),))))
    self.assertEqual(set(marks), {"w1"})
    session.system_scan.assert_not_called()

  def test_the_fallback_scan_does_not_block_the_event_loop(self):
    """A scan is O(endpoints^2); every other one in the TUI runs in a thread.

    Asserted by identity: the scan must not run on the loop's own thread.
    """
    session = StubSession()
    threads = []

    def scan(captured_at=None, max_age=0.0):
      threads.append(threading.current_thread())
      return snapshot()

    session.system_scan = scan

    async def run():
      loop_thread = threading.current_thread()
      await issue_marks.marks_for(session)
      return loop_thread

    loop_thread = asyncio.run(run())
    self.assertEqual(len(threads), 1)
    self.assertIsNot(threads[0], loop_thread,
                     "the scan ran on the event loop thread")

  def _rows(self, screen):
    """Rendered cell text and style for each row, in table order."""
    rows = []
    for row_key in screen.table.rows:
      cells = screen.table.get_row(row_key)
      rows.append([(str(cell), str(getattr(cell, "style", ""))) for cell in cells])
    return rows

  def _drive(self, screen):
    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    asyncio.run(run())
    return screen

  class ListRegistry(StubRegistry):
    """`StubRegistry` answers every lookup with an empty list, which renders an
    empty table; these screens are only interesting with rows in them."""

    def __init__(self, endpoints):
      self.endpoints = dict(endpoints)

    def expire_type_waits(self):
      pass

    def endpoints_for(self, participant_key):
      return list(self.endpoints.values())

    def endpoints_on_topic(self, topic_name):
      return [endpoint for endpoint in self.endpoints.values()
              if endpoint.topic_name == topic_name]

    def participant_for(self, endpoint):
      return None

  def _session_with(self, endpoints, issues):
    session = StubSession()
    session.registry = self.ListRegistry(endpoints)
    session.system_scan = lambda captured_at=None, max_age=0.0: (
        system_scan.SystemScanSnapshot(captured_at=1.0, topology=TOPOLOGY,
                                       issues=tuple(issues)))
    return session

  def test_the_participant_endpoint_list_paints_the_named_rows(self):
    endpoints = {"w1": FakeEndpoint("w1", "Writer", topic_name="Telemetry"),
                 "r1": FakeEndpoint("r1", "Reader", topic_name="Telemetry"),
                 "w2": FakeEndpoint("w2", "Writer", topic_name="Quiet")}
    session = self._session_with(
        endpoints, [issue_with(writer_keys=("w1",), reader_keys=("r1",))])
    participant = records.ParticipantRecord(key="p1", name="app")
    screen = self._drive(browse.EndpointListScreen(session, participant))
    styles = {row[0][0]: row[0][1] for row in self._rows(screen)}
    self.assertEqual(styles.get("Quiet"), "")
    self.assertEqual(set(styles) - {"Quiet"}, {"Telemetry"})
    marked = [row for row in self._rows(screen)
              if row[0][0] == "Telemetry"]
    self.assertTrue(marked)
    for row in marked:
      self.assertEqual({style for _, style in row}, {issue_marks.STYLE})
    self.assertIn("2 of 3", str(screen.legend.render()))

  def test_the_topic_endpoint_list_paints_the_named_rows(self):
    endpoints = {"w1": FakeEndpoint("w1", "Writer", topic_name="Telemetry"),
                 "r1": FakeEndpoint("r1", "Reader", topic_name="Telemetry")}
    session = self._session_with(endpoints, [issue_with(writer_keys=("w1",))])
    screen = self._drive(
        system_overview.TopicEndpointsScreen(session, "Telemetry"))
    styles = {row[0][0]: row[0][1] for row in self._rows(screen)}
    self.assertEqual(styles.get("Writer"), issue_marks.STYLE)
    self.assertEqual(styles.get("Reader"), "")
    self.assertIn("1 of 2", str(screen.legend.render()))


class TestAPassiveReportCanBeProbedOnDemand(unittest.TestCase):
  """`p` on a report that was opened without probing.

  Passive entry is deliberate and stays the default - arriving on a screen must
  not create DDS entities. But the operator who followed an issue to the writer
  it names had no way to probe that writer at all: the issue path only ever
  pushes a passive report, so the answer to "does anything actually flow here?"
  meant leaving the issue and finding the same endpoint again by hand in Browse.
  """

  def drive(self, session, endpoint, steps, probe=False, participant=None):
    collected = {}

    async def run():
      screen = report_screen.ReportScreen(
          session, endpoint=endpoint, participant=participant, probe=probe)
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await steps(pilot, screen, collected)

    asyncio.run(run())
    return collected

  async def press_probe(self, pilot, screen, out):
    await pilot.press("p")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    out["said"] = status_text(screen)
    out["screen"] = pilot.app.screen

  def test_the_passive_status_line_says_the_probe_is_available(self):
    """The footer is one place to learn it; the line that says "nothing ran" is
    the place the operator is already reading."""
    async def steps(pilot, screen, out):
      out["said"] = status_text(screen)

    result = self.drive(CaptureStubSession("lo"),
                        FakeEndpoint("w1", "Writer"), steps)
    self.assertIn("Press p", result["said"])
    self.assertIn("matching reader", result["said"])

  def test_a_reader_target_is_told_a_writer_is_what_gets_created(self):
    """Probing a reader means creating a WRITER, which is a different act."""
    async def steps(pilot, screen, out):
      out["said"] = status_text(screen)

    result = self.drive(CaptureStubSession("lo"),
                        FakeEndpoint("r1", "Reader"), steps)
    self.assertIn("matching writer", result["said"])

  @unittest.skip("interface capture was removed")
  def test_pressing_p_runs_the_probe_with_the_remembered_capture_answer(self):
    session = CaptureStubSession("lo")
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self.press_probe)
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual(len(probing), 1)
    self.assertEqual(probing[0]["endpoint"], "w1")
    self.assertEqual(probing[0]["capture_interface"], "lo")
    # And it publishes nothing: `p` is the read-only pass, `w` is the other one.
    self.assertFalse(probing[0]["write_samples"])
    self.assertIn("Full diagnostic complete", result["said"])

  @unittest.skip("interface capture was removed")
  def test_pressing_p_with_no_capture_answer_yet_asks_before_probing(self):
    """Same ordering as the probing entry path: tshark must precede the probe."""
    session = CaptureStubSession()

    async def steps(pilot, screen, out):
      await pilot.press("p")
      await pilot.pause()
      out["screen"] = pilot.app.screen
      out["probes"] = [call for call in session.calls if call["probe"]]

    result = self.drive(session, FakeEndpoint("w1", "Writer"), steps)
    self.assertIsInstance(result["screen"], report_screen.CaptureInterfaceScreen)
    self.assertEqual(result["probes"], [])

  def test_a_probe_from_a_finding_report_reaches_the_endpoint_named(self):
    """The whole point, end to end: finding -> report -> probe, one endpoint.

    `_open_issue_report` is what the issue list and issue detail both route
    through, so this drives the screen it actually pushes rather than one built
    by hand.
    """
    session = CaptureStubSession()
    session.registry = StubRegistry()
    session.registry.endpoints = {"w1": FakeEndpoint("w1", "Writer")}
    router = mock.Mock()
    system_overview._open_issue_report(
        router, session, issue_with(writer_keys=("w1",)))
    pushed = router.app.push_screen.call_args[0][0]
    self.assertIsInstance(pushed, report_screen.ReportScreen)
    self.assertTrue(pushed.probe, "the finding path uses the probe default")

    collected = {}

    async def run():
      app = Harness(pushed)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        collected["said"] = status_text(pushed)

    asyncio.run(run())
    probing = [call for call in session.calls if call["probe"]]
    self.assertEqual([call["endpoint"] for call in probing], ["w1"])
    self.assertIn("Probe complete", collected["said"])

  def test_the_key_is_not_offered_on_a_participant_report(self):
    """A participant report has no endpoint to probe, so the footer must not
    advertise a key that can only answer with a refusal."""
    screen = report_screen.ReportScreen(
        CaptureStubSession("lo"),
        participant=records.ParticipantRecord(key="p1", name="app"))
    self.assertFalse(screen.check_action("probe", None))
    self.assertTrue(report_screen.ReportScreen(
        CaptureStubSession("lo"),
        endpoint=FakeEndpoint("w1", "Writer")).check_action("probe", None))

  def test_a_pass_running_elsewhere_is_refused_rather_than_doubled(self):
    session = CaptureStubSession("lo")
    session.claim_pass(60.0)
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self.press_probe)
    self.assertIn("another report", result["said"])
    self.assertEqual([call for call in session.calls if call["probe"]], [])

  def test_probing_unlocks_delivery_verification_on_a_reader_target(self):
    """`w` is gated on this report probing, so `p` has to lift that gate too.

    Otherwise a reader reached from an issue could be probed and still refuse
    the one question a reader probe can answer with consent.
    """
    session = CaptureStubSession("lo")
    endpoint = FakeEndpoint("r1", "Reader")
    screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    self.assertFalse(screen.probe)

    async def steps(pilot, target, out):
      await pilot.press("p")
      await pilot.app.workers.wait_for_complete()
      await pilot.pause()
      out["probe"] = target.probe

    collected = {}

    async def run():
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await steps(pilot, screen, collected)

    asyncio.run(run())
    self.assertTrue(collected["probe"])
    self.assertTrue(screen.check_action("verify_delivery", None))


class TestTheDataTabShowsThePayload(unittest.TestCase):
  """The Data tab prints the samples the probe's reader took, and nothing else.

  The tab is the one place in the report that shows the payload rather than
  describing it, so every case where there is no payload has to say which case
  it is. "No probe was run", "no reader could be created", "the reader took
  nothing" and "this target is a reader, so we published instead" are four
  different facts, and a tab that rendered any of them as an empty body would
  read as the writer sending nothing at all.
  """

  def sections(self, result):
    return report.render_view_sections(report.ReportData(
        domain_id=7, scope="topic 'Telemetry'", all_findings=[],
        endpoint=FakeEndpoint("w1", "Writer"), probe_result=result))

  def taken(self, texts, samples_taken=None):
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.sample_texts = list(texts)
    result.samples_taken = (len(texts) if samples_taken is None
                            else samples_taken)
    return result

  def test_every_section_has_a_tab_to_render_it_in(self):
    """`_update_sections` indexes the screen's bodies by section id.

    A section with no TabPane is a KeyError on every report, and a TabPane with
    no section is a permanently empty tab. Neither is reachable from a unit test
    of either half alone, which is why this asserts the two sets are equal.
    """
    session = CaptureStubSession()
    endpoint = FakeEndpoint("w1", "Writer")
    screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=False)
    app = Harness(screen)

    async def run():
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    asyncio.run(run())
    self.assertEqual(set(screen.bodies),
                     set(report.render_view_sections(screen.data)))
    self.assertIn("data", screen.bodies)

  def test_it_prints_each_sample_it_received(self):
    text = self.sections(self.taken(['{"id":1,"label":"one"}',
                                     '{"id":2,"label":"two"}']))["data"]
    self.assertIn("SAMPLE DATA", text)
    self.assertIn("sample 1", text)
    self.assertIn("sample 2", text)
    self.assertIn('"label":"one"', text)
    self.assertIn('"label":"two"', text)

  def test_a_multi_line_sample_keeps_its_lines(self):
    text = self.sections(self.taken(["{\n  id: 1\n}"]))["data"]
    self.assertIn("  id: 1", text)

  def test_a_capped_view_says_how_much_it_is_not_showing(self):
    """The cap is a display limit, not an observation.

    Printing 20 samples with no note reads as "the writer sent 20", which is a
    claim about the system rather than about this tab.
    """
    text = self.sections(self.taken(["{}"] * 20, samples_taken=413))["data"]
    self.assertIn("20 of 413", text)

  def test_an_uncapped_view_does_not_pretend_to_be_capped(self):
    text = self.sections(self.taken(["{}", "{}"]))["data"]
    self.assertNotIn(" of ", text.split("oldest first")[0].splitlines()[-1])
    self.assertIn("samples shown", text)

  def test_a_created_reader_that_took_nothing_says_so(self):
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.elapsed = 6.0
    text = self.sections(result)["data"]
    self.assertIn("no valid sample", text)
    self.assertNotIn("sample 1", text)

  def test_a_reader_that_was_never_created_names_the_reason(self):
    result = probe.ProbeResult()
    result.attempted = True
    result.create_error = "no type information available, cannot create a reader"
    text = self.sections(result)["data"]
    self.assertIn("no type information available", text)

  def test_a_reader_target_says_it_published_rather_than_received(self):
    """A writer-probe has no incoming payload, and must not imply one."""
    result = probe.ProbeResult()
    result.attempted = result.created = True
    result.probe_kind = "writer"
    result.samples_written = 3
    text = self.sections(result)["data"]
    self.assertIn("created a WRITER", text)
    self.assertIn("3", text)
    self.assertNotIn("sample 1", text)

  def test_a_report_opened_without_a_probe_claims_nothing(self):
    text = self.sections(None)["data"]
    self.assertIn("No probe was run", text)


class TestPublishingNeedsApproval(unittest.TestCase):
  """rti_doctor writes to the system under test only when told to, per endpoint.

  Everything else this tool does is read-only, so the consent path is the one
  place a defaulted answer would be a real fault rather than an inconvenience.
  """

  def drive(self, session, endpoint, steps, probe=True):
    collected = {}

    async def run():
      screen = report_screen.ReportScreen(session, endpoint=endpoint, probe=probe)
      app = Harness(screen)
      async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await steps(pilot, screen, collected)

    asyncio.run(run())
    return collected

  async def _press_w(self, pilot, screen, out):
    await pilot.press("w")
    await pilot.pause()
    out["screen"] = pilot.app.screen
    out["said"] = status_text(screen)

  async def _answer(self, pilot, screen, out, label_contains):
    await pilot.press("w")
    await pilot.pause()
    consent = pilot.app.screen
    row = [index for index, choice in enumerate(consent.choices)
           if label_contains in choice[0]]
    consent.table.move_cursor(row=row[0])
    await pilot.press("enter")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    out["said"] = status_text(screen)

  def test_w_on_a_reader_asks_before_publishing_anything(self):
    session = CaptureStubSession(capture_interface="lo")
    result = self.drive(session, FakeEndpoint("r1", "Reader"), self._press_w)
    self.assertIsInstance(result["screen"], report_screen.PublishConsentScreen)
    self.assertTrue(all(not call["write_samples"] for call in session.calls),
                    "nothing may be published while the question is open")

  def test_declining_publishes_nothing(self):
    session = CaptureStubSession(capture_interface="lo")
    result = self.drive(
        session, FakeEndpoint("r1", "Reader"),
        lambda p, s, o: self._answer(p, s, o, "Do not publish"))
    self.assertTrue(all(not call["write_samples"] for call in session.calls))
    self.assertIn("Declined", result["said"])

  def test_escape_is_a_refusal_not_an_open_question(self):
    """An operator who backed out of a prompt about their production system
    did not consent to writing to it."""
    session = CaptureStubSession(capture_interface="lo")

    async def steps(pilot, screen, out):
      await pilot.press("w")
      await pilot.pause()
      await pilot.press("escape")
      await pilot.app.workers.wait_for_complete()
      await pilot.pause()
      out["said"] = status_text(screen)

    result = self.drive(session, FakeEndpoint("r1", "Reader"), steps)
    self.assertTrue(all(not call["write_samples"] for call in session.calls))
    self.assertIn("Declined", result["said"])

  def test_approving_publishes_and_says_so_first(self):
    session = CaptureStubSession(capture_interface="lo")
    self.drive(session, FakeEndpoint("r1", "Reader"),
               lambda p, s, o: self._answer(p, s, o, "Publish"))
    self.assertTrue(any(call["write_samples"] for call in session.calls),
                    "the approved pass must actually publish")

  def test_a_writer_target_is_never_offered_publishing(self):
    """It is already publishing; injecting data would answer nothing."""
    session = CaptureStubSession(capture_interface="lo")
    result = self.drive(session, FakeEndpoint("w1", "Writer"), self._press_w)
    self.assertNotIsInstance(result["screen"],
                             report_screen.PublishConsentScreen)
    self.assertNotIn("Publish", result["said"])

  def test_a_passive_report_has_no_writer_to_publish_from(self):
    session = CaptureStubSession(capture_interface="lo")
    result = self.drive(session, FakeEndpoint("r1", "Reader"), self._press_w,
                        probe=False)
    self.assertNotIsInstance(result["screen"],
                             report_screen.PublishConsentScreen)
    self.assertIn("without probing", result["said"])


if __name__ == "__main__":
  unittest.main()
