"""Passive, scoped system scans for the Issues and Topology views."""

from dataclasses import dataclass
from types import MappingProxyType
import time

from . import compat, findings as f, topology
from .checks import CheckContext, run_checks
from .checks import blind_spots, qos_match, static_discovery, type_compat


@dataclass(frozen=True)
class SystemIssue:
  """One actionable condition, normalized from one or more findings."""

  key: str
  severity: f.Severity
  finding_ids: tuple
  title: str
  observed: str
  root_cause: str
  recommendation: str
  topic_name: str
  scope: str
  writer_keys: tuple
  reader_keys: tuple
  participant_keys: tuple
  evidence: object
  suppressed_finding_ids: tuple = ()


@dataclass(frozen=True)
class SystemScanSnapshot:
  """One immutable passive scan used by Issues and system-report export."""

  captured_at: float
  topology: object
  issues: tuple
  suppressed_findings: tuple = ()
  wire_evidence: tuple = ()


def scan(registry, own_qos, type_lookup_settings, domain_id, active_domains=(),
         domain_scan_ran=False, type_wait=5.0, captured_at=None):
  """Return one passive system snapshot without creating a diagnostic reader."""
  captured_at = time.time() if captured_at is None else captured_at
  common = dict(
      registry=registry,
      own_qos=own_qos,
      type_lookup_settings=type_lookup_settings or {},
      domain_id=domain_id,
      active_domains=set(active_domains or ()),
      domain_scan_ran=domain_scan_ran,
      type_wait=type_wait,
  )
  findings = []

  findings.extend(_version_notes())

  findings.extend(_annotate(
      run_checks(CheckContext(**common), blind_spots.CHECKS), "domain"))

  for participant in sorted(registry.participant_list(), key=lambda item: item.key):
    context = CheckContext(**common, participant_record=participant)
    participant_checks = (
        static_discovery.check_vendor_identify,
        static_discovery.check_vendor_notes,
        static_discovery.check_transport,
        static_discovery.check_security_mismatch,
        static_discovery.check_partial_configuration,
        static_discovery.check_no_endpoints,
    )
    findings.extend(_annotate(run_checks(context, participant_checks), "participant",
                              participant=participant))

  for endpoint in sorted(registry.endpoint_list(), key=lambda item: item.key):
    participant = registry.participant_for(endpoint)
    context = CheckContext(**common, endpoint=endpoint,
                           participant_record=participant)
    endpoint_checks = [
        static_discovery.check_locators,
        static_discovery.check_no_multicast_locators,
        type_compat.check_type_state,
        type_compat.check_type_name_conflict,
        type_compat.check_extensibility,
        type_compat.check_representation,
    ]
    if endpoint.is_writer:
      endpoint_checks.append(type_compat.check_assignability)
    findings.extend(_annotate(run_checks(context, tuple(endpoint_checks)), "endpoint",
                              endpoint=endpoint, participant=participant))

  # Each writer evaluates every reader on its topic exactly once.
  for writer in sorted(registry.writers(), key=lambda item: item.key):
    context = CheckContext(**common, endpoint=writer,
                           participant_record=registry.participant_for(writer))
    findings.extend(_annotate(run_checks(context, qos_match.CHECKS), "pair",
                              endpoint=writer,
                              participant=registry.participant_for(writer)))

  ranked = f.rank(f.suppress(findings))
  active = tuple(item for item in ranked if item.suppressed_by is None)
  suppressed = tuple(item for item in ranked if item.suppressed_by is not None)
  return SystemScanSnapshot(
      captured_at=captured_at,
      topology=_freeze(topology.snapshot(registry, domain_id, active_domains,
                                          domain_scan_ran)),
      issues=_issues(active),
      suppressed_findings=suppressed,
  )


def _version_notes():
  """Advise operators running the older supported Connext 7.3 release."""
  version = compat.version_tuple()
  if version is None or version[:2] != (7, 3):
    return []
  return [f.Finding(
      id="environment.connext_7_3_upgrade",
      rung=f.RUNG_OWN_CONFIG,
      severity=f.Severity.INFO,
      title="Connext 7.3 is in use",
      observed=f"Detected Connext {compat.connext_version()}.",
      root_cause="This scan is running against the older supported Connext 7.3 line.",
      remedy="Plan an upgrade to Connext 7.7 for current fixes and capabilities.",
      evidence={"connext_version": compat.connext_version()},
  )]


def _annotate(findings, scope, endpoint=None, participant=None):
  """Attach stable discovery identity without asking checks to format UI labels."""
  annotated = []
  for finding in findings:
    evidence = dict(finding.evidence)
    evidence.setdefault("scope", scope)
    if endpoint is not None:
      evidence.setdefault("endpoint_key", endpoint.key)
      evidence.setdefault("participant_key", endpoint.participant_key)
      evidence.setdefault("topic_name", endpoint.topic_name)
      if endpoint.is_writer:
        evidence.setdefault("writer_key", endpoint.key)
        evidence.setdefault("writer_participant_key", endpoint.participant_key)
      else:
        evidence.setdefault("reader_key", endpoint.key)
        evidence.setdefault("reader_participant_key", endpoint.participant_key)
    elif participant is not None:
      evidence.setdefault("participant_key", participant.key)
    finding.evidence = evidence
    annotated.append(finding)
  return annotated


def _issues(findings):
  """Aggregate active non-OK findings by deterministic issue identity."""
  grouped = {}
  for finding in findings:
    if finding.severity == f.Severity.OK:
      continue
    evidence = finding.evidence or {}
    key = _issue_key(finding, evidence)
    grouped.setdefault(key, []).append(finding)

  issues = []
  for key, grouped_findings in grouped.items():
    primary = f.rank(grouped_findings)[0]
    evidence = primary.evidence or {}
    issues.append(SystemIssue(
        key=key,
        severity=max(item.severity for item in grouped_findings),
        finding_ids=tuple(sorted({item.id for item in grouped_findings})),
        title=primary.title,
        observed=primary.observed,
        root_cause=primary.root_cause,
        recommendation=primary.remedy,
        topic_name=str(evidence.get("topic_name", "")),
        scope=str(evidence.get("scope", "domain")),
        writer_keys=_tuple(evidence.get("writer_key")),
        reader_keys=_tuple(evidence.get("reader_key")),
        participant_keys=tuple(sorted(set(_tuple(evidence.get("participant_key")) +
                                          _tuple(evidence.get("writer_participant_key")) +
                                          _tuple(evidence.get("reader_participant_key"))))),
        evidence=_freeze(evidence),
    ))
  return tuple(sorted(issues, key=lambda item: (-int(item.severity), item.topic_name,
                                                  item.finding_ids, item.key)))


def _issue_key(finding, evidence):
  """Stable identity for one condition, independent of its display text."""
  identities = [
      str(evidence.get("writer_key", "")),
      str(evidence.get("reader_key", "")),
      str(evidence.get("endpoint_key", "")),
      str(evidence.get("participant_key", "")),
      str(evidence.get("topic_name", "")),
  ]
  mismatches = evidence.get("mismatches", ())
  policies = sorted(str(item.get("policy", "")) for item in mismatches
                    if isinstance(item, dict))
  return ":".join([finding.id] + identities + policies)


def _tuple(value):
  if value is None or value == "":
    return ()
  if isinstance(value, (list, tuple, set)):
    return tuple(str(item) for item in value if item is not None and item != "")
  return (str(value),)


def _freeze(value):
  if isinstance(value, dict):
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})
  if isinstance(value, (list, tuple, set)):
    return tuple(_freeze(item) for item in value)
  return value