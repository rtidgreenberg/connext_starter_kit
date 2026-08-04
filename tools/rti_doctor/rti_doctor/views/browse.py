"""Participant and endpoint browsing screens.

Same interaction model as rti_spy: a welcome panel with instructions, a
DataTable, Enter to drill down, b to go back, q to quit. The only new keys are
the diagnostic ones (d, D, s).
"""

import logging

from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .. import findings as f, records
from .report_screen import ReportScreen, SweepScreen


class ParticipantListScreen(Screen):
  """Top-level screen: every participant on the domain, with vendor and health."""

  BINDINGS = [
      ("d", "diagnose", "Diagnose"),
      ("D", "sweep", "Sweep all"),
      ("q", "quit_app", "Quit"),
  ]

  CSS = """
  #welcome_panel {
      height: auto;
      border: solid $primary;
      padding: 1 2;
      margin-bottom: 1;
  }
  #blind_spots {
      height: auto;
      padding: 0 2;
      color: $warning;
  }
  #participant_container {
      height: 1fr;
      border: solid $accent;
  }
  """

  def __init__(self, session):
    super().__init__()
    self.session = session
    self.table = DataTable()
    self.selected_key = None
    self.blind_spot_panel = None
    self.blind_spot_findings = []

  def compose(self):
    yield Header()
    with Container(id="welcome_panel"):
      yield Static("[bold cyan]RTI Doctor - DDS interoperability diagnostics[/bold cyan]")
      yield Static(
          f"Domain [bold]{self.session.domain_id}[/bold]. Discovers participants from "
          f"any DDS vendor and diagnoses why communication fails.")
      yield Static("[yellow]Keys:[/yellow] "
                   "[bold green]Enter[/bold green] endpoints  "
                   "[bold green]d[/bold green] diagnose selected  "
                   "[bold green]D[/bold green] sweep all writers  "
                   "[bold green]q[/bold green] quit")
    self.blind_spot_panel = Static("", id="blind_spots")
    yield self.blind_spot_panel
    with VerticalScroll(id="participant_container"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - domain {self.session.domain_id}"
    self.table.add_columns("Participant Name", "IP", "Vendor", "RTPS", "Type state")
    self.table.cursor_type = "row"
    self._refresh_blind_spots()
    await self.refresh_table()
    # The table must hold focus or Enter/d never reach it, and no row is ever
    # highlighted, so selected_key stays None and every action silently no-ops.
    self.table.focus()

  def _refresh_blind_spots(self):
    """Run the rung 0-1 audit and summarize it above the table."""
    try:
      self.blind_spot_findings = f.rank(self.session.diagnose_domain())
    except Exception as e:
      logging.error(f"[ParticipantListScreen] blind-spot audit failed: {e}")
      return

    problems = [x for x in self.blind_spot_findings if x.is_problem]
    if not problems:
      self.blind_spot_panel.update("")
      return
    worst = problems[0]
    extra = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
    self.blind_spot_panel.update(
        f"[!] {worst.severity.label}: {worst.title}{extra}  -  press d on any row "
        f"for the full audit")

  async def refresh_table(self):
    """Redraw the participant rows, preserving the cursor position."""
    cursor = self.table.cursor_row
    self.table.clear()
    for participant in sorted(self.session.registry.participant_list(),
                              key=lambda p: (p.name or "", p.key)):
      self.table.add_row(
          participant.name or "(unnamed)",
          participant.ip or "unknown",
          participant.vendor_name,
          participant.protocol_text,
          self._type_state_summary(participant),
          key=participant.key,
      )
    if cursor is not None and 0 <= cursor < self.table.row_count:
      self.table.move_cursor(row=cursor)

  def _type_state_summary(self, participant):
    """Per-participant rollup of writer type resolution - the key cross-vendor cell."""
    writers = [e for e in self.session.registry.endpoints_for(participant.key)
               if e.is_writer]
    if not writers:
      return "no writers"
    resolved = sum(1 for w in writers if w.type_state == records.TYPE_RESOLVED)
    unavailable = sum(1 for w in writers if w.type_state == records.TYPE_UNAVAILABLE)
    pending = len(writers) - resolved - unavailable
    if unavailable:
      return f"! {unavailable} of {len(writers)} no type"
    if pending:
      return f"{resolved}/{len(writers)} resolved, {pending} pending"
    return f"{resolved}/{len(writers)} resolved"

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    await self._open_endpoints()

  async def _open_endpoints(self):
    if self.selected_key is None:
      return
    participant = self.session.registry.participants.get(self.selected_key)
    if participant is not None:
      await self.app.push_screen(EndpointListScreen(self.session, participant))

  def action_diagnose(self):
    if self.selected_key is None:
      return
    participant = self.session.registry.participants.get(self.selected_key)
    if participant is not None:
      self.app.push_screen(ReportScreen(self.session, participant=participant))

  def action_sweep(self):
    self.app.push_screen(SweepScreen(self.session))

  def action_quit_app(self):
    self.app.exit()


class EndpointListScreen(Screen):
  """Endpoints belonging to one participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("d", "diagnose", "Diagnose"),
      ("q", "quit_app", "Quit"),
  ]

  CSS = """
  #directions { padding: 0 2; }
  #endpoint_container { height: 1fr; border: solid $accent; }
  """

  def __init__(self, session, participant):
    super().__init__()
    self.session = session
    self.participant = participant
    self.table = DataTable()
    self.selected_key = None

  def compose(self):
    yield Header()
    yield Static(
        f"[bold]{self.participant.name or '(unnamed)'}[/bold] "
        f"({self.participant.vendor_name})  -  "
        "[bold green]Enter[/bold green]/[bold green]d[/bold green] diagnose  "
        "[bold green]b[/bold green] back",
        id="directions")
    with Container(id="endpoint_container"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - {self.participant.name or self.participant.key}"
    self.table.add_columns("Topic Name", "Kind", "Type Name", "Type state")
    self.table.cursor_type = "row"
    self.session.registry.expire_type_waits()
    endpoints = sorted(self.session.registry.endpoints_for(self.participant.key),
                       key=lambda e: (e.topic_name, e.kind))
    for endpoint in endpoints:
      self.table.add_row(
          endpoint.topic_name or "(unnamed)",
          endpoint.kind,
          endpoint.type_name or "(none)",
          endpoint.type_state,
          key=endpoint.key,
      )
    self.table.focus()

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    self.action_diagnose()

  def action_diagnose(self):
    if self.selected_key is None:
      return
    endpoint = self.session.registry.endpoints.get(self.selected_key)
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()
