"""Live probe: create a matched reader, sample its statuses, take a sample.

The probe is the only part of rti_doctor that creates DDS entities beyond the
diagnostic participant, and it guarantees they are closed - a diagnostic that
leaks readers changes the system it is measuring.
"""

import logging
import time

import rti.connextdds as dds

from . import compat, records, typewalk

#: Protocol counters captured for the report appendix, in report order.
PROTOCOL_COUNTERS = (
    "received_sample_count",
    "received_sample_bytes",
    "received_heartbeat_count",
    "received_gap_count",
    "received_fragment_count",
    "reassembled_sample_count",
    "dropped_fragment_count",
    "sent_nack_count",
    "sent_nack_fragment_count",
    "duplicate_sample_count",
    "out_of_range_rejected_sample_count",
    "uncommitted_sample_count",
    "rejected_sample_count",
    "first_available_sample_sequence_number",
    "last_available_sample_sequence_number",
    "last_committed_sample_sequence_number",
)

#: Writer-side protocol counters, captured when the selected endpoint is a
#: READER and the probe therefore creates a writer. These are the reliable
#: handshake seen from the sending side: a RELIABLE writer sends heartbeats, and
#: `received_ack_count` / `received_nack_count` are the peer reader answering
#: them. Zero heartbeats sent with a matched reader, or heartbeats sent and no
#: ACK returned, are two different faults and neither is visible in the reader
#: counters this tool used to be the only consumer of.
WRITER_PROTOCOL_COUNTERS = (
    "pushed_sample_count",
    "pushed_sample_bytes",
    "pulled_sample_count",
    "sent_heartbeat_count",
    "received_ack_count",
    "received_nack_count",
    "received_nack_fragment_count",
    "sent_gap_count",
    "rejected_sample_count",
    "send_window_size",
    "first_available_sample_sequence_number",
    "last_available_sample_sequence_number",
    "first_unacknowledged_sample_sequence_number",
)

#: Writer-side reliability cache counters, from ReliableWriterCacheChangedStatus.
WRITER_CACHE_COUNTERS = (
    "unacknowledged_sample_count",
    "unacknowledged_sample_count_peak",
    "replaced_unacknowledged_sample_count",
)

#: Cache counters captured for the report appendix.
CACHE_COUNTERS = (
    "sample_count",
    "sample_count_peak",
    "replaced_dropped_sample_count",
    "expired_dropped_sample_count",
    "content_filter_dropped_sample_count",
    "time_based_filter_dropped_sample_count",
    "ownership_dropped_sample_count",
    "old_source_timestamp_dropped_sample_count",
    "tolerance_source_timestamp_dropped_sample_count",
    "virtual_duplicate_dropped_sample_count",
    "total_samples_dropped_by_instance_replacement",
    "writer_removed_batch_sample_dropped_sample_count",
    "alive_instance_count",
)


class ProbeResult:
  """Everything the probe observed. Consumed by the rung 4/5 checks."""

  def __init__(self):
    self.attempted = False
    self.created = False
    self.create_error = None
    # A failure AFTER the reader was created - typically a status read that
    # raised. Kept separate from create_error because `created` stays True and
    # the samples already walked are still real; what is no longer safe is to
    # present the run as a complete observation.
    self.error = None
    self.matched_count = 0
    self.samples_taken = 0
    self.walk = None
    self.sample_repr = ""
    # The Data view's payload: the text of every sample the probe took from the
    # selected writer, oldest first. `sample_repr` above stays truncated to the
    # one line Appendix B cites it as; these are kept long enough to read a
    # whole sample, which is the only reason the Data view exists.
    self.sample_texts = []
    # Collection stopped early because a sample came back at DATA_SAMPLE_LIMIT.
    # The report says so: "one sample" and "one sample because the rest were too
    # expensive to render" are different statements about the writer.
    self.sample_texts_capped = False
    # Writer-identity correlation. The probe's reader is created on a TOPIC, so
    # subscription_matched, requested_incompatible_qos and every sample can
    # belong to a different writer publishing the same topic. matched_count and
    # samples_taken above are scoped to the selected writer whenever
    # `correlated` is True; when it is False the binding could not report
    # matched publications and they fall back to topic-wide counts, which no
    # finding may attribute to the selected writer.
    self.correlated = False
    self.matched_other_count = 0
    self.matched_unreadable_count = 0
    self.samples_other = 0
    # Status snapshots, taken after the probe window.
    self.subscription_matched = None
    self.requested_incompatible_qos = None
    self.sample_lost = None
    self.sample_rejected = None
    self.protocol = {}
    self.cache = {}
    self.inconsistent_topic_count = None
    self.applied_reader_qos = {}
    # Which entity the probe created, NOT which entity was selected: "reader"
    # means the probe made a reader because the target is a writer.
    self.probe_kind = "reader"
    # Writer-probe fields, populated only when `probe_kind == "writer"`. They
    # stay `{}` / `None` on the reader path rather than being folded into
    # `protocol`/`cache`, because a report that printed reader counters for a
    # run that created a writer would be describing an entity that never
    # existed - which is how "n/a on Connext 7.7.0" came to be
    # printed for statuses this tool never asked for.
    self.writer_protocol = {}
    self.writer_cache = {}
    self.offered_incompatible_qos = None
    # Whether the probe published anything. False keeps every delivery
    # observation honest: with nothing written, silence is the expected result
    # and must never be reported as a fault of the peer.
    self.wrote_samples = False
    self.samples_written = 0
    self.acknowledged = None
    self.elapsed = 0.0
    self.listener_events = []
    # Isolation: the peers this probe asked its participant to ignore, so that
    # the only endpoint it can talk to is the selected one. Recorded in full
    # rather than as a count, because ignoring a peer changes what every
    # observation below means and the report has to be able to say exactly what
    # was excluded, not merely how many.
    #
    # `isolation_requested` is "we were asked to", `isolated` is "we did".
    # They differ whenever `isolation_error` is set, and the report must not
    # collapse them: "isolated, nothing to ignore" and "isolation failed, other
    # writers were live the whole time" are opposite readings of the same
    # `ignored == []`.
    self.isolation_requested = False
    self.isolated = False
    self.isolation_error = None
    self.isolation_elapsed = 0.0
    # Whether the SELECTED endpoint appeared in the probe participant's own
    # discovery. False means the sweep timed out without seeing it, so peers
    # that had not been announced yet may never have been ignored.
    self.isolation_target_seen = False
    self.ignored = []
    self.ignore_failures = []

  @property
  def matched(self):
    return self.matched_count > 0


class _DiagnosticListener(dds.DynamicData.NoOpDataReaderListener):
  """Records status callbacks as they happen.

  Polling alone can miss a transient: an incompatible-QoS event that is later
  followed by a successful match on a different writer still matters, and
  total_count_change is reset by each read. So both are used - callbacks for the
  event log, a final poll for authoritative totals.
  """

  def __init__(self, result):
    super().__init__()
    self.result = result

  def _log(self, text):
    self.result.listener_events.append(f"{time.strftime('%H:%M:%S')} {text}")
    logging.info(f"[probe] {text}")

  def on_requested_incompatible_qos(self, reader, status):
    policy = compat.get(status, "last_policy", "unknown")
    # Log every refusing policy, not only the last one evaluated: this line is
    # often the only record of why a probe never matched.
    policies = compat.incompatible_policies(status)
    named = ", ".join(f"{name} (x{count})" for name, count in policies)
    self._log(f"REQUESTED_INCOMPATIBLE_QOS last_policy={policy}"
              + (f" policies={named}" if named else ""))

  def on_sample_lost(self, reader, status):
    reason = compat.reason_text(compat.get(status, "last_reason", None))
    self._log(f"SAMPLE_LOST reason={reason}")

  def on_sample_rejected(self, reader, status):
    reason = compat.reason_text(compat.get(status, "last_reason", None))
    self._log(f"SAMPLE_REJECTED reason={reason}")

  def on_subscription_matched(self, reader, status):
    current = compat.get_int(status, "current_count")
    self._log(f"SUBSCRIPTION_MATCHED current_count={current}")


def build_reader_qos(endpoint):
  """Reader QoS mirroring the discovered writer, so RxO cannot fail on our side.

  Same approach as rti_spy's create_topic_subscription(): request exactly what
  the writer offers. Returns (qos, applied) where `applied` records what was set
  for the report - a probe that silently differs from what it claims to have
  requested is untrustworthy.

  Judging the *user's own* reader QoS is deliberately out of scope: rti_doctor
  does not know what QoS the real application requests, so it could only guess.
  Mirroring keeps every QoS-related finding factual - it reports what the writer
  offers, never what some hypothetical reader should have asked for.
  """
  qos = dds.DataReaderQos()
  applied = {}

  if endpoint.reliability is not None:
    try:
      qos.reliability.kind = endpoint.reliability.kind
      applied["reliability"] = str(endpoint.reliability.kind)
      max_blocking = compat.get(endpoint.reliability, "max_blocking_time", None)
      if max_blocking is not None:
        qos.reliability.max_blocking_time = max_blocking
    except Exception as e:
      applied["reliability"] = f"not applied ({e})"

  for name in ("durability", "latency_budget", "deadline", "ownership", "destination_order", "liveliness"):
    policy = getattr(endpoint, name, None)
    if policy is None:
      continue
    try:
      if name == "deadline":
        qos.deadline.period = policy.period
        applied[name] = str(policy.period)
      elif name == "latency_budget":
        qos.latency_budget.duration = policy.duration
        applied[name] = str(policy.duration)
      else:
        getattr(qos, name).kind = policy.kind
        applied[name] = str(policy.kind)
    except Exception as e:
      applied[name] = f"not applied ({e})"

  # Data representation: offer BOTH XCDR1 and XCDR2, always - never just what the
  # writer advertised.
  #
  # Mirroring is wrong here. A Cyclone DDS writer advertises an EMPTY
  # representation sequence while actually using XCDR2, so mirroring left the
  # probe on the Connext default. Cyclone then declined to match the reader from
  # its side, and the observable result was an asymmetric match: rti_doctor
  # reported "matched" while zero data and zero heartbeats arrived.
  #
  # Offering the superset is also what RTI's own cross-vendor guidance
  # recommends for readers, and it cannot cause a false finding: a reader that
  # accepts both formats never becomes the reason a match fails.
  try:
    qos.data_representation.value = [int(dds.DataRepresentation.XCDR),
                                     int(dds.DataRepresentation.XCDR2)]
    applied["data_representation"] = ("XCDR1, XCDR2 (superset offered for "
                                      "cross-vendor matching)")
  except Exception as e:
    applied["data_representation"] = f"not applied ({e})"

  return qos, applied


def build_subscriber(participant, endpoint):
  """Subscriber matching the writer's partition and presentation, if any."""
  sub_qos = dds.SubscriberQos()
  needed = False
  applied = {}

  partition = endpoint.partition
  names = compat.get(partition, "name", None) if partition is not None else None
  if names:
    try:
      sub_qos.partition.name = names
      applied["partition"] = ", ".join(str(n) for n in names)
      needed = True
    except Exception as e:
      applied["partition"] = f"not applied ({e})"

  presentation = endpoint.presentation
  if presentation is not None:
    try:
      sub_qos.presentation.access_scope = presentation.access_scope
      sub_qos.presentation.coherent_access = presentation.coherent_access
      sub_qos.presentation.ordered_access = presentation.ordered_access
      applied["presentation"] = str(presentation.access_scope)
      needed = True
    except Exception as e:
      applied["presentation"] = f"not applied ({e})"

  subscriber = dds.Subscriber(participant, sub_qos) if needed else dds.Subscriber(participant)
  return subscriber, applied


def build_writer_qos(endpoint):
  """Writer QoS that offers the selected reader's advertised policies.

  `applied` records the VALUE set, not the policy object. Recording `str(policy)`
  rendered every line of the report's applied-QoS block as
  `<rti.connextdds.Deadline object at 0x...>`, which is the one part of the
  report an operator reads to check the probe requested what it claims - so it
  was unreadable exactly where it mattered. Matches `build_reader_qos`, which
  has always recorded values.
  """
  qos = dds.DataWriterQos()
  applied = {}

  if endpoint.reliability is not None:
    try:
      qos.reliability.kind = endpoint.reliability.kind
      applied["reliability"] = str(endpoint.reliability.kind)
      max_blocking = compat.get(endpoint.reliability, "max_blocking_time", None)
      if max_blocking is not None:
        qos.reliability.max_blocking_time = max_blocking
    except Exception as error:
      applied["reliability"] = f"not applied ({error})"

  for name in ("durability", "latency_budget", "deadline", "ownership",
               "destination_order", "liveliness"):
    policy = getattr(endpoint, name, None)
    if policy is None:
      continue
    try:
      if name == "deadline":
        qos.deadline.period = policy.period
        applied[name] = str(policy.period)
      elif name == "latency_budget":
        qos.latency_budget.duration = policy.duration
        applied[name] = str(policy.duration)
      else:
        getattr(qos, name).kind = policy.kind
        applied[name] = str(policy.kind)
    except Exception as error:
      applied[name] = f"not applied ({error})"

  # A writer's list is NOT symmetric with a reader's, and Connext enforces it:
  # `DDS_DataWriterQos_is_consistentI` rejects a writer outright with
  # "representation. Writer can't have more than one." A reader's list is the
  # set it ACCEPTS, so offering the superset there is free and correct; a writer
  # declares the single encoding it will serialize, so exactly one value is
  # legal. Setting two here cost the writer its creation entirely - measured
  # against a live TRANSIENT_LOCAL reader on 2026-08-13, where the probe
  # reported "Failed to create DataWriter" and diagnosed nothing.
  #
  # The one value is the reader's own first choice where it advertised any, so
  # what goes on the wire is something the reader has said it accepts.
  # Otherwise XCDR1, which is what an empty advertisement means for Connext (see
  # `records.representation_text`) and the safer guess for any other vendor.
  known = (int(dds.DataRepresentation.XCDR), int(dds.DataRepresentation.XCDR2))
  requested = [i for i in records.representation_ids(
      getattr(endpoint, "representation", None)) if i in known]
  chosen = requested[0] if requested else int(dds.DataRepresentation.XCDR)
  try:
    qos.data_representation.value = [chosen]
    name = records.REPRESENTATION_NAMES.get(chosen, f"id={chosen}")
    applied["data_representation"] = (
        f"{name} (a writer may declare exactly one; "
        + ("mirroring the reader's first advertised representation)"
           if requested else "the reader advertised none, so the default)"))
  except Exception as error:
    applied["data_representation"] = f"not applied ({error})"

  return qos, applied


def build_publisher(participant, endpoint):
  """Publisher matching the selected reader's partition and presentation."""
  qos = dds.PublisherQos()
  needed = False
  applied = {}
  names = compat.get(getattr(endpoint, "partition", None), "name", None)
  if names:
    try:
      qos.partition.name = names
      applied["partition"] = ", ".join(str(name) for name in names)
      needed = True
    except Exception as error:
      applied["partition"] = f"not applied ({error})"
  presentation = getattr(endpoint, "presentation", None)
  if presentation is not None:
    try:
      qos.presentation.access_scope = presentation.access_scope
      qos.presentation.coherent_access = presentation.coherent_access
      qos.presentation.ordered_access = presentation.ordered_access
      applied["presentation"] = str(presentation.access_scope)
      needed = True
    except Exception as error:
      applied["presentation"] = f"not applied ({error})"
  publisher = dds.Publisher(participant, qos) if needed else dds.Publisher(participant)
  return publisher, applied


def _publication_key(reader, handle):
  """Builtin key text of one matched publication, or None when unreadable.

  Formatted exactly as discovery._endpoint_from_data formats EndpointRecord.key,
  so the two can be compared directly.
  """
  getter = compat.get(reader, "matched_publication_data", None)
  if not callable(getter):
    return None
  try:
    data = getter(handle)
  except Exception:
    return None
  value = compat.get(compat.get(data, "key", None), "value", None)
  return None if value is None else str(value)


def scan_matched_publications(reader, endpoint):
  """`(target_handles, others, unreadable)` for `endpoint`, or None.

  The one implementation of "which of this reader's matched publications ARE
  the selected writer", shared by the probe and by the live data view so the two
  can never disagree about whose samples they are showing. It reports counts and
  draws no conclusion; `_correlate` owns what the probe records, and it is the
  only caller that touches a ProbeResult.

  None means the selected writer cannot be identified at all - the binding does
  not expose matched publications, or an unreadable key could have been the
  writer we are looking for. It is never "no match".
  """
  handles = compat.get(reader, "matched_publications", None)
  if handles is None:
    return None
  try:
    handles = list(handles)
  except TypeError:
    return None

  target, others, unreadable = set(), 0, 0
  for handle in handles:
    key = _publication_key(reader, handle)
    if key is None:
      unreadable += 1
    elif key == endpoint.key:
      target.add(str(handle))
    else:
      others += 1

  # An empty target set is only a conclusion when EVERY publication resolved.
  # An unreadable key could have been the selected writer, and reporting "never
  # matched" from that would be the exact false certainty this exists to
  # prevent. Covers the all-unreadable case too.
  if not target and unreadable:
    return None
  return target, others, unreadable


def _correlate(reader, endpoint, result):
  """`scan_matched_publications`, recorded onto a ProbeResult.

  Returns None when the selected writer cannot be identified - see the scan. A
  None return is not "no match": it means observations stay topic-scoped and no
  finding may claim they describe the selected writer.

  An empty set IS a conclusion: the reader matched, or failed to match, and the
  selected writer was not among the publications it matched.
  """
  def uncorrelated():
    """Every field describing correlation, cleared together.

    `correlated` used to be a latch: set True on success and never cleared, so
    a later poll that could not resolve a publication left `correlated=True`
    beside a topic-wide matched_count and stale other/unreadable counts. Every
    consumer then read a writer-scoped answer off topic-wide data - the scope
    line claimed publication-handle correlation, and check_incompatible_qos
    could promote a topic-level WARN into a writer-scoped ERROR.
    The three fields must always describe the same reading.
    """
    result.correlated = False
    result.matched_other_count = 0
    result.matched_unreadable_count = 0
    return None

  scan = scan_matched_publications(reader, endpoint)
  if scan is None:
    return uncorrelated()
  target, others, unreadable = scan

  result.correlated = True
  # Current values, deliberately NOT a running max. `attributable` and
  # `exclusive` are present-tense questions: a writer that matched for one poll
  # iteration and departed must not permanently downgrade a real ERROR to a
  # topic-level WARN, nor permanently stop crediting the target's samples.
  # _snapshot_statuses calls this last, so the final value is the authoritative
  # post-window reading. matched_count stays a max - a transient match is still
  # a match.
  result.matched_other_count = others
  result.matched_unreadable_count = unreadable
  return target


def sample_is_target(sample, target_handles, exclusive):
  """Is this sample from the selected writer?

  When the reader matched only the selected writer, every sample on the topic is
  necessarily its own, so an unreadable publication_handle is safe to attribute.
  When other writers are matched too it is not, and the sample is counted as
  another writer's rather than credited to the target - an unattributable sample
  must never become evidence that the selected writer is delivering data.
  """
  handle = compat.get(sample.info, "publication_handle", None)
  if handle is None:
    return exclusive
  return str(handle) in target_handles


#: How many taken samples the Data view keeps, and how much of each one. The
#: probe stops as soon as it has a walked sample and a match, so in practice
#: this holds the first non-empty `take()` rather than a recording of the topic:
#: a diagnostic that buffered a fast writer's whole stream would become a load
#: on the system it is measuring. `DATA_SAMPLE_LIMIT` is far longer than
#: `sample_repr`'s default because the Data view's entire purpose is showing
#: the payload, and a rich type truncated at 800 characters shows a fragment.
DATA_SAMPLE_COUNT = 20
DATA_SAMPLE_LIMIT = 4000


def collect_sample_text(result, data):
  """Record one sample's text for the report's Data section, or decline to.

  Bounded in count and in cost, and the cost is the less obvious one:
  `sample_repr` serializes the WHOLE payload and truncates afterwards, so every
  text costs a full to_json() regardless of the limit. Twenty of them inside the
  probe's timed window is nothing for a telemetry struct and twenty
  multi-megabyte serializations on a large-data topic - paid by every probe, the
  CLI's and the matrix children's included, where before this section existed
  exactly one was paid.

  A text that comes back at the limit is the signal that this payload is large,
  so the first one to hit it is the last one collected: for a big type the cost
  returns to the single serialization it always was, and a small type still gets
  its whole window. `sample_texts_capped` is how the report says which of those
  two happened.
  """
  if len(result.sample_texts) >= DATA_SAMPLE_COUNT or result.sample_texts_capped:
    return
  text = sample_repr(data, limit=DATA_SAMPLE_LIMIT)
  result.sample_texts.append(text)
  if len(text) >= DATA_SAMPLE_LIMIT:
    result.sample_texts_capped = True


#: How long the isolation sweep waits for the probe participant's own discovery
#: to produce the selected endpoint. It is a separate budget from the probe
#: window and is spent before it, so isolating cannot eat the observation time
#: the report cites. Three seconds is well past the sub-second SPDP/SEDP
#: round trip measured on a local domain, and short enough that a target which
#: never appears does not double the length of the pass.
ISOLATION_TIMEOUT = 3.0
ISOLATION_POLL = 0.1


def _builtin_endpoint_reader(participant, is_writer):
  """The builtin reader announcing the peers that could compete with the target.

  A WRITER target competes with other writers, so the peers to enumerate are
  publications; a READER target competes for nothing, but the probe creates a
  writer, and ignoring the other readers is what keeps a consenting
  `--write-samples` injection from reaching an application that was never
  selected.
  """
  return compat.get(participant,
                    "publication_reader" if is_writer else "subscription_reader",
                    None)


def _ignore_peer(participant, is_writer, handle):
  """Ignore one discovered peer, permanently, on THIS participant.

  Named for what it costs. There is no un-ignore in DDS: the effect lasts for
  the life of the participant, which is why `probe_endpoint` refuses to do this
  unless its caller has said the participant is disposable.
  """
  name = "ignore_datawriter" if is_writer else "ignore_datareader"
  method = compat.get(participant, name, None)
  if not callable(method):
    raise AttributeError(f"this Connext binding has no {name}()")
  method(handle)


def isolation_sweep(participant, endpoint, result, seen):
  """Ignore every peer on the target topic that is not the target.

  Scoped to the target TOPIC on purpose. The probe creates exactly one entity on
  one topic, so a peer on any other topic cannot match it, cannot take exclusive
  ownership from it and cannot receive an injected sample - ignoring those would
  be a no-op that filled the report's "what we did" list with hundreds of
  irrelevant lines on a system of any size. The report says the scope out loud
  rather than implying it covers everything.

  `seen` carries across calls so each peer is ignored once and the sweep can be
  re-run cheaply during the probe window to catch a late joiner. Returns whether
  the selected endpoint itself has been seen in discovery yet.

  `take()`, not `read()`, and the difference is what makes re-sweeping cheap
  enough to do on a timer. `read()` returns every publication in the domain on
  every call, so a sweep repeated at 10 Hz by the probe and 5 Hz by the Data
  tab's event loop re-copied the entire discovery cache each tick - measured at
  20 records per tick against 20 writers, where `take()` costs 20 once and 0
  thereafter. It is safe only because this participant is disposable and nobody
  else consumes its builtin readers: `create_probe_participant` passes
  `registry=None` precisely so no listener is installed on them. Do not give
  that participant a registry without revisiting this.

  Raises only if the peers cannot be enumerated at all; a failure to ignore one
  peer is recorded and the sweep continues, because isolating three of four
  writers is a materially different (and reportable) outcome from isolating none.
  """
  reader = _builtin_endpoint_reader(participant, endpoint.is_writer)
  if reader is None:
    kind = "publication" if endpoint.is_writer else "subscription"
    raise AttributeError(
        f"this Connext binding exposes no builtin {kind} reader, so the peers "
        f"on this topic cannot be enumerated")

  for sample in reader.take():
    info = compat.get(sample, "info", None)
    if not compat.get(info, "valid", False):
      # Includes the peers this sweep has already ignored: Connext disposes
      # their builtin instances, so they arrive invalid from here on.
      continue
    data = compat.get(sample, "data", None)
    if compat.get(data, "topic_name", None) != endpoint.topic_name:
      continue
    key = str(compat.get(compat.get(data, "key", None), "value", "") or "")
    if not key or key in seen:
      continue
    seen.add(key)
    if key == endpoint.key:
      result.isolation_target_seen = True
      continue
    record = {
        "kind": "writer" if endpoint.is_writer else "reader",
        "key": key,
        "topic": endpoint.topic_name,
        "type_name": compat.get(data, "type_name", "") or "",
        "participant_key": str(compat.get(
            compat.get(data, "participant_key", None), "value", "") or ""),
    }
    try:
      _ignore_peer(participant, endpoint.is_writer,
                   compat.get(info, "instance_handle", None))
    except Exception as error:
      result.ignore_failures.append(
          dict(record, error=f"{type(error).__name__}: {error}"))
      logging.error(f"[probe] could not ignore {record['kind']} {key}: {error}")
      continue
    result.ignored.append(record)
    logging.info(f"[probe] ignored {record['kind']} {key} on "
                 f"'{endpoint.topic_name}' to isolate the selected endpoint")
  return result.isolation_target_seen


def isolate_endpoint(participant, endpoint, result, timeout=ISOLATION_TIMEOUT,
                     poll=ISOLATION_POLL):
  """Ignore the target's competitors BEFORE the probe creates its own entity.

  Order is the whole point. Ignoring after the probe's reader already matched a
  competing writer works - Connext unmatches it and re-arbitrates ownership -
  but samples the competitor had already put in the reader cache are still
  delivered afterwards, so the report has to caveat its own sample counts.
  Sweeping first was measured on 2026-08-31 against two EXCLUSIVE writers of
  equal strength on one instance: pre-ignored, the selected writer delivered 21
  samples with `ownership_dropped_sample_count = 0` and no tail from the
  ignored one; ignoring after the match instead left a sample from the ignored
  writer still to be taken.

  Never raises. A failure here must leave a probe that still runs and a report
  that says isolation did not happen, not no report at all.

  Returns the set of peer keys already handled, for reuse by later sweeps.
  """
  start = time.monotonic()
  seen = set()
  try:
    deadline = start + max(0.0, timeout)
    while True:
      if isolation_sweep(participant, endpoint, result, seen):
        break
      if time.monotonic() >= deadline:
        break
      time.sleep(poll)
    result.isolated = True
  except Exception as error:
    result.isolation_error = f"{type(error).__name__}: {error}"
    logging.error(f"[probe] isolation failed on '{endpoint.topic_name}': {error}")
  finally:
    result.isolation_elapsed = time.monotonic() - start
  return seen


def resweep(participant, endpoint, result, seen):
  """Re-run the sweep after the fact, for a peer that joined late.

  Public because the live Data feed calls it too: it is open for as long as an
  operator watches, so a writer joining later is ordinary there rather than a
  corner case.

  Best-effort by construction: the pre-probe sweep is what the report's
  guarantees rest on, and a failure here must not retract an isolation that
  already happened, so it records the error and leaves `isolated` alone.
  """
  try:
    isolation_sweep(participant, endpoint, result, seen)
  except Exception as error:
    result.isolation_error = f"{type(error).__name__}: {error}"


def probe_endpoint(participant, endpoint, timeout=10.0, poll=0.1,
                   write_samples=False, isolate=False, isolation_error=None):
  """Create a reader for `endpoint`, observe it for `timeout`, then tear down.

  Never raises: any failure is recorded on the result so the report can explain
  it. Always closes what it created.

  `write_samples` only reaches the reader-target path, where the probe creates a
  writer. A writer target is observed by reading what it already publishes, so
  nothing is ever injected there.

  `isolate` asks the probe to ignore every other endpoint on this topic, so the
  selected one is the only peer it can talk to. It defaults to OFF here and is
  turned on by the caller, and that split is the safety rule rather than a
  style choice: ignoring is irreversible and lasts for the life of the
  participant, so only a caller that knows the participant is disposable may ask
  for it. `engine.Session` owns that knowledge - it creates the throwaway
  participant - and this function never decides it for itself.

  `isolation_error` is how that caller reports a disposable participant it could
  not create. The probe then runs un-isolated on the shared participant, and the
  report says so instead of quietly claiming an isolation that never happened.
  """
  result = ProbeResult()
  result.attempted = True
  result.isolation_requested = bool(isolate) or isolation_error is not None
  result.isolation_error = isolation_error

  if not endpoint.is_writer:
    return probe_reader_endpoint(participant, endpoint, timeout, poll,
                                 write_samples=write_samples, isolate=isolate,
                                 isolation_error=isolation_error)
  if endpoint.type is None:
    result.create_error = "no type information available, cannot create a reader"
    return result

  subscriber = topic = reader = None
  isolation_seen = set()
  start = time.monotonic()
  try:
    if isolate:
      isolation_seen = isolate_endpoint(participant, endpoint, result)
      # The observation window starts after the sweep. `elapsed` is quoted in
      # findings as how long the probe watched for a match and for data, and
      # time spent waiting on our own discovery is not that.
      start = time.monotonic()
    topic = dds.DynamicData.Topic(participant, endpoint.topic_name, endpoint.type)
    subscriber, sub_applied = build_subscriber(participant, endpoint)
    reader_qos, qos_applied = build_reader_qos(endpoint)
    result.applied_reader_qos = {**sub_applied, **qos_applied}

    listener = _DiagnosticListener(result)
    mask = (dds.StatusMask.REQUESTED_INCOMPATIBLE_QOS
            | dds.StatusMask.SAMPLE_LOST
            | dds.StatusMask.SAMPLE_REJECTED
            | dds.StatusMask.SUBSCRIPTION_MATCHED)
    reader = dds.DynamicData.DataReader(subscriber, topic, reader_qos, listener, mask)
    result.created = True

    deadline = start + timeout
    while time.monotonic() < deadline:
      if isolate and result.isolated:
        # A writer that joins mid-probe would otherwise be matched, and on an
        # EXCLUSIVE topic could take ownership away from the selected one
        # partway through the window - producing a report whose sample count
        # silently describes two different systems.
        resweep(participant, endpoint, result, isolation_seen)
      target_handles = _correlate(reader, endpoint, result)
      if target_handles is None:
        matched = compat.get_int(reader.subscription_matched_status, "current_count")
        if matched:
          result.matched_count = max(result.matched_count, matched)
      else:
        result.matched_count = max(result.matched_count, len(target_handles))
      # "Exclusive" means nothing else this reader matched could have produced
      # the sample - so an unresolvable publication counts against it too.
      exclusive = (result.matched_other_count == 0
                   and result.matched_unreadable_count == 0)

      for sample in reader.take():
        if not sample.info.valid:
          continue
        if target_handles is not None and not sample_is_target(
            sample, target_handles, exclusive):
          result.samples_other += 1
          continue
        result.samples_taken += 1
        collect_sample_text(result, sample.data)
        if result.walk is None:
          result.walk = typewalk.walk_sample(sample.data, endpoint.type)
          result.sample_repr = sample_repr(sample.data)

      # Stop early once there is a walked sample AND a match: nothing further
      # is learned by waiting, and a snappy probe is a usable probe.
      if result.walk is not None and result.matched_count:
        break
      time.sleep(poll)

    _snapshot_statuses(reader, topic, endpoint, result)
  except Exception as e:
    detail = f"{type(e).__name__}: {e}"
    if result.created:
      result.error = detail
    else:
      result.create_error = detail
    logging.error(f"[probe] {endpoint.topic_name}: {e}")
  finally:
    result.elapsed = time.monotonic() - start
    _close_all(reader, subscriber, topic, endpoint.topic_name)

  return result


def probe_reader_endpoint(participant, endpoint, timeout=10.0, poll=0.1,
                          write_samples=False, isolate=False,
                          isolation_error=None):
  """Create a matching DataWriter for a discovered reader and observe the match.

  `write_samples` is off by default and is the difference between an observer
  and a participant in the system under test. Everything else rti_doctor does is
  read-only; publishing puts synthetic samples into a topic a real application
  is subscribed to, and that application cannot tell them from production data.
  It is therefore an explicit, per-run decision - never a side effect of opening
  a report.

  Without it this still reports far more than a match: the writer's own protocol
  counters say whether it is heartbeating the reader and whether the reader is
  acknowledging, which is the reliable handshake seen from the side that can
  actually observe it. What it cannot do is prove delivery, and
  `wrote_samples=False` is what keeps the report from claiming otherwise.

  `isolate` matters more on this path than on the reader one. Ignoring the other
  READERS on the topic means a consenting `--write-samples` run reaches only the
  reader the operator selected: without it, every application subscribed to the
  topic receives the synthetic samples and cannot tell them from production
  data. Isolation therefore narrows the blast radius of the one thing rti_doctor
  does that is not read-only.
  """
  result = ProbeResult()
  result.attempted = True
  result.probe_kind = "writer"
  result.isolation_requested = bool(isolate) or isolation_error is not None
  result.isolation_error = isolation_error
  if endpoint.type is None:
    result.create_error = "no type information available, cannot create a writer"
    return result

  publisher = topic = writer = None
  isolation_seen = set()
  start = time.monotonic()
  try:
    if isolate:
      isolation_seen = isolate_endpoint(participant, endpoint, result)
      start = time.monotonic()
    topic = dds.DynamicData.Topic(participant, endpoint.topic_name, endpoint.type)
    publisher, publisher_applied = build_publisher(participant, endpoint)
    writer_qos, qos_applied = build_writer_qos(endpoint)
    result.applied_reader_qos = {**publisher_applied, **qos_applied}
    writer = dds.DynamicData.DataWriter(publisher, topic, writer_qos)
    result.created = True

    deadline = start + timeout
    while time.monotonic() < deadline:
      if isolate and result.isolated:
        # Re-swept for the same reason as on the reader path, and for one more:
        # a reader that joins after the sweep and before `_write_probe_samples`
        # would receive the injected samples despite never being selected.
        resweep(participant, endpoint, result, isolation_seen)
      target_handles = _correlate_subscriptions(writer, endpoint, result)
      if target_handles is None:
        matched = compat.get_int(writer.publication_matched_status, "current_count")
        if matched:
          result.matched_count = max(result.matched_count, matched)
      else:
        result.matched_count = max(result.matched_count, len(target_handles))
      if result.matched_count:
        break
      time.sleep(poll)

    # Only ever after a match, and only when asked. Writing into a topic whose
    # reader never matched us proves nothing and still injects the data.
    if write_samples and result.matched_count:
      _write_probe_samples(writer, endpoint, result,
                           remaining=max(0.0, deadline - time.monotonic()))

    _snapshot_writer_statuses(writer, topic, endpoint, result)
  except Exception as error:
    detail = f"{type(error).__name__}: {error}"
    if result.created:
      result.error = detail
    else:
      result.create_error = detail
    logging.error(f"[probe] {endpoint.topic_name}: {error}")
  finally:
    result.elapsed = time.monotonic() - start
    _close_all(writer, publisher, topic, endpoint.topic_name)
  return result


#: How many synthetic samples a consenting write-probe publishes. Enough that a
#: single dropped sample is visible as a shortfall rather than as total silence,
#: few enough that the injection stays trivially small.
PROBE_SAMPLE_COUNT = 3


def _write_probe_samples(writer, endpoint, result, remaining):
  """Publish synthetic samples and, when RELIABLE, wait for acknowledgment.

  Never raises: a write that fails is recorded and the rest of the probe still
  reports what it observed.
  """
  try:
    sample = dds.DynamicData(endpoint.type)
  except Exception as error:
    result.error = f"could not build a sample for this type: {error}"
    return
  written = 0
  for _ in range(PROBE_SAMPLE_COUNT):
    try:
      writer.write(sample)
      written += 1
    except Exception as error:
      result.error = f"write failed after {written} sample(s): {error}"
      break
  result.samples_written = written
  result.wrote_samples = written > 0
  if not written:
    return
  # A RELIABLE writer's acknowledgment is the proof of delivery; for BEST_EFFORT
  # there is nothing to wait for and `acknowledged` stays None rather than False,
  # which would read as "the peer did not acknowledge".
  if not _endpoint_is_reliable(endpoint):
    return
  try:
    writer.wait_for_acknowledgments(dds.Duration(seconds=int(max(1.0, remaining))))
    result.acknowledged = True
  except Exception:
    # Connext raises a timeout exception rather than returning a flag.
    result.acknowledged = False


def _endpoint_is_reliable(endpoint):
  kind = compat.get(getattr(endpoint, "reliability", None), "kind", None)
  if kind is None:
    return False
  name = compat.get(kind, "name", None) or str(kind)
  return "RELIABLE" in str(name).upper()


def _subscription_key(writer, handle):
  """Builtin key text of one matched subscription, or None when unreadable."""
  getter = compat.get(writer, "matched_subscription_data", None)
  if not callable(getter):
    return None
  try:
    data = getter(handle)
  except Exception:
    return None
  value = compat.get(compat.get(data, "key", None), "value", None)
  return None if value is None else str(value)


def _correlate_subscriptions(writer, endpoint, result):
  """`_correlate`, for the writer probe: which matched subscriptions ARE `endpoint`.

  Same three-valued contract - None means the selected reader could not be
  identified and every observation stays topic-scoped.
  """
  def uncorrelated():
    result.correlated = False
    result.matched_other_count = 0
    result.matched_unreadable_count = 0
    return None

  handles = compat.get(writer, "matched_subscriptions", None)
  if handles is None:
    return uncorrelated()
  try:
    handles = list(handles)
  except TypeError:
    return uncorrelated()

  target, others, unreadable = set(), 0, 0
  for handle in handles:
    key = _subscription_key(writer, handle)
    if key is None:
      unreadable += 1
    elif key == endpoint.key:
      target.add(str(handle))
    else:
      others += 1

  if not target and unreadable:
    return uncorrelated()

  result.correlated = True
  result.matched_other_count = others
  result.matched_unreadable_count = unreadable
  return target


def _snapshot_writer_statuses(writer, topic, endpoint, result):
  """Authoritative post-window read of the WRITER's own statuses.

  `subscription_matched` carries publication_matched here - the field is named
  for the report slot rather than the status - but the protocol and cache
  counters go to `writer_protocol` / `writer_cache` rather than to `protocol` /
  `cache`. Those two belong to a DataReader that this path never created, and
  filling them from a writer would make the report describe the wrong entity.
  """
  result.subscription_matched = writer.publication_matched_status
  target_handles = _correlate_subscriptions(writer, endpoint, result)
  if target_handles is None:
    matched = compat.get_int(result.subscription_matched, "current_count")
    if matched is not None:
      result.matched_count = max(result.matched_count, matched)
  else:
    result.matched_count = max(result.matched_count, len(target_handles))

  result.offered_incompatible_qos = compat.get(
      writer, "offered_incompatible_qos_status", None)
  protocol = compat.get(writer, "datawriter_protocol_status", None)
  result.writer_protocol = compat.snapshot(protocol, WRITER_PROTOCOL_COUNTERS)
  reliable = compat.get(writer, "reliable_writer_cache_changed_status", None)
  result.writer_cache = compat.snapshot(reliable, WRITER_CACHE_COUNTERS)

  inconsistent = compat.get(topic, "inconsistent_topic_status", None)
  result.inconsistent_topic_count = compat.get_int(inconsistent, "total_count")


def _snapshot_statuses(reader, topic, endpoint, result):
  """Authoritative post-window status read. Missing counters stay None."""
  result.subscription_matched = reader.subscription_matched_status
  # subscription_matched is topic-wide. Only fall back to it when the selected
  # writer could not be identified among the matched publications.
  target_handles = _correlate(reader, endpoint, result)
  if target_handles is None:
    matched = compat.get_int(result.subscription_matched, "current_count")
    if matched is not None:
      result.matched_count = max(result.matched_count, matched)
  else:
    result.matched_count = max(result.matched_count, len(target_handles))

  result.requested_incompatible_qos = compat.get(
      reader, "requested_incompatible_qos_status", None)
  result.sample_lost = compat.get(reader, "sample_lost_status", None)
  result.sample_rejected = compat.get(reader, "sample_rejected_status", None)

  protocol = compat.get(reader, "datareader_protocol_status", None)
  result.protocol = compat.snapshot(protocol, PROTOCOL_COUNTERS)
  cache = compat.get(reader, "datareader_cache_status", None)
  result.cache = compat.snapshot(cache, CACHE_COUNTERS)

  inconsistent = compat.get(topic, "inconsistent_topic_status", None)
  result.inconsistent_topic_count = compat.get_int(inconsistent, "total_count")


def _close_all(endpoint, container, topic, topic_name):
  """Close what a probe created, innermost first. Both probe paths use this."""
  for entity, label in ((endpoint, "endpoint"), (container, "publisher/subscriber"),
                        (topic, "topic")):
    if entity is None:
      continue
    try:
      entity.close()
    except Exception as e:
      logging.error(f"[probe] error closing {label} for '{topic_name}': {e}")


def sample_repr(data, limit=800):
  for accessor in ("to_json", "to_string"):
    method = compat.get(data, accessor, None)
    if callable(method):
      try:
        text = str(method())
        return text if len(text) <= limit else text[: limit - 3] + "..."
      except Exception:
        continue
  try:
    text = str(data)
  except Exception:
    return "(sample could not be rendered)"
  return text if len(text) <= limit else text[: limit - 3] + "..."
