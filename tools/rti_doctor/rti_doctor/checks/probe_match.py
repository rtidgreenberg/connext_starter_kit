"""Rung 4 checks: did the reader match, and if not, which policy blocked it?"""

from .. import compat, probe as probe_mod
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


def _isolation_shortfall(probe):
  """Why an APPLIED isolation still is not a clean one, or "" when it is.

  Two ways a sweep that ran can still leave peers live, and neither shows up in
  the `ignored` list - which is exactly why they need naming. A peer the
  participant refused to ignore stays matched for the whole probe, and a sweep
  that raised partway through the probe window (`resweep` records the error and
  deliberately does not retract the isolation that already happened) may have
  stopped catching late joiners. Both were previously invisible: nothing read
  `isolation_error` on the isolated path at all.
  """
  reasons = []
  failures = len(getattr(probe, "ignore_failures", ()))
  if failures:
    reasons.append(f"{failures} peer(s) could not be ignored")
  if getattr(probe, "isolation_error", None):
    reasons.append("the sweep failed during the probe")
  return "; ".join(reasons)


def _isolation_scope_text(probe):
  """The scope sentence isolation earns, or "" when it earned none.

  Isolation changes the scope by construction rather than by inference: with
  every other endpoint on the topic ignored before the probe's entity existed,
  there is no other writer whose sample or whose status could be attributed to
  the selected one. That is a stronger claim than publication-handle
  correlation, and it is only true when the sweep both ran and saw the target -
  a sweep that timed out before the target appeared may have missed peers that
  were announced after it gave up.
  """
  if not getattr(probe, "isolation_requested", False):
    return ""
  if not getattr(probe, "isolated", False):
    return ("Isolation was requested and did not happen, so other endpoints on "
            "this topic were live for the whole probe.")
  ignored = len(getattr(probe, "ignored", ()))
  # Checked BEFORE the count, because a sweep that ignored nothing because it
  # FAILED and a sweep that ignored nothing because there was nothing there are
  # opposite readings of the same empty list. Reporting the second when the
  # first happened is the false certainty this whole feature exists to remove.
  incomplete = _isolation_shortfall(probe)
  if incomplete:
    return (f"Isolation was incomplete ({incomplete}), so other endpoints on "
            f"this topic may have been live for part or all of the probe.")
  if not getattr(probe, "isolation_target_seen", False):
    return (f"{ignored} other endpoint(s) on this topic were ignored, but the "
            f"selected endpoint never appeared in the probe participant's own "
            f"discovery, so peers announced later may not have been.")
  if not ignored:
    return ("Isolation was applied and found no other endpoint on this topic to "
            "ignore, so the selected one was alone on it.")
  return (f"{ignored} other endpoint(s) on this topic were ignored before the "
          f"probe created anything, so nothing else could match it.")


def _scope_text(probe):
  """What the probe's observations actually describe.

  The probe's reader is created on a topic, not on an endpoint, so every status
  it reports is topic-wide until the selected writer is identified among the
  reader's matched publications. Stating the scope keeps a topic-wide reading
  from being read as a fact about one writer.

  Isolation is appended rather than substituted. It narrows what could have
  produced an observation, but `requested_incompatible_qos` and the protocol
  counters are still reader-side aggregates, so the correlation caveat stays
  exactly as strong as it was.
  """
  isolation = _isolation_scope_text(probe)
  suffix = f" {isolation}" if isolation else ""
  if not probe.correlated:
    return ("Scope: topic-wide - the selected writer could not be identified "
            "among the reader's matched publications, so this reading covers "
            "every writer on the topic." + suffix)
  extra = []
  if probe.matched_other_count:
    extra.append(f"{probe.matched_other_count} other writer(s) on this topic "
                 f"also matched and are excluded")
  if probe.matched_unreadable_count:
    extra.append(f"{probe.matched_unreadable_count} matched publication(s) "
                 f"could not be resolved to a writer")
  if extra:
    return ("Scope: the selected writer, correlated by publication handle; "
            + "; ".join(extra) + "." + suffix)
  return ("Scope: the selected writer, correlated by publication handle; it is "
          "the only writer this reader matched." + suffix)


#: How many ignored peers the finding lists individually before summarising.
#: The list is the whole point of this finding - "we excluded these specific
#: endpoints" is not a claim an operator can check against a count - but a
#: scale topic can carry dozens, and a finding that fills a screen stops being
#: read. Past this, the count and the evidence dict still carry every key.
ISOLATION_LIST_LIMIT = 8


def _peer_line(record):
  """One ignored peer, identified the way the rest of the report identifies one."""
  parts = [f"{record.get('kind', 'endpoint')} {record.get('key', '?')}"]
  if record.get("participant_key"):
    parts.append(f"participant={record['participant_key']}")
  if record.get("type_name"):
    parts.append(f"type={record['type_name']}")
  if record.get("error"):
    parts.append(f"ERROR={record['error']}")
  return "; ".join(parts)


def check_isolation(context):
  """Exactly what the probe ignored, and what that does to everything below.

  Always reported when isolation was asked for, including when it ignored
  nothing. That is deliberate: the probe deliberately excluded part of the
  system under test, and every count, status and sample in this report was
  measured against what was left. An operator who cannot see that this happened
  cannot judge any of it, and "nothing was ignored" is a finding about the
  topic - it says the selected endpoint was alone on it - rather than an absence
  worth staying silent about.
  """
  probe = context.probe
  if probe is None or not getattr(probe, "isolation_requested", False):
    return []

  endpoint = context.endpoint
  topic = getattr(endpoint, "topic_name", None) or "this topic"
  peer = "writer" if getattr(endpoint, "is_writer", True) else "reader"
  ignored = list(getattr(probe, "ignored", ()))
  failures = list(getattr(probe, "ignore_failures", ()))
  elapsed = getattr(probe, "isolation_elapsed", 0.0) or 0.0

  if not getattr(probe, "isolated", False):
    return [Finding(
        id="probe.isolation_failed",
        rung=RUNG_MATCH,
        severity=Severity.WARN,
        title="The probe could not isolate the selected endpoint",
        observed=(getattr(probe, "isolation_error", None)
                  or "isolation did not run and gave no reason"),
        root_cause=(
            f"The probe was asked to ignore every other {peer} on '{topic}' so "
            f"that the selected one was its only peer, and could not. The probe "
            f"still ran, on a topic it shares with whatever else is publishing "
            f"or subscribing there, so every observation below is topic-wide in "
            f"the ordinary way and the correlation caveats on each finding "
            f"apply in full."),
        remedy=("Nothing needs fixing on the system under test. Re-run to try "
                "again; if it fails the same way, this is an rti_doctor "
                "limitation on this Connext version - report it with the error "
                "above, and read this report as an un-isolated one."),
        evidence={"isolation_error": getattr(probe, "isolation_error", None),
                  "isolated": False},
    )]

  # What we did, in the order it happened.
  observed = [
      f"ran a disposable participant for this probe and ignored {len(ignored)} "
      f"other {peer}(s) on '{topic}' before creating anything",
      f"selected endpoint seen in the probe participant's own discovery: "
      f"{'yes' if getattr(probe, 'isolation_target_seen', False) else 'no'}",
      f"isolation took {elapsed:.1f}s, and is not counted in the probe window",
  ]
  for record in ignored[:ISOLATION_LIST_LIMIT]:
    observed.append("ignored " + _peer_line(record))
  if len(ignored) > ISOLATION_LIST_LIMIT:
    observed.append(f"...and {len(ignored) - ISOLATION_LIST_LIMIT} more "
                    f"(every key is in this finding's evidence)")
  for record in failures:
    observed.append("could NOT ignore " + _peer_line(record))
  if getattr(probe, "isolation_error", None):
    observed.append(f"the sweep failed during the probe window: "
                    f"{probe.isolation_error}")

  shortfall = _isolation_shortfall(probe)
  claim = ("so the selected endpoint was the only peer this probe could match"
           if not shortfall else
           f"but the isolation was incomplete ({shortfall}), so the selected "
           f"endpoint was NOT necessarily its only peer")
  root = (
      f"rti_doctor asked its own participant to ignore those {peer}(s), {claim}. "
      f"This is a "
      f"change rti_doctor made to what it could see, not a change to the system "
      f"under test: ignoring is local to our participant, the applications "
      f"involved are unaffected and still talking to each other, and the "
      f"participant is closed at the end of the probe so the ignores expire "
      f"with it. ")
  if ignored:
    root += (
        "It matters most where the topic has several writers and OWNERSHIP is "
        "EXCLUSIVE: writers of equal strength arbitrate for each instance, the "
        "loser's samples are discarded at the reader as "
        "ownership_dropped_sample_count, and an un-isolated probe of the losing "
        "writer reports 'matched, but no samples were received' about a writer "
        "that is publishing perfectly well. ")
  elif shortfall:
    root += (f"Nothing was successfully ignored, so this probe was NOT isolated "
             f"from the rest of '{topic}' - read every observation below as "
             f"topic-wide. ")
  else:
    root += (f"Nothing was ignored because no other {peer} was discovered on "
             f"'{topic}', so the selected endpoint was alone on it. ")
  root += (
      "The one thing it does not do is rewrite history: a sample already in the "
      "reader's cache when its writer was ignored can still be taken afterwards.")

  remedy = ""
  if shortfall:
    remedy = (f"Isolation was incomplete ({shortfall}), so peers were live "
              f"during the probe - treat any per-endpoint attribution below as "
              f"topic-wide, and see the errors above. Nothing needs fixing on "
              f"the system under test.")
  elif not getattr(probe, "isolation_target_seen", False):
    remedy = (f"The selected endpoint never appeared in the probe participant's "
              f"own discovery within its fixed "
              f"{probe_mod.ISOLATION_TIMEOUT:.0f}s isolation window, so a peer "
              f"announced after the sweep gave up may not have been ignored. "
              f"--settle does not widen that window - it settles the session "
              f"participant, while this one is created when the probe starts - "
              f"so treat any per-endpoint attribution below as topic-wide, and "
              f"re-run: discovery that was merely slow usually lands inside "
              f"the window on a second attempt.")

  return [Finding(
      id="probe.isolated",
      rung=RUNG_MATCH,
      severity=Severity.WARN if shortfall else Severity.INFO,
      title=(f"Probe isolated the selected endpoint: {len(ignored)} other "
             f"{peer}(s) ignored"),
      observed="; ".join(observed),
      root_cause=root,
      remedy=remedy,
      evidence={"ignored_count": len(ignored),
                "ignored": [record.get("key") for record in ignored],
                "ignore_failures": failures,
                "isolation_error": getattr(probe, "isolation_error", None),
                "isolation_seconds": round(elapsed, 2),
                "target_seen_in_discovery": getattr(
                    probe, "isolation_target_seen", False),
                "topic": topic},
  )]


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
  # topic offered a policy the reader would not accept, never which one.
  # Matched-publication handles cannot close that gap: incompatible writers are
  # not matched and therefore absent from that list.

  root = ("A reader and writer only communicate when every requested-offered "
          "(RxO) policy is compatible. ")
  if rule:
    root += f"The reported policy's rule: {rule}"
  else:
    root += ("The reported policy could not be mapped to a known RxO rule; treat "
             "the policy name as authoritative.")
  root += (" The status is aggregated across writers on this topic, so it does "
           "not identify which discovered writer offered the incompatible policy.")

  evidence = {"total_count": total, "last_policy": str(policy),
              "policies": policy_detail,
              "probe_reader_qos": probe.applied_reader_qos,
              "status_scope": "topic",
              "writer_identified": probe.correlated,
              "other_writers_matched": probe.matched_other_count}

  # This id is deliberately absent from CAUSAL_EXPLAINERS: an aggregate
  # topic-level rejection must not be offered as the explanation for a
  # pair-specific symptom.
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
    # First: what rti_doctor did to the observation comes before what the
    # observation showed. Every finding after this one was measured against a
    # topic this check says we narrowed.
    check_isolation,
    check_probe_error,
    check_probe_incomplete,
    check_incompatible_qos,
    check_matched,
    check_inconsistent_topic,
    check_partition_overlap,
)
