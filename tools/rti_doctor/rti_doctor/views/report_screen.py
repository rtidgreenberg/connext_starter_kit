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
import collections
import logging
import os
import signal
import subprocess
import time

from rich.markup import escape
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from .. import (engine as engine_mod, livedata, paths, probe as probe_mod,
                report as report_mod, vendors, wire)

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


class PublishConsentScreen(Screen):
  """Explicit approval before rti_doctor publishes into the system under test.

  Every other thing this tool does is read-only. Publishing is not: the selected
  reader belongs to a running application, and a synthetic sample delivered to it
  is indistinguishable from production data. That is not a preference to be
  defaulted, so it is asked here, per endpoint, and never remembered - unlike the
  capture choice, which is remembered precisely because it changes nothing about
  the system it observes.

  Declining is the row under the cursor, for the same reason `Skip` is in
  `CaptureInterfaceScreen`: a reflexive Enter must land on the choice that
  changes nothing.
  """

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("q", "quit_app", "Quit")]

  def __init__(self, endpoint, on_answer):
    super().__init__()
    self.endpoint = endpoint
    self.on_answer = on_answer
    self.table = DataTable()
    self.choices = []

  def compose(self):
    yield Header()
    yield Static("[bold]Publish synthetic samples?[/bold]")
    topic = getattr(self.endpoint, "topic_name", "(unknown topic)")
    yield Static(
        f"To verify that data actually reaches the selected reader on "
        f"'{escape(str(topic))}', rti_doctor must PUBLISH to that topic. "
        f"The subscribed application will receive up to "
        f"{probe_mod.PROBE_SAMPLE_COUNT} synthetic sample(s) and cannot tell "
        f"them from production data. Nothing else rti_doctor does writes to the "
        f"system under test.")
    yield Static(
        "Declining still reports the match and the reliable handshake from the "
        "probe writer's own counters - it just cannot prove delivery.")
    with Container(id="publish_consent_choice"):
      yield self.table
    yield Footer()

  async def on_mount(self):
    self.title = "rti_doctor - publish synthetic samples?"
    self.table.add_columns("Answer", "What happens")
    self.table.cursor_type = "row"
    self.choices = [
        ("Do not publish", "observe only - nothing is written to the topic",
         False),
        (f"Publish {probe_mod.PROBE_SAMPLE_COUNT} sample(s)",
         "the subscribed application receives them as ordinary data", True),
    ]
    for index, (label, description, _) in enumerate(self.choices):
      self.table.add_row(label, description, key=str(index))
    self.table.focus()

  async def on_data_table_row_selected(self, event):
    if event.row_key is None:
      return
    _, _, approved = self.choices[int(event.row_key.value)]
    self.app.pop_screen()
    self.on_answer(approved)

  def action_back(self):
    """Escape is a refusal, not an unanswered question.

    The safe reading is the only defensible one: an operator who backed out of a
    prompt about writing to their production system did not consent to it.
    """
    self.app.pop_screen()
    self.on_answer(False)

  def action_quit_app(self):
    self.app.exit()


#: The profiles `run_version_matrix.sh` tries, in the order it tries them. The
#: script owns the real list; this mirrors it so the progress table can show a
#: row per profile before the runner has reached it.
MATRIX_PROFILES = ("default-v2", "vendor-v2", "vendor-v1")

#: Discovery settle floor for a matrix child run, matching the runner script's
#: own `--settle` default. Cross-vendor discovery is slower than the interactive
#: session's settle, and the preflight fails the topic check if it looks too
#: early, so a shorter session value is not carried into the children.
MATRIX_MIN_SETTLE = 20.0

#: How long a terminated matrix runner gets to exit before it is killed.
MATRIX_STOP_GRACE = 5.0

#: How often the Data tab drains its live reader. Fast enough that a 30 Hz
#: writer reads as a stream rather than as steps, slow enough that the event
#: loop is not spending its life in `take()`.
LIVE_POLL_SECONDS = 0.2

#: Samples the feed keeps on screen. It is a window on a live topic, not a
#: recording: a writer left running overnight must cost a bounded amount of
#: memory, and an operator reads the newest arrivals at the bottom rather than
#: the first hundred.
#:
#: `_render_live` rebuilds this whole window on every poll that brings a sample,
#: so the pair of numbers is a cost. Measured on this host at the worst case the
#: two allow - 200 samples at `livedata.SAMPLE_LIMIT`, 791 KB - one redraw is
#: 5.5 ms median and 14.3 ms at worst against the 200 ms poll, and 0.7 ms for a
#: payload the size of the test fixture's rich type. Raising either number, or
#: shortening the poll, spends against that margin.
LIVE_SAMPLE_HISTORY = 200

#: Consecutive failed polls before the feed gives up and says so. A poll that
#: fails returns nothing, and nothing is indistinguishable from a quiet writer -
#: so a reader that cannot be read has to stop pretending to be one rather than
#: log at five times a second forever.
LIVE_ERROR_LIMIT = 5


class CompatibilityMatrixScreen(Screen):
  """Live progress and evidence for isolated cross-vendor compatibility probes.

  Nothing in the runner behind this is specific to one vendor: it applies
  Connext XTypes and TypeObject profiles to fresh observer processes, and the
  peer is whatever is publishing the topic. `vendor` is therefore a label for
  what was detected, not a switch - it names the peer this run is about so the
  evidence left on disk can be read back months later.
  """

  BINDINGS = [("b", "back", "Back"), ("escape", "back", "Back"),
              ("q", "quit_app", "Quit")]

  def __init__(self, command, output_dir, vendor=None):
    super().__init__()
    self.command = command
    self.output_dir = output_dir
    self.vendor = vendor
    self.progress = None
    self.detail = None
    # Held so leaving the screen can stop the run; see `on_unmount`.
    self.process = None
    self.states = {"preflight": "waiting",
                   **{profile: "waiting" for profile in MATRIX_PROFILES}}

  def compose(self):
    yield Header()
    yield Static(f"[bold]{self._heading()}[/bold]")
    self.progress = Static("", id="compatibility_matrix_progress")
    yield self.progress
    with VerticalScroll(id="compatibility_matrix_detail"):
      # `markup=False`: this pane shows child-report text and raw runner stdout.
      # Parsed as markup, the reports' own "[ERROR]"/"[WARN]" labels vanish
      # (verified on this Textual), and a peer-supplied name containing "[/]"
      # raises MarkupError - collapsing a finished matrix into "the matrix
      # stopped". The progress table above is ours and keeps its markup.
      self.detail = Static("Preparing isolated observer processes...",
                           markup=False)
      yield self.detail
    yield Footer()

  def _heading(self):
    """Named after the peer when one was identified, generic when not."""
    if not self.vendor:
      return "Cross-Vendor Compatibility Matrix"
    return f"Cross-Vendor Compatibility Matrix - {self.vendor} writer"

  async def on_mount(self):
    self.title = "rti_doctor - cross-vendor compatibility matrix"
    self._render_progress()
    self.run_worker(self._run_matrix(), exit_on_error=False)

  def _render_progress(self):
    lines = ["Profile       Status"]
    lines.extend(f"{name:<13} {state}" for name, state in self.states.items())
    self.progress.update("\n".join(lines))

  @staticmethod
  def _next_text(lines, index):
    """The next line of report text after `index`, skipping section rules.

    `report._section` wraps every heading in a rule of dashes, so the line after
    "VERDICT" is that rule, not the verdict. Taking the first non-blank line
    reported an 80-dash rule as the verdict of every profile.
    """
    for item in lines[index + 1:]:
      stripped = item.strip()
      if not stripped or set(stripped) <= set("-="):
        continue
      return stripped
    return ""

  def _profile_findings(self):
    """Compact verdict and problem titles from completed child reports."""
    rows = []
    for profile in MATRIX_PROFILES:
      path = os.path.join(self.output_dir, profile, "topic_report.txt")
      if not os.path.isfile(path):
        continue
      try:
        with open(path, encoding="utf-8") as handle:
          lines = [line.rstrip() for line in handle]
      except OSError:
        continue
      verdict = ""
      for index, line in enumerate(lines):
        if line.startswith("VERDICT"):
          verdict = self._next_text(lines, index)
          break
      findings = []
      for index, line in enumerate(lines):
        if line.startswith("[ERROR]") or line.startswith("[WARN]"):
          findings.append(f"{line} {self._next_text(lines, index)}")
      rows.append(f"{profile}: {verdict or 'report completed'}")
      rows.extend(f"  {finding}" for finding in findings[:4])
    return "\n".join(rows) or "No completed profile reports were available."

  def _note_progress(self, line):
    """Record one MATRIX_PROGRESS line from the runner.

    The state is the rest of the line, not a single token: the runner reports
    results verbatim ("no ERROR findings", "ERROR findings or startup failure"),
    so a fixed four-field split raised ValueError on the three-token
    "MATRIX_PROGRESS preflight running" and killed this worker before the first
    profile ran.
    """
    parts = line.split(" ", 2)
    if len(parts) < 3:
      logging.warning(f"[matrix] malformed progress line: {line!r}")
      return
    _, profile, state = parts
    if profile not in self.states:
      logging.warning(f"[matrix] unknown profile: {profile!r}")
      return
    self.states[profile] = state
    self._render_progress()

  async def _run_matrix(self):
    """Drive the runner, reporting any failure on screen.

    The worker is started with `exit_on_error=False` so a failure here cannot
    take the TUI down with it - which also means nothing else would ever say
    the matrix had stopped, and the screen would sit on its placeholder.
    """
    try:
      await self._stream_matrix()
    except Exception as error:  # noqa: BLE001 - reported, not swallowed
      logging.error(f"[matrix] runner failed: {error}")
      self.detail.update(f"The compatibility matrix stopped: {error}")

  async def _stream_matrix(self):
    try:
      # Its own process group, so leaving this screen can take the whole tree
      # of child rti_doctor observers down with it rather than orphaning them.
      process = await asyncio.to_thread(
          lambda: subprocess.Popen(
              self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
              text=True, start_new_session=True))
    except OSError as error:
      self.detail.update(f"Could not start compatibility matrix: {error}")
      return
    self.process = process

    output = []
    while True:
      line = await asyncio.to_thread(process.stdout.readline)
      if not line:
        break
      line = line.rstrip()
      output.append(line)
      if line.startswith("MATRIX_PROGRESS "):
        self._note_progress(line)
      else:
        self.detail.update("\n".join(output[-12:]))

    status = await asyncio.to_thread(process.wait)
    summary_path = os.path.join(self.output_dir, "summary.txt")
    try:
      with open(summary_path, encoding="utf-8") as handle:
        summary = handle.read().strip()
    except OSError:
      summary = "No matrix summary was written."
    self.detail.update(
      f"Matrix exit: {status}\nEvidence: {self.output_dir}\n\n"
      f"Findings\n{self._profile_findings()}\n\nSummary\n{summary}")

  def on_unmount(self):
    """Stop the matrix when the screen goes away.

    The runner launches up to three child rti_doctor observers, each of which
    joins the domain being diagnosed. Leaving them running would keep observing
    - and would let a second press of `x` put two matrices on one domain, each
    seeing the other's traffic. `start_new_session` in `_run_matrix` is what
    makes one signal reach the whole tree rather than just bash.
    """
    self._stop_matrix()

  def _stop_matrix(self):
    process = self.process
    self.process = None
    if process is None or process.poll() is not None:
      return
    try:
      os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError) as error:
      logging.warning(f"[matrix] could not stop the runner: {error}")
      return
    try:
      process.wait(timeout=MATRIX_STOP_GRACE)
    except subprocess.TimeoutExpired:
      # A probe wedged in a Connext call will not return on SIGTERM; the run is
      # already abandoned, so do not leave the observers on the domain.
      try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
      except (OSError, ProcessLookupError):
        pass

  def action_back(self):
    self.app.pop_screen()

  def action_quit_app(self):
    self.app.exit()


class ReportScreen(Screen):
  """Findings for one endpoint or participant."""

  BINDINGS = [
      ("b", "back", "Back"),
      ("escape", "back", "Back"),
      ("p", "probe", "Probe endpoint"),
      ("w", "verify_delivery", "Publish to verify delivery"),
      ("x", "compatibility_matrix", "Cross-vendor compatibility"),
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
    self.scrolls = {}
    self.body = None
    self.status = None
    self.capturing = False
    self.probing = False
    # A capture picker of this screen's is open. Neither `probing` nor
    # `capturing` is set while it waits for an answer, so without this a second
    # offer stacks a second picker - and the answer discarded with it still
    # calls `record_capture_choice`, changing the interface the session
    # remembers, and replaces the pass announcement with a refusal.
    self.asking = False
    # The operator pressed `p`. Distinct from `probe`, which says this report
    # probes: the request survives a refusal, the capability does not.
    self.probe_requested = False
    # The Data tab's live feed. Open only while that tab is the active one; see
    # `on_tabbed_content_tab_activated`, which is also what closes it.
    self.live = None
    self.live_samples = collections.deque(maxlen=LIVE_SAMPLE_HISTORY)
    self.live_timer = None
    self.live_note = ""
    # The header as last drawn, so a poll that brings nothing can still tell
    # whether anything it would say has changed.
    self.live_shown = ""

  def check_action(self, action, parameters):
    """Hide inapplicable controls from the footer and keymap.

    The footer is the only place the keymap is documented, so an action it
    advertises has to be one this report will actually run - otherwise `x` is
    offered on a participant or an RTI writer and answers with a refusal.
    """
    del parameters
    if action == "probe":
      return self.endpoint is not None
    if action == "verify_delivery":
      # `self.probe` too: `action_verify_delivery` refuses a report that never
      # probed, because there is no probe writer to publish from. Without it the
      # footer advertised `w` on every passive reader report and answered with a
      # refusal - and `refresh_bindings()` in `action_probe` had nothing to
      # refresh, so the key stayed hidden after `p` made it real.
      return bool(self.endpoint is not None and not self.endpoint.is_writer
                  and self.probe)
    if action == "compatibility_matrix":
      return self._compatibility_applies()
    return True

  def _compatibility_applies(self):
    """Whether the isolated cross-vendor matrix has a target on this report.

    Any readable non-RTI writer. The gate used to be Fast DDS alone, which hid
    the key on a Cyclone or OpenDDS writer - the peers the experiments are most
    useful against - even though the runner does nothing Fast DDS-specific and
    the profiles it tries are properties of THIS observer.
    """
    return bool(self.endpoint is not None and self.endpoint.is_writer
                and vendors.is_foreign(getattr(self.endpoint, "vendor_id", None)))

  def compose(self):
    yield Header()
    # `markup=False` here and on the tab bodies below, and it is the whole
    # markup policy for this screen: everything either widget shows is
    # generated - report text, sample payload, peer names, exception and tshark
    # messages - and none of it is ours to interpret. A field or a message
    # holding "[/]" would otherwise raise out of the update, and one holding
    # "[red]" would silently delete the rest of its line. Set here rather than
    # escaped at 27 call sites, because that is how one escaped line ended up
    # beside an unescaped one.
    self.status = Static("Running static checks...", id="report_status",
                         markup=False)
    yield self.status
    with TabbedContent(id="report_tabs"):
      # Data sits next to Probe because it is what the probe received. Every
      # id here must have a section in `render_view_sections`, and vice versa:
      # `_update_sections` indexes `bodies` by that function's keys.
      for tab_id, title in (("overview", "Overview"), ("findings", "Findings"),
                            ("type", "Type"), ("probe", "Probe"),
                            ("data", "Data"), ("wire", "Wire"),
                            ("config", "Configuration")):
        with TabPane(title, id=tab_id):
          scroll = VerticalScroll(classes="report_body")
          self.scrolls[tab_id] = scroll
          with scroll:
            body = Static("", markup=False)
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
    # `p` is live while the static pass above is awaited, so the operator may
    # already have started their own pass - or be answering its capture picker.
    # Offering again here would report their pass as "started from another
    # report" and overwrite its announcement, or stack a second picker.
    if self.probing or self.capturing or self.asking:
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

  def _compatibility_hint_text(self):
    """Advertise the opt-in matrix only where it applies."""
    if not self._compatibility_applies():
      return ""
    vendor = vendors.vendor_name(getattr(self.endpoint, "vendor_id", None))
    return (f" {vendor} writer detected: press x to run isolated default/V2, "
            "vendor/V2, and vendor/V1 compatibility profiles.")

  def _offer_full_pass(self):
    """Run the full diagnostic on entry, asking about capture the first time.

    The order matters. A participant report has nothing to probe or capture; a
    report opened with `probe=False` asks for neither and stays a
    keypress-cheap screen; an unanswered capture question is asked before
    anything runs, because the capture has to start before the probe.
    """
    if self.endpoint is None:
      self.status.update(
          "Static checks complete (participant report: no probe, no packet "
          "capture).")
      return
    compatibility_hint = self._compatibility_hint_text()
    if not (self.probe or self.probe_requested):
      created = "reader" if self.endpoint.is_writer else "writer"
      self.status.update(
          "Static checks complete (opened without probing, so nothing has "
          f"touched the system). Press p to probe this endpoint: it creates a "
          f"matching {created}, samples its statuses, and offers a packet "
          "capture first." + compatibility_hint)
      return
    if self.session.pass_in_flight():
      self.status.update(
          "A diagnostic pass started from another report is still finishing. "
          "Press p to probe once it has." + compatibility_hint)
      return
    if self.session.capture_off_reason:
      self._begin_pass(None)
      return
    if not self.session.capture_choice_made:
      if self.asking:
        return
      self.asking = True
      self.status.update(
          "Choose where to capture RTPS packets for the full diagnostic, or "
          f"{SKIP_CAPTURE} to probe without capturing.")
      self.app.push_screen(CaptureInterfaceScreen(
          self.session, self._answer_capture,
          on_dismiss=lambda: self._answer_capture(None, dismissed=True)))
      return
    # An answer already exists, which may be a remembered Skip (None).
    self._begin_pass(self.session.capture_interface)

  def _answer_capture(self, interface, dismissed=False):
    """The picker's answer, which is also what closes the asking window."""
    self.asking = False
    self._begin_pass(interface, dismissed=dismissed)

  def _begin_pass(self, interface, dismissed=False, write_samples=False):
    """Start one combined probe+capture pass. The only path that runs either."""
    # The picker is a screen, so it can outlive the report that pushed it, and
    # a pass can have started elsewhere while it was open. `is_current` rather
    # than `is_mounted`: this is also reached from `on_mount`, where a screen
    # does not yet count as mounted.
    if not self.is_current:
      return
    if not self._capture_allowed():
      return
    # The request becomes the capability here, at the one place a pass starts.
    if self.probe_requested:
      self.probe_requested = False
      self.probe = True
      # Textual caches which bindings are active, and `w` is gated on this
      # report probing - without this the reader-target key stays hidden until
      # the screen is rebuilt.
      self.refresh_bindings()
    probing = self.probe and self.endpoint is not None
    if not probing and not interface:
      self.status.update("Nothing to run: this report does not probe, and no "
                         "capture interface was chosen.")
      return
    seconds = (self.session.probe_timeout if probing
               else engine_mod.DEFAULT_CAPTURE_SECONDS)
    destination = (os.path.abspath(self.session.capture_path())
                   if interface else None)
    # Said before tshark is spawned, not after it returns: what is being
    # collected, from where, for how long, and what it leaves on disk.
    self.status.update(
        self._pass_announcement(interface, probing, seconds, destination,
                                dismissed, write_samples))
    # One subscription at a time on this topic. A live feed running through a
    # probe is load the probe is trying to measure, and its frames would land in
    # that pass's capture as if they were the application's.
    self._stop_live()
    self.probing, self.capturing = probing, bool(interface)
    # The feed was closed above so the pass has the topic to itself. Say which
    # of the two it is: `_stop_live` leaves "select this tab again to reopen",
    # which is wrong for the whole length of a pass that will hand the feed back
    # on its own - and selecting the tab now would only earn a refusal.
    if self._data_tab_active():
      self.live_note = ("This report's diagnostic pass is running. The live "
                        "feed starts when it finishes.")
      self._render_live()
    # Claimed for the window tshark itself is bounded by, so a claim nobody
    # releases expires no later than the capture it was protecting.
    self.session.claim_pass(seconds + engine_mod.CAPTURE_DURATION_MARGIN)
    # run_worker, not asyncio.create_task: a bare task is only weakly
    # referenced by the loop and nothing cancels it when the screen is popped,
    # so a pass left running would write into unmounted widgets seconds after
    # the operator navigated away.
    self.run_worker(self._run_pass(probing, seconds, destination, interface,
                                   write_samples),
                    exit_on_error=False)

  def _pass_announcement(self, interface, probing, seconds, destination,
                         dismissed=False, write_samples=False):
    """What is about to run, said before it runs. Pure, so it can be tested.

    The result text can be intercepted on the status widget, but the entry
    announcement cannot: it is written during `on_mount`, before a test can
    install a recorder.
    """
    topic = self.endpoint.topic_name
    # A reader probe creates a DataWriter that publishes only when the operator
    # approved it. Promising frames otherwise would be a lie the Wire tab then
    # contradicts, and claiming an injection that was declined would be worse.
    probe_text = (
        f"probing for up to {seconds:.0f}s, creating a "
        f"{'reader' if self.endpoint.is_writer else 'writer'} and sampling "
        f"statuses")
    if write_samples:
      probe_text += (f", then PUBLISHING up to "
                     f"{probe_mod.PROBE_SAMPLE_COUNT} synthetic sample(s) to "
                     f"'{topic}' as approved - the subscribed application will "
                     f"receive them")
    if self.session.network_capture:
      probe_text += (", with RTI Network Capture recording this participant's "
                     "own frames including shared memory")
    if interface:
      return (f"Full diagnostic on '{topic}': capturing RTPS packets on "
              f"'{interface}' for {seconds:.0f}s, writing {destination} (and a "
              f".tshark.log beside it)"
              + (f", while {probe_text}. " if probing else ". ")
              + "Capture needs packet-capture privileges on this host.")
    if self.session.capture_off_reason:
      return (f"Packet capture is off for this session: "
              f"{_short(self.session.capture_off_reason)}. Now {probe_text} on "
              f"'{topic}'.")
    if dismissed:
      return (f"No interface chosen, so nothing is being captured. Now "
              f"{probe_text} on '{topic}'. The next report will ask again; "
              "choose an interface when opening it.")
    return (f"Full diagnostic on '{topic}' without packet capture "
            f"({SKIP_CAPTURE} is remembered for this session): {probe_text}. "
          "The capture choice remains in effect for this session.")

  async def _run_pass(self, probing, seconds, destination, interface,
                      write_samples=False):
    """One `diagnose_endpoint` call for both halves.

    The engine already starts the capture before the probe, which is the whole
    reason these cannot be two calls: a capture on a probed endpoint has
    nothing to observe unless it is the thing that drives the probe.
    """
    def work():
      try:
        return self.session.diagnose_endpoint(
            self.endpoint, probe=probing, capture_interface=interface,
            capture_seconds=seconds, capture_path=destination,
            write_samples=write_samples)
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
      # The pass is over, so the topic is free again. Reopen the feed if the
      # operator is sitting on the Data tab - including after a failure, where
      # a live stream is often the most useful thing left.
      self._start_live_if_active()

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
        return f"{reason} Packet capture is now off for this session.{tail}"
      return f"{reason}{tail}"
    # Name what was parsed, not just how many frames matched. A capture can
    # yield the peer's product version while matching zero user-data frames,
    # and the count alone reported that as nothing.
    return (f"{'Full diagnostic' if probing else 'Capture'} complete: "
            f"{report_mod.capture_headline(self.data)}. Written to {source}. "
            f"See Overview for what the capture added, Wire for the full "
            f"counts. {self.data.verdict}")

  def action_probe(self):
    """Probe an endpoint whose report was opened without probing.

    Passive is the right default for these reports and stays the default: a
    report reached from an issue, from `o`, or from the endpoint picker creates
    no entity and asks no question, because arriving on a screen must never be
    what starts a probe. What was missing was the way out of it. The operator
    who did want a probe had to leave and reopen the endpoint from a screen that
    probes on entry - and the issue path has no such screen, so the writer an
    issue names could not be probed at all without first finding it again by
    hand in Browse.

    This runs the same single pass the probing entry path runs, capture question
    included: the question comes first because a capture has to be recording
    before the probe it exists to observe.
    """
    if self.endpoint is None:
      self.status.update("Probing needs an endpoint; this is a participant "
                         "report.")
      return
    if self.probing or self.capturing:
      # This report's own pass, which `_offer_full_pass` would have reported as
      # "started from another report" - and it would have overwritten the
      # announcement naming the interface, the duration and the capture file.
      self.status.update("This report's diagnostic pass is already running.")
      return
    if self.asking:
      self.status.update("Answer the capture question first.")
      return
    # `probe` is set by `_begin_pass`, where a pass actually starts - not here.
    # `_offer_full_pass` can still refuse (another report's pass), and setting
    # the flag before finding out told the rest of the screen this report probes
    # when nothing ran: enough to unlock `w` and reach the publish consent from
    # a report with no probe behind it.
    self.probe_requested = True
    self._offer_full_pass()

  def action_verify_delivery(self):
    """Prove delivery to a discovered reader, with consent, by publishing to it.

    Only offered for a READER target. A writer target needs nothing of the sort:
    it is already publishing, and the probe verifies delivery by reading what it
    sends. Writing to a writer's topic would inject data to answer a question
    that was already answered without it.
    """
    if self.endpoint is None:
      self.status.update("Publishing needs an endpoint; this is a participant "
                         "report.")
      return
    if self.endpoint.is_writer:
      self.status.update(
          "This endpoint is a writer, so publishing verification is not "
          "available for it.")
      return
    if not self.probe:
      self.status.update(
          "This report was opened without probing, so there is no probe writer "
          "to publish from. Press p to probe first, then w to verify delivery.")
      return
    if self.session.pass_in_flight():
      self.status.update("A diagnostic pass is still finishing; try again when "
                         "it is done.")
      return
    self.app.push_screen(PublishConsentScreen(self.endpoint, self._begin_write_pass))

  @staticmethod
  def _matrix_runner_path():
    return os.path.join(paths.TOOL_ROOT, "run_version_matrix.sh")

  def _compatibility_command(self, output_dir):
    """Fresh-process cross-vendor matrix command for this writer's topic."""
    # `settle` is the interactive session's discovery settle, tuned for a local
    # RTI peer; a cross-vendor child run needs at least the runner's own
    # default or its preflight topic check can fire before the writer is seen.
    settle = max(float(getattr(self.session, "settle", 0.0)), MATRIX_MIN_SETTLE)
    return ["bash", self._matrix_runner_path(),
            "--domain", str(self.session.domain_id), "--topic", self.endpoint.topic_name,
            "--settle", str(settle),
            "--type-wait", str(self.session.type_wait),
            "--probe-timeout", str(self.session.probe_timeout),
            "--output-dir", output_dir]

  def action_compatibility_matrix(self):
    """Run isolated TypeObject/mask experiments against a non-RTI writer."""
    if self.endpoint is None or not self.endpoint.is_writer:
      self.status.update("Compatibility experiments apply to a selected writer.")
      return
    vendor_id = getattr(self.endpoint, "vendor_id", None)
    if vendors.is_rti_family(vendor_id):
      self.status.update(
          f"This is an {vendors.vendor_name(vendor_id)} writer; no cross-vendor "
          "matrix is needed.")
      return
    if not vendors.is_foreign(vendor_id):
      # `is_foreign` refuses an unreadable id and a stated 00.00 alike, and its
      # own docstring insists those are different: one is "we could not tell",
      # the other is the peer saying "no vendor". Naming the wrong one points at
      # the wrong remedy.
      octets = vendors.vendor_octets(vendor_id)
      self.status.update(
          "This writer states RTPS VENDORID_UNKNOWN (00.00), which names no "
          "vendor, so there is no cross-vendor claim for the matrix to test."
          if octets == vendors.VENDORID_UNKNOWN else
          "This writer's RTPS vendor id could not be read, so there is no "
          "cross-vendor claim for the matrix to test.")
      return
    if self.probing or self.session.pass_in_flight():
      self.status.update("Wait for the current diagnostic pass to finish before running the matrix.")
      return
    # Say the runner is missing here rather than letting bash report it into the
    # matrix screen's output pane, where it reads as a matrix that found nothing.
    runner = self._matrix_runner_path()
    if not os.path.isfile(runner):
      self.status.update(
          f"The compatibility matrix runner is missing: {runner}")
      return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = paths.test_output_path(
        "cross_vendor_compatibility", f"{self.session.domain_id}_{stamp}")
    command = self._compatibility_command(output_dir)
    self.app.push_screen(CompatibilityMatrixScreen(
        command, output_dir, vendor=vendors.vendor_name(vendor_id)))

  def _begin_write_pass(self, approved):
    """Re-run the pass, publishing only if the operator said to."""
    if not self.is_current:
      return
    if not approved:
      self.status.update(
          "Declined - nothing was published. The report still shows the match "
          "and the reliable handshake from the probe writer's own counters.")
      return
    self._begin_pass(self.session.capture_interface, write_samples=True)

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

  # --- The Data tab's live feed ----------------------------------------------

  def on_tabbed_content_tab_activated(self, event):
    """Open a reader on entering the Data tab; close it on leaving.

    The tab selection IS the operator's request here, which is why this is the
    one place in the report that creates a DDS entity without a keypress. It
    stays honest because the same event closes it: there is no way to be reading
    a topic and not be looking at the tab that says so.
    """
    active = getattr(event.tabbed_content, "active", None)
    if active == "data":
      self._start_live()
    else:
      self._stop_live()

  def on_screen_suspend(self):
    """Another screen went on top, so nothing is watching this feed.

    A suspended report is not an unmounted one - without this the reader would
    keep taking samples behind the capture picker or the matrix screen, which is
    exactly the invisible subscription this design is meant not to have.
    """
    self._stop_live()

  def on_screen_resume(self):
    self._start_live_if_active()

  def on_unmount(self):
    self._stop_live()

  def _start_live_if_active(self):
    """Start only when Data is the tab actually on screen.

    `is_current` first: this is reached from a pass's `finally`, which can run
    after the operator navigated away and `on_unmount` already closed the feed.
    Opening one there would leak the one reader in this tool that nothing else
    is going to close.
    """
    if self._data_tab_active():
      self._start_live()

  def _data_tab_active(self):
    """Is the Data tab the one on screen right now?

    `app.screen is self`, NOT `is_current`: measured on this Textual, a screen
    with another one pushed on top still reports `is_current` True, so that test
    would have reopened the feed behind the capture picker when a pass finished
    under it - the invisible subscription this design exists not to have. One
    try around the whole check because a caller can be a pass's `finally`, and
    both `app` and `query_one` reach for state a torn-down screen no longer has;
    raising there would surface as a worker error for a screen nobody is looking
    at.
    """
    try:
      if self.app.screen is not self:
        return False
      tabs = self.query_one("#report_tabs", TabbedContent)
    except Exception:
      return False
    return getattr(tabs, "active", None) == "data"

  def _start_live(self):
    """Open the feed's reader, or say why there will not be one.

    Never raises into the event loop: a Data tab that cannot stream has to keep
    being a readable tab, so a failure here becomes a line in the body.
    """
    if self.live is not None:
      return
    refusal = livedata.why_not(self.endpoint)
    if refusal is not None:
      self.live_note = refusal
      self._render_live()
      return
    # One thing at a time on a topic, as everywhere else here: an extra
    # subscription during a probe is load the probe is trying to measure, and
    # its frames would land in that pass's capture.
    if self.probing or self.capturing:
      # This report's own pass, and its `finally` is what hands the feed back.
      self.live_note = ("This report's diagnostic pass is running. The live "
                        "feed starts when it finishes.")
      self._render_live()
      return
    if self.session.pass_in_flight():
      # Another report's pass, which will never call back here. Promising a
      # restart would leave a dead tab waiting for an event that cannot arrive.
      self.live_note = ("A diagnostic pass started from another report is "
                        "still running. Select this tab again once it has "
                        "finished.")
      self._render_live()
      return
    try:
      # Same isolation setting as the probe, from the same session: the Data
      # tab and the Probe tab describe one endpoint, and if one of them
      # excluded the topic's other writers while the other did not, the two
      # would disagree about whether that endpoint delivers anything.
      self.live = livedata.LiveSubscription(
          self.session.participant, self.endpoint,
          isolate=self.session.isolate_probe,
          domain_id=self.session.domain_id,
          type_object_v1_only=self.session.type_object_v1_only)
    except Exception as error:
      logging.error(f"[ReportScreen] live feed could not start: {error}")
      self.live_note = f"The live feed could not create a reader: {error}"
      self._render_live()
      return
    self.live_samples.clear()
    self.live_note = ""
    self.live_timer = self.set_interval(LIVE_POLL_SECONDS, self._pump_live)
    self._render_live()

  def _stop_live(self):
    """Close the feed's reader and stop polling. Idempotent."""
    timer, self.live_timer = self.live_timer, None
    if timer is not None:
      timer.stop()
    live, self.live = self.live, None
    # Cleared with the attempt that produced it. A note is about starting a
    # feed, so a stale one left behind would keep annotating the tab - and one
    # from a transient failure would outlive the failure for as long as the
    # report is open.
    had_note, self.live_note = bool(self.live_note), ""
    if live is not None or had_note:
      # The samples stay on screen; what is gone is the reader behind them, and
      # the header has to stop claiming a stream that has been closed.
      if live is not None:
        live.close()
      self._render_live()

  def _pump_live(self):
    if self.live is None:
      return
    samples, skipped = self.live.poll()
    if self.live.errors >= LIVE_ERROR_LIMIT:
      self._fail_live(f"The live reader stopped after "
                      f"{self.live.errors} failed reads: "
                      f"{self.live.last_error}")
      return
    # Redrawn for a changed header as well as for arrivals. `skipped` is one
    # reason - a silent target on a busy topic, where the other-writer count is
    # the only thing distinguishing "nothing is being published" from "nothing
    # is being published BY THIS WRITER". Correlation is the other: it is
    # unknown until the first poll resolves it, so a header rendered before any
    # poll carries the topic-wide caveat and would keep carrying it for a writer
    # that never sends.
    if not samples and not skipped and self._live_header() == self.live_shown:
      return
    self.live_samples.extend(samples)
    self._render_live()

  def _fail_live(self, reason):
    """Close a feed that cannot read, and say why instead of showing silence."""
    self._stop_live()
    self.live_note = reason
    self._render_live()

  def _render_live(self):
    """Redraw the Data body from the feed, and follow the tail."""
    body = self.bodies.get("data")
    if body is None:
      return
    self.live_shown = self._live_header() if self.live is not None else ""
    scroll = self.scrolls.get("data")
    # Whether to follow the tail is decided BEFORE the update, from where the
    # operator had scrolled to. Following unconditionally meant a writer sending
    # every 200ms yanked the view back to the bottom five times a second, so the
    # 200-sample window it keeps could not actually be read.
    following = self._live_following(scroll)
    body.update("\n".join(self._live_lines()))
    if scroll is not None and self.live is not None and following:
      try:
        scroll.scroll_end(animate=False)
      except Exception:
        # Scrolling is a nicety; a feed that raised here would stop updating.
        pass

  @staticmethod
  def _live_following(scroll):
    """Was the view at the bottom, i.e. reading the newest arrivals?

    True when there is nothing to scroll yet, so a feed that has just opened
    starts by following. Any failure reading the offsets also answers True: the
    tail is the useful default, and this is a nicety either way.
    """
    if scroll is None:
      return True
    try:
      furthest = scroll.max_scroll_y
      if furthest <= 0:
        return True
      # A line of slack, so a view resting one row short still follows.
      return scroll.scroll_offset.y >= furthest - 1
    except Exception:
      return True

  def _live_lines(self):
    """Header, then every kept sample oldest-first, newest at the bottom."""
    lines = []
    if self.live is not None:
      lines.append(self._live_header())
      lines.append("A reader is open on the type discovery supplied. It closes "
                   "when you leave this tab.")
    elif self.live_samples:
      closed = f"FEED CLOSED - {len(self.live_samples)} sample(s) still shown."
      # The advice belongs to the note whenever there is one. During a pass,
      # "select this tab again" would only earn a refusal - and the pass hands
      # the feed back on its own, which is what the note says instead.
      if not self.live_note:
        closed += " Select this tab again to reopen the reader."
      lines.append(closed)
    if self.live_note:
      lines.append(self.live_note)
    if not self.live_samples:
      if self.live is not None:
        return lines + ["", "Waiting for the first sample..."]
      # No feed and nothing streamed. The probe's own snapshot is the better
      # thing to show than an empty screen - and it goes BELOW any refusal
      # rather than instead of it: a feed that could not start is a reason to
      # read what the probe captured, not a reason to hide it.
      snapshot = (report_mod.render_view_sections(self.data)["data"]
                  if self.data is not None else "")
      return (lines + ["", snapshot]) if snapshot else lines
    for sample in self.live_samples:
      lines.append("")
      lines.append(f"sample {sample.number}  {sample.clock}")
      for line in str(sample.text).splitlines():
        lines.append(f"  {line}")
    return lines

  def _live_header(self):
    """What the feed has seen, including what it is NOT showing.

    `dropped` and `others` are both differences between "the writer sent this"
    and "this is on screen", and a header that reported only the visible count
    would describe this UI's refresh rate as the writer's rate.
    """
    scope = ("" if self.live.correlated
             else " (TOPIC-WIDE: this reader's matched publications could not "
                  "be resolved, so samples are not attributed to this writer)")
    parts = [f"{self.live.received} sample(s) received",
             f"{len(self.live_samples)} shown"]
    if self.live.dropped:
      parts.append(f"{self.live.dropped} arrived faster than the view could "
                   "show and were not kept")
    if self.live.others:
      parts.append(f"{self.live.others} from other writers on this topic")
    return (f"STREAMING '{self.endpoint.topic_name}' - " + ", ".join(parts)
            + scope + self._live_isolation_text())

  def _live_isolation_text(self):
    """What the feed excluded, on the line that says what it is showing.

    The Data tab has no findings section and no appendix, so this header is the
    only place it can say that it narrowed the topic. An operator reading "0
    sample(s) received" has to be able to tell "this writer is silent" from
    "this writer is silent and we ignored the two that are not".
    """
    live = self.live
    if not getattr(live, "isolation_requested", False):
      return ""
    if not getattr(live, "isolated", False):
      return (f" (NOT ISOLATED: {live.isolation_error or 'unknown reason'} - "
              f"every writer on this topic is delivering into this feed)")
    ignored = len(getattr(live, "ignored", ()))
    failed = len(getattr(live, "ignore_failures", ()))
    error = getattr(live, "isolation_error", None)
    # Before the count, not after it. Checking `ignored` first made the failure
    # count unreachable whenever every ignore failed - the header then read
    # "no other writer on this topic to ignore" about a topic whose other
    # writers were all still delivering into this feed.
    if failed or error:
      shortfall = [f"{failed} could NOT be ignored"] if failed else []
      if error:
        shortfall.append("the sweep failed")
      return (f" (isolation INCOMPLETE - {ignored} ignored, "
              f"{'; '.join(shortfall)}: other writers may be live in this feed)")
    if not ignored:
      return " (isolated: no other writer on this topic to ignore)"
    return (f" (isolated: {ignored} other writer(s) on this topic ignored by "
            f"this feed)")

  def _update_sections(self):
    for tab_id, text in report_mod.render_view_sections(self.data).items():
      self.bodies[tab_id].update(text)
    # The feed owns the Data body only while it is OPEN, or while a refusal has
    # something to say about why it is not. Deferring to it for kept samples
    # alone put a closed feed's older arrivals over a fresher probe snapshot -
    # and re-entering the tab clears them anyway.
    if self.live is not None or self.live_note:
      self._render_live()

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
