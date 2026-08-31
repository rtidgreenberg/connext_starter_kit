"""Live sample streaming for the Data view.

Deliberately a separate concern from `probe`, not an extension of it. A probe is
a bounded measurement: it creates a reader, samples statuses for a fixed window,
and always tears down, because a diagnostic that leaves entities behind changes
the system it is measuring. A live feed has the opposite shape - it lives
exactly as long as an operator is watching it - and folding an unbounded
lifetime into the one function whose whole contract is that it has none would
cost the probe the property everything else here relies on.

What the two DO share is how the reader is built, and that sharing is the point:
the same mirrored QoS from `probe.build_reader_qos` and `probe.build_subscriber`,
a topic built from the type that arrived over DISCOVERY, the same
publication-handle correlation, the same isolation sweep, and the same sample
rendering. A feed that requested QoS the probe would not have, or credited
another writer's samples to this endpoint, would not be describing the endpoint
on screen.

Isolation is shared for a sharper reason than tidiness. The feed's own
correlation - dropping samples whose publication handle is not the selected
writer's - runs in `poll()`, which is downstream of ownership arbitration: on a
topic whose writers offer OWNERSHIP EXCLUSIVE, the losing writer's samples are
discarded inside the middleware as `ownership_dropped_sample_count` and never
reach `poll()` to be sorted. Measured on 2026-08-31 against two EXCLUSIVE
writers of equal strength, the feed on the losing writer reported 0 received and
54 from other writers while 56 of its samples were dropped by ownership. So the
feed has to exclude the competitors the same way the probe does - by ignoring
them before its reader exists - or it shows an empty tab for a writer that is
publishing perfectly well.
"""

import collections
import logging
import time

import rti.connextdds as dds

from . import discovery, probe

#: How much of one sample the feed renders. The Data view's snapshot cap exists
#: because it holds a fixed list; the feed drops old samples out of a ring
#: buffer instead, so only the per-sample length needs bounding here.
SAMPLE_LIMIT = probe.DATA_SAMPLE_LIMIT

#: Samples RENDERED per poll, not taken per poll. `take()` returns copies of
#: everything available in one call, so the surplus is already out of the
#: middleware and cannot be left for the next tick: what a cap can do is bound
#: the rendering, and what it must not do is lose the surplus silently. Anything
#: past this is counted into `received` and `dropped` and reported in the
#: header, because "40 samples arrived" and "40 of 4000 are on screen" are
#: different statements about the writer.
BATCH_LIMIT = 40


class LiveSample:
  """One rendered arrival: the text, and when this process saw it."""

  __slots__ = ("number", "received_at", "text")

  def __init__(self, number, received_at, text):
    self.number = number
    self.received_at = received_at
    self.text = text

  @property
  def clock(self):
    """Arrival time as HH:MM:SS.mmm, local to the observer.

    Reception time, not source timestamp: this is the feed saying when the
    sample reached this reader, which is the only one of the two it can state
    without trusting the peer's clock.
    """
    stamp = time.strftime("%H:%M:%S", time.localtime(self.received_at))
    return f"{stamp}.{int((self.received_at % 1) * 1000):03d}"


class LiveSubscription:
  """An open reader on one discovered writer's topic, polled by the view.

  The caller owns the lifetime: whoever opens one must close it. That is the
  same obligation `probe` discharges internally, moved to the only place that
  can know when the operator has stopped watching.
  """

  def __init__(self, participant, endpoint, isolate=False, domain_id=None,
               type_object_v1_only=False):
    """Open a reader on `endpoint`'s topic, optionally isolated.

    `isolate` follows the probe's rule that only a caller who knows a
    participant is disposable may ignore on it - but the shapes differ, so the
    ownership does too. A probe ends, so `engine.Session` can create and close
    its participant around the call; a feed lives until an operator navigates
    away, and the only code that knows when that happened is `close()`. So the
    subscription owns the participant it ignores on, and closing the
    subscription is what releases both. `participant` stays the caller's shared
    one and is used only when isolation was not asked for, or could not be set
    up - in which case `isolation_error` records why and the feed still runs.
    """
    self.endpoint = endpoint
    self.received = 0
    self.others = 0
    self.dropped = 0
    # Isolation state, named exactly as `probe.ProbeResult` names it so that
    # `probe.isolate_endpoint` can record onto this object directly. The two
    # views then cannot drift about what was excluded: there is one sweep, and
    # it writes the same fields whichever of them called it.
    self.isolation_requested = bool(isolate)
    self.isolated = False
    self.isolation_error = None
    self.isolation_elapsed = 0.0
    self.isolation_target_seen = False
    self.ignored = []
    self.ignore_failures = []
    self._isolation_seen = set()
    # Assigned before the try below, because a failure in it calls close().
    self._own_participant = None
    # Whether the samples counted above are known to be THIS writer's. False
    # means the binding could not resolve the reader's matched publications, so
    # anything on the topic was counted - the probe carries the same three-valued
    # answer into its report, and a feed that showed topic-wide traffic under
    # this endpoint's name without saying so would be the false certainty
    # `scan_matched_publications` returns None to prevent.
    self.correlated = False
    # Consecutive failed polls, and the last reason. A poll that fails returns
    # nothing, which the view would otherwise render as "waiting for the first
    # sample" - this tool's own broken reader presented as the writer's silence.
    self.errors = 0
    self.last_error = ""
    self.applied_qos = {}
    self._closed = False
    self._topic = self._subscriber = self._reader = None
    if isolate:
      try:
        self._own_participant = discovery.create_probe_participant(
            domain_id, type_object_v1_only=type_object_v1_only)
        participant = self._own_participant
      except Exception as error:
        self.isolation_error = (f"could not create the disposable feed "
                                f"participant, so nothing was ignored: "
                                f"{type(error).__name__}: {error}")
        logging.error(f"[livedata] {self.isolation_error}")
    try:
      if self._own_participant is not None:
        # Before the reader exists, for the same reason the probe does it there:
        # a competitor ignored afterwards has already had its samples arbitrated
        # into, or out of, this reader's cache.
        self._isolation_seen = probe.isolate_endpoint(
            participant, endpoint, self)
      self._topic = dds.DynamicData.Topic(
          participant, endpoint.topic_name, endpoint.type)
      self._subscriber, subscriber_applied = probe.build_subscriber(
          participant, endpoint)
      reader_qos, qos_applied = probe.build_reader_qos(endpoint)
      self.applied_qos = {**subscriber_applied, **qos_applied}
      self._reader = dds.DynamicData.DataReader(
          self._subscriber, self._topic, reader_qos)
    except Exception:
      # A half-built subscription still owns entities; nothing else has a
      # reference to close them.
      self.close()
      raise

  def poll(self):
    """Rendered samples that arrived since the last call, oldest first.

    Returns `(samples, skipped)`. `skipped` counts valid samples from OTHER
    writers on this topic, which are dropped rather than shown: the view is
    about one selected endpoint, and a feed that mixed writers would be
    evidence for neither.

    Every valid sample from the target is counted into `received` even when only
    the newest `BATCH_LIMIT` of them are returned for display, and the shortfall
    is counted into `dropped`. A feed that quietly returned 40 of 4000 would let
    the header describe the writer's rate as this UI's refresh rate.

    Never raises - a poll that fails logs and reports nothing, because a stream
    that tears down the report on one bad take is worse than a stream with a
    gap.
    """
    if self._closed or self._reader is None:
      return [], 0
    try:
      if self._own_participant is not None and self.isolated:
        # Re-swept every poll, and it matters more here than in the probe: a
        # feed is open for as long as someone is watching it, so a writer
        # starting up minutes later is ordinary rather than a corner case, and
        # on an EXCLUSIVE topic it could take ownership away mid-stream.
        probe.resweep(self._own_participant, self.endpoint, self,
                      self._isolation_seen)
      scan = probe.scan_matched_publications(self._reader, self.endpoint)
      self.correlated = scan is not None
      target = scan[0] if scan is not None else None
      # Same rule as the probe: with nothing else matched, an unreadable
      # publication handle is safely this writer's; otherwise it is not.
      exclusive = scan is not None and scan[1] == 0 and scan[2] == 0
      # Selected first, rendered second, and only the tail is rendered.
      # `sample_repr` serializes a whole payload, so rendering every sample in a
      # burst and then discarding all but the last `BATCH_LIMIT` would bound the
      # memory and leave the CPU cost unbounded - thousands of serializations
      # inside a UI timer tick, which is the very burst `dropped` exists to
      # report. Holding the selected samples themselves is safe: `take()`
      # returns copies, and they do not outlive this call.
      kept = collections.deque(maxlen=BATCH_LIMIT)
      arrived = skipped = 0
      for sample in self._reader.take():
        if not sample.info.valid:
          continue
        if target is not None and not probe.sample_is_target(
            sample, target, exclusive):
          skipped += 1
          continue
        arrived += 1
        kept.append(sample.data)
      self.errors = 0
      self.last_error = ""
      self.received += arrived
      self.others += skipped
      self.dropped += arrived - len(kept)
      now = time.time()
      first = self.received - len(kept) + 1
      return ([LiveSample(first + index, now,
                          probe.sample_repr(data, SAMPLE_LIMIT))
               for index, data in enumerate(kept)], skipped)
    except Exception as error:
      self.errors += 1
      self.last_error = f"{type(error).__name__}: {error}"
      logging.error(f"[livedata] {self.endpoint.topic_name}: {error}")
      return [], 0

  def close(self):
    """Close what this opened, innermost first. Idempotent.

    Idempotent because the view closes on leaving the tab, on the screen being
    suspended, and on unmount, and those overlap - a second close must be a
    no-op rather than an exception in a teardown path.
    """
    self._closed = True
    for entity, label in ((self._reader, "reader"),
                          (self._subscriber, "subscriber"),
                          (self._topic, "topic")):
      if entity is None:
        continue
      try:
        entity.close()
      except Exception as error:
        logging.error(f"[livedata] error closing {label} for "
                      f"'{self.endpoint.topic_name}': {error}")
    self._reader = self._subscriber = self._topic = None
    # Last, after the entities it contains. Closing it is also what expires the
    # ignores: a feed participant left open would keep the writers it excluded
    # invisible to itself for as long as the process lived, and this is the only
    # path that can know the operator has stopped watching.
    if self._own_participant is not None:
      try:
        self._own_participant.close()
      except Exception as error:
        logging.error(f"[livedata] error closing the feed participant for "
                      f"'{self.endpoint.topic_name}': {error}")
      self._own_participant = None

  @property
  def closed(self):
    return self._closed


def why_not(endpoint):
  """Why a live feed cannot run for `endpoint`, or None when it can.

  One place for the refusals so the view states them identically wherever it
  asks - and so each stays distinguishable: "this target is a reader" and "this
  writer's type never resolved" are different facts with different remedies,
  and an empty feed for either would read as a silent writer.
  """
  if endpoint is None:
    return "This is a participant report, so there is no endpoint to read from."
  if not endpoint.is_writer:
    return ("The selected endpoint is a reader, so there is nothing arriving to "
            "show: a reader-target probe creates a writer and publishes only "
            "when asked.")
  if endpoint.type is None:
    return ("No type information reached discovery for this writer, so no "
            "reader can be created for it - see the Type tab.")
  return None
