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
- Create and approve mock wireframes before implementing rs_gui_v2 screens.
- Build and test the app core in headless mode before wiring rich UI behavior.
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
- dependency adapters around existing environment and XTypes helpers.

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

## Milestone B: Service Admin and Monitoring Facades

Goal: Wrap the existing Recording Service controller and monitor in stable,
product-facing interfaces.

Deliverables:

- `ServiceAdminFacade` with typed command methods and typed command results.
- readiness model for admin writer/reply-reader matching.
- `ServiceMonitoringFacade` that normalizes config, event, and periodic samples.
- shared resource path builders.
- service state model with requested, acknowledged, and observed states.

Acceptance gates:

- Integration test sends pause/resume/tag/shutdown through the facade.
- Tests distinguish service unavailable, discovery timeout, command rejected,
  and command acknowledged.
- Monitoring updates are normalized without GUI dependencies.
- Existing direct controller and monitor tests still pass.

DDS notes:

- Remote administration and monitoring must be enabled in service XML.
- Admin domain and monitoring domain may differ; model both explicitly.
- Wait for request writer and reply reader matches before sending commands.
- A successful command reply can arrive before monitoring catches up.

Suggested PRs:

1. Add `app_core/services/admin.py` wrapping `recording_service_control.py`.
2. Add `app_core/services/monitoring.py` wrapping `recording_service_monitor.py`.
3. Add service facade tests using the existing live fixtures.

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

## Milestone F: RS GUI v2 Shell and Record Tab MVP

Goal: Deliver the first useful operator workflow while proving the UI bridge.

Deliverables:

- UI scheduler that drains app-core events on the Dear PyGui thread.
- status bar and event log panel.
- Record tab with service status, command buttons, tag controls, command history,
  and observed-state display.
- error presentation for timeout, no match, rejected command, and stale XML
  types.

Acceptance gates:

- UI remains responsive during service monitoring bursts.
- Record tab can pause/resume/tag/shutdown a live fixture service.
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

Goal: Plot selected numeric fields from live DynamicData streams with bounded
resource usage.

Deliverables:

- numeric field selection from the Topics tab.
- plot model with series, history window, and time source.
- decimation/downsampling before widget updates.
- pause/resume plot updates.
- plot layout model ready for persistence.

Acceptance gates:

- Plot remains responsive under sustained fixture traffic.
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
3. Wire Plots tab to selected live fields.

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

- replay service target selection.
- recording database selection.
- replay start, pause, resume, stop, and shutdown actions.
- replay rate, loop, and time-window controls where supported by config.
- replay state and progress display.

Acceptance gates:

- Live fixture replay can be controlled through the facade and UI.
- Replayed data can be inspected in Topics and plotted in Plots.
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
5. Add a second test that wires the existing Connext environment validation into
   the runtime but does not create a GUI.

That gives us a small, reversible foundation. The next PR can wrap the existing
Recording Service controller behind `ServiceAdminFacade` and immediately reuse
the live E2E fixtures.