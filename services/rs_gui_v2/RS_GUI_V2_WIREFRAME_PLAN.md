# RS GUI v2 Wireframe Approval Plan

## Purpose

Before implementing the rs_gui_v2 interface, we will create mock wireframes for
review and approval. The wireframes should validate the operator workflow,
screen layout, command feedback, data exploration model, and persistence flow
without committing to widget code too early.

The goal is not visual polish. The goal is to agree on what the tool should feel
like to operate before we build it.

## Wireframe Principles

- Mock the full workflow before implementing tabs.
- Prefer realistic DDS and RTI service states over generic placeholder content.
- Show command lifecycle states: requested, acknowledged, observed, failed.
- Show topic lifecycle states: discovered, type available, reader created,
  matched, receiving, unresolved, ambiguous.
- Show empty, loading, error, and degraded states for each major screen.
- Treat internal `rti/*` topics as hidden by default, with an advanced toggle.
- Validate persisted selections and restore behavior before implementing the GUI
  restore flow.

## First-Pass Wireframes

These sketches are intentionally low fidelity. They define information shape,
state vocabulary, and app-core API usage before any Dear PyGui widgets are
implemented.

### 1. App Shell

Purpose: Keep global Connext, workspace, and service health visible while tabs
focus on one workflow at a time.

```text
+------------------------------------------------------------------------------+
| Workspace: Robot Run 03 *        Domain: 0, 54      Connext: 7.6.0 / OK      |
| License: OK                       XML Types: current   Services: 1 degraded  |
+------------------------------------------------------------------------------+
| Record | Replay | Convert | Topics | Plots | Workspace                       |
+------------------------------------------------------------------------------+
|                                                                              |
| Active tab content                                                           |
|                                                                              |
|                                                        +-------------------+ |
|                                                        | Inspector         | |
|                                                        | Context details   | |
|                                                        | Selected object   | |
|                                                        | Diagnostics       | |
|                                                        +-------------------+ |
+------------------------------------------------------------------------------+
| 13:12:03 Monitoring active on domain 0 | Last command: Pause acknowledged    |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- `AppState` for lifecycle, feature availability, errors, and tab-level summary
  state.
- `WorkspaceDocument` for workspace name, unsaved state, domains, recent files,
  and persisted selections.
- Service snapshots from `ServiceMonitoringFacade` for global service health.
- Events from `AppRuntime` queues for the bottom event log.

States to show:

| State | Shell presentation |
| --- | --- |
| Starting | global status shows runtime startup and disabled tab commands |
| Ready | Connext install, license, workspace, and service health are visible |
| Degraded | yellow status for stale XML types, missing service, or partial discovery |
| Failed | top status surfaces the failure and bottom log keeps details |
| Unsaved | workspace title gains `*` and save actions become active |

Approval focus:

- Use a tab-first app with a persistent top status strip and bottom event log.
- Keep the right-side inspector optional but reserve the layout space in the
  first shell so Record, Topics, and Plots can share details behavior.
- Do not put DDS controls in the shell; route actions through the active tab.

### 2. Record Tab

Purpose: Provide the first operator workflow for Recording Service control,
monitoring, command feedback, and tagging.

```text
+------------------------------------------------------------------------------+
| Recording target: [deploy_8f4f2a1c v] Admin domain: 0  Monitoring domain: 0   |
| Readiness: request+reply matched State: RUNNING       Observed: STARTED       |
+------------------------------------------------------------------------------+
| Process selector                                                             |
| * deploy_8f4f2a1c  local pid 4218  dev-host  RUNNING  cpu 2%  mem 180 MB     |
|   deploy_91b0aa77  external pid 5110 lab-host RUNNING  stale 12s conflict    |
+------------------------------------------------------------------------------+
| [Pause] [Resume] [Tag...] [Shutdown]       Tag: e2e_tag_beta [Apply Tag]      |
+------------------------------------------------------------------------------+
| Command History                         | Monitoring Summary                 |
| id        command   reply       observed| sessions: 1 active                 |
| pause-21  Pause     OK          PAUSED  | topics: 4 discovered               |
| resume-22 Resume    OK          RUNNING | throughput: 1.2 MB/s               |
| tag-23    Tag       TIMEOUT     STARTED | last event: rollover not detected   |
+------------------------------------------------------------------------------+
| Sessions / Topic Groups                                                     |
| session      state      samples      bytes       storage                     |
| default      recording  12034        48 MB       sqlite                      |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- `ServiceInstanceRef` for service kind, name, admin domain, and monitoring
  domain.
- `AdminReadiness` for request/reply matching and service availability.
- `ServiceCommandOutcome` for acknowledged, rejected, timeout, and failed
  command results.
- `ServiceStateSnapshot` and `MonitoringSnapshot` values for observed service
  state, topic groups, sessions, throughput, and events.

Command lifecycle display:

| Lifecycle | Meaning | UI treatment |
| --- | --- | --- |
| Requested | command enqueued or sent | pending row with request id |
| Acknowledged | Service Admin reply returned OK | reply column is OK |
| Rejected | Service Admin reply rejected the action | row shows reason and resource |
| Timeout | no reply before timeout | row stays visible with retry action |
| Observed | monitoring state catches up | observed column updates independently |

States to show:

| State | Record tab presentation |
| --- | --- |
| No service | service selector empty, commands disabled, setup hint in inspector |
| Not ready | readiness shows missing request or reply match |
| Duplicate service name | selector shows a uniqueness conflict for the same name/admin domain and Service Admin commands remain disabled |
| Running | pause/tag/shutdown active, resume inactive |
| Paused | resume/tag/shutdown active, pause inactive |
| Stale XML | monitoring unavailable with XML type diagnostic |
| Command failed | command history row stays visible with reason and resource path |

Approval focus:

- Keep requested, acknowledged, and observed state separate.
- Show admin and monitoring domains next to the selected service.
- Show when more than one physical service process appears to match the same
  logical `ServiceInstanceRef`; do not silently pick one.
- Enforce unique service names for each service kind and admin domain so a
  Service Admin control request has exactly one intended target.
- Keep tag entry on the primary screen because tagging is a core Recording
  Service operator action.

Service-name uniqueness invariant:

- A controllable service target is unique by service kind, service name, and
  admin domain. Monitoring domain and config path are evidence for diagnostics,
  but they do not make a Service Admin request uniquely addressable.
- GUI-created services have two names: an editable display label for operators
  and a generated, session-scoped control name used by the actual service
  process. Build the control name from a sanitized label plus a session GUID
  suffix, for example `recording_service_8f4f2a1c`, and generate a new suffix
  whenever the GUI creates or restarts the service process.
- The session GUID must be part of the real service name used in the service
  configuration and Service Admin target. A UUID stored only in GUI metadata is
  not enough to make DDS control messages uniquely targetable.
- Store DDS discovery identity for each observed candidate: hostname,
  application/process id when available, participant key/GUID, participant name,
  and last-seen timestamps. These fields let the UI distinguish physical
  process instances and detect whether the same process is still present after a
  refresh.
- For Connext Python discovery, read participant system properties from
  `ParticipantBuiltinTopicData.property`: `dds.sys_info.hostname` and
  `dds.sys_info.process_id`. Obtain that data through
  `DomainParticipant.discovered_participants()` plus
  `discovered_participant_data(handle)`, or through `participant_reader` samples.
- For RTI Infrastructure Services, also correlate service monitoring config
  fields such as `application_guid`, `process.id`, and `host.name` when present.
- Discovery identity is evidence, not the normal Service Admin address. If two
  candidates advertise the same service kind, service name, and admin domain,
  their host/app ids make the conflict diagnosable but do not make pause/resume/
  tag/shutdown uniquely targetable through the service-name control path.
- GUI-created Recording, Replay, and Converter Service launch flows must refuse
  to start a service whose kind/name/admin-domain tuple is already active or
  reserved in the workspace.
- If the operator renames the display label, keep the running control name
  unchanged until the service is explicitly restarted/reconfigured. The restart
  receives a new session GUID and therefore a new unique control name.
- Workspace restore must validate persisted service names before enabling
  controls. Restored GUI launch intent does not reuse the previous session GUID;
  it generates a fresh control name for newly launched processes. Any old
  process still advertising the prior control name is shown as a discovered
  external candidate.
- Discovered external duplicates are allowed to appear in the candidate list for
  diagnosis and local-process cleanup, but Service Admin pause/resume/tag/
  shutdown controls stay disabled until the duplicate name conflict is resolved.

Duplicate tracking model:

- Treat `ServiceInstanceRef` as the logical operator target: service kind,
  service name, admin domain, monitoring domain, and configuration paths.
- Track physical candidates separately with launch/discovery evidence: local
  launch id, local pid when the GUI started the process, command/config path,
  observed admin match counts, discovery participant key/GUID, hostname,
  application/process id when available, monitoring sample source details,
  process metrics, host/user fields if available, and last observed time.
- Mark a service target ambiguous when a single logical reference has more than
  one live candidate or when one admin command correlation receives multiple
  service replies.
- Disable normal pause/resume/tag/shutdown controls for ambiguous targets until
  the service-name conflict is resolved. Selecting a candidate can enable local
  process cleanup controls, but it cannot make a non-unique Service Admin target
  safe.
- Prefer our own launch id for locally started services; use DDS discovery and
  monitoring evidence for externally started services because pid alone is not
  portable and can be reused.

Candidate-level control model:

- Application-level controls send Service Admin commands to the unique
  session-GUID service name. Process-level controls use stored host/pid evidence
  to terminate a local process only as an explicit fallback.
- Record and Replay tabs should both expose a target selector/dropdown plus an
  expandable candidate table. The selected candidate drives the visible stats,
  readiness, command history filter, and enabled controls.
- The compact selector should show the operator label and unique control name;
  the expanded list should show every live or recently-stale candidate with
  source, host, pid, state, age, and conflict/confidence indicators.
- Show each candidate process as a selectable row under the logical service:
  launch id, pid when local, host if known, application/process id when
  available, participant key/GUID, config path, admin domain, monitoring domain,
  observed state, last telemetry time, and confidence.
- Selecting a candidate scopes the command panel to that candidate's known
  control paths.
- `Stop local process` is available only for a process the GUI launched or can
  safely identify on the local host; it uses the local process handle/pid and is
  distinct from an RTI Service Admin shutdown request.
- `Shutdown via Service Admin` is available for a candidate only when the
  service kind, service name, and admin domain are unique enough that one
  request is expected to produce one reply. If multiple services share that
  tuple, the UI must treat it as a uniqueness violation and keep Service Admin
  commands disabled.
- Normal shutdown uses a two-layer escalation flow. First send `Shutdown via
  Service Admin` and wait for the reply plus monitoring/discovery disappearance.
  If the command is rejected, times out, or the process remains alive after the
  grace period, expose `Terminate local process` as a guarded fallback for
  candidates with a verified local process handle.
- The fallback should be visually and semantically separate from graceful
  shutdown, require an explicit confirmation, and show the reason it became
  available: admin timeout, rejected command, stale monitoring, or process still
  alive after shutdown acknowledgment.
- The fallback must revalidate the local pid/process handle immediately before
  signaling the process, because pids can be reused and discovery information can
  become stale.
- A discovered `dds.sys_info.process_id` can seed that fallback only when the
  hostname matches the local host and the launch/process-control adapter can
  verify the process is still the expected executable/session. Do not publish a
  generic DDS "kill pid" command as the normal shutdown path.
- If an emergency broadcast recovery action is ever added, it must be separate
  from normal service controls and show the expected candidate count and reply
  count before sending.
- A command history row should record the selected candidate id, the logical
  service key, the resource path, the expected reply count, the actual reply
  count, and any escalation from graceful shutdown to local process termination
  so duplicate and failure recovery remains auditable.

### 3. Replay Tab

Purpose: Treat replay as service orchestration while keeping replayed data
inspection in Topics and Plots.

```text
+------------------------------------------------------------------------------+
| Replay target: [replay_service_d34a910f v] Admin domain: 0 State: STOPPED     |
+------------------------------------------------------------------------------+
| Process selector                                                             |
| * replay_service_d34a910f local pid 4332 dev-host STOPPED db: test_recording |
|   replay_service_2c7718bb ext   pid 5175 lab-host RUNNING conflict           |
+------------------------------------------------------------------------------+
| Recording DB: services/rs_gui_v1/test/test_recording        [Browse]          |
| Time window: [start tag: e2e_tag_alpha] -> [end tag: e2e_tag_beta]            |
| Rate: 1.0x      Loop: off      Topic filter: /Robot/*                         |
+------------------------------------------------------------------------------+
| [Start Replay] [Pause] [Resume] [Stop] [Shutdown]                             |
+------------------------------------------------------------------------------+
| Progress                                      | DDS Visualization             |
| status: configured                           | Topics tab will subscribe to   |
| current time: --                             | replayed DDS topics.           |
| emitted samples: --                          | [Open Topics with filter]      |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- Future Replay Service facade DTOs should mirror the service admin pattern:
  service ref, command request, command outcome, and observed state.
- `WorkspaceDocument.recent_files` provides recent recording paths.
- `TopicSelectionState` and `DataSessionCoordinator` remain the visualization
  path after replay publishes samples into DDS.

States to show:

| State | Replay tab presentation |
| --- | --- |
| No database | start disabled, input path highlighted |
| Configured | start enabled, progress idle |
| Running | pause/stop active, rate and loop locked or explicitly mutable |
| Paused | resume/stop active, progress retained |
| Complete | progress summary and open Topics/Plots actions visible |
| Service unavailable | command controls disabled, admin readiness diagnostic shown |
| Duplicate replay service | multiple candidates shown with database/config evidence before commands are enabled |

Approval focus:

- Keep replay configuration inline for MVP; avoid wizard flow until the required
  timing controls are clearer.
- Represent replay-to-plot as a handoff to Topics/Plots, not as direct plot
  ownership inside Replay.
- Replayed samples become normal DDS topic data once Replay Service publishes
  them; Topics and Plots should inspect/plot them through the same subscription
  pipeline used for live publishers.
- Reuse the same duplicate-candidate model as Record so accidental multiple
  Replay Service instances do not receive unintended commands.
- Keep tags and time windows visible because they connect to Recording Service
  workflows.

Initial implementation note:

- The current v2 shell renders a mocked Replay tab that captures the approved
  information shape and emits `replay.*` command intents only. Live Replay
  Service control, command history, and replay-to-topic E2E validation are still
  later phases.
- The GUI session now handles mocked `replay.*` commands through a controller so
  selecting a Replay target and changing start/pause/resume/stop/shutdown state
  are visible before live Service Admin wiring is added.

### 4. Convert Tab

Purpose: Present conversion as a bounded job workflow with clear validation,
logs, and recent outputs.

```text
+------------------------------------------------------------------------------+
| Conversion Job                                                               |
+------------------------------------------------------------------------------+
| Input DB:  recordings/run_003                              [Browse]           |
| Output:    output/run_003_json                            [Browse]           |
| Format:    JSON            Preset: selected topics only                       |
| Topics:    /Robot/Pose, /Robot/Velocity                     [Edit]            |
+------------------------------------------------------------------------------+
| [Run] [Cancel] [Retry]                                                        |
+------------------------------------------------------------------------------+
| Job Status                         | Logs                                     |
| state: running                     | 13:14:10 validated input DB              |
| progress: 42%                      | 13:14:11 opened output directory         |
| current topic: /Robot/Pose         | 13:14:12 writing JSON records            |
+------------------------------------------------------------------------------+
| Recent Outputs                                                               |
| output/run_002_json   JSON   complete   [Open] [Inspect]                     |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- Future converter job facade should expose job request, validation result,
  progress snapshot, log entries, and output references.
- `WorkspaceDocument.recent_files` and future metadata hold recent inputs and
  outputs.
- Service admin/monitoring facades can be reused later if deployments treat
  Converter Service as a continuously running service.

States to show:

| State | Convert tab presentation |
| --- | --- |
| Empty | input and output pickers visible, run disabled |
| Invalid input | validation row shows missing path or unreadable database |
| Ready | run enabled after input/output/format validation |
| Running | cancel active, logs stream, controls protected from accidental edits |
| Failed | failed log row visible with retry action |
| Complete | recent output row added with open and inspect actions |

Approval focus:

- Treat conversion as a batch job in the MVP.
- Keep logs visible in the primary tab; do not hide them behind a modal.
- Keep converted output inspection separate from live DDS visualization.

### 5. Topics Tab

Purpose: Make discovery, type availability, subscription state, and sample
inspection understandable before plotting. The source may be a live publisher or
Replay Service republishing recorded samples onto DDS topics.

```text
+------------------------------------------------------------------------------+
| Domain: [0] Search: [pose] Type: [all] Status: [all] [ ] Show internal topics |
+------------------------------------------------------------------------------+
| Topics                                                                       |
| topic             type            writers readers state          action       |
| /Robot/Pose       Robot::Pose     1       0       receiving      [Unsub]      |
| /Robot/Velocity   Robot::Velocity 1       0       type_available [Subscribe]  |
| /Robot/Debug      DebugType       1       0       unresolved     [Resolve]    |
| DCPSPublication   builtin         0       1       internal       hidden       |
+------------------------------------------------------------------------------+
| Sample Log                         | Sample Inspector                         |
| t=13:15:01 valid rank=0            | metadata: source_ts=13:15:01             |
| t=13:15:02 valid rank=0            | pose                                     |
| t=13:15:03 invalid disposed        |   x: 12.4        [Plot]                  |
|                                    |   y: 7.9         [Plot]                  |
|                                    |   label: "base"                         |
+------------------------------------------------------------------------------+
| Diagnostics: matched writer, XML type loaded from xml_types/Robot.xml         |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- `TopicDiscoveryFacade`, `TopicInventory`, and `DiscoveredTopic` for topic
  rows and endpoint counts.
- `TypeCatalog` and `TypeResolution` for resolved, missing, and ambiguous type
  states.
- `FieldCatalog` and `FieldDescriptor` for the field tree and plottable numeric
  leaves.
- `DataSessionSnapshot` for subscription states and recent sample envelopes.

Topic lifecycle display:

| Lifecycle | Meaning | UI treatment |
| --- | --- | --- |
| Discovered | endpoint metadata exists | row visible, subscribe disabled until type known |
| Type available | local DynamicType can be loaded | subscribe enabled |
| Reader created | subscription request accepted | state shown while waiting for matches/samples |
| Matched | reader has matching writer metadata | diagnostic row shows match count |
| Receiving | valid or invalid samples are arriving | sample log and inspector active |
| Unresolved | type missing locally | row action points to XML type setup |
| Ambiguous | multiple type candidates exist | row action opens candidate chooser |

States to show:

| State | Topics tab presentation |
| --- | --- |
| No discovery | empty table with domain/setup diagnostic |
| Internal hidden | internal count appears beside show-internal toggle |
| QoS no match | row visible with no-match diagnostic and empty sample log |
| Invalid samples | sample log marks invalid and inspector shows metadata only |
| Unsupported field | field tree marks non-plottable struct/sequence/text leaves |

Approval focus:

- Use topic-first browsing for MVP because persisted selections are topic/type
  based.
- Keep discovery, sample log, and sample inspector in one screen so no-data
  diagnostics are visible.
- Make plotting a field action from the inspector, then manage layout in Plots.

### 6. Plots Tab

Purpose: Show selected numeric fields with bounded memory, explicit time axis,
and visible backpressure counters for either live DDS samples or replayed DDS
samples.

```text
+------------------------------------------------------------------------------+
| Plot: Pose                         Time: source timestamp  History: 60 s      |
| [Pause] [Resume] [Clear]           Decimation: 100 ms      Saved: yes         |
+------------------------------------------------------------------------------+
| Series                                                                       |
| color  topic          field     points accepted skipped dropped decimated     |
| blue   /Robot/Pose    pose.x    300    12000    2       40      810           |
| green  /Robot/Pose    pose.y    300    12000    0       40      810           |
+------------------------------------------------------------------------------+
|                                                                              |
|  y                                                                           |
|  |                      x x x                                                 |
|  |              x x x                                                         |
|  |      x x x                                                                 |
|  +---------------------------------------------------------------- time       |
|                                                                              |
+------------------------------------------------------------------------------+
| Diagnostics: nonnumeric samples skipped for pose.x at t=13:17:20             |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- `WorkspacePlotDefinition` and `WorkspacePlotSeries` for persisted plot
  intent.
- `PlotBufferSnapshot` and `PlotSeriesSnapshot` from `DataSessionSnapshot` for
  UI rendering.
- `PlotUpdateResult` counters for skipped, dropped, and decimated diagnostics.

States to show:

| State | Plots tab presentation |
| --- | --- |
| Empty | add-from-Topics action and saved layouts list |
| Running | plot panels update from snapshots on the UI frame loop |
| Paused | incoming samples may still cache, plot panel stops advancing |
| Missing type/topic | plot panel remains with unresolved badge and no reader |
| Invalid values | skipped counter and last message stay visible |
| High rate | dropped and decimated counters visible per series |

Approval focus:

- Build plot selection in Topics and manage plot layout in Plots.
- Keep live and replayed visualization source-agnostic: once samples arrive on a
  DDS topic, the same `DataSessionCoordinator`, sample cache, and plot buffers
  should handle them.
- Start with numeric scalar leaves only.
- Show backpressure counters in the normal view, not only in diagnostics.

### 7. Workspace and Restore Flow

Purpose: Make persisted intent and degraded restore behavior explicit before GUI
implementation.

```text
+------------------------------------------------------------------------------+
| Workspace: Robot Run 03 *                         Path: workspaces/run03.json |
| [Save] [Save As] [Open] [Reset]                                             |
+------------------------------------------------------------------------------+
| Restore Summary                                                              |
| domains: 0, 54                 XML paths: xml_types/Robot.xml                |
| services: deploy/admin=0       recent recordings: 3                          |
| topics: 2 selected             plots: 1 saved                                 |
+------------------------------------------------------------------------------+
| Selected Intent                                                              |
| kind     name/topic       status            action                            |
| service  deploy           ready             [Reconnect]                       |
| topic    /Robot/Pose      type available    [Subscribe]                       |
| topic    /Robot/Debug     unresolved type   [Locate XML]                     |
| plot     Pose             waiting samples   [Open Plot]                      |
+------------------------------------------------------------------------------+
| Unsaved changes: plot history changed from 30 s to 60 s                      |
+------------------------------------------------------------------------------+
```

Primary app-core inputs:

- `WorkspaceDocument` for saved domains, subscriptions, topics, plot
  definitions, XML type paths, recent files, and metadata.
- `TypeResolution`, `TopicSubscriptionState`, and service readiness snapshots
  for restore status.
- `save_workspace` and `load_workspace` for deterministic JSON persistence.

States to show:

| State | Workspace presentation |
| --- | --- |
| Clean | title has no marker, save disabled |
| Unsaved | title marker and change summary visible |
| Missing topic | selected intent row shows waiting for discovery |
| Missing type | row offers locate XML action |
| Reconnect needed | restored service/topic intent requires explicit operator action |
| Load failed | file error shown without mutating current runtime state |

Approval focus:

- Restore intent automatically, but require confirmation before reconnecting to
  services or subscribing to topics.
- Preserve missing topic/type rows so users can repair stale workspaces.
- Do not persist runtime DDS handles, transient endpoint GUIDs, or sample
  buffers.

## Review Checklist

The first-pass wireframes above should be reviewed against this checklist before
we approve the Dear PyGui implementation scope.

### 1. App Shell

Purpose: Validate the overall navigation model.

Must show:

- top status area with active domain, Connext install/status, license status,
  and service health summary
- primary tabs or navigation for Record, Replay, Convert, Topics, Plots, and
  Workspace/Settings
- bottom event log/status strip
- right-side contextual inspector or details area, if we choose that layout
- global error and notification pattern

Approval questions:

- Is this a tab-first app or a dashboard-first app?
- Are Record, Replay, Convert, Topics, and Plots the right top-level sections?
- Where should persistent service/domain status live?

### 2. Record Tab

Purpose: Validate the first operational vertical slice.

Must show:

- selected Recording Service instance
- admin domain and monitoring domain
- service state and readiness indicators
- pause, resume, tag, and shutdown controls
- command history with request id, reply status, and observed state
- monitoring summaries for sessions, topic groups, topics, and throughput
- tag entry and recent tag history
- unavailable service and stale XML type states

Approval questions:

- Is command feedback clear enough for live operations?
- Do we need a shallow control view, a diagnostic detail view, or both?
- Which monitoring fields are essential on the first screen?

### 3. Replay Tab

Purpose: Validate replay orchestration before implementation.

Must show:

- selected Replay Service instance
- input recording/database selection
- replay state, progress, rate, loop mode, and time window
- start, pause, resume, stop, shutdown, and optional jump controls
- topic/session selection for replay configuration
- link or action to inspect replayed DDS data in Topics/Plots

Approval questions:

- Should replay be configured inline or through a wizard-like flow?
- What replay timing controls are needed in the MVP?
- How should replay-to-plot be represented without coupling the tabs?

### 4. Convert Tab

Purpose: Validate conversion as a job workflow.

Must show:

- input recording/database picker
- output format and output directory
- conversion preset selection
- run, cancel, retry controls
- job status, logs, and recent outputs
- invalid path/configuration states

Approval questions:

- Is Converter Service treated as a running service or as a batch job in the MVP?
- Which output formats and presets matter first?
- Where should conversion logs and output browsing live?

### 5. Topics Tab

Purpose: Validate DDS discovery and sample inspection workflows.

Must show:

- discovered topics table or tree
- search and filters by domain, topic, type, endpoint status, and internal topic
  visibility
- type status: resolved, unresolved, ambiguous
- match/QoS status indicators
- subscribe and unsubscribe actions
- sample log preview
- selected sample inspector with metadata and structured field tree
- field picker for plotting

Approval questions:

- Should topic browsing be topic-first, participant-first, or service-first?
- Is the split between discovery, sample log, and sample inspector clear?
- What diagnostics are required when a topic has writers but no samples arrive?

### 6. Plots Tab

Purpose: Validate field selection and visualization before plotting code.

Must show:

- plot panels with selected topic/field series
- field picker handoff from Topics
- time axis mode: receive time, source time, or sample index
- history window, decimation, pause/resume, and clear controls
- missing/invalid value behavior
- saved plot layout indicator

Approval questions:

- Should plots be built in the Topics tab, Plots tab, or both?
- What is the minimum useful plot configuration for the MVP?
- How should high-rate topics communicate dropped/decimated samples?

### 7. Workspace and Restore Flow

Purpose: Validate persistence before implementing schema details.

Must show:

- current workspace name/path
- save and open controls dispatch shell commands rather than reaching into file
  persistence directly
- saved domains, service targets, selected topics, selected fields, and plots
- recent recordings and conversion outputs
- restore behavior when topics or types are missing
- unsaved changes indicator
- save, save as, open, and reset actions

Approval questions:

- What should be restored automatically on startup?
- What should require user confirmation before reconnecting/subscribing?
- How should missing topics or stale type definitions appear?

## Approval Gate

UI implementation may begin only after the wireframe package answers these
questions:

- The top-level navigation model is approved.
- Record tab command feedback is approved.
- Replay and Convert workflows are approved at an MVP scope level.
- Topic discovery, sample inspection, and plotting handoff are approved.
- Workspace save/restore behavior is approved.
- Error, empty, loading, and degraded states are represented.

Current first-pass status: drafted for review, not yet approved.

## Deliverable Format

Use the fastest format that lets us review the workflow clearly:

- Markdown wireframe sketches in this repo for structure and annotations.
- Optional static images if visual layout needs more fidelity.
- Optional clickable prototype later if the layout becomes ambiguous.

The first pass should be low-fidelity and text-heavy enough to revise quickly.
After approval, we can build rs_gui_v2 screens against mocked app-core state
before connecting live DDS.