"""Report and sweep screens.

The report screen streams: static findings render immediately, then the probe
runs in a worker thread and the findings are replaced with the full set. A probe
blocks for up to --probe-timeout, so running it on the UI thread would freeze the
app for ten seconds.
"""

import asyncio
import logging
import os

from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .. import report as report_mod


class ReportScreen(Screen):
  """Findings for one endpoint or participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("s", "save", "Save report"),
      ("q", "quit_app", "Quit"),
  ]

  CSS = """
  #report_body {
      height: 1fr;
      border: solid $accent;
      padding: 1 2;
  }
  #report_status {
      height: auto;
      padding: 0 2;
      color: $warning;
  }
  """

  def __init__(self, session, endpoint=None, participant=None, probe=True):
    super().__init__()
    self.session = session
    self.endpoint = endpoint
    self.participant = participant
    self.probe = probe
    self.data = None
    self.body = None
    self.status = None

  def compose(self):
    yield Header()
    self.status = Static("Running static checks...", id="report_status")
    yield self.status
    with VerticalScroll(id="report_body"):
      self.body = Static("")
      yield self.body
    yield Footer()

  async def on_mount(self):
    target = (f"topic '{self.endpoint.topic_name}'" if self.endpoint is not None
              else f"participant '{getattr(self.participant, 'name', '')}'")
    self.title = f"rti_doctor - {target}"

    # Static pass first so something useful is on screen immediately.
    await self._render_static()
    if self.endpoint is not None and self.probe and self.endpoint.is_writer:
      self.status.update(
          f"Probing '{self.endpoint.topic_name}' for up to "
          f"{self.session.probe_timeout:.0f}s (creating a reader, sampling "
          f"statuses)...")
      asyncio.create_task(self._run_probe())
    else:
      self.status.update("Static checks complete (no probe for this target).")

  async def _render_static(self):
    try:
      if self.endpoint is not None:
        self.data = await asyncio.to_thread(
            self.session.diagnose_endpoint, self.endpoint, False)
      else:
        self.data = await asyncio.to_thread(
            self.session.diagnose_participant, self.participant)
      self.body.update(report_mod.render_text(self.data))
    except Exception as e:
      logging.error(f"[ReportScreen] static pass failed: {e}")
      self.body.update(f"Static checks failed: {e}")

  async def _run_probe(self):
    try:
      self.data = await asyncio.to_thread(
          self.session.diagnose_endpoint, self.endpoint, True)
      self.body.update(report_mod.render_text(self.data))
      self.status.update(f"Probe complete. {self.data.verdict}")
    except Exception as e:
      logging.error(f"[ReportScreen] probe failed: {e}")
      self.status.update(f"Probe failed: {e}")

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()

  def action_save(self):
    if self.data is None:
      self.status.update("Nothing to save yet.")
      return
    scope = (self.endpoint.topic_name if self.endpoint is not None
             else getattr(self.participant, "name", "participant"))
    path = os.path.abspath(report_mod.default_filename(self.session.domain_id, scope))
    try:
      with open(path, "w", encoding="utf-8") as handle:
        handle.write(report_mod.render_text(self.data))
      self.status.update(f"Saved report to {path}")
    except OSError as e:
      self.status.update(f"Could not save report: {e}")


class SweepScreen(Screen):
  """Diagnose every writer on the domain, one row per topic."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("s", "save", "Save report"),
      ("enter", "open", "Open"),
      ("q", "quit_app", "Quit"),
  ]

  CSS = """
  #sweep_status { height: auto; padding: 0 2; color: $warning; }
  #sweep_container { height: 1fr; border: solid $accent; }
  """

  def __init__(self, session):
    super().__init__()
    self.session = session
    self.table = DataTable()
    self.status = None
    self.rows = []
    self.selected_index = None

  def compose(self):
    yield Header()
    self.status = Static("Starting sweep...", id="sweep_status")
    yield self.status
    with Container(id="sweep_container"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = f"rti_doctor - sweep domain {self.session.domain_id}"
    self.table.add_columns("Sev", "Topic", "Vendor", "Verdict")
    self.table.cursor_type = "row"
    asyncio.create_task(self._run_sweep())

  async def _run_sweep(self):
    writers = len(self.session.registry.writers())
    if not writers:
      self.status.update("No writers discovered on this domain.")
      return

    def progress(index, total, writer):
      topic = writer.topic_name if writer is not None else ""
      message = (f"Probing {index + 1}/{total}: {topic}" if writer is not None
                 else f"Sweep complete ({total} writer(s)).")
      self.app.call_from_thread(self.status.update, message)

    try:
      rows, _ = await asyncio.to_thread(self.session.sweep, progress, True)
    except Exception as e:
      logging.error(f"[SweepScreen] sweep failed: {e}")
      self.status.update(f"Sweep failed: {e}")
      return

    self.rows = rows
    self.table.clear()
    for index, row in enumerate(rows):
      self.table.add_row(row["severity"], row["topic"], row["vendor"],
                         row["verdict"], key=str(index))
    errors = sum(1 for r in rows if r["severity"] == "ERROR")
    warns = sum(1 for r in rows if r["severity"] == "WARN")
    self.status.update(
        f"Sweep complete: {len(rows)} writer(s), {errors} with ERROR, "
        f"{warns} with WARN. Enter opens a full report, s saves the sweep.")
    self.table.focus()

  async def on_data_table_row_highlighted(self, event):
    try:
      self.selected_index = int(event.row_key.value)
    except (TypeError, ValueError):
      self.selected_index = None

  def action_open(self):
    if self.selected_index is None or self.selected_index >= len(self.rows):
      return
    row = self.rows[self.selected_index]
    endpoint = row["report"].endpoint
    if endpoint is not None:
      self.app.push_screen(ReportScreen(self.session, endpoint=endpoint, probe=True))

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()

  def action_save(self):
    if not self.rows:
      self.status.update("Nothing to save yet.")
      return
    path = os.path.abspath(
        report_mod.default_filename(self.session.domain_id, "sweep"))
    try:
      with open(path, "w", encoding="utf-8") as handle:
        handle.write(report_mod.render_sweep_text(self.rows, self.session.domain_id))
      self.status.update(f"Saved sweep to {path}")
    except OSError as e:
      self.status.update(f"Could not save sweep: {e}")
