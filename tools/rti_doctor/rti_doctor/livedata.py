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
publication-handle correlation, and the same sample rendering. A feed that
requested QoS the probe would not have, or credited another writer's samples to
this endpoint, would not be describing the endpoint on screen.
"""

import collections
import logging
import time

import rti.connextdds as dds

from . import probe

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

  def __init__(self, participant, endpoint):
    self.endpoint = endpoint
    self.received = 0
    self.others = 0
    self.dropped = 0
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
    try:
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
