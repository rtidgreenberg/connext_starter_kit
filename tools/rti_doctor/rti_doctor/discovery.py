"""Builtin-topic listeners and the discovery registry.

Unlike rti_spy, state lives in a DiscoveryRegistry instance rather than module
globals, because several checks need cross-endpoint queries (topic census,
assignability between two writers on one topic) and globals make those
untestable.
"""

import logging
import threading
import time

import rti.connextdds as dds

from . import compat, records
from .records import EndpointRecord, ParticipantRecord


_PARTICIPANT_FACTORY_QOS_LOCK = threading.Lock()


class DiscoveryRegistry:
  """Thread-safe-enough store of what we have discovered.

  Builtin listeners fire on Connext receive threads, the TUI timer polls
  participants on the asyncio thread, and system_scan reads from a worker
  thread. Python dict reads/writes are individually atomic under the GIL, but a
  Python-level comprehension over `dict.values()` is not: a concurrent insert or
  delete raises "dictionary changed size during iteration" mid-walk. So every
  query below materializes `list(...)` first - one atomic C-level copy - and
  filters the copy.
  """

  def __init__(self, type_wait=5.0):
    self.participants = {}
    self.endpoints = {}
    self.type_wait = type_wait
    self.active_domains = set()
    self.selected_domain = None

  # --- Mutation (called from builtin listeners) ------------------------------

  def upsert_participant(self, record):
    existing = self.participants.get(record.key)
    if existing is None:
      record.first_seen = time.monotonic()
      self.participants[record.key] = record
      logging.info(
          f"[discovery] participant '{record.name}' ip={record.ip} "
          f"vendor={record.vendor_name} rtps={record.protocol_text}")
      return record
    merged = _merge_participant(existing, record)
    self.participants[record.key] = merged
    return merged

  def upsert_endpoint(self, record):
    existing = self.endpoints.get(record.key)
    if existing is None:
      record.first_seen = time.monotonic()
      if record.type is not None:
        record.note_type(record.type)
      self.endpoints[record.key] = record
      logging.info(
          f"[discovery] {record.kind.lower()} topic='{record.topic_name}' "
          f"type='{record.type_name}' type_state={record.type_state}")
      return record
    merged = _merge_endpoint(existing, record)
    self.endpoints[record.key] = merged
    return merged

  def remove_endpoint(self, key):
    """Forget an endpoint after its builtin-topic instance is disposed."""
    return self.endpoints.pop(key, None)

  def remove_participant(self, key):
    """Forget a participant after its builtin-topic instance is disposed."""
    self.participants.pop(key, None)
    for endpoint in list(self.endpoints.values()):
      if endpoint.participant_key == key:
        self.endpoints.pop(endpoint.key, None)

  # --- Queries --------------------------------------------------------------

  def participant_list(self):
    return list(self.participants.values())

  def endpoint_list(self):
    return list(self.endpoints.values())

  def writers(self):
    return [e for e in self.endpoint_list() if e.is_writer]

  def readers(self):
    return [e for e in self.endpoint_list() if not e.is_writer]

  def endpoints_for(self, participant_key):
    return [e for e in self.endpoint_list() if e.participant_key == participant_key]

  def endpoints_on_topic(self, topic_name):
    return [e for e in self.endpoint_list() if e.topic_name == topic_name]

  def participant_for(self, endpoint):
    return self.participants.get(endpoint.participant_key)

  def find_writer(self, topic_name):
    """Lowest-keyed writer on a topic, preferring one with a resolved type.

    Sorted rather than "first discovered": dict order is arrival order, so an
    unsorted pick made `--topic` select a different writer between runs on a
    multi-writer topic, and with it a different verdict and exit code.
    """
    candidates = sorted((e for e in self.writers() if e.topic_name == topic_name),
                        key=lambda e: e.key)
    if not candidates:
      return None
    resolved = [e for e in candidates if e.type is not None]
    return (resolved or candidates)[0]

  def find_reader(self, topic_name):
    """Lowest-keyed reader on a topic, chosen exactly as `find_writer` chooses.

    Same tie-break, and for the same reason: dict order is arrival order, so an
    unsorted pick would make `--topic` select a different endpoint - and report a
    different verdict - between runs on a multi-reader topic.
    """
    candidates = sorted((e for e in self.readers() if e.topic_name == topic_name),
                        key=lambda e: e.key)
    if not candidates:
      return None
    resolved = [e for e in candidates if e.type is not None]
    return (resolved or candidates)[0]

  def find_endpoint(self, topic_name):
    """The endpoint `--topic` should diagnose: a writer if there is one.

    A writer is preferred because reading what it already publishes verifies
    delivery without writing anything. Falling back to a reader is what makes a
    reader-only topic diagnosable headless at all - before this, `--topic` on
    one exited "target absent" while the system scan listed the topic, and the
    reader-target probe was reachable only from the TUI.

    Deliberately NOT targetable, for now. On a multi-endpoint topic this picks
    one and the report does not say which, so the headless path cannot be aimed
    at the endpoint a TUI operator would have selected. See HL-1/HL-2 in
    `docs/IMPROVEMENT_BACKLOG.md`: the fix is a selector plus an enumeration to
    read selectors off, and it is scheduled rather than improvised here.
    """
    return self.find_writer(topic_name) or self.find_reader(topic_name)

  def topic_names(self):
    return sorted({e.topic_name for e in self.endpoint_list() if e.topic_name})

  def expire_type_waits(self, now=None):
    """Advance PENDING -> UNAVAILABLE for endpoints past the type-wait window."""
    changed = []
    for endpoint in list(self.endpoints.values()):
      if endpoint.expire_type_wait(self.type_wait, now=now):
        changed.append(endpoint)
        logging.info(
            f"[discovery] type_state for topic='{endpoint.topic_name}' "
            f"-> {endpoint.type_state}")
    return changed


def _merge_participant(existing, incoming):
  """Prefer newly-populated fields, never discard what we already knew.

  Discovery samples are re-delivered and later ones can be sparser (see
  `partial_configuration`), so a missing field in a new sample must not erase a
  value an earlier sample gave us.
  """
  for name in (
      "name", "ip", "domain_id", "vendor_id", "protocol_version",
      "product_version", "dds_builtin_endpoints",
      "available_builtin_endpoints_ext", "vendor_builtin_endpoints",
      "partial_configuration", "rtps_host_id", "rtps_app_id",
  ):
    value = getattr(incoming, name, None)
    # Only genuine absence is skipped. The old predicate was
    # `value not in (None, "", 0)`, which compares by equality - and False == 0
    # is True in Python. An incoming partial_configuration=False, the sample
    # that says discovery has now completed, was therefore read as "field
    # absent" and never applied: check_partial_configuration then fired on
    # every later report for that peer, with a remedy ("re-run once discovery
    # has settled") the user could never satisfy. A legitimate domain_id of 0
    # and a genuinely-zero endpoint mask were lost the same way.
    if value is None or value == "":
      continue
    setattr(existing, name, value)
  for name in ("default_unicast_locators", "transport_info"):
    value = getattr(incoming, name, None)
    if value:
      setattr(existing, name, value)
  return existing


def _merge_endpoint(existing, incoming):
  """Merge an endpoint update, preserving resolved type state.

  This mirrors rti_spy's merge_endpoint() intent, and is load-bearing for late
  type resolution: the re-delivered sample that finally carries the TypeObject
  must upgrade type_state, while a sparser later sample must not clear it.
  """
  for name in (
      "topic_name", "type_name", "kind", "participant_key", "vendor_id",
      "protocol_version", "reliability", "durability", "latency_budget", "deadline", "liveliness",
      "ownership", "destination_order", "presentation", "partition",
      "representation",
  ):
    value = getattr(incoming, name, None)
    # Written the same way as _merge_participant, and for the same reason:
    # `value not in (None, "")` compares by equality, and False == 0 is True in
    # Python. No field above is numeric or boolean today, so this is not a live
    # bug - but it is one added field away from being the exact defect that
    # discarded participant_configuration=False, and the trap is not worth
    # leaving set.
    if value is None or value == "":
      continue
    setattr(existing, name, value)
  for name in ("unicast_locators", "multicast_locators"):
    value = getattr(incoming, name, None)
    if value:
      setattr(existing, name, value)
  if incoming.type is not None:
    existing.note_type(incoming.type)
  return existing


# --- QoS setup ---------------------------------------------------------------

def configure_type_object_v1_only(qos):
  """Advertise inline TypeObject v1 and disable the TypeLookup v2 channel."""
  qos.resource_limits.type_code_max_serialized_length = 0
  qos.resource_limits.type_object_max_serialized_length = 65536
  type_lookup = getattr(dds.DiscoveryConfigBuiltinChannelKindMask,
                        "TYPE_LOOKUP_SERVICE", None)
  if type_lookup is not None:
    channels = qos.discovery_config.enabled_builtin_channels
    qos.discovery_config.enabled_builtin_channels = (
        dds.DiscoveryConfigBuiltinChannelKindMask(int(channels) & ~int(type_lookup)))


def configure_type_lookup_qos(qos):
  """Enable remote DynamicType discovery on Connext 7.7+ and earlier inline-type peers.

  Adapted from rti_spy. Deliberately does NOT set enabled_builtin_channels: the
  QoS default already enables everything each Connext version needs for remote
  DynamicType discovery. On 7.3.x the default is SERVICE_REQUEST (3), and on
  7.6+/7.7 the default already includes TYPE_LOOKUP_SERVICE. Explicitly
  overriding it caused two bugs in rti_spy: on 7.3.x, ALL (127) is a fine-grained
  bitmask the 7.3.x core's QoS consistency check rejects (only 0,
  SERVICE_REQUEST=3, or 0xFFFFFFFF are valid there); and setting it to
  SERVICE_REQUEST alone on 7.6+/7.7 narrowed the default down and disabled
  TYPE_LOOKUP_SERVICE, breaking remote type/writer discovery.

  request_types_filter="*" is the setting that matters most for a diagnostic
  tool: by default Connext only requests an unknown remote type when a local
  endpoint on the same topic needs it for matching. Without the filter, we would
  see remote writers but never trigger TypeLookup, leaving every type empty.

  Also deliberately does NOT touch type_object_max_serialized_length: setting it
  to 0 disables propagation of BOTH TypeObject v1 and v2. AUTO is correct.

  Returns a dict of what was applied, for the report's own-config section.
  """
  applied = {}
  try:
    discovery_config = qos.discovery_config
  except Exception as e:
    logging.warning(f"[configure_type_lookup_qos] no discovery_config: {e}")
    return applied

  if compat.has(discovery_config, "endpoint_type_object_lb_serialization_threshold"):
    try:
      discovery_config.endpoint_type_object_lb_serialization_threshold = -1
      applied["endpoint_type_object_lb_serialization_threshold"] = -1
    except Exception as e:
      logging.debug(f"[configure_type_lookup_qos] threshold not settable: {e}")

  if compat.has(discovery_config, "request_types_filter"):
    try:
      discovery_config.request_types_filter = "*"
      applied["request_types_filter"] = "*"
    except Exception as e:
      logging.debug(f"[configure_type_lookup_qos] request_types_filter not settable: {e}")
  else:
    # Worth surfacing: on a version without this, unmatched remote types may
    # never be requested, so "no type info" findings are less conclusive.
    applied["request_types_filter"] = compat.na_text()

  return applied


def configure_transport(qos):
  """Keep Connext's default transports and report the capture-relevant choice.

  RTI Network Capture records rti_doctor's participant on every transport it
  uses, including UDPv4 and shared memory. Restricting the probe to UDPv4 would
  test a different path from a same-host application pair, so Doctor leaves the
  participant transport policy untouched even when capture is disabled.
  """
  del qos
  return "Connext default transports (UDPv4 and shared memory enabled)"


def create_participant(domain_id, name="RTI DOCTOR", registry=None,
                       type_object_v1_only=False, network_capture_active=False):
  """Create a participant with builtin listeners attached before enabling.

  Listeners are installed while autoenable is off so no discovery sample is
  missed between construction and listener installation - the same ordering
  rti_spy uses.

  RTI Network Capture records the participant across its default UDPv4 and
  shared-memory transports. Doctor does not narrow the transport policy, whether
  or not participant capture is enabled.
  """
  qos = dds.DomainParticipantQos()
  qos.entity_factory.autoenable_created_entities = True
  try:
    qos.participant_name.name = name
  except Exception:
    pass
  if type_object_v1_only:
    configure_type_object_v1_only(qos)
  type_lookup_settings = configure_type_lookup_qos(qos)
  type_lookup_settings["transport"] = configure_transport(qos)
  type_lookup_settings["type_object_discovery"] = (
      "v1-only" if type_object_v1_only else "default (v2 TypeLookup enabled)")

  participant = None
  try:
    with _PARTICIPANT_FACTORY_QOS_LOCK:
      previous_factory_qos = dds.DomainParticipant.participant_factory_qos
      factory_qos = dds.DomainParticipantFactoryQos()
      for policy_name in ("entity_factory", "monitoring", "system_resource_limits"):
        setattr(factory_qos, policy_name, getattr(previous_factory_qos, policy_name))
      factory_qos.entity_factory.autoenable_created_entities = False
      try:
        dds.DomainParticipant.participant_factory_qos = factory_qos
        participant = dds.DomainParticipant(domain_id, qos=qos)
      finally:
        dds.DomainParticipant.participant_factory_qos = previous_factory_qos
    if registry is not None:
      participant.publication_reader.set_listener(
          PublicationListener(registry), dds.StatusMask.DATA_AVAILABLE)
      participant.subscription_reader.set_listener(
          SubscriptionListener(registry), dds.StatusMask.DATA_AVAILABLE)
    participant.enable()
  except Exception:
    if participant is not None:
      try:
        participant.close()
      except Exception:
        pass
    raise

  return participant, type_lookup_settings


#: The name the disposable probe participant announces itself under. Distinct
#: from the session participant's, because both are on the domain at once and an
#: operator watching discovery from a third tool has to be able to tell which of
#: rti_doctor's two participants they are looking at.
PROBE_PARTICIPANT_NAME = "RTI DOCTOR probe"


def create_probe_participant(domain_id, type_object_v1_only=False):
  """A participant for ONE probe, to be closed as soon as that probe is done.

  This exists so the probe can call `ignore_datawriter` / `ignore_datareader`.
  Those are irreversible and participant-wide: DDS has no un-ignore, so ignoring
  a peer on the long-lived session participant would hide it from discovery for
  the rest of the run. An operator who probed one writer on a two-writer topic
  would then find the other writer unprobeable, reported as `match.none`, with
  the cause being something rti_doctor itself did an hour earlier. Scoping the
  ignores to a participant that dies with the probe is what makes them safe, and
  it is the ONLY reason this is not just `self.participant`.

  Built from a fresh `DomainParticipantQos` configured the way `create_participant`
  configures the session participant - deliberately NOT a copy of that
  participant's applied QoS. Applied QoS carries resolved identity: the
  participant index, and the RTPS host/app/instance ids. Reusing it was measured
  on 2026-08-31 to fail two different ways - first
  "Participant index 1 is in use or led to an invalid port calculation", and
  then, once the index was reset, remote peers rejecting both participants with
  "compare immutable remote participant ... config RW" because the two claimed
  the same RTPS identity. The probe reader matched nothing at all. A fresh QoS
  object still picks up any XML/env profile the operator configured, because
  that is what Connext defaults a new QoS object to.

  No registry listeners: nothing needs to record what this participant
  discovers, and its builtin readers still collect discovery data without one,
  which is what the isolation sweep reads.
  """
  participant, _ = create_participant(
      domain_id, name=PROBE_PARTICIPANT_NAME, registry=None,
      type_object_v1_only=type_object_v1_only)
  return participant


# --- Builtin listeners -------------------------------------------------------

def _endpoint_from_data(data, kind):
  return EndpointRecord(
      key=str(compat.get(compat.get(data, "key", None), "value", "")),
      kind=kind,
      participant_key=str(compat.get(compat.get(data, "participant_key", None), "value", "")),
      topic_name=compat.get(data, "topic_name", "") or "",
      type_name=compat.get(data, "type_name", "") or "",
      type=compat.get(data, "type", None),
      vendor_id=compat.get(data, "rtps_vendor_id", None),
      protocol_version=compat.get(data, "rtps_protocol_version", None),
      reliability=compat.get(data, "reliability", None),
      durability=compat.get(data, "durability", None),
      latency_budget=compat.get(data, "latency_budget", None),
      deadline=compat.get(data, "deadline", None),
      liveliness=compat.get(data, "liveliness", None),
      ownership=compat.get(data, "ownership", None),
      destination_order=compat.get(data, "destination_order", None),
      presentation=compat.get(data, "presentation", None),
      partition=compat.get(data, "partition", None),
      representation=compat.get(data, "representation", None),
      unicast_locators=list(compat.get(data, "unicast_locators", []) or []),
      multicast_locators=list(compat.get(data, "multicast_locators", []) or []),
  )


def _drain_endpoints(reader, registry, kind, label):
  """Apply every sample in one take(), isolating per-sample failures.

  take() removes the samples from the reader's cache, so they are never
  redelivered. A single unparseable sample - one vendor's SEDP field that will
  not read, a locator whose str() raises - must not take the rest of the batch
  with it: losing endpoints silently makes rti_doctor report "none of its
  endpoints are visible", a fabricated diagnosis caused by its own dropped
  samples.
  """
  try:
    batch = list(reader.take())
  except Exception as e:
    logging.error(f"[{label}] take failed: {e}")
    return
  for index, (data, info) in enumerate(batch):
    try:
      if info.valid:
        registry.upsert_endpoint(_endpoint_from_data(data, kind))
      else:
        registry.remove_endpoint(_sample_key(data, info, reader))
    except Exception as e:
      logging.error(f"[{label}] sample {index + 1}/{len(batch)} skipped: {e}")


class PublicationListener(dds.PublicationBuiltinTopicData.DataReaderListener):
  """Discovers DataWriters via the DCPSPublication builtin topic."""

  def __init__(self, registry):
    super().__init__()
    self.registry = registry

  def on_data_available(self, reader):
    _drain_endpoints(reader, self.registry, "Writer", "PublicationListener")


class SubscriptionListener(dds.SubscriptionBuiltinTopicData.DataReaderListener):
  """Discovers DataReaders via the DCPSSubscription builtin topic.

  Note: SubscriptionBuiltinTopicData exposes no type_consistency field on any
  supported Connext version, so a remote reader's type-consistency requirement
  is not observable here and rti_doctor does not claim to check it.
  """

  def __init__(self, registry):
    super().__init__()
    self.registry = registry

  def on_data_available(self, reader):
    _drain_endpoints(reader, self.registry, "Reader", "SubscriptionListener")


def _key_text(holder):
  """`holder.key.value` rendered exactly as EndpointRecord.key stores it."""
  value = compat.get(compat.get(holder, "key", None), "value", None)
  if value is None:
    return None
  text = str(value)
  # A BuiltinTopicKey of all zeros is the unpopulated default, not an identity.
  # Keys with no digits at all are left alone - only an all-zero numeric key is
  # rejected.
  digits = [ch for ch in text if ch.isdigit()]
  if digits and all(ch == "0" for ch in digits):
    return None
  return text


def _sample_key(data, info, reader):
  """Builtin key for either a valid or disposed discovery sample.

  A disposal sample's `data` is often unpopulated - that is why the reader
  fallback exists. key_value() returns an instance of the topic's DATA type
  (PublicationBuiltinTopicData), not a BuiltinTopicKey, so the key is at
  `.key.value`: the previous one-hop `.value` read always returned None, making
  remove_endpoint("") a silent no-op and leaving departed endpoints in the
  registry forever.
  """
  key = _key_text(data)
  if key is not None:
    return key
  try:
    key = _key_text(reader.key_value(info.instance_handle))
  except Exception as e:
    # Some foreign builtin readers cannot recover a key from a disposal
    # instance handle. This affects only removal of an already-departed endpoint
    # from this short-lived observer cache; keep it in --debug-log rather than
    # presenting it as an operator warning during a compatibility experiment.
    logging.debug(f"[discovery] disposal sample could not be keyed: {e}")
    return ""
  if key is None:
    logging.debug("[discovery] disposal sample carried no usable key; the "
                  "departed endpoint stays in the registry")
    return ""
  return key


def _participant_from_data(data):
  """One ParticipantRecord from one ParticipantBuiltinTopicData sample.

  Split out of `refresh_participants` so the whole mapping - every field read,
  not only the sample fetch - sits inside the caller's per-handle guard, and so
  the binding field names it depends on can be asserted by a unit test rather
  than only by a live domain.
  """
  key_value = compat.get(compat.get(data, "key", None), "value", None)
  host_id = app_id = 0
  if key_value is not None:
    try:
      parts = [int(v) for v in key_value]
      if len(parts) >= 2:
        host_id, app_id = parts[0], parts[1]
    except (TypeError, ValueError):
      pass

  locators = list(compat.get(data, "default_unicast_locators", []) or [])
  name_policy = compat.get(data, "participant_name", None)

  return ParticipantRecord(
      key=str(key_value),
      name=compat.get(name_policy, "name", "") or "",
      ip=records.first_locator_ip(locators),
      domain_id=compat.get_int(data, "domain_id"),
      vendor_id=compat.get(data, "rtps_vendor_id", None),
      protocol_version=compat.get(data, "rtps_protocol_version", None),
      product_version=compat.get(data, "product_version", None),
      default_unicast_locators=locators,
      transport_info=list(compat.get(data, "transport_info", []) or []),
      dds_builtin_endpoints=compat.get_int(data, "dds_builtin_endpoints"),
      available_builtin_endpoints_ext=compat.get_int(
          data, "available_builtin_endpoints_ext"),
      vendor_builtin_endpoints=compat.get_int(data, "vendor_builtin_endpoints"),
      partial_configuration=compat.get(data, "partial_configuration", None),
      rtps_host_id=host_id,
      rtps_app_id=app_id,
  )


def refresh_participants(participant, registry):
  """Poll DCPSParticipant for remote participants and update the registry."""
  try:
    handles = participant.discovered_participants()
  except Exception as e:
    logging.error(f"[refresh_participants] {e}")
    return

  live_keys = set()
  unreadable = 0
  for handle in handles:
    # The whole per-handle body is isolated, not just the data fetch. Reading
    # the sample is only the first of several places a binding object can raise:
    # `transport_info` and `default_unicast_locators` invoke __bool__/__len__/
    # __iter__ on a Connext sequence, `first_locator_ip` iterates a locator
    # address, and `participant_name` invokes the policy's own accessors. An
    # exception from any of them used to leave the function, so one bad peer
    # dropped every peer after it AND skipped the departure sweep - and in the
    # TUI it escaped the set_interval callback entirely. This is the same
    # requirement `_drain_endpoints` documents for endpoints, and its reasoning
    # applies verbatim: losing peers silently makes rti_doctor report an empty
    # or shrinking domain, a fabricated diagnosis caused by its own failed read.
    try:
      record = _participant_from_data(
          participant.discovered_participant_data(handle))
    except Exception as e:
      logging.debug(f"[refresh_participants] unreadable participant: {e}")
      unreadable += 1
      continue

    live_keys.add(record.key)
    registry.upsert_participant(record)

  # Only a complete read proves a participant departed. A handle whose data
  # would not read is still live - it was returned by discovered_participants()
  # on this very call - but it contributed no key, so removing everything
  # outside live_keys would evict that peer AND every one of its endpoints,
  # and the next scan would report endpoint.none or blind.empty_domain: a
  # fabricated diagnosis caused by one transient binding error.
  if unreadable:
    logging.warning(f"[refresh_participants] {unreadable} participant(s) could not be "
                    "read; skipping departure sweep for this cycle")
    return

  for key in set(registry.participants) - live_keys:
    registry.remove_participant(key)
