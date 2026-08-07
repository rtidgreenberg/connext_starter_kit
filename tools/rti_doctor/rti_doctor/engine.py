"""Orchestration: run the right checks for a target and build a ReportData.

Shared by the TUI and the headless modes so both produce identical findings -
a report that differs depending on how it was invoked would be worthless.
"""

import logging
import os
import time
from dataclasses import replace

from . import checks, probe as probe_mod, report, system_scan, topology, vendors, wire
from .checks import CheckContext


class Session:
  """One diagnostic session: a participant, a registry, and our own config."""

  def __init__(self, participant, registry, own_qos, type_lookup_settings,
               domain_id, type_wait=5.0, probe_timeout=10.0,
               active_domains=None, domain_scan_ran=False,
               discovery_capture=None):
    self.participant = participant
    self.registry = registry
    self.own_qos = own_qos
    self.type_lookup_settings = type_lookup_settings or {}
    self.domain_id = domain_id
    self.type_wait = type_wait
    self.probe_timeout = probe_timeout
    self.active_domains = active_domains or set()
    self.domain_scan_ran = domain_scan_ran
    self.discovery_capture = discovery_capture
    self._fastdds_product_versions = ()
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

  # --- Diagnoses -------------------------------------------------------------

  def diagnose_domain(self):
    """Blind-spot audit only: what might we not be seeing at all?"""
    context = self._context()
    return checks.run_checks(context, checks.blind_spot_checks())

  def close_discovery_capture(self):
    """Stop a startup discovery capture that never observed Fast DDS."""
    if self.discovery_capture is not None:
      self.discovery_capture.finish_discovery()
      self.discovery_capture = None

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
    )
    if (self.discovery_capture is not None
        and any(vendors.vendor_name(participant.vendor_id) == vendors.FASTDDS
                for participant in self.registry.participant_list())):
      evidence = self.discovery_capture.finish_discovery()
      self.discovery_capture = None
      self._fastdds_product_versions = tuple(
          evidence.get("fastdds_product_versions", ()))
      if evidence.get("error"):
        logging.warning("[engine] Fast DDS discovery capture unavailable: %s",
                        evidence["error"])
    if self._fastdds_product_versions:
      snapshot = replace(snapshot,
                         fastdds_product_versions=self._fastdds_product_versions)
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

  def diagnose_endpoint(self, endpoint, probe=True, capture_interface=None):
    """Full rungs 0-5 for one endpoint, probing unless told not to."""
    self.registry.expire_type_waits()
    participant_record = self.registry.participant_for(endpoint)

    probe_result = None
    wire_evidence = None
    capture = None
    if probe:
      logging.info(f"[engine] probing topic '{endpoint.topic_name}'")
      if capture_interface:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        capture = wire.LiveCapture(
            capture_interface,
            os.path.join("test_output", "rti_doctor_captures",
                         f"rti_doctor_domain{self.domain_id}_{timestamp}.pcapng"),
            wire.capture_filter(self.domain_id, endpoint, self.own_qos),
            writer_entity_id=(wire.endpoint_entity_id(endpoint)
                              if endpoint.is_writer else None),
            writer_guid_prefix=(wire.endpoint_guid_prefix(endpoint)
                                if endpoint.is_writer else None),
            reader_entity_id=(wire.endpoint_entity_id(endpoint)
                              if not endpoint.is_writer else None))
      try:
        if capture is not None:
          capture.start()
        probe_result = probe_mod.probe_endpoint(
            self.participant, endpoint, timeout=self.probe_timeout)
      finally:
        wire_evidence = capture.finish() if capture is not None else None

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
    )

  def sweep(self, progress=None, probe=True):
    """Diagnose every discovered writer. Returns (rows, reports)."""
    self.registry.expire_type_waits()
    writers = sorted(self.registry.writers(), key=lambda e: (e.topic_name, e.key))
    rows = []
    reports = []

    for index, writer in enumerate(writers):
      if progress is not None:
        try:
          progress(index, len(writers), writer)
        except Exception as e:
          logging.debug(f"[engine] sweep progress callback failed: {e}")
      data = self.diagnose_endpoint(writer, probe=probe)
      reports.append(data)
      rows.append(_sweep_row(data, writer))

    if progress is not None:
      try:
        progress(len(writers), len(writers), None)
      except Exception:
        pass
    return rows, reports


def _sweep_row(data, writer):
  from . import findings as f
  active = f.active(data.findings)
  worst = max((finding.severity for finding in active), default=f.Severity.OK)
  return {
      "topic": writer.topic_name or "(unnamed)",
      "vendor": writer.vendor_name,
      "severity": worst.label,
      "verdict": data.verdict,
      "findings": [(finding.id, finding.severity.label, finding.title)
                   for finding in active if finding.is_problem],
      "report": data,
  }


def health_label(data):
  """Short health string for a table cell."""
  from . import findings as f
  active = f.active(data.findings)
  errors = [x for x in active if x.severity >= f.Severity.ERROR]
  if errors:
    return f"x {errors[0].id.split('.')[-1]}"
  warns = [x for x in active if x.severity == f.Severity.WARN]
  if warns:
    return f"! {warns[0].id.split('.')[-1]}"
  return "OK"
