"""Rung 5 checks: data arrival, fragmentation, decode failures, field walk.

The point of this rung is to keep four very different "no data" worlds distinct,
because conflating them is what makes this class of bug expensive:

  * not matched            -> rung 3/4
  * matched but silent     -> writer idle, filtered, or return path broken
  * arriving but dropped   -> fragmentation, receive window, resource limits
  * arriving but undecodable -> deserialization / decode failure
"""

from .. import compat
from ..findings import PAYLOAD_FULL, RUNG_PAYLOAD, Finding, Severity


def _c(probe, name):
  """Protocol counter, or None when unavailable on this version."""
  return probe.protocol.get(name)


def _writer_is_reliable(context):
  """True when the discovered writer offers RELIABLE.

  Used to justify the asymmetric-match inference: only a RELIABLE writer is
  obliged to send heartbeats to a reader it has matched, so only then does the
  absence of heartbeats prove the writer has not matched us.
  """
  endpoint = getattr(context, "endpoint", None)
  if endpoint is None:
    return False
  kind = compat.get(getattr(endpoint, "reliability", None), "kind", None)
  if kind is None:
    return False
  name = compat.get(kind, "name", None) or str(kind)
  return "RELIABLE" in str(name).upper()


def check_silent(context):
  """Matched, but no samples arrived within the probe window."""
  probe = context.probe
  if probe is None or not probe.created or not probe.matched:
    return []
  if probe.samples_taken:
    return []

  heartbeats = _c(probe, "received_heartbeat_count")
  samples = _c(probe, "received_sample_count")
  gaps = _c(probe, "received_gap_count")

  observed = [f"0 valid samples taken in {probe.elapsed:.1f}s",
              f"received_sample_count = {compat.na_text() if samples is None else samples}",
              f"received_heartbeat_count = "
              f"{compat.na_text() if heartbeats is None else heartbeats}",
              f"received_gap_count = {compat.na_text() if gaps is None else gaps}"]

  if heartbeats and not samples:
    root = (
        "Heartbeats are arriving but no data is. The writer is alive and the "
        "reliable protocol path works in at least one direction, so the writer "
        "either has not written anything, or its samples are being filtered or "
        "dropped before delivery. GAP messages, if any, indicate the writer "
        "actively told the reader those sequence numbers will never arrive - "
        "typical of a writer-side content filter or of samples that expired "
        "before this late-joining reader appeared.")
    remedy = ("Confirm the publisher is actually writing. If it is, check for a "
              "writer-side content filter, a lifespan shorter than the write "
              "period, or VOLATILE durability with no live samples during the "
              "probe window.")
  elif samples:
    root = ("Samples were received at the protocol layer but none were delivered "
            "as valid data, so they were dropped between reception and the reader "
            "cache. The drop counters in the cache section identify which policy "
            "removed them.")
    remedy = "Check the cache-drop and sample-lost findings in this report."
  elif _writer_is_reliable(context):
    # Verified against a live Cyclone DDS writer: RTI matched it, but zero
    # heartbeats arrived. A RELIABLE writer that considers a reader matched is
    # obliged to send heartbeats to it, so zero heartbeats from a reliable writer
    # is strong evidence the match is one-sided.
    root = (
        "Nothing arrived at all - no data and no heartbeats - even though this "
        "writer is RELIABLE. A reliable writer that considers a reader matched "
        "must send it heartbeats, so the most likely explanation is an ASYMMETRIC "
        "MATCH: we matched the writer, but the writer has not matched us. Each "
        "side runs its own matching checks, and vendors differ in strictness, so "
        "the permissive side reports a match while the stricter side silently "
        "rejects. Cross-vendor the usual triggers are type-consistency "
        "enforcement on the writer's side rejecting our type, a data "
        "representation the writer will not accept (an XCDR1-only reader against "
        "an XCDR2/FINAL type), or a type name that differs after IDL "
        "module-name mangling. A locator the writer cannot reach produces the "
        "same silence.")
    remedy = (
        "Look at the writer's own side: check its logs or match status for a "
        "rejected reader, and compare its type-consistency and data-"
        "representation settings against this report's type findings. Confirm "
        "reachability in both directions, not just from here.")
  else:
    root = ("Nothing arrived at all: no data and no heartbeats. The endpoints "
            "matched through discovery (which can travel over multicast) but the "
            "user-data path is not working. For a BEST_EFFORT writer no "
            "heartbeats are expected, so this is either a writer that has not "
            "written during the probe window, or an advertised unicast locator "
            "that is not reachable from here.")
    remedy = ("Confirm the publisher is writing, then verify UDP reachability to "
              "the writer's advertised address and port.")

  return [Finding(
      id="data.silent",
      rung=RUNG_PAYLOAD,
      severity=Severity.WARN,
      title="Matched, but no samples were received",
      observed="; ".join(observed),
      root_cause=root,
      remedy=remedy,
      evidence=dict(probe.protocol),
  )]


def check_fragmentation(context):
  """Large-data path: are fragments arriving and reassembling?"""
  probe = context.probe
  if probe is None or not probe.created:
    return []

  fragments = _c(probe, "received_fragment_count")
  reassembled = _c(probe, "reassembled_sample_count")
  dropped = _c(probe, "dropped_fragment_count")
  nack_fragments = _c(probe, "sent_nack_fragment_count")

  if not fragments:
    return []

  # Ground truth is whether samples actually arrived. Two false positives were
  # observed against a healthy local large-data writer and must not come back:
  #
  #   1. dropped_fragment_count is NOT by itself evidence of a fault. A healthy
  #      TRANSIENT_LOCAL writer produced fragments=6, reassembled=6, dropped=6:
  #      the "dropped" fragments were redundant copies from ordinary repair
  #      traffic, and every sample still arrived intact.
  #   2. reassembled_sample_count can lag, because the probe stops as soon as it
  #      has walked one sample.
  #
  # So reassembly is only called broken when nothing was delivered at all.
  problem = probe.samples_taken == 0 and not reassembled
  if not problem:
    return [Finding(
        id="data.fragmentation",
        rung=RUNG_PAYLOAD,
        severity=Severity.INFO,
        title="Samples are fragmented and arriving intact",
        observed=(f"received_fragment_count = {fragments}, "
                  f"reassembled_sample_count = {reassembled}, "
                  f"dropped_fragment_count = {dropped}, "
                  f"sent_nack_fragment_count = {nack_fragments}, "
                  f"valid samples taken = {probe.samples_taken}"),
        root_cause=("This type exceeds the transport's message size, so Connext "
                    "fragments it, and samples are being delivered. Large data is "
                    "worth knowing about because it is sensitive to message-size "
                    "and receive-buffer differences between vendors even when it "
                    "currently works."),
        evidence={"received_fragment_count": fragments,
                  "reassembled_sample_count": reassembled},
    )]

  return [Finding(
      id="data.fragmentation",
      rung=RUNG_PAYLOAD,
      severity=Severity.ERROR,
      title="Fragments are arriving but no sample was ever reassembled",
      observed=(f"received_fragment_count = {fragments}, "
                f"reassembled_sample_count = {reassembled}, "
                f"dropped_fragment_count = {dropped}, "
                f"sent_nack_fragment_count = {nack_fragments}"),
      root_cause=(
          "Fragments are arriving but complete samples are not being rebuilt. "
          "Cross-vendor this is commonly a disagreement about maximum message "
          "size or fragment sizing, or a receive buffer too small to hold the "
          "fragments of one sample. Repeated NACK_FRAG traffic means the reader "
          "keeps asking for fragments it never gets."),
      remedy=("Align message_size_max across both sides and raise the reader's "
              "socket receive buffer. For very large types, confirm both vendors "
              "agree on the asynchronous-publishing/flow-controller setup."),
      evidence={"received_fragment_count": fragments,
                "reassembled_sample_count": reassembled,
                "dropped_fragment_count": dropped,
                "sent_nack_fragment_count": nack_fragments},
  )]


def check_window(context):
  """Receive-window and ordering problems."""
  probe = context.probe
  if probe is None or not probe.created:
    return []

  out_of_range = _c(probe, "out_of_range_rejected_sample_count")
  uncommitted = _c(probe, "uncommitted_sample_count")
  if not out_of_range and not uncommitted:
    return []

  return [Finding(
      id="data.window",
      rung=RUNG_PAYLOAD,
      severity=Severity.WARN,
      title="Samples rejected or held by the receive window",
      observed=(f"out_of_range_rejected_sample_count = {out_of_range}, "
                f"uncommitted_sample_count = {uncommitted}"),
      root_cause=(
          "Out-of-range rejections mean the reader's receive window was full and "
          "samples outside it were discarded. A persistently high uncommitted "
          "count means samples arrived but cannot be released to the application "
          "yet, normally because an earlier sequence number is missing."),
      remedy=("Increase the reader's resource limits, or reduce the writer's send "
              "rate. If uncommitted stays high, investigate the missing sequence "
              "numbers as loss rather than as a decode problem."),
      evidence={"out_of_range_rejected_sample_count": out_of_range,
                "uncommitted_sample_count": uncommitted},
  )]


def check_deserialize_failure(context):
  """Connext itself could not decode a sample - the strongest payload signal."""
  probe = context.probe
  if probe is None or not probe.created:
    return []

  lost = probe.sample_lost
  rejected = probe.sample_rejected
  lost_total = compat.get_int(lost, "total_count") or 0
  rejected_total = compat.get_int(rejected, "total_count") or 0
  if not lost_total and not rejected_total:
    return []

  lost_reason = compat.get(lost, "last_reason", None)
  rejected_reason = compat.get(rejected, "last_reason", None)

  deserialization = compat.reason_matches(
      lost_reason, compat.lost_reason_flag("LOST_BY_DESERIALIZATION_FAILURE"))
  decode_lost = compat.reason_matches(
      lost_reason, compat.lost_reason_flag("LOST_BY_DECODE_FAILURE"))
  decode_rejected = compat.reason_matches(
      rejected_reason, compat.rejected_reason_flag("REJECTED_BY_DECODE_FAILURE"))

  observed = [
      f"sample_lost total_count = {lost_total}, "
      f"last_reason = {compat.reason_text(lost_reason)}",
      f"sample_rejected total_count = {rejected_total}, "
      f"last_reason = {compat.reason_text(rejected_reason)}",
      f"datareader_protocol_status.rejected_sample_count = "
      f"{_c(probe, 'rejected_sample_count')}",
  ]

  if deserialization or decode_lost or decode_rejected:
    which = []
    if deserialization:
      which.append("LOST_BY_DESERIALIZATION_FAILURE")
    if decode_lost:
      which.append("LOST_BY_DECODE_FAILURE")
    if decode_rejected:
      which.append("REJECTED_BY_DECODE_FAILURE")
    return [Finding(
        id="data.deserialize_failure",
        rung=RUNG_PAYLOAD,
        severity=Severity.ERROR,
        title="Samples arrived but could not be deserialized",
        observed="; ".join(observed) + f"; matched reason(s): {', '.join(which)}",
        root_cause=(
            "Connext received bytes on the wire and could not turn them into a "
            "sample of this type. The reader's idea of the type does not match "
            "the bytes the writer produced. Cross-vendor, the usual causes are an "
            "XCDR1/XCDR2 mismatch, an extensibility disagreement (FINAL vs "
            "APPENDABLE vs MUTABLE), differing member bounds, or a differing enum "
            "bit bound. A decode failure specifically can also indicate a "
            "security/crypto transformation the reader cannot reverse."),
        remedy=("Compare the writer's IDL in appendix A against the reader's own "
                "definition, and make both sides agree on data representation and "
                "extensibility before looking anywhere else."),
        evidence={"sample_lost_total": lost_total,
                  "sample_lost_reason": compat.reason_text(lost_reason),
                  "sample_rejected_total": rejected_total,
                  "sample_rejected_reason": compat.reason_text(rejected_reason),
                  "matched_reasons": which},
    )]

  return [Finding(
      id="data.loss",
      rung=RUNG_PAYLOAD,
      severity=Severity.WARN,
      title="Samples were lost or rejected for a non-decode reason",
      observed="; ".join(observed),
      root_cause=("Samples went missing, but not because they could not be "
                  "decoded. The reported reason names the mechanism - typically a "
                  "resource limit, an unknown instance, or ordinary transport "
                  "loss."),
      remedy="Read the reported reason; it names the limit or condition directly.",
      evidence={"sample_lost_reason": compat.reason_text(lost_reason),
                "sample_rejected_reason": compat.reason_text(rejected_reason)},
  )]


def check_cache_drops(context):
  """Drops that are policy rather than corruption."""
  probe = context.probe
  if probe is None or not probe.created:
    return []

  interesting = {
      "replaced_dropped_sample_count":
          "KEEP_LAST history replaced older samples (normal under load)",
      "expired_dropped_sample_count":
          "samples passed their lifespan before being read",
      "content_filter_dropped_sample_count":
          "a content filter discarded them",
      "time_based_filter_dropped_sample_count":
          "a time-based filter discarded them",
      "ownership_dropped_sample_count":
          "a higher-strength exclusive owner won",
      "old_source_timestamp_dropped_sample_count":
          "source timestamps were older than already-received samples",
      "total_samples_dropped_by_instance_replacement":
          "instance replacement evicted them",
  }
  hits = {}
  for name, meaning in interesting.items():
    value = probe.cache.get(name)
    if value:
      hits[name] = (value, meaning)
  if not hits:
    return []

  return [Finding(
      id="data.cache_drops",
      rung=RUNG_PAYLOAD,
      severity=Severity.INFO,
      title="Samples were dropped by reader-cache policy, not by corruption",
      observed="; ".join(f"{name} = {value} ({meaning})"
                         for name, (value, meaning) in sorted(hits.items())),
      root_cause=("These counters record deliberate policy behaviour. They are "
                  "listed so that policy drops are not mistaken for loss or "
                  "decode failure."),
      remedy="",
      evidence={name: value for name, (value, _) in hits.items()},
  )]


def check_payload_walk(context):
  """The full-deserialization verdict: every member read, failures by field path."""
  probe = context.probe
  if probe is None or probe.walk is None:
    return []

  walk = probe.walk
  if walk.fatal:
    return [Finding(
        id="payload.partial",
        rung=RUNG_PAYLOAD,
        severity=Severity.ERROR,
        title="Sample could not be walked",
        observed=walk.fatal,
        root_cause=("The sample arrived but its type could not be traversed at "
                    "all, so no member-level verdict is possible."),
        remedy="Resolve the type-resolution findings first.",
    )]

  total = walk.total
  failed = walk.failed
  absent = walk.absent

  detail = [f"{total - len(failed)} of {total} member(s) read successfully"]
  if absent:
    detail.append(f"{len(absent)} optional member(s) legitimately absent")
  if walk.truncated:
    detail.append("walk truncated by rti_doctor's own element/depth caps, so some "
                  "members were not visited")

  if not failed:
    return [Finding(
        id="payload.full",
        rung=RUNG_PAYLOAD,
        severity=Severity.OK,
        title="Payload fully deserialized",
        observed="; ".join(detail),
        evidence={"members_total": total,
                  "members_absent": [r.path for r in absent],
                  "truncated": walk.truncated},
    )]

  listed = "; ".join(f"{r.path} ({r.detail})" for r in failed[:20])
  if len(failed) > 20:
    listed += f"; ... and {len(failed) - 20} more"

  return [Finding(
      id="payload.partial",
      rung=RUNG_PAYLOAD,
      severity=Severity.ERROR,
      title=(f"{len(failed)} of {total} members could not be read"
             if len(failed) < total else "No member of the sample could be read"),
      observed="; ".join(detail) + f". Unreadable: {listed}",
      root_cause=(
          "The sample was delivered, so discovery, matching, and transport are all "
          "working - but specific members cannot be decoded from the bytes "
          "received. When the failures cluster at the end of a struct, the usual "
          "cause is an XCDR1/XCDR2 or extensibility mismatch truncating the "
          "serialized extent. Scattered failures more often mean the two sides "
          "disagree about a member's type or bounds."),
      remedy=("Compare the field paths above against the IDL in appendix A, then "
              "align data representation and extensibility between the two sides."),
      evidence={"members_total": total,
                "members_unreadable": len(failed),
                "unreadable_paths": [r.path for r in failed],
                "truncated": walk.truncated},
  )]


CHECKS = (
    check_silent,
    check_fragmentation,
    check_window,
    check_deserialize_failure,
    check_cache_drops,
    check_payload_walk,
)
