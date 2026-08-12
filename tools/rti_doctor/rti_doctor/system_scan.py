"""Passive, scoped system scans for the Issues and Topology views."""

from dataclasses import dataclass
from types import MappingProxyType
import time

from . import compat, findings as f, topology, wire
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
  # Finding ids present in this scan that would explain this issue. Context
  # only: the issue is listed and counted either way.
  explained_by: tuple = ()


@dataclass(frozen=True)
class SystemScanSnapshot:
  """One immutable passive scan used by Issues and system-report export."""

  captured_at: float
  topology: object
  issues: tuple
  fastdds_product_versions: tuple = ()


def scan(registry, own_qos, type_lookup_settings, domain_id, active_domains=(),
         domain_scan_ran=False, type_wait=5.0, captured_at=None,
         fastdds_product_versions=(), fastdds_participant_versions=()):
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

  if registry.participant_list():
    findings.extend(_annotate(_connext_note(), "domain"))
    # Routed through _annotate like every other producer in this module. It
    # already sets its own participant-scoped identity, which _annotate's
    # setdefault preserves; going around _annotate is what left this finding
    # with no participant identity at all.
    findings.extend(_annotate(
        _fastdds_version_notes(registry, fastdds_participant_versions),
        "participant"))

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

  censused_topics = set()
  for endpoint in sorted(registry.endpoint_list(), key=lambda item: item.key):
    participant = registry.participant_for(endpoint)
    context = CheckContext(**common, endpoint=endpoint,
                           participant_record=participant)
    # check_extensibility is deliberately absent. It describes how a type is
    # declared, which is the same answer for every endpoint sharing that type -
    # 96 byte-identical entries in the issue list of a 96-endpoint domain - and
    # it describes the IDL rather than anything observed on this system. It
    # runs in targeted diagnosis, where the type map is the point.
    endpoint_checks = [
        static_discovery.check_locators,
        type_compat.check_representation,
    ]
    # The type-name census reads the whole topic, so it needs one endpoint on
    # each topic, not every endpoint: running it per endpoint was an
    # O(endpoints^2) walk that produced one identical finding per endpoint.
    if endpoint.topic_name not in censused_topics:
      censused_topics.add(endpoint.topic_name)
      endpoint_checks.append(type_compat.check_type_name_conflict)
    if endpoint.is_writer:
      # check_type_state is role-aware now, so a reader would no longer be
      # described as a writer. The system census still asks about writers only,
      # deliberately: a topic whose schema never propagates fails at its
      # publisher, and reporting the same unresolved schema again once per
      # subscriber would multiply one condition across the issue list. A
      # reader's own type state is still diagnosed when it is the target of a
      # focused run. Widening the census is a separate decision.
      endpoint_checks.append(type_compat.check_type_state)
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

  ranked = tuple(f.rank(f.link_causes(findings)))
  return SystemScanSnapshot(
      captured_at=captured_at,
      topology=_freeze(topology.snapshot(registry, domain_id, active_domains,
                                          domain_scan_ran)),
      issues=_issues(ranked),
      fastdds_product_versions=tuple(fastdds_product_versions),
  )


def _connext_note():
  """Advise operators running an older tested Connext line."""
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


def _fastdds_version_notes(registry, fastdds_participant_versions=()):
  """One WARN per still-present Fast DDS participant below the tested baseline.

  Three properties this has to hold, each of which it previously did not:

  * The finding declares RUNG_PARTICIPANT, so it must carry the
    `participant_key` the Health column and the `i` filter read. It names the
    participant whose version was observed rather than describing the domain.
  * Two peers on two different out-of-baseline versions are two conditions.
    Identity comes from `participant_key`, which `_issue_key` reads, so they no
    longer collapse into one issue naming whichever version sorted last.
  * A version observed on the wire is evidence about the participant that
    advertised it, not a standing property of the domain. A prefix no longer in
    the registry is dropped, so the WARN stops when that peer departs instead
    of outliving it for the rest of the session.
  """
  by_prefix = {}
  for participant in registry.participant_list():
    prefix = wire.record_guid_prefix(participant)
    if prefix is not None:
      by_prefix.setdefault(prefix, participant)

  notes = []
  for prefix, product_version in sorted(set(
      _version_pairs(fastdds_participant_versions))):
    participant = by_prefix.get(prefix)
    if participant is None:
      # The peer that advertised this version is gone from the registry.
      continue
    parsed = _parse_version(product_version)
    if parsed is None or parsed >= (3, 6, 2):
      continue
    label = participant.name or participant.key
    notes.append(f.Finding(
        id="environment.fastdds_version_older_than_validated",
        rung=f.RUNG_PARTICIPANT,
        severity=f.Severity.WARN,
        title="Fast DDS version is older than the validated baseline",
        observed=(f"RTPS discovery reported Fast DDS {product_version} for "
                  f"participant '{label}'; the validated baseline is 3.6.2."),
        root_cause="This Fast DDS version is older than the version covered by the interoperability fixtures.",
        remedy="Retest with Fast DDS 3.6.2 or newer before relying on the validated interoperability results.",
        evidence={"scope": "participant",
                  "participant_key": participant.key,
                  "fastdds_product_version": product_version,
                  "fastdds_guid_prefix": prefix,
                  "validated_baseline": "3.6.2"},
    ))
  return notes


def _version_pairs(value):
  """Normalize `(guid_prefix, version)` evidence that may arrive as lists."""
  pairs = []
  for item in value or ():
    if isinstance(item, (list, tuple)) and len(item) == 2:
      pairs.append((str(item[0]).replace(":", "").lower(), str(item[1])))
  return pairs


def _parse_version(value):
  """Return a numeric release tuple when RTPS discovery reports one."""
  try:
    return tuple(int(part) for part in str(value).split("."))
  except ValueError:
    return None


def _annotate(findings, scope, endpoint=None, participant=None):
  """Attach stable discovery identity without asking checks to format UI labels.

  A check running in the endpoint loop may widen its own scope to "topic" or
  "participant" - `check_type_name_conflict` describes a topic, and the
  no-locators branch of `check_locators` describes a participant. Endpoint
  identity is then deliberately withheld, because `_issue_key` folds it into the
  issue key: tagging a topic-wide condition with whichever endpoint happened to
  trigger it turns one fault into one duplicate issue per endpoint on the topic.
  """
  annotated = []
  for finding in findings:
    evidence = dict(finding.evidence)
    declared = evidence.setdefault("scope", scope)
    if endpoint is not None and declared == "topic":
      evidence.setdefault("topic_name", endpoint.topic_name)
    elif endpoint is not None and declared == "participant":
      evidence.setdefault("participant_key", endpoint.participant_key)
    elif endpoint is not None:
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
  """Aggregate non-OK findings by deterministic issue identity.

  Every non-OK finding produces an issue. Nothing is filtered by a causal
  guess - a likely cause travels with the issue as `explained_by` instead.
  """
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
        # `linked_*` are the keys a topic- or participant-scoped finding names
        # without claiming them as its own identity. They reach the Health
        # column and the `i` filter, which read these tuples, while staying out
        # of _issue_key - so one topic-wide condition stays one issue and is
        # still reachable from every endpoint it involves.
        writer_keys=_keys(evidence, "writer_key", "linked_writer_keys"),
        reader_keys=_keys(evidence, "reader_key", "linked_reader_keys"),
        participant_keys=_keys(evidence, "participant_key",
                               "writer_participant_key", "reader_participant_key",
                               "linked_participant_keys"),
        evidence=_freeze(evidence),
        explained_by=tuple(sorted({cause for item in grouped_findings
                                   for cause in item.explained_by})),
    ))
  return tuple(sorted(issues, key=lambda item: (-int(item.severity), item.topic_name,
                                                  item.finding_ids, item.key)))


def _keys(evidence, *names):
  """Union of several evidence fields as one sorted, deduplicated tuple."""
  found = ()
  for name in names:
    found += _tuple(evidence.get(name))
  return tuple(sorted(set(found)))


def _issue_key(finding, evidence):
  """Stable identity for one condition, independent of its display text.

  Reads only the singular identity fields. The `linked_*` fields are
  deliberately not read: they exist so a topic-scoped condition can name every
  endpoint it involves without that identity splitting it into one issue per
  endpoint, which is the whole reason topic scope withheld identity before.
  """
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