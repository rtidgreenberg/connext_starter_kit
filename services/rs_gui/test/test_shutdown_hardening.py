#!/usr/bin/env python3
"""Tests for rs_gui shutdown hardening.

Covers the regressions behind the 2026-08-05 replay-side freeze: a close that
never destroyed its window, a close that left no forensic trail, close targets
resolved from service state instead of process liveness, and admin readiness
polled forever against processes that had already exited.

See RS_GUI_SHUTDOWN_HARDENING_PLAN.md.
"""

import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppRuntime
from app_core.services import (
    AdminReadiness,
    AdminReadinessStatus,
    FakeServiceAdminClient,
    ServiceAdminFacade,
    ServiceCandidateSource,
    ServiceInstanceRef,
    ServiceKind,
    ServiceProcessCandidate,
    ServiceProcessManager,
)
from gui.session import _is_live_gui_launched
from gui.tabs import ReplayTabController, ReplayTabControllerConfig
from gui.tabs.controller_common import candidates_all_exited, readiness_for_service
from tk_gui import TkinterUnavailable, build_tk_placeholder_shell

from fakes import FakeHandle, FakeSpawner
from test_gui_session import build_session, make_replay_database_dir


def _candidate(
        candidate_id: str = "cand-1",
        alive: bool = True,
        observed_state: str = "running",
        owns_process: bool = True,
) -> ServiceProcessCandidate:
    return ServiceProcessCandidate(
        candidate_id=candidate_id,
        service=ServiceInstanceRef(ServiceKind.REPLAY, "replay_service_1"),
        source=ServiceCandidateSource.GUI_LAUNCH,
        alive=alive,
        observed_state=observed_state,
        owns_process=owns_process,
    )


class _RecordingBridge:
    """Stand-in refresh bridge that records when it was stopped."""

    def __init__(self, order):
        self._order = order
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        self._order.append("refresh_stopped")

    def start(self):
        pass


class _BoomBridge:
    def stop(self):
        raise RuntimeError("bridge stop exploded")


class TestTkCloseAlwaysDestroys(unittest.TestCase):
    """P1: the window goes away whatever the close handler does."""

    def _shell(self, **kwargs):
        try:
            return build_tk_placeholder_shell(workspace_name="Close Regression", **kwargs)
        except TkinterUnavailable as exc:
            self.skipTest(str(exc))

    def test_close_destroys_window_when_close_handler_raises(self):
        def _boom():
            raise RuntimeError("cleanup exploded")

        shell = self._shell(close_handler=_boom)
        # Must not propagate, and must still tear the window down. Before the fix
        # this left a live window with a running refresh loop and no way to exit.
        shell.close()
        self.assertTrue(shell._destroyed)
        # ...but the failure must still be visible to the caller.
        self.assertTrue(shell.close_failed)

    def test_successful_close_does_not_flag_failure(self):
        shell = self._shell(close_handler=lambda: None)
        shell.close()
        self.assertFalse(shell.close_failed)

    def test_close_destroys_window_on_base_exception(self):
        def _boom():
            raise KeyboardInterrupt()

        shell = self._shell(close_handler=_boom)
        shell.close()
        self.assertTrue(shell._destroyed)

    def test_close_survives_refresh_bridge_failure(self):
        calls = []
        shell = self._shell(close_handler=lambda: calls.append("handler"))
        shell._refresh_bridge = _BoomBridge()
        shell.close()
        self.assertEqual(calls, ["handler"])
        self.assertTrue(shell._destroyed)

    def test_close_is_reentrant_safe(self):
        calls = []
        shell = self._shell(close_handler=lambda: calls.append("handler"))
        shell.close()
        shell.close()
        shell.close()
        self.assertEqual(calls, ["handler"])

    def test_close_stops_refresh_loop_before_running_handler(self):
        order = []
        shell = self._shell(close_handler=lambda: order.append("handler"))
        bridge = _RecordingBridge(order)
        shell._refresh_bridge = bridge
        shell.close()
        # Ordering matters: a pending after() tick must not be able to re-enter
        # app-core while its services are being torn down. destroy() stops the
        # bridge again, which is harmless.
        self.assertEqual(order[:2], ["refresh_stopped", "handler"])
        self.assertGreaterEqual(bridge.stop_calls, 1)

    def test_destroy_is_idempotent(self):
        shell = self._shell()
        shell.destroy()
        shell.destroy()
        self.assertTrue(shell._destroyed)

    def test_close_watchdog_forces_shutdown_and_exits(self):
        forced = []
        exits = []

        def _slow_close():
            time.sleep(0.6)

        shell = self._shell(
            close_handler=_slow_close,
            force_close_handler=lambda deadline: forced.append(deadline),
        )
        shell.close_watchdog_sec = 0.05
        shell._exit_process = exits.append
        shell.close()

        self.assertEqual(forced, [0.05])
        self.assertEqual(exits, [3])
        self.assertTrue(shell._destroyed)

    def test_close_watchdog_does_not_fire_on_a_prompt_close(self):
        forced = []
        exits = []
        shell = self._shell(
            close_handler=lambda: None,
            force_close_handler=lambda deadline: forced.append(deadline),
        )
        shell.close_watchdog_sec = 5.0
        shell._exit_process = exits.append
        shell.close()
        time.sleep(0.2)
        self.assertEqual(forced, [])
        self.assertEqual(exits, [])

    def test_watchdog_that_fires_after_cleanup_finished_does_not_exit(self):
        forced = []
        exits = []
        shell = self._shell(
            close_handler=lambda: None,
            force_close_handler=lambda deadline: forced.append(deadline),
        )
        shell._exit_process = exits.append
        shell.close()

        # Timer.cancel() is a no-op once the timer has fired, so the callback can
        # still run after a successful close. It must not hard-exit the process.
        shell._on_close_watchdog(15.0)

        self.assertEqual(forced, [])
        self.assertEqual(exits, [])

    def test_watchdog_disabled_when_deadline_is_not_positive(self):
        forced = []
        shell = self._shell(
            close_handler=lambda: time.sleep(0.2),
            force_close_handler=lambda deadline: forced.append(deadline),
        )
        shell.close_watchdog_sec = 0.0
        shell._exit_process = lambda code: forced.append(("exit", code))
        shell.close()
        self.assertEqual(forced, [])


class TestCloseEventTrail(unittest.IsolatedAsyncioTestCase):
    """P2: every close publishes an ordered, greppable event trail."""

    async def test_close_publishes_full_event_sequence(self):
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime)
        await session.next_view_async(process_commands=False)

        with redirect_stdout(StringIO()):
            await session.handle_close_request_async("shutdown_gui_launched", ())

        types = [event.event_type for event in runtime.drain_events()]
        close_types = [name for name in types if name.startswith("gui.close") or name == "gui.runtime_shutdown_started"]
        self.assertEqual(close_types, [
            "gui.close_requested",
            "gui.close_resolving",
            "gui.close_targets_resolved",
            "gui.close_completed",
            "gui.runtime_shutdown_started",
            "gui.close_finished",
        ])

    async def test_close_requested_precedes_target_resolution(self):
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime)
        await session.next_view_async(process_commands=False)

        with redirect_stdout(StringIO()):
            await session.handle_close_request_async("shutdown_gui_launched", ())

        events = runtime.drain_events()
        requested = next(e for e in events if e.event_type == "gui.close_requested")
        resolved = next(e for e in events if e.event_type == "gui.close_targets_resolved")
        # The freeze produced no close event at all because the original code did
        # its DDS resolve work first. Intent must be recorded before that work.
        self.assertLess(events.index(requested), events.index(resolved))
        self.assertFalse(requested.payload["explicit_targets"])
        self.assertEqual(requested.payload["item_ids"], [])
        self.assertIn("record:launch-main", resolved.payload["item_ids"])

    async def test_explicit_targets_skip_resolution_events(self):
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime)
        await session.next_view_async(process_commands=False)

        with redirect_stdout(StringIO()):
            await session.handle_close_request_async("shutdown_gui_launched", ("record:launch-main",))

        types = [event.event_type for event in runtime.drain_events()]
        self.assertIn("gui.close_requested", types)
        self.assertNotIn("gui.close_resolving", types)
        self.assertIn("gui.close_finished", types)

    async def test_unsupported_action_publishes_close_failed_and_raises(self):
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime)

        with self.assertRaises(ValueError):
            await session.handle_close_request_async("teleport", ())

        events = runtime.drain_events()
        types = [event.event_type for event in events]
        self.assertIn("gui.close_requested", types)
        self.assertIn("gui.close_failed", types)
        self.assertNotIn("gui.close_completed", types)
        failed = next(e for e in events if e.event_type == "gui.close_failed")
        self.assertEqual(failed.payload["level"], "error")
        self.assertEqual(failed.payload["error_type"], "ValueError")
        self.assertIn("teleport", failed.payload["error"])

    def test_sync_close_reports_a_single_failure_cause(self):
        runtime = AppRuntime()
        session, _admin_client, _launch = build_session(runtime=runtime)

        with self.assertRaises(ValueError):
            session.handle_close_request("teleport", ())

        failures = [e for e in runtime.drain_events() if e.event_type == "gui.close_failed"]
        self.assertEqual(len(failures), 1)
        self.assertNotIn("stage", failures[0].payload)

    async def test_leave_running_publishes_trail_without_cleanup(self):
        runtime = AppRuntime()
        session, admin_client, _launch = build_session(runtime=runtime)

        await session.handle_close_request_async("leave_running", ())

        types = [event.event_type for event in runtime.drain_events()]
        self.assertIn("gui.close_requested", types)
        self.assertIn("gui.close_completed", types)
        self.assertIn("gui.close_finished", types)
        self.assertNotIn("gui.close_resolving", types)
        self.assertEqual(admin_client.requests, [])


class TestForceCloseWatchdogHook(unittest.IsolatedAsyncioTestCase):
    """P1/P2: the watchdog hook kills owned processes without touching DDS."""

    async def test_force_close_kills_live_owned_process_and_logs(self):
        runtime = AppRuntime()
        session, _admin_client, launch = build_session(runtime=runtime)
        await session.next_view_async(process_commands=False)

        killed = session.force_close_gui_launched(12.5)

        self.assertIn(launch.launch_id, killed)
        events = runtime.drain_events()
        expired = next(e for e in events if e.event_type == "gui.close_watchdog_expired")
        self.assertEqual(expired.payload["deadline_sec"], 12.5)
        self.assertEqual(expired.payload["level"], "error")
        forced = [e for e in events if e.event_type == "gui.close_forced"]
        self.assertTrue(forced)
        self.assertEqual(forced[0].payload["candidate_id"], launch.launch_id)

    async def test_force_close_is_a_noop_when_nothing_is_alive(self):
        runtime = AppRuntime()
        session, _admin_client, launch = build_session(runtime=runtime)
        await session.next_view_async(process_commands=False)
        session.force_close_gui_launched(1.0)
        runtime.drain_events()

        # Refresh so the cached selection observes the exit, then confirm a second
        # pass finds nothing left to kill.
        await session.next_view_async(process_commands=False)
        killed = session.force_close_gui_launched(1.0)

        self.assertEqual(killed, ())
        types = [event.event_type for event in runtime.drain_events()]
        self.assertIn("gui.close_watchdog_expired", types)
        self.assertNotIn("gui.close_forced", types)


class TestCloseTargetLiveness(unittest.IsolatedAsyncioTestCase):
    """P3: close targets follow process liveness, not the service state string."""

    def test_live_owned_candidate_is_a_close_target_even_when_stopped(self):
        # A stopped Replay Service still owns a running, admin-reachable process.
        self.assertTrue(_is_live_gui_launched(_candidate(alive=True, observed_state="stopped")))

    def test_exited_candidate_is_not_a_close_target(self):
        self.assertFalse(_is_live_gui_launched(_candidate(alive=False, observed_state="exited")))

    def test_unowned_candidate_is_not_a_close_target(self):
        self.assertFalse(_is_live_gui_launched(_candidate(owns_process=False)))

    async def test_stopped_replay_target_is_still_resolved_for_shutdown(self):
        replay_database_dir = make_replay_database_dir(self)
        handle = FakeHandle(7007)
        replay_manager = ServiceProcessManager(
            spawner=FakeSpawner(handle),
            hostname="dev-host",
            clock=lambda: 10.0,
        )
        replay_controller = ReplayTabController(
            process_manager=replay_manager,
            admin_facade=ServiceAdminFacade(FakeServiceAdminClient()),
            config=ReplayTabControllerConfig(local_hostnames=("dev-host",)),
            clock=lambda: 12.0,
        )
        launch = replay_controller.launch_replay({
            "label": "Manual Replay",
            "config_paths": ["dds/qos/replay_service.xml"],
            "config_name": "xcdr",
            "database_path": replay_database_dir,
            "executable": "/opt/rti/bin/rtireplayservice",
        })
        session, _admin_client, _record_launch = build_session(replay_controller=replay_controller)
        await session.next_view_async(process_commands=False)

        # Simulate the operator having pressed Stop: the row reads "stopped" while
        # the process is still alive. This is the sequence that orphaned a replay
        # service on 2026-08-05.
        replay_controller._state_overrides[launch.launch_id] = ("STOPPED", "stopped")
        view = await replay_controller.refresh_view()
        stopped_row = next(row for row in view.targets if row.target_id == launch.launch_id)
        self.assertEqual(stopped_row.state.lower(), "stopped")

        resolved = await session._resolve_gui_launched_item_ids()

        self.assertIn(f"replay:{launch.launch_id}", resolved)


class TestReadinessSuppression(unittest.IsolatedAsyncioTestCase):
    """P4: stop paying DDS discovery costs for processes that have exited."""

    def test_all_exited_requires_both_dead_and_process_exit_state(self):
        self.assertTrue(candidates_all_exited([_candidate(alive=False, observed_state="exited")]))
        # Service stopped but process alive: still reachable, keep polling.
        self.assertFalse(candidates_all_exited([_candidate(alive=True, observed_state="stopped")]))
        # alive=False but only a service-level state: not proof the process is gone.
        self.assertFalse(candidates_all_exited([_candidate(alive=False, observed_state="stopped")]))

    def test_unknown_candidates_do_not_suppress_readiness(self):
        # Nothing discovered yet must never suppress discovery.
        self.assertFalse(candidates_all_exited([]))

    def test_one_live_candidate_keeps_readiness_active(self):
        self.assertFalse(candidates_all_exited([
            _candidate("a", alive=False, observed_state="exited"),
            _candidate("b", alive=True, observed_state="running"),
        ]))

    async def test_readiness_skips_admin_round_trip_for_exited_process(self):
        client = FakeServiceAdminClient()
        facade = ServiceAdminFacade(client)
        service = ServiceInstanceRef(ServiceKind.REPLAY, "replay_service_1")

        readiness = await readiness_for_service(
            facade,
            service,
            lambda: 99.0,
            [_candidate(alive=False, observed_state="exited")],
        )

        self.assertEqual(readiness.status, AdminReadinessStatus.UNAVAILABLE)
        self.assertEqual(readiness.message, "Service process has exited")
        self.assertEqual(readiness.checked_at, 99.0)

    async def test_readiness_still_queried_while_a_process_is_alive(self):
        client = FakeServiceAdminClient()
        service = ServiceInstanceRef(ServiceKind.REPLAY, "replay_service_1")
        client.set_readiness(AdminReadiness(
            service=service,
            status=AdminReadinessStatus.READY,
            message="Service Admin request/reply matched",
        ))

        readiness = await readiness_for_service(
            ServiceAdminFacade(client),
            service,
            lambda: 99.0,
            [_candidate(alive=True, observed_state="running")],
        )

        self.assertEqual(readiness.status, AdminReadinessStatus.READY)

    async def test_readiness_returns_none_without_a_service_name(self):
        readiness = await readiness_for_service(
            ServiceAdminFacade(FakeServiceAdminClient()),
            ServiceInstanceRef(ServiceKind.REPLAY, ""),
            lambda: 1.0,
            [],
        )
        self.assertIsNone(readiness)


if __name__ == "__main__":
    unittest.main()
