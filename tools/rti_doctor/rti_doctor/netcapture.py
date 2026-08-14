"""RTI Network Capture: the only way to observe rti_doctor's own SHMEM traffic.

tshark reads network interfaces. Two participants on one host prefer the
shared-memory transport, and SHMEM traffic never reaches an interface - so a
tshark capture of a same-host pair is empty no matter which interface or filter
it is given. Measured against the `healthy` fixture on 2026-08-13: the probe
took 256 samples and counted 6 heartbeats while a capture of ALL UDP for the
same window carried only SPDP/SEDP and not one HEARTBEAT.

RTI Network Capture instruments the middleware instead of the wire, so it
records what a participant actually sent and received on every transport it
used. Verified on the same host, capturing the probe participant with SHMEM
left enabled: 81 RTPS frames, 15 HEARTBEAT and 14 ACKNACK, all dissected by
tshark as ordinary RTPS and all carrying no IP layer at all - shared-memory
frames, which is precisely the traffic no interface capture could see. It writes
a standard PCAP, so `wire.inspect_pcap` reads it unchanged and the report
appendix needs no second parser.

What RTI documents is only that Network Capture produces a pcap-based file for a
packet analyzer to open. The specifics this tool relies on - link type 252,
`LINKTYPE_WIRESHARK_UPPER_PDU`, an EXPORTED_PDU header naming the `rtpsvt`
dissector - are observed, not contracted, and RTI confirms no utility of its own
reads or summarizes these files. So tshark is not a convenience here, it is the
only reader, and a release that changed the encapsulation would break this path
without breaking any promise. If `inspect_pcap` ever returns frames it cannot
dissect, look here first.

Two constraints shape every decision here, and neither is negotiable:

  * **`enable()` must precede every other Connext call.** The binding's own
    docstring says so, and it means this cannot be a keypress. It is a launch
    flag, decided before the participant exists - unlike the tshark capture,
    which any report can start.
  * **It is scoped to one participant, ours.** It records rti_doctor's own
    conversation with the peer, in both directions, and nothing else. It can
    never show traffic between two other participants, which is exactly what a
    tshark capture is good at. The two are complements, not alternatives, and
    the report says which one produced which evidence.
"""

import logging
import os

try:
  import rti.connextdds as dds
  _NETWORK_CAPTURE = getattr(dds, "network_capture", None)
except Exception:  # pragma: no cover - import-time binding failure
  dds = None
  _NETWORK_CAPTURE = None

#: RTI Network Capture appends this to the path it is given.
CAPTURE_SUFFIX = ".pcap"


def available():
  """Whether this binding exposes RTI Network Capture at all."""
  return _NETWORK_CAPTURE is not None


def unavailable_reason():
  """Why `enable` would fail, for a message the operator can act on."""
  if dds is None:
    return "the Connext Python binding could not be imported"
  if _NETWORK_CAPTURE is None:
    return ("this Connext Python binding does not expose "
            "rti.connextdds.network_capture")
  return None


def enable():
  """Turn on RTI Network Capture. Returns (ok, reason).

  MUST be called before any other Connext library call - before the participant,
  before the XTypes mask, before anything. Enabling it later returns False from
  the native layer rather than raising, which would leave a run that believes it
  is capturing and is not; so the caller checks the return and says so.

  Never raises: an unavailable feature must cost the run a line of output, not
  its participant.
  """
  reason = unavailable_reason()
  if reason:
    return False, reason
  try:
    if _NETWORK_CAPTURE.enable():
      return True, None
    return False, ("rti.connextdds.network_capture.enable() returned False - it "
                   "must be called before any other Connext call")
  except Exception as error:
    return False, f"{type(error).__name__}: {error}"


def disable():
  """Turn it off on the way out. Never raises; failure is logged, not fatal."""
  if _NETWORK_CAPTURE is None:
    return False
  try:
    return bool(_NETWORK_CAPTURE.disable())
  except Exception as error:
    logging.error(f"[netcapture] disable failed: {error}")
    return False


def _params():
  """Capture both directions, on every transport the participant uses.

  `traffic` defaults to IN|OUT already; it is set explicitly because a default
  that changes underneath this tool would silently halve the evidence. The
  `transports` sequence is left empty, which means every transport - narrowing
  it to SHMEM would discard the UDP half of the same conversation.
  """
  params = _NETWORK_CAPTURE.NetworkCaptureParams()
  try:
    params.traffic = _NETWORK_CAPTURE.TrafficKindMask.ALL
  except Exception as error:
    logging.error(f"[netcapture] could not set traffic mask: {error}")
  return params


class ParticipantCapture:
  """One participant-scoped capture, shaped like `wire.LiveCapture`.

  Deliberately the same shape - `start()` / `finish()` returning a summary dict
  with a `source` and an `error` - so the engine drives both the same way and
  the report renders both through one appendix path.
  """

  def __init__(self, participant, output_path):
    self.participant = participant
    # The native layer appends its own suffix, so it is given the stem and the
    # real file is recorded separately. A caller that named a file on screen has
    # to be told the same name the report will cite.
    self.stem = output_path[:-len(CAPTURE_SUFFIX)] if output_path.endswith(
        CAPTURE_SUFFIX) else output_path
    self.output_path = self.stem + CAPTURE_SUFFIX
    self.started = False
    self.error = None

  def start(self):
    """Begin recording. Returns True when the capture is actually running."""
    if _NETWORK_CAPTURE is None:
      self.error = unavailable_reason()
      return False
    directory = os.path.dirname(self.output_path)
    if directory:
      os.makedirs(directory, exist_ok=True)
    try:
      if _NETWORK_CAPTURE.start(self.participant, self.stem, _params()):
        self.started = True
        return True
      self.error = ("rti.connextdds.network_capture.start() returned False; "
                    "network capture may not have been enabled at startup")
    except Exception as error:
      self.error = f"{type(error).__name__}: {error}"
    return False

  def stop(self):
    """End recording. Idempotent, and safe on a capture that never started."""
    if not self.started or _NETWORK_CAPTURE is None:
      return
    self.started = False
    try:
      _NETWORK_CAPTURE.stop(self.participant)
    except Exception as error:
      logging.error(f"[netcapture] stop failed: {error}")
      self.error = self.error or f"stop failed: {error}"

  def finish(self, writer_entity_id=None, writer_guid_prefix=None,
             reader_entity_id=None):
    """Stop, then parse. Same summary shape as a tshark capture.

    The entity filters are the probe's own, not the peer's: this file contains
    only rti_doctor's participant's frames, so filtering by the SELECTED
    endpoint's writer id is what isolates the conversation with it from our
    concurrent discovery traffic.
    """
    from . import wire
    self.stop()
    if self.error:
      return {"error": self.error, "source": self.output_path,
              "kind": "rti network capture"}
    if not os.path.isfile(self.output_path):
      return {"error": f"network capture wrote no file at {self.output_path}",
              "source": self.output_path, "kind": "rti network capture"}
    result = wire.inspect_pcap(
        self.output_path, writer_entity_id=writer_entity_id,
        writer_guid_prefix=writer_guid_prefix,
        reader_entity_id=reader_entity_id)
    result["kind"] = "rti network capture"
    # No BPF filter exists for this path, and saying so is not the same as
    # leaving the field absent - the appendix renders a capture filter when one
    # was applied, and its absence here is a property of the mechanism.
    result["capture_filter"] = ("none - RTI Network Capture records the "
                                "participant, not an interface")
    result["participant_scoped"] = True
    return result
