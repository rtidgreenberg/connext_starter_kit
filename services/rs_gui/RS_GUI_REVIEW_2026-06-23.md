# rs_gui End-to-End Review

Date: 2026-06-23

Scope: `services/rs_gui` with emphasis on simplicity, clarity, DRYness, reusability, and structural simplicity. The replay side was compared directly against the record side, using the record tab as the behavioral oracle for process management and monitoring.

## Executive Summary

The record path is the cleaner implementation. It has a single selection model, a guarded local-termination contract, and a better separation between cached monitoring state and per-refresh monitoring deltas. The replay path has grown a parallel control stack around the same service concepts, and that duplication is now producing behavior drift.

The most important replay-side issue is shutdown behavior: the button-driven replay shutdown path does not follow the record side's guarded "admin shutdown first, verify exit, then allow local termination only on failure" contract. Replay also treats cached monitoring state as if it were new monitoring updates, which can distort monitoring/event reporting. Finally, replay conflict handling is only half-wired: the view model supports duplicate-target warnings, but the controller never populates them.

## Status Update

Resolved after this review:

- Replay shutdown now follows the record-side guarded model closely enough for normal GUI operation.
- Replay monitoring deltas are separated from cached latest monitoring state.
- Replay duplicate-target conflicts are now wired through the shared selection availability model.
- Replay presentation-state text is normalized consistently at the UI/session layer.
- A small structural DRY step is complete: shared monitoring-cache behavior used by record and replay now lives in [gui/tabs/monitoring_cache.py](gui/tabs/monitoring_cache.py).
- Additional shared controller DRY steps are complete: common shutdown-exit polling and candidate display/conflict formatting now live in [gui/tabs/controller_common.py](gui/tabs/controller_common.py).
- Convert subprocess observability is improved: incremental stdout/stderr capture now feeds running progress state instead of relying only on completion-time output.
- The GUI ownership boundary is now explicit in [README.md](README.md): [tk_gui](tk_gui) is the supported shell, while [gui](gui) remains shared controller/session logic plus retained legacy helpers.

Still open:

- Replay still has a parallel controller/view-model control stack rather than building more directly on the record-side selection/action pattern.
- Replay action gating is still materially different from record action gating: replay depends on database selection and playback lifecycle semantics that do not map cleanly onto record's admin/termination availability model, so this layer should not be merged just for DRYness.
- Convert remains subprocess-oriented and still falls back to coarse progress when no parseable process output exists yet.
- The repo still carries both `gui/` and `tk_gui/` surfaces, but the authoritative ownership boundary is now documented; the remaining structural work is reducing or quarantining legacy renderer code over time.

## What The Record Side Gets Right

- Record uses `ServiceCandidateSelection` as the main source of truth for candidate identity and action availability in [gui/tabs/record_controller.py](gui/tabs/record_controller.py) and [gui/tabs/record_tab.py](gui/tabs/record_tab.py).
- Record preserves the difference between fresh monitoring deltas and cached latest state via `last_monitoring_updates` in [gui/tabs/record_controller.py#L119](gui/tabs/record_controller.py#L119) and the update assignment in [gui/tabs/record_controller.py#L145](gui/tabs/record_controller.py#L145).
- Record shutdown waits for observed process exit before treating the shutdown as complete in [gui/tabs/record_controller.py#L362](gui/tabs/record_controller.py#L362).
- Record only enables local termination after graceful shutdown failure, which matches the shared process-manager contract in [app_core/services/processes.py#L448](app_core/services/processes.py#L448).

These are the behaviors replay should converge on.

## Findings

### 1. Replay shutdown bypasses the guarded termination model

Status: Resolved

Severity: High

The replay command path used by the normal UI buttons is routed through `replay.*` commands in [gui/session.py#L254](gui/session.py#L254), which call `ReplayTabController.handle_command()`. In the `replay.shutdown` branch, the controller sends the admin shutdown and then immediately requests local termination for owned processes with `graceful_shutdown_failed=True` in [gui/tabs/replay_controller.py#L296](gui/tabs/replay_controller.py#L296).

That is not how record works. Record performs admin shutdown, waits for process exit, and only exposes local termination if graceful shutdown actually failed in [gui/tabs/record_controller.py#L349](gui/tabs/record_controller.py#L349) and [gui/tabs/record_controller.py#L362](gui/tabs/record_controller.py#L362).

Why this matters:

- Replay violates the intended safety contract encoded in [app_core/services/processes.py#L448](app_core/services/processes.py#L448).
- A successful admin shutdown can still be followed by an unnecessary local SIGTERM request.
- Replay now has two shutdown semantics: `handle_command("replay.shutdown")` and `execute_action("shutdown")`, which is avoidable complexity.

Suggested fix:

- Collapse replay shutdown onto the same model as record: admin shutdown, wait for exit, mark `graceful_shutdown_failed` only on failure/timeout, then allow `terminate_local` and `kill_local` as explicit fallback steps.

### 2. Replay monitoring publishes cached state as if it were fresh updates

Status: Resolved

Severity: High

`ReplayTabController.last_monitoring_updates` returns `_latest_monitoring` in [gui/tabs/replay_controller.py#L206](gui/tabs/replay_controller.py#L206), and `refresh_view()` repopulates `_latest_monitoring` from the entire cache in [gui/tabs/replay_controller.py#L514](gui/tabs/replay_controller.py#L514). Session-level monitoring publication then emits every item in `last_monitoring_updates` on each refresh in [gui/session.py#L587](gui/session.py#L587).

Record does not do this. Record stores true per-refresh deltas in `_last_monitoring_updates` in [gui/tabs/record_controller.py#L119](gui/tabs/record_controller.py#L119) and only publishes those deltas from [gui/session.py#L546](gui/session.py#L546).

Why this matters:

- Replay monitoring evidence can be noisy and repetitive.
- Event consumers cannot distinguish a new monitoring sample from cached state being replayed.
- The replay controller API is misleading: `last_monitoring_updates` is not actually "updates".

Suggested fix:

- Mirror the record controller: keep one field for fresh updates and one for cached latest state.
- Publish only the fresh-update field to the runtime event log.

### 3. Replay duplicate-target conflict handling is effectively dead code

Status: Resolved

Severity: Medium

The replay view model clearly expects conflict-aware behavior. Actions are disabled when `selected_target.conflict` is true in [gui/tabs/replay_tab.py#L377](gui/tabs/replay_tab.py#L377), and diagnostics also check `target.conflict` in [gui/tabs/replay_tab.py#L424](gui/tabs/replay_tab.py#L424).

But the replay controller never populates that field. `_runtime_targets()` builds rows from `_target_from_candidate()` in [gui/tabs/replay_controller.py#L673](gui/tabs/replay_controller.py#L673), and `_target_from_candidate()` leaves `conflict` at its default value.

Record already solves this class of problem by deriving duplicate-admin-target state from `ServiceCandidateSelection.control_availability()` and passing that into row construction in [gui/tabs/record_tab.py#L145](gui/tabs/record_tab.py#L145).

Why this matters:

- Replay can present ambiguous admin targets without warning.
- The UI suggests it supports conflict blocking, but the controller does not supply the data needed to do it.
- This increases the chance of sending admin commands to the wrong service instance.

Suggested fix:

- Reuse the same `ServiceCandidateSelection.control_availability()` signal that record uses.
- Either wire `conflict` from the selection model or remove the replay-only conflict UI until it is real.

### 4. Replay has a parallel control stack instead of reusing the record-side service-selection model

Status: Partially resolved

Severity: Medium

Record is organized around a shared service abstraction: `ServiceCandidateSelection` plus app-core process/admin/monitoring facades. Replay partly uses those same pieces, but layers a second target model on top: `_targets`, `_state_overrides`, `ReplayTargetRow`, `_runtime_targets()`, `_selected_candidate_for_target()`, `_set_target_state()`, and a separate action-enable function in [gui/tabs/replay_controller.py](gui/tabs/replay_controller.py) and [gui/tabs/replay_tab.py](gui/tabs/replay_tab.py).

That duplication is already leaking into behavior drift:

- Different shutdown semantics between record and replay.
- Different monitoring-update semantics between record and replay.
- Different action-policy inputs: record gates actions from `ServiceControlAvailability`, while replay also depends on database-path presence and playback lifecycle states such as `start`, `stop`, and `resume`.

Why this matters:

- The replay controller is harder to reason about because state exists in both `ServiceProcessCandidate` and `ReplayTargetRow` forms.
- Each lifecycle rule must now be implemented twice.
- Reusability is lower because the record-side abstractions are not the actual shared abstraction.

Progress made:

- Shared monitoring-cache operations are now extracted into [gui/tabs/monitoring_cache.py](gui/tabs/monitoring_cache.py), which removes one concrete area of controller duplication.
- Shared controller helpers in [gui/tabs/controller_common.py](gui/tabs/controller_common.py) now cover target resolution, readiness, shutdown-exit polling, candidate display fields, and duplicate-target conflict detection.
- Comparison of the remaining action-policy layer shows one safe shared seam and one unsafe one: duplicate-target conflict detection is now shared, but the replay action table is still semantically different enough that forcing it into the record model would hide real behavior differences.
- The larger replay-specific target/state control stack still exists.

Suggested fix:

- Make replay build from `ServiceCandidateSelection` the same way record does.
- Keep extracting shared candidate and availability primitives, but do not merge the full record/replay action-enable functions until replay no longer requires separate database/playback-state gating.

### 5. rs_gui still carries two GUI stacks, which increases structural complexity

Status: Partially resolved

Severity: Medium

The repository still contains both the newer `gui/` path and the older `tk_gui/` path, each with tab implementations and tests. The split is visible in [gui](gui), [tk_gui](tk_gui), and the corresponding `test_gui_*` and `test_tk_*` suites under [test](test).

Why this matters:

- The same workflow concepts exist in two UI trees.
- Review and maintenance cost is higher because ownership boundaries are less obvious.
- It is harder to tell which layer is authoritative when evaluating bugs or adding features.

Suggested fix:

- Explicitly mark one stack as legacy or migration-only.
- Once the remaining migration work is complete, remove the duplicate surface area rather than continuing to evolve both.

Progress made:

- [README.md](README.md) now marks [tk_gui](tk_gui) as the supported operator shell.
- [README.md](README.md) also clarifies that [gui](gui) remains the shared session/controller layer and should not grow new legacy renderer work.

### 6. Convert cancellation and progress reporting are not yet fully backed by runtime feedback

Status: Partially resolved

Severity: Medium

The convert path is subprocess-oriented rather than backed by a richer converter job-control API, but two concrete gaps are now fixed. `convert.cancel` now requests termination of the tracked local converter subprocess instead of only flipping GUI state, `_poll_job_status()` uses the existing progress parser when running output text is available in [gui/tabs/convert_controller.py](gui/tabs/convert_controller.py), and running subprocess output is now captured incrementally so progress parsing can use live stdout/stderr rather than only completion-time output.

The focused convert tests now cover local termination on cancel, parsed running progress when output is available, and incremental subprocess output capture, but the controller still falls back to a generic in-flight value when there is no parseable output yet.

Why this matters:

- The convert path is still fundamentally process-oriented, so its observability is weaker than a true job/status API would provide.
- Running-job progress is only as good as the process output the controller can observe at poll time.

Suggested fix:

- Keep local subprocess termination as the primary cancel mechanism unless/until a real converter job-control API exists.
- If higher-fidelity progress is needed, add incremental stdout/stderr capture or a real converter monitoring/status channel rather than relying on periodic process polling alone.

## Replay vs Record Comparison

### Process management

- Record: one main action path, guarded local termination, verified shutdown exit, explicit command history.
- Replay: split between `handle_command()` and `execute_action()`, immediate or near-immediate local termination fallback in common paths, and duplicated state held outside the shared candidate model.

### Monitoring

- Record: clear distinction between new updates and latest cached state.
- Replay: cached latest state is exposed as update data, which blurs monitoring semantics.

### UI action safety

- Record: duplicate-target conflicts are surfaced through the shared availability model.
- Replay: duplicate-target conflicts now come from the same shared availability model, but the rest of the action gating still depends on replay-specific database and playback-state prerequisites.

### Structural simplicity

- Record: closer to a reusable pattern.
- Replay: extra controller-local state and target mapping create complexity without adding a distinct abstraction benefit.

## Recommended Refactor Order

1. Make replay shutdown follow the record contract exactly.
2. Split replay monitoring deltas from cached monitoring state.
3. Replace replay-local conflict/state gating with `ServiceCandidateSelection`-based availability.
4. Keep collapsing duplicated record/replay tab control logic into shared helpers, but stop at primitive predicates and row formatting until replay's action model converges further.
5. Retire or quarantine the legacy GUI stack.

## Prioritized Implementation Plan

## Demo-Scope Priorities

For this repository's current purpose, the highest-value work is the DDS-facing control behavior, not full production-style cleanup. If time is limited, prioritize in this order:

1. Replay DDS lifecycle correctness: keep replay admin targeting, shutdown behavior, and monitoring semantics aligned with the record-side oracle.
2. Replay state-model simplification only where it reduces DDS ambiguity: remove replay-local mirrored state when it improves service identity, state, or command routing clarity.
3. Convert observability only if it affects the demo path: improve progress fidelity if convert is part of the DDS story being shown.
4. GUI-surface cleanup last: defer `gui/` versus `tk_gui/` consolidation until the DDS-critical behavior is stable.

That means the standard for "best practice" should be highest where the app demonstrates DDS control, monitoring, and lifecycle management, and lower for purely structural or non-demo-facing cleanup.

### Priority 1: Replay model convergence

Goal:

- Reduce the replay-only control stack without forcing replay into record abstractions that do not fit yet.

Scope:

- Keep `ServiceCandidateSelection` as the authoritative source for replay candidate identity and conflict state.
- Continue extracting shared replay/record primitives only where semantics already match: target resolution, readiness, conflict detection, row metadata, shutdown-exit polling.
- Leave replay action gating separate until the replay workflow no longer depends on distinct database and playback-state prerequisites.

Concrete next steps:

1. Remove one replay-local state hop at a time, starting with any remaining logic that mirrors candidate state into `ReplayTargetRow` only for controller bookkeeping.
2. Prefer deriving display state from candidate data plus narrow overrides, rather than growing `_targets` or `_state_overrides` further.
3. Add focused tests whenever a replay-local state holder is removed, especially around selection, start/stop, and shutdown transitions.

Stop condition:

- Stop extracting when the next candidate abstraction would need to encode replay-only playback semantics inside shared record/replay helpers.

### Priority 2: Convert observability improvement

Goal:

- Improve confidence in convert job progress without redesigning the convert path around a nonexistent backend job API.

Scope:

- Keep local subprocess management as the primary execution/cancellation mechanism.
- Improve progress fidelity only through process-output capture or another authoritative local signal.

Concrete next steps:

1. Add incremental stdout/stderr capture so progress parsing does not depend only on terminal completion or static stream snapshots.
2. Store the latest parsed progress evidence with the submission record, so polling can reuse it deterministically.
3. Expand convert tests around partial output, no-output fallback, and long-running process updates.

Stop condition:

- Stop if the next increment requires inventing a fake remote job-control protocol rather than improving the existing local-process model.

### Priority 3: GUI-surface simplification decision

Goal:

- Reduce maintenance ambiguity between `gui/` and `tk_gui/`.

Scope:

- Make an explicit repository decision before more feature work lands in both trees.

Concrete next steps:

1. Mark one stack as primary and one as legacy or migration-only in repo docs.
2. Freeze new feature work in the legacy stack except for break-fix changes.
3. Once replay/convert convergence stabilizes in the primary stack, remove or quarantine the duplicate surface.

Stop condition:

- Stop short of deletion until there is a clear owner decision on which GUI stack remains authoritative.

## Validation Notes

I ran focused replay/record/session tests with:

```bash
cd services/rs_gui
PYTHONPATH="$PWD:$PWD/test" python -m unittest test.test_gui_replay_controller test.test_record_tab_controller test.test_gui_session
```

Result:

- The targeted lifecycle and replay-focused session tests now pass for the fixed replay behaviors.
- The replay state-casing mismatch previously noted in [test/test_gui_session.py#L439](test/test_gui_session.py#L439) has been resolved.

I also ran focused convert tests with:

```bash
cd services/rs_gui
PYTHONPATH="$PWD:$PWD/test" python3 -m unittest test.test_gui_convert_controller test.test_gui_convert_phase5 test.test_gui_convert_phase6 test.test_gui_convert_phase7
```

Result:

- The convert controller now passes targeted tests for cancel-driven local termination, parsed running progress, and incremental subprocess output capture.