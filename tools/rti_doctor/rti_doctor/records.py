"""Discovery records and the type-resolution state machine.

These are plain data objects built from builtin topic samples, deliberately
decoupled from the DDS objects so every check can be unit-tested with fakes.
"""

import time
from dataclasses import dataclass, field

from . import compat, vendors

# --- Type resolution state ---------------------------------------------------
#
# With TypeObject v2, SEDP carries only a TypeIdentifier hash; Connext resolves
# the full TypeObject asynchronously over the TypeLookup service and then
# RE-DELIVERS the discovery sample for that endpoint. So the first sample having
# no `type` is normal, not a failure. Treating it as final is the single easiest
# way to produce a false "no type info" report, which is why this is a state
# machine with a wait window rather than a snapshot.

TYPE_PENDING = "pending"
TYPE_RESOLVED = "resolved"
TYPE_UNAVAILABLE = "unavailable"


@dataclass
class ParticipantRecord:
  """A remote DomainParticipant as seen through DCPSParticipant."""

  key: str
  name: str = ""
  ip: str = ""
  domain_id: int = None
  vendor_id: object = None
  protocol_version: object = None
  product_version: object = None
  default_unicast_locators: list = field(default_factory=list)
  transport_info: list = field(default_factory=list)
  dds_builtin_endpoints: int = None
  available_builtin_endpoints_ext: int = None
  vendor_builtin_endpoints: int = None
  partial_configuration: object = None
  rtps_host_id: int = 0
  rtps_app_id: int = 0
  first_seen: float = 0.0

  @property
  def vendor_name(self):
    return vendors.vendor_name(self.vendor_id)

  @property
  def vendor_hex(self):
    return vendors.vendor_hex(self.vendor_id)

  @property
  def protocol_text(self):
    return vendors.protocol_text(self.protocol_version)

  @property
  def is_rti(self):
    return vendors.is_rti(self.vendor_id)


@dataclass
class EndpointRecord:
  """A remote DataWriter or DataReader as seen through DCPSPublication/Subscription."""

  key: str
  kind: str = "Writer"  # "Writer" | "Reader"
  participant_key: str = ""
  topic_name: str = ""
  type_name: str = ""
  type: object = None
  vendor_id: object = None
  protocol_version: object = None
  # QoS relevant to RxO matching.
  reliability: object = None
  durability: object = None
  latency_budget: object = None
  deadline: object = None
  liveliness: object = None
  ownership: object = None
  destination_order: object = None
  presentation: object = None
  partition: object = None
  representation: object = None
  unicast_locators: list = field(default_factory=list)
  multicast_locators: list = field(default_factory=list)
  # Type resolution tracking.
  type_state: str = TYPE_PENDING
  first_seen: float = 0.0
  type_resolved_at: float = None

  @property
  def is_writer(self):
    return self.kind == "Writer"

  @property
  def vendor_name(self):
    return vendors.vendor_name(self.vendor_id)

  @property
  def type_resolution_delay(self):
    """Seconds between first discovery and type resolution, or None."""
    if self.type_resolved_at is None or not self.first_seen:
      return None
    return self.type_resolved_at - self.first_seen

  def note_type(self, dynamic_type, now=None):
    """Record a (possibly absent) type from a discovery sample.

    Only ever advances PENDING -> RESOLVED; a later sample without a type never
    un-resolves an endpoint, because discovery samples are re-delivered and a
    type-bearing one may be followed by a sparser update.
    """
    if dynamic_type is None:
      return
    if self.type is None:
      self.type = dynamic_type
    if self.type_state != TYPE_RESOLVED:
      self.type_state = TYPE_RESOLVED
      self.type_resolved_at = now if now is not None else time.monotonic()

  def expire_type_wait(self, wait_seconds, now=None):
    """Move PENDING -> UNAVAILABLE once the type-wait window has elapsed.

    Returns True when the state changed, so callers can log the transition.
    """
    if self.type_state != TYPE_PENDING:
      return False
    if self.type is not None:
      self.note_type(self.type, now=now)
      return True
    now = now if now is not None else time.monotonic()
    if not self.first_seen:
      return False
    if now - self.first_seen >= wait_seconds:
      self.type_state = TYPE_UNAVAILABLE
      return True
    return False


def locator_ip(locator):
  """IPv4 dotted-quad from a Locator's address bytes, or None.

  Connext stores the address as 16 bytes; for UDPv4 the address is the last 4.
  """
  address = compat.get(locator, "address", None)
  if address is None:
    return None
  try:
    octets = [int(b) for b in address]
  except (TypeError, ValueError):
    return None
  if len(octets) < 4:
    return None
  return ".".join(str(b) for b in octets[-4:])


def locator_text(locator):
  """"ip:port (kind=N)" for reports, degrading gracefully on odd locators."""
  ip = locator_ip(locator) or "unknown"
  port = compat.get_int(locator, "port")
  kind = compat.get_int(locator, "kind")
  text = f"{ip}:{port}" if port is not None else ip
  if kind is not None:
    text = f"{text} (kind={kind})"
  return text


def first_locator_ip(locators):
  for locator in locators or ():
    ip = locator_ip(locator)
    if ip:
      return ip
  return ""


def representation_ids(representation):
  """Data representation ids offered, as ints. Empty when unreadable.

  An empty list means "could not read", not "offers nothing" - callers must not
  treat it as evidence of incompatibility.
  """
  value = compat.get(representation, "value", None)
  if value is None:
    return []
  try:
    return [int(v) for v in value]
  except TypeError:
    try:
      return [int(value)]
    except (TypeError, ValueError):
      return []
  except ValueError:
    return []


#: Data representation id -> name. XCDR=0, XML=1, XCDR2=2 per XTypes; -1 is
#: Connext's AUTO sentinel, resolved from the type's extensibility.
REPRESENTATION_NAMES = {-1: "AUTO", 0: "XCDR1", 1: "XML", 2: "XCDR2"}


def representation_text(representation):
  """Readable representation list.

  An empty sequence is reported as "not advertised" rather than "unknown":
  verified against a live 7.7.0 writer, a writer using the default policy
  advertises an EMPTY sequence in discovery, which is readable but says nothing
  about what it supports. Calling that "unknown" invites the reader to infer an
  incompatibility that has not been observed.
  """
  if representation is None:
    return "unreadable"
  ids = representation_ids(representation)
  if not ids:
    return "not advertised"
  return ", ".join(REPRESENTATION_NAMES.get(i, f"id={i}") for i in ids)


def transport_text(transport_info):
  """Render participant transport_info entries for a report."""
  out = []
  for entry in transport_info or ():
    class_id = compat.get(entry, "class_id", None)
    size_max = compat.get_int(entry, "message_size_max")
    out.append(f"class={class_id} message_size_max={size_max}")
  return out


def policy_name(policy):
  """Readable name for a QoS policy kind value."""
  if policy is None:
    return "unknown"
  kind = compat.get(policy, "kind", compat.MISSING)
  if kind is not compat.MISSING and kind is not None:
    return str(kind)
  return str(policy)
