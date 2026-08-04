"""Rung 0-1 checks: why might we not be seeing anything at all?

These are the only checks that can explain an empty participant table, because
SPDP failures produce no row to select. Every condition here was confirmed as a
real cross-vendor blocker; each is a property of *our* configuration or of the
domain choice, not of a discovered peer.
"""

from .. import compat
from ..findings import (RUNG_OWN_CONFIG, RUNG_PARTICIPANT, Finding, Severity)

DOC_DISCOVERY = ("https://community.rti.com/howto/"
                 "typical-reasons-connext-dds-discovery-failing-and-suggested-solutions")
DOC_SPDP2 = ("https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/"
             "manuals/connext_dds_professional/users_manual/users_manual/"
             "Simple_Participant_Discovery_2.htm")


def _property_value(qos, name):
  """Read a QoS property-policy entry by name, or None."""
  policy = compat.get(qos, "property", None)
  if policy is None:
    return None
  # PropertyPolicy behaves like a mapping across versions; try both shapes.
  try:
    return policy[name]
  except Exception:
    pass
  try:
    for entry in policy:
      if compat.get(entry, "name", None) == name:
        return compat.get(entry, "value", None)
  except Exception:
    pass
  return None


def check_domain_tag(context):
  """A nonempty domain tag makes us invisible to every other vendor."""
  qos = context.own_qos
  if qos is None:
    return []
  tag = _property_value(qos, "dds.domain_participant.domain_tag")
  if not tag:
    return []
  return [Finding(
      id="blind.domain_tag",
      rung=RUNG_OWN_CONFIG,
      severity=Severity.ERROR,
      title="A domain tag is set, which blocks all cross-vendor discovery",
      observed=f"dds.domain_participant.domain_tag = '{tag}'",
      root_cause=(
          "Connext requires the domain ID AND the domain tag to match before it "
          "accepts a remote participant. Domain tags are an RTI extension that no "
          "other DDS vendor advertises, so any nonempty tag makes this "
          "participant and every third-party participant mutually invisible."),
      remedy=("Clear dds.domain_participant.domain_tag to interoperate with "
              "non-RTI implementations, or confirm the peer is also Connext and "
              "sets the identical tag."),
      evidence={"domain_tag": str(tag)},
      refs=[DOC_DISCOVERY],
  )]


def check_spdp2(context):
  """SPDP2 does not interoperate with standard SPDP."""
  qos = context.own_qos
  if qos is None:
    return []
  discovery_config = compat.get(qos, "discovery_config", None)
  plugins = compat.get(discovery_config, "builtin_discovery_plugins", compat.MISSING)
  if plugins is compat.MISSING:
    # Not present on this version, which also means SPDP2 cannot be enabled.
    return []
  text = str(plugins)
  if "SPDP2" not in text.upper():
    return []
  return [Finding(
      id="blind.spdp2",
      rung=RUNG_OWN_CONFIG,
      severity=Severity.ERROR,
      title="SPDP2 discovery is enabled, which cannot discover standard-SPDP peers",
      observed=f"discovery_config.builtin_discovery_plugins = {text}",
      root_cause=(
          "Simple Participant Discovery 2.0 and standard RTPS SPDP do not "
          "communicate directly. Fast DDS, Cyclone DDS, and RTPS-configured "
          "OpenDDS all use standard SPDP, so they will never be discovered while "
          "this participant runs SPDP2."),
      remedy="Enable the standard SPDP plugin to interoperate with other vendors.",
      evidence={"builtin_discovery_plugins": text},
      refs=[DOC_SPDP2],
  )]


def check_security_enabled(context):
  """A secure participant cannot discover an unsecure peer, or vice versa."""
  qos = context.own_qos
  if qos is None:
    return []
  library = _property_value(qos, "com.rti.serv.load_plugin")
  secure = bool(library) and "secur" in str(library).lower()
  if not secure:
    return []
  return [Finding(
      id="blind.security_enabled",
      rung=RUNG_OWN_CONFIG,
      severity=Severity.WARN,
      title="DDS Security is enabled on this participant",
      observed=f"com.rti.serv.load_plugin = {library}",
      root_cause=(
          "A secure participant and an unsecure participant are not usable as "
          "ordinary peers: discovery cannot complete the authentication "
          "handshake, which looks identical to 'no participant discovered'. Two "
          "secure participants also need compatible governance, permissions, and "
          "credentials."),
      remedy=("To diagnose plain interoperability, run rti_doctor without "
              "security plugins; to diagnose a secure system, confirm both sides "
              "share governance and permissions documents."),
      evidence={"load_plugin": str(library)},
      refs=[DOC_DISCOVERY],
  )]


def check_multicast_and_peers(context):
  """Multicast unusable with no usable initial_peers means nothing is reachable."""
  qos = context.own_qos
  if qos is None:
    return []
  discovery = compat.get(qos, "discovery", None)
  if discovery is None:
    return []

  peers = compat.get(discovery, "initial_peers", None)
  peer_list = []
  try:
    peer_list = [str(p) for p in (peers or ())]
  except TypeError:
    peer_list = [str(peers)] if peers else []

  has_multicast_peer = any(_looks_multicast(p) for p in peer_list)
  receive_addresses = compat.get(discovery, "multicast_receive_addresses", None)
  receive_list = []
  try:
    receive_list = [str(a) for a in (receive_addresses or ())]
  except TypeError:
    receive_list = [str(receive_addresses)] if receive_addresses else []

  if receive_list and (has_multicast_peer or len(peer_list) > 1):
    return []
  if not receive_list:
    return [Finding(
        id="blind.no_multicast_no_peers",
        rung=RUNG_OWN_CONFIG,
        severity=Severity.WARN,
        title="No multicast receive addresses configured",
        observed=(f"discovery.multicast_receive_addresses is empty; "
                  f"initial_peers = {peer_list or '[]'}"),
        root_cause=(
            "With no multicast receive address, this participant only discovers "
            "peers it can reach through initial_peers unicast. Any peer not in "
            "that list is invisible even when it is running correctly."),
        remedy=("Restore the default multicast receive address, or add every "
                "peer host to initial_peers (NDDS_DISCOVERY_PEERS)."),
        evidence={"initial_peers": peer_list, "multicast_receive_addresses": receive_list},
        refs=[DOC_DISCOVERY],
    )]
  return []


def _looks_multicast(peer):
  """True for a peer string in the IPv4 multicast range 224-239."""
  text = peer.split("@")[-1].split(":")[0]
  first = text.split(".")[0]
  try:
    return 224 <= int(first) <= 239
  except ValueError:
    return False


def check_accept_unknown_peers(context):
  """accept_unknown_peers=False silently drops otherwise-valid peers."""
  qos = context.own_qos
  if qos is None:
    return []
  discovery = compat.get(qos, "discovery", None)
  value = compat.get(discovery, "accept_unknown_peers", compat.MISSING)
  if value is compat.MISSING or value is None or bool(value):
    return []
  return [Finding(
      id="blind.unknown_peers_rejected",
      rung=RUNG_OWN_CONFIG,
      severity=Severity.ERROR,
      title="accept_unknown_peers is disabled, so unlisted peers are ignored",
      observed="discovery.accept_unknown_peers = False",
      root_cause=(
          "Discovery traffic from a participant not in initial_peers is received "
          "and then discarded. The peer appears completely absent even though "
          "its packets arrived."),
      remedy=("Set accept_unknown_peers to true, or add the peer to "
              "initial_peers."),
      evidence={"accept_unknown_peers": False},
      refs=[DOC_DISCOVERY],
  )]


def check_nonstandard_ports(context):
  """Nonstandard RTPS port mapping prevents SPDP packets from lining up."""
  qos = context.own_qos
  if qos is None:
    return []
  wire = compat.get(qos, "wire_protocol", None)
  ports = compat.get(wire, "rtps_well_known_ports", None)
  if ports is None:
    return []

  # The interoperable DDS-RTPS defaults. Any deviation is worth flagging, since
  # every vendor computes discovery ports from these.
  expected = {
      "port_base": 7400,
      "domain_id_gain": 250,
      "participant_id_gain": 2,
      "builtin_multicast_port_offset": 0,
      "builtin_unicast_port_offset": 10,
      "user_multicast_port_offset": 1,
      "user_unicast_port_offset": 11,
  }
  deviations = {}
  for name, default in expected.items():
    value = compat.get_int(ports, name)
    if value is not None and value != default:
      deviations[name] = f"{value} (interoperable default {default})"

  if not deviations:
    return []
  return [Finding(
      id="blind.nonstandard_ports",
      rung=RUNG_OWN_CONFIG,
      severity=Severity.WARN,
      title="RTPS well-known ports deviate from the usual defaults",
      observed="; ".join(f"{k} = {v}" for k, v in sorted(deviations.items())),
      root_cause=(
            "DDS implementations can interoperate with a custom RTPS port mapping, "
            "but every peer must use the same values. Remote port-mapping QoS is "
            "not advertised in discovery, so this is a local compatibility risk, "
            "not proof of a mismatch."),
          remedy=("Confirm every peer uses this mapping, or restore the usual "
              "rtps_well_known_ports defaults."),
      evidence=deviations,
      refs=[DOC_DISCOVERY],
  )]


def check_other_domain_active(context):
  """Participants announcing from a domain other than the one selected."""
  if not context.domain_scan_ran:
    return []
  others = {d for d in (context.active_domains or set()) if d != context.domain_id}
  if not others:
    return []
  ordered = ", ".join(str(d) for d in sorted(others))
  local_count = len(context.registry.participants) if context.registry else 0
  severity = Severity.WARN if local_count == 0 else Severity.INFO
  return [Finding(
      id="blind.other_domain_active",
      rung=RUNG_PARTICIPANT,
      severity=severity,
      title=f"Active participants detected on other domain(s): {ordered}",
      observed=(f"Selected domain {context.domain_id} has {local_count} discovered "
                f"participant(s); default domain announcements were also seen from "
                f"domain(s) {ordered}."),
      root_cause=(
          "Applications are running, but not on the domain being inspected. This "
          "is the most common explanation for an empty table when the network is "
          "otherwise healthy."),
      remedy=f"Re-run against one of: {ordered}.",
      evidence={"selected_domain": context.domain_id, "other_domains": sorted(others)},
  )]


def check_empty_domain(context):
  """Nothing discovered at all - roll the possible causes into one message."""
  if context.registry is None or context.registry.participants:
    return []
  scan_note = (
      "no other active domains were seen either, though that scan is best-effort "
      "and only detects RTI participants with default domain announcements enabled"
      if context.domain_scan_ran and not context.active_domains
      else "see blind.other_domain_active")
  return [Finding(
      id="blind.empty_domain",
      rung=RUNG_PARTICIPANT,
      severity=Severity.ERROR,
      title=f"No participants discovered on domain {context.domain_id}",
      observed=f"0 remote participants; {scan_note}.",
      root_cause=(
          "Participant discovery (SPDP) is not completing. In cross-vendor "
          "systems the usual causes are, in rough order of likelihood: nothing "
          "is actually running on this domain ID; multicast is blocked and "
          "initial_peers does not name the peer host; a domain tag is set on the "
          "Connext side; the peer is an OpenDDS application still using InfoRepo "
          "discovery rather than RTPS; a firewall is dropping UDP discovery "
          "traffic; or one side runs DDS Security and the other does not."),
      remedy=(
          "Confirm the domain ID first, then check the other findings in this "
          "report - any ERROR at rung 0 explains this on its own. If none fire, "
          "verify network reachability and the peer's own discovery configuration."),
      evidence={"domain_id": context.domain_id},
      refs=[DOC_DISCOVERY],
  )]


CHECKS = (
    check_domain_tag,
    check_spdp2,
    check_security_enabled,
    check_multicast_and_peers,
    check_accept_unknown_peers,
    check_nonstandard_ports,
    check_other_domain_active,
    check_empty_domain,
)
