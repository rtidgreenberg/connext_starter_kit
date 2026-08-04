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


def _hex_bytes(value):
  """Length of tshark's colon-separated byte rendering, or zero when absent."""
  if not value:
    return 0
  return len("".join(value.split(":"))) // 2


def summarize(observations, writer_entity_id=None, writer_guid_prefix=None):
  """Stable summary for a report appendix."""
  if writer_guid_prefix is not None:
    observations = [item for item in observations
                    if _same_guid_prefix(item.writer_guid_prefix, writer_guid_prefix)]
  else:
    observations = [item for item in observations if not _is_builtin_writer(item)]
  if writer_entity_id is not None and writer_guid_prefix is None:
    observations = [item for item in observations
                    if _same_entity_id(item.writer_entity_id, writer_entity_id)]
  encapsulations = sorted({item.encapsulation_id for item in observations
                           if item.encapsulation_id})
  writers = sorted({item.writer_entity_id for item in observations
                    if item.writer_entity_id})
  return {
      "packets": len(observations),
      "data_packets": sum(not _has_submessage(item, "0x16") for item in observations),
      "data_fragments": sum(_has_submessage(item, "0x16") for item in observations),
      "encapsulation_ids": encapsulations,
      "writer_entity_ids": writers,
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
  return observed.lower().removeprefix("0x") == expected.lower().removeprefix("0x")


def _same_guid_prefix(observed, expected):
  return observed.lower().replace(":", "") == expected.lower().replace(":", "")


def _has_submessage(observation, identifier):
  return identifier in observation.submessage_id.split(",")


def _is_builtin_writer(observation):
  """Discovery and participant-message writers end in the RTPS C2/C3 kinds."""
  entity_id = observation.writer_entity_id.lower()
  return entity_id.endswith("c2") or entity_id.endswith("c3")


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
      "-T", "fields", "-E", "occurrence=f",
      "-e", "frame.time_epoch", "-e", "rtps.sm.id",
      "-e", "rtps.sm.wrEntityId", "-e", "rtps.guidPrefix.src",
      "-e", "rtps.sm.seqNumber",
      "-e", "rtps.param.serialize.encap_kind", "-e", "rtps.issueData",
      "-e", "rtps.reassembled.data",
  ]
  try:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
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

  def start(self):
    if not self.tshark_path:
      self.error = "tshark was not found on PATH"
      return
    directory = os.path.dirname(self.output_path)
    if directory:
      os.makedirs(directory, exist_ok=True)
    try:
      self.process = subprocess.Popen(
          [self.tshark_path, "-n", "-i", self.interface, "-f", self.capture_filter, "-w",
           self.output_path],
          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
      self.started_at = time.monotonic()
      time.sleep(1.0)
      if self.process.poll() is not None:
        _, stderr = self.process.communicate()
        self.error = stderr.strip() or "tshark stopped before capture began"
    except OSError as error:
      self.error = f"could not start tshark: {error}"

  def finish(self):
    if self.process is not None and self.process.poll() is None:
      # tshark may still be opening its capture file when diagnosis needs no
      # probe (for example, when a peer does not serve TypeLookup data).
      if self.started_at is not None:
        remaining = 4.0 - (time.monotonic() - self.started_at)
        if remaining > 0:
          time.sleep(remaining)
      self.process.terminate()
      try:
        _, stderr = self.process.communicate(timeout=5)
      except subprocess.TimeoutExpired:
        self.process.kill()
        _, stderr = self.process.communicate()
        self.error = "tshark did not exit after termination and was killed"
      if self.error is None and self.process.returncode not in (0, -15):
        self.error = stderr.strip() or f"tshark exited with {self.process.returncode}"
    if self.error:
      return {"error": self.error, "source": self.output_path,
              "capture_filter": self.capture_filter}
    result = inspect_pcap(self.output_path, tshark_path=self.tshark_path,
                          writer_entity_id=self.writer_entity_id,
                          writer_guid_prefix=self.writer_guid_prefix)
    result["capture_filter"] = self.capture_filter
    return result