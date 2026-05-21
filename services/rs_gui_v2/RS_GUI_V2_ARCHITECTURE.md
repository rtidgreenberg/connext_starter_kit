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

## Target Shape

```text
services/rs_gui_v2/
+-- app_core/
|   +-- runtime.py              # DomainParticipant, QoS, XTypes, shutdown
|   +-- events.py               # App events and command/result DTOs
|   +-- state.py                # In-memory app state snapshots
|   +-- workspace.py            # Versioned persistence load/save/migrate
|   +-- discovery.py            # Built-in topic discovery catalog
|   +-- types.py                # XML DynamicData type registry
|   +-- subscriptions.py        # DynamicData reader lifecycle
|   +-- extractors.py           # Field-path compilation and value extraction
|   +-- plotting.py             # Ring buffers, decimation, series updates
|   +-- services/
|       +-- admin.py            # Shared Service Admin request/reply client
|       +-- monitoring.py       # Shared infrastructure service monitoring
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

### 2. Service Integration Layer

Owns operator-level service actions. It should hide DDS topic names, request
types, and monitoring topic schemas from the GUI.

Core concepts:

- `ServiceInstanceRef`: service kind, service name, admin domain, monitoring
  domain, and optional configuration paths.
- `ServiceAdminClient`: pause, resume, shutdown, tag, and service-specific
  commands using RTI Service Admin request/reply.
- `ServiceMonitorClient`: config, event, and periodic monitoring readers.
- `ServiceFacade`: cached service state plus commands and diagnostics.

Keep the control plane and monitoring plane separate. A command reply indicates
whether a service accepted and executed a command; monitoring topics describe
service state, metrics, and events. Those states do not always map one-to-one.

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

Filter internal topics by default, including `rti/*`, Service Admin topics, and
infrastructure monitoring topics. Let advanced users opt into seeing them.

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

Example:

```json
{
  "version": 1,
  "domains": [0, 54],
  "services": {
    "recording": [
      {"name": "Recorder", "admin_domain": 54, "monitoring_domain": 54}
    ],
    "replay": [
      {"name": "Replay", "admin_domain": 54, "monitoring_domain": 54}
    ]
  },
  "subscriptions": [
    {
      "domain": 0,
      "topic": "Position",
      "type_name": "Position",
      "fields": ["lat", "lon"],
      "view": "plot"
    }
  ],
  "plots": [
    {
      "title": "Position",
      "history_seconds": 60,
      "series": [
        {"domain": 0, "topic": "Position", "field": "lat"},
        {"domain": 0, "topic": "Position", "field": "lon"}
      ]
    }
  ],
  "recent_recordings": []
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
- Add `app_core` interfaces around the existing controller, monitor, and
  environment helpers.
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

- Keep current controller and monitor tests as the low-level DDS contract tests.
- Add pure unit tests for workspace schema, reducers, field paths, extractors,
  buffers, and topic filtering.
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
service-oriented DDS app core. Start by extracting interfaces and state models
from the proven Recording Service controller and monitor, then add discovery,
DynamicData subscriptions, plotting, and workspace persistence before expanding
Replay and Converter workflows.

That gives us a usable migration path: the existing tkinter app remains a
working reference while the new architecture grows in tested, replaceable
layers.