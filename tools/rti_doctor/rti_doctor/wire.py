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

from . import compat, records

#: Ceiling on a one-shot tshark read of an existing capture. An unbounded
#: subprocess.run over an arbitrarily large PCAP hangs the whole report.
TSHARK_READ_TIMEOUT = 120.0


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


@dataclass
class DiscoveryObservation:
  """One SPDP/SEDP metadata observation decoded by tshark."""

  guid_prefix: str = ""
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


def parse_tshark_fields(line):
  """Parse one tab-separated RTPS record from the tshark capture command."""
  fields = line.rstrip("\r\n").split("\t")
  fields += [""] * (8 - len(fields))
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

def parse_discovery_fields(line):
  """Parse RTPS discovery metadata emitted by tshark's fields formatter."""
  fields = line.rstrip("\r\n").split("\t")
  fields += [""] * (7 - len(fields))
  return DiscoveryObservation(
      guid_prefix=fields[0], writer_entity_id=fields[1],
      reader_entity_id=fields[2], builtin_endpoint_set=fields[3],
      topic_name=fields[4], type_name=fields[5], reliability_kind=fields[6])


def summarize_discovery(observations, source, capture_filter=None):
  """Summarize observed RTPS SPDP/SEDP metadata without decoding user data."""
  participants = {item.guid_prefix for item in observations if item.guid_prefix}
  topics = sorted({item.topic_name for item in observations if item.topic_name})
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


def summarize(observations, writer_entity_id=None, writer_guid_prefix=None):
  """Stable summary for a report appendix.

  Every filter that applies is applied. A GUID prefix identifies the remote
  PARTICIPANT, not the writer, so on its own it still admits that participant's
  SPDP/SEDP writers and its writers on other topics - the appendix would then
  present discovery traffic as the selected writer's user payload. The entity-id
  and builtin-writer filters therefore narrow it further rather than replacing
  it.

  Filtering is frame-level: a frame that coalesces the target writer with
  another writer is counted once, for the target.
  """
  if writer_guid_prefix is not None:
    observations = [item for item in observations
                    if _same_guid_prefix(item.writer_guid_prefix, writer_guid_prefix)]
  if writer_entity_id is not None:
    observations = [item for item in observations
                    if _same_entity_id(item.writer_entity_id, writer_entity_id)]
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
  key_text = str(getattr(endpoint, "key", ""))
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


def capture_filter(domain_id, endpoint, participant_qos):
  """Narrow a live capture to the RTPS domain range and discovered extra ports.

  A BPF filter must use data available before capture starts. A discovered
  UDPv4 locator can be rewritten by Docker/NAT, so the configured RTPS port
  range for the requested domain is the primary portable scope. Discovered
  writer ports outside that range are added explicitly. If neither is usable,
  fall back to the writer ports, then finally unrestricted UDP.
  """
  locators = []
  for locator in getattr(endpoint, "unicast_locators", ()) or ():
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


def inspect_pcap(path, tshark_path=None, writer_entity_id=None, writer_guid_prefix=None):
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
      "-e", "rtps.reassembled.data",
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
                                          writer_guid_prefix)}
  if writer_entity_id is not None:
    result["target_writer_entity_id"] = writer_entity_id
  if writer_guid_prefix is not None:
    result["target_writer_guid_prefix"] = writer_guid_prefix
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
      "-e", "rtps.guidPrefix.src", "-e", "rtps.sm.wrEntityId",
      "-e", "rtps.sm.rdEntityId", "-e", "rtps.param.builtin_endpoint_set",
      "-e", "rtps.param.topicName", "-e", "rtps.param.typeName",
      "-e", "rtps.reliability_kind",
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
  observations = [parse_discovery_fields(line) for line in completed.stdout.splitlines()
                  if line.strip()]
  return summarize_discovery(observations, path, capture_filter=capture_filter)


class LiveCapture:
  """An opt-in tshark process that writes a temporary PCAPNG while a probe runs."""

  def __init__(self, interface, output_path, capture_filter, writer_entity_id=None,
               writer_guid_prefix=None,
               tshark_path=None):
    self.interface = interface
    self.output_path = os.path.abspath(output_path)
    self.capture_filter = capture_filter
    self.writer_entity_id = writer_entity_id
    self.writer_guid_prefix = writer_guid_prefix
    self.tshark_path = tshark_path or shutil.which("tshark")
    self.process = None
    self.error = None
    self.started_at = None
    # tshark writes "Capturing on ..." and a running packet count to stderr for
    # the whole capture. An undrained PIPE fills at 64KB and blocks the process
    # mid-capture, so it goes to a file that both start() and finish() read.
    self.log_path = self.output_path + ".tshark.log"
    self._log = None

  def _stderr_text(self):
    try:
      with open(self.log_path, encoding="utf-8", errors="replace") as handle:
        return handle.read().strip()
    except OSError:
      return ""

  def start(self):
    if not self.tshark_path:
      self.error = "tshark was not found on PATH"
      return
    directory = os.path.dirname(self.output_path)
    if directory:
      os.makedirs(directory, exist_ok=True)
    try:
      self._log = open(self.log_path, "w", encoding="utf-8")
      self.process = subprocess.Popen(
          [self.tshark_path, "-n", "-i", self.interface, "-f", self.capture_filter, "-w",
           self.output_path],
          stdout=subprocess.DEVNULL, stderr=self._log, text=True)
      self.started_at = time.monotonic()
      time.sleep(1.0)
      if self.process.poll() is not None:
        self.process.wait()
        self.error = self._stderr_text() or "tshark stopped before capture began"
    except OSError as error:
      self.error = f"could not start tshark: {error}"

  def finish(self):
    if self.process is not None:
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
          self.error = "tshark did not exit after termination and was killed"
      # Outside the poll() guard on purpose. A tshark that died mid-capture -
      # interface removed, permissions revoked, disk full - has already exited
      # by now, and checking its status only when it was still running reported
      # the resulting empty file as a successful capture of zero packets.
      if self.error is None and self.process.returncode not in (0, -15):
        self.error = (self._stderr_text()
                      or f"tshark exited with {self.process.returncode}")
    if self._log is not None:
      self._log.close()
      self._log = None
    if self.error:
      return {"error": self.error, "source": self.output_path,
              "capture_filter": self.capture_filter}
    result = inspect_pcap(self.output_path, tshark_path=self.tshark_path,
                          writer_entity_id=self.writer_entity_id,
                          writer_guid_prefix=self.writer_guid_prefix)
    result["capture_filter"] = self.capture_filter
    return result