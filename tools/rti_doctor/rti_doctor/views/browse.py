"""Endpoint browsing screen.

Same interaction model as rti_spy: a DataTable, Enter to drill down, b to go
back, q to quit. The only new diagnostic key is o for the passive report.

Reached from the topology view, which selects the participant. The participant
list this module used to own went with the Issues-first landing screen; the
blind-spot findings it summarized now reach the operator through the Issues
list, which the system scan populates from the same rung 0-1 checks.
"""

from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from . import issue_marks
from .report_screen import ReportScreen


class EndpointListScreen(Screen):
  """Endpoints belonging to one participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("o", "open_report", "Open report"),
      ("q", "quit_app", "Quit"),
  ]

  CSS = """
  #directions { padding: 0 2; }
  #endpoint_legend { padding: 0 2; }
  #endpoint_container { height: 1fr; border: solid $accent; }
  """

  def __init__(self, session, participant, snapshot=None):
    super().__init__()
    self.session = session
    self.participant = participant
    # The caller normally has one already - the topology screen this is reached
    # from scanned to build its own rows - so marking the rows costs nothing.
    # Without one, `issue_marks` reuses a recent scan rather than forcing a new
    # O(endpoints^2) pass just to colour a list.
    self.snapshot = snapshot
    self.table = DataTable()
    self.legend = None
    self.selected_key = None

  def compose(self):
    yield Header()
    yield Static(
        f"[bold]{self.participant.name or '(unnamed)'}[/bold] "
        f"({self.participant.vendor_name})  -  "
        "[bold green]Enter[/bold green] deep diagnose  "
        "[bold green]o[/bold green] open report  "
        "[bold green]b[/bold green] back",
        id="directions")
    self.legend = Static("", id="endpoint_legend")
    yield self.legend
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
    marks = await issue_marks.marks_for(self.session, self.snapshot)
    shown = []
    for endpoint in endpoints:
      severity = marks.get(endpoint.key)
      shown.append(severity)
      self.table.add_row(
          *issue_marks.cells((
              endpoint.topic_name or "(unnamed)",
              endpoint.kind,
              endpoint.type_name or "(none)",
              endpoint.type_state,
          ), severity),
          key=endpoint.key,
      )
    self.legend.update(issue_marks.legend(
        shown, getattr(self.snapshot, "captured_at", None)))
    self.table.focus()

  async def on_data_table_row_highlighted(self, event):
    self.selected_key = event.row_key.value if event.row_key else None

  async def on_data_table_row_selected(self, event):
    self.selected_key = event.row_key.value if event.row_key else None
    self.action_debug()

  def action_open_report(self):
    if self.selected_key is None:
      return
    endpoint = self.session.registry.endpoints.get(self.selected_key)
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=False))

  def action_debug(self):
    if self.selected_key is None:
      return
    endpoint = self.session.registry.endpoints.get(self.selected_key)
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()
