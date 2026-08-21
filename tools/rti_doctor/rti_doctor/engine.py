"""Orchestration: run the right checks for a target and build a ReportData.

Shared by the TUI and the headless modes so both produce identical findings -
a report that differs depending on how it was invoked would be worthless.
"""

import logging
import os
import time

from . import (checks, findings as f, netcapture, paths, probe as probe_mod,
               report, system_scan, topology, wire)
from .checks import CheckContext

#: How long a capture runs when no probe is bounding it - a reader report, or a
#: writer diagnosed with probing off. Short enough that an operator waits for it
#: rather than wondering whether the screen has hung.
DEFAULT_CAPTURE_SECONDS = 8.0

#: Slack between the window a capture is asked to cover and the hard
#: ``-a duration:`` ceiling tshark applies to itself: the one-second startup
#: settle, the four-second settle in `LiveCapture.finish()`, and room for a probe
#: that overruns its timeout. The ceiling is there to end an abandoned capture,
#: not a normal one, so it is deliberately well clear of the expected window.
CAPTURE_DURATION_MARGIN = 15.0


def _type_information_observed(endpoint, discovery_evidence):
  """Whether the capture saw PID_TYPE_INFORMATION from this endpoint's peer.

  Three-valued, and the third value is the point: `None` means no capture
  produced discovery evidence to look in. `False` would say the peer did not
  advertise TypeInformation, which is a claim about the peer - and a report
  saved after `Skip`, or a headless run without `--capture-interface`, would be
  making it having never looked. Both remain falsy, so the remedy text this
  gates is unaffected; only what the finding records about itself changes.
  """
  if not discovery_evidence or discovery_evidence.get("error"):
    return None
  return wire.record_guid_prefix(endpoint) in set(
      discovery_evidence.get("type_information_participants", ()))


class Session:
  """One diagnostic session: a participant, a registry, and our own config."""

  def __init__(self, participant, registry, own_qos, type_lookup_settings,
               domain_id, type_wait=5.0, probe_timeout=10.0, settle=3.0,
               active_domains=None, domain_scan_ran=False,
               capture_interface=None, network_capture=False):
    self.participant = participant
    self.registry = registry
    self.own_qos = own_qos
    self.type_lookup_settings = type_lookup_settings or {}
    self.domain_id = domain_id
    self.type_wait = type_wait
    self.probe_timeout = probe_timeout
    # Carried only so a child process launched from the TUI can inherit the
    # operator's `--settle`; nothing in this session waits on it, because the
    # settle happened before the session existed.
    self.settle = settle
    self.active_domains = active_domains or set()
    self.domain_scan_ran = domain_scan_ran
    # Where a capture listens. Once `capture_choice_made` is set, `None` means
    # "nowhere" - a recorded Skip - rather than "not asked yet".
    self.capture_interface = capture_interface
    # Whether the operator (or `--capture-interface`) has answered the capture
    # question. A report asks on entry only while this is False, so one answer
    # covers the session and navigating between reports does not re-prompt.
    self.capture_choice_made = capture_interface is not None
    # RTI Network Capture, enabled at startup or not at all - `enable()` has to
    # precede every other Connext call, so unlike the tshark capture this can
    # never be turned on from a keypress. When it is on, every probed endpoint
    # report records the probe participant's own frames, shared memory included.
    self.network_capture = network_capture
    # Set by the first capture that fails, which turns capture off for the rest
    # of the session: on a host without capture privileges, every later report
    # would otherwise carry tshark's refusal as its wire evidence.
    self.capture_off_reason = None
    # Single-flight across screens, as a deadline rather than a flag. See
    # `claim_pass`.
    self.pass_deadline = 0.0
    # CAP-1. Every capture written this session, and the subset a saved report
    # cites - a saved report names its capture in Appendix C, so deleting that
    # file would break the report's own citation.
    self.capture_artifacts = []
    self.retained_artifacts = set()
    self._fastdds_product_versions = ()
    self._fastdds_participant_versions = ()
    self._last_scan = None

  # --- Single-flight for the diagnostic pass ---------------------------------

  def claim_pass(self, seconds):
    """Hold the single-flight claim for at most `seconds`.

    Only one combined probe+capture pass may run at a time, and the claim has
    to outlive the screen that took it: workers are not cancelled synchronously
    and `asyncio.to_thread` cannot be cancelled at all, so a report popped
    mid-pass leaves tshark running and a probe sampling. Two passes on one
    topic would each observe the other's traffic.

    A deadline rather than a flag, for the same reason `LiveCapture` takes
    tshark's own ``-a duration:`` ceiling: the holder is not guaranteed to come
    back and release it. A worker cancelled between being scheduled and first
    running executes neither its own `finally` nor the thread's, and a claim
    left set that way would dead-end every later report for the life of the
    session. `release_pass` is still the normal end; the ceiling is the
    backstop, and it is the same ceiling that stops the abandoned tshark - past
    it, there is nothing left running to protect.
    """
    self.pass_deadline = time.monotonic() + seconds

  def release_pass(self):
    """Give up the claim. Idempotent, and safe to call from any thread."""
    self.pass_deadline = 0.0

  def pass_in_flight(self):
    return time.monotonic() < self.pass_deadline

  # --- The capture question --------------------------------------------------

  def record_capture_choice(self, interface):
    """Remember an answer to the capture question: an interface, or Skip.

    `interface=None` is Skip - probe without capturing - and is as much an
    answer as a name is, so it stops the asking too. Also the re-enable path
    after `disable_capture`: choosing again is how an operator says the reason
    no longer applies.
    """
    self.capture_interface = interface
    self.capture_choice_made = True
    self.capture_off_reason = None

  def disable_capture(self, reason):
    """Turn capture off for the session after one failed attempt.

    The harm is report *content*, not the status line: a failed capture attaches
    `wire_evidence={"error": ...}` to every report that tries, which renders as
    a wire-evidence error in reports nobody asked to include one in.
    """
    self.capture_off_reason = reason
    self.capture_interface = None
    self.capture_choice_made = True

  # --- Capture artifacts (CAP-1) ---------------------------------------------

  def retain_capture(self, path):
    """Keep this capture past exit, because a saved report points at it."""
    if path:
      self.retained_artifacts.add(os.path.abspath(path))

  def sweep_capture_artifacts(self):
    """Delete captures no saved report cites; return what was removed.

    Capture is now offered on entry to every endpoint report, so a session spent
    browsing leaves one PCAPNG and one tshark log per report opened (N2/CAP-1).
    `RTI_DOCTOR_KEEP_ARTIFACTS` opts out, matching the fault artifacts in HAR-3.
    Never raises: this runs on the way out, where an unlink that fails must not
    replace the run's real exit code.
    """
    if os.environ.get("RTI_DOCTOR_KEEP_ARTIFACTS"):
      return []
    removed = []
    for path in self.capture_artifacts:
      if os.path.abspath(path) in self.retained_artifacts:
        continue
      # The tshark log is written beside the capture and is only readable
      # against it, so it goes with it rather than outliving it.
      for candidate in (path, f"{path}.tshark.log"):
        try:
          os.remove(candidate)
          removed.append(candidate)
        except FileNotFoundError:
          pass
        except OSError as e:
          logging.error(f"[engine] could not remove {candidate}: {e}")
    return removed

  def _context(self, endpoint=None, participant_record=None, probe_result=None,
               type_information_observed=None, wire_evidence=None,
               participant_evidence=None):
    return CheckContext(
        wire_evidence=wire_evidence,
        participant_evidence=participant_evidence,
        registry=self.registry,
        own_qos=self.own_qos,
        type_lookup_settings=self.type_lookup_settings,
        domain_id=self.domain_id,
        active_domains=self.active_domains,
        domain_scan_ran=self.domain_scan_ran,
        endpoint=endpoint,
        participant_record=participant_record,
        probe=probe_result,
        type_information_observed=type_information_observed,
        type_wait=self.type_wait,
    )

  def _topology(self):
    return topology.snapshot(
        self.registry, self.domain_id, self.active_domains, self.domain_scan_ran)

  def record_wire_discovery(self, evidence):
    """Take packet-only discovery facts from one operator-requested capture.

    Packet evidence used to arrive from a capture started at startup and run
    for the whole session. It now arrives only from a capture the operator
    asked for on one endpoint report, so this is where a bounded capture hands
    its findings to the system scan. Versions accumulate across captures: a
    second capture on another endpoint adds to what the first observed rather
    than replacing it, and `system_scan._fastdds_version_notes` already drops a
    version whose participant has since left, so nothing outlives its peer.
    """
    if not evidence or evidence.get("error"):
      return
    pairs = set(self._fastdds_participant_versions)
    pairs.update(tuple(pair) for pair in evidence.get("fastdds_participant_versions", ())
                 if isinstance(pair, (list, tuple)) and len(pair) == 2)
    versions = set(self._fastdds_product_versions)
    versions.update(evidence.get("fastdds_product_versions", ()))
    if (pairs == set(self._fastdds_participant_versions)
        and versions == set(self._fastdds_product_versions)):
      return
    self._fastdds_participant_versions = tuple(sorted(pairs))
    self._fastdds_product_versions = tuple(sorted(versions))
    # A cached scan predates this evidence and would render the version
    # findings as still unavailable for as long as it stays fresh.
    self._last_scan = None

  # --- Diagnoses -------------------------------------------------------------

  def system_scan(self, captured_at=None, max_age=0.0):
    """Passive issue/topology snapshot; never creates a diagnostic reader.

    A scan is O(endpoints^2) in the topic-census checks, and five TUI screens
    each ask for one. `max_age` lets a screen that is merely being opened reuse
    a recent snapshot; an explicit operator refresh leaves it at 0 and always
    re-scans.
    """
    cached = self._last_scan
    if (max_age > 0 and cached is not None and captured_at is None
        and 0 <= time.time() - cached.captured_at <= max_age):
      return cached

    self.registry.expire_type_waits()
    snapshot = system_scan.scan(
        registry=self.registry,
        own_qos=self.own_qos,
        type_lookup_settings=self.type_lookup_settings,
        domain_id=self.domain_id,
        active_domains=self.active_domains,
        domain_scan_ran=self.domain_scan_ran,
        type_wait=self.type_wait,
        captured_at=captured_at,
        fastdds_product_versions=self._fastdds_product_versions,
        fastdds_participant_versions=self._fastdds_participant_versions,
    )
    self._last_scan = snapshot
    return snapshot

  def diagnose_participant(self, participant_record):
    """Rungs 0-3 for a participant. No probing, so a keypress stays cheap."""
    self.registry.expire_type_waits()
    context = self._context(participant_record=participant_record)
    findings = checks.run_checks(context, checks.static_checks())
    findings += checks.run_checks(context, checks.own_config_checks(),
                                  scope=f.SCOPE_OWN_CONFIG)

    # Roll up the type state of this participant's writers, which is the single
    # most useful per-participant signal cross-vendor.
    writers = [e for e in self.registry.endpoints_for(participant_record.key)
               if e.is_writer]
    for writer in writers:
      sub = self._context(endpoint=writer, participant_record=participant_record)
      findings.extend(checks.run_checks(sub, checks.type_state_checks()))
    return report.ReportData(
        domain_id=self.domain_id,
        scope=f"participant '{participant_record.name or participant_record.key}'",
        all_findings=findings,
        participant=participant_record,
        type_lookup_settings=self.type_lookup_settings,
        topology=self._topology(),
    )

  def capture_path(self, timestamp=None):
    """Where a capture requested now would write its PCAPNG."""
    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    return paths.test_output_path(
        "rti_doctor_captures",
        f"rti_doctor_domain{self.domain_id}_{stamp}.pcapng")

  def participant_capture_path(self, timestamp=None):
    """Where an RTI Network Capture of our own participant would land.

    A distinct name from `capture_path`, not just a distinct extension: the two
    can run in the same pass over the same endpoint, and a report that cited one
    path for two different files would make its own evidence unresolvable.
    """
    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    return paths.test_output_path(
        "rti_doctor_captures",
        f"rti_doctor_participant_domain{self.domain_id}_{stamp}"
        f"{netcapture.CAPTURE_SUFFIX}")

  def diagnose_endpoint(self, endpoint, probe=True, capture_interface=None,
                        capture_seconds=None, capture_path=None,
                        write_samples=False):
    """Full rungs 0-5 for one endpoint, probing unless told not to.

    Capturing packets is a separate request from probing, not a consequence of
    it. A reader report has nothing to probe and is still a legitimate target
    for wire evidence, and a probe must be able to run without spawning a
    privileged capture the operator never asked for - which is what navigating
    to any writer report used to do. `capture_interface` is therefore the only
    thing that starts tshark, and it is only ever passed when someone asked.

    `write_samples` is the same principle one step further out. It reaches only
    the reader-target probe, where verifying delivery means publishing into a
    topic a real application consumes, and it defaults to off so that opening a
    report can never inject data.
    """
    self.registry.expire_type_waits()
    participant_record = self.registry.participant_for(endpoint)

    probe_result = None
    wire_evidence = None
    discovery_evidence = None
    participant_evidence = None
    capture = None
    participant_capture = None
    if capture_seconds is None:
      capture_seconds = self.probe_timeout if probe else DEFAULT_CAPTURE_SECONDS
    if capture_interface:
      # A caller that told the operator where the capture would land passes
      # that path in, so the file named on screen is the file written.
      destination = capture_path or self.capture_path()
      # Recorded before the capture runs, not after: a capture that fails still
      # leaves a tshark log, and one that is abandoned still leaves a file.
      self.capture_artifacts.append(destination)
      capture = wire.LiveCapture(
          capture_interface,
          destination,
          wire.capture_filter(
              self.domain_id, endpoint, self.own_qos,
              # An endpoint that advertises no locators of its own inherits its
              # participant's defaults, which is where Cyclone's user-traffic
              # port is (WIRE-2).
              owner=self.registry.participants.get(endpoint.participant_key)),
          writer_entity_id=(wire.endpoint_entity_id(endpoint)
                            if endpoint.is_writer else None),
          writer_guid_prefix=(wire.endpoint_guid_prefix(endpoint)
                              if endpoint.is_writer else None),
          reader_entity_id=(wire.endpoint_entity_id(endpoint)
                            if not endpoint.is_writer else None),
          duration=capture_seconds + CAPTURE_DURATION_MARGIN)
    # Runs whenever there is a probe to observe, without an interface, an
    # interface prompt or capture privileges: it instruments our own
    # participant rather than a device. A passively opened report still probes
    # nothing, so there is nothing of ours to record.
    if self.network_capture and probe:
      participant_destination = self.participant_capture_path()
      self.capture_artifacts.append(participant_destination)
      participant_capture = netcapture.ParticipantCapture(
          self.participant, participant_destination)

    if probe or capture is not None:
      try:
        if capture is not None:
          capture.start()
        if participant_capture is not None:
          participant_capture.start()
        if probe:
          logging.info(f"[engine] probing topic '{endpoint.topic_name}'")
          probe_result = probe_mod.probe_endpoint(
            self.participant, endpoint, timeout=self.probe_timeout,
            write_samples=write_samples)
        elif capture is not None:
          # Nothing else is holding this capture open, so it needs its own
          # window; finishing immediately would report an empty capture as the
          # endpoint's wire evidence.
          time.sleep(capture_seconds)
      finally:
        if participant_capture is not None:
          # Filtered by the SELECTED endpoint's ids, exactly as the tshark
          # capture is: this file holds only our participant's frames, so the
          # filter is what separates the conversation with this endpoint from
          # our concurrent discovery traffic.
          participant_evidence = participant_capture.finish(
              writer_entity_id=(wire.endpoint_entity_id(endpoint)
                                if endpoint.is_writer else None),
              reader_entity_id=(wire.endpoint_entity_id(endpoint)
                                if not endpoint.is_writer else None))
        if capture is not None:
          wire_evidence = capture.finish()
          # The same file, read for discovery metadata: Fast DDS advertises its
          # product version in SPDP and nothing else can observe it. One
          # capture answers both questions, so asking for wire evidence is not
          # also a reason to run a second tshark.
          #
          # Run for EVERY peer, including RTI. Skipping it on an RTI peer was
          # tried and reverted: this pass is scoped to the capture, not to the
          # selected endpoint, so it is also what supplies the domain-wide Fast
          # DDS version notes in `system_scan._fastdds_version_notes` (about
          # OTHER participants, which an RTI-peer report is as able to observe
          # as any other), Appendix C's announcement block, and the
          # TypeInformation evidence behind `type_information_observed`.
          # Skipping it discarded all three to save two tshark reads.
          #
          # The misattribution that motivated the skip - a Connext report led
          # with a neighbouring Fast DDS participant's version - is a RENDERING
          # question, and it is fixed where it belongs, in
          # `report._peer_fastdds_versions`: the vendor gate and the GUID-prefix
          # narrowing mean an RTI peer's report shows no Fast DDS line at all,
          # whether or not this parse ran.
          discovery_evidence = capture.finish_discovery()
          self.record_wire_discovery(discovery_evidence)

    context = self._context(endpoint=endpoint,
                            participant_record=participant_record,
                probe_result=probe_result,
                type_information_observed=_type_information_observed(
                    endpoint, discovery_evidence),
                wire_evidence=wire_evidence,
                participant_evidence=participant_evidence)
    # Two passes, not one concatenated list, so each finding is stamped with
    # whose reader it is about. They must stay separable all the way to the
    # report: the probe's own reader mirrors the peer it is testing, so it can
    # match and receive data where an application reader provably cannot, and a
    # single list presents those two facts as one contradictory body of evidence.
    findings = checks.run_checks(context, checks.static_checks(),
                                 scope=f.SCOPE_OBSERVED)
    # The third pass, and not part of either above: these read this tool's own
    # participant QoS, which is why an empty observed section can be rti_doctor
    # rather than the system.
    findings += checks.run_checks(context, checks.own_config_checks(),
                                  scope=f.SCOPE_OWN_CONFIG)
    if probe_result is not None:
      probe_selected = (checks.writer_probe_checks()
                        if probe_result.probe_kind == "writer"
                        else checks.probe_checks())
      findings += checks.run_checks(context, probe_selected,
                                    scope=f.SCOPE_PROBE)

    return report.ReportData(
        domain_id=self.domain_id,
        scope=f"topic '{endpoint.topic_name}'",
        all_findings=findings,
        probe_result=probe_result,
        endpoint=endpoint,
        participant=participant_record,
        type_lookup_settings=self.type_lookup_settings,
        topology=self._topology(), wire_evidence=wire_evidence,
        discovery_evidence=discovery_evidence,
        capture_interface=capture_interface,
        participant_evidence=participant_evidence,
    )


def health_label(data):
  """Short health string for a table cell."""
  from . import findings as f
  active = data.findings
  errors = [x for x in active if x.severity >= f.Severity.ERROR]
  if errors:
    return f"x {errors[0].id.split('.')[-1]}"
  warns = [x for x in active if x.severity == f.Severity.WARN]
  if warns:
    return f"! {warns[0].id.split('.')[-1]}"
  return "OK"
