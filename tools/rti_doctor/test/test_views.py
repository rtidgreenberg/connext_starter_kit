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
import unittest
from unittest import mock

from textual.app import App

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import findings, system_scan  # noqa: E402
from rti_doctor.views import system_overview  # noqa: E402

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


class FakeEndpoint:
  def __init__(self, key, kind, topic_name="Telemetry", type_name="TelemetryType"):
    self.key = key
    self.kind = kind
    self.topic_name = topic_name
    self.type_name = type_name

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


if __name__ == "__main__":
  unittest.main()
