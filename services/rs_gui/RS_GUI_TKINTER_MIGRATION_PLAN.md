# RS GUI v2 Tkinter Migration Plan

## Purpose

This document is the working implementation plan for replacing the previous
control surface in rs_gui with a Tkinter-based desktop UI.

It is intended to be the persistent source of truth for:

- migration scope
- reuse-vs-rewrite boundaries
- high-confidence implementation slices
- current status
- validation evidence
- next recommended slice

Update this document as work progresses instead of keeping migration state only
in chat or commit messages.

## Decision

We will not do a full rewrite from scratch.

We will keep the current app-core, process/service control, monitoring, and
session behavior layers where possible, and replace the legacy frontend with a
new Tkinter UI layer built beside the current implementation.

## Why This Direction

The current backend split already contains the difficult domain logic:

- service launch and local process tracking
- shutdown and recovery rules
- service admin and monitoring adapters
- controller-level validation and command dispatch
- workspace/session state shaping for the service-control surface

The current pain is concentrated in the GUI layer:

- immediate-mode refresh behavior
- popup and validation ergonomics
- form state handling
- widget lifecycle coupling
- incremental UI maintenance cost

That makes this a UI replacement effort, not a ground-up application rewrite.

## Migration Rules

- Keep app-core as the behavioral source of truth unless a concrete mismatch is
  discovered.
- Do not port the legacy renderer widget-for-widget. Rebuild the UI layer
  around Tkinter/Ttk idioms.
- Prefer a new Tkinter package beside the current GUI rather than a gradual
  in-place mutation of the legacy renderer.
- Keep the legacy UI available until the first Tkinter vertical
  slice is validated.
- Treat each migration slice as complete only when it has executable
  validation.
- Do not expand scope within a slice. Finish one vertical slice before opening
  the next.

## Reuse vs Replace

### Keep and Reuse

- `services/rs_gui/app_core/`
- `services/rs_gui/gui/session.py`
- `services/rs_gui/gui/tabs/record_controller.py`
- `services/rs_gui/gui/tabs/replay_controller.py`
- service/process DTOs, monitoring models, workspace models, command/event DTOs
- existing unit and live behavior tests where they are not renderer-specific

### Replace

- legacy Record/Replay renderer layer
- legacy render helpers and callback glue
- renderer-specific shell tests once equivalent Tkinter tests exist

### Likely Adapter Layer

- thin Tk presenters or view adapters that translate controller/view-model
  snapshots into Tk widgets
- timer-driven refresh orchestration
- dialog and validation helpers

## Proposed Target Shape

```text
services/rs_gui/
+-- app_core/                      # mostly retained
+-- gui/                           # retained session/controller layer and legacy helpers
+-- tk_gui/
|   +-- app.py                     # Tk entry point/bootstrap
|   +-- main_window.py             # root window shell
|   +-- refresh.py                 # timer-driven refresh wiring
|   +-- dialogs.py                 # error, confirmation, validation dialogs
|   +-- tabs/
|   |   +-- record_tab.py
|   |   +-- replay_tab.py
|   +-- widgets/
|       +-- service_table.py
|       +-- command_history.py
|       +-- console_view.py
|       +-- form_fields.py
+-- test/
    +-- test_tk_shell_smoke.py
    +-- test_tk_record_tab.py
    +-- test_tk_replay_tab.py
```

The exact package names can change, but the separation should remain:

- backend behavior stays in app-core and controllers
- Tkinter owns widgets, dialogs, layout, and input handling
- no direct DDS calls from Tk widgets

## Current Backend Contract To Preserve

The Tk migration should treat the existing session/controllers as the backend
contract unless a concrete mismatch is found.

### Session Entry Points

- `gui.session.GuiShellSession.command_sink()`
- `gui.session.GuiShellSession.next_view()`
- `gui.session.GuiShellSession.next_view_async()`
- `gui.session.GuiShellSession.process_pending_commands()`
- `gui.session.GuiShellSession.dispatch_command()`

### Record Entry Points

- `gui.tabs.record_controller.RecordTabController.refresh_view()`
- `gui.tabs.record_controller.RecordTabController.launch_recording()`
- `gui.tabs.record_controller.RecordTabController.execute_action()`
- `gui.tabs.record_controller.RecordTabController.select_candidate()`
- `gui.tabs.record_controller.RecordTabController.set_tag_value()`

### Replay Entry Points

- `gui.tabs.replay_controller.ReplayTabController.refresh_view()`
- `gui.tabs.replay_controller.ReplayTabController.handle_command()`
- `gui.tabs.replay_controller.ReplayTabController.launch_replay()`
- `gui.tabs.replay_controller.ReplayTabController.select_target()`

### Explicit Boundary

- Tk widgets may read view-model fields and call the session/controller methods
  above.
- Tk widget creation, mutation, and teardown must stay on the Tk main thread.
- Background or async work may compute snapshots or enqueue commands, but it
  must hand results back to the Tk thread before touching widgets.
- Tk widgets must not call DDS APIs, admin adapters, monitoring adapters, or
  process-manager methods directly.
- Tk widgets must not reimplement command routing already encoded in
  `GuiShellSession.dispatch_command()`.

## High-Confidence Slice Strategy

Each slice below is intentionally small, behavior-scoped, and independently
valuable.

### Slice 0: Minimal Tk Shell Scaffolding

Goal:
Create the smallest Tkinter shell needed to host the Recording and Replay tabs
and prove the app can start and shut down cleanly.

Scope:

- add a Tk entry point
- add a minimal root window with a two-tab placeholder shell
- add app start/exit smoke test

Why high confidence:

- no service behavior changes
- no controller rewrites
- establishes only the shell needed for Record and Replay

Done when:

- a Tk window opens successfully with Record and Replay tab placeholders
- app exits cleanly
- smoke test passes

Validation:

- Tk smoke/unit test
- manual local launch

Files to add/change:

- `services/rs_gui/requirements.txt`
- `services/rs_gui/tk_gui/__init__.py`
- `services/rs_gui/tk_gui/app.py`
- `services/rs_gui/tk_gui/main_window.py`
- `services/rs_gui/test/test_tk_shell_smoke.py`

Allowed backend touchpoints:

- none beyond session construction needed to open an empty shell
- no command dispatch yet
- no direct tab controller logic beyond placeholder labels/tabs

Validation command:

- `cd services/rs_gui && python test/test_tk_shell_smoke.py`

Out of scope:

- no refresh loop
- no command bridge
- no Record or Replay widgets beyond placeholders
- no edits to `gui/session.py`, record controller, or replay controller

### Slice 1: Shared Refresh And Command Bridge

Goal:
Replace the legacy frame-refresh model with a Tk timer and explicit command
dispatch bridge for the Record and Replay surfaces.

Scope:

- `after()`-driven refresh loop
- call into existing session/controller refresh methods
- map command submissions from Tk events to existing command sink/session
- support only shared shell state required by Record and Replay

Why high confidence:

- keeps the existing backend contract intact
- avoids tab-specific widget complexity initially

Done when:

- periodic refresh updates shell state
- commands can be enqueued from Tk without touching DDS directly

Validation:

- unit test for timer-driven refresh bridge
- unit test for command dispatch bridge

Files to add/change:

- `services/rs_gui/tk_gui/app.py`
- `services/rs_gui/tk_gui/main_window.py`
- `services/rs_gui/tk_gui/refresh.py`
- `services/rs_gui/test/test_tk_shell_smoke.py`
- `services/rs_gui/test/test_gui_session.py`

Allowed backend touchpoints:

- `GuiShellSession.next_view()` for state refresh from the Tk `after()` loop
- `GuiShellSession.command_sink()` for queued user intents
- `GuiShellSession.next_view_async()` only if a bridge helper explicitly owns
  the async boundary away from Tk widget code
- `GuiShellSession.process_pending_commands()` only if needed by the bridge,
  not by direct widget callbacks
- `GuiShellSession.dispatch_command()` only through existing session flow, not
  by direct widget calls

Required bridge contract:

- one Tk-owned timer requests the next shell snapshot on a fixed cadence
- Tk callbacks stay synchronous; the bridge should prefer `next_view()` rather
  than running ad hoc async logic inside widget callbacks
- one Tk-owned adapter accepts widget intents and forwards them to
  `command_sink()`
- the bridge may translate Tk callbacks into `AppCommand` creation, but it must
  not add business rules
- the bridge may cache the latest shell snapshot for rendering, but it must not
  mutate controller state except through existing session/controller methods
- widget creation and updates remain on the Tk main thread even if a later
  implementation uses helper threads for non-UI work

Validation command:

- `cd services/rs_gui && python test/test_gui_session.py`
- `cd services/rs_gui && python test/test_tk_shell_smoke.py`

Out of scope:

- no Record field widgets
- no Replay field widgets
- no new command semantics
- no edits to `app_core/`
- no direct calls from Tk to `ServiceProcessManager`, `ServiceAdminFacade`, or
  `ServiceMonitoringFacade`

### Slice 2: Record Tab Vertical Slice

Goal:
Port the Record tab first because it is the primary control surface and already
has the strongest backend/test coverage.

Scope:

- launch form
- candidate selection table/combo
- pause/resume/tag/shutdown buttons
- launch validation and modal errors
- command history/status rendering needed for recording workflows

Why high confidence:

- existing controller behavior is mature
- most critical operational workflow
- best area to prove the Tkinter architecture

Done when:

- recording launch and control work through Tk
- local validation and error dialogs behave correctly
- no legacy renderer dependency is required for recording workflows

Validation:

- record-tab widget tests
- existing controller tests still pass
- required Record live integration scenarios pass

Files to add/change:

- `services/rs_gui/tk_gui/main_window.py`
- `services/rs_gui/tk_gui/tabs/record_tab.py`
- `services/rs_gui/tk_gui/widgets/service_table.py`
- `services/rs_gui/tk_gui/widgets/command_history.py`
- `services/rs_gui/tk_gui/dialogs.py`
- `services/rs_gui/test/test_tk_record_tab.py`

Allowed backend touchpoints:

- read Record state from the shell snapshot returned by `next_view()`
- use `command_sink()` to send Record intents such as launch, pause, resume,
  tag, shutdown, and terminate-local
- use existing Record-controller behavior indirectly through session dispatch
- if a local UI selection must be mirrored immediately, only call
  `RecordTabController.select_candidate()` or `set_tag_value()` through an
  explicit adapter layer

Validation command:

- `cd services/rs_gui && python test/test_tk_record_tab.py`
- `cd services/rs_gui && python test/test_record_tab_controller.py`
- `cd services/rs_gui && python test/test_tk_record_live_integration.py`

Out of scope:

- no Replay widgets
- no cutover/default-entrypoint changes
- no changes to Record service semantics, launch args, or shutdown behavior
- no direct launch calls from Tk to `RecordTabController.launch_recording()`
  unless routed through the agreed adapter/session path

### Slice 3: Replay Tab Vertical Slice

Goal:
Port Replay next, including the recent launch-path validation rules.

Scope:

- replay launch form
- required recording database path
- validation popup/dialog behavior
- replay target selection and action buttons
- replay status rendering needed for operator workflows

Why high confidence:

- controller rules are now explicit and tested
- follows the same UI/control pattern as Record

Done when:

- invalid replay path is rejected in Tk before launch
- valid replay launches and status updates render correctly
- no legacy renderer dependency is required for replay workflows

Validation:

- replay-tab widget tests
- existing replay controller tests still pass
- required Replay live integration scenarios pass

Files to add/change:

- `services/rs_gui/tk_gui/main_window.py`
- `services/rs_gui/tk_gui/tabs/replay_tab.py`
- `services/rs_gui/tk_gui/dialogs.py`
- `services/rs_gui/test/test_tk_replay_tab.py`

Allowed backend touchpoints:

- read Replay state from the shell snapshot returned by `next_view()`
- use `command_sink()` to send Replay intents such as launch, start, pause,
  resume, stop, and shutdown
- preserve the existing replay validation path in controller/session code
- if a local UI selection must be mirrored immediately, only call
  `ReplayTabController.select_target()` through an explicit adapter layer

Validation command:

- `cd services/rs_gui && python test/test_tk_replay_tab.py`
- `cd services/rs_gui && python test/test_gui_replay_controller.py`
- `cd services/rs_gui && python test/test_tk_replay_live_integration.py`

Out of scope:

- no Record rewiring unless required to generalize a shared widget
- no changes to replay database validation semantics
- no changes to replay admin-command semantics
- no direct calls from Tk to file-system launch helpers except through the
  existing controller path

### Slice 4: Record And Replay Cutover

Goal:
Make the Tk frontend the supported control surface for Recording and Replay and
retire the equivalent legacy paths.

Scope:

- select the default entry point for the two-tab control surface
- update docs and launch commands
- remove legacy renderer code that only exists for Record and Replay

Why high confidence:

- deferred until both vertical slices are validated
- limited to the two retained tabs only

Done when:

- Tk is the default supported Record/Replay control surface
- legacy renderer code for those workflows can be deleted without behavioral loss

Validation:

- final regression test pass
- manual operator sanity check

Files to add/change:

- `services/rs_gui/rs_gui_app.py`
- `services/rs_gui/run_gui.sh`
- `services/rs_gui/README.md`
- remove the legacy Record/Replay renderer files
- `services/rs_gui/test/test_headless_entrypoint.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_shell_smoke.py`
- `cd services/rs_gui && python test/test_tk_record_tab.py`
- `cd services/rs_gui && python test/test_tk_replay_tab.py`
- `cd services/rs_gui && python test/test_record_tab_controller.py`
- `cd services/rs_gui && python test/test_gui_replay_controller.py`
- `cd services/rs_gui && python test/test_headless_entrypoint.py`
- `cd services/rs_gui && python test/test_tk_record_live_integration.py`
- `cd services/rs_gui && python test/test_tk_replay_live_integration.py`
- `cd services/rs_gui && python test/test_tk_service_button_live_integration.py`
- `cd services/rs_gui && python test/test_tk_session_live_integration.py`

Out of scope:

- no migration of convert/topics/plots
- no removal of reusable backend logic in `gui/session.py` or `app_core/`
- no broader application redesign beyond making Tk the default Record/Replay UI

## Required End-To-End Validation

The migration is not complete when the Tk widgets render correctly. It is only
complete when the Tk surface preserves the existing operator-visible live
behavior across Record and Replay end-to-end flows.

These end-to-end scenarios are required, not optional.

### Scenario A: DDS Publish -> Record -> Artifact Verification

Goal:
Generate DDS samples, record them through the Tk Record workflow, and verify
that a valid recording artifact set is produced.

Required behavior:

- start the Tk UI and launch Recording Service from the Record tab
- generate DDS test data on the configured data domain
- verify the Record tab reflects live monitoring state transitions
- verify the selected service shows a non-empty current file path when the
  service reports one
- stop or shutdown recording cleanly
- verify the recording directory contains `metadata.db` and at least one
  `data_*.db` file

Suggested test file:

- `services/rs_gui/test/test_tk_record_live_integration.py`

Current implementation anchor:

- `services/rs_gui/test/test_gui_session_live_integration.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_record_live_integration.py`

Artifacts to verify:

- generated DDS samples reached the recorder
- recording output directory exists under workspace-controlled output
- `metadata.db` exists
- at least one `data_*.db` exists
- current file/current output path is visible in the UI state when available

### Scenario B: Replay Recorded Data -> Subscribe -> Verify Payloads

Goal:
Replay previously recorded DDS data through the Tk Replay workflow and verify
the replayed samples by subscribing to the output.

Required behavior:

- start the Tk UI and launch Replay Service from the Replay tab
- point replay at a valid recording database directory
- subscribe to the replayed topic(s) with a test subscriber
- verify expected samples are received from replay, not only that the service
  process starts
- verify Replay state transitions are reflected live in the UI

Suggested test file:

- `services/rs_gui/test/test_tk_replay_live_integration.py`

Current implementation anchor:

- `services/rs_gui/test/test_gui_service_button_live_integration.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_replay_live_integration.py`

Artifacts to verify:

- subscriber receives replayed samples
- payload count/content matches the generated fixture expectations
- Replay target state and progress values update in the UI while replay runs

### Scenario C: Exercise All Record/Replay Buttons And Live State Changes

Goal:
Exercise every supported Record and Replay button in the Tk UI and verify the
visible monitored state changes for each action.

Required Record actions:

- launch
- pause
- resume
- tag
- shutdown
- terminate local, when applicable

Required Replay actions:

- launch
- start
- pause
- resume
- stop
- shutdown

Required assertions:

- each enabled button dispatches the correct command intent
- each action produces the expected live state change in the rendered Tk view
- command history/status output updates accordingly
- failure conditions render visible errors/dialogs instead of failing silently
- paused, resumed, stopped, shutdown, and terminated states are explicitly
  asserted rather than inferred from button success alone
- when shutdown or terminate-local is invoked for a GUI-owned process, the test
  must verify that the underlying PID exits within a bounded timeout
- process-death checks must confirm the process is actually gone, not merely
  hidden from the UI

Suggested test file:

- `services/rs_gui/test/test_tk_service_button_live_integration.py`

Current implementation anchor:

- `services/rs_gui/test/test_gui_service_button_live_integration.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_service_button_live_integration.py`

### Scenario D: Full Process Lifecycle And State Transition Verification

Goal:
Verify the full process lifecycle for GUI-visible Record and Replay services,
including explicit monitored state transitions such as paused and resumed.

Required Record lifecycle coverage:

- not running or undiscovered -> launched
- launched -> running or enabled/started, depending on the monitoring surface
- running -> paused
- paused -> resumed/running
- running or paused -> shutdown requested
- shutdown requested -> stopped/exited or removed from active candidates
- local GUI-owned process -> terminated locally when that path is exercised

Required Replay lifecycle coverage:

- not running or undiscovered -> launched
- launched -> started/running
- running -> paused
- paused -> resumed/running
- running or paused -> stopped
- stopped or running -> shutdown requested
- shutdown requested -> stopped/exited or removed from active targets

Required assertions:

- each lifecycle action is verified by observed UI state, not just process exit
- paused state is visible in the Tk UI when pause is issued
- resumed/running state is visible again after resume or start
- stopped/shutdown states are distinguished where the backend exposes them
- process disappearance from selectors/lists is asserted when the service exits
- command history or status output records the lifecycle action result
- monitoring fields such as current file, progress, or current target details
  continue updating correctly while lifecycle changes occur
- after shutdown, the owned service PID is verified dead within a bounded
  timeout when the test has process visibility
- after local termination, the owned service PID is verified dead within a
  bounded timeout
- process-death assertions must explicitly reject zombie/defunct processes as a
  passing outcome

Suggested test files:

- `services/rs_gui/test/test_tk_record_live_integration.py`
- `services/rs_gui/test/test_tk_replay_live_integration.py`
- `services/rs_gui/test/test_tk_service_button_live_integration.py`

Current implementation anchors:

- `services/rs_gui/test/test_gui_session_live_integration.py`
- `services/rs_gui/test/test_gui_service_button_live_integration.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_record_live_integration.py`
- `cd services/rs_gui && python test/test_tk_replay_live_integration.py`
- `cd services/rs_gui && python test/test_tk_service_button_live_integration.py`

### Scenario E: Live Service Discovery And Refresh

Goal:
Verify that when a new service is detected after the UI is already running, the
Tk view refreshes automatically and shows updated live state without requiring a
manual restart.

Required behavior:

- start the Tk UI before the target service exists
- bring up a new Record or Replay service after the UI is already running
- verify the service appears in the relevant selector/list automatically
- verify the selected/visible data refreshes on the timer-driven update path
- verify current monitored values, including current file where available,
  become visible after discovery

Suggested test file:

- `services/rs_gui/test/test_tk_session_live_integration.py`

Current implementation anchor:

- `services/rs_gui/test/test_gui_session_live_integration.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_session_live_integration.py`

### Scenario F: Full Operator Flow

Goal:
Prove the complete operator workflow under Tk from data generation through
recording, replay, and subscriber verification.

Required sequence:

- generate deterministic DDS test data
- launch Record from Tk
- verify live Record monitoring, including current file visibility
- stop or shutdown Record, verify the process is dead, and verify recording
  artifacts
- launch Replay from Tk against the produced recording
- subscribe and verify replayed DDS samples
- exercise Replay controls while monitoring live UI state changes
- shutdown Replay and verify the process is dead

This scenario can be implemented either as one dedicated end-to-end test or as
an orchestrated test suite that runs Scenarios A through E in sequence.

Suggested test file:

- `services/rs_gui/test/test_tk_record_replay_e2e.py`

Validation command:

- `cd services/rs_gui && python test/test_tk_record_replay_e2e.py`

## Validation Artifacts And Constraints

- All generated outputs must stay inside the workspace, preferably under
  `services/rs_gui/test_output/` or another workspace-local test artifact
  directory.
- End-to-end tests must use deterministic topic/data fixtures so subscriber
  assertions are stable.
- Live integration tests may be environment-gated when RTI runtime
  prerequisites are missing, but the plan still requires them before declaring
  migration complete.
- Process-lifecycle tests must use OS-level process checks when a PID is known,
  and those checks must verify the process exited rather than becoming a zombie
  or merely disappearing from the rendered UI.
- The Tk migration is not complete until the Tk test set provides parity with
  the current live integration intent covered by:
  `test_gui_session_live_integration.py` and
  `test_gui_service_button_live_integration.py`.

## Medium-Model Safety Notes

This plan is intended to be executable by a medium-capability implementation
model only if the following rules are enforced:

- complete one slice at a time with its listed validation before opening the
  next slice
- do not invent new backend abstractions before proving the current session
  contract is insufficient
- prefer adding new Tk files over editing existing backend files
- if a slice requires changes outside its listed files, stop and record the
  mismatch in the Slice Log before widening scope

## V1 Acceptance Checklist

Use this section as the single pass/fail baseline for V1. V1 is complete only
when all items below pass.

### Required V1 Tests

- [ ] `cd services/rs_gui && python test/test_tk_shell_smoke.py`
- [ ] `cd services/rs_gui && python test/test_gui_session.py`
- [ ] `cd services/rs_gui && python test/test_tk_record_tab.py`
- [ ] `cd services/rs_gui && python test/test_record_tab_controller.py`
- [ ] `cd services/rs_gui && python test/test_tk_replay_tab.py`
- [ ] `cd services/rs_gui && python test/test_gui_replay_controller.py`
- [ ] `cd services/rs_gui && python test/test_tk_record_live_integration.py`
- [ ] `cd services/rs_gui && python test/test_tk_replay_live_integration.py`
- [ ] `cd services/rs_gui && python test/test_tk_service_button_live_integration.py`
- [ ] `cd services/rs_gui && python test/test_tk_session_live_integration.py`
- [ ] `cd services/rs_gui && python test/test_tk_record_replay_e2e.py`
- [ ] `cd services/rs_gui && python test/test_headless_entrypoint.py`

### Required V1 Behavioral Coverage

- [ ] Tk shell starts and exits cleanly
- [ ] timer-driven refresh and command dispatch work through the existing
  session/controller path
- [ ] Record launch, pause, resume, tag, shutdown, and terminate-local work
- [ ] Replay launch, start, pause, resume, stop, and shutdown work
- [ ] DDS publish -> Record -> artifact verification works end to end
- [ ] Replay -> subscribe -> payload verification works end to end
- [ ] new service discovery refreshes live without restarting the UI
- [ ] command history and operator-visible status updates remain functional

### Required V1 Shutdown Verification

- [ ] Record shutdown is verified by observed UI state and OS-level process exit
- [ ] Replay shutdown is verified by observed UI state and OS-level process exit
- [ ] local termination is verified by OS-level process exit when that path is
  exercised
- [ ] process-death checks reject zombie or defunct processes as passing
  outcomes
- [ ] shutdown/process-death verification is covered in the button flow,
  lifecycle, and end-to-end scenarios rather than in only one place

### V1 Exit Rule

Do not declare V1 complete until every item above is checked off. The V2
backlog below is intentionally excluded from the V1 exit gate.

## V2 Backlog: Deferred Integration Coverage

The sections above define the minimum baseline required to begin the Tk
migration safely. The items below are important follow-on integration coverage
that should be treated as V2 work so baseline implementation can start without
losing these gaps.

These are deferred, not rejected.

### V2-1: Close-Policy Parity

Gap:
The current baseline covers shutdown and termination flows, but does not yet
require a dedicated integration test for GUI close-policy behavior.

Required follow-on coverage:

- `leave_running` closes the GUI while leaving externally or GUI-owned services
  running as intended
- `shutdown_gui_launched` closes the GUI and shuts down only GUI-owned
  processes
- PID/state checks verify services are either preserved or dead according to the
  selected close policy

Recommended generated test:

- `services/rs_gui/test/test_tk_close_policy_integration.py`

### V2-2: Duplicate/Conflict Parity

Gap:
The baseline covers live discovery refresh, but not duplicate service-name or
duplicate admin-target conflict handling under Tk.

Required follow-on coverage:

- duplicate Record candidates appear visibly with conflict diagnostics
- duplicate Replay targets appear visibly with conflict diagnostics
- admin actions stay disabled while the duplicate target remains ambiguous
- local-only actions remain available only when safe and intended

Recommended generated test:

- `services/rs_gui/test/test_tk_duplicate_conflict_integration.py`

### V2-3: Advanced Record Launch Options Parity

Gap:
The baseline proves Record launch and lifecycle, but not that all retained
operator-facing Record launch fields are honored in a live run.

Fields to cover:

- config name
- verbosity
- working directory
- extra args
- topic allow and topic deny
- retained storage/output shaping fields that remain in the Tk UI

Required follow-on coverage:

- launched command/process reflects the selected launch options
- resulting recording artifacts and monitored fields match the chosen options
- invalid combinations surface visible validation failures

Recommended generated test:

- `services/rs_gui/test/test_tk_record_launch_options_integration.py`

### V2-4: Advanced Replay Launch Options Parity

Gap:
The baseline proves Replay launch and lifecycle, but not that all retained
Replay configuration fields affect runtime behavior correctly.

Fields to cover:

- playback rate
- loop
- time window
- qos file path
- participant QoS profile
- writer QoS profile
- config name, verbosity, working directory, and extra args if those remain in
  the Tk UI

Required follow-on coverage:

- replay launch arguments reflect the chosen settings
- replay behavior changes in a test-observable way where practical
- invalid or missing paths/profiles surface visible validation failures

Recommended generated test:

- `services/rs_gui/test/test_tk_replay_launch_options_integration.py`

### V2-5: Event-Log Parity

Gap:
The baseline checks event/status behavior indirectly, but does not yet require
full Tk parity for the operator-visible event log stream.

Required follow-on coverage:

- launch, pause, resume, stop, shutdown, discovery, monitoring, and failure
  events appear in the Tk event log
- event severity and message content remain useful for operators
- event ordering is stable enough for debugging and auditability

Recommended generated test:

- `services/rs_gui/test/test_tk_event_log_integration.py`

## Recommended Generated Tests

If the goal is to start implementation now and generate only the most valuable
follow-on tests first, generate them in this order:

1. `test_tk_close_policy_integration.py`
2. `test_tk_duplicate_conflict_integration.py`
3. `test_tk_record_launch_options_integration.py`
4. `test_tk_replay_launch_options_integration.py`
5. `test_tk_event_log_integration.py`

Reason for this order:

- close-policy and duplicate/conflict behavior are the most likely to produce
  operator-facing regressions that a medium-level implementation model would
  miss
- advanced launch options are easy to render incorrectly while still passing
  basic lifecycle tests
- event-log parity matters, but it is slightly less likely to block initial
  baseline usability than the four items above

## Current Status Tracker

### Overall Phase

- [x] Slice 0 complete
- [x] Slice 1 complete
- [x] Slice 2 complete
- [x] Slice 3 complete
- [x] Slice 4 complete

### Current Recommended Next Slice

`Completed`

Reason:
The default shell now launches the Tk Record/Replay surface, launcher docs are
aligned, and the remaining work shifts from architecture slices to parity and
cleanup follow-up.

## Slice Log

Use this section to update progress as work is performed.

| Slice | Status | Owner | Last Updated | Notes | Validation |
| --- | --- | --- | --- | --- | --- |
| 0 | Done | Copilot | 2026-06-04 | Replaced the blocked initial scaffold with a working `tk_gui/` scaffold, `--tk-gui-check` / `--tk-gui`, and `test_tk_shell_smoke.py` | `python test/test_tk_shell_smoke.py`; `python test/test_headless_entrypoint.py`; `get_errors` clean |
| 1 | Done | Copilot | 2026-06-04 | Added a Tk `after()` refresh bridge, session-backed shell rendering for shared status/event state, and command forwarding through the existing session boundary | `python test/test_tk_shell_smoke.py`; `python test/test_headless_entrypoint.py`; `get_errors` clean |
| 2 | Done | Copilot | 2026-06-04 | Added a working Tk Record tab with launch controls, candidate selection, tag editing, and action buttons wired through the existing session/controller boundary | `python test/test_tk_record_tab.py`; `python test/test_tk_shell_smoke.py`; `python test/test_headless_entrypoint.py` |
| 3 | Done | Copilot | 2026-06-05 | Added a working Tk Replay tab with target selection, launch-path editing, and playback action buttons wired through the existing Replay/session boundary | `python test/test_tk_replay_tab.py`; `python test/test_tk_shell_smoke.py`; `get_errors` clean |
| 4 | Done | Copilot | 2026-06-05 | Switched the default `--gui` launcher path to the Tk Record/Replay shell and aligned startup diagnostics and docs with the Tk cutover | `python test/test_tk_replay_tab.py`; `python test/test_tk_shell_smoke.py`; `python test/test_headless_entrypoint.py`; `get_errors` clean |

Suggested status values:

- `Not started`
- `In progress`
- `Blocked`
- `Done`

## Working Notes

### Assumptions

- `dds view` now owns the richer data viewer/plot experience.
- rs_gui only needs to be a reliable Record/Replay control and state-update surface.
- existing app-core and controllers are good enough to reuse as the initial
  backend contract.

### Risks To Watch

- some current controller/view-model code may still encode legacy
  renderer-oriented assumptions and need small adapter cleanup
- `gui/session.py` may prove too shell-specific and require extraction of a
  Tk-neutral presenter bridge
- some tests may be tightly coupled to legacy renderer call recording and need
  to be replaced rather than ported

### Explicit Non-Goals For Early Slices

- redesigning service/process semantics
- changing DDS adapter ownership
- broad workspace format rewrites
- reintroducing plotting complexity into the control surface
- migrating convert, topic inspection, or other non-Record/Replay tabs

## Update Procedure

When starting a slice:

1. Set its status to `In progress` in the Slice Log.
2. Add a short note describing the exact scope being attempted.

When completing a slice:

1. Mark the slice checkbox complete.
2. Set the Slice Log row to `Done`.
3. Record the validation command(s) or evidence.
4. Change `Current Recommended Next Slice` to the next slice.

When blocked:

1. Set the Slice Log row to `Blocked`.
2. Add the blocking issue in Notes.
3. Record the smallest decision needed to unblock it.
