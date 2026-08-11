"""Orchestration: run the right checks for a target and build a ReportData.

Shared by the TUI and the headless modes so both produce identical findings -
a report that differs depending on how it was invoked would be worthless.
"""

import logging
import time

from . import checks, paths, probe as probe_mod, report, system_scan, topology, wire
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


class Session:
  """One diagnostic session: a participant, a registry, and our own config."""

  def __init__(self, participant, registry, own_qos, type_lookup_settings,
               domain_id, type_wait=5.0, probe_timeout=10.0,
               active_domains=None, domain_scan_ran=False,
               capture_interface=None):
    self.participant = participant
    self.registry = registry
    self.own_qos = own_qos
    self.type_lookup_settings = type_lookup_settings or {}
    self.domain_id = domain_id
    self.type_wait = type_wait
    self.probe_timeout = probe_timeout
    self.active_domains = active_domains or set()
    self.domain_scan_ran = domain_scan_ran
    # The interface an explicitly requested capture uses. Nothing starts a
    # capture because this is set; it only says where one would listen.
    self.capture_interface = capture_interface
    self._fastdds_product_versions = ()
    self._fastdds_participant_versions = ()
    self._last_scan = None

  def _context(self, endpoint=None, participant_record=None, probe_result=None):
    return CheckContext(
        registry=self.registry,
        own_qos=self.own_qos,
        type_lookup_settings=self.type_lookup_settings,
        domain_id=self.domain_id,
        active_domains=self.active_domains,
        domain_scan_ran=self.domain_scan_ran,
        endpoint=endpoint,
        participant_record=participant_record,
        probe=probe_result,
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

  def diagnose_endpoint(self, endpoint, probe=True, capture_interface=None,
                        capture_seconds=None, capture_path=None):
    """Full rungs 0-5 for one endpoint, probing unless told not to.

    Capturing packets is a separate request from probing, not a consequence of
    it. A reader report has nothing to probe and is still a legitimate target
    for wire evidence, and a probe must be able to run without spawning a
    privileged capture the operator never asked for - which is what navigating
    to any writer report used to do. `capture_interface` is therefore the only
    thing that starts tshark, and it is only ever passed when someone asked.
    """
    self.registry.expire_type_waits()
    participant_record = self.registry.participant_for(endpoint)

    probe_result = None
    wire_evidence = None
    discovery_evidence = None
    capture = None
    if capture_seconds is None:
      capture_seconds = self.probe_timeout if probe else DEFAULT_CAPTURE_SECONDS
    if capture_interface:
      capture = wire.LiveCapture(
          capture_interface,
          # A caller that told the operator where the capture would land passes
          # that path in, so the file named on screen is the file written.
          capture_path or self.capture_path(),
          wire.capture_filter(self.domain_id, endpoint, self.own_qos),
          writer_entity_id=(wire.endpoint_entity_id(endpoint)
                            if endpoint.is_writer else None),
          writer_guid_prefix=(wire.endpoint_guid_prefix(endpoint)
                              if endpoint.is_writer else None),
          reader_entity_id=(wire.endpoint_entity_id(endpoint)
                            if not endpoint.is_writer else None),
          duration=capture_seconds + CAPTURE_DURATION_MARGIN)
    if probe or capture is not None:
      try:
        if capture is not None:
          capture.start()
        if probe:
          logging.info(f"[engine] probing topic '{endpoint.topic_name}'")
          probe_result = probe_mod.probe_endpoint(
            self.participant, endpoint, timeout=self.probe_timeout)
        elif capture is not None:
          # Nothing else is holding this capture open, so it needs its own
          # window; finishing immediately would report an empty capture as the
          # endpoint's wire evidence.
          time.sleep(capture_seconds)
      finally:
        if capture is not None:
          wire_evidence = capture.finish()
          # The same file, read for discovery metadata: Fast DDS advertises its
          # product version in SPDP and nothing else can observe it. One
          # capture answers both questions, so asking for wire evidence is not
          # also a reason to run a second tshark.
          discovery_evidence = capture.finish_discovery()
          self.record_wire_discovery(discovery_evidence)

    context = self._context(endpoint=endpoint,
                            participant_record=participant_record,
                            probe_result=probe_result)
    selected = checks.static_checks()
    if probe_result is not None:
      if probe_result.probe_kind == "writer":
        from .checks import probe_match
        selected = selected + probe_match.CHECKS
      else:
        selected = selected + checks.probe_checks()
    findings = checks.run_checks(context, selected)

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
