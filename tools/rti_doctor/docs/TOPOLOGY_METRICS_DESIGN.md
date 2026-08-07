# RTI Doctor Topology Metrics

## Collection Policy

Every RTI Doctor report includes an observed topology snapshot:

- selected DDS domain ID and any domains found by the optional cross-domain scan;
- remote DomainParticipant count;
- remote DataReader count;
- remote DataWriter count;
- unique topic count and topic names.

The primary source is Doctor's existing builtin-topic `DiscoveryRegistry`. It is
already populated for diagnosis, so producing a snapshot adds no network traffic,
packet copying, or payload parsing. Doctor itself is excluded from all counts
because the registry stores remote entities only.

Fast DDS is an explicit exception: the recorded interoperability failure showed
valid Fast DDS SPDP/SEDP traffic even when Doctor missed the endpoint or could
not deserialize its TypeInformation. When native discovery is incomplete for a
Fast DDS peer, record a second, separate `tshark RTPS discovery` snapshot. It is
evidence of what was present on the wire, not a replacement for all DDS metadata.

## Coverage And Timing

The snapshot is an observed topology, not a claim that it contains every entity
that has ever existed on the domain. A late-starting DDS observer can miss an
endpoint announcement that is not replayed.

1. Run the normal bounded discovery settle period first. This costs no capture
   process and gives the best current topology that builtin discovery provides.
2. If cross-domain awareness is needed and the initial scan sees no evidence,
   run the existing passive default-domain announcement scan for up to 32
   seconds. The default announcement period is 30 seconds, so the extra two
   seconds cover an observer that began just after a remote participant's last
   announcement.
3. The 32-second scan identifies active domain IDs. It cannot reconstruct
   DataReader/DataWriter/topic SEDP announcements that a peer did not replay;
   report this limitation rather than inflating counts from assumptions.

## Packet Capture Escalation

Use `tshark` as an automatic bounded fallback when native discovery is
incomplete for a Fast DDS peer, and as optional evidence for other
vendor-specific problems. Do not run it for every normal report.

- Start with a domain-scoped BPF such as the configured RTPS port range, never
  an unrestricted interface-wide UDP capture.
- Use a short window, normally 3-5 seconds, and terminate immediately after the
  required SPDP/SEDP evidence appears.
- If no startup discovery arrives, extend only the passive domain-announcement
  wait to 32 seconds. Do not retain 32 seconds of interface traffic: either use
  native `scan_active_domains()` or a filtered, rolling capture with a bounded
  file size.
- Parse only RTPS discovery fields needed for evidence: vendor ID, GUID prefix,
  builtin endpoint bitmask, SEDP reader/writer entity IDs, topic name, type name,
  and the relevant QoS parameters. Never decode user payload merely to count
  topology.
- Save captures only on test failure or explicit debug request under
  `test_output/`; summaries belong in the report while PCAPNG remains optional.

## Future Capture Metrics

RTPS discovery parsing is implemented for PCAP/PCAPNG evidence through
`wire.inspect_discovery_pcap()`. It reports unique source GUID prefixes,
deduplicated endpoint observations, topic names, and SPDP builtin endpoint
bitmasks. It intentionally does not derive reader/writer counts from raw RTPS
yet: that requires a stable entity-kind classification table across the
dissectors and vendor variations. Never merge RTPS and native-discovery counts
silently: duplicate RTPS packets and missed historical SEDP announcements make a
merged number misleading.