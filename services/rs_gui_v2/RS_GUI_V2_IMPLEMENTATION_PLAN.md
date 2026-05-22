# RS GUI v2 Implementation Plan

## Confidence Assessment

We have enough confidence to begin implementation, with one important boundary:
the first work should productize the DDS app core before building feature-heavy
rs_gui_v2 screens.

The current code already proves the hardest first DDS pieces:

- Recording Service admin request/reply works with correlated replies.
- Recording Service monitoring works with XML DynamicData and `rti.asyncio`.
- Connext environment, license, XML type stamping, and XTypes policy setup are
  centralized.
- GUI command execution is serialized and tested.
- Live Recording Service E2E tests exist.

The remaining high-risk areas are not whether we can talk to DDS; they are
runtime shape, discovery/type resolution, DynamicData throughput, GUI thread
isolation, plotting backpressure, and durable workspace persistence. This plan
front-loads those risks.

## Implementation Rules

- Keep the current tkinter GUI working as the reference implementation until
  rs_gui_v2 has its own vertical slice.
- Keep rs_gui_v2 independent from rs_gui_v1. rs_gui_v2 must not import,
  instantiate, subclass, shell out to, or depend on rs_gui_v1 implementation
  modules. Use rs_gui_v1 only as an external behavior reference and regression
  baseline.
- If logic needs to be shared between the two applications, extract it into a
  neutral shared module with its own tests instead of making either GUI depend
  on the other.
- Create and approve mock wireframes before implementing rs_gui_v2 screens.
- Build and test the app core in headless mode before wiring rich UI behavior.
- Treat rs_gui_v2 as a Connext reference example: each new capability should
  have a small app-level API, an isolated Connext adapter when DDS is needed,
  and tests or docs that make the RTI API usage easy to find.
- Keep direct `rti.*` imports out of pure models, facades, state reducers,
  persistence, plotting buffers, and GUI modules. Direct Connext imports belong
  only in explicitly named `rti_` or `dds_` adapter modules and their live tests.
- Document the public API and the matching Connext API surface before expanding
  a feature into UI code.
- Do not let the UI layer or Dear PyGui own DDS entities or mutate widgets from
  DDS callbacks.
- Model admin command acknowledgment separately from observed service state.
- Use bounded queues, bounded sample caches, and plot decimation from the first
  DynamicData subscription work.
- Persist declarative user intent, not live DDS handles or transient discovery
  identities.

## Milestone A: Headless Runtime Foundation

Goal: Create a runnable app skeleton with clean startup, shutdown, logging, and
dependency wiring, but no feature-heavy UI.

Deliverables:

- `app_core` package scaffold.
- runtime lifecycle object for startup, background tasks, and shutdown.
- app command queue and app event queue.
- headless entry point for tests.
- v2-owned dependency adapters around Connext environment and XTypes helpers.

Acceptance gates:

- App starts and exits repeatedly without orphan threads or DDS tasks.
- Headless startup/shutdown test passes.
- Existing tkinter GUI tests still pass.

DDS notes:

- Stop background DDS tasks before destroying participants.
- Keep Connext policy setup idempotent and process-wide.
- Keep the DDS runtime owned by app core, not the UI bootstrap.

Suggested first PRs:

1. Add `app_core/runtime.py`, `app_core/events.py`, `app_core/state.py`.
2. Add `rs_gui_v2_app.py` or equivalent shell entry point.
3. Add headless lifecycle tests.

Initial implementation status:

- Added `app_core` runtime, event, command, result, and state models.
- Added `rs_gui_v2_app.py` with a DDS-free `--headless-check` entry point.
- Added pure headless unit tests for lifecycle, queues, task supervision,
  immutable DTOs, and the entry point.
- Deferred environment/XTypes adapters to Milestone B so Milestone A remains
  DDS-free.

Milestone B initial implementation status:

- Added v2-owned service DTOs for service references, admin readiness, command
  requests/outcomes, monitoring snapshots, and service-state snapshots.
- Added DDS-free `ServiceAdminFacade` and `ServiceMonitoringFacade` protocols.
- Added deterministic fake admin and monitoring clients for headless tests.
- Added import-boundary tests proving the headless app core does not import DDS,
  Dear PyGui, tkinter, or rs_gui_v1 implementation modules.
- Added `app_core/services/rti_admin.py` as the v2-owned RTI Service Admin
  request/reply adapter, with Connext imports isolated to the adapter module.
- Added `setup.sh` and ignored `xml_types/` path so v2 generates its own
  Service Admin XML DynamicData artifacts instead of depending on rs_gui_v1.
- Added fake-Connext adapter tests for Service Admin resource paths, state and
  tag payload encoding, readiness, reply timeout, rejected replies, and cleanup.
- Added `app_core/services/rti_monitoring.py` as the v2-owned RTI service
  monitoring adapter for config, event, and periodic monitoring topics.
- Expanded `setup.sh` to generate and normalize v2-owned monitoring XML type
  artifacts.
- Added fake-Connext adapter tests for monitoring reader setup, invalid sample
  filtering, config/event/periodic normalization, snapshot streaming, and
  cleanup.
- Added DDS-free discovery and type catalog models for topic inventory,
  endpoint direction, local type availability, internal-topic filtering, and
  persisted topic/field selections.
- Added `app_core/rti_discovery.py` as the v2-owned Connext built-in topic
  discovery adapter for publication and subscription built-in readers.
- Added fake-Connext adapter tests for discovery sample normalization, endpoint
  churn, internal-topic filtering, topic aggregation, and cleanup.
- Expanded `app_core/types.py` to enumerate generated XML type declarations and
  preserve source XML, declaration kind, canonical name, short-name resolution,
  and missing/ambiguous resolution messages without importing DDS.
- Added `app_core/rti_types.py` as the v2-owned Connext XML DynamicData type
  registry adapter that uses `QosProvider.type()` to load DynamicTypes from the
  generated v2 XML files.
- Added fake-Connext adapter tests for exact type lookup, short-name lookup,
  missing catalog types, provider load failures, configured XML validation, and
  workspace-local test XML cleanup.
- Deferred live service fixtures and broader DDS runtime setup to later
  Milestone B/C slices.

## Milestone B: Service Admin and Monitoring Facades

Goal: Build rs_gui_v2-owned Recording Service admin and monitoring adapters with
stable, product-facing interfaces.

Deliverables:

- `ServiceAdminFacade` with typed command methods and typed command results.
- readiness model for admin writer/reply-reader matching.
- `ServiceMonitoringFacade` that normalizes config, event, and periodic samples.
- shared resource path builders.
- service state model with requested, acknowledged, and observed states.
- import-boundary tests proving service adapters do not depend on rs_gui_v1.
- reference notes that show which RTI Service Admin and monitoring topics, types,
  and resource paths are used by the Connext adapters.

Acceptance gates:

- Integration test sends pause/resume/tag/shutdown through the facade.
- Tests distinguish service unavailable, discovery timeout, command rejected,
  and command acknowledged.
- Monitoring updates are normalized without GUI dependencies.
- Existing rs_gui_v1 controller and monitor tests still pass as an external
  regression baseline.
- rs_gui_v2 service adapters have no imports from `services/rs_gui_v1`.
- Pure service models, facades, and fakes have no `rti.*` imports.
- Any DDS-backed admin or monitoring client lives in an explicitly named Connext
  adapter module and implements the DDS-free protocol.
- Adapter tests show pause, resume, tag, shutdown, readiness, timeout,
  rejected-command behavior, config/event/periodic monitoring normalization,
  invalid sample handling, and cleanup. Live tests should be added once v2
  service fixtures are available.

DDS notes:

- Remote administration and monitoring must be enabled in service XML.
- Admin domain and monitoring domain may differ; model both explicitly.
- Wait for request writer and reply reader matches before sending commands.
- A successful command reply can arrive before monitoring catches up.

Suggested PRs:

1. Add `app_core/services/models.py` with service refs, readiness, command
  results, and monitoring snapshots.
2. Add `app_core/services/admin.py` as the DDS-free admin protocol and facade.
3. Add `app_core/services/monitoring.py` as the DDS-free monitoring protocol and
  facade.
4. Add fake service adapters for deterministic headless tests.
5. Add live service facade tests that compare against the existing service
  fixtures without importing rs_gui_v1 implementation modules.
6. Add `app_core/services/rti_admin.py` and `rti_monitoring.py` only after the
   DDS-free protocols and fakes are covered by tests.

Reference API checklist:

- `ServiceInstanceRef` names the service kind, service name, admin domain, and
  monitoring domain without storing DDS handles.
- Enforce service-name uniqueness for the service kind and admin domain before
  launch, during workspace restore, and when discovered services are merged into
  the operator target list.
- For GUI-created services, generate a fresh session GUID each time the GUI
  creates or restarts a service process, derive the launched service control name
  from the operator label plus that session GUID, and store the editable label
  and launch intent in the workspace document without reusing old session GUIDs.
- Keep application-level control and process-level recovery separate in the API:
  Service Admin commands target the unique service control name, while process
  termination uses verified local host/pid identity only after graceful shutdown
  fails.
- Store discovered hostname, application/process id when available, participant
  key/GUID, participant name, and last-seen timestamps for each service
  candidate so duplicate-name conflicts can still identify the physical process
  instances involved.
- Extend the RTI discovery adapter to collect participant system properties from
  `ParticipantBuiltinTopicData.property`, including `dds.sys_info.hostname` and
  `dds.sys_info.process_id`, using `discovered_participants()` /
  `discovered_participant_data(handle)` or the participant built-in topic reader.
- Extend the RTI monitoring adapter to preserve service identity fields from
  config samples, including `application_guid`, `process.id`, and `host.name`,
  as candidate-correlation evidence.
- Model shutdown as a two-layer operation: Service Admin graceful shutdown first,
  followed by a guarded local process termination fallback only for verified
  local process candidates when graceful shutdown fails or does not complete.
- `ServiceAdminFacade` exposes operator verbs and returns typed command
  outcomes.
- `rti_admin.py` shows request/reply topic names, request/reply types,
  correlation handling, resource paths, readiness matching, and timeout mapping.
- `ServiceMonitoringFacade` exposes normalized snapshots.
- `rti_monitoring.py` shows config, event, and periodic monitoring readers and
  maps DynamicData into typed snapshots.

## Milestone C: Discovery and Type Catalog

Goal: Build the metadata backbone for topic browsing, plotting, replay
selection, and persisted subscriptions.

Deliverables:

- built-in topic discovery cache.
- topic inventory model.
- type catalog that maps discovered topic/type names to locally available
  DynamicData types.
- internal-topic filtering policy.
- explicit topic states: discovered, type available, reader created, matched,
  receiving, unresolved, ambiguous.

Acceptance gates:

- Headless test discovers fixture topics.
- Type resolution succeeds for at least one user topic and service monitoring
  topics.
- Discovery churn test handles writers/readers appearing and disappearing.
- Internal `rti/*` and service topics are hidden by default but can be shown.
- Discovery APIs distinguish DDS discovery metadata from local type availability
  and reader/subscription state.
- Connext built-in topic reader usage is isolated to a dedicated adapter module.

DDS notes:

- Discovery is eventually consistent; do not require all metadata to arrive in
  one order.
- A discovered topic may not be locally subscribable until the type is available.
- Multiple endpoints can share a topic name with different QoS or type-evolution
  details; surface ambiguity.

Suggested PRs:

1. Add `app_core/discovery.py` with topic inventory models.
2. Add `app_core/types.py` for local XML DynamicData type lookup.
3. Add tests for filtering, ambiguity, and missing type handling.
4. Add a dedicated `rti_discovery.py` adapter that demonstrates built-in topic
   reader usage without leaking DDS objects into catalog models.

Initial implementation status:

- Added `app_core/discovery.py` with DDS-free endpoint, topic inventory,
  discovery facade, fake discovery client, internal-topic filtering, and
  persisted topic-selection DTOs.
- Added `app_core/types.py` with a DDS-free `TypeCatalog` and `TypeResolution`
  model that distinguishes available, missing, ambiguous, and unknown type
  resolution states.
- Added `app_core/rti_discovery.py` as a pull-based Connext adapter that reads
  `DomainParticipant.publication_reader` and `subscription_reader`, maps
  built-in publication/subscription samples to `DiscoveredEndpoint`, and closes
  owned participants cleanly.
- Added headless tests for type resolution, topic aggregation, internal-topic
  hiding, persisted selections, fake discovery scans, built-in sample mapping,
  endpoint removal, and adapter cleanup.
- Expanded `TypeCatalog` to parse generated XML files with structured XML
  parsing, track `TypeSource` records, and resolve exact and short type names.
- Added `app_core/rti_types.py` with `RtiTypeRegistry`, `DynamicTypeLookup`, and
  `RtiTypeRegistryConfig` for Connext `QosProvider.type()` lookups behind the
  DDS-free catalog API.
- Added tests for XML type parsing, exact and short-name DynamicType lookup,
  missing types, Connext provider failures, and configured XML file validation.
- Verified the real registry loads the generated v2 XML catalog and resolves
  Service Admin and Service Monitoring DynamicTypes.
- Deferred live discovery fixtures to the next Milestone C slice.

Reference API checklist:

- Discovery models identify domain, topic name, type name, endpoint direction,
  endpoint count, and internal-topic classification.
- Type catalog APIs identify whether local DynamicData type information exists
  and why a type is unresolved or ambiguous.
- `rti_types.py` shows generated XML file enumeration, source validation, and
  Connext `QosProvider.type()` lookup without leaking DynamicType handles into
  pure catalog models.
- Adapter tests include discovery churn and a topic with discovered metadata but
  missing local type information.

## Milestone D: DynamicData Subscription Engine

Goal: Create reusable, bounded topic subscriptions before building the Topics
and Plots UI.

Deliverables:

- `SubscriptionManager` for creating and stopping DynamicData readers.
- `SampleCache` with bounded ring buffers per topic.
- sample metadata model with timestamps and instance state.
- field-path extraction primitives.
- rate limits, decimation, and pause/resume controls.

Acceptance gates:

- Subscribe and unsubscribe repeatedly without leaks.
- Sustained sample-rate test has bounded memory growth.
- Multiple simultaneous topic subscriptions work in headless tests.
- Invalid samples and instance state changes are represented, not silently lost.
- Raw DynamicData reading, field extraction, sample caching, and plotting remain
  separate modules with separate tests.

DDS notes:

- Python `read()` and `take()` produce Python objects; high-rate streams can
  create allocation pressure.
- Avoid per-sample UI updates; publish snapshots or coalesced events.
- Prefer selected field extraction over walking full DynamicData trees for every
  plot update.

Suggested PRs:

1. Add `app_core/subscriptions.py` and `app_core/sample_cache.py`.
2. Add `app_core/extractors.py` for canonical field paths.
3. Add headless load tests with a fixture publisher.
4. Add `rti_subscriptions.py` as the only module in this layer that creates
   Connext DynamicData readers.

Reference API checklist:

- Subscription APIs accept declarative topic/type/field selections, not DDS
  handles.
- `rti_subscriptions.py` shows topic lookup/creation, DynamicData reader
  creation, `read`/`take` choice, sample-info handling, and shutdown.
- Extractor tests show scalar, nested-struct, optional/missing, and nonnumeric
  field behavior without requiring live DDS.
- Sample-cache tests prove bounded memory and dropped/decimated sample counters.

Initial implementation status:

- Added `app_core/subscriptions.py` with DDS-free subscription requests,
  subscription states, sample metadata snapshots, sample envelopes, stable
  subscription keys, and a bounded `SampleCache` with dropped-sample counters.
- Added `TopicSubscriptionClient` and `FakeTopicSubscriptionClient` so app-core
  orchestration and tests can exercise subscription behavior without importing
  Connext.
- Added `app_core/rti_subscriptions.py` as the v2-owned Connext DynamicData
  subscription adapter. It resolves DynamicTypes through `RtiTypeRegistry`,
  creates `DynamicData.Topic` and `DynamicData.DataReader`, maps valid and
  invalid samples into `SampleEnvelope`, and closes owned readers and
  participants.
- Added headless tests for subscription DTO round trips, sample metadata,
  bounded cache behavior, unresolved type handling, reader creation,
  valid/invalid sample mapping, unsubscribe, and cleanup.
- Verified a real smoke creates a DynamicData reader from generated v2 XML type
  information on an unused domain and takes zero samples without a writer.
- Added `app_core/extractors.py` with DDS-free `FieldPath`, `FieldPathStep`,
  `FieldExtraction`, extraction status, value-kind classification, and helpers
  for extracting selected paths from `SampleEnvelope` data.
- Added headless extractor tests for nested mappings, object attributes,
  DynamicData-like item access, sequence indexes, missing fields, null values,
  invalid paths, invalid samples, and numeric/text/boolean/sequence
  classification.
- Added `app_core/fields.py` with DDS-free `FieldCatalog`, `FieldDescriptor`,
  catalog status, scalar-kind classification, collection-kind classification,
  parent/child path metadata, and plot-eligibility helpers.
- Added `app_core/rti_fields.py` as the v2-owned Connext DynamicType field
  catalog adapter. It resolves DynamicTypes through `RtiTypeRegistry`, walks
  struct and union members, records bounded strings and sequences, classifies
  numeric scalar leaves, and keeps collection expansion explicit.
- Added headless field catalog tests for DTO round trips, child-path population,
  plottable-field filtering, nested DynamicType traversal, union variants,
  unresolved types, depth limits, and optional collection-content expansion.
- Verified a real smoke builds field catalogs from generated v2 XML DynamicTypes
  and finds plottable numeric leaves without creating DDS readers.
- Added `app_core/workspace.py` with DDS-free `WorkspaceDocument`,
  `WorkspacePlotDefinition`, `WorkspacePlotSeries`, versioned JSON migration,
  deterministic load/save helpers, and validation errors for malformed
  workspace state.
- Added headless workspace tests for JSON round trips, file save/load, v1 to v2
  migration, unknown future fields, malformed documents, declarative-only JSON,
  and restart-style preservation of topic, field, subscription, and plot intent.
- Added `app_core/plotting.py` with DDS-free `PlotSeriesBuffer`,
  `PlotBufferSet`, point and snapshot DTOs, numeric sample updates from
  `SampleEnvelope`, bounded history windows, max-point pruning, skipped sample
  counters, dropped point counters, and deterministic last-value decimation.
- Added headless plotting tests for numeric updates, invalid/missing/nonnumeric
  sample skips, topic/type matching, history pruning, max-point pruning,
  decimation, point round trips, plot-level snapshots, disabled plots, and
  nonmatching sample behavior.
- Added `app_core/data_session.py` with `DataSessionCoordinator`,
  `DataSessionConfig`, `DataSessionUpdate`, and `DataSessionSnapshot` to compose
  workspace subscriptions, topic selections, plot series, type resolution,
  sample caches, subscription clients, and plot buffers without importing DDS or
  GUI libraries.
- Added headless data-session tests for workspace request derivation,
  duplicate field merging, disabled selections, available and unresolved type
  states, sample polling, bounded cache drops, invalid-sample accounting, plot
  updates, snapshot serialization, stop, and close behavior.
- Deferred live fixture publishers and GUI rendering to later Milestone D/E
  slices.

## Milestone E: UI Wireframes and Approval

Goal: Approve the operator workflow and screen structure before writing
rs_gui_v2 UI code.

Deliverables:

- mock wireframes for App Shell, Record, Replay, Convert, Topics, Plots, and
  Workspace/Settings.
- state annotations for loading, empty, degraded, unavailable, and error states.
- command lifecycle representation: requested, acknowledged, observed, failed.
- topic lifecycle representation: discovered, type available, reader created,
  matched, receiving, unresolved, ambiguous.
- approval notes captured in
  [RS_GUI_V2_WIREFRAME_PLAN.md](RS_GUI_V2_WIREFRAME_PLAN.md).

Acceptance gates:

- Top-level navigation model is approved.
- Record tab command feedback and monitoring layout are approved.
- Replay and Convert MVP workflow scope is approved.
- Topics to Plots handoff is approved.
- Workspace save/restore behavior is approved.

DDS notes:

- Use realistic DDS and RTI service states in the mockups.
- Include no-match, stale XML, missing license, unresolved type, and QoS mismatch
  states before UI implementation.
- Keep Replay visualization represented as normal DDS topic subscription, not as
  data owned by the Replay tab.

Suggested PRs:

1. Add low-fidelity Markdown wireframes for each major view.
2. Review and revise wireframes with operator feedback.
3. Freeze the approved MVP UI scope before rs_gui_v2 widget implementation.

Initial wireframe draft status:

- Expanded [RS_GUI_V2_WIREFRAME_PLAN.md](RS_GUI_V2_WIREFRAME_PLAN.md) with
  low-fidelity Markdown sketches for App Shell, Record, Replay, Convert,
  Topics, Plots, and Workspace/Settings.
- Added app-core API annotations for each view so the future Dear PyGui shell
  can stay snapshot-driven and DDS-free.
- Added state tables for command lifecycle, topic lifecycle, degraded restore,
  missing type, unavailable service, invalid sample, high-rate plotting, and
  job failure behavior.
- Added duplicate-service tracking guidance so accidental multiple Recording or
  Replay Service instances are represented as ambiguous physical candidates for
  one logical `ServiceInstanceRef`, rather than silently selecting one process.
- Added candidate-level control guidance that distinguishes local process stop
  from Service Admin shutdown, and keeps Service Admin controls disabled when a
  duplicate service name would make the DDS admin target non-unique.
- Added service-name uniqueness guidance so duplicate service kind/name/admin
  domain combinations are treated as validation conflicts and Service Admin
  controls stay disabled until the conflict is resolved.
- Added session-GUID-backed service control-name guidance so GUI-created
  services can keep friendly labels while producing fresh, uniquely targetable
  Service Admin names on each service launch or restart.
- Added discovery-identity guidance so host/app ids and participant keys can be
  stored as candidate evidence without replacing the unique service control name
  required for Service Admin targeting.
- Added two-layer shutdown guidance so graceful Service Admin shutdown is tried
  before local process termination, and process termination remains an explicit,
  validated fallback path.
- Added Connext discovery guidance for retrieving host and process id from
  participant builtin topic properties while keeping PID-based termination as a
  local fallback, not a Service Admin command target.
- Added an explicit two-layer control summary: unique session-GUID application
  names for Service Admin commands, and stored process ids for guarded local
  termination fallback.
- Added Record/Replay process selector guidance so multiple launched or
  discovered candidates can be selected, inspected, and controlled without
  silently choosing one.
- Added Milestone F.0 headless service control foundation with session-GUID
  control identities, process candidates, selector state, duplicate-target
  detection, and guarded process-termination availability tests.
- Added candidate composition helpers that merge GUI launch identity, RTI
  monitoring snapshots, and DDS discovery endpoint evidence into selector-ready
  `ServiceCandidateSelection` snapshots.
- Marked the wireframe package as drafted for review, not yet approved.

## Milestone F.0: Headless Service Candidate and Control Identity Foundation

Goal: Prove the service/process identity model before adding Dear PyGui state.

Implemented:

- `ServiceLaunchIntent` captures persisted operator launch intent without
  storing runtime DDS handles or stale session GUIDs.
- `ServiceControlIdentity` derives a fresh session-GUID service control name for
  each GUI-created launch/restart and exposes the corresponding
  `ServiceInstanceRef` for Service Admin commands.
- `ServiceProcessCandidate` stores launched or discovered process evidence:
  source, host, pid, participant identity, application guid, config paths,
  state, metrics, ownership, confidence, and timestamps.
- `ServiceCandidateSelection` backs the Record/Replay target selector and scopes
  control availability to the selected process candidate.
- `ServiceControlAvailability` distinguishes Service Admin availability from
  guarded local process termination fallback.
- Candidate composition helpers build candidates from GUI launch identities,
  monitoring snapshots, and discovered endpoints, then merge matching evidence
  by application guid, participant key, launch id, or host/pid.

Acceptance gates:

- Fresh session GUIDs produce unique Service Admin control names.
- Duplicate live candidates for the same service kind/name/admin-domain disable
  Service Admin controls.
- Process termination is enabled only after graceful shutdown failure and only
  for owned or verified-local process candidates.
- Service control foundation remains DDS-free, GUI-free, and independent of
  rs_gui_v1.
- Candidate composition preserves the owned-process flag from GUI launches while
  enriching the selected candidate with monitoring metrics and discovery
  participant identity.

## Milestone F: RS GUI v2 Shell and Record Tab MVP

Goal: Deliver the first useful operator workflow while proving the UI bridge.

Deliverables:

- UI scheduler that drains app-core events on the Dear PyGui thread.
- status bar and event log panel.
- Record tab with target selector/dropdown, candidate table, service status,
  command buttons, tag controls, command history, and observed-state display.
- error presentation for timeout, no match, rejected command, and stale XML
  types.

Acceptance gates:

- UI remains responsive during service monitoring bursts.
- Record tab can pause/resume/tag/shutdown a live fixture service.
- Record tab can select among multiple launched or discovered Recording Service
  candidates and scope stats/controls to the selected candidate.
- Command history shows request id, target resource, reply status, and observed
  state when available.
- No Dear PyGui calls occur from DDS/runtime threads.

DDS notes:

- Keep one admin request/reply exchange active per service client at a time.
- Show requested, acknowledged, and observed state separately.
- Monitoring may remain at a service-level state while a recording session is
  paused; do not overfit UI state to one monitoring field.

Suggested PRs:

1. Add rs_gui_v2 shell and scheduler.
2. Add Record tab backed by mocked app-state snapshots.
3. Wire Record tab to the real service facade.

## Milestone G: Topics Tab

Goal: Make discovery and sample inspection useful before plotting.

Deliverables:

- discovered topic table/tree.
- search, filter, and show-internal toggle.
- type status and QoS/matching diagnostics.
- subscribe/unsubscribe actions.
- sample inspector for structured DynamicData values.
- field picker based on the type catalog.

Acceptance gates:

- User can inspect a live user topic and a service monitoring topic.
- Unresolved or unsupported types display clear states.
- Topic selection survives discovery churn when stable topic/type identity is
  unchanged.

DDS notes:

- Topic discovery is not a guarantee that DynamicData subscription will work.
- QoS mismatch can look like an empty data view; expose match diagnostics.
- Start with a conservative flattening strategy for nested fields.

Suggested PRs:

1. Add Topics tab using mocked discovery snapshots.
2. Wire topic list to discovery catalog.
3. Wire sample inspector to subscription snapshots.

## Milestone H: Plots Tab

Goal: Plot selected numeric fields from live or replayed DynamicData streams
with bounded resource usage.

Deliverables:

- numeric field selection from the Topics tab.
- plot model with series, history window, and time source.
- decimation/downsampling before widget updates.
- pause/resume plot updates.
- plot layout model ready for persistence.

Acceptance gates:

- Plot remains responsive under sustained fixture traffic.
- Plot remains source-agnostic: live publishers and Replay Service output both
  feed the same topic subscription, sample cache, and plot buffer pipeline.
- Missing or invalid values do not break the plot loop.
- Memory remains bounded during a long plotting test.
- Plot configuration can be serialized by the workspace layer.

DDS notes:

- Choose receive timestamp vs source timestamp explicitly.
- Replay can produce timing patterns different from live data; handle out-of-order
  or bursty samples.
- Do not bind plot widgets directly to raw DDS sample arrival.

Suggested PRs:

1. Add `app_core/plotting.py` with series reducers and buffers.
2. Add Plots tab with mocked series.
3. Wire Plots tab to selected live or replayed DDS fields.

## Milestone I: Workspace Persistence

Goal: Restore user intent across restarts without persisting DDS runtime
objects.

Deliverables:

- versioned workspace schema.
- save/load for domains, services, selected topics, selected fields, plots,
  filters, recent recordings, and UI layout preferences.
- migration tests.
- degraded restore behavior when topics or types are absent.

Acceptance gates:

- Workspace round-trip test passes.
- Older schema migration test passes.
- Loading a workspace with missing topics produces unresolved selections rather
  than failing startup.
- GUI can restore Record, Topics, and Plots selections after restart.

DDS notes:

- Persist domain id, topic name, registered type name, field path, service name,
  and resource identifiers.
- Do not persist DomainParticipant, DataReader, Requester, DynamicType objects,
  or transient endpoint GUIDs as primary user identity.

Suggested PRs:

1. Add `app_core/workspace.py` and schema tests.
2. Add save/load commands in the shell.
3. Restore topic and plot selections through app-core reconciliation.

## Milestone J: Replay Tab

Goal: Add Replay Service workflows after the command/state and plotting models
are proven.

Deliverables:

- replay service target selection with process selector/dropdown and candidate
  table.
- recording database selection.
- replay start, pause, resume, stop, and shutdown actions.
- replay rate, loop, and time-window controls where supported by config.
- replay state and progress display.

Acceptance gates:

- Live fixture replay can be controlled through the facade and UI.
- Replay tab can select among multiple Replay Service candidates and scope
  progress, stats, and controls to the selected candidate.
- Replayed data can be inspected in Topics and plotted in Plots.
- Replay visualization uses the same Topics/Plots pipeline as live data after
  Replay Service publishes samples onto DDS topics.
- Replay command errors and monitoring lag are visible.

DDS notes:

- Replay publishes data back into DDS; visualization should subscribe through the
  normal topic pipeline, not through the Replay tab.
- Replay writer QoS must match the readers that consume replayed data.
- Centralize replay command builders; do not assemble string or octet bodies in
  UI callbacks.

Suggested PRs:

1. Add replay facade and state model.
2. Add Replay tab with mocked state.
3. Add live replay-to-topic-inspection E2E test.

## Milestone K: Convert Tab

Goal: Add Converter Service or conversion-job orchestration after the core UI is
valuable.

Deliverables:

- conversion input selection.
- output format and output location controls.
- job preset model.
- run/cancel controls and job log display.
- recent conversion outputs.

Acceptance gates:

- Known-good conversion job completes from the UI.
- Invalid input/output paths surface clear errors.
- Conversion presets persist in the workspace.

DDS notes:

- Treat Converter as a job facade first unless the deployed service exposes the
  same admin/monitoring behavior we need.
- Keep converted file inspection separate from live DDS visualization.

Suggested PRs:

1. Add converter job facade.
2. Add Convert tab with validation and logs.
3. Add live conversion fixture test.

## Milestone L: Hardening, Packaging, and Soak

Goal: Make the tool durable enough for repeated operator use.

Deliverables:

- performance counters for queues, samples, drops, and UI update cadence.
- telemetry burst tests.
- service restart and discovery churn tests.
- high-rate subscription memory plateau test.
- packaging and launcher scripts.
- user documentation and troubleshooting guide.

Acceptance gates:

- Long-running monitoring and plotting soak passes.
- Repeated Recording/Replay Service restarts do not wedge the UI.
- Memory usage plateaus under high-rate fixture traffic.
- Startup diagnostics identify stale XML, missing license, missing service admin,
  and no-match conditions.

## Suggested Sprint Grouping

Sprint 1:

- Milestone A and the first half of Milestone B.
- Outcome: headless runtime plus Service Admin facade.

Sprint 2:

- Finish Milestone B and complete Milestone C.
- Outcome: monitoring facade plus discovery/type catalog.

Sprint 3:

- Milestone D and Milestone E.
- Outcome: subscription engine plus approved UI wireframes.

Sprint 4:

- Milestone F and Milestone G.
- Outcome: rs_gui_v2 Record tab vertical slice plus topic browsing and sample
  inspection.

Sprint 5:

- Milestone H and Milestone I.
- Outcome: plotting MVP plus persisted workspaces.

Sprint 6:

- Milestone J through Milestone L.
- Outcome: Replay workflow, Convert workflow, hardening, soak, and packaging.

## First Implementation Cut

Start with a narrow PR that creates the headless app core without changing the
existing tkinter path:

1. Add `app_core/runtime.py` with lifecycle start/stop and task registration.
2. Add `app_core/events.py` with command and event DTOs.
3. Add `app_core/state.py` with a minimal immutable app-state snapshot.
4. Add tests that start and stop the runtime without DDS.
5. Add a second test that wires v2-owned Connext environment validation into the
  runtime but does not create a GUI.

That gives us a small, reversible foundation. The next PR can add v2-owned
Recording Service admin models, fake adapters, and a `ServiceAdminFacade` shape,
then validate behavior against live service fixtures without importing rs_gui_v1
implementation modules.