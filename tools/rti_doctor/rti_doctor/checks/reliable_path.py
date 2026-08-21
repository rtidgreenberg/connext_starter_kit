"""Rung 5: is the RTPS reliable protocol actually running between these two?

A match is an agreement about QoS, not evidence that anything crossed the wire.
For a RELIABLE pair the protocol itself is the evidence: the writer must
heartbeat a reader it believes it has matched, and that reader must ACKNACK.
Either half missing is a specific, nameable fault, and neither is visible from
`subscription_matched`.

Two independent sources, deliberately both:

  * The middleware's own counters, from whichever entity the probe created.
    Exact and per-entity, but they only ever describe *our* side of the
    conversation, and a binding that does not expose them yields nothing.
  * The packet capture, when the operator ran one. Vendor-neutral and describes
    both sides, but it is frame-scoped rather than writer-scoped and only exists
    if someone pressed `c`.

They are reported together and compared. Agreement is worth stating; a
disagreement is a finding in its own right, because it means one of the two is
measuring something other than what this report claims it is.
"""

from .. import compat, records
from ..findings import RUNG_PAYLOAD, Finding, Severity


def shared_memory_note(context):
  """The commonest reason a packet capture is empty while the pair is healthy.

  Two participants on one host prefer the shared-memory transport, and SHMEM
  user data never reaches a network interface - so tshark observes nothing no
  matter which interface or filter it is given. Measured on this repo's own
  `healthy` fixture on 2026-08-13: 256 samples delivered and 6 heartbeats
  counted by the probe's reader, while a capture of ALL UDP on the host's
  interface for the same window carried only SPDP/SEDP and not one HEARTBEAT.

  rti_doctor's own participant is UDPv4-only (`discovery.configure_udp_only_
  transport`), so the probe's own conversation with this endpoint is always
  carried over UDP and is always observable. What stays invisible is this
  endpoint's traffic to its OTHER counterparts on the same host, which is the
  remaining way a capture can under-count a busy endpoint.

  Returns "" when no SHMEM locator is advertised, so this is only ever offered
  where it actually applies.
  """
  if not records.advertises_shared_memory(
      getattr(context, "endpoint", None),
      getattr(context, "participant_record", None)):
    return ""
  return (" This endpoint also advertises a SHARED MEMORY locator. rti_doctor's "
          "own participant is UDP-only, so its traffic with this endpoint is on "
          "UDP and was capturable - but this endpoint's traffic to other "
          "same-host counterparts travels over shared memory and never reaches "
          "a network interface, so no capture on any interface can include it.")


def _reliable(endpoint):
  """Whether the selected endpoint advertises RELIABLE."""
  kind = compat.get(getattr(endpoint, "reliability", None), "kind", None)
  if kind is None:
    return False
  name = compat.get(kind, "name", None) or str(kind)
  return "RELIABLE" in str(name).upper()


def _wire(context, key):
  """One packet count from whichever capture ran, or None when none usable did.

  Both mechanisms are consulted, participant capture first. RTI Network Capture
  is scoped to rti_doctor's own participant, so for the probe's own conversation
  - which is the only conversation this check judges - it is the more precise of
  the two, and it is the ONLY one that exists when the pair is talking over
  shared memory. An interface capture is the fallback.

  None and 0 must stay distinct: no capture is not the same claim as a capture
  that saw none, and this check reports the difference rather than defaulting.
  """
  for attribute in ("participant_evidence", "wire_evidence"):
    evidence = getattr(context, attribute, None)
    if not evidence or evidence.get("error"):
      continue
    value = evidence.get(key)
    if value is not None:
      return value
  return None


def _text(value):
  return "not measured" if value is None else str(value)


def _no_heartbeat(observed, subject, wire_heartbeats, wire_acknacks):
  """No heartbeats at all from a RELIABLE endpoint that believes it is matched.

  One definition, reached from both the published and the unpublished writer
  paths: the absence of heartbeats means the same thing either way, and having
  written it twice would let the two drift.
  """
  return Finding(
      id="reliable.no_heartbeat",
      rung=RUNG_PAYLOAD,
      severity=Severity.ERROR,
      title=f"RELIABLE, matched, but no heartbeats from {subject[0]}",
      observed="; ".join(observed),
      root_cause=(
          "A RELIABLE writer must heartbeat every reader it considers "
          "matched. Zero heartbeats while the match is reported is the "
          "signature of an ASYMMETRIC MATCH: this side matched, the other "
          "side did not, and each side runs its own matching checks so the "
          "more permissive one reports success while the stricter one "
          "silently rejects. Cross-vendor the usual triggers are type "
          "consistency enforcement, a data representation the peer will not "
          "accept, or a type name that differs after IDL module mangling. An "
          "unreachable unicast locator produces the same silence."),
      remedy=("Check the peer's own side for a rejected endpoint, and compare "
              "its type-consistency and data-representation settings against "
              "the type findings in this report. Confirm UDP reachability in "
              "both directions, not only from here."),
      evidence={"wire_heartbeats": wire_heartbeats,
                "wire_acknacks": wire_acknacks},
  )


def check_reliable_handshake(context):
  """Heartbeats out, acknowledgments back - from counters and from packets."""
  probe = context.probe
  endpoint = context.endpoint
  if probe is None or not probe.created or endpoint is None:
    return []
  if not probe.matched:
    # Rung 4 already owns "never matched". A handshake finding on top of it
    # would be the same fault reported twice, one rung too high.
    return []
  if not _reliable(endpoint):
    return []

  writer_probe = getattr(probe, "probe_kind", "reader") == "writer"
  wire_heartbeats = _wire(context, "heartbeats")
  wire_acknacks = _wire(context, "acknacks")

  if writer_probe:
    # The probe is the writer. Our own counters describe what we sent and what
    # the selected reader sent back.
    sent = probe.writer_protocol.get("sent_heartbeat_count")
    acked = probe.writer_protocol.get("received_ack_count")
    nacked = probe.writer_protocol.get("received_nack_count")
    observed = [f"datawriter_protocol_status sent_heartbeat_count = {_text(sent)}",
                f"received_ack_count = {_text(acked)}",
                f"received_nack_count = {_text(nacked)}",
                f"capture HEARTBEAT = {_text(wire_heartbeats)}",
                f"capture ACKNACK = {_text(wire_acknacks)}"]
    outbound = _first_positive(sent, wire_heartbeats)
    inbound = _first_positive(acked, wire_acknacks)
    subject = ("the probe's writer", "the selected reader")

    # A writer probe that published nothing cannot judge the return half, and
    # must not try. There is nothing for the reader to acknowledge, and the
    # probe snapshots its counters the instant the match appears - so a healthy
    # RELIABLE reader reads as `received_ack_count = 0` and was being reported
    # as `reliable.no_acknowledgment`, a WARN blaming firewalls, NAT and
    # one-way routing for rti_doctor's own restraint. Verified against an
    # ordinary healthy reader: WARN without `--write-samples`, `reliable.ok`
    # with it, same endpoint.
    #
    # The outbound half is still real and still worth reporting: heartbeats
    # leaving a RELIABLE writer that believes it is matched is what an
    # asymmetric match would NOT produce.
    if not getattr(probe, "wrote_samples", False):
      if not outbound:
        return [_no_heartbeat(observed, subject, wire_heartbeats, wire_acknacks)]
      return [Finding(
          id="reliable.not_measured",
          rung=RUNG_PAYLOAD,
          severity=Severity.INFO,
          title="Heartbeats are being sent; acknowledgment was not measured",
          observed="; ".join(observed),
          root_cause=(
              "The probe created a matching writer and published nothing, so "
              "the selected reader had nothing to acknowledge. Zero "
              "acknowledgments here is rti_doctor's own restraint, not a "
              "property of the reader or of the path back from it. What IS "
              "established is the forward half: this writer considers the "
              "reader matched and is heartbeating it, which an asymmetric "
              "match would not produce."),
          remedy=("Press w (or pass --write-samples) to publish a few synthetic "
                  "samples and verify delivery end to end. The subscribed "
                  "application receives them as ordinary data, so it is asked "
                  "for rather than assumed."),
          evidence={"wire_heartbeats": wire_heartbeats,
                    "wire_acknacks": wire_acknacks,
                    "published": False},
      )]
  else:
    # The probe is the reader. `sent_nack_count` is what we sent back; a pure
    # positive acknowledgment leaves no reader-side counter, so an arriving
    # sample is the other evidence that our side of the protocol is working.
    heard = probe.protocol.get("received_heartbeat_count")
    sent_nack = probe.protocol.get("sent_nack_count")
    observed = [f"datareader_protocol_status received_heartbeat_count = {_text(heard)}",
                f"sent_nack_count = {_text(sent_nack)}",
                f"capture HEARTBEAT = {_text(wire_heartbeats)}",
                f"capture ACKNACK = {_text(wire_acknacks)}",
                f"valid samples taken = {probe.samples_taken}"]
    outbound = _first_positive(heard, wire_heartbeats)
    inbound = _first_positive(sent_nack, wire_acknacks,
                              probe.samples_taken or None)
    subject = ("the selected writer", "the probe's reader")

  if outbound is None and inbound is None:
    # Nothing measured either way. Saying "the handshake is broken" from an
    # unexposed counter and an absent capture would be inventing a symptom.
    return [Finding(
        id="reliable.not_measured",
        rung=RUNG_PAYLOAD,
        severity=Severity.INFO,
        title="The reliable handshake could not be measured",
        observed="; ".join(observed),
        root_cause=(
            "This pair is RELIABLE, so RTPS requires a heartbeat/acknowledgment "
            "exchange between them - but neither source could report one. The "
            "middleware counters were unavailable on this binding, and no "
            "packet capture was run for this endpoint."),
        remedy=("Open an endpoint report and select packet capture when it "
          "opens. The "
                "handshake is visible in the packets regardless of vendor, and "
                "regardless of which counters the bindings expose."),
        evidence={"wire_heartbeats": wire_heartbeats,
                  "wire_acknacks": wire_acknacks},
    )]

  if not outbound:
    return [_no_heartbeat(observed, subject, wire_heartbeats, wire_acknacks)]

  if not inbound:
    return [Finding(
        id="reliable.no_acknowledgment",
        rung=RUNG_PAYLOAD,
        severity=Severity.WARN,
        title=f"Heartbeats are being sent, but {subject[1]} is not answering",
        observed="; ".join(observed),
        root_cause=(
            "Heartbeats are reaching the wire and nothing is coming back. The "
            "forward path works, so this is the return path: the acknowledging "
            "side either never received the heartbeat, or its reply is not "
            "arriving. A one-way firewall rule, an advertised locator that is "
            "reachable in only one direction, and NAT without a matching return "
            "mapping all produce exactly this."),
        remedy=("Verify UDP reachability from the acknowledging side back to "
                "this host, on the ports in Appendix C. A capture taken on the "
                "peer's host will show whether the heartbeats arrive there."),
        evidence={"wire_heartbeats": wire_heartbeats,
                  "wire_acknacks": wire_acknacks},
    )]

  return [Finding(
      id="reliable.ok",
      rung=RUNG_PAYLOAD,
      severity=Severity.OK,
      title="Reliable handshake verified in both directions",
      observed="; ".join(observed),
      evidence={"wire_heartbeats": wire_heartbeats,
                "wire_acknacks": wire_acknacks},
  )]


def _first_positive(*values):
  """The first value that is a positive count; 0 if any was measured as zero.

  Returns None only when every source declined to measure, which is what
  separates "not observed" from "observed to be absent".
  """
  measured = [value for value in values if value is not None]
  if not measured:
    return None
  for value in measured:
    if value:
      return value
  return 0


def check_wire_disagrees(context):
  """A capture that contradicts the middleware's own counters.

  Not a fault of the system under test - a fault in how this report is scoping
  its evidence, and worth saying so rather than letting a reader pick whichever
  number suits them. The capture is frame-scoped and can include a neighbour's
  traffic; the counters are entity-scoped and cannot.
  """
  probe = context.probe
  if probe is None or not probe.created:
    return []
  wire_heartbeats = _wire(context, "heartbeats")
  if wire_heartbeats is None:
    return []
  if getattr(probe, "probe_kind", "reader") == "writer":
    counter = probe.writer_protocol.get("sent_heartbeat_count")
    label = "datawriter_protocol_status sent_heartbeat_count"
  else:
    counter = probe.protocol.get("received_heartbeat_count")
    label = "datareader_protocol_status received_heartbeat_count"
  if counter is None:
    return []
  # Only the disagreements that change a conclusion: one source saw the
  # handshake and the other saw none of it. Unequal positive counts are
  # expected, since the capture window and the probe window are not the same
  # interval and a frame can coalesce submessages.
  if bool(counter) == bool(wire_heartbeats):
    return []
  return [Finding(
      id="reliable.evidence_disagrees",
      rung=RUNG_PAYLOAD,
      severity=Severity.INFO,
      title="Packet capture and status counters disagree about heartbeats",
      observed=f"{label} = {counter}; capture HEARTBEAT = {wire_heartbeats}",
      root_cause=(
          "One source observed the reliable handshake and the other observed "
          "none of it. They measure different things: the counter is scoped to "
          "the entity the probe created, while the capture is scoped to frames "
          "matching a BPF filter and a window that starts before the probe and "
          "ends after it. A capture on a shared interface can therefore include "
          "another endpoint's heartbeats, and a capture filter that cannot reach "
          "the endpoint's real locators can miss all of them."
          + (shared_memory_note(context) or "")),
      remedy=("Check the capture filter in Appendix C against the endpoint's "
              "advertised locators. Where the two disagree, the status counter "
              "is the one scoped to this endpoint."),
      evidence={"counter": counter, "wire_heartbeats": wire_heartbeats},
  )]


CHECKS = (
    check_reliable_handshake,
    check_wire_disagrees,
)
