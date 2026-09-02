"""Orchestration: run the right checks for a target and build a ReportData.

Shared by the TUI and the headless modes so both produce identical findings -
a report that differs depending on how it was invoked would be worthless.
"""

import logging
import os
import time

from . import (checks, discovery, findings as f, netcapture, paths,
               probe as probe_mod, report, system_scan, topology, wire)
from .checks import CheckContext

def _type_information_observed(endpoint, discovery_evidence):
  """Whether the capture saw PID_TYPE_INFORMATION from this endpoint's peer.

  Three-valued, and the third value is the point: `None` means no capture
  produced discovery evidence to look in. `False` would say the peer did not
  advertise TypeInformation, which is a claim about the peer - and a report
  saved without a probe, or a headless run, would be making it having never
  looked. Both remain falsy, so the remedy text this
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
               active_domains=None, domain_scan_ran=False, network_capture=False,
               probe_default=True,
               isolate_probe=True, type_object_v1_only=False):
    self.participant = participant
    self.registry = registry
    self.own_qos = own_qos
    self.type_lookup_settings = type_lookup_settings or {}
    self.domain_id = domain_id
    self.type_wait = type_wait
    self.probe_timeout = probe_timeout
    # The interactive default for every endpoint report, regardless of whether
    # the operator reached it from Findings or Topology.
    self.probe_default = probe_default
    # Carried only so a child process launched from the TUI can inherit the
    # operator's `--settle`; nothing in this session waits on it, because the
    # settle happened before the session existed.
    self.settle = settle
    self.active_domains = active_domains or set()
    self.domain_scan_ran = domain_scan_ran
    # Whether each probe runs on its own disposable participant with every other
    # endpoint on the topic ignored. On by default: without it the probe's
    # entity is one of several on the topic, and a competing writer that wins
    # EXCLUSIVE ownership starves the selected one, which the report can only
    # describe as "matched, but no samples were received" - a true sentence that
    # points at the wrong system. See `discovery.create_probe_participant` for
    # why the participant has to be disposable.
    self.isolate_probe = isolate_probe
    # Carried so the disposable probe participant is configured the way the
    # session participant was; discovering types one way and probing another
    # would make the probe's own type resolution incomparable to the report's.
    self.type_object_v1_only = type_object_v1_only
    # RTI Network Capture, enabled at startup or not at all - `enable()` has to
    # precede every other Connext call. When it is on, every probed endpoint
    # report records the probe participant's own frames, shared memory included.
    self.network_capture = network_capture
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

    A deadline rather than a flag because the holder is not guaranteed to come
    back and release it. A worker cancelled between being scheduled and first
    running executes neither its own `finally` nor the thread's, and a claim
    left set that way would dead-end every later report for the life of the
    session. `release_pass` is still the normal end; the deadline is the
    backstop.
    """
    self.pass_deadline = time.monotonic() + seconds

  def release_pass(self):
    """Give up the claim. Idempotent, and safe to call from any thread."""
    self.pass_deadline = 0.0

  def pass_in_flight(self):
    return time.monotonic() < self.pass_deadline

  # --- Capture artifacts (CAP-1) ---------------------------------------------

  def retain_capture(self, path):
    """Keep this capture past exit, because a saved report points at it."""
    if path:
      self.retained_artifacts.add(os.path.abspath(path))

  def sweep_capture_artifacts(self):
    """Delete captures no saved report cites; return what was removed.

    Every probed endpoint report records one participant PCAP.
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
      for candidate in (path,):
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

  def participant_capture_path(self, timestamp=None):
    """Where an RTI Network Capture of our own participant would land.

    One network capture is produced for each probe.
    """
    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    return paths.test_output_path(
        "rti_doctor_captures",
        f"rti_doctor_participant_domain{self.domain_id}_{stamp}"
        f"{netcapture.CAPTURE_SUFFIX}")

  def diagnose_endpoint(self, endpoint, probe=True, write_samples=False):
    """Full rungs 0-5 for one endpoint, probing unless told not to.

    A probe records its own traffic through RTI Network Capture when enabled.
    `write_samples` reaches only
    the reader-target probe, where verifying delivery means publishing into a
    topic a real application consumes, and it defaults to off so that opening a
    report can never inject data.
    """
    self.registry.expire_type_waits()
    participant_record = self.registry.participant_for(endpoint)

    probe_result = None
    participant_evidence = None
    discovery_evidence = None
    participant_capture = None
    # The probe's own participant, and the reason it may differ from ours.
    # `ignore_datawriter` / `ignore_datareader` have no inverse and last for the
    # life of the participant, so isolation is only ever applied to one we are
    # about to throw away. If it cannot be created the probe still runs - on the
    # shared participant, un-isolated - and `isolation_error` is what makes the
    # report say that rather than imply an isolation it never got.
    probe_participant = self.participant
    scoped_participant = None
    isolation_error = None
    if probe and self.isolate_probe:
      try:
        scoped_participant = discovery.create_probe_participant(
            self.domain_id, type_object_v1_only=self.type_object_v1_only)
        probe_participant = scoped_participant
      except Exception as error:
        isolation_error = (f"could not create the disposable probe participant, "
                           f"so nothing was ignored: "
                           f"{type(error).__name__}: {error}")
        logging.error(f"[engine] {isolation_error}")

    # Runs whenever there is a probe to observe, without an interface, an
    # interface prompt or capture privileges: it instruments our own
    # participant rather than a device. A passively opened report still probes
    # nothing, so there is nothing of ours to record.
    if self.network_capture and probe:
      participant_destination = self.participant_capture_path()
      self.capture_artifacts.append(participant_destination)
      # `probe_participant`, not `self.participant`. Network Capture is scoped
      # to one participant, and once the probe moved onto a disposable one this
      # file would otherwise hold the session participant's discovery chatter
      # and none of the conversation the report is about.
      participant_capture = netcapture.ParticipantCapture(
          probe_participant, participant_destination)

    if probe:
      try:
        if participant_capture is not None:
          participant_capture.start()
        if probe:
          logging.info(f"[engine] probing topic '{endpoint.topic_name}'")
          probe_result = probe_mod.probe_endpoint(
            probe_participant, endpoint, timeout=self.probe_timeout,
            write_samples=write_samples,
            isolate=scoped_participant is not None,
            isolation_error=isolation_error)
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
          if not participant_evidence.get("error"):
            discovery_evidence = wire.inspect_discovery_pcap(
                participant_evidence["source"])
            self.record_wire_discovery(discovery_evidence)
        # Last, and after `participant_capture.finish()` above: that call stops
        # a Network Capture scoped to this very participant. Closing it is also
        # what makes the probe's ignores expire, so nothing here may skip it -
        # a leaked probe participant would keep ignoring the peers it isolated
        # for the rest of the session, which is the exact failure the
        # disposable participant exists to prevent.
        if scoped_participant is not None:
          try:
            scoped_participant.close()
          except Exception as error:
            logging.error(f"[engine] error closing the probe participant: {error}")

    context = self._context(endpoint=endpoint,
                            participant_record=participant_record,
                probe_result=probe_result,
          type_information_observed=_type_information_observed(
            endpoint, discovery_evidence),
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
        topology=self._topology(),
        discovery_evidence=discovery_evidence,
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
