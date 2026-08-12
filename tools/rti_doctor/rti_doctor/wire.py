"""Direct RTPS observations collected through tshark.

Discovery tells us what an endpoint advertised. This module records what a
packet capture actually saw without attempting to decode DDS user payloads.
"""

from dataclasses import dataclass
import os
import re
import shutil
import subprocess
import time
from xml.etree import ElementTree

from . import compat, records

#: Ceiling on a one-shot tshark read of an existing capture. An unbounded
#: subprocess.run over an arbitrarily large PCAP hangs the whole report.
TSHARK_READ_TIMEOUT = 120.0

#: Ceiling on the field-support probe below, which opens no capture and should
#: answer in milliseconds. Generous because it is paid at most once per field.
TSHARK_FIELD_PROBE_TIMEOUT = 10.0

#: Ceiling on `tshark -D`. Far below TSHARK_READ_TIMEOUT, which is sized for
#: reading a whole capture file: enumerating interfaces opens nothing and should
#: be near-instant, but extcap helpers are third-party binaries that tshark runs
#: to enumerate remote-capture devices, and one of those hanging must not hold a
#: picker open for two minutes.
TSHARK_INTERFACE_LIST_TIMEOUT = 15.0


#: DDS serialized-payload encapsulation identifiers observable in RTPS DATA.
#: Each value identifies the encoding actually used on the wire, unlike the
#: discovery DataRepresentation QoS which only advertises supported encodings.
ENCAPSULATION_NAMES = {
  "0x0000": "XCDR1 (big-endian)",
  "0x0001": "XCDR1 (little-endian)",
  "0x0002": "XCDR1 parameter list (big-endian)",
  "0x0003": "XCDR1 parameter list (little-endian)",
  "0x0006": "XCDR2 (big-endian)",
  "0x0007": "XCDR2 (little-endian)",
  "0x0008": "XCDR2 delimited (big-endian)",
  "0x0009": "XCDR2 delimited (little-endian)",
  "0x000a": "XCDR2 parameter list (big-endian)",
  "0x000b": "XCDR2 parameter list (little-endian)",
}


def encapsulation_text(encapsulation_ids):
  """Render observed DDS serialization encodings with their raw IDs."""
  return ", ".join(
    f"{ENCAPSULATION_NAMES.get(str(value).lower(), 'unknown encoding')} [{value}]"
    for value in encapsulation_ids)


@dataclass
class WireObservation:
  """One RTPS user-data observation emitted by tshark's fields formatter."""

  timestamp: str = ""
  submessage_id: str = ""
  writer_entity_id: str = ""
  writer_guid_prefix: str = ""
  sequence_number: str = ""
  encapsulation_id: str = ""
  payload_bytes: int = 0
  reassembled_bytes: int = 0
  reader_entity_id: str = ""


@dataclass
class DiscoveryObservation:
  """One SPDP/SEDP metadata observation decoded by tshark."""

  guid_prefix: str = ""
  vendor_id: str = ""
  product_version_major: str = ""
  product_version_minor: str = ""
  product_version_release: str = ""
  product_version_release_string: str = ""
  product_version_revision: str = ""
  writer_entity_id: str = ""
  reader_entity_id: str = ""
  builtin_endpoint_set: str = ""
  topic_name: str = ""
  type_name: str = ""
  reliability_kind: str = ""


#: tshark's aggregator when a field occurs more than once in a frame. Every
#: field below is per-submessage, and RTPS routinely coalesces several
#: submessages into one frame, so occurrences are requested and split here.
OCCURRENCE_SEPARATOR = ","


#: The single ordered discovery-column layout: one (tshark field, observation
#: attribute) pair per column, in the order tshark emits them. The capture
#: command's ``-e`` list and the parser's positional mapping are both built
#: from this, because maintaining them as two independent lists let a field be
#: added to one and not the other, shifting every column after it.
#:
#: Field names must stay unique. tshark emits one column per ``-e`` argument
#: even when a name repeats - the earlier duplicate column is simply blank and
#: the value lands in the later one - so a repeated name costs a column that
#: carries nothing while shifting every real value one slot right of where the
#: parser expects it. That is the defect this layout exists to prevent.
DISCOVERY_FIELDS = (
    ("rtps.guidPrefix.src", "guid_prefix"),
    ("rtps.vendorId", "vendor_id"),
    ("rtps.param.product_version.major", "product_version_major"),
    ("rtps.param.product_version.minor", "product_version_minor"),
    ("rtps.param.product_version.release", "product_version_release"),
    ("rtps.param.product_version.release_string", "product_version_release_string"),
    ("rtps.param.product_version.revision", "product_version_revision"),
    ("rtps.sm.wrEntityId", "writer_entity_id"),
    ("rtps.sm.rdEntityId", "reader_entity_id"),
    ("rtps.param.builtin_endpoint_set", "builtin_endpoint_set"),
    ("rtps.param.topicName", "topic_name"),
    ("rtps.param.typeName", "type_name"),
    ("rtps.reliability_kind", "reliability_kind"),
)


#: Discovery columns whose tshark field is not in every Wireshark build.
#:
#: tshark validates every ``-e`` name *before* it opens the capture and refuses
#: to run when one is unknown ("Some fields aren't valid"), so asking
#: unconditionally for a field the local dissector lacks would trade one
#: missing version line for every capture returning nothing at all. Each of
#: these is probed once and dropped from the layout where it is absent.
OPTIONAL_DISCOVERY_FIELDS = frozenset({
    "rtps.param.product_version.release_string",
})


#: Answers, per (tshark, field), from `_tshark_supports_field`. The dissector
#: cannot change under a running interpreter, so one probe per field is enough.
_FIELD_SUPPORT = {}


def reset_field_support_cache():
  """Forget probed field support. For tests that vary the tshark they mock."""
  _FIELD_SUPPORT.clear()


def _tshark_supports_field(tshark_path, field):
  """Whether this tshark build knows `field`.

  `tshark -G fields` is the documented enumerator and costs about 12 s and
  260,000 lines on the Wireshark 4.4.9 this was measured against - far too much
  to pay before reading a capture. Field names are validated before the capture
  file is opened, so naming the field against `os.devnull` answers the same
  question in milliseconds: an unknown field is rejected outright, while a
  known one gets far enough to complain about the file instead.
  """
  key = (tshark_path, field)
  if key not in _FIELD_SUPPORT:
    _FIELD_SUPPORT[key] = _probe_field(tshark_path, field)
  return _FIELD_SUPPORT[key]


def _probe_field(tshark_path, field):
  """One `-e` validation run, keyed on the message rather than the exit code.

  The rejection is identified by what tshark says, not by a status: a future
  build that opened the file first would fail a valid field too, and the
  message is what distinguishes the two cases.
  """
  try:
    completed = subprocess.run(
        [tshark_path, "-r", os.devnull, "-T", "fields", "-e", field],
        text=True, capture_output=True, check=False,
        timeout=TSHARK_FIELD_PROBE_TIMEOUT)
  except (OSError, subprocess.TimeoutExpired):
    # A probe that could not run has said nothing about the field. Treat it as
    # absent: dropping an optional column costs one line of evidence, keeping
    # an unknown one costs the entire capture.
    return False
  return not ("aren't valid" in completed.stderr and field in completed.stderr)


def discovery_fields(tshark_path):
  """The discovery layout this tshark can actually be asked for.

  Both the ``-e`` list and the parser's positional mapping are built from the
  return value, so a dropped optional column shifts neither out of step with
  the other - the same reason `DISCOVERY_FIELDS` is one shared layout.
  """
  return tuple((field, attribute) for field, attribute in DISCOVERY_FIELDS
               if field not in OPTIONAL_DISCOVERY_FIELDS
               or _tshark_supports_field(tshark_path, field))


def parse_tshark_fields(line):
  """Parse one tab-separated RTPS record from the tshark capture command."""
  fields = line.rstrip("\r\n").split("\t")
  fields += [""] * (9 - len(fields))
  payload = _hex_bytes(fields[6])
  reassembled = _hex_bytes(fields[7])
  return WireObservation(
      timestamp=fields[0],
      submessage_id=fields[1],
      writer_entity_id=fields[2],
      writer_guid_prefix=fields[3],
      sequence_number=fields[4],
      encapsulation_id=fields[5],
      payload_bytes=payload,
      reassembled_bytes=reassembled,
      reader_entity_id=fields[8],
  )


def _values(field):
  """Every occurrence of a repeated tshark field, normalized and de-duplicated."""
  return [item.strip().lower() for item in str(field).split(OCCURRENCE_SEPARATOR)
          if item.strip()]


def _hex_bytes(value):
  """Total bytes across tshark's colon-separated renderings, or zero if absent."""
  if not value:
    return 0
  digits = value.replace(":", "").replace(OCCURRENCE_SEPARATOR, "")
  return len(digits) // 2

def parse_discovery_fields(line, layout=None):
  """Parse RTPS discovery metadata emitted by tshark's fields formatter.

  Columns are assigned by position from `layout`, which defaults to the full
  `DISCOVERY_FIELDS`. Callers that dropped an optional column from the capture
  command must pass the same resolved layout here, or every column after the
  gap is read one slot to the left.
  """
  layout = layout or DISCOVERY_FIELDS
  fields = line.rstrip("\r\n").split("\t")
  fields += [""] * (len(layout) - len(fields))
  return DiscoveryObservation(**{attribute: fields[index]
                                 for index, (_, attribute) in enumerate(layout)})


#: Stands in for a version component the capture did not carry. A version keeps
#: all four dot-separated components so its shape is stable for anything
#: reading these strings, and an unknown component says so rather than being
#: dropped or filled with a zero that was never advertised.
UNKNOWN_VERSION_COMPONENT = "x"


def _fastdds_product_versions(observation):
  """Fast DDS versions advertised through its vendor-specific discovery PID.

  Components are paired by position across the subfield columns, and a column
  that is absent - or that carries a different number of occurrences than the
  frame's major/minor - is rendered as `x` at every position rather than
  truncating the pairing (M2). `zip` truncates to its shortest input, so an
  empty release column used to discard the version whole, major and minor
  included, and columns of unequal length used to pair the survivors into a
  version that was never on the wire.

  Major and minor are what make a version meaningful, so they must both be
  present and of equal length. When they are not, nothing here can be paired by
  position and no version is claimed at all.
  """
  if not any(value.removeprefix("0x") == "010f" for value in _values(observation.vendor_id)):
    return []
  major = _values(observation.product_version_major)
  minor = _values(observation.product_version_minor)
  if not major or len(major) != len(minor):
    return []
  # Not a second source: the dissector renders the one release octet under
  # either name depending on the build, so the string form is a fallback for
  # when the numeric column came back empty.
  release = (_values(observation.product_version_release)
             or _values(observation.product_version_release_string))
  revision = _values(observation.product_version_revision)
  count = len(major)
  trailing = [part if len(part) == count else [] for part in (release, revision)]
  return [".".join([major[index], minor[index]]
                   + [part[index] if part else UNKNOWN_VERSION_COMPONENT
                      for part in trailing])
          for index in range(count)]


#: The RTPS parameter carrying a product version. RTI and eProsima both use it,
#: but Wireshark names its subfields only for RTI's vendor id - see
#: `product_versions_from_pdml`.
PRODUCT_VERSION_PID = "0x8000"

#: XTypes TypeInformation carried in SEDP endpoint discovery. Its presence is
#: direct wire evidence that a participant advertised TypeObject v2 identifiers.
TYPE_INFORMATION_PID = "0x0075"

#: eProsima's RTPS vendor id, in the form tshark renders it.
FASTDDS_VENDOR_ID = "010f"


def _version_from_parameter_data(octets):
  """Four product-version octets, as tshark renders them, or None.

  major.minor.release.revision, one octet each, so byte order does not apply.
  """
  if not octets or len(octets) != 8:
    return None
  try:
    return ".".join(str(int(octets[index:index + 2], 16))
                    for index in range(0, 8, 2))
  except ValueError:
    return None


def product_versions_from_pdml(document, vendor_id=FASTDDS_VENDOR_ID):
  """(guid prefix, version) for every peer of `vendor_id` in a PDML document.

  Read from the parameter's own bytes rather than from
  `rtps.param.product_version.*`, because Wireshark decodes those subfields
  only for RTI's vendor id `0x0101`: the identical PID from eProsima's `0x010f`
  dissects as `Unknown (0x8000)` and the named columns come back empty, so the
  version was on the wire and absent from the report at the same time (WIRE-1).

  PDML is what makes this safe. It nests each RTPS parameter as a node holding
  its own `rtps.param.id` and `rtps.parameter_data`, so an id arrives already
  paired with its bytes. The flat `-T fields` view cannot do this: it emits raw
  parameter data only for the parameters the dissector leaves undissected, so
  the id and data columns have different lengths and no correspondence - which
  is `M2`'s defect in a new place.

  Fields are walked in document order and attributed to the most recent GUID
  prefix and vendor id seen, so a frame carrying more than one RTPS message
  attributes each version to the message it actually arrived in.
  """
  try:
    root = ElementTree.fromstring(document)
  except ElementTree.ParseError:
    return []
  found = set()
  for packet in root:
    prefix = None
    vendor = None
    for field in packet.iter("field"):
      name = field.get("name")
      if name == "rtps.guidPrefix.src":
        prefix = (field.get("show") or "").replace(":", "").lower()
      elif name == "rtps.vendorId":
        vendor = (field.get("show") or "").removeprefix("0x").lower()
      children = {child.get("name"): child for child in field}
      identifier = children.get("rtps.param.id")
      payload = children.get("rtps.parameter_data")
      if identifier is None or payload is None:
        continue
      if identifier.get("show") != PRODUCT_VERSION_PID or vendor != vendor_id:
        continue
      version = _version_from_parameter_data(payload.get("value"))
      if version and prefix:
        found.add((prefix, version))
  return sorted(found)


def read_product_versions(path, tshark_path=None, vendor_id=FASTDDS_VENDOR_ID):
  """One PDML pass over `path` for peer product versions, or [] if it fails.

  Narrowed to frames carrying the parameter, because PDML renders the whole
  protocol tree and a discovery capture of any size would otherwise be read as
  XML for nothing. It is a second pass over the same file either way (`N1`).
  """
  tshark_path = tshark_path or shutil.which("tshark")
  if not tshark_path:
    return []
  try:
    completed = subprocess.run(
        [tshark_path, "-n", "-r", path,
         "-Y", f"rtps.param.id == {PRODUCT_VERSION_PID}", "-T", "pdml"],
        text=True, capture_output=True, check=False,
        timeout=TSHARK_READ_TIMEOUT)
  except (OSError, subprocess.TimeoutExpired):
    return []
  if completed.returncode:
    return []
  return product_versions_from_pdml(completed.stdout, vendor_id=vendor_id)


def type_information_participants_from_pdml(document):
  """GUID prefixes that advertised PID_TYPE_INFORMATION in a PDML document."""
  try:
    root = ElementTree.fromstring(document)
  except ElementTree.ParseError:
    return []
  participants = set()
  for packet in root:
    prefix = None
    for field in packet.iter("field"):
      name = field.get("name")
      if name == "rtps.guidPrefix.src":
        prefix = (field.get("show") or "").replace(":", "").lower()
      children = {child.get("name"): child for child in field}
      identifier = children.get("rtps.param.id")
      if (identifier is not None
          and identifier.get("show") == TYPE_INFORMATION_PID
          and prefix):
        participants.add(prefix)
  return sorted(participants)


def read_type_information_participants(path, tshark_path=None):
  """Read TypeInformation-advertising participant prefixes from one capture."""
  tshark_path = tshark_path or shutil.which("tshark")
  if not tshark_path:
    return []
  try:
    completed = subprocess.run(
        [tshark_path, "-n", "-r", path,
         "-Y", f"rtps.param.id == {TYPE_INFORMATION_PID}", "-T", "pdml"],
        text=True, capture_output=True, check=False,
        timeout=TSHARK_READ_TIMEOUT)
  except (OSError, subprocess.TimeoutExpired):
    return []
  if completed.returncode:
    return []
  return type_information_participants_from_pdml(completed.stdout)


def summarize_discovery(observations, source, capture_filter=None,
                        participant_versions=(), type_information_participants=()):
  """Summarize observed RTPS SPDP/SEDP metadata without decoding user data.

  `participant_versions` is the PDML-read (prefix, version) evidence, which is
  the only source that works for a Fast DDS peer. It is merged with anything
  the named subfields yielded rather than replacing it, so a Wireshark whose
  dissector does name them agrees with itself instead of reporting twice.
  """
  participants = {item.guid_prefix for item in observations if item.guid_prefix}
  topics = sorted({item.topic_name for item in observations if item.topic_name})
  fastdds_versions = sorted({version for item in observations
                             for version in _fastdds_product_versions(item)}
                            | {version for _, version in participant_versions})
  # The same version paired with the GUID prefix that advertised it.
  # `fastdds_product_versions` alone cannot say which peer is on which version,
  # so a caller reporting one version per participant - or deciding whether the
  # participant that advertised it is still present - has nothing to key on.
  # `rtps.guidPrefix.src` is the sending participant, and the product-version
  # PID travels in that participant's own SPDP payload, so the pairing is
  # per-observation rather than inferred.
  fastdds_participant_versions = sorted({
      (item.guid_prefix.replace(":", "").lower(), version)
      for item in observations if item.guid_prefix
      for version in _fastdds_product_versions(item)}
      | {tuple(pair) for pair in participant_versions})
  # One tuple per (prefix, writer, reader) actually paired in a submessage.
  # Zipping the occurrence lists positionally rather than crossing them keeps
  # a coalesced frame from fabricating pairs that were never on the wire.
  endpoints = set()
  for item in observations:
    writers = _values(item.writer_entity_id) or [""]
    readers = _values(item.reader_entity_id) or [""]
    for index in range(max(len(writers), len(readers))):
      writer = writers[index] if index < len(writers) else ""
      reader = readers[index] if index < len(readers) else ""
      if writer or reader:
        endpoints.add((item.guid_prefix, writer, reader))
  return {
      "kind": "tshark RTPS discovery",
      "source": source,
      "capture_filter": capture_filter,
      "participants": len(participants),
      "endpoint_observations": len(endpoints),
      "topics": topics,
      "topic_count": len(topics),
      "fastdds_product_versions": fastdds_versions,
      "fastdds_participant_versions": [list(pair)
                                       for pair in fastdds_participant_versions],
      "type_information_participants": sorted(set(type_information_participants)),
      "builtin_endpoint_sets": sorted({item.builtin_endpoint_set
                                         for item in observations
                                         if item.builtin_endpoint_set}),
      "complete": False,
      "completion_note": (
          "RTPS discovery packets observed during a bounded capture. Counts "
          "can miss participants or endpoints announced before capture began "
          "and endpoint observations cannot be classified as readers or "
          "writers unless their SEDP entity kind is decoded."
      ),
  }


def summarize(observations, writer_entity_id=None, writer_guid_prefix=None,
              reader_entity_id=None):
  """Stable summary for a report appendix.

  Every filter that applies is applied. A GUID prefix identifies the remote
  PARTICIPANT, not the writer, so on its own it still admits that participant's
  SPDP/SEDP writers and its writers on other topics - the appendix would then
  present discovery traffic as the selected writer's user payload. The entity-id
  and builtin-writer filters therefore narrow it further rather than replacing
  it.

  Filtering is frame-level: a frame that coalesces the target writer with
  another writer is included once. Its other fields remain frame-level
  evidence, not evidence attributable to the selected writer alone. The
  returned mapping says so in `scope` / `writer_attributed` / `scope_note`,
  because the text appendix labels every count "in matching frames" but a JSON
  consumer reads the keys alone and would otherwise attribute them to the
  selected writer.
  """
  if writer_guid_prefix is not None:
    observations = [item for item in observations
                    if _same_guid_prefix(item.writer_guid_prefix, writer_guid_prefix)]
  if writer_entity_id is not None:
    observations = [item for item in observations
                    if _same_entity_id(item.writer_entity_id, writer_entity_id)]
  elif reader_entity_id is not None:
    observations = [item for item in observations
                    if _same_entity_id(item.reader_entity_id, reader_entity_id)]
  else:
    observations = [item for item in observations if not _is_builtin_writer(item)]

  encapsulations, writers = set(), set()
  for item in observations:
    encapsulations.update(_values(item.encapsulation_id))
    writers.update(_values(item.writer_entity_id))
  return {
      "packets": len(observations),
      "data_packets": sum(_has_submessage(item, "0x15") for item in observations),
      "data_fragments": sum(_has_submessage(item, "0x16") for item in observations),
      "encapsulation_ids": sorted(encapsulations),
      "writer_entity_ids": sorted(writers),
      "payload_bytes": sum(item.payload_bytes for item in observations),
      "reassembled_bytes": sum(item.reassembled_bytes for item in observations),
      "scope": "frames matching the filters",
      "writer_attributed": False,
      "scope_note": (
          "Every count, ID and byte total here describes whole RTPS frames "
          "that matched the filters, not one writer within them. A frame can "
          "coalesce several DATA submessages - including submessages from "
          "other writers on the same participant - and the frame-level tshark "
          "fields do not preserve which bytes belonged to which submessage. "
          "The target writer is therefore a filter, not an attribution claim."
      ),
  }


def endpoint_entity_id(endpoint):
  """Last 32-bit word of a discovered endpoint GUID, rendered for tshark."""
  key_text = str(getattr(endpoint, "key", ""))
  match = re.search(r"\[([^]]+)\]", key_text)
  values = [int(value) for value in re.findall(r"\d+", match.group(1))] if match else []
  if len(values) != 4:
    return None
  return f"{values[-1] & 0xffffffff:08x}"


def endpoint_guid_prefix(endpoint):
  """First three 32-bit words of a discovered endpoint GUID as RTPS bytes."""
  return record_guid_prefix(endpoint)


def record_guid_prefix(record):
  """GUID prefix of any discovered record whose key is a four-word builtin key.

  `EndpointRecord.key` and `ParticipantRecord.key` are both
  `str(data.key.value)` over the same four-word BuiltinTopicKey, and the first
  three words are the RTPS GUID prefix in both cases - so a participant
  observed on the wire by GUID prefix can be matched back to its registry
  record without a second key format.
  """
  key_text = str(getattr(record, "key", ""))
  match = re.search(r"\[([^]]+)\]", key_text)
  values = [int(value) for value in re.findall(r"\d+", match.group(1))] if match else []
  if len(values) != 4:
    return None
  return "".join(f"{value & 0xffffffff:08x}" for value in values[:3])


def _same_entity_id(observed, expected):
  wanted = expected.lower().removeprefix("0x")
  return any(value.removeprefix("0x") == wanted for value in _values(observed))


def _same_guid_prefix(observed, expected):
  wanted = expected.lower().replace(":", "")
  return any(value.replace(":", "") == wanted for value in _values(observed))


def _has_submessage(observation, identifier):
  return identifier.lower() in _values(observation.submessage_id)


def _is_builtin_writer(observation):
  """Discovery and participant-message writers end in the RTPS C2/C3 kinds."""
  return any(value.endswith("c2") or value.endswith("c3")
             for value in _values(observation.writer_entity_id))


def capture_filter(domain_id, endpoint, participant_qos, owner=None):
  """Narrow a live capture to the RTPS domain range and discovered extra ports.

  A BPF filter must use data available before capture starts. A discovered
  UDPv4 locator can be rewritten by Docker/NAT, so the configured RTPS port
  range for the requested domain is the primary portable scope. Discovered
  writer ports outside that range are added explicitly. If neither is usable,
  fall back to the writer ports, then finally unrestricted UDP.

  `owner` is the endpoint's own participant record. An endpoint may advertise no
  locators of its own and inherit its participant's defaults, which is legal
  RTPS and is what Cyclone does: measured 2026-08-12, its writer's
  `unicast_locators` is empty while its participant advertises one UDPv4 locator
  on an ephemeral port - 41050 against domain 99, whose range is 32150-32399. So
  such an endpoint contributed no ports at all, and the range term alone cannot
  reach a vendor that ignores the participant-index port mapping. Connext and
  Fast DDS both populate the endpoint list, so this changes nothing for them.

  **This closes that gap and does not by itself fix WIRE-2.** Every port here is
  a *receive* address, which is what the endpoint term has always contributed.
  A writer's outgoing user DATA is addressed to its matched **reader's**
  locator, so selecting a Cyclone writer still yields a filter that its own data
  frames do not match: measured on the same fixtures, DATA left port 57276 for
  port 34850 while the filter named the writer's advertised port. Capturing a
  writer's data needs the counterpart endpoints' locators, which is the decision
  WIRE-2 records.
  """
  locators = []
  sources = [getattr(endpoint, "unicast_locators", ()) or ()]
  if not sources[0]:
    # Only as a fallback. When an endpoint names its own locators those are
    # narrower, and mixing in participant defaults would widen the capture for
    # every vendor to fix one that needs it.
    sources.append(getattr(owner, "default_unicast_locators", ()) or ())
  for locator in [item for source in sources for item in source]:
    if compat.get_int(locator, "kind") != 1:  # UDPv4 only; IPv6 needs a BPF variant.
      continue
    address = records.locator_ip(locator)
    port = compat.get_int(locator, "port")
    if address and port is not None and 0 < port <= 65535:
      locators.append((address, port))

  ports = compat.get(compat.get(participant_qos, "wire_protocol", None),
                     "rtps_well_known_ports", None)
  base = compat.get_int(ports, "port_base")
  domain_gain = compat.get_int(ports, "domain_id_gain")
  if base is not None and domain_gain is not None and domain_gain > 0:
    first = base + (domain_id * domain_gain)
    last = first + domain_gain - 1
    if 0 <= first <= last <= 65535:
      extra_ports = sorted({port for _, port in locators if port < first or port > last})
      terms = [f"portrange {first}-{last}"] + [f"port {port}" for port in extra_ports]
      return "udp and (" + " or ".join(terms) + ")"

  if locators:
    writer_ports = sorted({port for _, port in locators})
    return "udp and (" + " or ".join(f"port {port}" for port in writer_ports) + ")"
  return "udp"


def capture_interfaces(tshark_path=None):
  """tshark capture interfaces as ``(index, description)`` pairs, plus an error.

  Restored for the TUI interface picker (CAP-2). It was removed in `ccaaa7b`
  along with the startup capture prompt, which left `c` with no way to ask: the
  interface could only come from `--capture-interface`, so choosing one meant
  quitting and relaunching, and the fallback was `any` - the choice needing the
  broadest privileges of all.

  Returns `((), reason)` rather than raising, because "tshark is missing" and
  "tshark refused" are things the picker must display, not crash on.
  """
  tshark_path = tshark_path or shutil.which("tshark")
  if not tshark_path:
    return (), "tshark was not found on PATH"
  try:
    completed = subprocess.run([tshark_path, "-D"], text=True, capture_output=True,
                               check=False, timeout=TSHARK_INTERFACE_LIST_TIMEOUT)
  except (OSError, subprocess.TimeoutExpired) as error:
    return (), f"could not list tshark interfaces: {error}"
  if completed.returncode:
    return (), (completed.stderr.strip()
                or f"tshark exited with {completed.returncode}")
  interfaces = []
  for line in completed.stdout.splitlines():
    number, separator, description = line.partition(". ")
    if separator and number.isdigit() and description:
      interfaces.append((number, description))
  return tuple(interfaces), None


#: The name tshark gives the pseudo-interface that captures on every device.
#: Always offered, even when `tshark -D` does not list it, so the picker can
#: never be a dead end - and listed last, because it is the most privileged
#: choice rather than the natural default (N3).
ANY_INTERFACE = "any"


def interface_name(description):
  """The name to pass to `tshark -i` from a `tshark -D` description line.

  `tshark -D` prints "eth0" or "lo" bare, but also "\\Device\\NPF_{GUID} (Local
  Area Connection)" and "any (Pseudo-device that captures on all interfaces)".
  Only the leading token is the name.
  """
  return str(description).split(" ", 1)[0].strip()


def inspect_pcap(path, tshark_path=None, writer_entity_id=None, writer_guid_prefix=None,
                 reader_entity_id=None):
  """Return direct RTPS user-data observations from an existing PCAP/PCAPNG."""
  tshark_path = tshark_path or shutil.which("tshark")
  if not tshark_path:
    return {"error": "tshark was not found on PATH", "source": path}
  if not os.path.isfile(path):
    return {"error": f"capture file does not exist: {path}", "source": path}

  command = [
      tshark_path, "-n", "-r", path,
      # The serialization encapsulation kind is direct evidence of a DDS sample.
      # Generic RTPS DATA also carries discovery parameter lists, so filtering
      # by submessage ID alone would count SEDP as user payload.
      "-Y", "rtps.param.serialize.encap_kind",
      # occurrence=a, not =f. Every field here is per-submessage and RTPS
      # coalesces submessages into one frame, typically behind an INFO_TS. With
      # only the first occurrence, rtps.sm.id read 0x09 (INFO_TS) on almost
      # every frame, so DATA_FRAG could never be counted and DATA was counted
      # from a submessage that was neither.
      "-T", "fields", "-E", "occurrence=a", "-E",
      f"aggregator={OCCURRENCE_SEPARATOR}",
      "-e", "frame.time_epoch", "-e", "rtps.sm.id",
      "-e", "rtps.sm.wrEntityId", "-e", "rtps.guidPrefix.src",
      "-e", "rtps.sm.seqNumber",
      "-e", "rtps.param.serialize.encap_kind", "-e", "rtps.issueData",
      "-e", "rtps.reassembled.data", "-e", "rtps.sm.rdEntityId",
  ]
  try:
    completed = subprocess.run(command, text=True, capture_output=True,
                               check=False, timeout=TSHARK_READ_TIMEOUT)
  except subprocess.TimeoutExpired:
    return {"error": f"tshark did not finish reading the capture within "
                     f"{TSHARK_READ_TIMEOUT:.0f}s", "source": path}
  except OSError as error:
    return {"error": f"could not run tshark: {error}", "source": path}
  if completed.returncode:
    error = completed.stderr.strip() or f"tshark exited with {completed.returncode}"
    return {"error": error, "source": path}

  observations = [parse_tshark_fields(line) for line in completed.stdout.splitlines()
                  if line.strip()]
  result = {"source": path, **summarize(observations, writer_entity_id,
                                          writer_guid_prefix, reader_entity_id)}
  if writer_entity_id is not None:
    result["target_writer_entity_id"] = writer_entity_id
  if writer_guid_prefix is not None:
    result["target_writer_guid_prefix"] = writer_guid_prefix
  if reader_entity_id is not None:
    result["target_reader_entity_id"] = reader_entity_id
  return result


def inspect_discovery_pcap(path, tshark_path=None, capture_filter=None):
  """Return metadata-only RTPS topology evidence from a PCAP/PCAPNG.

  This is deliberately separate from ``inspect_pcap``: it reads SPDP/SEDP
  fields and never inspects serialized user payload.
  """
  tshark_path = tshark_path or shutil.which("tshark")
  if not tshark_path:
    return {"error": "tshark was not found on PATH", "source": path}
  if not os.path.isfile(path):
    return {"error": f"capture file does not exist: {path}", "source": path}

  command = [
      tshark_path, "-n", "-r", path,
      # Not "-Y rtps": that admits ordinary user DATA/HEARTBEAT/ACKNACK, so
      # `participants` counted the sender of any RTPS packet and one logical
      # writer produced several endpoint tuples. Only frames actually carrying
      # SPDP or SEDP parameters are discovery evidence.
      "-Y", "rtps.param.builtin_endpoint_set or rtps.param.topicName",
      "-T", "fields", "-E", "occurrence=a", "-E",
      f"aggregator={OCCURRENCE_SEPARATOR}",
  ]
  # Resolved once, and used for both the request and the parse below.
  layout = discovery_fields(tshark_path)
  for field, _ in layout:
    command += ["-e", field]
  try:
    completed = subprocess.run(command, text=True, capture_output=True,
                               check=False, timeout=TSHARK_READ_TIMEOUT)
  except subprocess.TimeoutExpired:
    return {"error": f"tshark did not finish reading the capture within "
                     f"{TSHARK_READ_TIMEOUT:.0f}s", "source": path}
  except OSError as error:
    return {"error": f"could not run tshark: {error}", "source": path}
  if completed.returncode:
    error = completed.stderr.strip() or f"tshark exited with {completed.returncode}"
    return {"error": error, "source": path}
  observations = [parse_discovery_fields(line, layout)
                  for line in completed.stdout.splitlines() if line.strip()]
  return summarize_discovery(
      observations, path, capture_filter=capture_filter,
      participant_versions=read_product_versions(path, tshark_path=tshark_path),
      type_information_participants=read_type_information_participants(
        path, tshark_path=tshark_path))


class LiveCapture:
  """An opt-in tshark process that writes a temporary PCAPNG while a probe runs.

  Every capture is bounded. `duration` becomes tshark's own ``-a duration:``
  stop condition, so a capture whose owner never reaches `finish()` - an
  abandoned worker, a screen popped mid-capture, an interpreter killed
  outright - still ends by itself instead of writing until the disk fills.
  `finish()` remains the normal end; the ceiling is the backstop.
  """

  def __init__(self, interface, output_path, capture_filter, writer_entity_id=None,
               writer_guid_prefix=None, reader_entity_id=None,
               tshark_path=None, duration=None):
    self.interface = interface
    self.output_path = os.path.abspath(output_path)
    self.capture_filter = capture_filter
    self.writer_entity_id = writer_entity_id
    self.writer_guid_prefix = writer_guid_prefix
    self.reader_entity_id = reader_entity_id
    self.tshark_path = tshark_path or shutil.which("tshark")
    self.duration = duration
    self.process = None
    self.error = None
    #: Where `error` came from: "start" if the capture never ran at all, "stop"
    #: if it ran and then ended badly, "read" if it left nothing to parse. The
    #: caller needs the difference: a capture that could not start is a property
    #: of the host - no tshark, no capture privileges - and says the next one
    #: will fail the same way, while one that started and was killed late says
    #: nothing about the next.
    self.error_stage = None
    self.started_at = None
    # tshark writes "Capturing on ..." and a running packet count to stderr for
    # the whole capture. An undrained PIPE fills at 64KB and blocks the process
    # mid-capture, so it goes to a file that both start() and finish() read.
    self.log_path = self.output_path + ".tshark.log"
    self._log = None

  def _fail(self, stage, reason):
    """Record the first failure and what stage it happened at.

    First only: a capture that could not start also exits non-zero, and the
    start failure is the one that explains the run.
    """
    if self.error is None:
      self.error, self.error_stage = reason, stage

  def _stderr_text(self):
    try:
      with open(self.log_path, encoding="utf-8", errors="replace") as handle:
        return handle.read().strip()
    except OSError:
      return ""

  def start(self):
    if not self.tshark_path:
      self._fail("start", "tshark was not found on PATH")
      return
    directory = os.path.dirname(self.output_path)
    if directory:
      os.makedirs(directory, exist_ok=True)
    command = [self.tshark_path, "-n", "-i", self.interface, "-f", self.capture_filter,
               "-w", self.output_path]
    if self.duration:
      # tshark takes whole seconds and treats 0 as "no limit", so a sub-second
      # window still has to round up to one.
      command += ["-a", f"duration:{max(1, int(round(self.duration)))}"]
    try:
      self._log = open(self.log_path, "w", encoding="utf-8")
      self.process = subprocess.Popen(
          command, stdout=subprocess.DEVNULL, stderr=self._log, text=True)
      self.started_at = time.monotonic()
      time.sleep(1.0)
      if self.process.poll() is not None:
        self.process.wait()
        self._fail("start",
                   self._stderr_text() or "tshark stopped before capture began")
    except OSError as error:
      self._fail("start", f"could not start tshark: {error}")

  def stop(self):
    """Terminate the capture and record how it ended. Safe to call twice.

    One capture file answers two different questions - what user data crossed
    the wire, and what discovery metadata did - and a report that asks both
    reads the same file twice. Stopping is therefore separate from parsing:
    `finish()` and `finish_discovery()` may be called in either order on one
    capture, and only the first of them stops anything.
    """
    if self.process is None:
      return
    if self.process.poll() is None:
      # tshark may still be opening its capture file when diagnosis needs no
      # probe (for example, when a peer does not serve TypeLookup data).
      if self.started_at is not None:
        remaining = 4.0 - (time.monotonic() - self.started_at)
        if remaining > 0:
          time.sleep(remaining)
      self.process.terminate()
      try:
        self.process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        self.process.kill()
        self.process.wait()
        self._fail("stop", "tshark did not exit after termination and was killed")
    # Outside the poll() guard on purpose. A tshark that died mid-capture -
    # interface removed, permissions revoked, disk full - has already exited
    # by now, and checking its status only when it was still running reported
    # the resulting empty file as a successful capture of zero packets.
    if self.error is None and self.process.returncode not in (0, -15):
      self._fail("stop", self._stderr_text()
                 or f"tshark exited with {self.process.returncode}")
    if self._log is not None:
      self._log.close()
      self._log = None

  def _unusable(self, evidence_kind):
    """The capture's own failure, or nothing to read, as an evidence mapping."""
    if self.error:
      return {"error": self.error, "error_stage": self.error_stage,
              "source": self.output_path, "capture_filter": self.capture_filter}
    if not os.path.isfile(self.output_path):
      return {"error": "tshark exited without creating a capture file; no packets "
                       f"were available for {evidence_kind} evidence",
              "error_stage": "read",
              "source": self.output_path, "capture_filter": self.capture_filter}
    return None

  def finish(self):
    self.stop()
    unusable = self._unusable("packet")
    if unusable is not None:
      return unusable
    result = inspect_pcap(self.output_path, tshark_path=self.tshark_path,
                          writer_entity_id=self.writer_entity_id,
                          writer_guid_prefix=self.writer_guid_prefix,
                          reader_entity_id=self.reader_entity_id)
    result["capture_filter"] = self.capture_filter
    return result

  def finish_discovery(self):
    """Stop this capture and parse discovery metadata instead of user data."""
    self.stop()
    unusable = self._unusable("discovery")
    if unusable is not None:
      return unusable
    result = inspect_discovery_pcap(
        self.output_path, tshark_path=self.tshark_path,
        capture_filter=self.capture_filter)
    result["capture_filter"] = self.capture_filter
    return result