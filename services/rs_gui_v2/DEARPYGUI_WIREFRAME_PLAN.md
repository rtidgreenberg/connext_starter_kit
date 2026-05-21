# Dear PyGui Wireframe Approval Plan

## Purpose

Before implementing the Dear PyGui interface, we will create mock wireframes for
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
- Validate persisted selections and restore behavior before implementing the
  workspace layer.

## Wireframe Package

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
- What replay timing controls are needed in v1?
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

- Is Converter Service treated as a running service or as a batch job in v1?
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
- What is the minimum useful plot configuration for v1?
- How should high-rate topics communicate dropped/decimated samples?

### 7. Workspace and Restore Flow

Purpose: Validate persistence before implementing schema details.

Must show:

- current workspace name/path
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
- Replay and Convert workflows are approved at a v1 scope level.
- Topic discovery, sample inspection, and plotting handoff are approved.
- Workspace save/restore behavior is approved.
- Error, empty, loading, and degraded states are represented.

## Deliverable Format

Use the fastest format that lets us review the workflow clearly:

- Markdown wireframe sketches in this repo for structure and annotations.
- Optional static images if visual layout needs more fidelity.
- Optional clickable prototype later if the layout becomes ambiguous.

The first pass should be low-fidelity and text-heavy enough to revise quickly.
After approval, we can build Dear PyGui screens against mocked app-core state
before connecting live DDS.