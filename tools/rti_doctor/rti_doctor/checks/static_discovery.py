"""Rung 2 checks: vendor identification, locators, transports, security posture.

Everything here reads discovery data only - no reader is created, so these are
cheap enough to run on every row.
"""

import ipaddress
import socket

from .. import compat, records, vendors
from ..findings import RUNG_ENDPOINT, RUNG_PARTICIPANT, Finding, Severity


def _participant(context):
  if context.participant_record is not None:
    return context.participant_record
  if context.endpoint is not None and context.registry is not None:
    return context.registry.participant_for(context.endpoint)
  return None


def check_vendor_identify(context):
  """Report who the peer is. Informational, but the anchor for everything else."""
  participant = _participant(context)
  if participant is None:
    return []

  name = participant.vendor_name
  detail = [
      f"vendor = {name} (id {participant.vendor_hex})",
      f"RTPS protocol version = {participant.protocol_text}",
  ]
  product = vendors.product_text(participant.product_version, participant.vendor_id)
  if product:
    detail.append(f"product version = {product}")
  elif not participant.is_rti:
    detail.append("product version = not reported (RTI extension; "
                  "not meaningful for other vendors)")

  severity = Severity.INFO
  root_cause = ""
  remedy = ""
  if not vendors.is_recognized(participant.vendor_id):
    severity = Severity.WARN
    root_cause = ("The RTPS vendor id is not one rti_doctor recognizes, so no "
                  "vendor-specific guidance can be offered.")
    remedy = "Identify the implementation from its vendor id before interpreting other findings."
  elif not participant.is_rti and not vendors.is_validated(participant.vendor_id):
    root_cause = (f"{name} is recognized but is not part of rti_doctor's "
                  f"validation matrix, so vendor notes for it are unverified.")

  return [Finding(
      id="vendor.identify",
      rung=RUNG_PARTICIPANT,
      severity=severity,
      title=f"Peer implementation: {name}",
      observed="; ".join(detail),
      root_cause=root_cause,
      remedy=remedy,
      evidence={
          "vendor": name,
          "vendor_id": participant.vendor_hex,
          "rtps_protocol_version": participant.protocol_text,
          "product_version": product,
          "participant_name": participant.name,
      },
  )]


def check_vendor_notes(context):
  """Surface curated per-vendor interop caveats."""
  participant = _participant(context)
  if participant is None:
    return []
  notes = vendors.notes_for(participant.vendor_id)
  if not notes:
    return []

  out = []
  for index, (hint, text) in enumerate(notes):
    out.append(Finding(
        id="vendor.known_issues",
        rung=RUNG_PARTICIPANT,
        severity=Severity.WARN if hint == "warn" else Severity.INFO,
        title=f"{participant.vendor_name} interop note {index + 1}",
        observed=text,
        root_cause="",
        remedy="",
        evidence={"vendor": participant.vendor_name},
    ))
  return out


def _local_networks():
  """IPv4 networks this host is on, for reachability judgement.

  Uses the addresses of local interfaces via getaddrinfo on the hostname plus a
  UDP-connect trick for the default route. Best-effort: an empty result means
  "cannot judge", and the locator check then stays silent rather than guessing.
  """
  addresses = set()
  try:
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
      addresses.add(info[4][0])
  except Exception:
    pass
  try:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
      probe.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
      addresses.add(probe.getsockname()[0])
    finally:
      probe.close()
  except Exception:
    pass

  networks = set()
  for address in addresses:
    try:
      networks.add(ipaddress.ip_network(f"{address}/24", strict=False))
    except ValueError:
      continue
  return networks, addresses


def check_locators(context):
  """Advertised locator addresses we have reason to believe are unreachable."""
  endpoint = context.endpoint
  participant = _participant(context)
  if participant is None:
    return []

  locators = list(endpoint.unicast_locators) if endpoint is not None else []
  source = "endpoint unicast_locators"
  if not locators:
    locators = list(participant.default_unicast_locators)
    source = "participant default_unicast_locators"
  if not locators:
    return [Finding(
        id="locator.unroutable",
        rung=RUNG_PARTICIPANT,
        severity=Severity.WARN,
        title="No unicast locators advertised",
        observed="Neither the endpoint nor its participant advertised a unicast locator.",
        root_cause=("Without a unicast locator there is no address to send "
                    "user-data or reliable-protocol traffic to."),
        remedy="Check the peer's transport configuration and enabled_transports.",
    )]

  networks, local_addresses = _local_networks()
  problems = []
  for locator in locators:
    if not _is_ip_locator(locator):
      # Shared-memory and other non-IP locators legitimately carry a 0.0.0.0
      # address; judging them as IP addresses produced a false "unspecified
      # address" finding against every healthy local peer.
      continue
    ip = records.locator_ip(locator)
    if not ip:
      continue
    reason = _address_problem(ip, networks, local_addresses)
    if reason:
      problems.append((records.locator_text(locator), reason))

  if not problems:
    return []

  return [Finding(
      id="locator.unroutable",
      rung=RUNG_PARTICIPANT,
      severity=Severity.WARN,
      title="Peer advertises an address that may be unreachable from here",
      observed="; ".join(f"{text}: {reason}" for text, reason in problems),
      root_cause=(
          "A participant advertises the addresses it believes it owns. Behind "
          "Docker/NAT, on a VPN, or with several NICs, it can advertise an "
          "address that is meaningless on this host. Discovery over multicast "
          "still succeeds, so the peer appears - but reliable traffic sent to the "
          "advertised locator goes nowhere, which looks like 'matched but no data'."),
      remedy=("Confirm the peer is reachable at the advertised address (ping/"
              "route). If it is containerised, publish the correct host address "
              "or restrict the peer's transport to the shared network."),
      evidence={"source": source,
                "locators": [records.locator_text(l) for l in locators],
                "local_addresses": sorted(local_addresses)},
  )]


#: RTPS locator kinds whose address field is a real IP address. UDPv4 is 1 and
#: UDPv6 is 2; shared memory (0x01000000) and vendor transports are not IP and
#: must not be judged for reachability.
IP_LOCATOR_KINDS = (1, 2)


def _is_ip_locator(locator):
  kind = compat.get_int(locator, "kind")
  if kind is None:
    return True  # cannot tell; judging it is better than skipping silently
  return kind in IP_LOCATOR_KINDS


def _address_problem(ip, networks, local_addresses):
  """Why `ip` looks unreachable, or None when it looks fine."""
  try:
    address = ipaddress.ip_address(ip)
  except ValueError:
    return None

  if address.is_unspecified:
    return "unspecified address (0.0.0.0)"
  if address.is_loopback:
    if ip in local_addresses:
      return None
    return "loopback address, only reachable if the peer is on this host"
  if address.is_link_local:
    return "link-local address (169.254/16), typically an unconfigured interface"
  if str(address).startswith("172.17.") and not any(
      str(local).startswith("172.17.") for local in local_addresses):
    return ("default Docker bridge range, and this host has no address on that "
            "bridge, so it is probably not routable from here")

  # Deliberately NOT flagged: an address merely outside this host's own subnets.
  # Peers on another subnet are entirely normal in a routed network, and the real
  # prefix length is unknown here (assuming /24 would be a guess), so reporting it
  # would produce a warning on healthy systems - the fastest way to make a
  # diagnostic tool ignorable.
  return None


def check_no_multicast_locators(context):
  """Peer advertises no multicast locator for user traffic."""
  endpoint = context.endpoint
  if endpoint is None or not endpoint.is_writer:
    return []
  if endpoint.multicast_locators:
    return []
  return [Finding(
      id="locator.no_multicast",
      rung=RUNG_ENDPOINT,
      severity=Severity.INFO,
      title="Writer advertises no multicast locator",
      observed="endpoint multicast_locators is empty",
      root_cause=("User data will be delivered over unicast to each matched "
                  "reader. This is normal and usually intentional; it only "
                  "matters for fan-out efficiency, not correctness."),
      remedy="",
  )]


def check_transport(context):
  """Transport class mismatch, e.g. a shared-memory-only peer on another host."""
  participant = _participant(context)
  if participant is None or not participant.transport_info:
    return []

  entries = records.transport_text(participant.transport_info)
  class_ids = [str(compat.get(t, "class_id", "")) for t in participant.transport_info]
  joined = " ".join(class_ids).upper()

  has_udp = "UDP" in joined
  has_shmem = "SHMEM" in joined or "SHARED" in joined
  if has_udp or not class_ids:
    return []

  severity = Severity.WARN if has_shmem else Severity.INFO
  return [Finding(
      id="transport.class_mismatch",
      rung=RUNG_PARTICIPANT,
      severity=severity,
      title="Peer advertises no UDP transport",
      observed="; ".join(entries),
      root_cause=(
          "Cross-vendor interoperability needs a transport both sides implement, "
          "which in practice means UDPv4. A peer advertising only shared memory "
          "can only communicate with processes on the same host, and vendor-"
          "specific transports are not mutually intelligible at all."),
      remedy="Enable UDPv4 on the peer, or run both applications on one host.",
      evidence={"transport_info": entries},
  )]


def check_security_mismatch(context):
  """A secure peer while we are unsecure (or the reverse)."""
  participant = _participant(context)
  if participant is None:
    return []

  ext = participant.available_builtin_endpoints_ext
  base = participant.dds_builtin_endpoints
  if ext is None and base is None:
    return []

  # Secure builtin endpoints live in the high bits of the endpoint masks. We
  # cannot name individual bits portably across versions, so this only reports
  # the observed masks and lets the reader judge, rather than asserting a
  # specific security posture we cannot prove.
  own_secure = False
  if context.own_qos is not None:
    from .blind_spots import _property_value
    library = _property_value(context.own_qos, "com.rti.serv.load_plugin")
    own_secure = bool(library) and "secur" in str(library).lower()

  peer_secure_hint = bool(ext) and ext != base
  if not peer_secure_hint or own_secure:
    return []

  return [Finding(
      id="security.mismatch",
      rung=RUNG_PARTICIPANT,
      severity=Severity.INFO,
      title="Peer advertises extended builtin endpoints; security posture differs",
      observed=(f"dds_builtin_endpoints = {base}, "
                f"available_builtin_endpoints_ext = {ext}; "
                f"this participant has no security plugins loaded"),
      root_cause=(
          "The extended endpoint mask differs from the base mask, which is how "
          "secure builtin endpoints are advertised. If the peer requires DDS "
          "Security, an unsecure participant cannot complete discovery with it, "
          "and the symptom is an absent or non-matching endpoint."),
      remedy=("If the peer is a secure participant, rti_doctor must be run with "
              "matching security plugins, governance, and permissions to see it "
              "properly."),
      evidence={"dds_builtin_endpoints": base, "available_builtin_endpoints_ext": ext},
  )]


def check_partial_configuration(context):
  """Discovery data flagged incomplete - other fields are less trustworthy."""
  participant = _participant(context)
  if participant is None:
    return []
  value = participant.partial_configuration
  if value is None or not bool(value):
    return []
  return [Finding(
      id="discovery.partial",
      rung=RUNG_PARTICIPANT,
      severity=Severity.INFO,
      title="Participant discovery data is marked partial",
      observed="ParticipantBuiltinTopicData.partial_configuration is set",
      root_cause=(
          "Only the bootstrap fields are guaranteed populated; other fields in "
          "this participant's discovery data may not yet reflect its real "
          "configuration."),
      remedy="Re-run once discovery has settled before trusting locator or transport findings.",
      evidence={"partial_configuration": True},
  )]


def check_no_endpoints(context):
  """Participant visible but exposing no endpoints - a rung-2 failure."""
  participant = _participant(context)
  if participant is None or context.registry is None:
    return []
  if context.endpoint is not None:
    return []  # we are focused on an endpoint, so clearly some exist

  endpoints = context.registry.endpoints_for(participant.key)
  if endpoints:
    return []
  return [Finding(
      id="endpoint.none",
      rung=RUNG_ENDPOINT,
      severity=Severity.WARN,
      title="Participant discovered, but none of its endpoints are visible",
      observed=f"Participant '{participant.name}' has 0 discovered readers or writers.",
      root_cause=(
          "Participant discovery (SPDP) succeeded but endpoint discovery (SEDP) "
          "has not produced any endpoint for it. Either the application genuinely "
          "has no readers or writers yet, or the reliable SEDP exchange is not "
          "completing - for example because discovery traffic is being dropped "
          "after the initial announcement."),
      remedy=("Give discovery more time, then confirm the peer application has "
              "actually created its endpoints."),
      evidence={"participant": participant.name},
  )]


CHECKS = (
    check_vendor_identify,
    check_vendor_notes,
    check_locators,
    check_no_multicast_locators,
    check_transport,
    check_security_mismatch,
    check_partial_configuration,
    check_no_endpoints,
)
