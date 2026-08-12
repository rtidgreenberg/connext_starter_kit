"""The report screen.

It streams: static findings render immediately, then one combined pass - probe
and, if the operator consented to one, packet capture - runs in a worker thread
and the findings are replaced with the full set. That pass blocks for up to
--probe-timeout, so running it on the UI thread would freeze the app.

One pass, not two. A capture with nothing on the wire is an empty file, so a
capture on a probed endpoint has to be the thing that drives the probe. When
capture was a separate keystroke, the full report cost two probes: one on mount
and one under the capture. Asking on entry is what collapses them.

Capture on entry is not a return of what `ccaaa7b` removed. That capture was
silent, unconditional, on `any`, on every navigation, and on a host without
capture privileges it filed tshark's refusal as a wire-evidence error in a
report nobody had asked to include one. Each of those is inverted here: the
interface is chosen before anything runs, Skip is a first-class answer that is
remembered, every entry names on screen what is about to run and where the file
lands, the first failure turns capture off for the session, and what is left on
disk is swept at exit (CAP-1). Reports opened passively - `o`, or from an issue
- still probe nothing and capture nothing.
"""

import asyncio
import logging
import os

from rich.markup import escape
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from .. import engine as engine_mod, report as report_mod, wire

#: Shown for the Skip row. Skip is an answer - "probe, but capture nothing" -
#: and is remembered like any other, so it is worth naming rather than leaving
#: as the absence of a choice.
SKIP_CAPTURE = "Skip"

#: A tshark refusal can be several lines. The status bar repeats it on every
#: later report, so it is truncated there - the untruncated reason is what the
#: failing report itself said.
_REASON_CHARS = 60


def _short(reason):
  reason = " ".join(str(reason).split())
  return (reason if len(reason) <= _REASON_CHARS
          else reason[:_REASON_CHARS - 1] + "…")


class CaptureInterfaceScreen(Screen):
  """Choose which interface a capture runs on, or Skip capturing (CAP-2).

  Before this, the interface came from `--capture-interface` or defaulted to
  `any`, so choosing one meant quitting and relaunching - and `any` needs the
  broadest capture privileges of any choice, making the default the most
  privileged one (N3). An operator on a host where they may capture `lo` and
  nothing else had no way to say so.

  The choice is remembered on the session, so this asks once per session rather
  than on every report. `--capture-interface` still wins outright and skips it.
  """

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("q", "quit_app", "Quit")]

  def __init__(self, session, on_chosen, on_dismiss=None):
    super().__init__()
    self.session = session
    self.on_chosen = on_chosen
    # Dismissal has to do something now that this can open on entry: without
    # it, `b` would leave a report showing static findings, no probe, and a
    # status line still asking a question nothing will answer.
    self.on_dismiss = on_dismiss
    self.table = DataTable()
    # Not enumerated here. `tshark -D` runs extcap helpers - third-party
    # binaries - so it is a subprocess of unbounded duration, and __init__ runs
    # on the Textual event loop where it would freeze the whole TUI. Same
    # reason the probe runs in a worker, per this module's docstring.
    self.interfaces, self.error = (), None
    self.notice = None

  def compose(self):
    yield Header()
    yield Static("[bold]Capture interface[/bold]")
    self.notice = Static("Listing capture interfaces...")
    yield self.notice
    yield Static("Pick the interface to capture RTPS packets on, or Skip to "
                 "probe without capturing. The choice is remembered for this "
                 "session. Capturing needs packet-capture privileges on "
                 f"whichever you choose, and '{wire.ANY_INTERFACE}' needs the "
                 "broadest of all.")
    with Container(id="capture_interface_choice"):
      yield self.table
    yield Footer()

  def _choices(self):
    """Skip first, enumerated interfaces, `any` last and never duplicated.

    Rows are `(number, label, description, interface)`: what is shown and what
    is handed to tshark are separate, so Skip can be a row without becoming a
    sentinel string that some later caller passes to `-i`.

    Skip sits under the cursor for the same reason `any` is pushed to the
    bottom (N3): the reflexive Enter must land on the least privileged and
    least surprising option, not the most.
    """
    choices = [("", SKIP_CAPTURE,
                "no packet capture - probe only, remembered for this session",
                None)]
    for number, description in self.interfaces:
      name = wire.interface_name(description)
      if name and name != wire.ANY_INTERFACE:
        choices.append((number, name, description, name))
    choices.append(("", wire.ANY_INTERFACE,
                    "every interface - needs the broadest privileges",
                    wire.ANY_INTERFACE))
    return choices

  async def on_mount(self):
    self.title = f"rti_doctor - capture interface domain {self.session.domain_id}"
    self.table.add_columns("#", "Interface", "Description")
    self.table.cursor_type = "row"
    self.interfaces, self.error = await asyncio.to_thread(wire.capture_interfaces)
    if self.error:
      # A picker that cannot enumerate is still useful: `any` remains valid, and
      # the reason belongs on screen rather than swallowed.
      self.notice.update(f"Could not list interfaces: {escape(self.error)}. "
                         f"'{wire.ANY_INTERFACE}' is still offered below.")
    else:
      self.notice.update(f"{len(self.interfaces)} interface(s) reported by tshark.")
    self.choices = self._choices()
    for index, (number, label, description, _) in enumerate(self.choices):
      self.table.add_row(number, label, description, key=str(index))
    self.table.focus()

  async def on_data_table_row_selected(self, event):
    if event.row_key is None:
      return
    _, _, _, interface = self.choices[int(event.row_key.value)]
    self.session.record_capture_choice(interface)
    # Pop before starting the pass, so the report screen is what the operator
    # watches it run on.
    self.app.pop_screen()
    self.on_chosen(interface)

  def action_back(self):
    """Leave without answering. Dismissal is not an answer.

    Nothing is recorded, so the next report asks again. Remembering a dismissal
    would make the explicit Skip row decoration, and would silently opt out for
    the session an operator who pressed Escape out of habit.
    """
    self.app.pop_screen()
    if self.on_dismiss is not None:
      self.on_dismiss()

  def action_quit_app(self):
    self.app.exit()


class ReportScreen(Screen):
  """Findings for one endpoint or participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("c", "capture", "Capture packets"),
      ("C", "choose_interface", "Capture interface"),
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

    # Static pass first so something useful is on screen immediately, and so a
    # Skip or a dismissal still leaves a usable report behind the picker.
    await self._render_static()
    # `_render_static` awaited a thread, and `b` works while it does. Without
    # this the picker would be pushed on top of whatever screen the operator
    # navigated to, and its callback would run against a report that is gone.
    # `is_current`, not `is_mounted`: a screen is not yet mounted while its own
    # `on_mount` is still running, so `is_mounted` here is always False.
    if not self.is_current:
      return
    self._offer_full_pass()

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

  # --- The full diagnostic pass ----------------------------------------------

  def _offer_full_pass(self):
    """Run the full diagnostic on entry, asking about capture the first time.

    The order matters. A participant report has nothing to probe or capture; a
    report opened passively (`o`, or from an issue) asked for neither and must
    stay a keypress-cheap screen; and an unanswered capture question is asked
    before anything runs, because the capture has to start before the probe.
    """
    if self.endpoint is None:
      self.status.update(
          "Static checks complete (participant report: no probe, no packet "
          "capture).")
      return
    if not self.probe:
      self.status.update(
          "Static checks complete (opened without probing, so nothing else "
          "runs). Press c for RTPS packet evidence, C to choose the interface.")
      return
    if self.session.pass_in_flight():
      self.status.update(
          "A diagnostic pass started from another report is still finishing. "
          "Press c to run this one when it is done.")
      return
    if self.session.capture_off_reason:
      self._begin_pass(None)
      return
    if not self.session.capture_choice_made:
      self.status.update(
          "Choose where to capture RTPS packets for the full diagnostic, or "
          f"{SKIP_CAPTURE} to probe without capturing.")
      self.app.push_screen(CaptureInterfaceScreen(
          self.session, self._begin_pass,
          on_dismiss=lambda: self._begin_pass(None, dismissed=True)))
      return
    # An answer already exists, which may be a remembered Skip (None).
    self._begin_pass(self.session.capture_interface)

  def _begin_pass(self, interface, dismissed=False):
    """Start one combined probe+capture pass. The only path that runs either."""
    # The picker is a screen, so it can outlive the report that pushed it, and
    # a pass can have started elsewhere while it was open. `is_current` rather
    # than `is_mounted`: this is also reached from `on_mount`, where a screen
    # does not yet count as mounted.
    if not self.is_current:
      return
    if not self._capture_allowed():
      return
    probing = self.probe and self.endpoint is not None
    if not probing and not interface:
      self.status.update("Nothing to run: this report does not probe, and no "
                         "capture interface was chosen. Press C to choose one.")
      return
    seconds = (self.session.probe_timeout if probing
               else engine_mod.DEFAULT_CAPTURE_SECONDS)
    destination = (os.path.abspath(self.session.capture_path())
                   if interface else None)
    # Said before tshark is spawned, not after it returns: what is being
    # collected, from where, for how long, and what it leaves on disk.
    self.status.update(
        self._pass_announcement(interface, probing, seconds, destination,
                                dismissed))
    self.probing, self.capturing = probing, bool(interface)
    # Claimed for the window tshark itself is bounded by, so a claim nobody
    # releases expires no later than the capture it was protecting.
    self.session.claim_pass(seconds + engine_mod.CAPTURE_DURATION_MARGIN)
    # run_worker, not asyncio.create_task: a bare task is only weakly
    # referenced by the loop and nothing cancels it when the screen is popped,
    # so a pass left running would write into unmounted widgets seconds after
    # the operator navigated away.
    self.run_worker(self._run_pass(probing, seconds, destination, interface),
                    exit_on_error=False)

  def _pass_announcement(self, interface, probing, seconds, destination,
                         dismissed=False):
    """What is about to run, said before it runs. Pure, so it can be tested.

    The result text can be intercepted on the status widget, but the entry
    announcement cannot: it is written during `on_mount`, before a test can
    install a recorder.
    """
    topic = self.endpoint.topic_name
    # A reader probe creates a DataWriter that never publishes, so it puts no
    # user data on the wire. Promising frames there would be a lie the Wire tab
    # then contradicts.
    probe_text = (
        f"probing for up to {seconds:.0f}s, creating a "
        f"{'reader' if self.endpoint.is_writer else 'writer'} and sampling "
        f"statuses")
    if interface:
      return (f"Full diagnostic on '{topic}': capturing RTPS packets on "
              f"'{interface}' for {seconds:.0f}s, writing {destination} (and a "
              f".tshark.log beside it)"
              + (f", while {probe_text}. " if probing else ". ")
              + "Capture needs packet-capture privileges on this host. "
                "Press C to change the interface.")
    if self.session.capture_off_reason:
      return (f"Packet capture is off for this session: "
              f"{_short(self.session.capture_off_reason)}. Now {probe_text} on "
              f"'{topic}'. Press C to choose another interface and turn it "
              f"back on.")
    if dismissed:
      return (f"No interface chosen, so nothing is being captured. Now "
              f"{probe_text} on '{topic}'. The next report will ask again; "
              f"press C to choose one now.")
    return (f"Full diagnostic on '{topic}' without packet capture "
            f"({SKIP_CAPTURE} is remembered for this session): {probe_text}. "
            f"Press C to choose a capture interface and run it again.")

  async def _run_pass(self, probing, seconds, destination, interface):
    """One `diagnose_endpoint` call for both halves.

    The engine already starts the capture before the probe, which is the whole
    reason these cannot be two calls: a capture on a probed endpoint has
    nothing to observe unless it is the thing that drives the probe.
    """
    def work():
      try:
        return self.session.diagnose_endpoint(
            self.endpoint, probe=probing, capture_interface=interface,
            capture_seconds=seconds, capture_path=destination)
      finally:
        # Released from the thread, not only the coroutine: `asyncio.to_thread`
        # cannot be cancelled, so a worker killed by navigation would otherwise
        # hold the claim until its deadline for no reason.
        self.session.release_pass()

    try:
      self.data = await asyncio.to_thread(work)
      self._update_sections()
      self.status.update(self._pass_result_text(interface, probing))
    except Exception as e:
      logging.error(f"[ReportScreen] diagnostic pass failed: {e}")
      self.status.update(f"Diagnostic pass failed: {e}")
    finally:
      self.probing = self.capturing = False
      # Released here as well as in the thread: the thread covers a cancelled
      # worker, and this covers a coroutine entered but cancelled before
      # `to_thread` dispatches. Both are idempotent, and the claim's own
      # deadline covers the case neither reaches - a worker cancelled before it
      # ever ran.
      self.session.release_pass()

  def _pass_result_text(self, interface, probing):
    """What the pass produced - and the one place capture turns itself off."""
    if not interface:
      return f"Probe complete. {self.data.verdict}"
    evidence = self.data.wire_evidence or {}
    source = evidence.get("source", "the capture file")
    if evidence.get("error"):
      lead = "Probe complete, but the capture" if probing else "The capture"
      reason = (f"{lead} on '{interface}' produced no packet evidence: "
                f"{evidence['error']}.")
      tail = f" {self.data.verdict}" if probing else ""
      # Only a capture that never started says anything about the next one.
      # "No tshark" and "no capture privileges" are properties of the host and
      # would otherwise attach a wire-evidence error to every later report,
      # which is the harm; a capture that ran and then ended badly - killed
      # after termination, a truncated file - is this report's problem alone,
      # and disabling the session for it would be the opposite mistake.
      #
      # An exception from `diagnose_endpoint` deliberately does not land here:
      # the engine funnels tshark failures into `wire_evidence["error"]`, so an
      # exception is a bug, not a privilege problem, and stays per-report.
      if evidence.get("error_stage") == "start":
        self.session.disable_capture(evidence["error"])
        return (f"{reason} Packet capture is now off for this session; press C "
                f"to choose another interface.{tail}")
      return f"{reason} Press c to try again, C to change the interface.{tail}"
    # Name what was parsed, not just how many frames matched. A capture can
    # yield the peer's product version while matching zero user-data frames,
    # and the count alone reported that as nothing.
    return (f"{'Full diagnostic' if probing else 'Capture'} complete: "
            f"{report_mod.capture_headline(self.data)}. Written to {source}. "
            f"See Overview for what the capture added, Wire for the full "
            f"counts. {self.data.verdict}")

  # --- Packet capture on request ---------------------------------------------

  def action_capture(self):
    """Get packet evidence for this endpoint now.

    Still the way to ask for a capture the entry pass did not run: after a Skip,
    after a dismissal, or on a report opened passively.
    """
    if not self._capture_allowed():
      return
    # Falsy for any reason - never asked, Skip, or disabled by a failure - means
    # there is no interface to capture on, so ask rather than reaching for the
    # most privileged one there is (CAP-2).
    if not self.session.capture_interface:
      self.app.push_screen(
          CaptureInterfaceScreen(self.session, self._begin_pass))
      return
    self._begin_pass(self.session.capture_interface)

  def action_choose_interface(self):
    """Re-open the picker, so one choice does not bind the whole session.

    Also the way back from a capture that failed: recording a choice clears the
    reason capture was turned off.
    """
    if not self._capture_allowed():
      return
    self.app.push_screen(CaptureInterfaceScreen(self.session, self._begin_pass))

  def _capture_allowed(self):
    if self.endpoint is None:
      self.status.update("Packet capture needs an endpoint; this is a "
                         "participant report.")
      return False
    if self.capturing:
      self.status.update("A capture is already running for this endpoint.")
      return False
    if self.probing:
      # Two probes on one topic at once would each report the other's traffic.
      self.status.update("This report's diagnostic pass is still running.")
      return False
    if self.session.pass_in_flight():
      # The same hazard one screen further out: workers survive navigation, so
      # a pass started on another report can still be live here.
      self.status.update("A diagnostic pass started from another report is "
                         "still finishing.")
      return False
    return True

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
      # Appendix C names the capture this report was written from, so saving
      # the report is what keeps that file past exit (CAP-1). A citation
      # pointing at a swept file would be worse than no citation.
      evidence = self.data.wire_evidence or {}
      self.session.retain_capture(evidence.get("source"))
      self.status.update(f"Saved report to {path}")
    except OSError as e:
      self.status.update(f"Could not save report: {e}")
