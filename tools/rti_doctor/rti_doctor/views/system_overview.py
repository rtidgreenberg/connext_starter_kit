"""System overview, passive issue list, and observed-topology metrics screens."""

import asyncio
import logging
import os
import time

from rich.markup import escape
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .. import findings as f, report
from .browse import EndpointListScreen
from .report_screen import ReportScreen

#: Seconds a snapshot may be reused when a screen is merely being opened. A
#: scan is expensive and five screens each ask for one, so navigating between
#: them otherwise pays for a full re-scan per screen. An explicit `r` refresh
#: always re-scans.
SCAN_REUSE_SECONDS = 3.0


def _issue_counts(snapshot):
  return {severity: sum(issue.severity == severity for issue in snapshot.issues)
          for severity in (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO)}


def _spawn(screen, coroutine):
  """Run `coroutine` as a worker owned by `screen`.

  Textual's run_worker, not asyncio.create_task: the event loop holds only a
  weak reference to a bare task, so it can be collected mid-flight, and nothing
  cancels it when the screen is popped - leaving a scan that finishes seconds
  later writing into unmounted widgets.

  `exit_on_error=False` keeps one failed refresh from tearing down the app, but
  on its own it also makes the failure invisible: the worker dies, the screen
  keeps its previous render, and the operator is looking at stale data with no
  marker. `_report` is the backstop for anything the refresh raises that `_scan`
  did not already handle.
  """
  screen.run_worker(_guarded(screen, coroutine), exit_on_error=False)


async def _guarded(screen, coroutine):
  try:
    await coroutine
  except Exception as error:  # noqa: BLE001 - reported on screen, not swallowed
    _report(screen, error, previous=getattr(screen, "snapshot", None))


def _report(screen, error, previous=None, action="Scan"):
  """Put a refresh failure on the screen's status line and in the log.

  A failed scan must never render like a scan that found nothing to change.
  These screens hold their snapshot across refreshes, so without this a scan
  that has been failing for minutes is indistinguishable from a healthy system
  - which is the one thing a diagnostic tool must not do.
  """
  logging.error(f"[{type(screen).__name__}] {action.lower()} failed: {error}")
  screen.scan_error = error
  detail = escape(str(error)) or type(error).__name__
  if previous is None:
    screen.status.update(f"[red]{action} failed: {detail}[/red] - no data has "
                         "been collected yet. Press r to retry.")
    return
  stamp = time.strftime("%H:%M:%S", time.localtime(previous.captured_at))
  screen.status.update(f"[red]{action} failed: {detail}[/red] - still showing "
                       f"the snapshot from {stamp}. Press r to retry.")


async def _scan(screen, max_age=0.0, previous=None):
  """Scan for `screen`, or report why it could not, returning None.

  Callers keep `previous` and skip their render on None, so the last good data
  stays on screen underneath the failure line rather than being blanked.
  """
  try:
    snapshot = await asyncio.to_thread(screen.session.system_scan, None, max_age)
  except Exception as error:  # noqa: BLE001 - reported on screen, not swallowed
    _report(screen, error, previous)
    return None
  if screen.scan_error is not None:
    # Recovered. Clear the marker; the caller's render writes the status line
    # it would have written had the failure never happened.
    screen.scan_error = None
    screen.status.update("")
  return snapshot


class SystemOverviewScreen(Screen):
  """The initial routing screen for issue-first and topology-first workflows."""

  BINDINGS = [("r", "refresh", "Refresh"), ("m", "metrics", "Metrics"),
              ("s", "save", "Save report"), ("q", "quit_app", "Quit")]

  def __init__(self, session):
    super().__init__()
    self.session = session
    self.menu = DataTable()
    self.summary = None
    self.status = None
    self.snapshot = None
    self.scan_error = None

  def compose(self):
    yield Header()
    with Container(id="system_overview"):
      yield Static("[bold cyan]DDS System Overview[/bold cyan]")
      self.summary = Static("Collecting observed topology...", id="system_summary")
      yield self.summary
      yield Static("Use Up/Down and Enter to choose a view.")
      yield self.menu
      self.status = Static("", id="system_status")
      yield self.status
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - domain {self.session.domain_id}"
    self.menu.add_columns("View", "Description")
    self.menu.add_row("Issues", "Triage errors, warnings, and notes.", key="issues")
    self.menu.add_row("DDS Topology & Health",
                      "Browse participants and their discovered endpoints.", key="topology")
    self.menu.cursor_type = "row"
    self.menu.focus()
    await self.refresh_summary()

  async def on_screen_resume(self):
    """Discovery keeps arriving while the operator is in a child screen.

    Without this the landing screen shows the counts it computed at startup for
    the rest of the session - on a domain that is still settling, which is the
    common case, that is the first thing the operator sees and the most likely
    thing to be wrong.

    Textual posts ScreenResume on the initial push too, right after on_mount, so
    this reuses a very recent scan rather than paying for a duplicate at startup.
    """
    if self.snapshot is not None:
      await self.refresh_summary(max_age=SCAN_REUSE_SECONDS)

  async def refresh_summary(self, max_age=0.0):
    snapshot = await _scan(self, max_age, self.snapshot)
    if snapshot is None:
      return
    counts = _issue_counts(snapshot)
    metrics = snapshot.topology
    if not metrics["participants"]:
      # Never show "0 Errors" over an empty domain: that reads as a healthy
      # system, and nothing was observed at all.
      self.summary.update(
          f"[yellow]No DDS discovered on domain {self.session.domain_id}.[/yellow]\n"
          "Nothing was observed, so there is nothing to report - this is not a "
          "clean bill of health.")
    else:
      self.summary.update(
          f"Observed: {metrics['participants']} participants | {metrics['readers']} readers | "
          f"{metrics['writers']} writers | {metrics['topic_count']} topics\n"
          f"Issues: {counts[f.Severity.ERROR]} Errors | {counts[f.Severity.WARN]} Warnings | "
          f"{counts[f.Severity.INFO]} Notes")
    self.snapshot = snapshot

  async def on_data_table_row_selected(self, event):
    if event.row_key is None or self.snapshot is None:
      return
    if event.row_key.value == "issues":
      self.app.push_screen(IssueSeverityScreen(self.session, self.snapshot))
    elif event.row_key.value == "topology":
      self.app.push_screen(TopologyHealthScreen(self.session))

  def action_refresh(self):
    _spawn(self, self.refresh_summary())

  def action_metrics(self):
    self.app.push_screen(MetricsScreen(self.session))

  def action_save(self):
    snapshot = self.snapshot
    if snapshot is None:
      return
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(snapshot, self.session.domain_id))
    self.status.update(f"Saved system report to {path}")

  def action_quit_app(self):
    self.app.exit()


class IssueSeverityScreen(Screen):
  """Choose which severity of a passive issue snapshot to inspect."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("r", "refresh", "Refresh"), ("q", "quit_app", "Quit")]

  def __init__(self, session, snapshot=None):
    super().__init__()
    self.session = session
    self.snapshot = snapshot
    self.table = DataTable()
    self.status = None
    self.scan_error = None

  def compose(self):
    yield Header()
    yield Static("Use Up/Down and Enter to select the issues to display.")
    with Container(id="issue_severity_menu"):
      yield self.table
    self.status = Static("Collecting issue counts...", id="issue_severity_status")
    yield self.status
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - issue severity domain {self.session.domain_id}"
    self.table.add_columns("Severity", "Count", "Description")
    self.table.cursor_type = "row"
    if self.snapshot is None:
      await self._refresh(max_age=SCAN_REUSE_SECONDS)
    else:
      self._render_menu()
    self.table.focus()

  async def on_screen_resume(self):
    """The child list can refresh; without this the counts here disagree with it."""
    if self.snapshot is not None and self.is_mounted:
      await self._refresh(max_age=SCAN_REUSE_SECONDS)

  async def _refresh(self, max_age=0.0):
    snapshot = await _scan(self, max_age, self.snapshot)
    if snapshot is None:
      return
    self.snapshot = snapshot
    self._render_menu()

  def _render_menu(self):
    self.table.clear()
    counts = _issue_counts(self.snapshot)
    choices = (("error", f.Severity.ERROR, "Errors", "Requires attention"),
               ("warning", f.Severity.WARN, "Warnings", "Potential interoperability risk"),
               ("info", f.Severity.INFO, "Info", "Advisory observations"))
    for key, severity, label, description in choices:
      self.table.add_row(label, str(counts[severity]), description, key=key)
    self.status.update("Select a severity to show only issues at that level.")

  async def on_data_table_row_selected(self, event):
    if event.row_key is None:
      return
    severity = {
        "error": f.Severity.ERROR,
        "warning": f.Severity.WARN,
        "info": f.Severity.INFO,
    }.get(event.row_key.value)
    if severity is not None:
      self.app.push_screen(IssueListScreen(
          self.session, snapshot=self.snapshot, severity=severity))

  def action_refresh(self):
    _spawn(self, self._refresh())

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class IssueListScreen(Screen):
  """A stable passive issue snapshot, refreshed only by the operator."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("r", "refresh", "Refresh"), ("m", "metrics", "Metrics"),
              ("s", "save", "Save report"), ("o", "open_report", "Open report"),
              ("q", "quit_app", "Quit")]

  def __init__(self, session, snapshot=None, issue_keys=None, severity=None):
    super().__init__()
    self.session = session
    self.table = DataTable()
    self.status = None
    self.snapshot = snapshot
    self.issue_keys = set(issue_keys) if issue_keys is not None else None
    self.severity = severity
    self.selected_key = None
    self.scan_error = None

  def compose(self):
    yield Header()
    self.status = Static("Building issue snapshot...", id="issue_status")
    yield self.status
    with Container(id="issue_table"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - issues domain {self.session.domain_id}"
    self.table.add_columns("No.", "Severity", "Topic", "Finding", "State")
    self.table.cursor_type = "row"
    if self.snapshot is None:
      await self._refresh(max_age=SCAN_REUSE_SECONDS)
    else:
      self._render_snapshot()
    self.table.focus()

  async def _refresh(self, max_age=0.0):
    previous = self.selected_key
    snapshot = await _scan(self, max_age, self.snapshot)
    if snapshot is None:
      return
    self.snapshot = snapshot
    self._render_snapshot(previous)

  def _visible_issues(self):
    if self.snapshot is None:
      return ()
    issues = self.snapshot.issues
    if self.issue_keys is not None:
      issues = tuple(item for item in issues if item.key in self.issue_keys)
    if self.severity is not None:
      issues = tuple(item for item in issues if item.severity == self.severity)
    return issues

  def _render_snapshot(self, previous=None):
    self.table.clear()
    issues = self._visible_issues()
    for number, issue in enumerate(issues, 1):
      self.table.add_row(str(number), issue.severity.label, issue.topic_name or "(domain)",
                         ", ".join(issue.finding_ids), "observed", key=issue.key)
    counts = {severity: sum(issue.severity == severity for issue in issues)
              for severity in (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO)}
    stamp = time.strftime("%H:%M:%S", time.localtime(self.snapshot.captured_at))
    scope = self.severity.label.title() if self.severity is not None else "All"
    if not self.snapshot.topology["participants"]:
      # "0 Errors" over an empty domain reads as a healthy system.
      self.status.update(f"Snapshot {stamp}: no DDS discovered on domain "
                         f"{self.session.domain_id}, so there is nothing to "
                         "report. Press r to refresh.")
    else:
      self.status.update(
          f"{scope} issues, snapshot {stamp}: {counts[f.Severity.ERROR]} Errors | "
          f"{counts[f.Severity.WARN]} Warnings | {counts[f.Severity.INFO]} Notes. "
          "Press r to refresh.")
    if previous and previous in {item.key for item in issues}:
      self.table.move_cursor(row=next(index for index, item in enumerate(issues)
                                       if item.key == previous))

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    issue = self._selected_issue()
    if issue is not None:
      self.app.push_screen(IssueDetailScreen(self.session, self.snapshot, issue))

  def action_refresh(self):
    _spawn(self, self._refresh())

  def _selected_issue(self):
    if self.snapshot is None or self.selected_key is None:
      return None
    return next((item for item in self._visible_issues() if item.key == self.selected_key), None)

  def action_metrics(self):
    self.app.push_screen(MetricsScreen(self.session))

  def action_save(self):
    if self.snapshot is None:
      return
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(self.snapshot, self.session.domain_id))
    self.status.update(f"Saved system report to {path}")

  def action_open_report(self):
    issue = self._selected_issue()
    if issue is None or len(issue.writer_keys) != 1:
      self.status.update("Select an issue with one writer to open its report.")
      return
    endpoint = self.session.registry.endpoints.get(issue.writer_keys[0])
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class IssueDetailScreen(Screen):
  """Evidence and relationships for one passive system issue."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("o", "open_report", "Open report"),
              ("s", "save", "Save report"),
              ("q", "quit_app", "Quit")]

  def __init__(self, session, snapshot, issue):
    super().__init__()
    self.session = session
    self.snapshot = snapshot
    self.issue = issue
    self.status = None

  def compose(self):
    yield Header()
    with VerticalScroll(id="issue_detail"):
      lines = [f"[bold]{self.issue.severity.label}: {self.issue.title}[/bold]", "",
               f"Finding: {', '.join(self.issue.finding_ids)}",
               f"Scope: {self.issue.scope}",
               f"Topic: {self.issue.topic_name or '(domain-wide)'}",
               f"Writers: {', '.join(self.issue.writer_keys) or '(none)'}",
               f"Readers: {', '.join(self.issue.reader_keys) or '(none)'}",
               f"Participants: {', '.join(self.issue.participant_keys) or '(none)'}", "",
               "[bold]Observed[/bold]", self.issue.observed or "(none)", "",
               "[bold]Likely cause[/bold]", self.issue.root_cause or "(none)", "",
               "[bold]Recommendation[/bold]", self.issue.recommendation or "(none)"]
      yield Static("\n".join(lines))
    self.status = Static("", id="issue_detail_status")
    yield self.status
    yield Footer()

  def _endpoint(self):
    keys = set(self.issue.writer_keys) | set(self.issue.reader_keys)
    if len(keys) != 1:
      return None
    return self.session.registry.endpoints.get(next(iter(keys)))

  def action_open_report(self):
    endpoint = self._endpoint()
    if endpoint is None:
      self.status.update("Open report requires an issue with exactly one writer.")
      return
    self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_save(self):
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(self.snapshot, self.session.domain_id))
    self.status.update(f"Saved system report to {path}")

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class TopologyHealthScreen(Screen):
  """Entity-first view across participants, readers, writers, and topics."""

  BINDINGS = [("1", "participants", "Participants"), ("2", "readers", "Readers"),
              ("3", "writers", "Writers"), ("4", "topics", "Topics"),
              ("r", "refresh", "Refresh"), ("i", "issues", "Linked issues"),
              ("o", "open_report", "Open report"),
              ("m", "metrics", "Metrics"), ("s", "save", "Save report"),
              ("b", "back", "Back"),
              ("escape", "back", "Back"), ("q", "quit_app", "Quit")]

  def __init__(self, session):
    super().__init__()
    self.session = session
    self.table = DataTable()
    self.status = None
    self.mode = "participants"
    self.snapshot = None
    self.selected_key = None
    self.scan_error = None

  def compose(self):
    yield Header()
    self.status = Static("Collecting topology...", id="topology_status")
    yield self.status
    with Container(id="topology_table"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - topology domain {self.session.domain_id}"
    self.table.cursor_type = "row"
    await self._refresh(max_age=SCAN_REUSE_SECONDS)
    self.table.focus()

  async def _refresh(self, max_age=0.0):
    snapshot = await _scan(self, max_age, self.snapshot)
    if snapshot is None:
      return
    self.snapshot = snapshot
    self._render_table()

  def _render_table(self):
    self.table.clear(columns=True)
    if self.mode == "participants":
      self.table.add_columns("Participant", "Vendor", "Readers", "Writers", "Topics", "Health")
      for participant in sorted(self.session.registry.participant_list(), key=lambda item: item.key):
        endpoints = self.session.registry.endpoints_for(participant.key)
        readers = sum(not item.is_writer for item in endpoints)
        writers = sum(item.is_writer for item in endpoints)
        topics = len({item.topic_name for item in endpoints if item.topic_name})
        self.table.add_row(participant.name or "(unnamed)", participant.vendor_name,
                           str(readers), str(writers), str(topics),
                           self._health(participant_key=participant.key), key=participant.key)
    elif self.mode in ("readers", "writers"):
      writer = self.mode == "writers"
      self.table.add_columns("Topic", "Participant", "Vendor", "Type", "Health")
      endpoints = self.session.registry.writers() if writer else self.session.registry.readers()
      for endpoint in sorted(endpoints, key=lambda item: (item.topic_name, item.key)):
        participant = self.session.registry.participant_for(endpoint)
        self.table.add_row(endpoint.topic_name or "(unnamed)",
                           participant.name if participant and participant.name else "(unnamed)",
                           endpoint.vendor_name, endpoint.type_name or "(none)",
                           self._health(endpoint_key=endpoint.key), key=endpoint.key)
    else:
      self.table.add_columns("Topic", "Readers", "Writers", "Health")
      for topic in self.session.registry.topic_names():
        endpoints = self.session.registry.endpoints_on_topic(topic)
        self.table.add_row(topic, str(sum(not item.is_writer for item in endpoints)),
                           str(sum(item.is_writer for item in endpoints)),
                           self._health(topic_name=topic), key=f"topic:{topic}")
    self.status.update(f"View: {self.mode.title()} | 1 Participants  2 Readers  "
                       "3 Writers  4 Topics | r refresh")

  def _health(self, participant_key=None, endpoint_key=None, topic_name=None):
    linked = []
    for issue in self.snapshot.issues:
      if participant_key and participant_key in issue.participant_keys:
        linked.append(issue)
      elif endpoint_key and (endpoint_key in issue.writer_keys or endpoint_key in issue.reader_keys):
        linked.append(issue)
      elif topic_name and issue.topic_name == topic_name:
        linked.append(issue)
    if not linked:
      return "OK"
    worst = max(issue.severity for issue in linked)
    return f"{worst.label} ({len(linked)})"

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    self.action_open_report()

  def action_participants(self):
    self.mode = "participants"
    self._render_table()

  def action_readers(self):
    self.mode = "readers"
    self._render_table()

  def action_writers(self):
    self.mode = "writers"
    self._render_table()

  def action_topics(self):
    self.mode = "topics"
    self._render_table()

  def action_refresh(self):
    _spawn(self, self._refresh())

  def action_metrics(self):
    self.app.push_screen(MetricsScreen(self.session))

  def action_issues(self):
    keys = self._linked_issue_keys()
    self.app.push_screen(IssueListScreen(self.session, self.snapshot, keys))

  def _linked_issue_keys(self):
    if self.selected_key is None:
      return {item.key for item in self.snapshot.issues}
    if self.mode == "participants":
      return {item.key for item in self.snapshot.issues
              if self.selected_key in item.participant_keys}
    if self.mode == "topics":
      topic = self.selected_key.removeprefix("topic:")
      return {item.key for item in self.snapshot.issues if item.topic_name == topic}
    return {item.key for item in self.snapshot.issues
            if self.selected_key in item.writer_keys or self.selected_key in item.reader_keys}

  def _selected_endpoint(self):
    if self.selected_key is None:
      return None
    return self.session.registry.endpoints.get(self.selected_key)

  def action_open_report(self):
    if self.mode == "participants" and self.selected_key:
      participant = self.session.registry.participants.get(self.selected_key)
      if participant is not None:
        self.app.push_screen(EndpointListScreen(self.session, participant))
      return
    if self.mode == "topics" and self.selected_key:
      self.app.push_screen(TopicEndpointsScreen(
          self.session, self.selected_key.removeprefix("topic:")))
      return
    endpoint = self._selected_endpoint()
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_debug(self):
    endpoint = self._selected_endpoint()
    if endpoint is None:
      self.status.update("Debug is available only when one endpoint is selected.")
      return
    self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_save(self):
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(self.snapshot, self.session.domain_id))
    self.status.update(f"Saved system report to {path}")

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class TopicEndpointsScreen(Screen):
  """Readers and writers belonging to one selected topic."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("o", "open_report", "Open report"),
              ("q", "quit_app", "Quit")]

  def __init__(self, session, topic_name):
    super().__init__()
    self.session = session
    self.topic_name = topic_name
    self.table = DataTable()
    self.selected_key = None

  def compose(self):
    yield Header()
    with Container(id="topic_endpoints"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - topic {self.topic_name}"
    self.table.add_columns("Kind", "Participant", "Vendor", "Type")
    self.table.cursor_type = "row"
    for endpoint in sorted(self.session.registry.endpoints_on_topic(self.topic_name),
                           key=lambda item: (item.kind, item.key)):
      participant = self.session.registry.participant_for(endpoint)
      self.table.add_row(endpoint.kind,
                         participant.name if participant and participant.name else "(unnamed)",
                         endpoint.vendor_name, endpoint.type_name or "(none)",
                         key=endpoint.key)
    self.table.focus()

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    self.action_debug()

  def _endpoint(self):
    return self.session.registry.endpoints.get(self.selected_key) if self.selected_key else None

  def action_open_report(self):
    endpoint = self._endpoint()
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_debug(self):
    endpoint = self._endpoint()
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class MetricsScreen(Screen):
  """Live topology counters, explicitly separate from a saved issue snapshot."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("r", "refresh", "Refresh"), ("q", "quit_app", "Quit")]

  def __init__(self, session):
    super().__init__()
    self.session = session
    self.body = None
    self.status = None
    self.snapshot = None
    self.scan_error = None

  def compose(self):
    yield Header()
    with VerticalScroll(id="metrics_body"):
      self.body = Static("Collecting metrics...")
      yield self.body
    # Counters are the screen's whole content, so a failed refresh here leaves
    # numbers on screen with nothing marking them as old. This is the line that
    # says so.
    self.status = Static("", id="metrics_status")
    yield self.status
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - metrics domain {self.session.domain_id}"
    await self._refresh(max_age=SCAN_REUSE_SECONDS)

  async def _refresh(self, max_age=0.0):
    snapshot = await _scan(self, max_age, self.snapshot)
    if snapshot is None:
      return
    self.snapshot = snapshot
    data = snapshot.topology
    rows = [
        ("Domain ID", str(self.session.domain_id)),
        ("Remote participants", str(data["participants"])),
        ("Remote DataReaders", str(data["readers"])),
        ("Remote DataWriters", str(data["writers"])),
        ("Unique topics", str(data["topic_count"])),
        ("Topic names", ", ".join(data["topics"]) or "(none observed)"),
        ("Source", data["source"]),
        ("Coverage", data["completion_note"]),
    ]
    width = max(len(label) for label, _ in rows) + 2
    self.body.update("\n".join(
        ["[bold]Observed Domain Metrics[/bold]", ""]
        + [f"{label.ljust(width)}{value}" for label, value in rows]))

  def action_refresh(self):
    _spawn(self, self._refresh())

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()