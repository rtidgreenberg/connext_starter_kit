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
    self.matched_count = 0
    self.samples_taken = 0
    self.walk = None
    self.sample_repr = ""
    # Status snapshots, taken after the probe window.
    self.subscription_matched = None
    self.requested_incompatible_qos = None
    self.sample_lost = None
    self.sample_rejected = None
    self.protocol = {}
    self.cache = {}
    self.inconsistent_topic_count = None
    self.applied_reader_qos = {}
    self.elapsed = 0.0
    self.listener_events = []

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
    self._log(f"REQUESTED_INCOMPATIBLE_QOS last_policy={policy}")

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


def probe_endpoint(participant, endpoint, timeout=10.0, poll=0.1):
  """Create a reader for `endpoint`, observe it for `timeout`, then tear down.

  Never raises: any failure is recorded on the result so the report can explain
  it. Always closes what it created.
  """
  result = ProbeResult()
  result.attempted = True

  if not endpoint.is_writer:
    result.create_error = "endpoint is a DataReader; only writers can be probed"
    return result
  if endpoint.type is None:
    result.create_error = "no type information available, cannot create a reader"
    return result

  subscriber = topic = reader = None
  start = time.monotonic()
  try:
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
      matched = compat.get_int(reader.subscription_matched_status, "current_count")
      if matched:
        result.matched_count = max(result.matched_count, matched)

      for sample in reader.take():
        if not sample.info.valid:
          continue
        result.samples_taken += 1
        if result.walk is None:
          result.walk = typewalk.walk_sample(sample.data, endpoint.type)
          result.sample_repr = _sample_repr(sample.data)

      # Stop early once there is a walked sample AND a match: nothing further
      # is learned by waiting, and a snappy probe is a usable probe.
      if result.walk is not None and result.matched_count:
        break
      time.sleep(poll)

    _snapshot_statuses(reader, topic, result)
  except Exception as e:
    result.create_error = f"{type(e).__name__}: {e}"
    logging.error(f"[probe] {endpoint.topic_name}: {e}")
  finally:
    result.elapsed = time.monotonic() - start
    _close_all(reader, subscriber, topic, endpoint.topic_name)

  return result


def _snapshot_statuses(reader, topic, result):
  """Authoritative post-window status read. Missing counters stay None."""
  result.subscription_matched = reader.subscription_matched_status
  matched = compat.get_int(result.subscription_matched, "current_count")
  if matched is not None:
    result.matched_count = max(result.matched_count, matched)

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


def _close_all(reader, subscriber, topic, topic_name):
  for entity, label in ((reader, "reader"), (subscriber, "subscriber"), (topic, "topic")):
    if entity is None:
      continue
    try:
      entity.close()
    except Exception as e:
      logging.error(f"[probe] error closing {label} for '{topic_name}': {e}")


def _sample_repr(data, limit=800):
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
