"""Rung 4 checks: did the reader match, and if not, which policy blocked it?"""

from .. import compat
from ..findings import RUNG_MATCH, Finding, Severity

#: RxO rules in plain English, keyed by the substring Connext reports in
#: last_policy. Stated as the rule the reader must satisfy, since the reader is
#: the side that drives matching. Keys may overlap - see _policy_rule.
RXO_RULES = {
    "RELIABILITY": ("A RELIABLE reader cannot match a BEST_EFFORT writer. The "
                    "reader may request BEST_EFFORT from a RELIABLE writer, but "
                    "not the reverse."),
    "DURABILITY": ("The reader's durability must be no stronger than the "
                   "writer's: VOLATILE < TRANSIENT_LOCAL < TRANSIENT < PERSISTENT."),
    "DEADLINE": ("The reader's deadline period must be greater than or equal to "
                 "the writer's."),
    "LATENCYBUDGET": ("The reader's latency budget must be greater than or equal "
                      "to the writer's."),
    "LIVELINESS": ("The reader's liveliness kind must be no stronger than the "
                   "writer's, and its lease duration no shorter."),
    "OWNERSHIP": "Ownership kind must match exactly: SHARED and EXCLUSIVE never mix.",
    "DESTINATIONORDER": ("The reader's destination order must be no stronger than "
                         "the writer's: BY_RECEPTION_TIMESTAMP < BY_SOURCE_TIMESTAMP."),
    "PRESENTATION": ("The reader's presentation access scope must be no broader "
                     "than the writer's, and coherent/ordered access must be "
                     "compatible."),
    "PARTITION": ("Reader and writer must share at least one partition name. "
                  "Partitions are matched as strings, with wildcards allowed on "
                  "one side only."),
    "DATAREPRESENTATION": ("The reader must offer at least one data "
                           "representation the writer also offers (XCDR1/XCDR2)."),
    "TYPECONSISTENCYENFORCEMENT": ("The reader's type-consistency requirement "
                                   "rejected the writer's type."),
}


def _policy_rule(policy_text):
  """The rule for a policy name, matching the most specific key.

  Connext reports last_policy with a version-dependent prefix or suffix, so this
  matches on substring rather than equality. Longest match wins: PRESENTATION is
  a substring of DATAREPRESENTATION, and first-match would explain a data
  representation mismatch with the presentation rule.
  """
  key = str(policy_text).upper().replace("_", "").replace(" ", "")
  matches = [name for name in RXO_RULES if name in key]
  if not matches:
    return None
  return RXO_RULES[max(matches, key=len)]


def _scope_text(probe):
  """What the probe's observations actually describe.

  The probe's reader is created on a topic, not on an endpoint, so every status
  it reports is topic-wide until the selected writer is identified among the
  reader's matched publications. Stating the scope keeps a topic-wide reading
  from being read as a fact about one writer.
  """
  if not probe.correlated:
    return ("Scope: topic-wide - the selected writer could not be identified "
            "among the reader's matched publications, so this reading covers "
            "every writer on the topic.")
  extra = []
  if probe.matched_other_count:
    extra.append(f"{probe.matched_other_count} other writer(s) on this topic "
                 f"also matched and are excluded")
  if probe.matched_unreadable_count:
    extra.append(f"{probe.matched_unreadable_count} matched publication(s) "
                 f"could not be resolved to a writer")
  if extra:
    return ("Scope: the selected writer, correlated by publication handle; "
            + "; ".join(extra) + ".")
  return ("Scope: the selected writer, correlated by publication handle; it is "
          "the only writer this reader matched.")


def check_probe_error(context):
  """The probe could not even create a reader."""
  probe = context.probe
  if probe is None or not probe.attempted or probe.created:
    return []
  return [Finding(
      id="probe.not_created",
      rung=RUNG_MATCH,
      severity=Severity.ERROR,
      title="Could not create a reader for this endpoint",
      observed=probe.create_error or "unknown failure",
      root_cause=(
          "Without a reader nothing downstream can be measured. If the cause is "
          "missing type information, the rung-3 finding explains it; otherwise "
          "this is a local failure, not a property of the peer."),
      remedy="Resolve the error above, then re-run the probe.",
      evidence={"error": probe.create_error},
  )]


def check_probe_incomplete(context):
  """The reader was created, then something failed before the probe finished."""
  probe = context.probe
  if probe is None or not probe.created or not getattr(probe, "error", None):
    return []
  return [Finding(
      id="probe.incomplete",
      rung=RUNG_MATCH,
      severity=Severity.WARN,
      title="The probe did not run to completion",
      observed=probe.error,
      root_cause=(
          "The reader was created and whatever this report shows was genuinely "
          "observed, but the probe raised before finishing - typically while "
          "reading a status counter. Absent evidence in this report is "
          "therefore not evidence of absence: a counter that reads as zero may "
          "simply never have been sampled."),
      remedy=("Re-run the probe. If it fails the same way, this is an "
              "rti_doctor bug against this Connext version, not a property of "
              "the peer - report it with the error above."),
      evidence={"error": probe.error},
  )]


def check_incompatible_qos(context):
  """RequestedIncompatibleQos, with the offending policy named."""
  probe = context.probe
  if probe is None or not probe.created:
    return []

  status = probe.requested_incompatible_qos
  total = compat.get_int(status, "total_count")
  if not total:
    return []

  policy = compat.get(status, "last_policy", "unknown")
  rule = _policy_rule(policy)
  policies = compat.get(status, "policies", None)
  policy_detail = ""
  try:
    entries = [f"{compat.get(p, 'policy', '?')}={compat.get_int(p, 'count')}"
               for p in (policies or ())]
    policy_detail = ", ".join(e for e in entries if e)
  except TypeError:
    policy_detail = ""

  observed = [f"requested_incompatible_qos total_count = {total}",
              f"last_policy = {policy}"]
  if policy_detail:
    observed.append(f"policies = {policy_detail}")
  if probe.applied_reader_qos:
    observed.append("probe reader requested: " + ", ".join(
        f"{k}={v}" for k, v in sorted(probe.applied_reader_qos.items())))

  observed.append(_scope_text(probe))

  # requested_incompatible_qos is a READER status: it says some writer on this
  # topic offered a policy the reader would not accept, never which one. It may
  # only be reported as a fact about the selected writer when that writer is the
  # only one this reader could have rejected.
  attributable = (probe.correlated and not probe.matched_other_count
                  and not probe.matched_unreadable_count)

  root = ("A reader and writer only communicate when every requested-offered "
          "(RxO) policy is compatible. ")
  if rule:
    root += f"The reported policy's rule: {rule}"
  else:
    root += ("The reported policy could not be mapped to a known RxO rule; treat "
             "the policy name as authoritative.")
  # Worth stating: the probe mirrors the writer's QoS, so an incompatibility here
  # is not an artefact of the probe's own choices.
  root += (" Note that rti_doctor's probe mirrors the discovered writer's QoS, so "
           "this mismatch is not caused by the probe requesting something unusual "
           "- it reflects a policy the writer offers that no compliant reader can "
           "accept, or one that could not be mirrored on this version.")

  evidence = {"total_count": total, "last_policy": str(policy),
              "policies": policy_detail,
              "probe_reader_qos": probe.applied_reader_qos,
              "writer_identified": probe.correlated,
              "other_writers_matched": probe.matched_other_count}

  if attributable:
    return [Finding(
        id="match.incompatible_qos",
        rung=RUNG_MATCH,
        severity=Severity.ERROR,
        title=f"Incompatible QoS: {policy}",
        observed="; ".join(observed),
        root_cause=root,
        remedy=(f"Align the {policy} policy between writer and reader. The reader "
                f"is the constrained side: it must request no more than the writer "
                f"offers."),
        evidence=evidence,
    )]

  # Deliberately a DIFFERENT id, at WARN. It is not registered in
  # CAUSAL_EXPLAINERS, so an unattributable rejection is never offered as the
  # explanation for data.silent or match.none - a maybe must not be presented
  # as the cause of a real symptom.
  return [Finding(
      id="match.incompatible_qos_topic",
      rung=RUNG_MATCH,
      severity=Severity.WARN,
      title=f"Incompatible QoS on this topic: {policy}",
      observed="; ".join(observed),
      root_cause=(
          "Some writer on this topic offered a policy the probe's reader would "
          "not accept. requested_incompatible_qos is a reader-side status and "
          "does not name the writer that caused it, and this reader could have "
          "rejected a writer other than the selected one, so this is reported "
          "as a topic-level observation rather than a fault of the selected "
          "writer. " + root),
      remedy=(f"Identify which writer on this topic offers {policy}, then align "
              f"that policy. Re-running against a topic with a single writer "
              f"attributes the rejection directly."),
      evidence=evidence,
  )]


def check_matched(context):
  """Did the reader match at all?"""
  probe = context.probe
  if probe is None or not probe.created:
    return []

  current = compat.get_int(probe.subscription_matched, "current_count")
  total = compat.get_int(probe.subscription_matched, "total_count")
  scope = _scope_text(probe)

  probe_kind = getattr(probe, "probe_kind", "reader")
  subject = "Writer matched the reader" if probe_kind == "writer" else "Reader matched the writer"
  status_name = "publication_matched" if probe_kind == "writer" else "subscription_matched"
  if probe.matched:
    return [Finding(
        id="match.ok",
        rung=RUNG_MATCH,
        severity=Severity.OK,
         title=(subject if probe.correlated
               else "Reader matched a writer on this topic"),
         observed=(f"{status_name} current_count = {current}, "
                  f"total_count = {total} after {probe.elapsed:.1f}s. {scope}"),
        evidence={"current_count": current, "total_count": total,
                  "writer_identified": probe.correlated,
                  "other_writers_matched": probe.matched_other_count},
    )]

  return [Finding(
      id="match.none",
      rung=RUNG_MATCH,
      severity=Severity.ERROR,
            title=("Writer never matched the reader" if probe_kind == "writer"
              else "Reader never matched the writer"),
            observed=(f"{status_name} current_count = {current}, "
                f"total_count = {total} after {probe.elapsed:.1f}s. {scope}"),
      root_cause=(
          "The reader was created on the same topic with QoS mirroring the writer, "
          "and still did not match. In order of likelihood: an RxO policy could "
          "not be mirrored (see any incompatible-QoS finding); type consistency "
          "rejected the type; partitions do not overlap; or the writer's "
          "advertised locators are unreachable so the endpoints never completed "
          "discovery with each other."),
      remedy=("Work upward from the lowest-rung ERROR in this report - a rung 0-3 "
              "failure explains this one entirely."),
      evidence={"current_count": current, "total_count": total,
                "elapsed_seconds": round(probe.elapsed, 2),
                "writer_identified": probe.correlated,
                "other_writers_matched": probe.matched_other_count},
  )]


def check_inconsistent_topic(context):
  """Local topic definition conflicts with a remote definition of the same name."""
  probe = context.probe
  if probe is None or not probe.created:
    return []
  count = probe.inconsistent_topic_count
  if not count:
    return []
  return [Finding(
      id="match.topic_inconsistent",
      rung=RUNG_MATCH,
      severity=Severity.WARN,
      title="Topic reported as inconsistent",
      observed=f"InconsistentTopicStatus.total_count = {count}",
      root_cause=(
          "Another entity uses this topic name with a different type definition. "
          "This is a Topic-level status, not a per-writer one, so it flags a "
          "clash somewhere on the topic rather than with this specific writer."),
      remedy="Check every application publishing this topic name for a type mismatch.",
      evidence={"inconsistent_topic_total_count": count},
  )]


def check_partition_overlap(context):
  """Writer in a named partition while the probe could not mirror it."""
  probe = context.probe
  endpoint = context.endpoint
  if probe is None or not probe.created or endpoint is None:
    return []
  if probe.matched:
    return []

  names = compat.get(endpoint.partition, "name", None)
  try:
    listed = [str(n) for n in (names or ())]
  except TypeError:
    listed = []
  if not listed:
    return []

  applied = probe.applied_reader_qos.get("partition")
  if applied and "not applied" not in str(applied):
    return []

  return [Finding(
      id="match.partition",
      rung=RUNG_MATCH,
      severity=Severity.WARN,
      title="Writer is in a named partition the probe could not mirror",
      observed=f"writer partitions = {', '.join(listed)}; probe partition = {applied}",
      root_cause=("Readers and writers must share at least one partition name. A "
                  "reader in the default partition cannot see a writer in a named "
                  "one."),
      remedy=f"Place the reader in one of: {', '.join(listed)}.",
      evidence={"writer_partitions": listed, "probe_partition": applied},
  )]


CHECKS = (
    check_probe_error,
    check_probe_incomplete,
    check_incompatible_qos,
    check_matched,
    check_inconsistent_topic,
    check_partition_overlap,
)
