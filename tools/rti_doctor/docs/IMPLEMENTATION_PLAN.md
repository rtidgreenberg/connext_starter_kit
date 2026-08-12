# rti_doctor Implementation Plan

## Goal

A standalone Python DDS interoperability diagnostic app. It listens to a domain
the way [rti_spy](../rti_spy/rtispy.py) does — pick a domain, see every
participant on it, including ones published by non-RTI open-source DDS
implementations — and when you select a topic it answers three questions:

1. **Can we discover and match this writer?** — and if not, exactly which
   config, transport, discovery, or QoS condition blocks it.
2. **Can its samples be fully deserialized?** — every member of the type walked
   and read, with the exact field path of anything that fails.
3. **What is the most likely root cause?** — a ranked set of findings, each with
   observed evidence, probable cause, and a concrete fix.

The emphasis is cross-vendor: an RTI Connext reader against eProsima Fast DDS,
Eclipse Cyclone DDS, OpenDDS, or ADLINK/Vortex OpenSplice writers.

## Decisions

- **Standalone app**, not a mode inside `rti_spy`. `rti_spy` stays a monitor and
  is not modified. [rtispy.py](../rti_spy/rtispy.py) is already 1420 lines in one
  module with `endpoints`/`participants` as globals; adding ~35 checks and a
  findings model to it would require a risky package split of a working tool for
  no benefit to either.
- **Self-contained**, following the repo's existing precedent:
  [rti_view](../rti_view/rti_view/) has its own `discovery.py` rather than
  importing from `rti_spy`. `rti_doctor` reuses `rti_spy`'s *patterns* — copied
  and adapted with attribution — not its code.
- **Textual TUI** with the same interaction model as `rti_spy` (highlight a row,
  press a key), plus a headless mode, because a diagnostic you can't attach to a
  bug report is half a tool.
- **Read-only.** Creates readers, never writers. Never modifies remote
  configuration and never claims to have fixed anything.
- **Validation targets: Cyclone DDS (pip) and Fast DDS (Docker).** OpenDDS and
  OpenSplice are recognized by vendor ID and get advisory notes, but are not in
  the test matrix.
- Target Connext 7.7.x, degrade gracefully on 7.3.x — feature-detect every status
  and field via `getattr`, as [rtispy.py:60](../rti_spy/rtispy.py) already does
  for `request_types_filter`.

## The Visibility Ladder — the organizing principle

Cross-vendor visibility degrades in rungs, and each rung fails differently. This
determines which checks exist and where they surface.

| Rung | Mechanism | Cross-vendor fragility | How a failure looks |
|---|---|---|---|
| 0 | Our own config | Self-inflicted blindness | **Nothing appears at all** |
| 1 | SPDP participant discovery — ParameterList to well-known multicast `239.255.0.1` + standard port formula | Most robust; when it fails it fails totally | **Nothing appears at all** |
| 2 | SEDP endpoint discovery — reliable RTPS builtin endpoints | Usually works if rung 1 did; more moving parts | Participant visible, no topics under it |
| 3 | Type resolution — TypeInformation + TypeLookup Service | **Weakest link** | Topic and type *name* visible, `type` empty |
| 4 | QoS matching (RxO) | Well-specified, cleanly diagnosable | Reader never matches |

The dominant cross-vendor case is **rung 2 without rung 3**: you see `topic_name`
and `type_name` because those are plain SEDP strings, but you can't build a
`DynamicType` because the schema comes from a separate request/reply service the
peer may not implement.

**Rungs 0 and 1 have no row to click on.** Confirmed with Connext AI, the things
that make an RTI participant and a third-party participant mutually invisible on
the *same domain ID* are all config-level:

- **Domain tag** — Connext requires domain ID *and* domain tag to match. No other
  vendor advertises one, so any nonempty tag on our side is total blindness.
- **SPDP2** — Simple Participant Discovery 2.0 does **not** interoperate with
  standard SPDP. Not the 7.7 default, but a hard cliff if someone configured it.
- **Security posture mismatch** — secure vs unsecure participant; discovery never
  completes the handshake.
- **Multicast unavailable with no usable `initial_peers`**, or
  `accept_unknown_peers = false`.
- **Nonstandard `wire_protocol.rtps_well_known_ports`** or a nonstandard
  discovery multicast address.
- **OpenDDS configured for InfoRepo** discovery emits no peer-to-peer SPDP at all.

Vendor-specific parameter PIDs are *not* a likely blocker — unknown optional PIDs
are required to be skipped — so that stays a packet-capture item, not a check.

Because these failures are invisible, they need different treatment from the
per-row checks: a **blind-spot audit** of our own configuration, plus a port of
the passive domain-0 announcement scan at
[rtispy.py:106](../rti_spy/rtispy.py) (`scan_active_domains`). That scan matters
more here than at startup: it can see a participant announcing from a *different*
domain, turning "nothing is here" into "something is alive, but not on the domain
you picked."

## What We Reuse From rti_spy (copied, not imported)

- `scan_active_domains()` — including its docstring, which documents two
  empirically-confirmed and undocumented behaviors worth preserving verbatim.
- `configure_type_lookup_qos()` — already sets `request_types_filter = "*"`,
  which is exactly what rung-3 introspection needs, and documents why
  `enabled_builtin_channels` must **not** be overridden. Keep the comment.
- `PublicationListener` / `SubscriptionListener` and `merge_endpoint()` — the
  merge-on-update semantics are load-bearing for late type resolution.
- `create_topic_subscription()` — mirrors a discovered writer's QoS onto a
  DynamicData reader; the probe's reader creation is a diagnostic-instrumented
  version of this.
- `test/e2e_dynamic_publisher.py` — the separate-process publisher fixture the
  negative fixtures are variations on.
- `run_rtispy.sh` structure and [scripts/python_env.sh](../../scripts/python_env.sh)
  helpers for env bootstrap.

---

## Architecture

```
tools/rti_doctor/
  run_rti_doctor.sh          # env bootstrap, mirrors run_rtispy.sh
  requirements.txt           # textual (rti.connext resolved by python_env.sh)
  README.md
  IMPLEMENTATION_PLAN.md
  rti_doctor/
    __init__.py
    __main__.py              # CLI, domain resolution, interactive/headless dispatch
    domain_scan.py           # scan_active_domains()
    discovery.py             # builtin listeners -> DiscoveryRegistry
    records.py               # ParticipantRecord, EndpointRecord, type_state
    vendors.py               # vendor id table + per-vendor advisory notes (data)
    findings.py              # Finding, Severity, rung ordering, verdict rollup
    typewalk.py              # deferred payload-health traversal (backlog S8)
    probe.py                 # reader lifecycle + status sampling
    report.py                # text / JSON / Textual rendering
    checks/
      __init__.py            # registry + runner
      blind_spots.py         # rung 0-1: our own config, cross-domain scan
      static_discovery.py    # rung 2: vendor, locators, transport, security
      type_compat.py         # rung 3: type state, names, assignability, IDL
      probe_match.py         # rung 4: matching and QoS
      probe_payload.py       # deferred payload-health checks (backlog S8)
    views/
      participants.py        # participant list + blind-spot pane
      endpoints.py           # endpoint list per participant
      report.py              # findings screen, streams as probe progresses
      sweep.py               # diagnose-all-writers verdict table
  test/
    ...                      # Phases 7-8
```

A `DiscoveryRegistry` object replaces `rti_spy`'s module globals, because checks
need cross-endpoint queries (topic census, assignability between two writers on
one topic) and globals make that untestable.

**Finding model** — the single output currency of the whole app:

```python
Finding(
  id="type.no_type_info",     # stable, greppable, what tests assert on
  rung=3,                     # drives causal ordering and suppression
  severity=Severity.ERROR,    # ERROR | WARN | INFO | OK
  title="No type information available for this writer",
  observed="...",             # what we measured, with numbers
  root_cause="...",           # most likely cause
  remedy="...",               # concrete action
  evidence={...},             # raw values for the saved/JSON report
  refs=[...],                 # doc links
)
```

Checks are functions `check(ctx) -> list[Finding]` in a registry table, so the
catalog below is data, the runner is one loop, and every row is independently
unit-testable against fake discovery records.

## UI And CLI

**Same terminal UI as `rti_spy`** — this is a requirement, not a coincidence.
Textual, the same `Screen` stack navigation, the same `DataTable` row-highlight
interaction, the same `Header`/`Footer`, the same welcome-panel-with-instructions
pattern from `ParticipantListScreen`, and the same CSS idiom (bordered containers
with `$primary`/`$accent`/`$surface` theme colors). Existing bindings keep their
existing meanings: `Enter` drills down, `b` goes back, `q` quits. Someone who uses
`rti_spy` should not have to learn anything to use `rti_doctor`; the only new keys
are the diagnostic ones (`d`, `D`, `s`).

Interactive flow:

```
Domain 1 — 4 participants   [!] 1 blind-spot warning

 Participant Name      IP           Vendor        RTPS  Health
─────────────────────────────────────────────────────────────────
 publisher_app         10.0.0.5     RTI Connext   2.5   OK
 fastdds_pub           10.0.0.9     Fast DDS      2.3   ! no type
 cyclone_talker        10.0.0.11    Cyclone DDS   2.5   OK
 opensplice_node       10.0.0.14    OpenSplice    2.1   x QoS

 Enter endpoints   d diagnose   D sweep all   s save   q quit
```

- Endpoint screen adds `Type` (`resolved` / `pending` / `unavailable`) and
  `Health` columns to `Topic Name` / `Kind`.
- `d` on a participant → rung 0–3 findings plus an endpoint rollup, no probing
  (keeps a keypress cheap). `d` on an endpoint → targeted discovery and
  matching diagnosis through rung 4.
- `D` → sweep screen: probe every discovered writer, verdict table sorted by
  severity. The "I don't know which topic is broken" entry point.
- `s` → save the current report as a shareable plain-text file (see below).
- Report screen renders static discovery and matching findings immediately, with
   a visible progress line only while an explicit matching probe is running.

CLI:

- `-d/--domain`, `--scan-timeout`, `--no-domain-scan` — same semantics and
  defaults as `rti_spy`, including the 32.0s justification.
- `-t/--topic TOPIC` — headless, diagnose one topic and exit.
- `--all` — headless sweep of every writer.
  *(Removed: superseded by `--system` + `--topic`; see decisions C2/C2a/S4.)*
- `--format text|json` (default `text`), `-o/--output PATH`.
  *(Removed: `--format` is gone and the text report is the only output; see
  decision H1. `-o/--output PATH` is unchanged.)*

## The Shareable Report File

The primary output artifact is a **plain-text report file** — written by `s` in
the TUI, or by `-o` headlessly. Plain `.txt`, no markup, so it pastes into a
ticket, an email, or a terminal unchanged and stays readable in any viewer. Fixed
width 100 columns, ASCII only.

Structure, in fixed order so two reports diff cleanly against each other:

```
================================================================================
RTI DOCTOR INTEROP REPORT
================================================================================
Generated     2026-08-03 14:22:31 -0700
Tool          rti_doctor <version>
Host          <hostname>  <os> <kernel>
Connext       7.7.0  (NDDSHOME=/home/rti/rti_connext_dds-7.7.0)
Python        3.10.12
Domain        1
Scope         topic 'SensorData'      # or 'all writers (7)'

--------------------------------------------------------------------------------
DIAGNOSIS
--------------------------------------------------------------------------------
matched; no active discovery or QoS incompatibility found

--------------------------------------------------------------------------------
PEER
--------------------------------------------------------------------------------
Participant   fastdds_pub  @ 10.0.0.9
Vendor        eProsima Fast DDS (01.0F)
RTPS          2.3
Topic         SensorData
Type name     SensorData
Type state    RESOLVED (via TypeLookup, 1.4s after discovery)

--------------------------------------------------------------------------------
FINDINGS  (3 ERROR, 1 WARN, 2 INFO)
--------------------------------------------------------------------------------
  Evidence     writer.representation=[XCDR2]  reader.representation=[XCDR1]
               extensibility=APPENDABLE
  Reference    <doc link>

[WARN] rung 2  locator.no_multicast
  ...

--------------------------------------------------------------------------------
APPENDIX A — DISCOVERED TYPE (IDL)
--------------------------------------------------------------------------------
struct SensorData {
    ...
};

--------------------------------------------------------------------------------
APPENDIX B — RAW STATUS COUNTERS
--------------------------------------------------------------------------------
subscription_matched            current=1 total=1
datareader_protocol_status      received_sample_count=412 ...
sample_lost_status              total=2 last_reason=LOST_BY_DESERIALIZATION_FAILURE
...
```

Rules for the report writer:

- **Only observed values.** Every number traces to a real API read. If a counter
  isn't available on this Connext version, print `n/a (not available on 7.3.x)` —
  never omit it silently and never infer a value.
- The environment header exists so a report is self-explanatory to whoever
  receives it without asking follow-up questions.
- Appendix B is the complete raw counter dump, not a filtered one, so a reader who
  disagrees with a finding can check the underlying evidence.
- Findings sort by severity then rung ascending, same as the screen, with
  causally-explained findings suppressed but **listed by id** under a
  `SUPPRESSED (explained by <id>)` line so nothing vanishes without a trace.
- Default filename `rti_doctor_<domain>_<topic-or-all>_<timestamp>.txt` in the
  current directory; `-o` overrides.
- `--probe-timeout` (default 10.0), `--type-wait` (default 5.0, how long to wait
  for TypeLookup before declaring no type info).
- `--debug-log`.

---

## Check Catalog

### Rung 0–1 — Blind spots (`checks/blind_spots.py`)

Run once at startup, rendered on the participant screen. The only checks that can
explain an empty table.

| id | Detects | Signal |
|---|---|---|
| `blind.domain_tag` | Nonempty domain tag makes us invisible to every other vendor | our QoS `property` `dds.domain_participant.domain_tag` |
| `blind.spdp2` | SPDP2 configured — no interop with standard SPDP | `discovery_config.builtin_discovery_plugins` |
| `blind.security_enabled` | We're secure; unsecure peers undiscoverable, and vice versa | security plugin properties; remote `dds_builtin_endpoints` secure bits |
| `blind.no_multicast_no_peers` | Multicast unusable and `initial_peers` won't reach anyone | `discovery.initial_peers`, multicast-capable NIC check |
| `blind.unknown_peers_rejected` | `accept_unknown_peers = false` silently drops valid peers | `discovery.accept_unknown_peers` |
| `blind.nonstandard_ports` | Nonstandard port mapping or discovery multicast address | `wire_protocol.rtps_well_known_ports`, builtin UDPv4 multicast address |
| `blind.other_domain_active` | Participants alive on a *different* domain than selected | `scan_active_domains()` results |
| `blind.empty_domain` | Zero participants — rolls the above into one actionable message | participant count == 0 |

### Rung 2 — Static discovery (`checks/static_discovery.py`)

| id | Detects | Signal |
|---|---|---|
| `vendor.identify` | Which implementation is on the other side | `rtps_vendor_id`, `rtps_protocol_version.major/minor`, `product_version`, `participant_name` |
| `vendor.known_issues` | Vendor-specific interop caveats | vendor id → curated `vendors.py` notes |
| `locator.unroutable` | Advertised address we can't reach | endpoint `unicast_locators` else participant `default_unicast_locators`; flag loopback-from-remote-host, Docker/NAT ranges, link-local, IPv6-only, address outside every local subnet |
| `transport.class_mismatch` | Shared-memory-only path across hosts; TCP/UDPv6-only peer | `ParticipantBuiltinTopicData.transport_info` (class id, max message size) |
| `security.mismatch` | Secure remote participant vs our unsecure one | `dds_builtin_endpoints`, `available_builtin_endpoints_ext` secure bits |
| `discovery.partial` | Discovery data incomplete — don't over-trust other fields | `partial_configuration` |
| `endpoint.none` | Participant visible but no endpoints under it (rung 2 failure) | endpoint count for that participant key |

Vendor ID table (`vendors.py`):

| Implementation | vendor id |
|---|---|
| RTI Connext | `01.01` |
| ADLINK / Vortex OpenSplice | `01.02` |
| OpenDDS | `01.03` |
| eProsima Fast DDS | `01.0F` |
| Eclipse Cyclone DDS | `01.10` |

Unrecognized IDs render as raw hex plus "unrecognized vendor" — never guessed.
Vendor ID is an implementation *hint*, not a capability declaration.
`product_version` is an RTI extension and is meaningless for other vendors.

### Rung 3 — Type resolution and compatibility (`checks/type_compat.py`)

| id | Detects | Signal |
|---|---|---|
| `type.no_type_info` | `endpoint.type` empty | must distinguish *still resolving* from *not resolvable*, and name which |
| `type.name_conflict` | Same `topic_name`, different `type_name` across participants | registry census |
| `type.assignability` | Structurally incompatible types on one topic | `DynamicType.is_assignable_from()` in **both** directions, reporting which direction fails and on which member |
| `type.extensibility` | FINAL vs APPENDABLE vs MUTABLE mismatch | resolved `DynamicType` extensibility kinds |
| `repr.no_common` | XCDR1 vs XCDR2 with no overlap | writer `PublicationBuiltinTopicData.representation` vs what our reader offers |
| `reader.type_consistency` | A third-party reader on this topic enforces `EXACT_TYPE` | `SubscriptionBuiltinTopicData.type_consistency` |

Three correctness constraints from the Connext AI research, all easy to get wrong:

1. **`type_state` is a state machine, not a snapshot.** With TypeObject v2, SEDP
   carries only a TypeIdentifier hash; Connext resolves the full TypeObject
   asynchronously over TypeLookup Service and then **re-delivers the discovery
   sample** for that endpoint. The first sample having no `type` is normal. Model
   it `PENDING → RESOLVED | UNAVAILABLE` with a `--type-wait` window, and keep
   `merge_endpoint()` semantics so a later type-bearing sample wins. A
   TypeIdentifier alone is an identifier, not a schema — sufficient only when we
   already have that type cached.
2. **Directionality.** `type_consistency` is a **reader** requirement and appears
   only in `SubscriptionBuiltinTopicData`. `representation` is the **writer**
   offer, in `PublicationBuiltinTopicData`. There is no writer-side
   `type_consistency` to read.
3. **Never set `type_object_max_serialized_length = 0`** on our participant — that
   disables propagation of both TypeObject v1 and v2. `AUTO` plus default builtin
   channels is correct, which is what `configure_type_lookup_qos()` produces.

When `type.no_type_info` fires, the report names which case it is:

- lookup still in flight → retry, don't conclude
- peer advertises TypeInformation but serves no TypeLookup replies
- peer serves MINIMAL TypeObject only → member names unavailable or hashed
- peer propagates no type representation at all
- our `request_types_filter` doesn't match the topic (shouldn't happen with `*`,
  but verify rather than assume)

### Rung 4 — Matching (`checks/probe_match.py`)

The probe creates a DynamicData reader (instrumented version of
`create_topic_subscription()`) with a listener on `REQUESTED_INCOMPATIBLE_QOS |
SAMPLE_LOST | SAMPLE_REJECTED | SUBSCRIPTION_MATCHED`, plus polling of
`topic.inconsistent_topic_status`.

| id | Detects | Signal |
|---|---|---|
| `qos.rxo_predict` | Predict incompatibility *before* creating a reader | writer QoS vs planned reader QoS across reliability, durability, deadline, liveliness, ownership, destination_order, presentation, partition, representation |
| `match.none` | Never matched within `--probe-timeout` | `subscription_matched_status.current_count` |
| `match.incompatible_qos` | Exactly which policy blocked it | `requested_incompatible_qos_status.last_policy` + `.policies`, mapped to a plain-English RxO rule |
| `match.topic_inconsistent` | Local topic definition conflict | `InconsistentTopicStatus.total_count` (Topic-level, not reader-level) |

### Deferred Payload-Health Diagnosis

Payload decode, field walking, decode/drop counters, and payload verdicts are
not part of the current discovery-and-matching scope. They remain future
roadmap work in `IMPROVEMENT_BACKLOG.md` item S8.

**The full-deserialization verdict.** "Can the message be fully deserialized" is
not "did `take()` throw." Walk the resolved `DynamicType`, read every member of a
received sample, catch per-member exceptions, record the failing **field path**:

- nested structs (recurse) and inheritance
- sequences and arrays — length, element read, bounded-sequence overflow
- unions — discriminator, then only the active member
- optional members — present vs absent, where absent is not an error
- enums — value outside the declared set, suggesting a bit-bound difference
- strings/wstrings — bounds and encoding
- `@external` members
- keyed types — which members are keys

Verdict is `FULL` / `PARTIAL(field paths)` / `FAILED`. For anything but `FULL`,
include the IDL fragment for the offending member — via
`DynamicType.to_string(dds.DynamicTypePrintFormatProperty(indent=4))`, or
`print_idl()` for the whole type — next to the likely encoding cause: XCDR1 vs
XCDR2, extensibility mismatch, differing bounds, alignment, enum bit bound, or key
hashing.

### Report ordering

`report.py` sorts by severity, then **rung ascending**, and suppresses
higher-rung findings that a lower rung causally explains — a locator problem
explains a match failure, and listing them as peers is noise.

---

## Phase 1 — Packaging, CLI, Domain Selection

Deliverables:

- `requirements.txt` (textual; `rti.connext` resolved by
  `python_env_sync_rti_connext`).
- `run_rti_doctor.sh` mirroring `run_rtispy.sh` structure exactly.
- `__main__.py` with the CLI above; interactive vs headless dispatch.
- `domain_scan.py` — port `scan_active_domains()` with its docstring intact.

Tests: `bash -n run_rti_doctor.sh`; unit tests for `parse_args` (interactive,
`--topic`, `--all`, bad format, `--topic` with `--all`); `--help` works.

Gate: `./tools/rti_doctor/run_rti_doctor.sh --help` reaches Python help; the
domain prompt behaves like `rti_spy`'s.

## Phase 2 — Findings Model And Report Rendering

Deliverables: `findings.py` (Finding, Severity, rung ordering, causal
suppression, verdict rollup); `report.py` with three renderers — the shareable
plain-text file per the spec above, the Textual screen, and the unstable JSON
dump; `checks/__init__.py` registry + runner.

The shareable text file is built in this phase, not bolted on at the end, so
every later phase's findings are shareable the day they land.

Tests: unit tests for ranking, suppression, and verdict rollup with synthetic
findings. Snapshot test on the full text report including the environment header,
suppression lines, and both appendices. A test asserting an unavailable counter
renders `n/a (...)` rather than being dropped.

Gate: a hand-built finding list produces a complete, readable report file with
correct ordering, correct suppression traces, and no invented values.

## Phase 3 — Discovery Model And Vendor Identification

Deliverables:

- `records.py`: `ParticipantRecord` (key, vendor, protocol version, product
  version, domain, name, default locators, `transport_info`, builtin-endpoint
  bitmaps, `partial_configuration`) and `EndpointRecord` (key, participant key,
  kind, topic, type_name, `type`, `type_state`, all RxO QoS, `representation`,
  endpoint locators, `type_consistency` for readers).
- `discovery.py`: listeners + `DiscoveryRegistry` with merge-on-update and the
  `type_state` machine.
- `vendors.py` table and note data.

Tests: unit tests over fake builtin data for record building, merge behavior, and
every `type_state` transition including late resolution.

Gate: the app lists what `rti_spy` lists on the same domain, with a correct
vendor name and RTPS version for a Cyclone or Fast DDS participant.

## Phase 4 — Blind-Spot Audit

Deliverables: `checks/blind_spots.py`; blind-spot pane on the participant screen;
`scan_active_domains()` wired into `blind.other_domain_active`.

Tests: unit tests per check id against synthetic QoS objects. Live test that
selects an empty domain while a publisher runs on another and asserts
`blind.other_domain_active` fires.

Gate: a domain-tagged or empty domain produces an actionable message instead of a
blank table.

## Phase 5 — Static And Type Checks

Deliverables: `checks/static_discovery.py`, `checks/type_compat.py`,
`views/report.py`, the `d` binding. Optional `--local-types <file.xml>` to compare
a discovered type against a reference loaded with `dds.QosProvider`.

Tests: table-driven unit tests per check id, firing and non-firing. For
assignability, build `dds.StructType`s differing by member type, bound,
optionality, extensibility, and enum bit bound; assert the reported breaking
member.

Gate: `d` on a topic with no resolvable type reports `type.no_type_info` with the
correct sub-reason; two writers on one topic with different types report the
specific breaking member.

## Phase 6 — Probe Engine

Deliverables: `probe.py` (reader/subscriber lifecycle with guaranteed close,
diagnostic listener, periodic status snapshots, per-writer protocol status) and
`checks/probe_match.py`.

Every status and field access feature-detected so 7.3.x doesn't crash on a
7.7-only counter; a missing counter yields `INFO` "not available on this Connext
version" rather than a false negative.

Tests: unit tests for matching status-to-finding mapping with fake status
objects; a leak test asserting readers and subscribers close when the report
screen is dismissed.

Gate: a healthy RTI topic reports no active discovery or matching incompatibility
and leaves no open reader behind.

## Phase 7 — Sweep Screen And Headless Modes

Deliverables: `views/sweep.py`, the `D` binding, `s` to save; `--topic` and
`--all` headless paths sharing the same check runner and renderers as the TUI.
Sweep probes run bounded and concurrently with a cap, streaming rows as verdicts
land.

Tests: integration test over several fixture publishers asserting the sweep
reaches a verdict for each and closes all readers. JSON output is smoke-tested for
"parses and contains the expected finding ids" only — no structural assertions, so
the shape stays free to change.

Gate: `--all --format json` on a domain with a healthy, a QoS-mismatched, and a
no-type topic produces three correct verdicts.

## Phase 8 — Negative Fixtures (RTI-only)

Deliverables: separate-process publishers modeled on
[rti_spy's e2e_dynamic_publisher.py](../rti_spy/test/e2e_dynamic_publisher.py):

- `fixture_healthy.py` — baseline, expect `FULL`
- `fixture_qos_mismatch.py` — BEST_EFFORT writer against a stricter reader
  → expect `match.incompatible_qos` naming RELIABILITY
- `fixture_no_type_info.py` — `type_object_max_serialized_length = 0`
  → expect `type.no_type_info` with the "propagation disabled" sub-reason
- `fixture_type_conflict.py` — same topic, different type
  → expect `type.name_conflict` / `type.assignability`
- `fixture_large_data.py` — samples above transport MTU
  → expect fragmentation counters populated, verdict still `FULL`
- `fixture_partition.py` — non-matching partition → expect no match, partition cited

Tests: gated integration tests asserting exact finding ids per fixture.

Gate: every fixture produces its expected id and no unexpected ERROR.

## Phase 9 — Cross-Vendor Validation And Docs

Deliverables:

- `test/vendors/cyclone_publisher.py` — pip `cyclonedds`, publishing a keyed
  struct with nested, sequence, optional, union, and enum members so the field
  walk is genuinely exercised.
- `test/vendors/fastdds/` — Docker-based Fast DDS publisher of the same shape,
  with a run script.
- Both suites skip cleanly (never fail) when the vendor isn't installed.
- Verify every `vendors.py` note against real traffic and **delete any note that
  doesn't reproduce**. Notes ship only once observed, with a source link.
- `README.md`: quick start, CLI, what each finding id means, how to read the
  verdict, the visibility ladder as a troubleshooting order, explicit limitations.
- Add `rti_doctor` to [tools/README.md](../../README.md) alongside `rti_spy` and
  `rti_view`.

Gate: a real Cyclone writer and a real Fast DDS writer are each discovered,
probed, and given an accurate verdict, and every finding they trigger is real.

---

## Out Of Scope

- Any modification to `rti_spy` or `rti_view`, including a hook from `rti_spy`
  into this tool.
- A stable, versioned, or documented JSON report schema.
- Writing user data, or acting as a test publisher for third-party readers.
- Diagnosing DDS Security configuration beyond flagging secure/unsecure mismatch.
- RTPS wire decoding or packet capture — Wireshark's job, and the vendor-PID class
  of problem is explicitly deferred to it.
- Automatically fixing QoS or generating QoS XML.
- RTI Monitoring Library / Admin Console-equivalent metrics history.
- OpenDDS and OpenSplice in the test matrix (recognized and annotated only).

## Post-V1 Interoperability Test Roadmap

Use the [OMG DDS-RTPS interoperability suite](https://github.com/omg-dds/dds-rtps)
as a reference for expanding the live test matrix. The existing RxO matrix already
covers matching compatibility; these additions verify data-flow behavior after a
match. Run each applicable scenario for Connext-to-Connext, Connext-to-Cyclone,
Cyclone-to-Connext, and Connext-to-Fast DDS when the corresponding fixture is
available.

| # | Scenario | Expected assertion |
|---|----------|--------------------|
| I1 | Content-filtered topics | A reader receives only key and non-key samples selected by its filter. |
| I2 | History and time-based filtering | KEEP_LAST/KEEP_ALL and TIME_BASED_FILTER preserve the expected per-instance sample sequence and rate. |
| I3 | Exclusive ownership strength | A reader selects the strongest writer for one instance and receives from both writers for distinct instances. |
| I4 | Late-joiner durability | VOLATILE and TRANSIENT_LOCAL readers receive the expected historical samples after joining. |
| I5 | Lifespan expiry | Expired samples are absent while unexpired samples remain readable for reliable and best-effort flows. |
| I6 | Instance final state | Unregister, dispose, and writer shutdown produce the expected instance-state transitions. |
| I7 | Ordered access and coherent sets | Multi-topic, multi-instance readers preserve the ordering and coherent-set boundaries required by their presentation QoS. |
| I8 | Large payload integrity | Fragmented samples arrive and retain a verified payload sentinel, complementing Doctor's current fragmentation counters. |

## Implementation Status (built and verified)

All phases are implemented. Deviations from the plan above, each driven by
something measured rather than assumed:

- **Scope grew to include RxO QoS comparison** (`checks/qos_match.py`). The tool
  is an observer inserted into a running system, so both the writer's offered QoS
  and the reader's requested QoS come from discovery - nothing is user-supplied.
  It cannot and does not judge a hypothetical reader's QoS.
- **`reader.type_consistency` was dropped.** `SubscriptionBuiltinTopicData` has no
  such field on 6.1/7.3/7.7, contrary to some documentation. Verified by
  introspecting the real API.
- **`--local-types` was not built.** Comparing a discovered type against the
  user's own IDL would require user-supplied types; type comparison is
  discovered-vs-discovered only.
- **XTypes compliance mask added.** Connext's default mask (`0x18C`) is not fully
  OMG-compliant; the tool now applies the VENDOR mask before creating entities and
  records it in Appendix C. Measured caveat: it did not by itself fix the observed
  Cyclone no-data case.
- **The probe offers XCDR1+XCDR2 rather than mirroring representation**, because
  Cyclone advertises an empty representation while using XCDR2.
- **Test fixtures**: `qos_mismatch` became `best_effort` (the probe mirrors QoS, so
  it verifies mirroring) and `bad_pair` was added - a live BEST_EFFORT writer plus
  a RELIABLE/EXCLUSIVE reader, which is what actually exercises RxO detection.

Bugs found by testing and fixed (each now has a regression test):

| Bug | Why it mattered |
|---|---|
| `is_aggregation_type`/`is_collection_type` are **methods**, not properties | `bool(bound_method)` is always True, so every member of every type was misclassified as a collection |
| `loan_value` holds a bind on the parent | Reading one aggregate member made every *sibling* read fail - phantom failures after the first nested member |
| `EventCount64`/`SequenceNumber` are not ints | Real counters rendered as "not available on this version" - the exact dishonesty the report rules forbid |
| Strings are DDS collection types | Strings were walked as containers of characters |
| `dropped_fragment_count > 0` treated as a fault | Healthy large data showed fragments=6/reassembled=6/dropped=6; dropped fragments are ordinary repair duplicates |
| "outside every local /24" heuristic | Warned on any peer in another subnet - normal in a routed network, and the real prefix is unknown |
| SHMEM locators judged as IP addresses | Every healthy local peer got a false "unspecified address" warning |
| App-level `b` binding popped the base screen | Back at the top level revealed an empty placeholder |
| DataTable never focused | Enter/`d` never reached it, so every action silently no-oped |
| `_writer_is_reliable` referenced but undefined | Would have raised on the no-data path |

Verified: 7.7.0 and 7.3.1 end to end (58 unit + 17 live tests pass on both).
6.1.2 was not installed here, so it is feature-detected but unverified; a `6.1`
bucket was added to `scripts/python_env.sh`, which previously mapped 6.1.x to
Python 3.10 and a 7.7 wheel.

Cross-vendor: validated against Cyclone DDS 11.0.1. Type resolution across
vendors works; the tool correctly diagnosed an asymmetric match (RTI matched
Cyclone's writer, Cyclone never sent data), independently confirmed with a
`tshark` capture. Fast DDS was not exercised.

## Settled For V1

No open questions. This is a v1 shipment; the following are decided, and each can
be revisited later on real usage rather than speculation.

- **Standalone and self-contained.** No imports from `rti_spy`, no changes to it,
  and no `d`-key hook from `rti_spy` into this tool. Patterns are copied with
  attribution, not shared.
- **Textual TUI matching `rti_spy`.** No Dear PyGui front end.
- **The shareable artifact is a plain-text report file**, structured per the spec
  above and built in Phase 2. Fixed section order so reports diff against each
  other; environment header so a recipient needs no follow-up questions; raw
  counter appendix so findings are checkable.
- **No JSON schema contract.** `--format json` ships as an unstable dump of the
  finding fields, free to change between releases. No versioning, no documented
  schema, no structural tests. The text file is what gets shared; JSON is a
  convenience for whoever eventually wants to parse it, and gets a schema then.
  *(Settled by decision H1: the convenience was never taken up outside the test
  harness, so `--format json` is removed rather than given a schema. The text
  report is the single output contract, and the harness parses it.)*
- **Validation scope is Cyclone + Fast DDS.** OpenDDS and OpenSplice are
  recognized by vendor ID with advisory notes only.
