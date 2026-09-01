# DDS Debug Game Implementation Plan

## Goal

Create `tools/rti_debug_game`, a standalone Python/Textual learning and
debugging tool that generates realistic DDS systems with intentional faults.
For each level, it copies editable generated participant scripts into
`tools/rti_debug_game/run/`, starts the simulated system, and passes the level
only when real DDS observation proves that every required reader received the
expected samples.

The game teaches a user to diagnose and correct DDS configurations by changing
programmatic participant, publisher, subscriber, writer, reader, and topic QoS
settings in each process. It reuses the repository's Python environment
launcher contract and the Textual interaction style of `rti_doctor`; it does
not modify `rti_doctor` or `rti_spy`.

## Product Decisions

### Editable Workspace

- Each level has an immutable generator definition in
  `tools/rti_debug_game/rti_debug_game/levels/`.
- Selecting **Start** or **Reset** renders the selected level into
  `tools/rti_debug_game/run/`. This directory is ignored by Git and is always
  visible to the user.
- Generated files include one `participant_*.py` script per participant,
  `README.txt`, and `expected.json`. Participant scripts are the only
  player-editable artifacts; `expected.json` and runner files are regenerated
  or package-owned.
- Every participant script defines both a `ParticipantQos` class and an
  `EndpointQos` class. `ParticipantQos` controls that process's participant
  QoS, including discovery QoS and initial peers; the scenario domain ID is
  game-owned and immutable. `EndpointQos` controls its
  publisher, subscriber, writer, reader, topic QoS, and topic name. Both
  classes use direct Python API values, not opaque generated QoS blobs or
  external configuration files.
- Every participant script also defines `DataModel`, which keeps the initial
  field schema fixed but exposes the registered type name and XTypes
  extensibility (`FINAL`, `APPENDABLE`, or `MUTABLE`) as gameplay settings.
- Starting a different level replaces the contents of `run/` after an explicit
  confirmation in the TUI and records the previous attempt under
  `run_history/<timestamp>-<level>/`. A normal rerun preserves the editable
  participant scripts exactly. Reset deletes and rerenders only the active
  level's generated scripts from its scenario file.
- The evaluator and level answer data remain in the installed package. The
  player may change every generated system setting, but a level passes only
  from measured DDS data, not from a player-maintained expected-result flag.

### Scenario Model

Each level is deterministic from a seed, but supports controlled variation so
the user learns a class of problem rather than memorizing one file.

```python
Scenario(
    id="reliable-command-drop",
    seed=1042,
  domain_id=42,
    duration_seconds=12,
    participants=[...],
    flows=[...],
    required_deliveries=[...],
    injected_faults=[...],
)
```

- Every scenario uses game-owned DDS domain `42`, reported in the TUI and
  `README.txt` for RTI Admin Console. The game takes a workspace lock before
  launch so concurrent Debug Game runs cannot collide on that domain.
- Every participant gets a deterministic name, role, host label, topic
  membership, and entity QoS configuration. Randomness is restricted to the
  level seed and is written to `expected.json`, making a failed run reproducible
  with `--seed`.
- Processes start in separate Python interpreters. A coordinator owns their
  lifecycle, collects structured stdout/stderr logs in `run/logs/`, and always
  terminates remaining children on pass, failure, Ctrl-C, or TUI exit.
- The first release runs all participants locally. Generated `ParticipantQos`
  defaults enable loopback UDP, multicast, and shared memory; their transport
  QoS, interface selection, discovery QoS, and initial-peer values are
  player-editable troubleshooting surfaces in every level. A configuration that
  leaves no usable transport is a valid failed-game state, not a launcher
  validation error.
- The first release uses a package-owned programmatic `DynamicType` builder
  and `DynamicData` payload with a fixed field schema, avoiding `rtiddsgen`.
  The schema reserves `writer_id`, `sequence`, `instance_key`, and `region` so
  the verifier can evaluate ordinary, ownership, and CFT expectations. Players
  may set each model's registered type name and XTypes extensibility, but do
  not add, remove, or change field definitions in this release.

### QoS Configuration Surface

Each generated participant script exposes two distinct classes for every QoS
policy available in the installed `rti.connextdds` Python API. The game must
not provide a short allowlist that silently prevents realistic fixes.

- `ParticipantQos` models process-wide participant QoS, including discovery
  configuration, `initial_peers`, transports, and participant properties. The
  package-owned scenario assigns the common domain ID and generated participant
  name. `EndpointQos` models
  publisher, subscriber, topic, data writer,
  and data reader QoS independently.
- `EndpointQos` exposes separately named factory methods for every generated
  local topic, writer, and reader. No generated endpoint silently inherits a
  shared writer or reader QoS object, so players can correct one relationship
  without changing another endpoint in the same process. Each playable
  participant creates one shared Publisher for all of its writers and one
  shared Subscriber for all of its readers; their QoS is explicitly configured
  by named `EndpointQos` factories. Initial scenarios use one shared publisher
  partition and one shared subscriber partition per playable process.
- A generic policy adapter maps the declarative Python values to RTI QoS
  objects. It supports nested policies, enums, durations, locators, sequences,
  builtin profiles, and property maps rather than handling policies through
  string substitutions.
- Generated `participant_*.py` scripts use explicit Python constructors for
  the policies relevant to the level and preserve an `extra_qos` escape hatch
  for every valid API-exposed property. The loader validates unknown entities,
  policies, enum values, duration formats, and incompatible value types before
  it creates DDS entities.
- Programmatic Python QoS values are the only configuration input; XML profiles
  and XML URLs are intentionally unsupported. Supported player-editable
  settings include discovery, transport, partition, data representation, resource limits,
  durability, reliability, ownership, liveliness, deadline, latency budget,
  lifespan, history, presentation, time-based filter, content filter, and
  flow-controller-related properties exposed by the Python API.
- Security is out of scope for the first release. The scenario model reserves
  an optional capability field for a later security scenario family, which must
  have explicit credential provisioning and isolated test infrastructure.
- The tool reports a clear capability error when a requested property is not
  present in the selected Connext/Python API version. It does not pretend to
  support unavailable vendor plugins or security credentials.

### Realistic System Scale

Normal levels use four to six participants. The advanced-system template uses
10-12 participants after laptop performance is measured, while retaining
realistic autonomous-system roles and topics.

| System area | Example participants | Example topics |
|---|---|---|
| Vehicle control | `AsterVehicleSupervisor`, `HeliosMotionController`, `NaviRoutePlanner` | `VehicleCommand`, `TrajectoryPlan`, `VehicleState` |
| Perception | `OrionLidarFusion`, `MiraCameraPerception`, `SableRadarTracker` | `LidarDetections`, `CameraObjects`, `TrackedObjects` |
| Localization | `AtlasLocalization`, `PioneerMapService`, `SentinelGnssBridge` | `PoseEstimate`, `MapUpdate`, `GnssFix` |
| Fleet operations | `KeplerFleetCoordinator`, `VectorMissionControl`, `HarborTelemetryGateway` | `MissionAssignment`, `FleetHealth`, `AuditEvent` |
| Safety and platform | `AegisSafetyMonitor`, `CinderPowerManager`, `QuartzDiagnostics` | `SafetyStatus`, `PowerState`, `DiagnosticAlert` |

Additional roles fill out redundant perception, simulation, actuator,
recording, and remote-operations services. Each generated topology includes
only meaningful producer/consumer relationships; it must not create a dense
all-to-all mesh simply to reach a participant count.

## User Experience

### TUI Flow

`./tools/rti_debug_game/run_rti_debug_game.sh` opens a Textual interface with
the familiar `rti_doctor` navigation conventions: arrow keys and Enter select,
`b` backs out, `r` refreshes, and `q` quits.

1. **Level select** shows all levels, completion status, difficulty,
   participating services, and the primary concept without revealing the fix.
2. **Briefing** shows the operational symptom, topology summary, immutable
  Mission Contract, scenario-domain instruction for RTI Admin Console, launch
  command, and the active `run/` path.
3. **Run monitor** displays process lifecycle and concise pass progress. It does
  not provide a diagnostic analysis surface; users inspect participants,
  endpoints, QoS, discovery, and matching with RTI Admin Console or other DDS
  diagnostic tools.
4. **Result** declares pass only after the verification contract succeeds. A
  scenario that has not passed remains live in **Waiting for fix** with its
  participants available to Admin Console; rerun, reset, level change, or quit
  stops the processes. A passed scenario remains live in **Passed - running**
  for Admin Console comparison until the same explicit actions stop it.

Participant writers publish continuously and readers continuously publish their
receipt state on control domain `100`. The coordinator re-evaluates the Mission
Contract for every state update and marks the level passed immediately when all
expectations are satisfied. Edits do not change existing DDS entities: after
editing a participant script, the user must select rerun to recreate the
scenario with the new participant QoS, endpoint QoS, and type metadata.
Completion is recorded once for the active run and is not revoked by subsequent
continuous traffic.

Continuous traffic is divided into immutable repeating verification rounds.
Each writer emits the scenario-defined sequence range for `round_id=1`, then
starts the same range for the next round. Receipt state includes `run_id`,
`round_id`, `writer_id`, `instance_key`, and `sequence`. A Mission Contract
passes as soon as one round satisfies every `ReaderExpectation`; it never
requires receipt of an unbounded continuous stream.

The normal edit/run loop is deliberately terminal-native:

```bash
./tools/rti_debug_game/run_rti_debug_game.sh
# TUI creates tools/rti_debug_game/run/
$EDITOR tools/rti_debug_game/run/participant_helios_motion_controller.py
./tools/rti_debug_game/run_rti_debug_game.sh --run
```

`--run`, `--status`, `--reset`, `--level ID`, `--seed N`, and `--headless` make
the same flow automatable. Headless runs print a concise
ASCII result and use nonzero exit status for configuration, runtime, or
verification failure. Interactive runs have no automatic timeout; headless and
test invocations provide an explicit finite timeout so they can return a result.

### Mission Contract

Every scenario defines package-owned pass metadata. The generator renders the
same human-readable Mission Contract in the TUI briefing, `run/README.txt`,
the run monitor, and `result.json`; player-editable participant scripts cannot
change it. It explains what correct DDS behavior looks like, without naming the
QoS setting that produces it.

The contract and `README.txt` state the exact scenario domain ID to open in RTI
Admin Console, along with the generated participant, topic, and registered type
names. The private game control domain is deliberately omitted from this
player-facing diagnostic recipe.

For ordinary fan-in, show the required reader, topic, writers, measured sample
count, and the post-match delivery window:

```text
MISSION CONTRACT
Topic: VehicleCommand
Required reader: HeliosMotionController
Expected writers: AsterVehicleSupervisor, VectorMissionControl
Delivery window: 10 samples per writer after communication is ready
Pass: Helios receives sequences 1-10 from both writers
```

Ownership and filtering scenarios instead name their applicable semantics:

```text
Topic: VehicleCommand
Required reader: HeliosMotionController
Expected active owner: AsterVehicleSupervisor
Backup: VectorMissionControl after Aster becomes unavailable
Pass: Receive only Aster data initially, then Vector data after failover
```

```text
Topic: TrackedObjects
Required reader: AegisSafetyMonitor
Expected writers: OrionLidarFusion, MiraCameraPerception
Filter rule: region == "west"
Pass: Receive every west-region sample and no other samples
```

The result compares every named expectation with observed writer IDs, keyed
instances where applicable, sequence ranges, and unexpected samples. A failed
contract reports those differences as operational evidence, not as a suggested
QoS correction.

### Progression

- Progress is stored locally in `tools/rti_debug_game/.state/progress.json`;
  no network account or telemetry is required.
- All levels are selectable from the start. The TUI records local completion
  and permits replaying completed levels; `--level` remains available for
  automation and development.
- A pass records the level ID, generator version, seed, elapsed time, and
  delivery summary. It must not record the source of the user's fix.
- Versioned level IDs preserve progress when new levels are added. If a level's
  behavior changes incompatibly, introduce a new ID instead of changing an
  existing completed challenge.

## Verification Contract

The coordinator validates reader-reported delivery through a game-owned
coordination topic and local process supervision. Generated participant scripts
are declarative modules: they define `ParticipantQos`, `EndpointQos`, and
`DataModel`, then hand them to an immutable package-owned participant runtime.
That runtime uses the package-owned field schema plus player-selected type
metadata, creates DDS entities, records received samples, and publishes a
`GameParticipantState` sample whenever its state changes. Required DDS readers
therefore follow player-edited QoS while state reporting cannot be accidentally
changed with the scenario configuration.

`GameParticipantState` is a shared immutable data model with process ID, run
ID, lifecycle state, discovered participant count, endpoint match counts,
received writer/instance/sequence ranges, incompatible-QoS policy IDs,
liveliness changes, sample-lost/rejected counts, write timeouts, valid versus
invalid lifecycle samples, and error detail. Each process
publishes it from a separate game-owned participant on a private loopback-only
control domain `100`. The scenario domain `42` therefore contains only the
participants, topics, and endpoints that the user inspects in Admin Console.
Control-domain QoS, type definitions, and discovery settings are fixed and are
not part of the player-editable configuration surface; the local process
supervisor still owns startup, timeouts, and cleanup.

This is a learning-tool integrity boundary, not a security boundary against a
user deliberately rewriting arbitrary Python. The coordinator never trusts
`run/expected.json`; it loads expectations from the package-owned scenario and
uses the generated copy only for display.

Each package-owned scenario defines `ReaderExpectation` entries rather than a
single global “every reader receives every sample” rule:

```python
ReaderExpectation(
   reader="AegisSafetyMonitor",
   topic="SafetyStatus",
   mode="all_matched_writers",
   post_match_samples_per_writer=10,
  forbidden_writers=("HarborTelemetryGateway",),
)
```

- `all_matched_writers` requires each reader to receive every declared measured
  sequence from each compatible writer on its topic. A writer begins measured
  publication only after its own declared local match condition is met and
  reports `WAITING_FOR_MATCH` otherwise.
- `exclusive_owner` requires each keyed instance to contain samples only from
  the selected live writer with highest `OWNERSHIP_STRENGTH`; an explicit
  failover expectation can require the backup only after ownership transfers.
- `content_filter` requires exactly the samples whose immutable fields satisfy
  the scenario's declared predicate and parameters. The coordinator computes
  this expected subset independently from player code.
- `time_filtered`, `late_join_volatile`, and `late_join_durable` declare their
  legitimate suppression/history semantics explicitly. They are never judged
  against the unfiltered writer sequence.
- `ordered_delivery` requires the declared writer sequences to be observed in
  source-timestamp order. `deadline` requires the configured deadline interval
  to complete without a requested-deadline-missed event.
- `liveliness` requires the declared alive/lost timeline; it supports both an
  RxO incompatibility and a matched writer that later loses its lease.
- `valid_data_only` distinguishes expected valid payloads from expected
  dispose, unregister, or no-writer lifecycle notifications. `partial_prefix`
  is used for controlled cache, batching, flow-control, or expiry exercises.
- Every expectation has required and forbidden receipt sets. A round passes
  only when every required sample arrives and no forbidden writer, instance, or
  sample arrives. This prevents broad partition, topic, or filter changes from
  passing by admitting unintended traffic.

1. Before processes start, the coordinator assigns a run ID and starts the
  local lifecycle timer. It tracks coordination-state delivery, participant
  discovery, endpoint discovery, matching, and data delivery as separate
  states; none is a prerequisite for process supervision.
2. Every writer publishes a run ID, round ID, source participant, keyed
  instance when applicable, monotonic sequence, timestamp, and payload
  checksum.
3. The package-owned runtime publishes received-sample state to the
  coordination topic. The coordinator rejects stale run IDs, duplicate ranges,
  and reports from a reader that exits abnormally.
4. The level passes immediately when every `ReaderExpectation` passes. An
  interactive run remains live until an explicit user action; a headless or
  test run reports failure when its caller-supplied finite timeout expires.
  Optional traffic may be reported but cannot conceal a failed expected
  reader-writer relationship.

The result file, `run/result.json`, includes per-flow expected count, observed
count, missing sequence ranges, incompatibility status, elapsed time, and log
paths. This gives the user enough evidence to debug without exposing a canned
solution.

## Progressive Scenario Catalog

The catalog is ordered from a single obvious writer-reader fault to realistic
system troubleshooting. It is based on the common discovery, endpoint matching,
and delivery failures identified by RTI Connext guidance. All levels are freely
selectable; the ordering is a learning path, not an unlock rule.

| ID | Scenario | Difficulty | Fault family | Mission Contract |
|---|---|---:|---|---|
| `L01` | Motion command is not armed | 1 | Writer best-effort cannot satisfy reader reliable request | `HeliosMotionController` receives sequences 1-10 from `AsterVehicleSupervisor` |
| `L02` | Safety alerts are routed away | 1 | Publisher/subscriber partition mismatch | `AegisSafetyMonitor` receives all declared `SafetyStatus` writer sequences |
| `L03` | Guidance channel has the wrong identity | 2 | Topic-name mismatch | `HeliosMotionController` receives all `VehicleCommand` writer sequences |
| `L04` | Perception type cannot be resolved | 2 | Registered type-name or XTypes extensibility incompatibility | eligible `TrackedObjects` readers match and deserialize their expected sequences |
| `L05` | Map replay misses the late joiner | 3 | Durability, history, and resource limits | `NaviRoutePlanner` receives declared retained history plus live `MapUpdate` sequences |
| `L06` | Safety monitor sees the wrong objects | 3 | Content-filter expression/parameter mismatch | reader receives exactly the `region == "west"` expected subset and no others |
| `L07` | Tracker appears to lose data | 4 | Time-based filter or deadline behavior | reader receives the scenario-declared rate-limited set and meets its deadline contract |
| `L08` | Dual controllers contend for actuation | 4 | Exclusive ownership and ownership strength | reader receives only the selected owner per instance, then the designated backup after failover |
| `L09` | Local fleet peers cannot find each other | 5 | Initial peers, discovery QoS, transport, or interface selection | all declared scenario-domain reader expectations pass |
| `L10` | Autonomous fleet recovery | 6 | Declared combined participant and endpoint issues | every Mission Contract expectation passes in a 10-12 participant system |
| `L11` | Vehicle cell has the wrong domain tag | 2 | Participant discovery domain-tag mismatch | required participants and endpoints become visible, then all declared deliveries pass |
| `L12` | Navigation entities never activate | 3 | Entity-factory auto-enable disabled | generated entities are enabled and every declared `PoseEstimate` delivery passes |
| `L13` | Perception endpoints vanish under load | 5 | Builtin endpoint-discovery resource limits or TypeObject size limits | all expected endpoints appear, match, and deliver |
| `L14` | Fleet control requests coherent access | 4 | Publisher/subscriber presentation QoS incompatibility | required endpoints match and command sequences arrive |
| `L15` | Sensor frames arrive in the wrong order | 4 | Destination-order incompatibility or source timestamps | source-timestamp ordered delivery passes |
| `L16` | Safety watchdog loses its publisher | 5 | Liveliness kind/lease incompatibility or lost assertion | required alive/lost timeline and designated failover behavior pass |
| `L17` | Diagnostics queue fills | 5 | Reader/writer history and resource exhaustion | all required sequences arrive without rejected samples or blocked writes |
| `L18` | Batch controller never ships commands | 5 | Batching, asynchronous publish mode, or restrictive flow controller | each reader receives its complete expected post-write sequence |
| `L19` | Obstacle record disappears immediately | 5 | Lifespan expiry or dispose/unregister lifecycle handling | Mission Contract's valid-data and lifecycle-event expectations pass |

Focused levels contain one primary fault. `L10` declares its known issue
categories in the briefing but has no predetermined issue count; it may contain
as many interacting participant, endpoint, topic/type, or transport/discovery
problems as the scenario requires.

### Capability Map

| Scenario need | Design element | First release status |
|---|---|---|
| Participant discovery, `initial_peers`, transports, interface selection | Per-process `ParticipantQos`; game-owned scenario domain `42` | Supported |
| Publisher/subscriber partitions | Shared publisher/subscriber factories in `EndpointQos` | Supported: one partition per shared entity |
| Topic identity | Per-topic `EndpointQos` factory | Supported |
| Registered type identity and extensibility | Per-process `DataModel`; fixed field schema | Supported |
| Reliability, durability, history, deadlines, liveliness, ownership, resource limits | Individually named writer/reader QoS factories in `EndpointQos` | Supported |
| Content filtering and time-based filtering | Immutable CFT-capable data fields plus `content_filter` / `time_filtered` `ReaderExpectation` | Supported |
| Ownership failover | Keyed immutable sample metadata plus `exclusive_owner` `ReaderExpectation` | Supported |
| Domain tags and entity enablement | `ParticipantQos` plus package-owned runtime enable policy | Supported |
| Presentation and destination order | Shared Publisher/Subscriber QoS and individual endpoint QoS factories | Supported |
| Liveliness, lifecycle state, expiry, batching, and asynchronous publication | `EndpointQos`, package-owned write schedule, and `liveliness` / `valid_data_only` / `partial_prefix` expectations | Supported |
| Endpoint-discovery and TypeObject resource limits | `ParticipantQos` plus endpoint/type visibility telemetry | Supported |
| Cache exhaustion and reliable blocked writes | Writer/reader resource QoS plus write-result and sample-rejection telemetry | Supported |
| Deterministic pass/fail evidence | Private control-domain `100` `GameParticipantState`; package-owned Mission Contract | Supported |
| Arbitrary DynamicData schema/key changes | Editable `DataModel` schema plus receipt-metadata adapter | Future roadmap |
| Multiple Publishers/Subscribers per participant | Expanded entity model and independent partitions/presentation | Future roadmap |
| Security exercises | Credentials, permissions, and isolated security fixture | Future roadmap |

The Mission Contract remains the source of pass criteria, and users diagnose
the declared system issues with Admin Console and the editable Python source.

### Runtime Support for Advanced Scenarios

- The package-owned participant runtime must honor
  `EntityFactoryQosPolicy.autoenable_created_entities`. When player QoS disables
  automatic enablement, it must not silently call `enable()` unless the scenario
  explicitly declares a package-owned lifecycle step.
- The scenario definition owns the deterministic write schedule, including
  deliberate late joins, delayed takes, source timestamps, manual-liveliness
  assertions, batching/flush timing, and controlled dispose/unregister calls.
  Player scripts supply QoS and type metadata, not test-oracle logic.
- The runtime captures applied QoS and every relevant DDS status condition in
  `GameParticipantState`, so the TUI can show concise progress while Admin
  Console remains the primary diagnostic surface.
- Advanced resource-limit and TypeObject scenarios use fixed small values and
  bounded sample counts; they must prove their broken and reference-fixed forms
  repeatedly in the live test tier before becoming playable levels.

## Future Roadmap

- Add an opt-in editable `DataModel` class for DynamicData type-definition,
  keying, assignability, and type-evolution exercises. It will require a stable
  receipt-metadata adapter so the game can evaluate CFT, ownership, and
  delivery expectations after a player changes the schema.
- Add advanced scenarios with multiple Publisher/Subscriber entities per
  participant, including independent partitions and presentation behavior.

## Architecture

```text
tools/rti_debug_game/
  run_rti_debug_game.sh
  run_tests.sh
  requirements.txt
  README.md
  .gitignore                         # run/, run_history/, .state/, test_output/
  rti_debug_game/
    __main__.py                      # CLI and launcher dispatch
    app.py                           # Textual App and screen routing
    state.py                         # progress and active-run metadata
    models.py                        # Scenario, EntitySpec, FlowSpec, ReaderExpectation
    qos.py                           # validated declarative QoS -> RTI QoS adapter
    generator.py                     # seed-based rendering into run/
    participant_runtime.py            # immutable DDS entity/receipt runtime
    coordination.py                   # private control-domain state aggregation
    runner.py                        # child processes, cleanup, timeouts
    verifier.py                      # independent delivery oracle and result
    reporting.py                     # TUI/headless result formatting
    levels/
      catalog.py
      l01_reliability.py
      ...
    views/
      level_select.py
      briefing.py
      run_monitor.py
      result.py
  test/
    test_models.py
    test_qos.py
    test_generator.py
    test_verifier.py
    test_runner.py
    test_cli.py
    test_live_levels.py
  run/                               # generated, ignored, user editable
```

## Delivery Stages

### Stage 1: Foundation and Launcher

1. Add the standalone package, launcher, requirements, Git ignore rules, and
   `README.md` under `tools/rti_debug_game/`.
2. Mirror the supported `scripts/python_env.sh` bootstrap sequence used by
   `rti_doctor`: initialize, resolve optional `NDDSHOME`, create/activate the
   repository virtual environment, synchronize `rti.connextdds`, Textual, and
   required runtime dependencies, then resolve the license when using the
   public package.
3. Implement CLI validation and stable exit statuses before creating a DDS
   participant. `--help` and malformed-option tests must run without a license.
4. Add state initialization and a clearly named ignored output layout.

### Stage 2: Declarative Scenario and QoS Engine

1. Define typed models for participants, topics, entities, flows, expected
   deliveries, faults, seeds, and timeouts.
2. Implement the generic QoS adapter with version-aware capability checks and
   exact validation errors that identify the entity and policy path.
3. Build generated participant-script loading: import the local `ParticipantQos`,
  `EndpointQos`, and `DataModel` classes in a separate child process, validate
  their values, and pass them to the immutable participant runtime. The shared
  runtime, not player-authored code, owns entity lifecycle and receipt reporting.
4. Unit-test supported policy conversion, invalid values, nested policy values,
   and unavailable-API behavior without a live DDS domain.

### Stage 3: Generator and Editable Run Lifecycle

1. Build level catalog entries and seed-based topology generation.
2. Render readable Python sources with named constants and deliberately local
   QoS declarations, plus a concise operational `README.txt` and machine
   readable expectations.
3. Implement active-run replacement, normal reruns that preserve edits, reset
  that deletes and regenerates the active scripts, archived attempts, and
  recovery after interrupted generation using atomic directory swaps.
4. Test that same level/version/seed renders byte-identical files and that a
   different seed changes only documented variable fields.

### Stage 4: DDS Runner and Independent Oracle

1. Implement a child-process protocol for generated participants, readiness,
   structured logs, received-sample reports, stop requests, and abnormal exits.
2. Implement writers/readers using the generated QoS and typed envelope.
3. Implement the coordinator and result evaluator, including run IDs, match
  barriers, sequence tracking, duplicate/stale receipt rejection, deadline
  handling, and bounded cleanup.
4. Add a local live-domain harness that proves the oracle fails each injected
   fault and passes only after the level's valid configuration is restored.

### Stage 5: Textual Experience and Progression

1. Implement the four screens and shared `rti_doctor` keyboard conventions.
2. Stream runner state at a bounded interval, keeping logs and long results
   scrollable without blocking the UI event loop.
3. Add progress persistence, freely selectable levels, replay, reset confirmation, and
   clear active-directory/path presentation.
4. Add headless parity tests so a TUI run and `--headless --run` produce the
   same verifier result.

### Stage 6: Level Content and Documentation

1. Deliver `L01` and `L02` as reference implementations; validate that their
   intended corrections are limited to generated programmatic settings.
2. Add the remaining initial level set incrementally, adding a real passing and
   failing live test for each new fault family.
3. Document supported Connext/Python versions, license/runtime setup, how to
   edit and reset `run/`, expected local DDS-network constraints, and the
   distinction between a learning simulator and diagnosis of an external live
   system.
4. Update [tools/README.md](../tools/README.md) after the launcher and first
   playable levels are available.

## Test Strategy

Adopt the same explicit tiers as `rti_doctor`:

| Tier | Command | Coverage |
|---|---|---|
| Unit | `./tools/rti_debug_game/run_tests.sh` | model, QoS conversion, generator, state, CLI, result aggregation; no DDS entity |
| Live | `./tools/rti_debug_game/run_tests.sh live` | local-domain level execution using Connext and a license |
| Stress | `./tools/rti_debug_game/run_tests.sh stress` | 10-12 participant advanced topology, cleanup, bounded logs, repeatability |

- Unit tests use fakes at the RTI boundary and assert the generated source and
  structured scenario model separately.
- Live tests start on an isolated domain, run each level in its intentionally
  broken form, assert failure, apply the reference programmatic correction,
  then assert pass. They also assert that at least one required reader really
  misses data in the failing run.
- Stress runs repeat the advanced scenario enough times to identify resource
  leaks and port/domain contamination, with time limits suitable for CI.
- All test logs and generated artifacts stay under
  `tools/rti_debug_game/test_output/` or its ignored run directories.

## Acceptance Criteria

- A user can launch a Textual DDS Debug Game using the repository's supported
  Python environment workflow.
- Starting a level creates readable, editable participant scripts under
  `tools/rti_debug_game/run/`; reruns preserve edits, reset regenerates the
  active scripts, and level changes archive prior attempts.
- Generated participant scripts permit programmatic configuration of every QoS
  property exposed by the selected RTI Connext DDS Python API, plus topic names
  and `DataModel`-owned registered type names, with clear errors for
  unavailable capabilities.
- The evaluator uses live DDS observation and requires every nominated reader
  to receive its expected data before awarding a pass.
- The initial release includes freely selectable realistic autonomous-system
  scenarios and an advanced topology of 10-12 participants.
- A failed level produces actionable delivery, matching, and log evidence
  without disclosing a hard-coded solution.
- Unit, live, and 10-12 participant stress tiers pass through the tool's own
  `run_tests.sh` launcher.