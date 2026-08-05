"""System overview, passive issue list, and observed-topology metrics screens."""

import asyncio
import os
import time

from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .. import findings as f, report
from .browse import EndpointListScreen
from .report_screen import ReportScreen


def _issue_counts(snapshot):
  return {severity: sum(issue.severity == severity for issue in snapshot.issues)
          for severity in (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO)}


class SystemOverviewScreen(Screen):
  """The initial routing screen for issue-first and topology-first workflows."""

  BINDINGS = [("1", "issues", "Issues"), ("i", "issues", "Issues"),
              ("2", "topology", "Topology"), ("t", "topology", "Topology"),
              ("m", "metrics", "Metrics"), ("s", "save", "Save report"),
              ("q", "quit_app", "Quit")]

  def __init__(self, session):
    super().__init__()
    self.session = session
    self.summary = None
    self.status = None

  def compose(self):
    yield Header()
    with Container(id="system_overview"):
      yield Static("[bold cyan]DDS System Overview[/bold cyan]")
      self.summary = Static("Collecting observed topology...", id="system_summary")
      yield self.summary
      yield Static("[1] Issues\n    Triage errors, warnings, and notes.\n\n"
                   "[2] DDS Topology & Health\n"
                   "    Browse participants and their discovered endpoints.")
      self.status = Static("", id="system_status")
      yield self.status
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - domain {self.session.domain_id}"
    await self.refresh_summary()

  async def refresh_summary(self):
    snapshot = await asyncio.to_thread(self.session.system_scan)
    counts = _issue_counts(snapshot)
    metrics = snapshot.topology
    self.summary.update(
        f"Observed: {metrics['participants']} participants | {metrics['readers']} readers | "
        f"{metrics['writers']} writers | {metrics['topic_count']} topics\n"
        f"Issues: {counts[f.Severity.ERROR]} Errors | {counts[f.Severity.WARN]} Warnings | "
        f"{counts[f.Severity.INFO]} Notes")
    self._snapshot = snapshot

  def action_issues(self):
    self.app.push_screen(IssueListScreen(self.session))

  def action_topology(self):
    self.app.push_screen(TopologyHealthScreen(self.session))

  def action_metrics(self):
    self.app.push_screen(MetricsScreen(self.session))

  def action_save(self):
    snapshot = getattr(self, "_snapshot", None)
    if snapshot is None:
      return
    path = os.path.abspath(report.system_filename(self.session.domain_id))
    with open(path, "w", encoding="utf-8") as handle:
      handle.write(report.render_system_text(snapshot, self.session.domain_id))
    self.status.update(f"Saved system report to {path}")

  def action_quit_app(self):
    self.app.exit()


class IssueListScreen(Screen):
  """A stable passive issue snapshot, refreshed only by the operator."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("r", "refresh", "Refresh"), ("m", "metrics", "Metrics"),
              ("s", "save", "Save report"), ("o", "open_report", "Open report"),
              ("d", "debug", "Debug writer"), ("q", "quit_app", "Quit")]

  def __init__(self, session, snapshot=None, issue_keys=None):
    super().__init__()
    self.session = session
    self.table = DataTable()
    self.status = None
    self.snapshot = snapshot
    self.issue_keys = set(issue_keys) if issue_keys is not None else None
    self.selected_key = None

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
      await self._refresh()
    else:
      self._render_snapshot()
    self.table.focus()

  async def _refresh(self):
    previous = self.selected_key
    self.snapshot = await asyncio.to_thread(self.session.system_scan)
    self._render_snapshot(previous)

  def _visible_issues(self):
    if self.snapshot is None:
      return ()
    if self.issue_keys is None:
      return self.snapshot.issues
    return tuple(item for item in self.snapshot.issues if item.key in self.issue_keys)

  def _render_snapshot(self, previous=None):
    self.table.clear()
    issues = self._visible_issues()
    for number, issue in enumerate(issues, 1):
      self.table.add_row(str(number), issue.severity.label, issue.topic_name or "(domain)",
                         ", ".join(issue.finding_ids), "observed", key=issue.key)
    counts = {severity: sum(issue.severity == severity for issue in issues)
              for severity in (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO)}
    stamp = time.strftime("%H:%M:%S", time.localtime(self.snapshot.captured_at))
    self.status.update(f"Snapshot {stamp}: {counts[f.Severity.ERROR]} Errors | "
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

  def _selected_issue(self):
    if self.snapshot is None or self.selected_key is None:
      return None
    return next((item for item in self._visible_issues() if item.key == self.selected_key), None)

  def action_refresh(self):
    asyncio.create_task(self._refresh())

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

  def action_debug(self):
    issue = self._selected_issue()
    if issue is None or len(issue.writer_keys) != 1:
      self.status.update("Debug requires an issue with exactly one selected writer.")
      return
    endpoint = self.session.registry.endpoints.get(issue.writer_keys[0])
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class IssueDetailScreen(Screen):
  """Evidence and relationships for one passive system issue."""

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("o", "open_report", "Open report"), ("d", "debug", "Debug writer"),
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

  def _writer(self):
    if len(self.issue.writer_keys) != 1:
      return None
    return self.session.registry.endpoints.get(self.issue.writer_keys[0])

  def action_open_report(self):
    endpoint = self._writer()
    if endpoint is None:
      self.status.update("Open report requires an issue with exactly one writer.")
      return
    self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_debug(self):
    endpoint = self._writer()
    if endpoint is None:
      self.status.update("Debug requires an issue with exactly one writer.")
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


class TopologyHealthScreen(Screen):
  """Entity-first view across participants, readers, writers, and topics."""

  BINDINGS = [("1", "participants", "Participants"), ("2", "readers", "Readers"),
              ("3", "writers", "Writers"), ("4", "topics", "Topics"),
              ("r", "refresh", "Refresh"), ("i", "issues", "Linked issues"),
              ("d", "debug", "Debug writer"), ("o", "open_report", "Open report"),
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
    await self._refresh()
    self.table.focus()

  async def _refresh(self):
    self.snapshot = await asyncio.to_thread(self.session.system_scan)
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
    asyncio.create_task(self._refresh())

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
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_debug(self):
    endpoint = self._selected_endpoint()
    if endpoint is None or not endpoint.is_writer:
      self.status.update("Debug is available only when one writer is selected.")
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
              ("o", "open_report", "Open report"), ("d", "debug", "Debug writer"),
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
    self.action_open_report()

  def _endpoint(self):
    return self.session.registry.endpoints.get(self.selected_key) if self.selected_key else None

  def action_open_report(self):
    endpoint = self._endpoint()
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_debug(self):
    endpoint = self._endpoint()
    if endpoint is not None and endpoint.is_writer:
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

  def compose(self):
    yield Header()
    with VerticalScroll(id="metrics_body"):
      self.body = Static("Collecting metrics...")
      yield self.body
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - metrics domain {self.session.domain_id}"
    await self._refresh()

  async def _refresh(self):
    snapshot = await asyncio.to_thread(self.session.system_scan)
    data = snapshot.topology
    self.body.update("\n".join([
        "[bold]Observed Domain Metrics[/bold]", "",
        f"Domain ID                 {self.session.domain_id}",
        f"Remote participants       {data['participants']}",
        f"Remote DataReaders         {data['readers']}",
        f"Remote DataWriters         {data['writers']}",
        f"Unique topics              {data['topic_count']}",
        f"Topic names                {', '.join(data['topics']) or '(none observed)'}",
        f"Source                     {data['source']}",
        f"Coverage                   {data['completion_note']}",
    ]))

  def action_refresh(self):
    asyncio.create_task(self._refresh())

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()