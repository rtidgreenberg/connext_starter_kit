# RTI Doctor System Scanner Plan

## Goal

Add a domain-level **System Overview** to `rti_doctor` that lets an operator
quickly answer both "What needs attention in this DDS domain right now?" and
"What DDS entities are currently present and healthy?"

The scanner will:

- observe a selected DDS domain and retain its current topology snapshot;
- make **DDS Topology & Health** and **Issues** equal first-level navigation
   choices;
- aggregate immediately observable diagnosis findings into **Errors**,
   **Warnings**, and **Notes**;
- show the current number of items in each severity bucket;
- let the operator select a numbered item to open its topic, involved readers
  and writers, observed evidence, likely cause, and recommended resolution;
- provide a metrics dialog for observed participants, readers, writers, and
  topics; and
- add packet-capture evidence only when native discovery is incomplete or an
  operator asks for it.

The scanner remains read-only. It must not create a probe reader until the
operator selects one specific discovered writer and explicitly starts a deep
diagnosis.

## Design Options

### Option A: Extend the Existing Sweep Screen

Replace `SweepScreen` with a severity-filtered issue list and add a metrics key.

**Advantages**

- Reuses the current worker-thread sweep and report-opening behavior.
- Smallest number of new Textual screens.

**Costs**

- A sweep is writer-centric and potentially runs a live probe for every writer.
- It does not naturally include domain blind spots, reader-only facts, or
  upgrade recommendations.
- It conflates "currently observed" state with results from a completed probe
  pass that may already be stale.

### Option B: Add a System Scanner Dashboard (Recommended)

Replace the existing domain-wide sweep workflow with an explicit per-writer
deep-diagnosis action. Add a domain scanner dashboard reachable from the
participant screen with a new `i` binding (Issues) and a `m` binding (Metrics).

The overview initially runs only discovery-backed static checks. It presents
severity counts, topology metrics, and two navigable views: a numbered,
deduplicated issue queue and a DDS entity topology with health rollups.
Selecting an item in either view opens detail; from there, the operator can
open the existing full report or explicitly run deep diagnosis for the selected
writer.

**Advantages**

- Immediate issues appear without waiting for a full writer-by-writer probe.
- Includes domain-level blind spots, endpoint incompatibilities, vendor
  advisories, and environment recommendations in one place.
- Preserves the current distinction between a passive scanner and an active
  probe.
- Fits the current `ParticipantListScreen` -> `EndpointListScreen` ->
  `ReportScreen` interaction model without replacing it.

**Costs**

- Requires a small normalized issue model and two new Textual screens.
- Static results must refresh predictably as discovery records arrive or expire.

### Option C: Separate Full-Screen Scanner Application

Introduce a separate CLI mode and Textual app dedicated to continuous scanning.

**Advantages**

- Maximum freedom for a monitoring-style workflow and long-lived history.

**Costs**

- Duplicates session, discovery, and navigation logic.
- Makes it harder to move from an issue to the existing endpoint report.
- Larger maintenance surface before the immediate triage workflow is proven.

**Decision:** implement Option B. Revisit a separate application only if the
scanner later needs persistence, multi-domain comparison, or alert delivery.

## Architecture Decisions Before Implementation

The following decisions resolve the parts of this view plan that are not fully
expressed by the present `Finding` and session APIs. They are requirements for
the first implementation slice, not deferred polish.

### 1. Give Findings Machine-Readable Entity Identity

The existing finding text and evidence are primarily human-readable. The
scanner must not parse titles or labels to determine relationships. Pairwise
findings, especially `qos.rxo_mismatch`, must include these fields in
`Finding.evidence`:

```python
{
      "writer_key": "<endpoint GUID key>",
      "reader_key": "<endpoint GUID key>",
      "writer_participant_key": "<participant GUID key>",
      "reader_participant_key": "<participant GUID key>",
      "topic_name": "Telemetry",
      "mismatches": [...],
}
```

Single-endpoint findings must similarly carry `endpoint_key` and
`participant_key`; domain findings carry `scope="domain"`. The presentation
layer resolves names, vendor labels, and locators from the current registry.
This makes `SystemIssue.key` deterministic and avoids parsing display text.

### 2. Define Scanner Check Scopes

`Session.system_scan()` must not call the full static-check catalog for every
object. Some checks are domain-wide, so doing so would repeat one real problem
many times. The scan must run in these scopes:

| Scope | Frequency | Examples |
|---|---|---|
| Domain | Once per scan snapshot | blind-spot audit, runtime recommendation |
| Participant | Once per participant | missing endpoints, participant discovery metadata |
| Endpoint | Once per endpoint | type state, locator and transport facts |
| Pair | Once per canonical writer-reader pair on one topic | RxO mismatch and compatible-pair observations |

Pair evaluation uses the writer key then reader key as canonical identity.
Issue aggregation remains a safety net, but correct check scope is the primary
way to prevent duplicate issues.

### 3. Make a Scan Snapshot Atomic

Create one immutable `SystemScanSnapshot` on entry to the Issues screen and on
manual `r` refresh:

```python
SystemScanSnapshot(
      captured_at=...,
      topology={...},
      issues=[...],
      wire_evidence=[...],
)
```

The System Overview and Metrics dialog may show newer live topology, but a
saved system report must serialize exactly one `SystemScanSnapshot`. It must
never combine an old issue list with a fresh topology count. The UI labels live
metrics and last issue-snapshot time separately.

### 4. Define Issue Scope and Health Inheritance

Every `SystemIssue` must declare one of `domain`, `participant`, `endpoint`,
or `pair` scope. DDS Topology & Health renders them as follows:

- An endpoint shows direct endpoint and pair issues involving that endpoint.
- A participant shows its direct issues and a count of issues involving one of
   its endpoints.
- A topic shows issues involving any reader or writer on that topic.
- A domain issue appears in the overview and as a distinct inherited indicator;
   it does not turn every participant row into an unrelated `ERROR`.

The health table must distinguish direct and inherited conditions in its detail
view. `OK` always means "no issue in this displayed scope", never that end-to-
end communication is proven.

### 5. Define Deep-Debug Target Selection and Result Lifetime

`d` is enabled only when the UI has exactly one selected writer. For an issue
that references multiple writers, `d` opens a writer selector. For domain-only
or reader-only issues it is disabled with the reason shown in the footer.

Store a `DeepDiagnosisResult` by writer endpoint key with `started_at`,
`completed_at`, and the existing report/verdict. It is a post-snapshot result:
the report must show its completion time and must not alter the saved snapshot's
issue counts or severity. This preserves the distinction between passive
observation and the later targeted diagnostic action.

### 6. Keep Live Capture Manual in the First Release

The first release does not infer that native discovery is incomplete and does
not automatically start `tshark`. Expose `w` only when startup configuration
provides a capture interface and `tshark` is available. It is a manual,
bounded evidence action for the selected writer or issue. Automatic escalation
requires a separately tested incomplete-discovery predicate and is out of scope
until then.

## Operator Workflow

```text
Start rti_doctor on a domain
        |
        v
System Overview (live discovery refresh)
        |
   +-- 1 / i --> Issues
   |              |
   |              +-- Errors / Warnings / Notes --> issue detail
   |
   +-- 2 / t --> DDS Topology & Health
   |              |
   |              +-- participant --> endpoint --> report or issue detail
   |
      +-- m --> Metrics dialog
         |
      +-- writer --> Deep diagnose
```

The dashboard must show only static, currently observed findings when first
opened. `d` on a selected writer is the only scanner path that may create a
diagnostic DataReader and wait for samples.

## Issue Aggregation Model

Add a scanner-only presentation model, for example in
`rti_doctor/system_scan.py`. It consumes existing `Finding`, `EndpointRecord`,
`ParticipantRecord`, native topology snapshots, and optional wire evidence; it
does not reimplement DDS checks.

```python
SystemIssue(
    key="qos.rxo_mismatch:<writer-guid>:<reader-guid>:RELIABILITY",
    severity=Severity.ERROR,
    title="Reliability requested/offered mismatch",
    finding_ids=["qos.rxo_mismatch"],
    topic_name="Telemetry",
    domain_id=7,
    writers=[EndpointRef(...)],
    readers=[EndpointRef(...)],
    participants=[ParticipantRef(...)],
    observed="Writer offers BEST_EFFORT; reader requests RELIABLE.",
    root_cause="The reader's requested QoS exceeds the writer's offer.",
    recommendation="Make the writer RELIABLE or change the reader to BEST_EFFORT.",
    evidence={...},
    source="native discovery",
    probe_state="not run",
)
```

### Aggregation Rules

1. Run `Session.diagnose_domain()` once for domain-level findings.
2. Run the existing static checks for every currently discovered endpoint and
   participant. Do not run probe checks in this pass.
3. Convert each actionable finding to a `SystemIssue` using endpoint GUIDs,
   participant GUIDs, topic, finding ID, and policy names as the stable key.
4. Merge duplicate reports of the same root condition, retaining every affected
   endpoint reference. For example, one incompatible writer/reader pair is one
   issue even if it appears in both endpoint passes.
5. Keep suppressed findings out of the primary queue, but show them in issue
   detail under "Also observed" with their suppression reason.
6. Sort Errors, then Warnings, then Notes; within a bucket sort by topic,
   finding ID, and stable GUID key. Assign the on-screen numbers after sorting.
7. When the refresh changes the list, preserve selection by `SystemIssue.key`,
   not by its changing display number.
8. Build an issue snapshot when the Issues screen opens. Keep that snapshot
   stable while the operator investigates it; refresh it only when the operator
   presses `r` (Refresh). Do not re-run static checks on every discovery timer
   tick. The screen must display its last-refresh time and state that topology
   may have changed since the snapshot was built.

### Shareable System Report

Add an `s` (Save system report) action to the System Overview, Issues, and
DDS Topology & Health screens. It writes one plain-text, ASCII document that
contains the exact issue snapshot currently being viewed and a fresh or
snapshot-associated observed topology section. The save operation must not
implicitly refresh findings, start a deep diagnosis, or start packet capture.

The filename should be deterministic and ticket-friendly:

```text
rti_doctor_system_<domain>_<timestamp>.txt
```

The exported report must include:

1. Environment and collection metadata: timestamp, host, OS, Python, Connext
   version, `NDDSHOME`, selected domain, Doctor command, and scanner refresh
   time.
2. A topology metrics summary: remote participant, reader, writer, and unique
   topic counts; topic names; collection source; and the discovery coverage
   limitation.
3. An issue summary with Error, Warning, and Note counts.
4. Every active issue in severity and stable display order, including its
   number, finding ID, topic, affected participants/readers/writers, observed
   evidence, likely cause, recommendation, and native or wire provenance.
5. Suppressed findings under their parent issue, retaining the explaining
   finding ID.
6. Any separately collected `tshark` observation in a clearly marked wire
   evidence appendix. It must never be merged into native topology counts.
7. A final statement that the report is an observed snapshot, not proof of
   complete historical topology or end-to-end data flow; identify writers that
   received a targeted deep diagnosis after the snapshot and include its
   result time and verdict when one exists.

Use the existing report renderer conventions: fixed width, deterministic
section ordering, ASCII-only content, and only observed values. Implement a
separate `SystemReportData` / `render_system_text()` path rather than forcing
system-level data into an endpoint `ReportData` object.

### Severity Mapping

| Scanner bucket | Input findings | Example |
|---|---|---|
| Errors | `Severity.ERROR` and above | `qos.rxo_mismatch`, no common data representation, unreachable locator that blocks an observed endpoint |
| Warnings | `Severity.WARN` | type information unavailable, no endpoints from a visible participant, discovery coverage is incomplete |
| Notes | `Severity.INFO` and scanner recommendations | vendor identity, fragmentation evidence, a Connext-version recommendation |

`OK` findings are never put in the issue queue. The dashboard can show an
observed healthy-endpoint count separately, but it must not call it a complete
health guarantee when discovery coverage is incomplete.

## TUI Design

### System Overview: First Menu

Replace the current participant list as the initial Textual screen with a
`SystemOverviewScreen`. It is the top-level, live-refreshing menu for the
selected domain, and it deliberately offers both operational viewpoints before
showing a table of entities.

```text
Domain 7 - DDS System Overview

Observed: 4 participants | 9 readers | 7 writers | 6 topics
Issues:   2 Errors | 3 Warnings | 1 Note

   [1] Issues
         Triage actionable errors, warnings, and notes.
   [2] DDS Topology & Health
         Browse participants, readers, writers, topics, and their observed health.

   m Metrics   q Quit
```

The overview must remain compact and intentionally not resemble a marketing
landing page or a nested-card layout. Its job is routing. Numeric choices are
the primary initial interaction, with mnemonic bindings for experienced users.

| Key | Action |
|---|---|
| `1` / `i` | Open the System Scanner issue dashboard |
| `2` / `t` | Open DDS Topology & Health |
| `m` | Open live metrics |
| `q` | Quit |

### DDS Topology & Health

`TopologyHealthScreen` replaces the participant list as the entity-first
browser. The initial table is participant-centric because discovery natively
groups endpoints by participant, but it must offer explicit switches for the
other DDS entity kinds.

```text
DDS Topology & Health - Domain 7                     4 participants | 16 endpoints

View: [Participants]  Readers  Writers  Topics

Name              Vendor       Readers  Writers  Topics  Health
logger            RTI Connext        1        2       2  WARN (1)
dashboard         Cyclone DDS        3        0       3  ERROR (1)
control           Fast DDS           5        5       4  OK

Enter details   i linked issues   m metrics   b back
```

Health is a rollup of currently observed static findings that relate to the
entity. It is not a new diagnosis algorithm. The row must show an `ERROR (N)`,
`WARN (N)`, `NOTE (N)`, or `OK` label, never color alone. Selecting a
participant opens its endpoint table; selecting a topic shows all known readers
and writers for that topic, grouped by participant; selecting a reader or
writer opens the existing static report path. `i` opens only issues linked to
the selected entity, making it possible to move directly from topology to
triage.

Only a selected **writer** exposes the `d` (Debug writer) action. It runs the
existing probe sequence only for that writer: create Doctor's temporary reader,
observe match state, receive samples for the bounded interval, inspect payload
readability, collect status counters, and update the writer's report. Selecting
a **reader** must not offer `d`: Doctor cannot validate an arbitrary remote
reader's actual data reception without publishing test data, which would violate
the scanner's read-only contract. Reader detail instead shows its requested QoS,
matched or incompatible writers known from discovery, and linked issues.

The prior `ParticipantListScreen` behavior and endpoint drill-down are retained
inside this view. No entity is removed from the current navigation model.

### Issue Dashboard

The System Scanner dashboard is the issue-first sibling of DDS Topology &
Health. It uses the same live registry and issue snapshot but has a different
sorting and selection model: actionability first rather than entity hierarchy.

### Topology Navigation Changes

Add these bindings at the overview and topology levels:

| Key | Action |
|---|---|
| `i` | Open the System Scanner dashboard or linked entity issues |
| `t` | Open DDS Topology & Health from the overview |
| `m` | Open the live metrics dialog |

The overview summary and all topology rollups refresh at the same cadence as
discovery, with aggregation work coalesced so the UI does not launch overlapping
scanner workers.

Use a Textual `DataTable`, not a free-form numbered prompt. Rows expose their
number in the first column, while `Enter` is the primary selection action.
Numeric shortcuts are additive: pressing `1` through `9` selects an item only
when the relevant list is focused; numbers above nine remain reachable through
the table and typed jump-to-number dialog.

```text
Domain 7 - System Scanner                     2 Errors | 3 Warnings | 1 Note

 [1] Errors (2)     [2] Warnings (3)     [3] Notes (1)       m Metrics

 No.  Topic       Finding                 Affected endpoints                 State
  1   Telemetry   qos.rxo_mismatch        writer: logger; reader: dashboard   observed
  2   Command     repr.no_common          writer: control; reader: gateway    observed

 Enter details   d debug selected writer   w capture evidence   o full report   r refresh   b back
```

`r` is reserved for **Refresh issues** in the issue list and issue detail
screens. The existing full-report action should use a non-conflicting binding,
for example `o` (Open report). A refresh rebuilds the static issue snapshot,
retains the selected issue when its `SystemIssue.key` still exists, and clearly
reports when the selected issue has disappeared or changed severity.

Use real Textual tabs or a segmented selection control only if they remain
keyboard accessible. The severity count must always remain visible. Do not
render bare color as the sole severity signal; use the words `ERROR`, `WARN`,
and `NOTE` as well.

### Issue Detail

Each issue detail view renders:

- topic and domain;
- all incompatible writers and readers, including participant, vendor, GUID,
  advertised QoS/representation, and locator where known;
- observed evidence, root cause, and recommendation from the existing finding;
- native versus wire-evidence source and collection time;
- deep-diagnosis state (`not run`, `running`, `complete`, or `unavailable`);
- suppressed secondary findings; and
- actions to open the existing full report, run a focused probe, or collect a
  bounded capture when capture is available.

For RxO issues, the UI must name both sides explicitly. It must never only say
"incompatible topic" when the registry contains the involved writer and reader.

### Metrics Dialog

Implement a modal `MetricsScreen` that obtains a fresh
`topology.snapshot(...)` whenever opened and on its configured refresh timer.

```text
Observed Domain Metrics

Domain ID                 7
Remote participants       4
Remote DataReaders         9
Remote DataWriters         7
Unique topics              6
Topic names                Command, Telemetry, Status, ...
Source                     native builtin discovery
Coverage                   Observed since scanner start; late observers may miss historical SEDP.
```

The metric values are remote observed entities only, matching the current
topology contract; Doctor's own participant and probe readers are excluded.

## Connext Version Recommendation

Add a scanner recommendation provider that derives a note from the environment
reported by `compat.environment_info()`. It must parse versions semantically,
not compare strings.

Initial policy:

| Detected runtime | Note |
|---|---|
| 7.3.x | Recommend upgrading to Connext 7.7.x for the verified full Doctor feature set; explain that 7.3 lacks `DiscoveryConfig.request_types_filter`, so remote type lookup diagnostics can be less conclusive. |
| 7.7.x | Note that the runtime is in Doctor's verified support range. Do not create an issue by default. |
| Unknown, older, or newer runtime | State the detected version and the documented support/verification status without claiming compatibility. |

This is a **Note**, not a Warning or Error. It must include the observed
version and link to the local supported-version documentation or a stable RTI
reference when one is available. No external network lookup belongs in a normal
scan.

## Native Discovery and TShark Evidence

Native builtin-topic discovery is authoritative for the primary metrics and
issue relationships. `tshark` is an optional, bounded evidence source:

1. Start with native discovery and static checks.
2. For the first release, offer `w` only when `tshark` is installed and a
   capture interface was configured at startup.
3. Use the existing domain-scoped BPF construction and bounded capture window.
4. Parse only RTPS discovery metadata and relevant QoS evidence; never decode
   user payload merely to populate scanner metrics.
5. Display wire observations in a distinct section, for example
   `Wire evidence: Fast DDS SEDP observed; native endpoint metadata incomplete`.
6. Never add native and packet-derived reader/writer counts together. Raw RTPS
   endpoint observations remain a separate count until entity-kind
   classification is proven stable across supported dissectors and vendors.

Do not automatically elevate an incomplete-discovery warning from capture in
the first release. The report can describe a manually collected observation and
its limitations, but it must not invent reader/writer identities from uncertain
packet fields. Automatic capture escalation is deferred until an
incomplete-discovery predicate is tested across supported vendors.

## Delivery Plan

### Phase 1: Scanner Data and Unit Tests

1. Add `SystemScanSnapshot`, `SystemIssue`, scoped finding identity fields, and
   an aggregation function consuming synthetic registry records and findings.
2. Add version-note generation with semantic version parsing.
3. Add scoped scan execution: domain once, participant once, endpoint once,
   and each canonical writer-reader pair once.
4. Unit-test severity bucketing, deduplication, stable ordering, suppression
   visibility, 7.3/7.7 version notes, scoped health rollups, and no double
   counting of wire evidence.
5. Add `Session.system_scan()` that returns one immutable snapshot containing
   issues and the associated native topology snapshot.

**Acceptance:** a synthetic reliability mismatch produces exactly one `ERROR`
issue whose evidence includes both endpoint keys, names its writer, reader,
topic, offered and requested values, and creates no probe reader.

### Phase 2: Metrics Dialog and Summary

1. Add `MetricsScreen` and bind `m` from the System Overview.
2. Add `SystemOverviewScreen` with the two numbered first-level choices.
3. Refresh the metrics snapshot with discovery updates and show the existing
   coverage note verbatim.
4. Update the Textual tests to assert the four counts, the no-data state, and
   navigation to both Issues and DDS Topology & Health. Distinguish the live
   metrics time from the issue-snapshot time.

**Acceptance:** an active fixture domain displays participant, reader, writer,
and topic counts that agree with `topology.snapshot()`; Doctor itself is not
counted.

### Phase 2b: Shareable System Report

1. Add `SystemReportData` and `render_system_text()` using the existing report
   formatting conventions.
2. Bind `s` on the System Overview, Issues, and DDS Topology & Health screens.
3. Export the current immutable scan snapshot without triggering a refresh or
   diagnosis, then label any cached deep-diagnosis results as post-snapshot.
4. Unit-test report ordering, all severity sections, topology counts, suppressed
   findings, and the explicit separation of native and wire evidence.

**Acceptance:** a saved report from a known reliability mismatch contains the
issue's writer and reader, the selected domain's four topology metrics, the
coverage caveat, and the same Error/Warning/Note totals shown in the UI.

### Phase 3: DDS Topology & Health

1. Refactor the current participant and endpoint screens under
   `TopologyHealthScreen` without changing their existing entity detail paths.
2. Add participant, reader, writer, and topic views backed by the registry.
3. Add static-finding health rollups and linked-issue navigation for every
   entity kind, including direct versus inherited domain conditions.
4. Preserve entity selection across discovery refresh by stable GUID key.

**Acceptance:** an operator can begin in DDS Topology & Health, choose a topic,
see all observed readers and writers for it, and open the related issue list.

### Phase 4: Issue Dashboard and Detail

1. Add `SystemScannerScreen`, severity filters, numbered rows, and keyboard
   selection.
2. Add `IssueDetailScreen` with endpoint relationships and provenance.
3. Reuse `ReportScreen` for full reports and focused probes rather than
   duplicating diagnostic rendering.
4. Preserve issue selection across refresh by stable issue key. Enable `d`
   only for one selected writer; provide a writer picker for multi-writer
   issues and a disabled reason for all other issue scopes.

**Acceptance:** an operator can choose Errors, select issue number 1, and see
the named topic plus every discovered incompatible reader and writer.

### Phase 5: Optional Capture Evidence

1. Connect the existing wire capture/inspection path to an explicit issue or
   writer action only when startup supplied a capture interface.
2. Render native and wire evidence separately.
3. Add capture fixtures using saved PCAPNG files; skip live-capture tests when
   permissions or `tshark` are unavailable.

**Acceptance:** a Fast DDS incomplete-discovery fixture retains native counts,
shows the RTPS observation separately, and does not merge their totals.

### Phase 6: Documentation and End-to-End Validation

1. Update the README key table, the metrics contract, and the passive-versus-
   probe distinction.
2. Add a live Connext fixture test for scanner aggregation and metrics.
3. Extend the cross-vendor fault suite so a known RxO mismatch surfaces in the
   scanner before deep diagnosis and opens the corresponding writer report.

**Acceptance:** Connext/Cyclone and Connext/Fast DDS reliability faults produce
one immediately selectable `ERROR` issue with the same `qos.rxo_mismatch`
evidence asserted by the existing headless report tests.

## Non-Goals for the First Release

- Historical trend storage, alerting, or incident management.
- A claim that a passive scan contains every endpoint that ever existed.
- Automatic interface-wide packet capture.
- Automatic probing of every writer on each UI refresh.
- Changing remote QoS, discovery, security, or application configuration.
- Treating a Connext upgrade recommendation as proof that it resolves a live
  interoperability defect.

## Validation Matrix

| Test layer | What it verifies |
|---|---|
| Unit | Aggregation, deduplication, severity counts, version notes, source separation, system report rendering |
| Textual screen tests | Overview routing, topology views, key bindings, numbered selection, metrics rendering, selection preservation |
| Live Connext | Native counts and scanner issue details agree with `DiscoveryRegistry` |
| Cross-vendor E2E | Known Cyclone/Fast DDS RxO faults appear immediately and name both endpoint sides |
| PCAP fixture | TShark evidence is displayed distinctly and never merged into native topology counts |

The existing fast unit tier should cover Phases 1-4. The cross-vendor and packet
capture tiers remain optional in environments without their runtimes,
permissions, or Docker image, and must report explicit skips rather than passing
silently.