# rs_gui Historical QoS Analysis Plan

## Goal

Add a Replay-tab action, **Run QoS Mismatch Analysis**, that becomes available
after the operator selects a valid Recording Service SQLite log directory. The
action reads recorded discovery data from the recording's `discovery.db`,
reconstructs historical writer and reader endpoint state, evaluates the same
observable QoS rules as RTI Doctor, and lists findings grouped by recorded
domain, participant/process, and topic.

This is an offline historical analysis. It must not claim that a result is a
live Replay Service incompatibility or an original runtime status event.

## Prototype Status

This document records the target design and the investigation behind the
prototype. The current rs_gui implementation is a coarse reference example,
not an implementation of every contract below. It uses a direct, read-only
7.7 `discovery.db` reader and reports a limited set of candidate QoS mismatches.
It does not yet provide the shared RTI Doctor comparator, complete lifecycle
interpretation, complete data-representation handling, timestamp selection,
cancellation, grouped policy detail, or the full fixture/live coverage
described in this plan.

Do not treat its output as authoritative endpoint matching history. It does not
cover all lifecycle, type-compatibility, security, transport,
data-representation, and related edge cases. Supported QoS mismatch analysis
is planned for an upcoming Connext Studio release.

## Decisions

- Read `discovery.db` directly in read-only mode. The 7.7 Recording Service
  writes flattened discovery samples there, while `rticonverter` accepts only
  the user-data fileset and rejects this database as an empty input set.
- Treat its table layout as version-pinned adapter input, not as a cross-version
  storage API. Validate required tables and columns before analysis, and report
  an unsupported recording schema rather than guessing.
- Extract RTI Doctor's DDS-free endpoint-pair comparison into a neutral shared
  Python module. Doctor retains its `Finding` formatting wrapper; rs_gui uses
  the same comparison results in GUI view models.
- Preserve `FAIL`, `PASS`, and `UNEVALUATED` policy results. Missing historical
  discovery fields are not defaults and must not become a mismatch.
- Treat `PARTITION` as a separate endpoint-match gate, not an RxO QoS failure.
- Report data-representation compatibility from public discovery fields only.
  Mark the RTI compression extension unavailable: its settings are not exposed
  by the public publication/subscription built-in topic data.

## User Flow

1. The operator selects a recording directory in the Replay launch form.
2. rs_gui validates that the directory contains `metadata.db` and one or more
   `data_*.db` files, then enables **Run QoS Mismatch Analysis** independently
   of whether Replay Service is running.
3. The operator selects a recorded domain from metadata, or accepts the only
  discovered domain, and optionally narrows the analysis time window.
4. rs_gui reads the recording's `discovery.db` in a background worker, validates
  its 7.7 schema, reconstructs endpoint lifetimes, compares candidate
  writer/reader pairs, and shows a result tree.
5. The result tree groups issues as `domain -> participant/process -> topic ->
   writer/reader pair -> policy`. Selecting a policy displays offered/requested
   values, the DDS rule, timestamp, endpoint GUIDs, and unavailable policy data.

## Analysis Contracts

### Shared QoS Core

Create a neutral Python package under `dds/utils/python/` with no `rti.*`, GUI,
or RTI Doctor imports. Its input is a small endpoint DTO containing:

```text
endpoint key, direction, participant key, participant name, process metadata,
domain id, topic name, type name, vendor id, observed time, alive state,
reliability, durability, latency budget, deadline, liveliness, ownership,
destination order, presentation, partition, data representation
```

Expose `compare_endpoints(writer, reader) -> ComparisonResult`, preserving the
Doctor result semantics:

- ordered RxO: `RELIABILITY`, `DURABILITY`, `LIVELINESS`,
  `DESTINATION_ORDER`, and `PRESENTATION.access_scope`;
- duration RxO: `DEADLINE`, `LATENCY_BUDGET`, and
  `LIVELINESS.lease_duration`;
- exact RxO: `OWNERSHIP`;
- directional RxO: `DATA_REPRESENTATION`;
- presentation flags: `coherent_access` and `ordered_access`;
- non-RxO endpoint gate: wildcard-aware `PARTITION` overlap;
- `UNEVALUATED` for unreadable/missing fields.

The module must retain Doctor's conservative vendor-specific handling of an
empty writer data-representation advertisement. It must not infer an effective
representation for an unknown vendor or unreadable field.

### Recorded Discovery Reader

Add `app_core/recorded_discovery.py`, which is DDS-free and opens
`<recording>/discovery.db` in SQLite read-only mode. It must:

1. Require `DCPSParticipant`, `DCPSPublication`, and `DCPSSubscription`, plus
  the 7.7 flattened `SampleInfo_*`, key, participant-key, topic/type, and QoS
  columns used by the comparator.
2. Read the flattened samples and normalize them into the shared endpoint DTO;
  use `hex()` on key blobs so endpoint and participant GUIDs remain stable
  strings without XCDR deserialization.
3. Apply valid/dispose/unregister lifecycle changes in timestamp order.
4. Compute an active interval for every endpoint. In whole-recording mode,
  compare pairs only while their valid intervals overlap; at a selected instant,
  apply the latest lifecycle state at or before that instant.
5. Generate pairs only inside the same domain and topic. Type mismatch and
   partition disjointness remain distinct results from RxO mismatches.
6. Associate endpoints with participant name plus best-effort process metadata
   from recorded participant properties (`hostname`, `process_id`, executable).

Keep all SQL isolated in this adapter and use parameterized values. Persist a
small 7.7 `discovery.db` fixture before treating table or column names as the
supported feature contract.

## rs_gui Integration

### App Core

- Add immutable analysis DTOs: request, read progress, endpoint snapshot, policy
  result, pair result, grouped issue, and analysis snapshot.
- Add an `HistoricalQosAnalysisController`/facade that owns analysis state,
  background database work, cancellation, and schema/read diagnostics.
- Do not put SQLite or QoS comparison logic in tkinter code.
- Add command types `replay.analyze_qos` and `replay.cancel_qos_analysis`.

### Replay Models and Controller

- Extend `ReplayTabViewModel` with an analysis section containing availability,
  running state, progress, output path/tail, selected timestamp, and grouped
  issues.
- Add the analysis controller dependency to `ReplayTabController`; route the
  two new command types through it.
- Enable analysis when `_has_replayable_sqlite_files()` succeeds, not only after
  Replay Service launches.
- Persist the selected analysis timestamp and last successful output location in
  GUI workspace intent; do not persist temporary process handles or endpoint
  object instances.

### Tk Replay Tab

- Add **Run QoS Mismatch Analysis** next to Replay actions and a Cancel control
  only while database analysis is active.
- Add a compact analysis-status row and a timestamp selector.
- Render issue groups in a tree/table with columns: domain, participant/process,
  topic, writer, reader, result, and policy count.
- Render pair/policy detail below the list, including the offered/requested table
  and explicit `UNEVALUATED` policies.
- Keep a clean empty state: "Select a recording directory containing discovery
  data"; distinguish missing discovery streams from conversion failures.

## Tests and Acceptance

1. Move Doctor's existing RxO unit matrix to the neutral shared module without
   changing its expected results, then run Doctor's focused `test_checks.py`.
2. Add shared-module tests for all nine observable RxO policies, partition
   wildcard/default behavior, unknown/unreadable values, and vendor-scoped
   data-representation inference.
3. Add recorded-discovery JSON SQLite fixtures and tests for schema failure,
   participant/process attribution, endpoint lifecycle reconstruction, selected
   timestamp snapshots, and grouped results.
4. Add Replay controller tests verifying valid/invalid recording availability,
   schema failures, cancellation, success/failure propagation, and workspace
   persistence.
5. Add Tk widget tests for action enablement, progress rendering, issue grouping,
   and policy detail rendering.
6. Run `./tools/rti_doctor/run_tests.sh` for Doctor and rs_gui tests. Add one
  licensed live smoke test that records a known QoS mismatch and verifies the
  expected historical finding from `discovery.db`.

## Risks and Guards

- Existing logs may lack sufficient discovery history. Report this explicitly;
  do not manufacture endpoint pairs.
- `discovery.db` is an implementation-facing Recording Service artifact. Pin
  fixture coverage to the supported release and fail clearly on unsupported
  schema.
- Historical discovery proves what endpoints advertised at a timestamp, not the
  exact original match-status event. Label all results accordingly.
- Replay Service writer QoS is separate from original writer QoS. Do not merge
  replay-time statuses into historical analysis results.

## 7.7 Spike Evidence

On 2026-09-03, `tools/rti_doctor/test/fixture_publisher.py --mode mixed_qos`
with seed `42` was recorded using a dedicated Recording Service configuration
that selected the three discovery built-in topics. The resulting recording
contained `metadata.db`, empty user-data `data_0.db`, and `discovery.db` with
the three expected tables.

`discovery.db` contained 22 participant, 34 publication, and 18 subscription
sample rows. Its publication/subscription tables retain flattened timestamps,
valid/lifecycle state, endpoint and participant keys, topic/type, all required
observable QoS fields, partition, vendor data, and participant properties.
Repeated rows and final invalid lifecycle samples prove that analysis must use
timestamped lifetimes rather than final-row state.

`rticonverter` 7.7 rejects this recording for discovery conversion with
`Empty file set passed to input connection set, nothing to replay`, because it
only consumes the user-data fileset. This is why this plan deliberately uses a
validated, release-pinned direct reader for `discovery.db`.