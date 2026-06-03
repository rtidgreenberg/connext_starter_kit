# rti_view Implementation Plan

## Goal

Build `rti_view` as a Dear PyGui desktop tool for inspecting one DDS field at a time.
V1 supports one Dear PyGui process, one selected domain, one topic, one field, and
one active field view with a Message Data / Plot toggle.

## Current State

- Architecture is documented in `ARCHITECTURE.md`.
- Python package scaffold lives in `tools/rti_view/rti_view/`.
- `fields.py` can enumerate nested DynamicType fields and read selected values using
  `sample[field_path]`.
- `discovery.py` has builtin-topic listener scaffolding based on `tools/rti_spy/rtispy.py`.
- `views/main_window.py` is a Dear PyGui placeholder and needs real wiring.

## Delivery Strategy

Build in thin vertical slices. Each phase should leave the tool runnable, even if
the UI only shows placeholders or fake data at first. Prefer DDS-free unit tests for
logic and small gated live tests for Connext behavior.

Test tiers:

- **Unit tests:** pure Python, fake DDS objects, no Connext participant required.
- **API smoke tests:** import/CLI/shell syntax checks and constructed DynamicType checks.
- **Live DDS tests:** optional/gated tests that create real DynamicData topics, writers,
  readers, and participants when Connext is available.
- **Manual GUI validation:** Dear PyGui visual checks after UI wiring.

## Phase 1 — Tool Packaging And Launch

### Slice 1.1 — Runner And Requirements

Deliverables:

- Add `tools/rti_view/requirements.txt` with `dearpygui` and RTI Python dependency notes.
- Add `tools/rti_view/run_rti_view.sh` to mirror RTI Spy's environment bootstrap style.
- Keep the shared repo virtual environment at `connext_dds_env/` unless a later decision
  creates per-tool virtual environments.

Tests:

- `bash -n tools/rti_view/run_rti_view.sh`
- Verify the runner resolves repo root from `tools/rti_view/`.
- Verify missing dependency messages are clear.

Completion gate:

- `./tools/rti_view/run_rti_view.sh --help` reaches the Python CLI help without path errors.

### Slice 1.2 — CLI Contract

Deliverables:

- Keep CLI options aligned with copied startup strings:
  - `--domain/-d`
  - `--topic/-t`
  - `--field/-f`
  - `--mode/-m text|plot`
  - `--history`
  - `--timeout`
- Rename internal `run_headless` terminology to `run_direct_view` everywhere.
- Add direct view argument validation: topic and field must both be present to skip browsing.

Tests:

- Unit-test `parse_args()` for interactive launch, direct launch, invalid mode, and partial
  topic/field input.
- API smoke: `python -m rti_view --help` with `PYTHONPATH=tools/rti_view`.

Completion gate:

- CLI help, interactive placeholder, and direct-view placeholder all route correctly.

## Phase 2 — Discovery Model

### Slice 2.1 — Participant Registry

Deliverables:

- Add `DiscoveredParticipant` model with:
  - participant key
  - participant name when available
  - IP/locator fallback
  - RTPS host/app IDs when available
- Add registry methods:
  - `add_participant()`
  - `participants()`
  - `participant_for_key()`
- Refresh participants with `participant.discovered_participants()` and
  `participant.discovered_participant_data(handle)`.

Tests:

- Unit-test participant registry add/update behavior.
- Unit-test display label fallback when participant name is missing.
- Fake-DDS test for participant data shape modeled after `tools/rti_spy/rtispy.py`.

Completion gate:

- UI can show process/participant rows from fake discovery snapshots.

### Slice 2.2 — Endpoint Grouping

Deliverables:

- Keep publication/subscription builtin listeners.
- Store writer endpoints with participant key, topic name, type name, DynamicType, and QoS.
- Add registry methods:
  - `writers_for_participant(participant_key)`
  - `writers_for_topic(topic_name)`
  - `topics_for_participant(participant_key)`
- Keep direct mode topic lookup independent of participant selection.

Tests:

- Unit-test endpoint grouping by participant key.
- Unit-test `writers_for_topic()` returns only writers, not readers.
- Unit-test multiple writers with same topic produce deterministic ordering and diagnostic input.

Completion gate:

- Fake discovery can drive `process -> writer topic` browsing without Connext.

### Slice 2.3 — Discovery Diagnostics

Deliverables:

- Add diagnostic status objects/messages for:
  - no participants discovered
  - selected participant has no writer topics
  - topic not found before timeout
  - topic found without usable DynamicType
  - multiple writers match direct startup command

Tests:

- Unit-test each diagnostic path.
- Smoke-test timeout behavior with an empty registry.

Completion gate:

- UI can display meaningful discovery states instead of empty/blank panes.

## Phase 3 — Field Catalog

### Slice 3.1 — DynamicType Traversal

Deliverables:

- Finalize `FieldDescriptor` shape:
  - path
  - name
  - type kind
  - plottable flag
  - collection flag if useful
- Traverse fields from discovered `DynamicType`, not live sample values.
- Use member accessors:
  - `dynamic_type.member_count`
  - `dynamic_type.member(index)`
  - `member.name`, `member.type`, `member.type.kind`
- Keep `dynamic_type.members()` support when available.

Tests:

- Unit-test fake DynamicTypes with nested structs.
- Unit-test constructed Connext `StructType` with nested fields.
- Unit-test recursion guard/max depth for self-referential or repeated type references.

Completion gate:

- Field list shows `position.x` style nested paths from fake and constructed DynamicTypes.

### Slice 3.2 — Plottability

Deliverables:

- Classify numeric scalar fields as plottable.
- Mark strings, enums, structs, sequences, and arrays as non-plottable for v1.
- Keep non-plottable fields selectable for Message Data mode.

Tests:

- Unit-test plottable classification for integer, float, string, enum, sequence, array, and struct.
- Unit-test Plot toggle disabled/diagnostic state for non-numeric fields.

Completion gate:

- Field list can distinguish Message Data-compatible fields from Plot-compatible fields.

### Slice 3.3 — Field Value Reads

Deliverables:

- Read sample values using `sample[field_path]`, including nested paths like
  `sample["position.x"]`.
- Return structured extraction results for found/missing/invalid sample states.

Tests:

- Unit-test fake mapping/object/DynamicData-like access.
- Constructed Connext DynamicData test for top-level and nested field reads.
- Invalid path test returns a diagnostic rather than crashing.

Completion gate:

- A selected field path can be read from incoming sample-like objects reliably.

## Phase 4 — Subscriber Runtime

### Slice 4.1 — Reader Creation

Deliverables:

- Create `dds.DynamicData.Topic(participant, endpoint.topic_name, endpoint.dynamic_type)`.
- Create subscriber QoS using discovered partition and presentation QoS when present.
- Create reader QoS using discovered reliability, durability, deadline, and ownership.
- Return structured setup result with reader or diagnostic.

Tests:

- Unit-test QoS copy logic with fake endpoint QoS objects.
- Unit-test missing DynamicType fails with a clear diagnostic.
- Optional live DDS test creates a DynamicData topic/reader from a constructed type.

Completion gate:

- Direct view can create a reader or report exactly why it cannot.

### Slice 4.2 — Sample Pump

Deliverables:

- Poll/take valid samples without blocking the Dear PyGui render loop.
- Store bounded buffers:
  - latest message rows
  - plot points `(timestamp, numeric_value)`
- Keep one active subscription at a time.
- Switching Message Data / Plot must not recreate the reader.

Tests:

- Unit-test buffer size bounds and point ordering.
- Unit-test invalid samples are skipped/reported.
- Unit-test toggle changes mode only, not subscription identity.

Completion gate:

- Fake reader samples flow into message and plot buffers.

### Slice 4.3 — Direct View Discovery

Deliverables:

- For `--domain --topic --field`, wait for topic discovery up to `--timeout`.
- Select first compatible writer when multiple writers match.
- Emit a visible diagnostic for duplicate matching writers.
- Validate field existence before subscribing.

Tests:

- Unit-test topic timeout.
- Unit-test duplicate writer diagnostic.
- Unit-test field-not-found diagnostic.

Completion gate:

- Direct view can start from CLI args with fake discovery and a fake reader.

## Phase 5 — Dear PyGui UI

### Slice 5.1 — Static Layout

Deliverables:

- Build one Dear PyGui window with:
  - top domain selector and refresh/apply control
  - left Process/Participant list
  - middle Writer Topic list
  - right Field list
  - main Message Data / Plot pane
  - bottom startup command and Copy button
- Use stable tags/constants for widgets.

Tests:

- Unit-test startup command generation separately.
- Smoke-test `render_once` style function with a fake/minimal DPG adapter if practical.
- Manual GUI check that layout opens and key widgets are visible.

Completion gate:

- Dear PyGui shell opens with fake/static data and no DDS dependency.

### Slice 5.2 — Interactive Browsing

Deliverables:

- Wire domain apply/refresh to discovery lifecycle.
- Selecting a process filters writer topics.
- Selecting a writer topic populates fields.
- Selecting a field creates/replaces the active subscription.

Tests:

- Unit-test selection state transitions with fake snapshots.
- Unit-test changing domain closes/replaces active participant/subscription state.
- Manual GUI check with fake discovery data.

Completion gate:

- User can browse fake process/topic/field data end-to-end in the UI.

### Slice 5.3 — Live Field View

Deliverables:

- Message Data mode shows newest selected field values.
- Plot mode updates a Dear PyGui line series over time.
- Plot mode disabled or diagnostic shown for non-numeric fields.
- Startup command updates as domain/topic/field/mode changes.
- Copy button copies the generated command using available Dear PyGui clipboard support
  or a documented fallback.

Tests:

- Unit-test generated command for mode changes.
- Unit-test plot buffer window/history behavior.
- Manual GUI check with simulated samples.

Completion gate:

- Fake sample stream updates both message and plot views without recreating subscription.

## Phase 6 — Live DDS Validation

### Slice 6.1 — Fixture Publisher

Deliverables:

- Add optional live test fixture that publishes a constructed DynamicData type with fields:
  - `id`
  - `position.x`
  - `position.y`
  - `label`
- Publish on an isolated topic/domain to avoid user traffic.

Tests:

- Gated live test skips clearly when Connext or license is unavailable.
- Live test discovers fixture writer and propagated DynamicType.

Completion gate:

- Live discovery sees the fixture writer and field catalog.

### Slice 6.2 — Live Subscription

Deliverables:

- Subscribe to the fixture writer with matched QoS.
- Read one selected numeric field value.
- Read one selected text field value in Message Data mode.

Tests:

- Gated live test for `position.x` numeric extraction.
- Gated live test for `label` text extraction.

Completion gate:

- Live data can flow through discovery, field catalog, subscription, and extraction.

### Slice 6.3 — Manual GUI Smoke

Deliverables:

- Run fixture publisher and `rti_view` together.
- Validate interactive flow:
  - domain selection
  - process/participant selection
  - writer topic selection
  - field selection
  - Message Data view
  - Plot view
  - copied startup command
- Validate direct command from copied startup string.

Tests:

- Manual checklist recorded in test output or PR notes, not committed as generated logs unless requested.

Completion gate:

- The v1 workflow works end-to-end with a real DDS fixture.

## Phase 7 — Documentation And Cleanup

### Slice 7.1 — User Docs

Deliverables:

- Add `tools/rti_view/README.md` with:
  - install/run instructions
  - interactive flow
  - direct startup examples
  - v1 limitations
  - troubleshooting diagnostics

Tests:

- Verify all documented commands are valid or clearly marked as examples.

Completion gate:

- A new user can run the tool from the README.

### Slice 7.2 — Repo Integration

Deliverables:

- Update `tools/README.md` to list `rti_view/` and `rti_spy/` separately.
- Ensure `rs_gui_v2` only references `rti_view` where needed.
- Remove stale `dds_view`, Textual, or old path references.

Tests:

- Search for stale strings:
  - `dds_view`
  - `tools/install.sh`
  - `tools/requirements.txt`
  - old root `run_rtispy.sh`
- Run editor diagnostics on touched Python files.

Completion gate:

- Tool layout and docs are coherent across the repo.

## Out Of Scope For V1

- Multi-topic views
- Multi-field overlays
- Automatic domain scanning
- Participant/process identifiers in copied startup commands
- External XML/IDL/generated type loading
- Web UI or terminal TUI modes
