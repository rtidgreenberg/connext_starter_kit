# RTI Doctor Code Review

Review date: 2026-08-03

Scope: all Python implementation modules under `tools/rti_doctor/rti_doctor`,
the CLI/TUI execution paths, packet-capture behavior, and the unit and live-test
coverage that accompanies them.

## Findings

### High - Live packet evidence is not correlated to the selected endpoint

`--capture-interface` starts tshark with only the BPF filter `udp`, then
`inspect_pcap()` accepts every RTPS packet containing a serialization
encapsulation and summarizes it into the selected topic's report. It neither
filters on the discovered writer GUID/entity ID nor verifies the RTPS endpoint
against the target topic. The special-case removal of builtin entity kinds does
not establish this association.

On a host carrying traffic for more than one DDS topic or domain, the report can
claim an unrelated writer's XCDR encapsulation, packet count, or byte count as
evidence for the target endpoint. This undermines the central distinction the
tool makes between advertised QoS and directly observed payload representation.

Affected code:

- `rti_doctor/__main__.py:271-281` starts a capture for a selected topic but
  passes no target identity to the capture parser.
- `rti_doctor/wire.py:79-109` filters only for packets with an encapsulation
  parameter and aggregates all resulting writers.
- `rti_doctor/wire.py:131-134` captures all UDP traffic on the interface.

Recommended fix: retain the selected endpoint's full GUID prefix and entity ID,
parse the matching RTPS writer identity from tshark, and include only those
packets in the report. Until that is implemented, label this appendix as
interface-wide observation rather than evidence for the selected writer. Add a
test PCAP with a target writer and a second user writer using a different
encapsulation; assert only the target's packets are reported.

Capture-efficiency requirement: scope every live tshark command as tightly as
the available pre-capture facts permit before it writes a packet. At minimum,
derive the selected domain's RTPS UDP port range from the active
`rtps_well_known_ports` QoS and pass that range in tshark's `-f` BPF expression,
instead of the current unrestricted `udp` capture. Where a discovered peer has
specific UDP locators, also constrain the capture to those host/port pairs.
Identity-level RTPS writer filtering is generally a Wireshark display-filter
capability and must remain an analysis-time safeguard, but it does not replace
the capture-time BPF filter: the latter minimizes packet-copy work, PCAP size,
and the impact on unrelated DDS traffic.

### High - Departed endpoints remain indefinitely and are diagnosed as live

Both builtin-topic listeners ignore every invalid sample. Invalid discovery
samples are the lifecycle signal for disposed/unregistered DataWriter and
DataReader instances, yet `DiscoveryRegistry` has no removal or expiry path for
either endpoint or participant records. A writer that has stopped can therefore
remain in the sweep and in `find_writer()` indefinitely. Its subsequent probe
will time out or fail to match, producing a report about a peer that no longer
exists.

Affected code:

- `rti_doctor/discovery.py:277-283` and `rti_doctor/discovery.py:295-301` only
  upsert valid samples and drop the invalid lifecycle samples.
- `rti_doctor/discovery.py:23-85` owns persistent dictionaries but provides no
  removal or liveness-expiration mechanism.

Recommended fix: remove endpoint records when the builtin sample has a valid
key and an invalid/disposed instance state. Apply the same lifecycle policy to
participants, or explicitly expire them from a fresh discovery snapshot. Add a
live test that terminates a fixture writer, waits for its discovery disposal,
and verifies that it disappears from `writers()` and cannot be selected by a
sweep.

### High - Static QoS analysis can certify incompatible endpoints as compatible

`EndpointRecord` does not retain `latency_budget`, and the discovery conversion,
merge logic, and `compare_endpoints()` never evaluate it. Cyclone DDS treats a
reader latency budget smaller than the writer's as an RxO incompatibility, but
this tool returns no mismatch and emits `qos.compatible`.

The same comparison checks only Presentation's `access_scope`; it ignores
`coherent_access` and `ordered_access`. A reader that requests either behavior
from a writer that does not offer it can also be labelled compatible. The report
therefore represents a partial comparison as a full compatibility conclusion.

Affected code:

- `rti_doctor/records.py:76-85` omits `latency_budget` from the stored QoS.
- `rti_doctor/discovery.py:246-267` and `rti_doctor/discovery.py:141-159` do
  not read or merge it.
- `rti_doctor/checks/qos_match.py:125-221` compares selected policies but not
  latency budget or the Presentation booleans.
- `rti_doctor/checks/qos_match.py:257-265` emits `qos.compatible` whenever the
  incomplete comparison finds no mismatch.

Recommended fix: capture and compare `latency_budget` with the same duration
rule used for deadline, compare `coherent_access` and `ordered_access`, and use
an explicitly partial/indeterminate finding whenever a required QoS policy
cannot be read. Add unit fixtures for all three incompatibilities.

### Medium - A stuck tshark can abort diagnosis and escape cleanup

`LiveCapture.finish()` calls `communicate(timeout=5)` after `terminate()` but
does not catch `subprocess.TimeoutExpired`. Consequently a tshark process that
does not exit promptly raises from the `finally` block in
`run_headless_topic()`. No report is emitted, `kill()` is never attempted, and
the child can remain alive. This is particularly problematic for a diagnostic
intended to be run against impaired network environments.

Affected code:

- `rti_doctor/wire.py:143-157` has no timeout recovery or forced kill.
- `rti_doctor/__main__.py:278-281` invokes `finish()` in a `finally` block but
  does not isolate capture-finalization failure from report generation.

Recommended fix: catch `TimeoutExpired`, call `kill()`, drain the process, and
return a structured wire-observation error. Ensure the report still renders
with an unavailable capture appendix. Add a unit test with a mock process that
times out on `communicate()`.

### Medium - Participant creation overwrites global factory QoS instead of restoring it

`create_participant()` constructs a new factory QoS object, changes
`autoenable_created_entities`, and writes that object back after creation with
the value forced to `True`. It never reads and restores the process's prior
factory QoS. In an embedding process that has intentionally disabled automatic
entity enabling or set any other factory policy, running Doctor permanently
changes that process-wide configuration.

If participant construction fails, `participant` is also unbound at the return
statement, which can replace the original DDS exception with
`UnboundLocalError` and obscure the actual setup failure.

Affected code:

- `rti_doctor/discovery.py:218-241` replaces the global factory QoS and restores
  an invented value rather than the previous one.

Recommended fix: read and retain the existing factory QoS, make a copy with
only automatic enabling changed, and restore the retained QoS in `finally`.
Return only after successful construction, and close a partially created
participant if listener installation or `enable()` fails. Add mock-based tests
for construction failure and exact QoS restoration.

### Medium - Custom RTPS port mappings are reported as inherently non-interoperable

`check_nonstandard_ports()` reports an ERROR for any local departure from the
default RTPS port mapping and says that other implementations will never
communicate. The defaults are needed for out-of-the-box interoperability, but
DDS applications using the same explicitly configured mapping can interoperate.
The peer's mapping is not available in discovery, so the tool cannot conclude
that the mappings differ.

Affected code:

- `rti_doctor/checks/blind_spots.py:180-213` treats any local deviation as a
  proven cross-vendor failure.

Recommended fix: downgrade this to a warning that reports a local compatibility
risk, state that every peer must use the same mapping, and avoid suppressing
later match evidence solely because this local configuration is non-default.

### Medium - Live tests choose domain IDs that can wrap into privileged UDP ports

The live fixture randomizes domains in the range `401..600`. With the default
RTPS well-known port formula, a selected domain can wrap the computed discovery
port through the 16-bit UDP range and land below `1024`. The review run selected
domain `496`, for which Connext attempted to bind UDP port `328` and failed with
`Permission denied`. The same suite can therefore pass or fail depending on the
random domain rather than on the Doctor behavior under test.

Affected code:

- `test/test_live_integration.py:31-33` selects a random domain in an unsafe
  range for the default RTPS port mapping.

Recommended fix: use a deterministic domain whose default multicast and
unicast ports are within `1024..65535`, or calculate and reject any random
candidate whose complete RTPS port set is out of range or privileged. Do the
same audit for every vendor fixture that uses default RTPS port arithmetic.

## Implementation Status

All findings above were applied after the review.

| Finding | Resolution |
|---|---|
| Live packet evidence correlation | Live capture uses a domain-scoped BPF filter before recording. PCAP analysis retains only records whose RTPS source GUID prefix matches the selected endpoint; entity ID remains report context. Vendor E2E tests pass for Cyclone DDS and Fast DDS. |
| Departed endpoint lifecycle | Invalid builtin endpoint samples remove their records, participant snapshot refresh removes departed participants and their endpoints, and listener disposal is unit-tested. |
| Partial QoS compatibility claims | `latency_budget` and Presentation `coherent_access` / `ordered_access` are retained and compared. A non-mismatch result now says no observable mismatch rather than certifying full compatibility. |
| Stuck tshark cleanup | Capture finalization terminates, kills and drains a non-responsive tshark process, returning structured capture evidence instead of aborting diagnosis. |
| Factory QoS mutation | Participant setup restores the exact preceding factory QoS and closes a partially created participant before reraising setup failures. |
| Custom port mapping claim | The diagnostic is now an advisory warning explaining that peers with matching explicit mappings can interoperate; it does not suppress match evidence. |
| Unsafe live-test domains | Live integration domains now stay in a safe non-privileged range. |

Capture scope remains deliberately conservative for host-network and Docker/NAT
deployments: a discovered locator address is not used as a BPF host predicate,
because that address may not be the one visible on the capture interface. The
domain RTPS port range, plus any out-of-range discovered writer port, bounds the
pre-capture work; the source GUID prefix provides the target-specific analysis
guard. An empty selected-peer observation remains non-conclusive.

## Test Coverage

Focused deterministic tests passed after the review:

```text
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools/rti_doctor/test/test_checks.py \
  tools/rti_doctor/test/test_wire.py \
  tools/rti_doctor/test/test_findings.py

Ran 62 tests in 0.071s
OK
```

The existing test suite has no coverage for builtin discovery disposal,
interface-capture target correlation, `LiveCapture` timeout recovery, or
factory-QoS restoration. The live and vendor tests validate healthy flows but
do not exercise those failure paths.

A full discovery run was attempted after the focused suite. It ran 79 tests but
failed in `TestLargeData.setUpClass` because its randomized domain selected a
privileged wrapped RTPS port (`328`), not because of a product-code assertion.

Correction retained from the prior review: Cyclone DDS source-level verification
shows that `LATENCY_BUDGET` participates in its RxO match check, and the same
source checks both Presentation boolean flags. An earlier Connext AI answer
saying otherwise was incorrect.

Representation note: Cyclone DDS resolves an unspecified data-representation
policy from the type's defaults, which can prefer XCDR2. An empty sequence in
discovery is therefore insufficient to infer XCDR1 and should remain a
non-conclusive diagnostic state.

## Review Notes

The Doctor directory is untracked in this worktree, so the review used the
filesystem rather than `git diff` as its source of truth. Unrelated worktree
changes were not altered.
