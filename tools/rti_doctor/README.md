# RTI Doctor

`rti_doctor` is a Python/Textual DDS **interoperability diagnostic**. You point it
at a domain, it discovers every participant on it — including ones from Fast DDS,
Cyclone DDS, OpenDDS, or OpenSplice — and for any topic it tells you whether
communication is possible, whether samples can be fully deserialized, and what the
most likely root cause is when they can't.

It is an **observer inserted into a running system**, not a replacement for one
side of it. Because it sees both the writers' offered QoS and the readers'
requested QoS in discovery data, it can report why two live endpoints will never
match without you supplying anything.

It creates DataReaders and nothing else. It never writes user data, never changes
remote configuration, and always closes what it created.

## Quick Start

From the repository root:

```bash
./tools/rti_doctor/run_rti_doctor.sh
```

You'll be asked for a domain ID exactly as `rti_spy` asks, then get a system
overview. Use `Up`/`Down` and `Enter` to choose Issues or DDS Topology & Health.
The Issues menu shows Errors, Warnings, and Info with their current counts;
selecting one shows only that severity. Keys:

| Key | Action |
|---|---|
| `Up` / `Down` / `Enter` | Select a menu item, drill into a participant/topic, or deep-diagnose an endpoint |
| `1` / `2` / `3` / `4` | In Topology: participants, readers, writers, topics |
| `o` | Open a passive report for the selected writer where available |
| `i` | In Topology: the issues linked to the highlighted row |
| `m` | Observed domain metrics |
| `r` | Re-scan (every screen shows a snapshot, never a live feed) |
| `c` | On an endpoint report: capture RTPS packets for that endpoint |
| `s` | Save the current system or diagnostic report as a shareable text file |
| `b` / `Esc` | Back |
| `q` | Quit |

Every screen shows a *snapshot*, not a live view, so a reading never changes
under you while you read it. `r` takes a new one.

## Packet Capture Is Something You Ask For

Nothing runs `tshark` unless you press `c` on a reader or writer report. Before
it starts, the screen states the interface, the file it will write (under
`tools/rti_doctor/test_output/rti_doctor_captures/`, with a `.tshark.log` beside
it) and how long it will run; the capture is bounded by tshark's own
`-a duration:`, so one that is abandoned still stops. `--capture-interface`
chooses the interface; without it, `c` uses `any`.

A few facts are observable **only** in RTPS packets — a Fast DDS peer's product
version above all — and reports render those as `Run capture to ascertain`
rather than as absent, because "nobody looked" and "there is nothing there" are
different answers. One capture answers both questions: the user data that
crossed the wire, and the discovery metadata around it.

## The Visibility Ladder

Cross-vendor failures come in rungs, and each one fails differently. The report
is ordered by this, and a higher-rung finding is annotated with the lower-rung
findings that would explain it. Nothing is hidden: the link is context, and
every finding stays in the list, the counts and the exit code.

| Rung | Mechanism | How a failure looks |
|---|---|---|
| 0 | Our own configuration | **Nothing appears at all** |
| 1 | SPDP participant discovery | **Nothing appears at all** |
| 2 | SEDP endpoint discovery | Participant visible, no topics under it |
| 3 | Type resolution (TypeLookup) | Topic and type *name* visible, no schema |
| 4 | QoS matching (RxO) | Endpoints exist but never match |
| 5 | Payload decode | Matched, but samples lost or unreadable |

**The most common cross-vendor state is rung 2 without rung 3**: you see
`topic_name` and `type_name` because those are plain discovery strings, but there
is no usable type, because the schema comes from a separate request/reply service
the peer may not implement.

**Rungs 0 and 1 leave no row to click on**, so they get a separate blind-spot
audit shown above the participant table. It covers the conditions that make an
RTI participant and a third-party participant mutually invisible *on the same
domain ID*: a domain tag set on our side, SPDP2 configured (which does not
interoperate with standard SPDP at all), a secure-vs-unsecure mismatch,
`accept_unknown_peers = false`, and nonstandard RTPS port mappings. It also
reuses the passive domain-0 announcement scan, so "nothing is here" can become
"something is alive, but on domain 5".

It does **not** diagnose multicast reachability. Whether multicast works between
two hosts is not observable from either side's participant QoS, and a finding
derived from rti_doctor's own defaults would describe the diagnostic, not the
system it was pointed at.

## CLI

```text
-d, --domain          DDS domain ID (prompts on startup; 1 when non-interactive)
    --system          Headless: assess the DDS system and exit (stage one)
-t, --topic TOPIC     Headless: diagnose one topic and exit (stage two)
-o, --output PATH     Write the report to PATH instead of stdout
    --probe-timeout   Seconds to observe a probed reader (default: 10.0)
    --type-wait       Seconds to wait for remote type resolution (default: 5.0)
    --settle          Seconds to let discovery settle first (default: 3.0)
    --scan-timeout    Seconds to listen for active domains (default: 32.0)
    --no-domain-scan  Skip the active-domain scan before prompting
    --no-probe        Static checks only; never create a reader
    --type-object-v1-only
          Advertise TypeObject v1 and disable TypeLookup v2 for an experiment
    --pcap PATH       Analyze RTPS user-data packets in an existing capture (with --topic)
    --capture-interface IFACE
              Interface for packet capture: captured while probing with --topic,
              or used by the TUI's 'c' capture action (default: any)
-i, --interval        UI refresh interval (default: 2.0)
    --debug-log PATH  Discovery/probe log output
    --connext-log PATH
          Native Connext middleware diagnostics, including discovery parsing
    --connext-verbosity LEVEL
          silent (default) | exception | warning | status-local | status-remote | status-all
```

Headless work is two stages: assess the DDS system, then diagnose one endpoint.
Stage one is cheap and answers whether the system is visible and healthy at all.
Stage two is deliberately focused, because a full diagnosis probes, waits for
type resolution and can start a capture - work that scales linearly with the
number of writers and should be spent on the one you chose.

```bash
# Stage one - the system: discovery, topology and our own configuration
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --system -o system.txt

# Stage two - one topic, report to stdout
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --topic SensorData

# Inspect direct RTPS packet evidence from a saved capture
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --topic SensorData --pcap session.pcapng

# Capture during one topic probe (writes tools/rti_doctor/test_output/rti_doctor_captures/*.pcapng)
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --topic SensorData --capture-interface lo

# Preserve native Connext discovery/TypeLookup diagnostics for later parsing.
# status-all includes the Fast DDS TypeInformation deserialization failure.
./tools/rti_doctor/run_rti_doctor.sh --domain 1 --topic SensorData --no-probe \
  --connext-log tools/rti_doctor/test_output/rti_doctor_connext.log \
  --connext-verbosity status-all
```

### Exit status

Usable directly in CI. No finding is excluded from that decision by a causal
guess about another finding.

| Code | Meaning |
|---|---|
| `0` | A diagnosis ran and reported no ERROR-severity finding |
| `1` | A diagnosis ran and reported at least one ERROR-severity finding |
| `2` | The named topic was not found — or the arguments were rejected |
| `3` | `--ready-after-participants` was not met before `--ready-timeout` |
| `4` | Doctor could not run: no license, an unusable domain, a failed startup |
| `130` | Interrupted (`Ctrl-C`) |

`1` means one thing only: **a diagnosis completed and found an error**. A
startup failure used to reach the shell as `1` too, by way of an uncaught
traceback, so a CI job could not tell "your system has an error" from "Doctor
never ran". A `4` prints one line on stderr saying what failed; the traceback
goes to `--debug-log`.

`2` is still overloaded — argparse rejects a bad command line with it as well —
so a wrapper that retries on "topic absent" should check stderr before looping.

## Manual Scenarios

Start a fixture in one terminal, then inspect the printed domain and topic from
another:

```bash
./tools/rti_doctor/test/run_manual_scenario.sh --scenario healthy
./tools/rti_doctor/run_rti_doctor.sh --domain 42
```

The scenarios default to domain `42`; use `--domain ID` to override it. Press
`Ctrl-C` in the scenario terminal to stop it. Fast DDS scenarios explicitly
stop and remove their Docker containers during that cleanup.

## The Shareable Report

The text report is the only output rti_doctor produces. There was a second,
`--format json`, documented in its own code as an unstable dump with no schema —
so nothing could safely depend on it, while it still had to be kept working and
in step with the text. Everything a script needs is on the face of the report:
one `[SEVERITY] rung N  finding.id` line per finding, labelled fields under it,
and a fixed section order. `test/doctor_e2e.py` reads it back that way.

`s` in the TUI, or `-o` headlessly, writes a plain-text report: fixed 100-column
width, ASCII only, fixed section order so two reports diff cleanly. It carries an
environment header (host, OS, Connext version, `NDDSHOME`, Python, domain, the
exact command), the verdict, the peer identity, every finding with observed
evidence / root cause / remedy, the discovered type as IDL, and a complete raw
counter dump.

Three rules the writer follows:

- **Only observed values.** A counter unavailable on this Connext version prints
  `n/a (not available on Connext X.Y.Z)` — never `0`, never omitted.
- **The raw appendix is complete, not filtered**, so anyone who doubts a finding
  can check the evidence themselves.
- **Nothing is filtered out by a guess.** A finding whose likely cause is also
  present says so on a `Likely explained by` line, but stays fully reported and
  counted. The link matches on finding id alone, so it can point at a condition
  on another topic — confirm it applies before acting on it.

## Reading a Verdict

```
VERDICT: matched, samples arriving, payload PARTIAL (2 of 41 members unreadable)
```

The report keeps four very different "no data" worlds distinct, because
conflating them is what makes this class of bug expensive:

| Verdict | Meaning |
|---|---|
| `not probed (...)` | Could not even create a reader — usually no type (rung 3) |
| `NOT MATCHED` | Endpoints exist but don't match — rung 3 or 4 |
| `matched but no samples received` | Writer idle, filtered, or the return path is broken |
| `payload FULL` | Every member of a real sample was read successfully |
| `payload PARTIAL` | Specific field paths could not be decoded |
| `payload FAILED` | Nothing in the sample could be decoded |

## Finding IDs

Findings have stable, greppable ids. The ones that matter most:

| id | Rung | Meaning |
|---|---|---|
| `blind.domain_tag` | 0 | A domain tag makes all cross-vendor discovery impossible |
| `blind.spdp2` | 0 | SPDP2 cannot discover standard-SPDP peers |
| `blind.unknown_peers_rejected` | 0 | `accept_unknown_peers=false` silently drops valid peers |
| `blind.nonstandard_ports` | 0 | RTPS port mapping deviates from the interoperable default |
| `blind.other_domain_active` | 1 | Traffic exists, but on a different domain |
| `blind.empty_domain` | 1 | Nothing discovered; lists the likely causes |
| `vendor.identify` | 1 | Which implementation the peer is |
| `locator.unroutable` | 1 | Peer advertises an address unreachable from here |
| `transport.class_mismatch` | 1 | Peer advertises no UDP transport |
| `endpoint.none` | 2 | Participant visible but exposing no endpoints |
| `type.no_type_info` | 3 | No usable schema, with the specific reason named |
| `type.name_conflict` | 3 | One topic, several type names |
| `type.assignability` | 3 | External TypeObject check: each discovered reader can or cannot accept a writer type; remote enforcement QoS remains unobservable |
| `type.extensibility` | 3 | FINAL/APPENDABLE/MUTABLE hazards |
| `repr.no_common` | 3 | Writer offers XCDR2 only |
| `qos.rxo_mismatch` | 4 | Two live endpoints whose QoS can never match, policies named |
| `match.none` | 4 | The probe reader never matched |
| `data.silent` | 5 | Matched but nothing arrived, with the sub-case identified |
| `data.fragmentation` | 5 | Large-data reassembly state |
| `data.deserialize_failure` | 5 | Connext itself could not decode a sample |
| `payload.partial` | 5 | Which field paths are unreadable |

## Supported Connext Versions

| Version | Status |
|---|---|
| 7.7.x | **Verified** — full check catalog, all tests pass |
| 7.3.x | **Verified** — all tests pass; `request_types_filter` is unavailable, which the report records explicitly |
| 6.1.2 | **Feature-detected but not verified here** — no 6.1.2 install was available to test against |

For Connext 7.3.x, RTI Doctor supports Python 3.9. The launcher selects the
matching Python 3.9 virtual environment and Connext API wheel automatically.

Every version-sensitive field goes through `rti_doctor/compat.py`, which reports a
missing field rather than assuming a value. The known differences are documented
in that module's docstring.

On 7.3.x, `DiscoveryConfig.request_types_filter` does not exist. That setting is
what makes Connext fetch a remote type for which it has no local matching reader,
so on 7.3.x a `type.no_type_info` finding is *less* conclusive — the report names
our own missing filter as the first candidate cause rather than blaming the peer.

## XTypes Compliance Mask

Connext's **default** XTypes compliance mask (`0x18C` on 7.7.0) is deliberately
*not* fully OMG XTypes 1.3 compliant - it preserves some legacy Connext encoding
behavior. RTI's own cross-vendor guidance is to use the VENDOR mask (`0x1A9`).

`rti_doctor` sets the VENDOR mask for its own process before creating any DDS
entity, so it cannot fail to decode a peer because of its own encoding defaults,
and records the mask actually in force in Appendix C of every report:

```text
  xtypes_compliance_mask     0x9a9 (VENDOR applied)
```

The equivalent for your own applications is:

```bash
export NDDS_XTYPES_COMPLIANCE_MASK=0x000001a9
```

**Measured caveat:** setting the vendor mask did *not*, by itself, fix an observed
Cyclone DDS case where no user data arrived. The mask governs serialization, not
whether a peer decides to match, so it is not a cure for "matched but no data".

## Verified Cross-Vendor Finding: Asymmetric Match

Against a live Cyclone DDS 11.0.1 writer on the same host, `rti_doctor`:

- identified the vendor correctly (`01.10`, RTPS 2.5),
- **resolved the remote type** through TypeLookup - cross-vendor type discovery works,
- flagged that Cyclone's types default to `FINAL` extensibility,
- matched the writer, and then received **zero data and zero heartbeats**.

It reports that as an **asymmetric match**: a writer that considers a reader
matched sends traffic to it, so zero user traffic over the test interval means the
writer has not completed the reciprocal match even though Connext has. Each side
runs its own matching checks and vendors differ in strictness, so the permissive
side reports a match while the stricter side silently rejects.

A `tshark` capture confirmed this independently: Cyclone announced its writer, the
RTI reader announced itself and sent ACKNACKs, and Cyclone never put a single user
DATA packet on the wire. Cyclone-to-Cyclone on the same topic worked, so the
publisher was healthy.

This is exactly the failure class the tool exists to name: without it, the
symptom is "it says matched, so why is there no data?"

An empty Cyclone `DataRepresentationQosPolicy` advertisement does not identify
the payload representation. Cyclone resolves an unspecified policy from the
type's defaults, which can select XCDR2. Use the optional PCAP evidence to report
the representation actually selected by that writer and type.

**This is the same emptiness a Connext writer advertises, and it does not mean
the same thing.** Measured against live Connext 7.7.0
(`test/test_data_representation_spike.py`), an empty advertisement from a
Connext writer means XCDR1: a writer configured explicitly `[XCDR1]` advertises
an empty sequence too, and both are refused by an XCDR2-only reader. Cyclone's
empty advertisement can mean XCDR2. So "advertised nothing" is a per-vendor
question, not a single fact — which is why the tool still declines to judge it
rather than guessing. See Q3 in `docs/DESIGN_DECISIONS.md`.

The controlled manual `FINAL`/XCDR1 fixture additionally uses explicit sequential
member IDs and a matching XCDR1-only writer/reader configuration. Cyclone still
reported zero writer matches while Connext reported one reader match and received
zero samples. Applying Connext's
`BuiltinQosLib::Generic.OtherDDSVendorCompatibility` participant profile did not
change that result. These controls narrow the remaining issue to Cyclone's
interpretation of Connext discovery or type metadata, not an implicit
data-representation selector or a missing dynamic member ID.

## Limitations

- **It cannot judge your application's QoS**, only the QoS of endpoints that are
  actually running. The probe mirrors the discovered writer's QoS deliberately, so
  a QoS finding always describes real endpoints, never a hypothetical reader.
- **It does not compare against your IDL.** Type comparison is between types
  discovered on the wire.
- **The blind-spot audit inspects our own participant**, so it can prove a
  self-inflicted blindness but cannot see the peer's configuration.
- **The domain scan is best-effort**: it relies on RTI's default domain
  announcements, so an empty result is not proof that no other domain is active.
- **Wire observation is opt-in and bounded.** `--pcap`, `--capture-interface`
  and the TUI's `c` action use `tshark` to count RTPS DATA/DATA_FRAG submessages
  and report the encapsulation IDs Wireshark actually decodes. Nothing else
  captures: no capture starts at startup, on navigation, or on a report you
  merely opened. A live capture applies
  a BPF filter for the selected domain's configured RTPS port range before packets
  are written; discovered writer ports outside that range are added explicitly.
  The resulting observations are then limited to the selected endpoint's RTPS
  source GUID prefix. No observed selected-peer user-data packet means only that
  none was present in that capture interval; it does not establish a selected
  representation. DDS Security payload encryption can also prevent user data from
  being decoded.
- **DDS Security is flagged, not diagnosed.**
- **OpenDDS and OpenSplice** are recognized by vendor id and carry advisory notes,
  but are not in the validation matrix. OpenDDS is only visible at all if it was
  configured for RTPS discovery rather than InfoRepo.

## Testing

`requirements.txt` is what the launcher installs on every run, so it holds
runtime dependencies only, with `textual` pinned exactly — the TUI uses APIs
that have moved between releases, and an unpinned upgrade would land on a user
at launch time. Development tooling is separate and no launch reads it:

```bash
pip install -r tools/rti_doctor/requirements.txt \
            -r tools/rti_doctor/requirements-dev.txt
```

Unit tests — no DDS participant required, ~60 tests:

```bash
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
    -m unittest discover -s tools/rti_doctor/test -p 'test_findings.py'
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
    -m unittest discover -s tools/rti_doctor/test -p 'test_checks.py'
```

Live integration tests — real participants, real probes, real fixtures, including
a headless drive of the whole TUI and a check that the probe leaks no entities:

```bash
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
    -m unittest tools.rti_doctor.test.test_live_integration
```

Cross-vendor wire tests launch matching publisher/reader pairs for Cyclone DDS
and Fast DDS, then run the complete `rti_doctor` CLI with a `tshark` capture.
They assert that Wireshark decoded RTPS user data and an actual CDR
encapsulation ID from the saved PCAPNG. The Fast DDS test uses the current Fast DDS
3.6.2 Docker build. This fixture tracks the currently supported Fast DDS release;
when diagnosing a vendor issue, update to the current fixture first, then retain
the resulting evidence for follow-up. Build it once before running the suite:

```bash
bash tools/rti_doctor/test/vendors/fastdds/build_image.sh
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools.rti_doctor.test.test_vendor_wire_e2e
```

Set `RTI_DOCTOR_TEST_CAPTURE_INTERFACE` when `any` is not the interface that
observes your DDS traffic. All RTI Doctor test artifacts remain under
`tools/rti_doctor/test_output/`.

RxO data-flow tests construct all diagnosed requested/offered mismatches
(reliability, durability, liveliness kind and lease, destination order,
Presentation scope and flags, deadline, latency budget, ownership, data
representation, and partition). They verify Connext-to-Connext,
Connext-to-Cyclone, and Cyclone-to-Connext in both compatible and mismatched
configurations: compatible readers receive samples; mismatched readers do not,
while writers continue publishing.

```bash
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools.rti_doctor.test.test_rxo_vendor_e2e
```

Type-extensibility data-flow matrices use a controlled, identical schema and
XCDR1 in both directions. They cover every FINAL/APPENDABLE writer-reader pair
for Connext/Cyclone and Connext/Fast DDS; each case requires endpoint matching
and actual reader samples. The Fast DDS matrix uses the same current Docker image
as the wire test and builds two generated TypeObject fixtures, one per
extensibility kind.

```bash
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools.rti_doctor.test.test_extensibility_vendor_e2e \
  tools.rti_doctor.test.test_fastdds_extensibility_vendor_e2e
```

### Manual scenarios

Start a long-running fixture in one terminal, then run the printed Doctor
GUI command from another. The launcher initializes the same Connext Python
environment as `run_rti_doctor.sh` and stops all fixture processes on Ctrl-C.
The GUI discovers the fixture; select the printed topic to inspect its report.

```bash
tools/rti_doctor/test/run_manual_scenario.sh \
  --scenario healthy --domain 42 --duration 300
```

Available scenarios are `healthy`, `no-type-info`, `large-data`, `partition`,
`bad-pair`, `rxo-compatible`, and `rxo-reliability-mismatch`. Cross-vendor
reliability controls are available in both directions as
`connext-cyclone-compatible`, `connext-cyclone-reliability-mismatch`,
`cyclone-connext-compatible`, `cyclone-connext-reliability-mismatch`,
`connext-fastdds-compatible`, `connext-fastdds-reliability-mismatch`,
`fastdds-connext-compatible`, `fastdds-connext-reliability-mismatch`, and
`fastdds-no-type-info`. The latter starts only a Fast DDS writer with
TypeInformation metadata suppressed; Doctor should discover the endpoint, emit
`type.no_type_info`, and report a `not probed` verdict.

The `rxo-` and cross-vendor scenarios start separate reader and writer
endpoints. Their printed command starts the normal Doctor GUI, so you can see
the same discovery and report flow as an interactive user. Cyclone cases require
the `cyclonedds` Python package. Fast DDS cases require Docker and the current
test image, which can be built with:

```bash
bash tools/rti_doctor/test/vendors/fastdds/build_image.sh
```

The `fastdds-connext-compatible` fixture deliberately uses the custom Fast DDS
FINAL TypeObject from the vendor suite: its endpoints exchange data, but Doctor
may also report `type.assignability`. Run `--help` for all flags.

The fixture publisher can also be run by hand to create a system to point the
tool at:

```bash
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
    tools/rti_doctor/test/fixture_publisher.py --mode bad_pair --domain 1
```

| Mode | What it builds |
|---|---|
| `healthy` | Rich type (nested, sequence-of-struct, union, enum, optional, array) — expect `payload FULL` |
| `best_effort` | BEST_EFFORT writer; verifies the probe mirrors it |
| `no_type_info` | Type propagation disabled — expect `type.no_type_info` |
| `type_conflict` | Same topic and type name, incompatible structure |
| `large_data` | Samples above the MTU, to exercise fragmentation |
| `partition` | Writer in a named partition |
| `bad_pair` | A BEST_EFFORT writer *and* a RELIABLE/EXCLUSIVE reader — two live endpoints that can never match |

## Relationship to rti_spy and rti_view

Self-contained by design. `rti_doctor` borrows patterns from
[rti_spy](../rti_spy/rtispy.py) — the domain scan, the builtin-topic listeners,
the QoS-mirroring subscription, the screen layout — but imports nothing from it
and modifies nothing in it, so neither tool can break the other. `rti_spy` stays a
monitor; `rti_doctor` is the diagnostic.
