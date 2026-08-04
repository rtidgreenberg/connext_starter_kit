"""Builtin-topic listeners and the discovery registry.

Unlike rti_spy, state lives in a DiscoveryRegistry instance rather than module
globals, because several checks need cross-endpoint queries (topic census,
assignability between two writers on one topic) and globals make those
untestable.
"""

import logging
import time

import rti.connextdds as dds

from . import compat, records
from .records import EndpointRecord, ParticipantRecord


class DiscoveryRegistry:
  """Thread-safe-enough store of what we have discovered.

  Builtin listeners fire on Connext receive threads while the UI reads on the
  asyncio thread. Python dict reads/writes are individually atomic under the
  GIL, and every consumer takes a snapshot via the list/dict copies below, so no
  explicit lock is needed for this access pattern.
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
    return [e for e in self.endpoints.values() if e.is_writer]

  def readers(self):
    return [e for e in self.endpoints.values() if not e.is_writer]

  def endpoints_for(self, participant_key):
    return [e for e in self.endpoints.values() if e.participant_key == participant_key]

  def endpoints_on_topic(self, topic_name):
    return [e for e in self.endpoints.values() if e.topic_name == topic_name]

  def participant_for(self, endpoint):
    return self.participants.get(endpoint.participant_key)

  def find_writer(self, topic_name):
    """First writer on a topic, preferring one with a resolved type."""
    candidates = [e for e in self.writers() if e.topic_name == topic_name]
    if not candidates:
      return None
    resolved = [e for e in candidates if e.type is not None]
    return (resolved or candidates)[0]

  def topic_names(self):
    return sorted({e.topic_name for e in self.endpoints.values() if e.topic_name})

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
    if value not in (None, "", 0):
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
    if value not in (None, ""):
      setattr(existing, name, value)
  for name in ("unicast_locators", "multicast_locators"):
    value = getattr(incoming, name, None)
    if value:
      setattr(existing, name, value)
  if incoming.type is not None:
    existing.note_type(incoming.type)
  return existing


# --- QoS setup ---------------------------------------------------------------

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


def create_participant(domain_id, name="RTI DOCTOR", registry=None):
  """Create a participant with builtin listeners attached before enabling.

  Listeners are installed while autoenable is off so no discovery sample is
  missed between construction and listener installation - the same ordering
  rti_spy uses.
  """
  previous_factory_qos = dds.DomainParticipant.participant_factory_qos
  factory_qos = dds.DomainParticipantFactoryQos()
  for name in ("entity_factory", "monitoring", "system_resource_limits"):
    setattr(factory_qos, name, getattr(previous_factory_qos, name))
  factory_qos.entity_factory.autoenable_created_entities = False
  dds.DomainParticipant.participant_factory_qos = factory_qos

  qos = dds.DomainParticipantQos()
  try:
    qos.participant_name.name = name
  except Exception:
    pass
  type_lookup_settings = configure_type_lookup_qos(qos)

  participant = None
  try:
    participant = dds.DomainParticipant(domain_id, qos=qos)
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
  finally:
    dds.DomainParticipant.participant_factory_qos = previous_factory_qos

  return participant, type_lookup_settings


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


class PublicationListener(dds.PublicationBuiltinTopicData.DataReaderListener):
  """Discovers DataWriters via the DCPSPublication builtin topic."""

  def __init__(self, registry):
    super().__init__()
    self.registry = registry

  def on_data_available(self, reader):
    try:
      for data, info in reader.take():
        if info.valid:
          self.registry.upsert_endpoint(_endpoint_from_data(data, "Writer"))
        else:
          self.registry.remove_endpoint(_sample_key(data, info, reader))
    except Exception as e:
      logging.error(f"[PublicationListener] {e}")


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
    try:
      for data, info in reader.take():
        if info.valid:
          self.registry.upsert_endpoint(_endpoint_from_data(data, "Reader"))
        else:
          self.registry.remove_endpoint(_sample_key(data, info, reader))
    except Exception as e:
      logging.error(f"[SubscriptionListener] {e}")


def _sample_key(data, info, reader):
  """Builtin key for either a valid or disposed discovery sample."""
  key = compat.get(compat.get(data, "key", None), "value", None)
  if key is None:
    try:
      key = compat.get(reader.key_value(info.instance_handle), "value", None)
    except Exception:
      key = None
  return str(key) if key is not None else ""


def refresh_participants(participant, registry):
  """Poll DCPSParticipant for remote participants and update the registry."""
  try:
    handles = participant.discovered_participants()
  except Exception as e:
    logging.error(f"[refresh_participants] {e}")
    return

  live_keys = set()
  for handle in handles:
    try:
      data = participant.discovered_participant_data(handle)
    except Exception as e:
      logging.debug(f"[refresh_participants] unreadable participant: {e}")
      continue

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

    record = ParticipantRecord(
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
    live_keys.add(record.key)
    registry.upsert_participant(record)

  for key in set(registry.participants) - live_keys:
    registry.remove_participant(key)
