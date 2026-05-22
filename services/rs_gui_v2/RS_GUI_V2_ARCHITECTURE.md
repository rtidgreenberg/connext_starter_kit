# RS GUI v2 RTI Services App Architecture

Companion planning documents:
[RS_GUI_V2_IMPLEMENTATION_PLAN.md](RS_GUI_V2_IMPLEMENTATION_PLAN.md) breaks this
architecture into phased milestones, PR-sized tasks, and validation gates.
[RS_GUI_V2_WIREFRAME_PLAN.md](RS_GUI_V2_WIREFRAME_PLAN.md) defines the mock
wireframes and approval gate required before rs_gui_v2 UI implementation.

## Purpose

This document sketches the next architecture step for the Recording Service GUI
work: rs_gui_v2, a Dear PyGui-based application for operating RTI infrastructure
services and inspecting DDS data.

The current tkinter GUI remains the compact DDS reference implementation. This
document is the target architecture for a broader operator tool that supports:

- Recording Service control and tagging
- Replay Service control
- Converter Service job orchestration
- DDS topic discovery and selection
- DynamicData sample inspection
- Numeric field plotting
- Persisted workspaces across restarts

rs_gui_v2 is also intended to be a reference example for Connext end users. That
means the architecture should favor clear, inspectable API usage over clever
framework code. Each major capability should have an obvious owner, a small
public interface, and an adapter module where the relevant Connext API calls are
easy to find.

## Reference Example Goals

- Keep user-facing workflows separate from Connext transport details.
- Keep pure models, protocols, reducers, and persistence importable without DDS.
- Put direct `rti.*` imports only in explicitly named Connext adapter modules.
- Prefer small modules that demonstrate one Connext concept at a time:
  participant setup, Service Admin request/reply, monitoring readers, discovery,
  DynamicData type lookup, or DynamicData subscriptions.
- Make request/reply, monitoring, discovery, and data subscription examples
  independently testable so users can copy or study one area without pulling in
  the whole GUI.
- Document the app-level API beside the Connext API it uses, so the sample is
  useful both as an application and as learning material.

## Design Principle

rs_gui_v2 should use Dear PyGui as the view layer, not the DDS layer.

DDS entities, service requesters, monitoring readers, topic subscriptions, type
registries, and persistence should live in an application core that has no Dear
PyGui dependency. The GUI should render state snapshots, dispatch user intents,
and drain thread-safe event queues during its frame loop.

This keeps the existing DDS lessons intact:

- DDS callbacks and reader loops stay off the GUI thread.
- Service administration and service monitoring remain separate channels.
- DynamicData type loading is explicit and tied to the active Connext install.
- Process-wide Connext policies are configured once by a shared runtime layer.

The same separation applies inside `app_core`: lifecycle, state, service DTOs,
and facade protocols remain DDS-free; Connext code lives behind adapter classes
whose purpose is visible from the filename and tests.

## Target Shape

```text
services/rs_gui_v2/
+-- setup.sh                  # Generate v2-owned XML DynamicData type files
+-- app_core/
|   +-- runtime.py              # DDS-free lifecycle, queues, task ownership
|   +-- connext_environment.py  # NDDSHOME, license, XML stamp helpers
|   +-- dds_runtime.py          # DomainParticipant, QoS, XTypes, shutdown
|   +-- events.py               # App events and command/result DTOs
|   +-- state.py                # In-memory app state snapshots
|   +-- workspace.py            # Versioned persistence load/save/migrate
|   +-- discovery.py            # Built-in topic discovery catalog
|   +-- rti_discovery.py        # Connext built-in topic reader adapter
|   +-- types.py                # XML DynamicData type registry
|   +-- rti_types.py            # Connext QosProvider DynamicType lookup adapter
|   +-- fields.py               # DDS-free field catalog DTOs
|   +-- rti_fields.py           # Connext DynamicType field catalog adapter
|   +-- subscriptions.py        # DynamicData reader lifecycle
|   +-- rti_subscriptions.py    # Connext DynamicData reader adapter
|   +-- extractors.py           # Field-path compilation and value extraction
|   +-- plotting.py             # Ring buffers, decimation, series updates
|   +-- data_session.py         # Workspace-driven sample and plot snapshots
|   +-- services/
|       +-- models.py           # Pure service DTOs
|       +-- admin.py            # DDS-free admin protocol and facade
|       +-- monitoring.py       # DDS-free monitoring protocol and facade
|       +-- fakes.py            # Deterministic fake service clients
|       +-- rti_admin.py        # Connext Service Admin request/reply adapter
|       +-- rti_monitoring.py   # Connext service monitoring reader adapter
|       +-- recording.py        # Recording Service facade
|       +-- replay.py           # Replay Service facade
|       +-- converter.py        # Converter Service job facade
+-- gui/
|   +-- main_window.py          # Dear PyGui setup and frame loop
|   +-- tabs/
|   |   +-- record_tab.py
|   |   +-- replay_tab.py
|   |   +-- convert_tab.py
|   |   +-- topics_tab.py
|   |   +-- plots_tab.py
|   +-- widgets/
|       +-- topic_tree.py
|       +-- field_picker.py
|       +-- sample_inspector.py
|       +-- service_status.py
+-- test/
  +-- test_workspace.py
  +-- test_discovery_catalog.py
  +-- test_field_extractors.py
  +-- test_plotting_buffers.py
  +-- test_e2e_rs_gui_v2_services.py
```

The package names above are a target direction. The first implementation can
reuse protocol lessons from the current Recording Service GUI, but rs_gui_v2
must not depend on rs_gui_v1 implementation modules. If a helper becomes useful
to both applications, extract it into a neutral shared package with its own tests
instead of coupling one GUI version to the other.

## API Boundary Rules

| Layer | Owns | Public API | Connext imports |
| --- | --- | --- | --- |
| Runtime core | lifecycle, queues, task supervision | `AppRuntime`, `RuntimeConfig`, `AppEvent`, `AppCommand` | No |
| State/model core | immutable snapshots and DTOs | dataclasses with `to_dict`/`from_dict` where useful | No |
| Service facades | operator-level service commands and monitoring views | `ServiceAdminFacade`, `ServiceMonitoringFacade`, service DTOs | No |
| Connext adapters | mapping facade calls to RTI APIs | protocol implementations such as `RtiServiceAdminClient` | Yes, adapter only |
| GUI | widgets, layout, user input | state snapshots and command dispatch | No direct DDS |
| Tests/examples | behavioral contracts and reference snippets | fakes for unit tests, live fixtures for adapters | Adapter tests only |

Rules for new modules:

- A module named `models.py`, `events.py`, `state.py`, `workspace.py`, or
  `plotting.py` must not import DDS or GUI libraries.
- A module named `admin.py`, `monitoring.py`, `recording.py`, `replay.py`, or
  `converter.py` should define app-level APIs and facades, not low-level DDS
  calls.
- A module that directly imports `rti.*` should use an explicit `rti_` or
  `dds_` name and should expose a small implementation of a protocol from the
  DDS-free layer.
- UI modules should consume immutable state snapshots and enqueue commands. They
  should not create participants, topics, readers, requesters, or DynamicData
  objects.
- Shared helpers must be neutral. If code is useful to both rs_gui_v1 and
  rs_gui_v2, move it into a separate shared package with tests rather than
  importing one GUI version from the other.

## Connext API Usage Map

| Capability | App-level API | Adapter module | Connext concepts shown |
| --- | --- | --- | --- |
| Runtime setup | `DdsRuntime` or equivalent lifecycle owner | `app_core/dds_runtime.py` | `DomainParticipant`, `QosProvider`, participant shutdown, process-wide policy setup |
| Service Admin | `ServiceAdminClient` implementation | `app_core/services/rti_admin.py` | Service Admin request/reply topics, command request/reply types, correlation, resource paths, reply timeout handling |
| Service monitoring | `ServiceMonitoringClient` implementation | `app_core/services/rti_monitoring.py` | monitoring config/event/periodic topics, DynamicData readers, sample normalization |
| Topic discovery | `TopicDiscoveryFacade`, `TopicInventory`, `TopicSelectionState` | `app_core/rti_discovery.py` | publication/subscription built-in topic readers, endpoint metadata, discovery churn |
| Type catalog | `TypeCatalog`, `TypeResolution` | `app_core/types.py`, `app_core/rti_types.py` | XML type enumeration, local type availability, `QosProvider.type()` DynamicType lookup |
| Field catalog | `FieldCatalog`, `FieldDescriptor` | `app_core/fields.py`, `app_core/rti_fields.py` | DynamicType member traversal, scalar/collection classification, plot eligibility |
| Workspace persistence | `WorkspaceDocument`, `WorkspacePlotDefinition` | `app_core/workspace.py` | DDS-free topic/type/field intent, versioned JSON migration |
| Data subscription | `TopicSubscriptionRequest`, `SampleEnvelope`, `SampleCache` | `app_core/subscriptions.py`, `app_core/rti_subscriptions.py` | DynamicData topics/readers, `take`, sample info, instance state, reader shutdown |
| Field extraction | `FieldPath`, `FieldExtraction` | `app_core/extractors.py` | DDS-free extraction from mapping/object/DynamicData-like sample values |
| Plot buffers | `PlotBufferSet`, `PlotSeriesBuffer`, `PlotBufferSnapshot` | `app_core/plotting.py` | DDS-free bounded history, numeric sample updates, deterministic decimation |
| Data session | `DataSessionCoordinator`, `DataSessionSnapshot` | `app_core/data_session.py` | DDS-free orchestration of workspace intent, type resolution, subscription clients, sample caches, and plot buffers |
| Replay visualization | normal topic subscription APIs | `app_core/rti_subscriptions.py` | replayed samples are just DDS data consumed by Topics/Plots |

Each adapter should make the Connext calls visible in one place. The facade
above it should translate those calls into typed outcomes and snapshots that are
safe for UI code, tests, and persisted workspaces.

## Layer Responsibilities

### 1. DDS Runtime Layer

Owns low-level Connext entities and process-wide DDS setup:

- DomainParticipant lifecycle
- `QosProvider` loading
- XML DynamicData type loading
- shared XTypes compliance policy setup
- built-in discovery readers
- DynamicData topic readers
- request/reply clients
- orderly shutdown

Only this layer should directly create DDS entities. A good initial target is one
participant per domain for the application runtime, with shared subscribers and
readers underneath it. Avoid creating a participant per tab or per plot.

Reference example guidance:

- Keep participant creation and QoS provider loading in one module so users can
  see the complete setup path.
- Keep shutdown order explicit: stop readers/tasks, close requesters/readers,
  then release participants.
- Do not hide `$NDDSHOME`, license, XML type, or QoS errors behind generic app
  exceptions; preserve enough detail for end users learning Connext setup.

### 2. Service Integration Layer

Owns operator-level service actions. It should hide DDS topic names, request
types, and monitoring topic schemas from the GUI.

Core concepts:

- `ServiceInstanceRef`: service kind, service name, admin domain, monitoring
  domain, and optional configuration paths.
- `ServiceAdminClient`: pause, resume, shutdown, tag, and service-specific
  commands using RTI Service Admin request/reply.
- `ServiceMonitoringClient`: config, event, and periodic monitoring readers.
- `ServiceFacade`: cached service state plus commands and diagnostics.

Keep the control plane and monitoring plane separate. A command reply indicates
whether a service accepted and executed a command; monitoring topics describe
service state, metrics, and events. Those states do not always map one-to-one.

Reference example guidance:

- `ServiceAdminFacade` should expose operator verbs such as `pause`, `resume`,
  `shutdown`, and `tag`.
- `rti_admin.py` should expose the Connext mechanics behind those verbs:
  request topic, reply topic, request type, reply type, resource path, timeout,
  and correlation handling.
- `ServiceMonitoringFacade` should expose normalized service snapshots.
- `rti_monitoring.py` should show how monitoring DynamicData samples are read
  and mapped into config, event, and periodic updates.
- Do not combine admin request/reply and monitoring state into one DDS class;
  they are separate RTI service interfaces and should remain separately
  teachable.

### 3. Discovery and Type Catalog Layer

Owns the difference between a topic that was discovered and a topic the app can
inspect or plot.

The catalog should track:

- domain id
- topic name
- registered type name
- discovered writers and readers
- endpoint QoS summaries when available
- whether local type information is available
- whether a DynamicData reader can be created
- whether numeric leaf fields are available for plotting
- persisted topic and field selections as declarative user intent, separate from
  DDS reader handles

Filter internal topics by default, including `rti/*`, Service Admin topics, and
infrastructure monitoring topics. Let advanced users opt into seeing them.

Reference example guidance:

- Keep discovery metadata separate from local type availability.
- Surface why a topic cannot be subscribed: unresolved type, ambiguous type,
  QoS mismatch, no matched writers, or internal-topic filtering.
- Keep the built-in topic reader calls visible in `rti_discovery.py`; the
  facade and persisted selection DTOs must remain importable without Connext.
- Keep XML parsing and type-resolution DTOs in `types.py`; keep Connext
  `QosProvider.type()` calls in `rti_types.py` so type lookup remains a clear,
  standalone reference example.
- Keep field catalog DTOs and plot-eligibility decisions in `fields.py`; keep
  Connext DynamicType member traversal in `rti_fields.py` so the field picker
  can explain what is selectable without creating readers.

### 4. Visualization Pipeline Layer

Owns live data subscriptions requested by the GUI.

Responsibilities:

- create and destroy DynamicData readers for selected topics
- process samples on the DDS runtime thread or asyncio loop
- extract only selected fields for plots
- maintain bounded ring buffers
- decimate or drop visualization samples under load
- emit GUI-friendly events and snapshots

Start with numeric scalar leaves for plotting. Complex structs, sequences,
unions, strings, and arrays should appear in the sample inspector first, then
graduate into plotting only when the UX and extraction rules are clear.

Reference example guidance:

- Keep raw DynamicData reading separate from field extraction and plotting.
- Keep declarative subscription requests, sample envelopes, and bounded caches
  in `subscriptions.py`; keep Connext DynamicData topic/reader creation in
  `rti_subscriptions.py`.
- Show selected-field extraction as a reusable API rather than burying it inside
  chart code.
- Keep field-path parsing and value classification DDS-free in `extractors.py`;
  extract from mapping/object/DynamicData-like values but do not create readers
  or plot series there.
- Use `FieldCatalog` metadata to drive field pickers and initial plot
  eligibility, then use `extractors.py` only for sample values that arrive from
  active subscriptions.
- Keep plot buffers and UI snapshots DDS-free in `plotting.py`; consume
  `WorkspacePlotDefinition` and `SampleEnvelope` values, not readers or
  DynamicData handles.
- Keep workspace-to-runtime orchestration DDS-free in `data_session.py`; use
  `TopicSubscriptionClient` implementations for transport, and publish
  `DataSessionSnapshot` values for UI code.
- Keep backpressure visible through dropped, skipped, and decimated sample
  counters.

### 5. Workspace Persistence Layer

Owns declarative state that can survive restarts. Persist selections and
configuration, not live DDS handles.

Persist:

- domains
- service instances and admin domains
- selected topics
- selected field paths
- plot definitions and history windows
- recent recording databases and output folders
- XML type search paths
- UI layout preferences

Do not persist:

- DomainParticipant, Topic, DataReader, Requester, or DynamicData objects
- transient endpoint GUIDs as the primary identity for user settings
- rolling sample buffers unless the user explicitly exports them

Version the workspace schema from the first draft.

Keep workspace persistence in `workspace.py` DDS-free. It can store
`TopicSelectionState`, `TopicSubscriptionRequest`, field paths, plot definitions,
XML type paths, and recent files. It must not store participants, readers,
requesters, DynamicData objects, or sample buffers.

Example:

```json
{
  "version": 2,
  "name": "Robot Workspace",
  "domains": [0, 54],
  "topic_selections": {
    "include_internal": false,
    "selections": [
      {
        "domain_id": 0,
        "topic_name": "Position",
        "type_name": "Position",
        "selected_fields": ["lat", "lon"],
        "plot_fields": ["lat", "lon"],
        "enabled": true
      }
    ]
  },
  "subscriptions": [
    {
      "domain_id": 0,
      "topic_name": "Position",
      "type_name": "Position",
      "selected_fields": ["lat", "lon"],
      "max_samples": 1024
    }
  ],
  "plots": [
    {
      "name": "Position",
      "history_seconds": 60,
      "max_points": 2000,
      "series": [
        {"domain_id": 0, "topic_name": "Position", "type_name": "Position", "field_path": "lat"},
        {"domain_id": 0, "topic_name": "Position", "type_name": "Position", "field_path": "lon"}
      ]
    }
  ],
  "xml_type_paths": ["xml_types/Position.xml"],
  "recent_files": ["recordings/session_001"],
  "metadata": {}
}
```

Service launch/admin preferences can be added as a later versioned extension,
for example:

```json
{
  "services": {
    "recording": [
      {"name": "Recorder", "admin_domain": 54, "monitoring_domain": 54}
    ]
  }
}
```

## UI Model

### Record Tab

Primary workflows:

- select or launch a Recording Service configuration
- view service state, sessions, topic groups, and throughput
- pause, resume, tag, and shutdown
- open recent recording databases

The tab should use the service facade only. It should not parse monitoring
DynamicData directly.

### Replay Tab

Primary workflows:

- select a recording database
- select replay service target
- choose topic/session/time window
- set replay rate and loop mode
- pause, resume, and shutdown replay

Replay is service orchestration. Visualization is independent: replay publishes
data back into DDS, and the Topics or Plots tabs subscribe to that data when the
operator chooses to inspect it.

### Convert Tab

Primary workflows:

- select an input recording
- choose output format and destination
- run or cancel conversion jobs
- inspect job logs and output files

Treat Converter Service as a batch job facade first. If later deployments keep a
Converter Service running continuously with admin and monitoring enabled, it can
share the same service interfaces.

### Topics Tab

Primary workflows:

- browse discovered DDS topics
- inspect type availability and QoS match status
- subscribe and unsubscribe
- inspect recent samples as structured data
- select fields for plotting

Discovery should show explicit states such as discovered, type available,
reader created, matched, and receiving. Empty charts are often QoS or matching
problems, so the UI should expose those diagnostics early.

### Plots Tab

Primary workflows:

- create plot panels from selected numeric fields
- pause and resume plot updates
- adjust history window and decimation settings
- save plot layouts into the workspace

Use bounded buffers and selected field extractors. Do not walk entire
DynamicData samples for every chart on every sample.

## Threading and Event Flow

```text
DDS runtime thread / rti.asyncio loop
    -> service monitoring readers
    -> discovery readers
    -> DynamicData subscription readers
    -> internal events queue
    -> app core state reducer
    -> immutable snapshots / UI events
    -> Dear PyGui frame loop drains queue and redraws widgets

Dear PyGui callbacks
    -> command queue
    -> service facade or subscription manager
    -> result events
    -> app state update
```

Rules:

- Dear PyGui callbacks must not block on DDS discovery, request/reply, file
  conversion, or database operations.
- DDS listeners, if used at all, should only enqueue small events.
- Admin commands should be serialized per service instance so one request/reply
  exchange is active for a given requester at a time.
- Long-running converter/replay tasks should emit progress and logs through the
  same app event path as DDS updates.

## QoS and Type Strategy

- Reuse the starter kit QoS libraries where possible.
- Let Replay Service configurations reference the same QoS profiles as the live
  system so replayed writers can match current readers.
- Keep XML DynamicData generation tied to the active `$NDDSHOME` and validate
  the generated type stamp before startup.
- Treat generated XML type files as local artifacts, not hand-maintained source.
- Support additional user type search paths for application IDL/XML.

## Phased Path Forward

### Phase 1: Document and Isolate the Core

- Keep the existing tkinter GUI working as the reference app.
- Add v2-owned `app_core` models, protocols, and fakes with no DDS or GUI
  imports.
- Document the public API for each new layer before adding the Connext adapter
  behind it.
- Define the versioned workspace schema.
- Add unit tests for workspace load/save/migration.

### Phase 2: Discovery and Type Catalog

- Add built-in topic discovery.
- Build a catalog that separates discovered topics from subscribable topics.
- Add field metadata extraction from DynamicData types.
- Add tests for topic filtering and field path generation.

### Phase 3: RS GUI v2 Shell

- Create a minimal rs_gui_v2 app with Record, Replay, Convert, Topics, and
  Plots tabs.
- Wire it to mocked app-core snapshots before DDS integration.
- Add a single real Recording Service status panel through the service facade.

### Phase 4: Live Data Browser and Plotting

- Add DynamicData subscription management for selected topics.
- Add sample inspector and scalar numeric plotting.
- Add backpressure, bounded buffers, and decimation.
- Persist selected topics, fields, and plot layouts.

### Phase 5: Replay and Convert Workflows

- Add Replay Service orchestration and replay configuration presets.
- Add Converter Service job execution, log capture, and recent output tracking.
- Validate the replay-to-plot workflow with live E2E tests.

## Testing Strategy

- Keep current rs_gui_v1 controller and monitor tests as an external regression
  baseline, not as dependencies of rs_gui_v2.
- Add pure unit tests for workspace schema, reducers, field paths, extractors,
  buffers, and topic filtering.
- Add import-boundary tests proving pure layers do not import `rti.*`, GUI
  libraries, or rs_gui_v1 implementation modules.
- Add focused adapter tests that are allowed to import `rti.*` and demonstrate
  one Connext API area at a time.
- Add GUI tests around app-state snapshots rather than live DDS where possible.
- Add focused live E2E tests for Recording Service, Replay Service, Converter
  job execution, and replay-to-plot workflows.
- Use behavioral oracles for pause/resume and replay, such as sample counts or
  emitted samples, rather than only top-level service state text.

## Main Risks

- Topic discovery does not guarantee local type usability.
- QoS mismatch can look like missing data unless diagnostics are visible.
- High-rate DynamicData plotting can create Python object churn and GUI lag.
- Replay and live visualization can become coupled if the architecture lets the
  Replay tab own subscriptions.
- Persisting runtime DDS identities will make workspaces brittle.

## Recommendation

The best path forward is to create rs_gui_v2 as a new shell over a
service-oriented DDS app core. Start with v2-owned interfaces, state models, and
fakes; then add narrow Connext adapters that make RTI API usage clear and
testable. After Service Admin and monitoring are proven, add discovery,
DynamicData subscriptions, plotting, and workspace persistence before expanding
Replay and Converter workflows.

That gives us a usable migration path: the existing tkinter app remains a
working reference while the new architecture grows in tested, replaceable
layers. It also gives Connext end users a readable example where each RTI API
area can be studied independently.