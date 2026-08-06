"""Endpoint browsing screen.

Same interaction model as rti_spy: a DataTable, Enter to drill down, b to go
back, q to quit. The only new keys are the diagnostic ones (d, o).

Reached from the topology view, which selects the participant. The participant
list this module used to own went with the Issues-first landing screen; the
blind-spot findings it summarized now reach the operator through the Issues
list, which the system scan populates from the same rung 0-1 checks.
"""

from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .report_screen import ReportScreen


class EndpointListScreen(Screen):
  """Endpoints belonging to one participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("d", "debug", "Debug writer"),
      ("o", "open_report", "Open report"),
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
        "[bold green]Enter[/bold green] details  "
        "[bold green]d[/bold green] debug writer  "
        "[bold green]o[/bold green] open report  "
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
    self.action_open_report()

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
    if endpoint is not None and endpoint.is_writer:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()
