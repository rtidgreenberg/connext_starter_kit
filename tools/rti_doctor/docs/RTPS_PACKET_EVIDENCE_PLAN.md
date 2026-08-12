# RTI Doctor RTPS Packet Evidence Plan

## Goal

Extend the opt-in, bounded `tshark` capture used by deep diagnosis (`d`) so a
report can distinguish DDS-level symptoms from RTPS wire evidence:

- no packet sent or received;
- packets sent to an unexpected locator or port;
- reliable repair requested but not received;
- fragments missing or not reassembled;
- endpoint discovery/security/type-lookup traffic incomplete; or
- packets present but unavailable to DDS because of matching, security, or
  serialization failure.

This is evidence for a selected endpoint during one probe window. It is not a
replacement for builtin-topic discovery, nor a claim to decode arbitrary user
payloads.

## Collection Policy

- Start capture only for explicit deep diagnosis or an explicit headless capture
  option. Passive screens and ordinary reports never start `tshark`.
- Capture on `any` in the interactive Linux workflow; use the selected
  endpoint's RTPS domain port range plus advertised UDPv4 ports as the BPF
  scope. Headless mode retains the operator-selected interface.
- Bound capture to the probe interval and save PCAPNG/log files under
  `test_output/rti_doctor_captures/`.
- Store a compact normalized summary in the report. Keep the PCAPNG optional
  evidence for a ticket, not a required runtime dependency.
- If `tshark` is unavailable or capture privileges are denied, record that in
  the report and continue the DDS diagnosis.

## Evidence Model

Preserve three levels rather than flattening every UDP datagram into one result.

| Level | Key fields | Meaning |
|---|---|---|
| Frame | frame number/time, IP addresses, UDP ports, byte length | Where traffic was actually observed and its timing/direction. |
| RTPS message | source GUID prefix, protocol version, vendor ID | Which participant emitted the RTPS message. |
| Submessage | ordinal, ID, flags, writer/reader entity IDs, sequence state | The operation and endpoint identity to which a conclusion may apply. |

A writer GUID is `source GUID prefix + writer entity ID` from the same DATA,
HEARTBEAT, GAP, or DATA_FRAG submessage. A reader entity ID alone is not a
globally unique reader identity; when possible combine it with directed context
and the discovery table. Never call packet byte totals exact per-writer values:
coalesced frames can contain multiple submessages and writers.

## Extraction Phases

### Phase 1: Transport and endpoint identity

Add per-frame and per-submessage extraction for:

- `frame.number`, `frame.time_epoch`, `ip.src`, `ip.dst`, `udp.srcport`,
  `udp.dstport`, and frame/UDP length;
- `rtps.guidPrefix.src`, protocol version, and vendor ID;
- `rtps.sm.id`, submessage flags, and submessage length;
- `rtps.sm.wrEntityId`, `rtps.sm.rdEntityId`, sequence number; and
- `INFO_DST` and `INFO_TS` as inherited context for the immediately following
  submessage only.

Analysis:

1. Compare observed UDP tuples with discovered participant/endpoint locators.
2. Report unexpected destination address/port as a reachability clue, not a
   fault: NAT, relays, and containers may legitimately rewrite source tuples.
3. Use writer GUID filtering for writer targets. For reader targets, report a
   reader-entity filter as weaker evidence unless directed participant context
   also identifies the reader.

### Phase 2: Reliable delivery and repair

Extract each control submessage into a normalized record, keeping both raw and
decoded bit values:

| Submessage | Required fields | Analysis |
|---|---|---|
| HEARTBEAT | first/last sequence number, count, final/liveliness flags | Writer advertises data availability; absence of ACKNACK is a return-path or reader-side clue. |
| ACKNACK | bitmap base, number of bits, bitmap, count, final flag | Set bits identify requested missing samples; repeated identical requests indicate repair is not arriving. |
| GAP | gap start, bitmap base/bitmap | Writer declares samples unavailable; do not label this packet loss without context. |
| DATA / DATA_FRAG | sequence number, reader ID, payload/key/inline-QoS flags | Confirms a writer sent the sequence toward a reader or unknown reader. |
| HEARTBEAT_FRAG / NACK_FRAG | fragment numbers, size/sample size, bitmap, count | Identifies missing fragments and failed large-data repair. |

Initial findings should be advisory until validated against live fixtures:

- `wire.no_return_path`: HEARTBEAT/DATA from the selected writer but no matching
  ACKNACK during a reliable reader probe;
- `wire.repair_unresolved`: repeated ACKNACK or NACK_FRAG bitmap without a
  subsequent matching DATA/DATA_FRAG repair;
- `wire.gap_declared`: relevant samples declared unavailable, with late-joiner,
  filtering, and history limits listed as possible causes; and
- `wire.fragment_repair`: missing fragments repeatedly requested or a mismatch
  between fragment/sample-size observations.

### Phase 3: Discovery, lifecycle, and type evidence

During a bounded capture, parse SPDP/SEDP and TypeLookup records separately
from user traffic:

- builtin endpoint-set bitmask;
- topic/type name, TypeIdentifier/TypeObject data when exposed;
- reliability, durability, ownership, partition, representation, and locator
  parameters;
- `PID_STATUS_INFO` raw/decoded dispose and unregister bits; and
- TypeLookup request/reply identities, correlated by GUID prefix and sequence
  number.

The native `DiscoveryRegistry` remains authoritative for current topology. RTPS
discovery is complementary evidence and must never be silently merged into its
counts.

### Phase 4: Security evidence

Detect, but do not attempt to infer protected contents from:

- `SEC_BODY`, `SEC_PREFIX`, `SEC_POSTFIX`, `SRTPS_PREFIX`, and `SRTPS_POSTFIX`;
- transformation kind (signing versus encryption); and
- the PSK-protection flag, secure builtin endpoints, and visible handshake/key
  exchange traffic.

If `tshark` cannot decrypt a wrapper, report only wrapper presence and any
dissector expert warning. Do not attribute enclosed entity IDs, QoS, sequence
numbers, or payload fields.

## Report Shape

Add a `WIRE OBSERVATION` section with separate subsections:

1. **Capture scope:** interface, BPF, duration, frame count, and any capture
   error.
2. **Target evidence:** target GUID/entity filter, matching frames, and the
   explicit attribution limitation.
3. **Transport path:** observed source/destination UDP tuples compared with
   advertised locators.
4. **Reliability evidence:** compact event counts plus the latest/most relevant
   ACKNACK, GAP, and fragment bitmap summaries.
5. **Security/type evidence:** wrapper/TypeLookup/dissector results when seen.

JSON should retain raw masks and decoded flag names. Human text should show a
short hex value and decoded names, for example:

```text
ACKNACK: reader=00000104 writer=00000103 base=42 bitmap=0x00000005
         missing sequences: 42, 44; count=7; final=false
```

## Dissector Compatibility

Do not assume every installed `tshark` exposes the same field names. At startup
or capture parse time:

1. query `tshark -G fields` once and cache supported RTPS field names;
2. build the field command from supported fields only;
3. record unavailable requested fields in the summary as `n/a (tshark field not
   available)`; and
4. preserve the original PCAPNG so newer Wireshark/tshark can inspect it later.

Do not make the entire capture fail because an optional field is absent.

## Safety Rules

- `INFO_DST` and `INFO_TS` apply forward to the next submessage, never the
  entire packet.
- A header GUID prefix names the sender participant, not every writer in a
  coalesced frame.
- A DATA packet proves emission, not remote delivery or application acceptance.
- A calculated Wireshark domain ID may be wrong with non-default port mappings.
- A topic/type label attached by Wireshark is discovery correlation, not a field
  inherent to user DATA.
- Encrypted RTPS must remain opaque unless the dissector explicitly decrypts it.

## Validation Plan

1. **Parser fixtures:** saved/constructed `tshark -T fields` output covering
   coalesced DATA+HEARTBEAT, ACKNACK/GAP bitmaps, DATA_FRAG/NACK_FRAG, lifecycle
   status, and protected RTPS wrappers.
2. **Unit tests:** preserve occurrence ordering, decode masks deterministically,
   reject cross-submessage attribution, and degrade when a field is missing.
3. **Live Connext test:** reliable writer/reader with intentional packet loss or
   a controlled late joiner; confirm ACKNACK/GAP conclusions against DDS status
   counters.
4. **Large-data test:** force fragmented samples and validate fragment evidence
   against reassembly/cache counters.
5. **Cross-vendor tests:** run the existing Cyclone and Fast DDS fixtures;
   verify that discovery/type evidence agrees with the native registry without
   asserting unsupported vendor fields.
6. **Security test where credentials are available:** distinguish protected
   traffic seen but opaque from a successful decrypted parse.

Implementation is complete only when every new finding is backed by a packet
fixture plus a live scenario or is clearly labelled observational/advisory.