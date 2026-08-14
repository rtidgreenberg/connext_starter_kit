"""Discovery records and the type-resolution state machine.

These are plain data objects built from builtin topic samples, deliberately
decoupled from the DDS objects so every check can be unit-tested with fakes.
"""

import ipaddress
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
  """The address a Locator carries, read according to its kind, or None.

  Connext stores every address as 16 bytes. For UDPv4 the address is the last 4
  of them, which is why this read the last four unconditionally - and on a UDPv6
  locator that printed the tail of a v6 address as a dotted quad: an address
  that exists nowhere, reported with no hint it was manufactured, and then
  judged for reachability by `static_discovery.check_locators`. A v6 locator now
  renders as v6.
  """
  address = compat.get(locator, "address", None)
  if address is None:
    return None
  try:
    octets = [int(b) for b in address]
  except (TypeError, ValueError):
    return None
  if compat.get_int(locator, "kind") == LOCATOR_KIND_UDPV6 and len(octets) >= 16:
    try:
      return str(ipaddress.IPv6Address(bytes(octets[-16:])))
    except (ValueError, TypeError):
      return None
  if len(octets) < 4:
    return None
  return ".".join(str(b) for b in octets[-4:])


#: RTPS locator kinds this tool distinguishes. UDPv4 is the only one a UDP
#: packet capture can observe at all, which is why SHMEM has to be nameable:
#: two participants on one host prefer shared memory, and their user data then
#: never reaches a network interface. A capture of that pair is empty for a
#: reason that has nothing to do with the endpoints being broken.
LOCATOR_KIND_UDPV4 = 1
LOCATOR_KIND_UDPV6 = 2
LOCATOR_KIND_SHMEM = 0x01000000

#: Every locator kind by the name `rti.connextdds.LocatorKind` gives it. Written
#: out rather than read from the binding because these records are deliberately
#: DDS-free: a table a fake locator can be tested against is worth more than one
#: that exists only when Connext imports.
#:
#: Kind 2 is UDPv6. The binding also spells 2 as `SHMEM_510`, which is what
#: Connext used for shared memory through 5.1.0 - a peer this tool does not
#: support, so the ambiguity is resolved in favour of the modern meaning.
LOCATOR_KIND_NAMES = {
    -1: "INVALID",
    0: "ANY",
    LOCATOR_KIND_UDPV4: "UDPv4",
    LOCATOR_KIND_UDPV6: "UDPv6",
    3: "INTRA",
    8: "TCPV4_LAN",
    9: "TCPV4_WAN",
    10: "TLSV4_LAN",
    11: "TLSV4_WAN",
    1000: "RESERVED",
    LOCATOR_KIND_SHMEM: "SHMEM",
}

#: Kinds whose sixteen address octets are not an IP address, and so must not be
#: rendered as one. They are all zeroes, which printed as "0.0.0.0" - and that
#: is exactly the unspecified-address fault `static_discovery._address_problem`
#: reports, so a SHMEM locator read as broken for having no IP address, which is
#: its ordinary condition.
NON_IP_LOCATOR_KINDS = frozenset((-1, 0, 3, 1000, LOCATOR_KIND_SHMEM))


def advertises_shared_memory(*owners):
  """Whether any of these records advertises a SHMEM locator.

  Takes several records because an endpoint may advertise no locators of its own
  and inherit its participant's, which is where SHMEM usually appears.
  """
  for owner in owners:
    if owner is None:
      continue
    for attribute in ("unicast_locators", "default_unicast_locators"):
      for locator in (compat.get(owner, attribute, None) or ()):
        if compat.get_int(locator, "kind") == LOCATOR_KIND_SHMEM:
          return True
  return False


def locator_kind_text(kind):
  """An RTPS locator kind by name, falling back to `kind=N` when unrecognized.

  A number is better than a wrong name: an unknown kind keeps its integer rather
  than being rounded to the nearest one this table happens to know.
  """
  if kind is None:
    return ""
  return LOCATOR_KIND_NAMES.get(kind, f"kind={kind}")


def locator_text(locator):
  """"ip:port (UDPv4)" for reports, degrading gracefully on odd locators.

  Named rather than numbered. `kind=16777216` is SHMEM and `kind=9` is
  TCPV4_WAN, and an operator reading a report should not have to know that - the
  kind is often the whole explanation for a finding (a pair on one host that
  talks over shared memory), so it has to be legible where the finding is.

  A non-IP locator prints its port and no address, for the reason in
  `NON_IP_LOCATOR_KINDS`.
  """
  kind = compat.get_int(locator, "kind")
  port = compat.get_int(locator, "port")
  if kind in NON_IP_LOCATOR_KINDS:
    text = f"port {port}" if port is not None else "no address"
  else:
    ip = locator_ip(locator) or "unknown"
    text = f"{ip}:{port}" if port is not None else ip
  name = locator_kind_text(kind)
  return f"{text} ({name})" if name else text


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
  advertises an EMPTY sequence in discovery.

  What that emptiness *means* was measured on 2026-08-11 by
  `test/test_data_representation_spike.py`, and the answer is narrower than this
  docstring used to claim. For a Connext writer an empty advertisement is not
  "says nothing about what it supports": a writer configured explicitly
  `[XCDR1]` advertises an empty sequence too, and both configurations match an
  XCDR1 reader while being refused by an XCDR2-only reader with
  `requested_incompatible_qos` naming DATA_REPRESENTATION. Empty means XCDR1.
  The label stays "not advertised" because that is what was *observed* on the
  wire, and because the same emptiness from a non-Connext writer has not been
  measured - see Q3 in `docs/DESIGN_DECISIONS.md` before treating it as a claim
  about any vendor.
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
