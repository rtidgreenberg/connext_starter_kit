"""The report screen.

It streams: static findings render immediately, then the probe runs in a worker
thread and the findings are replaced with the full set. A probe blocks for up to
--probe-timeout, so running it on the UI thread would freeze the app for ten
seconds.

Packet capture is an operator action, `c`, and never a side effect of opening
this screen. Every report used to spawn `tshark -i any` while it probed:
undisclosed, unconditional, on a privileged interface, leaving a PCAPNG and a
log per report and adding seconds to every navigation - and on a host without
capture privileges it filed tshark's refusal as a wire-evidence error in a
report nobody had asked to include one.
"""

import asyncio
import logging
import os

from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from .. import engine as engine_mod, report as report_mod

#: Used when no `--capture-interface` was given. tshark's own pseudo-interface,
#: named rather than guessed at, and always shown on screen before it is used.
DEFAULT_CAPTURE_INTERFACE = "any"


class ReportScreen(Screen):
  """Findings for one endpoint or participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("c", "capture", "Capture packets"),
      ("s", "save", "Save report"),
      ("q", "quit_app", "Quit"),
  ]

  CSS = """
    #report_tabs {
      height: 1fr;
      border: solid $accent;
    }
    .report_body {
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
    self.bodies = {}
    self.body = None
    self.status = None
    self.capturing = False
    self.probing = False

  def compose(self):
    yield Header()
    self.status = Static("Running static checks...", id="report_status")
    yield self.status
    with TabbedContent(id="report_tabs"):
      for tab_id, title in (("overview", "Overview"), ("findings", "Findings"),
                            ("type", "Type"), ("probe", "Probe"),
                            ("wire", "Wire"), ("config", "Configuration")):
        with TabPane(title, id=tab_id):
          with VerticalScroll(classes="report_body"):
            body = Static("")
            self.bodies[tab_id] = body
            if tab_id == "overview":
              self.body = body
            yield body
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
      self.probing = True
      self.run_worker(self._run_probe(), exit_on_error=False)
    else:
      self.status.update("Static checks complete (no probe for this target). "
                         "Press c for RTPS packet evidence.")

  async def _render_static(self):
    try:
      if self.endpoint is not None:
        self.data = await asyncio.to_thread(
            self.session.diagnose_endpoint, self.endpoint, False)
      else:
        self.data = await asyncio.to_thread(
            self.session.diagnose_participant, self.participant)
      self._update_sections()
    except Exception as e:
      logging.error(f"[ReportScreen] static pass failed: {e}")
      self.bodies["overview"].update(f"Static checks failed: {e}")

  async def _run_probe(self):
    try:
      self.data = await asyncio.to_thread(
          self.session.diagnose_endpoint, self.endpoint, True)
      self._update_sections()
      self.status.update(f"Probe complete. {self.data.verdict}")
    except Exception as e:
      logging.error(f"[ReportScreen] probe failed: {e}")
      self.status.update(f"Probe failed: {e}")
    finally:
      self.probing = False

  # --- Packet capture --------------------------------------------------------

  @property
  def capture_interface(self):
    return (getattr(self.session, "capture_interface", None)
            or DEFAULT_CAPTURE_INTERFACE)

  def action_capture(self):
    """Capture RTPS packets for this endpoint, on request and only on request."""
    if self.endpoint is None:
      self.status.update("Packet capture needs an endpoint; this is a "
                         "participant report.")
      return
    if self.capturing:
      self.status.update("A capture is already running for this endpoint.")
      return
    if self.probing:
      # Two probes on one topic at once would each report the other's traffic.
      self.status.update("Wait for the probe to finish, then press c.")
      return
    # A capture with nothing to observe is an empty file, so a writer report
    # probes again while capturing - that is what puts matched user data on the
    # wire - and the window is the probe's. A reader report has no probe, so it
    # captures for its own fixed window instead.
    probing = self.probe and self.endpoint.is_writer
    seconds = (self.session.probe_timeout if probing
               else engine_mod.DEFAULT_CAPTURE_SECONDS)
    destination = os.path.abspath(self.session.capture_path())
    # Said before tshark is spawned, not after it returns: what is being
    # collected, from where, for how long, and what it leaves on disk.
    self.status.update(
        f"Capturing RTPS packets on interface '{self.capture_interface}' for "
        f"{seconds:.0f}s, writing {destination} (and a .tshark.log beside it). "
        f"Capture needs packet-capture privileges on this host.")
    self.capturing = True
    self.run_worker(self._run_capture(probing, seconds, destination),
                    exit_on_error=False)

  async def _run_capture(self, probing, seconds, destination):
    try:
      self.data = await asyncio.to_thread(
          lambda: self.session.diagnose_endpoint(
              self.endpoint, probe=probing,
              capture_interface=self.capture_interface, capture_seconds=seconds,
              capture_path=destination))
      self._update_sections()
      evidence = self.data.wire_evidence or {}
      source = evidence.get("source", "the capture file")
      if evidence.get("error"):
        self.status.update(f"Capture on '{self.capture_interface}' produced no "
                           f"packet evidence: {evidence['error']}")
      else:
        self.status.update(
            f"Capture complete: {evidence.get('packets', 0)} matching frames in "
            f"{source}. See the Wire tab. {self.data.verdict}")
    except Exception as e:
      logging.error(f"[ReportScreen] capture failed: {e}")
      self.status.update(f"Capture failed: {e}")
    finally:
      self.capturing = False

  def _update_sections(self):
    for tab_id, text in report_mod.render_view_sections(self.data).items():
      self.bodies[tab_id].update(text)

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
