"""The report screen.

It streams: static findings render immediately, then the probe runs in a worker
thread and the findings are replaced with the full set. A probe blocks for up to
--probe-timeout, so running it on the UI thread would freeze the app for ten
seconds.
"""

import asyncio
import logging
import os

from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

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
      # run_worker, not asyncio.create_task: a bare task is only weakly
      # referenced by the loop and nothing cancels it when the screen is
      # popped, so a probe left running would write into unmounted widgets
      # seconds after the operator navigated away.
      self.run_worker(self._run_probe(), exit_on_error=False)
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
