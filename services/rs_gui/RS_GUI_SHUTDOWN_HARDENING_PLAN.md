# rs_gui Shutdown Hardening Plan

**Created:** 2026-08-05
**Trigger:** Replay-side freeze after launch → stop → close app (session PID 23012)
**Scope:** Make application close deterministic, observable, and cheap. Stop polling dead services.

---

## 1. Evidence

Source: `rs_gui_logs/rs_gui_20260805_155003_23012.jsonl` (12,300 events, 15:50:03 → 16:03:14).

| Time | Event |
|---|---|
| 15:56:31 | `service.launch_replay` → `STARTED` 15:56:41 |
| 15:57:29 | `replay.stop` → `STOPPED` 15:57:30, **process still `alive: true`** |
| 15:58:12 | `replay.shutdown` (`send_command … timeout=None`) |
| 15:58:23 | Replay process observed `exited`, `alive: false` |
| 15:58:23 → 16:03:14 | **4m51s** of `check_readiness service='replay_service_93712050'` → `"Waiting for Service Admin endpoints"`, ~50 cycles/min, against a process that no longer exists |
| 16:03:14.252 | Log ends at a clean cycle boundary — process force-killed |

Key negative evidence: **no `gui.close_requested`, no `gui.close_completed`, no
`runtime.lifecycle_changed → stopping`.** `_EventLogWriter.write` opens, appends and closes
the file per event (`app_core/runtime.py:218-224`), so nothing was lost to buffering. The
close path never reached its first log statement.

Measured refresh cost: single `after` chain (min inter-tick gap always ~254 ms = the configured
interval, so **not** a timer storm). A full cycle took ~1.16 s in 15:59–16:01, of which ~910 ms
was blocking work on the Tk thread — the UI was unresponsive **~78% of the time** before the
operator ever clicked close.

### Root causes addressed by this plan

| # | Cause | Location |
|---|---|---|
| A | `close()` has no `try/finally`; any exception on the close path skips `destroy()`, leaving an unclosable window with a live refresh loop | `tk_gui/main_window.py:187-190` |
| B | Close runs `asyncio.run(...)` on the Tk callback thread with no visible feedback | `tk_gui/main_window.py:124`, `gui/session.py:304-312` |
| C | `gui.close_requested` is published *after* `_resolve_gui_launched_item_ids()` does blocking DDS work, so a hang or raise leaves zero forensic trail | `gui/session.py:319-330` |
| D | Close-target resolution filters on the *service* state string, which includes `"stopped"`. A replay service that is stopped but whose **process is still alive** is skipped and orphaned — exactly the operator's sequence | `gui/session.py:364,373` |
| E | Admin readiness is polled for services that have exited; only `service.name` is checked | `gui/tabs/controller_common.py:98-108`, `replay_controller.py:550`, `record_controller.py:182` |

### Deferred (documented, not in this plan)

- Move DDS off the Tk thread: one persistent asyncio loop + one shared executor instead of
  `asyncio.run()` per 250 ms tick (`gui/session.py:137-144`, `rti_admin.py:119-121`).
- Close DDS entities on shutdown. `RtiServiceAdminClient.close_sync()` exists
  (`rti_admin.py:111-117`) but nothing calls it; `runtime.shutdown()` only cancels asyncio
  tasks (`runtime.py:77-98`).
- Bound interactive admin commands. `DEFAULT_DISCOVERY_TIMEOUT_SEC` /
  `DEFAULT_REPLY_TIMEOUT_SEC` are both `60.0` and the Shutdown button passes `timeout=None`,
  so `_send_command_sync` can block ~120 s (`rti_admin.py:54-56`).
- Buffer debug logging: `makedirs` + `open` + `write` + `close` per event under a global lock,
  from both the Tk thread and DDS executor threads (`app_core/debug_log.py:44-52`).
- Age out stale exited candidates entirely (P4 removes the *cost*, not the row).

---

## 2. Work items

### P1 — The window always closes
`tk_gui/main_window.py`

1. Re-entry guard (`_closing`) so a second click on X during teardown is a no-op.
2. Stop the refresh bridge **before** invoking `close_handler`, so no `after` tick can
   re-enter app-core mid-teardown.
3. Wrap `close_handler()` in `try/except BaseException` + `finally: self.destroy()`. The window
   is destroyed whether cleanup succeeds, raises, or is interrupted. Log the traceback via
   `dbg_exc`.
4. Make `destroy()` idempotent and exception-tolerant.
5. Visible feedback before blocking: status line + title → "shutting down services…", watch
   cursor, `update_idletasks()` so Tk paints it.
6. **Close watchdog.** A `threading.Timer` armed before `close_handler` runs. If the deadline
   expires, the main thread is wedged inside a non-cancellable native DDS call, so: log
   `gui.close_watchdog_expired`, force-kill GUI-launched child processes, then `os._exit`.
   Configurable via `RS_GUI_CLOSE_WATCHDOG_SEC` (default `15.0`; `0`/negative disables).
   Rationale: the alternative on this path is the current unclosable window plus orphaned
   services. `asyncio.wait_for` cannot help — `run_in_executor` work is not cancellable and
   `asyncio.run` joins the default executor on exit (no `timeout` param before Python 3.12).

**Acceptance:** with a `close_handler` that raises, and with one that sleeps past the watchdog,
the window still goes away and the log records why.

### P2 — Close path fully instrumented
`gui/session.py`

Publish `gui.close_requested` **first**, before any resolve work, then emit an event at every
step so a future freeze is diagnosable from the JSONL alone:

| Event | When |
|---|---|
| `gui.close_requested` | Immediately on entry, before any DDS work |
| `gui.close_resolving` | Before `_resolve_gui_launched_item_ids()` |
| `gui.close_targets_resolved` | After resolve, with the resolved item ids |
| `gui.close_step` | Per cleanup action (`admin_shutdown`, `terminate_local`, `kill_local`, exit observed) with kind, candidate id, status |
| `gui.close_completed` | Existing — after cleanup, before runtime shutdown |
| `gui.runtime_shutdown_started` | Before `await self._runtime.shutdown()` |
| `gui.close_finished` | After runtime shutdown returns |
| `gui.close_failed` | On any exception, with traceback, before re-raising |
| `gui.close_watchdog_expired` | From the P1 watchdog thread |
| `gui.close_forced` | Per process killed by the watchdog |

Also wrap the sync `handle_close_request()` wrapper so a failure inside `asyncio.run` still
produces `gui.close_failed`.

**Acceptance:** a normal close writes `close_requested → resolving → targets_resolved → step* →
close_completed → runtime_shutdown_started → close_finished`. A raising close writes
`close_requested … close_failed` with a traceback.

### P3 — Resolve close targets by process liveness
`gui/session.py:356-391`

`_resolve_gui_launched_item_ids` currently skips any candidate whose state string is in
`_EXITED_STATES`, which contains `"stopped"`. For replay, `"stopped"` means *the service is
stopped*, not *the process is gone* — the 15:57:30 log entry shows `observed: stopped` with
`alive: true`. Such a process is currently left running when the app closes.

Switch both branches to the controllers' backing candidates (`last_selection.candidates`,
already exposed on both controllers) and select on `candidate.owns_process and candidate.alive`.
`alive` is the merged liveness signal maintained by `candidates.py:286`.

**Acceptance:** a GUI-launched replay service that has been stopped but not shut down is
included in the close targets and terminated.

### P4 — Stop polling dead services
`gui/tabs/controller_common.py`, `replay_controller.py`, `record_controller.py`

1. Add canonical `EXITED_SERVICE_STATES` (union of the three sets currently duplicated across
   `session.py:23`, `candidates.py:373`, `replay_controller.py:777`) plus a
   `all_candidate_states_exited(states)` helper to `controller_common.py`. Have `session.py`
   alias it rather than keep its own copy.
2. Guard `readiness_for_service` with an `active` flag: skip the admin round trip and return
   the last known readiness when the caller reports that every known candidate has exited.
3. In both controllers, compute the candidate selection **before** the readiness call (neither
   `_runtime_targets` nor `_selection` depends on readiness, so the reorder is safe) and pass
   the liveness verdict down.

Deliberately conservative: readiness is suppressed only when candidates exist **and all of them
are exited**. With no candidates yet — a service being launched, or an external service being
discovered — readiness still runs, so discovery is unaffected.

**Acceptance:** after a service exits, no further `check_readiness` for it appears in the log,
and per-cycle cost drops. Discovery of a not-yet-seen service still works.

### P5 — Tests
`test/`

- `close()` destroys the window when `close_handler` raises.
- `close()` is re-entrant-safe.
- `close()` stops the refresh bridge before calling `close_handler`.
- Watchdog fires and invokes the force-close hook (injected, no `os._exit` in test).
- Close emits the full event sequence, in order.
- Close emits `gui.close_failed` with a traceback on failure.
- A stopped-but-alive GUI-launched replay target is resolved as a close target.
- Readiness is skipped when all candidates are exited; still runs when none are known.

Baseline before changes: 66 passing in
`test_gui_session test_tk_shell_smoke test_tk_refresh test_gui_replay_controller test_record_tab_controller`.
Full suite: `test/run_all_tests.py`.

---

## 3. Order of work

P1 → P2 → P3 → P4 → P5, running the targeted suite after each. P1 and P2 are the ones that turn
this class of failure from "unclosable window, no evidence" into "closes, with a log trail".

---

## 4. Outcome (2026-08-05)

All five items implemented, then self-reviewed (§5). Full suite: **421 tests, OK.**

### Changed

| File | Change |
|---|---|
| `tk_gui/main_window.py` | `close()` rewritten: `_closing` re-entry guard, refresh bridge stopped first, `close_handler` wrapped in `try/except BaseException` + `finally: destroy()`, `destroy()` idempotent and exception-tolerant, `_show_closing_state()` paints "shutting down services…" with a watch cursor, `_start_close_watchdog()` arms the deadline. `_exit_process` is a seam for tests. |
| `tk_gui/app.py` | Plumbs `force_close_handler` through both builders; the session shell wires it to `session.force_close_gui_launched`. |
| `gui/session.py` | `gui.close_requested` now published before any DDS work; full event trail (table below); `gui.close_failed` on any exception, published once (`_close_failure_published` de-dupes the sync wrapper); new `force_close_gui_launched()`; `_resolve_gui_launched_item_ids` now reads controller candidates and selects on `owns_process and alive` via `_is_live_gui_launched`; dead `_EXITED_STATES` removed. |
| `gui/tabs/controller_common.py` | `PROCESS_EXITED_STATES`, `candidates_all_exited()`, and a `candidates` argument on `readiness_for_service` that short-circuits to `UNAVAILABLE` / "Service process has exited". |
| `gui/tabs/record_controller.py`, `gui/tabs/replay_controller.py` | Candidate resolution moved ahead of the readiness call; readiness now receives the candidates; `process_manager` exposed as a property. |
| `test/test_shutdown_hardening.py` | New: 29 tests across the four areas. |

### Close event trail

`gui.close_requested` → `gui.close_resolving` → `gui.close_targets_resolved` →
`gui.close_completed` → `gui.runtime_shutdown_started` → `gui.close_finished`.
Failure paths add `gui.close_failed` (with `error`, `error_type`, and a `dbg_exc`
traceback). The watchdog adds `gui.close_watchdog_expired` plus one
`gui.close_forced` per process killed. `gui.close_resolving` /
`gui.close_targets_resolved` are skipped when the caller passes explicit targets.

To confirm a clean close in future logs:

```bash
python3 -c "
import json,sys
for line in open(sys.argv[1]):
    e=json.loads(line)
    if e['event_type'].startswith('gui.close') or e['event_type']=='gui.runtime_shutdown_started':
        print(e['created_at'], e['event_type'], e['payload'].get('message',''))
" rs_gui_logs/<session>.jsonl
```

### Additional bug found while implementing P3

`_resolve_gui_launched_item_ids` filtered on the service state string, and that set
contained `"stopped"`. A Replay Service that had been stopped but whose process was
still alive was therefore **excluded from close cleanup and left running** — the
2026-08-05 session hit exactly this (15:57:30: `observed: stopped`, `alive: true`).
Now keyed off `candidate.alive`. Covered by
`test_stopped_replay_target_is_still_resolved_for_shutdown`.

### Close watchdog

`RS_GUI_CLOSE_WATCHDOG_SEC`, default `15.0`; `0` or negative disables it. On expiry:
log, kill GUI-launched child processes through the local process handles (no DDS
calls, since the wedge is in DDS), then `os._exit(3)`. This is a hard exit by
design — the alternative on that path is the unclosable window plus orphaned
services that prompted this work.

### Test-suite note

Two live-DDS tests (`test_gui_session_live_integration`:
`test_default_gui_launch_receives_live_monitoring_current_file`,
`test_live_publisher_recording_file_size_increases`) failed on a first full-suite run
that took 234s, and passed both in isolation and on a re-run of the same code that
took 119s. Their 12–15s budgets for live monitoring discovery expire under CPU
contention. Pre-existing flakiness, unrelated to these changes — but worth raising
the budgets or marking them load-sensitive.

---

## 5. Code review of §4 (2026-08-05)

Three issues found in the new code and fixed; two verified non-issues recorded so
they are not re-litigated.

**Fixed — watchdog could hard-exit a successful close.** `threading.Timer.cancel()`
is a no-op once the timer has already fired, so a close landing near the 15s
deadline would run `_on_close_watchdog` anyway: `os._exit(3)` instead of a clean
exit, `destroy()` skipped, and misleading `close_watchdog_expired` /
`close_forced` events claiming a wedge that never happened. A close doing two 3s
admin shutdowns plus reap waits and runtime teardown can plausibly land there.
Now `_close_handler_done` is set under `_close_lock` before `cancel()`, and the
watchdog callback returns early if it sees it. Regression test:
`test_watchdog_that_fires_after_cleanup_finished_does_not_exit`.

**Fixed — `force_close_gui_launched` overstated what it killed.** It appended every
candidate to its result regardless of outcome, so a missing process handle
(`NOT_FOUND`) or an already-dead process (`ALREADY_EXITED`) was reported as killed.
Now only `outcome.ok` (status `REQUESTED`) counts; every attempt is still logged
with its real status in the `gui.close_forced` payload.

**Fixed — a failed close exited 0.** Since P1 makes the window always destroy
itself, a cleanup failure previously became invisible to the launcher. `close()`
now sets `close_failed`, and `run_tk_session_shell` returns 1 when set. Tests:
`test_close_destroys_window_when_close_handler_raises`,
`test_successful_close_does_not_flag_failure`.

**Verified non-issue — the P4 reorder is safe.** `_last_readiness` is only ever
assigned, never read by `_selection` or `_runtime_targets`, so moving candidate
resolution ahead of the readiness `await` cannot change either result.

**Verified non-issue — `replay:{candidate_id}` matches the old `replay:{target_id}`.**
`_target_from_candidate` sets `target_id=candidate.candidate_id`
(`replay_controller.py:794`), so switching P3 from view rows to backing candidates
keeps the item-id format that `_shutdown_gui_launched_items` and
`select_target()` expect.

**Accepted risk — cross-thread event publishing.** `force_close_gui_launched` runs
on the watchdog thread and publishes events. `AppRuntime.publish_event` uses a
`queue.Queue` (thread-safe) and `_EventLogWriter.write` does one small
append-mode write, so interleaving is not a practical concern on this path — and
this only runs when the process is about to be killed anyway.

**Known cosmetic gap — the watchdog test's exit stub returns.** In production
`os._exit` never returns, so the code after `_exit_process` is unreachable;
under the test seam it continues into `destroy()`. The test asserts wiring, not
that post-exit behavior is meaningful.

### Still deferred

The four items in §1 "Deferred" are unchanged: DDS off the Tk thread, closing DDS
entities on shutdown, bounding interactive admin timeouts, and buffering debug
logging. The first two are the remaining structural risks — the ~78%
UI-unresponsiveness and the participants that are never closed at exit.
