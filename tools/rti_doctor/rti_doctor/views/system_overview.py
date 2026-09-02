"""System overview, passive finding list, and observed-topology metrics screens."""

import asyncio
import logging
import os
import time

from rich.markup import escape
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .. import findings as f, report, system_scan
from . import issue_marks
from .browse import EndpointListScreen
from .report_screen import ReportScreen

#: Re-exported so this module's screens keep reading it by the bare name; the
#: policy itself belongs with the scan, which the endpoint lists share.
SCAN_REUSE_SECONDS = system_scan.SCAN_REUSE_SECONDS


def _issue_counts(snapshot):
  return {severity: sum(issue.severity == severity for issue in snapshot.issues)
          for severity in (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO)}


def _issue_endpoints(session, issue):
  """Every endpoint an issue names, as `(role, label, endpoint)`, writers first.

  RxO is directional - the writer offers, the reader requests the minimum it
  will accept - so both sides of a `qos.rxo_mismatch` are legitimate places to
  start. A topic-scoped condition can name more than two.
  """
  evidence = issue.evidence or {}
  found = []
  for keys, role, label_key in ((issue.writer_keys, "Writer (offers)", "writer"),
                                (issue.reader_keys, "Reader (requests)", "reader")):
    for key in keys:
      endpoint = session.registry.endpoints.get(key)
      if endpoint is None:
        continue  # departed since the snapshot was taken
      label = evidence.get(label_key) if len(keys) == 1 else None
      found.append((role, str(label or endpoint.topic_name or key), endpoint))
  return found


def _issue_endpoint_navigation(session, issue):
  """Detail text naming finding endpoints and the action that opens one."""
  endpoints = _issue_endpoints(session, issue)
  lines = [f"{role}: {label}" for role, label, _ in endpoints]
  if not lines:
    return "[bold]Endpoint pages[/bold]\n(none still in discovery)"
  return ("[bold]Endpoint pages[/bold]\n" + "\n".join(lines)
          + "\nPress [bold]o[/bold] to choose an endpoint page.")


def _issue_technical_ids(issue):
  """Secondary discovery IDs for operators who need to correlate raw evidence."""
  lines = []
  if issue.writer_keys:
    lines.append(f"Writers: {', '.join(issue.writer_keys)}")
  if issue.reader_keys:
    lines.append(f"Readers: {', '.join(issue.reader_keys)}")
  if issue.participant_keys:
    lines.append(f"Participants: {', '.join(issue.participant_keys)}")
  return "[bold]Technical identifiers[/bold]\n" + "\n".join(lines) if lines else ""


def _open_issue_report(screen, session, issue):
  """Open a targeted report for `issue`, asking which endpoint when ambiguous.

  Both the issue list and the issue detail route through here. The detail
  screen used to require exactly one endpoint across both roles, so the
  flagship ERROR - `qos.rxo_mismatch`, which always names a writer AND a
  reader - could never open one; the list screen silently opened the writer,
  which hides the reader-driven constraint the mismatch is usually about.
  """
  if issue is None:
    screen.status.update("Select a finding first.")
    return
  choices = _issue_endpoints(session, issue)
  if not choices:
    screen.status.update(
        "This finding names no endpoint still in discovery, so there is no "
        "targeted report to open.")
    return
  if len(choices) == 1:
    screen.app.push_screen(
        ReportScreen(session, endpoint=choices[0][2], probe=session.probe_default))
    return
  screen.app.push_screen(EndpointChoiceScreen(session, issue, choices))


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
  """The initial routing screen for findings-first and topology-first workflows."""

  BINDINGS = [("r", "refresh", "Refresh"), ("m", "metrics", "Metrics"),
              ("s", "save", "Save system report"), ("q", "quit_app", "Quit")]

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
    self.menu.add_row("Findings", "Review errors, warnings, and observations.", key="findings")
    self.menu.add_row("Topology", "Browse participants and their discovered endpoints.", key="topology")
    self.menu.add_row("Topics", "Browse topic health and endpoint relationships.", key="topics")
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
    if not metrics["participants"] and not snapshot.issues:
      # Never show "0 Errors" over an empty domain: that reads as a healthy
      # system, and nothing was observed at all.
      self.summary.update(
          f"[yellow]No DDS discovered on domain {self.session.domain_id}.[/yellow]\n"
          "Nothing was observed, so there is nothing to report - this is not a "
          "clean bill of health.")
    elif not metrics["participants"]:
      self.summary.update(
          f"[yellow]No DDS discovered on domain {self.session.domain_id}.[/yellow]\n"
          f"Findings: {issue_marks.severity_summary(counts)}")
    else:
      finding_summary = ("[bold green]No active issues found.[/bold green]"
                         if not any(counts.values()) else
                         f"Findings: {issue_marks.severity_summary(counts)}")
      self.summary.update(
          f"Observed: {metrics['participants']} participants | {metrics['readers']} readers | "
          f"{metrics['writers']} writers | {metrics['topic_count']} topics\n"
          f"{finding_summary}")
    self.snapshot = snapshot

  async def on_data_table_row_selected(self, event):
    if event.row_key is None or self.snapshot is None:
      return
    if event.row_key.value == "findings":
      self.app.push_screen(IssueSeverityScreen(self.session, self.snapshot))
    elif event.row_key.value == "topology":
      self.app.push_screen(TopologyHealthScreen(self.session))
    elif event.row_key.value == "topics":
      self.app.push_screen(TopicListScreen(self.session, self.snapshot))

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
      handle.write(report.render_system_text(
          snapshot, self.session.domain_id,
          type_lookup_settings=self.session.type_lookup_settings))
    self.status.update(f"Saved system report to {path}")

  def action_quit_app(self):
    self.app.exit()


class IssueSeverityScreen(Screen):
  """Choose which severity of a passive finding snapshot to inspect."""

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
    yield Static("Use Up/Down and Enter to select the findings to display.")
    with Container(id="issue_severity_menu"):
      yield self.table
    self.status = Static("Collecting finding counts...", id="issue_severity_status")
    yield self.status
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - finding severity domain {self.session.domain_id}"
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
      self.table.add_row(issue_marks.severity_text(label, severity),
                         issue_marks.severity_text(counts[severity], severity),
                         description, key=key)
    self.status.update("Select a severity to show only findings at that level.")

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
  """A stable passive finding snapshot, refreshed only by the operator."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("r", "refresh", "Refresh"),
              ("s", "save", "Save system report"),
              ("o", "open_report", "Open report"),
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
    self.status = Static("Building finding snapshot...", id="issue_status")
    yield self.status
    with Container(id="issue_table"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - findings domain {self.session.domain_id}"
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
      self.table.add_row(str(number),
                         issue_marks.severity_text(issue.severity.label, issue.severity),
                         issue.topic_name or "(domain)", ", ".join(issue.finding_ids),
                         issue_marks.severity_text("OBSERVED", issue.severity), key=issue.key)
    counts = {severity: sum(issue.severity == severity for issue in issues)
              for severity in (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO)}
    stamp = time.strftime("%H:%M:%S", time.localtime(self.snapshot.captured_at))
    scope = self.severity.label.title() if self.severity is not None else "All"
    if not self.snapshot.topology["participants"] and not issues:
      # "0 Errors" over an empty domain reads as a healthy system.
      self.status.update(f"Snapshot {stamp}: no DDS discovered on domain "
                         f"{self.session.domain_id}, so there is nothing to "
                         "report. Press r to refresh.")
    else:
      prefix = (f"No DDS discovered on domain {self.session.domain_id}; "
                if not self.snapshot.topology["participants"] else "")
      finding_summary = ("[bold green]No active issues found.[/bold green]"
                         if not any(counts.values()) else
                         issue_marks.severity_summary(counts))
      self.status.update(
          f"{prefix}{scope} findings, snapshot {stamp}: {finding_summary}. "
          "Press s to save the full system report, or r to refresh.")
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

  def action_save(self):
    if self.snapshot is None:
      return
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(
          self.snapshot, self.session.domain_id,
          type_lookup_settings=self.session.type_lookup_settings))
    self.status.update(f"Saved system report to {path}")

  def action_open_report(self):
    _open_issue_report(self, self.session, self._selected_issue())

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class EndpointChoiceScreen(Screen):
  """Pick which endpoint page of a multi-endpoint finding to open."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("q", "quit_app", "Quit")]

  def __init__(self, session, issue, choices):
    super().__init__()
    self.session = session
    self.issue = issue
    self.choices = list(choices)
    self.table = DataTable()

  def compose(self):
    yield Header()
    if self.issue is None:
      yield Static("[bold]Topic endpoints[/bold]")
      yield Static("Choose an endpoint to open its direct report.")
    else:
      yield Static(f"[bold]{escape(self.issue.title)}[/bold]")
      yield Static("This finding involves more than one endpoint. Choose which one "
                   "to open - each endpoint page describes one endpoint.")
    with Container(id="endpoint_choice"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - choose endpoint domain {self.session.domain_id}"
    self.table.add_columns("Role", "Endpoint", "Type")
    self.table.cursor_type = "row"
    for index, (role, label, endpoint) in enumerate(self.choices):
      self.table.add_row(role, label, endpoint.type_name or "(none)", key=str(index))
    self.table.focus()

  async def on_data_table_row_selected(self, event):
    if event.row_key is None:
      return
    _, _, endpoint = self.choices[int(event.row_key.value)]
    # Pop first: Back from the report should return to the finding, not to this
    # picker, which has nothing left to say once a side has been chosen.
    self.app.pop_screen()
    self.app.push_screen(ReportScreen(
      self.session, endpoint=endpoint, probe=self.session.probe_default))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class IssueDetailScreen(Screen):
  """Evidence and relationships for one passive system finding."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("o", "open_report", "Open report"),
              ("s", "save", "Save system report"),
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
      style = issue_marks.SEVERITY_STYLE.get(self.issue.severity, "bold")
      lines = [f"[{style}]{self.issue.severity.label}: "
               f"{escape(self.issue.title)}[/{style}]", "",
               f"Finding: {', '.join(self.issue.finding_ids)}",
               f"Scope: {self.issue.scope}",
               f"Topic: {self.issue.topic_name or '(domain-wide)'}", "",
               _issue_endpoint_navigation(self.session, self.issue), "",
               "[bold]Observed[/bold]", self.issue.observed or "(none)", "",
               "[bold]Likely cause[/bold]", self.issue.root_cause or "(none)", "",
               "[bold]Recommendation[/bold]", self.issue.recommendation or "(none)"]
      technical_ids = _issue_technical_ids(self.issue)
      if technical_ids:
        lines += ["", technical_ids]
      yield Static("\n".join(lines))
    self.status = Static("", id="issue_detail_status")
    yield self.status
    yield Footer()

  def action_open_report(self):
    _open_issue_report(self, self.session, self.issue)

  def action_save(self):
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(
          self.snapshot, self.session.domain_id,
          type_lookup_settings=self.session.type_lookup_settings))
    self.status.update(f"Saved system report to {path}")

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class TopologyHealthScreen(Screen):
  """Entity-first view across participants, readers, writers, and topics."""

  BINDINGS = [("1", "participants", "Participants"), ("2", "readers", "Readers"),
              ("3", "writers", "Writers"), ("4", "topics", "Topics"),
              ("r", "refresh", "Refresh"), ("f", "findings", "Linked findings"),
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

  def _without_snapshot(self):
    """True when no scan has succeeded yet, with the reason on the status line.

    `None` is a supported state here, not an impossible one: `_scan` returns
    None on a failed first scan and `_report` writes "Press r to retry" over a
    screen that never got a snapshot. Every action that reads `self.snapshot`
    has to survive that. Four of them did not - they raised `AttributeError`
    inside a Textual action handler, which kills the interaction with nothing on
    screen to say why, and `s` additionally left a zero-byte report file behind
    because `open(..., "w")` had already run. The two sibling screens guard this
    at `on_data_table_row_selected` and `action_save`; this is the same guard,
    centralized because this screen has six entry points into the snapshot
    rather than two.
    """
    if self.snapshot is not None:
      return False
    detail = f" ({escape(str(self.scan_error))})" if self.scan_error else ""
    self.status.update(
        f"[red]No topology has been collected yet{detail}.[/red] Press r to retry.")
    return True

  def _render_table(self):
    # Before clearing: a failed first scan must not blank the table and then
    # overwrite its own "Scan failed" banner with a View line describing an
    # empty view.
    if self._without_snapshot():
      return
    self.table.clear(columns=True)
    if self.mode == "participants":
      self.table.add_columns("Participant", "Vendor", "Readers", "Writers", "Topics", "Findings")
      for participant in sorted(self.session.registry.participant_list(), key=lambda item: item.key):
        endpoints = self.session.registry.endpoints_for(participant.key)
        readers = sum(not item.is_writer for item in endpoints)
        writers = sum(item.is_writer for item in endpoints)
        topics = len({item.topic_name for item in endpoints if item.topic_name})
        self.table.add_row(participant.name or "(unnamed)", participant.vendor_name,
                           str(readers), str(writers), str(topics),
                           self._finding_summary(participant_key=participant.key), key=participant.key)
    elif self.mode in ("readers", "writers"):
      writer = self.mode == "writers"
      self.table.add_columns("Topic", "Participant", "Vendor", "Type", "Findings")
      endpoints = self.session.registry.writers() if writer else self.session.registry.readers()
      for endpoint in sorted(endpoints, key=lambda item: (item.topic_name, item.key)):
        participant = self.session.registry.participant_for(endpoint)
        self.table.add_row(endpoint.topic_name or "(unnamed)",
                           participant.name if participant and participant.name else "(unnamed)",
                           endpoint.vendor_name, endpoint.type_name or "(none)",
                           self._finding_summary(endpoint_key=endpoint.key), key=endpoint.key)
    else:
      self.table.add_columns("Topic", "Readers", "Writers", "Findings")
      for topic in self.session.registry.topic_names():
        endpoints = self.session.registry.endpoints_on_topic(topic)
        self.table.add_row(topic, str(sum(not item.is_writer for item in endpoints)),
                           str(sum(item.is_writer for item in endpoints)),
                           self._finding_summary(topic_name=topic), key=f"topic:{topic}")
    self.status.update(f"View: {self.mode.title()} | 1 Participants  2 Readers  "
               "3 Writers  4 Topics | Enter drills in | f linked findings | "
               "r refresh")

  def _finding_summary(self, participant_key=None, endpoint_key=None, topic_name=None):
    linked = []
    for issue in self.snapshot.issues:
      if participant_key and participant_key in issue.participant_keys:
        linked.append(issue)
      elif endpoint_key and (endpoint_key in issue.writer_keys or endpoint_key in issue.reader_keys):
        linked.append(issue)
      elif topic_name and issue.topic_name == topic_name:
        linked.append(issue)
    if not linked:
      return issue_marks.severity_text("OK", f.Severity.OK)
    worst = max(issue.severity for issue in linked)
    noun = "finding" if len(linked) == 1 else "findings"
    summary = issue_marks.severity_text(f"{len(linked)} {noun} (worst: ", worst)
    summary.append(worst.label, style=issue_marks.SEVERITY_STYLE[worst])
    summary.append(")")
    return summary

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

  def action_findings(self):
    if self._without_snapshot():
      return
    keys = self._linked_finding_keys()
    self.app.push_screen(IssueListScreen(self.session, self.snapshot, keys))

  def _linked_finding_keys(self):
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
    """What Enter does: drill into the selected topology row.

    Not bound to a key - `on_data_table_row_selected` is its only caller, so
    what Enter means on a row stays defined in one place.
    """
    if self._without_snapshot():
      return
    if self.mode == "participants" and self.selected_key:
      participant = self.session.registry.participants.get(self.selected_key)
      if participant is not None:
        self.app.push_screen(EndpointListScreen(self.session, participant,
                                                snapshot=self.snapshot))
      return
    if self.mode == "topics" and self.selected_key:
      self.app.push_screen(TopicEndpointsScreen(
          self.session, self.selected_key.removeprefix("topic:"),
          snapshot=self.snapshot))
      return
    endpoint = self._selected_endpoint()
    if endpoint is not None:
      self.app.push_screen(ReportScreen(
          self.session, endpoint=endpoint, probe=self.session.probe_default))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class TopicEndpointsScreen(Screen):
  """Readers and writers belonging to one selected topic."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("f", "findings", "Linked findings"),
              ("o", "open_report", "Choose endpoint report"),
              ("q", "quit_app", "Quit")]

  CSS = """
  #topic_legend { padding: 0 2; }
  """

  def __init__(self, session, topic_name, snapshot=None):
    super().__init__()
    self.session = session
    self.topic_name = topic_name
    self.snapshot = snapshot
    self.table = DataTable()
    self.legend = None
    self.selected_key = None
    self.endpoints_by_row_key = {}

  def compose(self):
    yield Header()
    self.legend = Static("", id="topic_legend")
    yield self.legend
    with Container(id="topic_endpoints"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - topic {self.topic_name}"
    self.table.add_columns("Kind", "Participant", "Vendor", "Type", "Details")
    self.table.cursor_type = "row"
    relationship = system_scan.topic_relationship(
      self.session.registry, self.snapshot, self.topic_name)
    marks = await issue_marks.marks_for(self.session, self.snapshot)
    shown = []
    for group in relationship.groups:
      self._add_endpoint("Compatible group", group.writer, "writer",
                         marks.get(group.writer.key))
      shown.append(marks.get(group.writer.key))
      for reader in group.readers:
        self._add_endpoint("  matched reader", reader, "compatible by discovery",
                           marks.get(reader.key))
        shown.append(marks.get(reader.key))
    for unmatched in relationship.unmatched_writers:
      self._add_endpoint("Unmatched writer", unmatched.endpoint, unmatched.reason,
                         marks.get(unmatched.endpoint.key))
      shown.append(marks.get(unmatched.endpoint.key))
    for unmatched in relationship.unmatched_readers:
      self._add_endpoint("Unmatched reader", unmatched.endpoint, unmatched.reason,
                         marks.get(unmatched.endpoint.key))
      shown.append(marks.get(unmatched.endpoint.key))
    self.legend.update(
        f"{relationship.severity.label}: observed compatibility, not live association\n"
        + issue_marks.legend(shown, getattr(self.snapshot, "captured_at", None)))
    self.table.focus()

  def _add_endpoint(self, section, endpoint, detail, severity):
    participant = self.session.registry.participant_for(endpoint)
    row_key = endpoint.key
    duplicate = 2
    while row_key in self.endpoints_by_row_key:
      row_key = f"{endpoint.key}#{duplicate}"
      duplicate += 1
    self.endpoints_by_row_key[row_key] = endpoint
    self.table.add_row(*issue_marks.cells(
      (endpoint.kind,
         participant.name if participant and participant.name else "(unnamed)",
       endpoint.vendor_name, endpoint.type_name or "(none)",
       f"{section}: {detail}"), severity),
        key=row_key)

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    self.action_debug()

  def _endpoint(self):
    return self.endpoints_by_row_key.get(self.selected_key) if self.selected_key else None

  def action_debug(self):
    endpoint = self._endpoint()
    if endpoint is not None:
      self.app.push_screen(ReportScreen(
          self.session, endpoint=endpoint, probe=self.session.probe_default))

  def action_findings(self):
    issues = {item.key for item in getattr(self.snapshot, "issues", ())
              if item.topic_name == self.topic_name}
    self.app.push_screen(IssueListScreen(self.session, self.snapshot, issues))

  def action_open_report(self):
    choices = []
    for endpoint in sorted(self.session.registry.endpoints_on_topic(self.topic_name),
                           key=lambda item: (item.kind, item.key)):
      participant = self.session.registry.participant_for(endpoint)
      label = participant.name if participant and participant.name else endpoint.key
      choices.append((endpoint.kind, label, endpoint))
    if choices:
      self.app.push_screen(EndpointChoiceScreen(self.session, None, choices))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class TopicListScreen(Screen):
  """Topic-first navigation with passive health rollups."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("r", "refresh", "Refresh"), ("q", "quit_app", "Quit")]

  def __init__(self, session, snapshot=None):
    super().__init__()
    self.session = session
    self.snapshot = snapshot
    self.table = DataTable()
    self.status = None
    self.selected_key = None
    self.scan_error = None

  def compose(self):
    yield Header()
    self.status = Static("Collecting topics...", id="topic_list_status")
    yield self.status
    with Container(id="topic_list"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - topics domain {self.session.domain_id}"
    self.table.add_columns("Topic", "Writers", "Readers", "Health")
    self.table.cursor_type = "row"
    if self.snapshot is None:
      await self._refresh(max_age=SCAN_REUSE_SECONDS)
    else:
      self._render_table()
    self.table.focus()

  async def _refresh(self, max_age=0.0):
    snapshot = await _scan(self, max_age, self.snapshot)
    if snapshot is None:
      return
    self.snapshot = snapshot
    self._render_table()

  def _render_table(self):
    self.table.clear()
    rows = []
    for topic_name in self.session.registry.topic_names():
      endpoints = self.session.registry.endpoints_on_topic(topic_name)
      severity = system_scan.topic_severity(self.snapshot, topic_name, endpoints)
      rows.append((severity, topic_name, endpoints))
    for severity, topic_name, endpoints in sorted(rows, key=lambda item: (-int(item[0]), item[1])):
      self.table.add_row(topic_name, str(sum(item.is_writer for item in endpoints)),
                         str(sum(not item.is_writer for item in endpoints)),
                         issue_marks.severity_text(severity.label, severity),
                         key=topic_name)
    self.status.update("Topics by observed health | Enter opens relationships | r refresh")

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    if self.selected_key:
      self.app.push_screen(TopicEndpointsScreen(
          self.session, self.selected_key, snapshot=self.snapshot))

  def action_refresh(self):
    _spawn(self, self._refresh())

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class MetricsScreen(Screen):
  """Live topology counters, explicitly separate from a saved finding snapshot."""

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