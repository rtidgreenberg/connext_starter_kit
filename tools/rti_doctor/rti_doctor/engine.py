"""Orchestration: run the right checks for a target and build a ReportData.

Shared by the TUI and the headless modes so both produce identical findings -
a report that differs depending on how it was invoked would be worthless.
"""

import logging

from . import checks, probe as probe_mod, report, system_scan, topology
from .checks import CheckContext


class Session:
  """One diagnostic session: a participant, a registry, and our own config."""

  def __init__(self, participant, registry, own_qos, type_lookup_settings,
               domain_id, type_wait=5.0, probe_timeout=10.0,
               active_domains=None, domain_scan_ran=False):
    self.participant = participant
    self.registry = registry
    self.own_qos = own_qos
    self.type_lookup_settings = type_lookup_settings or {}
    self.domain_id = domain_id
    self.type_wait = type_wait
    self.probe_timeout = probe_timeout
    self.active_domains = active_domains or set()
    self.domain_scan_ran = domain_scan_ran

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

  def system_scan(self, captured_at=None):
    """Passive issue/topology snapshot; never creates a diagnostic reader."""
    self.registry.expire_type_waits()
    return system_scan.scan(
        registry=self.registry,
        own_qos=self.own_qos,
        type_lookup_settings=self.type_lookup_settings,
        domain_id=self.domain_id,
        active_domains=self.active_domains,
        domain_scan_ran=self.domain_scan_ran,
        type_wait=self.type_wait,
        captured_at=captured_at,
    )

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

  def diagnose_endpoint(self, endpoint, probe=True):
    """Full rungs 0-5 for one endpoint, probing unless told not to."""
    self.registry.expire_type_waits()
    participant_record = self.registry.participant_for(endpoint)

    probe_result = None
    if probe and endpoint.is_writer:
      logging.info(f"[engine] probing topic '{endpoint.topic_name}'")
      probe_result = probe_mod.probe_endpoint(
          self.participant, endpoint, timeout=self.probe_timeout)

    context = self._context(endpoint=endpoint,
                            participant_record=participant_record,
                            probe_result=probe_result)
    selected = checks.static_checks()
    if probe_result is not None:
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
        topology=self._topology(),
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
