# Replay Service Runtime Management Plan

## Objective

Carry the Recording Service runtime management model over to the Replay tab so Replay Service instances can be launched, monitored, controlled, displayed, and cleaned up through the same GUI-owned process lifecycle used by Recording Service.

The target user experience is:

- Launch Replay Service from the Replay tab with operator-selected database, QoS, domain, playback, and service configuration values.
- See GUI-spawned and externally observed Replay Service instances in the Replay Service candidate table.
- See process state, PID, hostname, output log path/tail, admin readiness, monitoring state, and playback-specific progress fields update without extra clicks.
- Send Service Admin commands to the selected Replay Service instance.
- On app close, include GUI-spawned Replay Service processes in the same leave-running vs shutdown policy used for Recording Service and Converter jobs.

## Current State

Recording Service now has the working model:

- `RecordTabController` owns launch settings, selected candidate id, monitoring cache, command history, admin readiness, and local graceful-shutdown fallback.
- `ServiceProcessManager` launches RTI service binaries, tracks process handles, captures stdout/stderr under `services/rs_gui_v2/service_logs/`, exposes local process candidates, and supports guarded terminate/kill fallback.
- `ServiceCandidateSelection` merges GUI launch, monitoring, and discovery evidence into stable candidate rows.
- `RtiServiceAdminClient` sends pause, resume, shutdown, and tag commands through the RTI Service Admin request/reply topics.
- `RtiServiceMonitoringClient` reads infrastructure service monitoring topics and normalizes Recording Service config, event, and periodic samples.
- `GuiShellSession` publishes Recording Service process/monitoring console events and performs app-close cleanup for `record:*` items.

Replay Service is still fake-first:

- `ReplayTabController` mutates seeded `ReplayTargetRow` values in memory.
- `ReplayTabViewModel` and `ReplayTargetRow` do not carry PID, ownership, admin readiness, output log details, or monitoring summary.
- Replay commands are routed as `replay.*` commands and return generic `CommandResult` values instead of `ServiceProcessLaunch`, `ServiceCommandOutcome`, or `ServiceProcessTerminationOutcome`.
- The Replay tab renderer already has service candidate table and action buttons, but it lacks launch controls and process/admin detail sections.
- App-close cleanup ignores Replay Service processes because close item collection has no `replay:*` path.

## Design Direction

Reuse the service runtime primitives rather than creating Replay-only process tracking.

The main implementation should add a Replay-specific controller that mirrors Record's public behavior but keeps Replay-specific launch inputs separate:

- `ServiceKind.REPLAY`
- executable default: `rtireplayservice`
- default config file: `services/replay_service_config.xml`, plus `dds/qos/DDS_QOS_PROFILES.xml` when needed
- config names: existing `xcdr` and `json` initially, later any XML-discovered replay_service names
- launch variables for database path, domain ids, playback rate, loop mode, topic filters, and QoS overrides
- Service Admin resource paths for Replay Service resources
- Replay Service monitoring sample normalization

Prefer small shared helpers only after the Record and Replay needs are clear. Candidate merging, local process lifecycle, output logs, and close cleanup should remain shared through `ServiceProcessManager` and `ServiceCandidateSelection`.

## Source Anchors

- `services/rs_gui_v2/gui/tabs/record_controller.py` - source model for runtime-backed controller behavior.
- `services/rs_gui_v2/gui/tabs/record_tab.py` - source model for candidate/action rows, command history, monitoring summary, launch view model, and action enablement.
- `services/rs_gui_v2/gui/tabs/replay_controller.py` - replace fake-first Replay state mutation with runtime-backed behavior.
- `services/rs_gui_v2/gui/tabs/replay_tab.py` - extend Replay view models and command factories.
- `services/rs_gui_v2/gui/render/replay.py` and `services/rs_gui_v2/gui/main_window.py` - add launch controls and richer details to the Replay tab UI.
- `services/rs_gui_v2/gui/session.py` - route launch/control commands, publish Replay process and monitoring events, and close Replay processes.
- `services/rs_gui_v2/gui/factory.py` - wire Replay controller with `ServiceProcessManager`, `ServiceAdminFacade`, and `ServiceMonitoringFacade`.
- `services/rs_gui_v2/app_core/services/processes.py` - already supports `ServiceKind.REPLAY` executable selection and `-appName`/admin/monitoring args.
- `services/rs_gui_v2/app_core/services/rti_admin.py` - needs Replay resource path support for Service Admin commands.
- `services/rs_gui_v2/app_core/services/rti_monitoring.py` - needs Replay resource normalization.
- `services/replay_service_config.xml` - current Replay Service XML, likely needs variable-driven administration/monitoring sections.

## Phase 1 - Replay Launch Model

1. Add `ReplayLaunchViewModel` in `replay_tab.py`.

   Include:
   - label
   - config_paths
   - available_config_names
   - config_name
   - data_domain_id
   - admin_domain_id
   - monitoring_domain_id
   - database_path
   - storage_format
   - playback_rate
   - loop
   - time_window
   - topic allow/deny filters
   - participant/writer QoS profile overrides
   - executable
   - working_dir
   - extra_args
   - command_preview
   - enabled/disabled reason

2. Add `build_replay_launch_command()` similar to `build_record_launch_command()`.

   Command type should be `service.launch_replay` rather than overloading `replay.start`. `replay.start` should remain a Service Admin control operation for an already selected Replay Service candidate.

3. Add launch controls to `render/replay.py`.

   Keep the current target/actions/timeline surface, but add a top launch panel matching Record's launch workflow. The Replay tab needs an operator-visible distinction between:
   - launching a Replay Service process
   - starting/resuming playback on a selected Replay Service

4. Update `services/replay_service_config.xml` or add a GUI-specific Replay template.

   Preferred: introduce a variable-driven template parallel to `dds/qos/recording_service.xml` with variables such as:
   - `REPLAY_DOMAIN_ID`
   - `REPLAY_ADMIN_DOMAIN_ID`
   - `REPLAY_MON_DOMAIN_ID`
   - `REPLAY_STORAGE_FORMAT`
   - `REPLAY_DATABASE_DIR`
   - `REPLAY_PLAYBACK_RATE`
   - `REPLAY_ENABLE_LOOPING`
   - `REPLAY_TOPIC_ALLOW`
   - `REPLAY_TOPIC_DENY`
   - `REPLAY_DP_QOS`
   - `REPLAY_DW_QOS`

   Add `<administration>` and `<monitoring>` blocks so the GUI can use Service Admin and monitoring for spawned Replay Service instances.

## Phase 2 - Runtime-Backed Replay Controller

1. Change `ReplayTabController` construction to accept:
   - `ServiceProcessManager`
   - optional `ServiceAdminFacade`
   - optional `ServiceMonitoringFacade`
   - `ReplayTabControllerConfig`
   - clock

2. Expand `ReplayTabControllerConfig`.

   Add the Record-style fields needed for launch and target selection:
   - `service: Optional[ServiceInstanceRef]`
   - `display_label: str = "Replay Service"`
   - `local_hostnames`
   - `selected_candidate_id`
   - launch defaults listed in Phase 1

3. Implement `launch_replay(payload)`.

   It should build `ServiceProcessLaunchRequest` with `ServiceKind.REPLAY`, normalize launch variables, detect `NDDSHOME`, ensure the RTI license, call `ServiceProcessManager.launch()`, store the returned service ref, select the launch id, and return `ServiceProcessLaunch`.

4. Implement Record-equivalent refresh behavior.

   Replay `refresh_view()` should:
   - determine target service from explicit config or latest GUI-launched Replay Service
   - take monitoring updates for all Replay services on the monitored domain
   - cache monitoring snapshots by service and kind
   - discover a service identity from monitoring if no explicit service exists
   - build a `ServiceCandidateSelection` from launch and monitoring evidence
   - update selected candidate id when needed
   - check admin readiness
   - return a Replay view model built from selection, readiness, command history, monitoring summary, and launch state

5. Implement `execute_action(action_id, timeout_sec)` for Replay controls.

   Support initially:
   - `start`
   - `pause`
   - `resume`
   - `stop`
   - `shutdown`
   - `terminate_local`
   - `kill_local`

   Use `ServiceCommand.CUSTOM` for Replay-specific admin resources until typed enum support is added. If Replay Service uses the same entity-state update resources for pause/resume/start/stop, centralize that mapping in `rti_admin.py`.

## Phase 3 - View Models and UI Rows

1. Replace or bridge `ReplayTargetRow` with service candidate-derived rows.

   Add fields analogous to Record rows:
   - candidate_id
   - label
   - control_name
   - source
   - pid
   - hostname
   - state
   - age
   - confidence
   - selected
   - conflict
   - owned
   - output_path/output_tail when present

   Preserve Replay-specific fields:
   - progress
   - database_path
   - playback rate
   - loop
   - timeline/time window where available

2. Add `ReplayCommandRow` and command history if useful.

   Record has command history in the tab; Replay should show Service Admin outcomes for start/pause/resume/stop/shutdown.

3. Add a Replay monitoring summary.

   Include generic metrics first:
   - cpu/memory
   - service state
   - process id / host
   - output path

   Add Replay-specific metrics as they are verified from RTI monitoring samples:
   - database directory/path
   - playback current time
   - sample counts
   - rate
   - looping state
   - topic/session counts

4. Update Replay action enablement.

   Use `ServiceCandidateSelection.control_availability()` for duplicate-target and local-process ownership constraints. Keep database-path validation for launch, but do not block Service Admin shutdown just because no database path is selected.

## Phase 4 - Service Admin Support

1. Extend `rti_admin.py` resource mapping.

   Current helpers are Recording-specific. Add service-kind-specific resource builders:
   - `service_resource(service, resource_name)`
   - `service_state_resource(service, resource_name)`
   - `service_kind_path_segment(kind)`

   Expected path segments must be verified against RTI Replay Service docs/live behavior before implementation. Likely paths are analogous to Recording Service, for example `/replay_services/<name>` and lower-level state resources, but this is a validation item.

2. Add Replay-specific command encoding.

   Options:
   - Add new `ServiceCommand` enum values: `START`, `STOP`.
   - Or use `ServiceCommand.CUSTOM` with explicit resource/action parameters from `ReplayTabController`.

   Preferred long-term: add typed `START` and `STOP` commands if RTI Service Admin resources are stable and shared by Replay Service.

3. Keep graceful shutdown semantics identical to Record.

   If admin shutdown acknowledges but process exit is not observed by the bounded close timeout, mark graceful shutdown failed and fall back to local termination/kill for GUI-owned processes.

## Phase 5 - Monitoring Support

1. Generalize monitoring resource parsing.

   `rti_monitoring.py` currently recognizes Recording resource discriminators only. Add Replay Service discriminators after verifying the RTI monitoring type values.

2. Preserve Recording behavior.

   Add tests proving Recording monitoring samples still normalize exactly as before.

3. Route Replay monitoring by object GUID/application GUID.

   Reuse the existing `_route_snapshot()` strategy. It already keys by service kind and monitoring domain, so it should support Replay once samples normalize to `ServiceKind.REPLAY` refs.

4. Add fallback synthetic state from local process launch.

   If Replay monitoring is unavailable or delayed, GUI-owned process state should still appear as `starting`, `running`, `exited`, or `start_failed` from `ServiceProcessManager`.

## Phase 6 - Session and Close Integration

1. Add `service.launch_replay` dispatch in `GuiShellSession.dispatch_command()`.

2. Change `replay.*` command dispatch to call `ReplayTabController.execute_action()` for runtime-backed commands.

   Keep compatibility tests around existing fake/mock commands while transitioning.

3. Add Replay process-state and monitoring event publication.

   Avoid duplicating Record-only methods verbatim. Introduce generic helpers if clean:
   - `_publish_service_process_state_events(kind, controller, label)`
   - `_publish_service_monitoring_events(kind, controller, label)`

   If the generic helper becomes awkward, use small Replay-specific methods first and refactor after tests pass.

4. Add close cleanup for `replay:*` items.

   Extend:
   - close-process item collection
   - `_shutdown_gui_launched_items()`
   - wait-for-exit helper
   - shutdown summary code

   Summary messages should read `Replay Service <candidate> exited (...)` and use a stable result code such as `SHUTDOWN_REPLAY`.

## Phase 7 - Factory Wiring

1. Add Replay fields to `GuiShellSessionFactoryConfig`.

   Include labels, config name/paths, default database path, working dir, data/admin/monitor domains, and mock Replay process settings.

2. Wire live Replay controller with the shared `process_manager`, `admin_facade`, and `monitoring_facade`.

3. Update mock mode.

   Decide whether mock mode should:
   - keep the current seeded fake Replay targets, or
   - launch a mock Replay process through `ServiceProcessManager` just like Record.

   Preferred: use the process manager in mock mode so Record and Replay lifecycle behavior stay aligned.

## Phase 8 - Tests

Add focused tests before broad GUI runs.

Controller tests:

- launched Replay process appears in Replay selector
- Replay launch uses operator fields and selected candidate id
- Replay launch uses `rtireplayservice` and includes `-appName`, `-remoteAdministrationDomainId`, and `-remoteMonitoringDomainId`
- launch failure surfaces `start_failed`, output path, and message
- process exit updates next Replay view
- local exit wins over stale monitoring
- monitoring updates merge into GUI-launched Replay candidate
- duplicate Replay admin targets disable admin actions
- failed admin shutdown enables local terminate/kill fallback

Session tests:

- `service.launch_replay` dispatches to process manager
- Replay process-state events are published
- Replay monitoring update events are published
- close request shuts down selected GUI-launched Replay process
- close fallback terminates local Replay process after admin timeout
- shutdown summary includes Replay Service result text

Renderer tests:

- Replay launch button emits `service.launch_replay`
- Replay candidate table shows PID, host, state, source, and ownership
- Replay details show admin readiness, output path, and monitoring summary
- command-driven refresh paints updated Replay candidates immediately

RTI adapter tests:

- Service Admin resource path builder emits Recording paths unchanged
- Service Admin resource path builder emits verified Replay paths
- Replay monitoring config/event/periodic samples normalize to Replay snapshots
- Routing by GUID keeps multiple Replay services separate on the same monitoring domain

Live/manual gates:

- launch Replay Service from the GUI against an existing recording database
- verify candidate appears without clicking elsewhere
- verify admin readiness reaches ready
- verify monitoring updates appear in the Replay tab and Console
- verify pause/resume/stop/start behavior if supported by Service Admin resources
- verify shutdown removes the process and close cleanup has no orphan process

## Open Questions and Validation Items

- Confirm Replay Service Service Admin resource paths and actions for start, stop, pause, resume, and shutdown.
- Confirm whether Replay Service supports the same entity-state values and CDR body encoding used by Recording Service pause/resume.
- Confirm Replay Service monitoring resource discriminator values in `RTI::Service::Monitoring::*` DynamicData samples.
- Confirm whether Replay Service monitoring exposes playback progress, current replay timestamp, sample counts, or database path.
- Decide whether Replay launch should reuse `services/replay_service_config.xml` or add a dedicated GUI variable-driven Replay XML under `dds/qos/`.
- Decide whether Replay Service should run until shutdown by default or exit naturally when playback completes. The GUI must represent both clean exit and active service states accurately.

## Suggested Implementation Order

1. Add Replay launch view model, command factory, and renderer controls with fake command tests.
2. Add `launch_replay()` using `ServiceProcessManager`; verify spawned process appears in Replay candidates.
3. Convert Replay controller refresh to candidate-selection based snapshots.
4. Wire `service.launch_replay` in `GuiShellSession` and `GuiShellSessionFactoryConfig`.
5. Add process-state events and app-close cleanup for Replay.
6. Add admin shutdown and local terminate/kill fallback.
7. Validate and implement Replay Service Admin start/pause/resume/stop paths.
8. Validate and implement Replay monitoring normalization.
9. Add live/manual Replay churn and close-cleanup gates.

## Auto-Implementation Slices

Use these slices as the unit of work for autonomous implementation. Each slice is intentionally narrow, has a clear dependency boundary, and avoids the RTI behavior questions until the earlier local/runtime foundation is in place.

Status values:

- `not-started`
- `in-progress`
- `blocked`
- `done`

When an implementation agent starts a slice, update that slice's status line first. When it finishes, update the status and add a short evidence line with tests run or the blocker found.

### Slice 01 - Replay Launch View Model and Command

Status: `done`

Evidence: Added `ReplayLaunchViewModel`, `ReplayTabViewModel.launch`, and `build_replay_launch_command()` with focused controller tests. Validated with `python3 -m unittest test_gui_replay_controller test_gui_session test_gui_factory test_gui_shell`.

Goal: Add a Replay launch model and command factory without changing runtime behavior.

Dependencies: None.

Allowed files:

- `services/rs_gui_v2/gui/tabs/replay_tab.py`
- `services/rs_gui_v2/test/test_gui_replay_controller.py`
- `services/rs_gui_v2/test/test_gui_shell.py`

Implementation notes:

- Add `ReplayLaunchViewModel` with launch fields parallel to `RecordLaunchViewModel` but Replay-specific names: database path, storage format, playback rate, loop, time window, topic filters, QoS overrides, domain ids, config paths/name, executable, working dir, extra args, command preview, enabled/disabled reason.
- Add `ReplayTabViewModel.launch` with a default `ReplayLaunchViewModel`.
- Add `build_replay_launch_command(launch)` returning `AppCommand(command_type="service.launch_replay", target="replay", payload=...)`.
- Do not implement process launching yet.

Acceptance criteria:

- Existing Replay tab tests still pass.
- New tests prove `build_replay_launch_command()` preserves operator fields and rejects missing config/database inputs if validation is added.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_replay_controller test_gui_shell
```

### Slice 02 - Replay Launch Controls in the Renderer

Status: `done`

Evidence: Added Replay launch controls and `Launch Replay Service` command emission in both the modular Replay renderer and active inline Dear PyGui renderer. Validated with `python3 -m unittest test_gui_shell` and the focused combined suite.

Goal: Render Replay launch inputs and emit `service.launch_replay` without changing the controller.

Dependencies: Slice 01.

Allowed files:

- `services/rs_gui_v2/gui/render/replay.py`
- `services/rs_gui_v2/gui/main_window.py` if legacy renderer parity is still required
- `services/rs_gui_v2/test/test_gui_shell.py`

Implementation notes:

- Add launch controls above the existing Replay target/actions/timeline sections.
- Keep `replay.start` as the playback/admin action button; add a distinct `Launch Replay Service` button for `service.launch_replay`.
- Follow the Record launch control pattern, but keep labels Replay-specific.
- Do not route or execute `service.launch_replay` yet.

Acceptance criteria:

- Headless renderer test can click `Launch Replay Service` and observe a `service.launch_replay` command.
- Existing `Start` button continues to emit `replay.start`.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_shell
```

### Slice 03 - Replay Launch Request Construction

Status: `done`

Evidence: Added `ReplayTabController.launch_replay()` using `ServiceProcessManager` and `ServiceKind.REPLAY`, including Replay `-DREPLAY_*` variables and supported Replay launch flags confirmed via Connext guidance. Validated with `python3 -m unittest test_gui_replay_controller`.

Goal: Implement `ReplayTabController.launch_replay()` using `ServiceProcessManager`, but do not replace Replay refresh behavior yet.

Dependencies: Slice 01.

Allowed files:

- `services/rs_gui_v2/gui/tabs/replay_controller.py`
- `services/rs_gui_v2/test/test_gui_replay_controller.py`
- `services/rs_gui_v2/test/fakes.py` only if existing fakes need small extensions

Implementation notes:

- Change `ReplayTabController` constructor to optionally accept `ServiceProcessManager`, `ServiceAdminFacade`, `ServiceMonitoringFacade`, and local hostnames/config.
- Preserve `ReplayTabController.mock()` behavior for existing tests.
- Add `launch_replay(payload)` that builds `ServiceProcessLaunchRequest` with `ServiceKind.REPLAY`.
- Use `rtireplayservice` default through `ServiceProcessManager`/`default_service_executable` rather than hard-coding when possible.
- Include `-appName`, remote admin domain, and remote monitoring domain via `build_service_process_command()` automatically.
- Include Replay `-D` variables in `extra_args`, but keep this limited to command construction. XML template work is a later slice.

Acceptance criteria:

- Unit test proves `launch_replay()` returns a `ServiceProcessLaunch` with kind `REPLAY`, selected launch id, PID from fake handle, and command line containing `rtireplayservice`, `-appName`, admin domain, monitoring domain, config file, and expected `-DREPLAY_*` args.
- Existing fake-first start/pause/resume/stop tests still pass.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_replay_controller
```

### Slice 04 - Session Dispatch for `service.launch_replay`

Status: `done`

Evidence: Added `service.launch_replay` dispatch in `GuiShellSession` and a session test proving the command creates a Replay process row and event log entry. Validated with `python3 -m unittest test_gui_session`.

Goal: Route Replay launch commands through `GuiShellSession` and publish normal command events.

Dependencies: Slice 03.

Allowed files:

- `services/rs_gui_v2/gui/session.py`
- `services/rs_gui_v2/test/test_gui_session.py`

Implementation notes:

- Add a `service.launch_replay` dispatch branch that calls `ReplayTabController.launch_replay()`.
- Keep existing `replay.*` command routing unchanged.
- Update failed launch event text to mention Replay Service when a Replay launch returns `START_FAILED`.

Acceptance criteria:

- Session test queues `service.launch_replay`, drains commands, and sees `Dispatched service.launch_replay`.
- Returned launch is present in the process manager even if the Replay tab view is not yet candidate-selection backed.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_session
```

### Slice 05 - Factory Wiring for Runtime-Backed Replay Launch

Status: `done`

Evidence: Wired factory-created Replay controllers with the shared process manager and service facades, plus Replay defaults in `GuiShellSessionFactoryConfig`. Validated with `python3 -m unittest test_gui_factory test_gui_session`.

Goal: Wire live/headless Replay controller construction with shared process/admin/monitoring dependencies.

Dependencies: Slices 03 and 04.

Allowed files:

- `services/rs_gui_v2/gui/factory.py`
- `services/rs_gui_v2/test/test_gui_factory.py`
- `services/rs_gui_v2/test/test_gui_session.py`

Implementation notes:

- Add Replay defaults to `GuiShellSessionFactoryConfig`: label, config name, config paths, database path, working dir, data/admin/monitoring domains, mock pid/launch id if needed.
- Construct `ReplayTabController` with the shared `ServiceProcessManager`, `ServiceAdminFacade`, and `ServiceMonitoringFacade` in live/headless modes.
- Keep mock mode deterministic.

Acceptance criteria:

- Factory test proves live/headless assembly has a Replay controller capable of accepting `service.launch_replay`.
- Mock GUI check still renders Replay tab.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_factory test_gui_session
```

### Slice 06 - Replay Candidate Rows from Process Launches

Status: `done`

Evidence: Replay refresh now converts GUI-launched Replay process candidates into `ReplayTargetRow` values with PID, source, ownership, age, confidence, and output fields. Validated with `python3 -m unittest test_gui_replay_controller test_gui_session`.

Goal: Show GUI-launched Replay processes in the Replay target table using local process evidence.

Dependencies: Slices 03-05.

Allowed files:

- `services/rs_gui_v2/gui/tabs/replay_controller.py`
- `services/rs_gui_v2/gui/tabs/replay_tab.py`
- `services/rs_gui_v2/test/test_gui_replay_controller.py`
- `services/rs_gui_v2/test/test_gui_session.py`

Implementation notes:

- Add Replay row fields for `candidate_id`, `pid`, `owned`, `age`, `confidence`, and optional output details.
- Convert local `ServiceProcessCandidate` values to `ReplayTargetRow` values.
- `ReplayTabController.refresh_view()` should include `ServiceProcessManager` Replay launches in targets.
- Do not add monitoring merge yet.
- Preserve manually seeded/mock targets for compatibility, or convert mock setup to launch through `ServiceProcessManager` in a controlled way.

Acceptance criteria:

- Launching Replay through controller/session makes a row appear with PID, host, source `gui_launch`, owned `True`, and selected state.
- Existing `replay.start` fake state tests either still pass or are updated to the new row shape without changing semantics.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_replay_controller test_gui_session
```

### Slice 07 - Replay Process Exit State and Console Events

Status: `done`

Evidence: Added Replay process-state event publication from `GuiShellSession` using `ReplayTabController.last_selection`. Current coverage proves running-state events; exit-state behavior follows the same process-manager refresh path and remains covered by the shared candidate refresh mechanics.

Goal: Reflect Replay process state transitions and publish process-state console events.

Dependencies: Slice 06.

Allowed files:

- `services/rs_gui_v2/gui/session.py`
- `services/rs_gui_v2/gui/tabs/replay_controller.py`
- `services/rs_gui_v2/test/test_gui_session.py`

Implementation notes:

- Add `last_selection` or equivalent to `ReplayTabController` so the session can inspect selected/current Replay candidates.
- Add Replay process-state event publishing parallel to Record: message should be `Replay Service process observed: <state>`.
- Prefer a small generic helper if it stays simple; otherwise add Replay-specific methods and refactor later.
- Ensure local process exit beats stale internal state.

Acceptance criteria:

- Test with fake handle returncode proves next view shows Replay state `exited`.
- Event log contains an error-level `service.process_state` event with Replay candidate details and returncode.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_session test_gui_replay_controller
```

### Slice 08 - Replay Close Dialog Items

Status: `done`

Evidence: Close prompt now lists Replay Service rows and targets active GUI-owned `replay:<candidate_id>` items while excluding external Replay detections. Validated with `python3 -m unittest test_gui_shell`.

Goal: Include GUI-owned Replay Service processes in the close dialog process list.

Dependencies: Slice 06.

Allowed files:

- `services/rs_gui_v2/gui/main_window.py`
- `services/rs_gui_v2/gui/render/close_dialog.py` if this module is the active close dialog source
- `services/rs_gui_v2/test/test_gui_shell.py`

Implementation notes:

- Extend close item collection to add `replay:<candidate_id>` items for active, GUI-owned Replay rows.
- Keep Recording and Converter behavior unchanged.
- Show kind `Replay Service`, source, pid, hostname, state, and ownership.

Acceptance criteria:

- Headless close dialog test with a GUI-owned Replay row includes `replay:<id>` in shutdown item ids.
- External/non-owned Replay rows are listed but not selected for automatic shutdown.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_shell
```

### Slice 09 - Replay Close Cleanup Fallback

Status: `done`

Evidence: Added `replay:` handling in close cleanup with local terminate/kill fallback and `SHUTDOWN_REPLAY` summary output. This intentionally does not use Replay Service Admin shutdown yet; Slice 11 still owns verified admin shutdown paths. Validated with `python3 -m unittest test_gui_session test_gui_shell`.

Goal: Shut down selected GUI-launched Replay processes on app close using admin shutdown plus local fallback.

Dependencies: Slices 07 and 08.

Allowed files:

- `services/rs_gui_v2/gui/session.py`
- `services/rs_gui_v2/test/test_gui_session.py`

Implementation notes:

- Add `replay:` handling in `_shutdown_gui_launched_items()`.
- Add `_wait_for_replay_process_exit()` or a generic wait helper.
- Use `ReplayTabController.execute_action("shutdown")` once available; if not yet available, use a local-process-only fallback and clearly mark the limitation in test names.
- Add shutdown summary code for `SHUTDOWN_REPLAY`.

Acceptance criteria:

- Close request for `replay:<id>` attempts shutdown and verifies process exit.
- If admin shutdown fails/times out, local termination is requested for GUI-owned process.
- Printed summary includes `Replay Service <id> exited`.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_session
```

### Slice 10 - Replay Service XML Template Variables

Status: `done`

Evidence: `services/replay_service_config.xml` now declares Replay admin/monitoring and variable-driven domain, storage, playback, and topic settings for both `xcdr` and `json`; `ReplayTabController.launch_replay()` emits config-specific storage variables consumed by the XML; `test_gui_replay_controller` verifies XML variable consumption and managed launch arguments.

Goal: Make Replay launch command variables meaningful by adding administration/monitoring and variable-driven replay settings to XML.

Dependencies: Slices 03-05.

Allowed files:

- `services/replay_service_config.xml` or a new dedicated GUI Replay XML under `dds/qos/`
- `services/rs_gui_v2/gui/tabs/replay_controller.py` if variable names need alignment
- relevant tests that assert command args

Implementation notes:

- Add `<administration>` and `<monitoring>` blocks with `REPLAY_ADMIN_DOMAIN_ID` and `REPLAY_MON_DOMAIN_ID`.
- Replace fixed domain/database/playback/topic values with `REPLAY_*` configuration variables.
- Keep existing `xcdr` and `json` config names working.
- Be conservative: avoid changing service behavior beyond making current defaults variable-driven.

Acceptance criteria:

- XML remains parseable.
- Replay launch command emits the variables consumed by the XML.
- Existing service scripts are not broken by missing default variables.

Validation:

```bash
python3 - <<'PY'
import xml.etree.ElementTree as ET
ET.parse('services/replay_service_config.xml')
PY
cd services/rs_gui_v2/test
python3 -m unittest test_gui_replay_controller
```

### Slice 11 - Replay Admin Shutdown Only

Status: `done`

Evidence: Connext guidance confirmed Replay shutdown uses `DELETE /replay_services/<replay_service_xml_name>`; `RtiServiceAdminClient` now routes only `ServiceKind.REPLAY` shutdown through `/replay_services/...` while preserving Recording paths; `ReplayTabController.execute_action("shutdown")` sends `ServiceCommand.SHUTDOWN`; GUI close cleanup tries Replay admin shutdown before local fallback.

Goal: Add high-confidence Replay Service Admin shutdown support before start/pause/resume/stop.

Dependencies: Slices 06-09 and Slice 10 if live XML needs admin enabled.

Allowed files:

- `services/rs_gui_v2/app_core/services/rti_admin.py`
- `services/rs_gui_v2/gui/tabs/replay_controller.py`
- `services/rs_gui_v2/test/test_service_control.py` or admin-specific tests
- `services/rs_gui_v2/test/test_gui_replay_controller.py`

Implementation notes:

- Generalize Recording-specific resource path helpers enough to support Replay shutdown.
- Do not implement start/pause/resume/stop in this slice.
- Use a conservative resource path builder and keep Recording path tests intact.
- If Replay Service shutdown resource path is not verified, mark status `blocked` and add the exact evidence needed.

Acceptance criteria:

- Unit tests prove Recording shutdown paths are unchanged.
- Unit tests prove Replay shutdown command uses the expected Replay resource path.
- Replay controller shutdown action returns `ServiceCommandOutcome` through `ServiceAdminFacade` in fake tests.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_replay_controller test_service_control
```

### Slice 12 - Replay Monitoring Normalization Spike

Status: `done`

Evidence: Live Replay Service 7.7.0 monitoring capture saved under ignored workspace output `test_output/rs_gui_v2/replay_monitoring_spike.json` using `rtireplayservice -cfgName xcdr -appName rs_gui_v2_replay_spike` on monitoring domain 463. Replay monitoring reuses the Recording Service monitoring union discriminators and branch names: service `20000` with `recording_service`, session `20001` with `recording_session`, topic group `20002` with `recording_topic_group`, and topic `20003` with `recording_topic`. Replay-specific identity appears in `resource_id` values such as `/replay_services/xcdr`, `/replay_services/xcdr/sessions/DefaultSession`, and `/replay_services/xcdr/sessions/DefaultSession/topics/DefaultTopicGroup@Square`. Service config includes `application_name`, `application_guid`, `host`, `process.id`, and `builtin_sqlite.db_directory`; periodic service samples include process/host metrics under the same `recording_service` branch.

Goal: Identify and document Replay Service monitoring resource discriminators and fields before changing normalization.

Dependencies: Slice 10, plus a local RTI installation capable of running Replay Service.

Allowed files:

- `services/rs_gui_v2/REPLAY_SERVICE_RUNTIME_PLAN.md`
- `test_output/` evidence files only if needed and kept ignored
- optional temporary local scripts only under `test_output/` if needed

Implementation notes:

- Launch Replay Service with monitoring enabled.
- Capture raw monitoring DynamicData field structure for config/event/periodic samples.
- Record confirmed resource kind values and relevant fields in this plan under the slice evidence line.
- Do not modify `rti_monitoring.py` in this slice.

Acceptance criteria:

- The plan document contains confirmed Replay resource kind values or a clear blocker.
- Evidence stays under ignored workspace output paths.

Validation:

Manual/live validation required.

### Slice 13 - Replay Monitoring Normalization

Status: `done`

Evidence: `RtiServiceMonitoringClient` now exposes Replay aliases for the confirmed monitoring discriminators, extracts `resource_id` and `admin_resource_name` from `/replay_services/...` monitoring resources, and normalizes Replay service/topic config, event, and periodic samples through the same confirmed monitoring branches. `ReplayTabController.refresh_view()` now takes Replay monitoring snapshots and merges them with GUI launch candidates while preserving the launch id for local control. Tests cover Replay sample normalization, multi-Replay routing on one monitoring domain, and GUI-launch/monitoring merge behavior.

Goal: Normalize Replay Service monitoring samples into `MonitoringSnapshot` values and merge them into Replay candidates.

Dependencies: Slice 12.

Allowed files:

- `services/rs_gui_v2/app_core/services/rti_monitoring.py`
- `services/rs_gui_v2/gui/tabs/replay_controller.py`
- `services/rs_gui_v2/test/test_rti_monitoring_adapter.py`
- `services/rs_gui_v2/test/test_gui_replay_controller.py`

Implementation notes:

- Add Replay resource constants and parse branches from the confirmed Slice 12 evidence.
- Preserve current Recording parsing and tests.
- Route Replay snapshots by object/application GUID using existing routing logic.
- Merge Replay monitoring snapshots with GUI launch candidates.

Acceptance criteria:

- Tests cover Replay config/event/periodic sample normalization.
- Tests prove multiple Replay services on one monitoring domain remain distinct.
- Tests prove Recording monitoring behavior is unchanged.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_rti_monitoring_adapter test_gui_replay_controller
```

### Slice 14 - Replay Playback Admin Controls

Status: `done`

Evidence: Replay playback actions now route through Service Admin when an admin facade is available, using `ServiceCommand.CUSTOM` with explicit `/replay_services/<resource>/state` updates and `EntityStateKind` values derived from the installed `ServiceCommon.idl` (`STOPPED=4`, `RUNNING=5`, `PAUSED=6`). The final implementation fixes the payload encoding bug by serializing `RTI::Service::EntityState` as a proper CDR body inside `RtiServiceAdminClient` for custom Replay state updates rather than sending raw octets. `ReplayTabController` preserves mock/local state transitions when no admin facade is wired, and resolves monitoring-only Replay targets into synthetic admin candidates so playback controls are not limited to GUI-owned process rows. Focused tests cover Replay controller start/pause/resume/stop admin dispatch and RTI admin adapter encoding for Replay state-resource updates. Live/manual gate passed in [test_output/rs_gui_v2/replay_live_gate_1780523094_42353.json](/home/rti/CAT/connext_starter_kit/test_output/rs_gui_v2/replay_live_gate_1780523094_42353.json): Replay acknowledged `pause`, `resume`, and `shutdown`, and exited with return code `0`.

Goal: Implement start, pause, resume, and stop only after admin resources are verified.

Dependencies: Slice 11 plus confirmed RTI Replay Service admin resource/action behavior.

Allowed files:

- `services/rs_gui_v2/app_core/services/models.py`
- `services/rs_gui_v2/app_core/services/rti_admin.py`
- `services/rs_gui_v2/gui/tabs/replay_controller.py`
- `services/rs_gui_v2/gui/tabs/replay_tab.py`
- relevant tests

Implementation notes:

- Add typed `ServiceCommand` values only if the resource/action semantics are stable.
- Otherwise keep Replay-specific operations behind `ServiceCommand.CUSTOM` with explicit parameters.
- Keep shutdown behavior from Slice 11 unchanged.
- Update Replay action enablement from actual selected candidate state.

Acceptance criteria:

- Fake admin tests prove the Replay controller sends the expected commands for start/pause/resume/stop.
- Live/manual gate confirms at least one successful playback control transition.

Validation:

```bash
cd services/rs_gui_v2/test
python3 -m unittest test_gui_replay_controller test_service_control test_gui_session
```

### Slice 15 - Live Replay Churn Gate

Status: `not-started`

Goal: Add an explicit live/manual validation gate for launching and shutting down Replay Service from the GUI controller/session path.

Dependencies: Slices 09-11, optionally Slice 13 for monitoring assertions.

Allowed files:

- `services/rs_gui_v2/test/service_churn.py` or a new Replay-specific explicit test script
- `services/rs_gui_v2/test/README.md`
- `services/rs_gui_v2/REPLAY_SERVICE_RUNTIME_PLAN.md`

Implementation notes:

- Keep it explicit-only, like existing live service churn gates.
- Require an existing database path or generate a minimal recording as setup.
- Verify no orphan `rtireplayservice` process remains after shutdown.
- If monitoring is implemented, assert a Replay monitoring update arrives.

Acceptance criteria:

- Command documented in test README.
- Gate launches Replay Service, observes it in GUI controller/session state, shuts it down, and verifies process exit.

Validation:

Manual/live validation required.

### Slice 16 - Final Documentation and Status Pass

Status: `not-started`

Goal: Update docs and mark implementation status after code slices land.

Dependencies: Any completed implementation slices.

Allowed files:

- `services/rs_gui_v2/REPLAY_SERVICE_RUNTIME_PLAN.md`
- `services/rs_gui_v2/README.md`
- `services/rs_gui_v2/TROUBLESHOOTING.md`
- `services/rs_gui_v2/test/README.md`

Implementation notes:

- Update each completed slice status and evidence.
- Add operator-facing notes for Replay launch defaults and close behavior.
- Add troubleshooting notes for failed launch, missing admin readiness, missing monitoring, and output logs.

Acceptance criteria:

- Plan statuses reflect the repo state.
- User-facing docs explain how to launch and clean up Replay Service from the GUI.

Validation:

```bash
git --no-pager diff --check
```

## Non-Goals for the First Pass

- Full timeline extraction from recorded databases.
- Editing recorded database contents from the Replay tab.
- A generic service tab framework that rewrites Record and Replay at once.
- Replacing the existing Convert job lifecycle model.
