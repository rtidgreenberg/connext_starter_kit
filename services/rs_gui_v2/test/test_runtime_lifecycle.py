#!/usr/bin/env python3
"""Pure unit tests for the rs_gui_v2 headless runtime."""

import asyncio
import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand, AppEvent, AppRuntime, LifecyclePhase, RuntimeConfig


class TestRuntimeLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_start_and_shutdown_are_idempotent(self):
        runtime = AppRuntime()

        runtime.start()
        runtime.start()
        self.assertEqual(runtime.lifecycle, LifecyclePhase.RUNNING)

        await runtime.shutdown()
        await runtime.shutdown()
        self.assertEqual(runtime.lifecycle, LifecyclePhase.STOPPED)
        self.assertEqual(runtime.task_names, [])

    async def test_shutdown_cancels_managed_tasks(self):
        runtime = AppRuntime()
        cancelled = asyncio.Event()

        async def long_running_task():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        runtime.start()
        runtime.spawn_task("long-running", long_running_task())
        await asyncio.sleep(0)
        self.assertEqual(runtime.task_names, ["long-running"])

        await runtime.shutdown()

        self.assertTrue(cancelled.is_set())
        self.assertEqual(runtime.task_names, [])
        self.assertEqual(runtime.lifecycle, LifecyclePhase.STOPPED)

    async def test_fatal_task_failure_sets_failed_state(self):
        runtime = AppRuntime()

        async def failing_task():
            raise RuntimeError("boom")

        runtime.start()
        task = runtime.spawn_task("failing", failing_task(), fatal=True)
        await asyncio.gather(task, return_exceptions=True)

        self.assertEqual(runtime.lifecycle, LifecyclePhase.FAILED)
        self.assertIn("boom", runtime.state.recent_errors)
        failure_events = [
            event for event in runtime.drain_events()
            if event.event_type == "runtime.task_failed"
        ]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0].payload["task"], "failing")

    async def test_spawn_requires_running_runtime(self):
        runtime = AppRuntime()

        async def noop():
            return None

        with self.assertRaises(RuntimeError):
            runtime.spawn_task("noop", noop())

        await noop()


class TestRuntimeQueues(unittest.TestCase):
    def test_command_queue_is_bounded_and_fifo(self):
        runtime = AppRuntime(RuntimeConfig(command_queue_max_size=2))
        first = AppCommand("first")
        second = AppCommand("second")
        third = AppCommand("third")

        self.assertTrue(runtime.enqueue_command(first))
        self.assertTrue(runtime.enqueue_command(second))
        self.assertFalse(runtime.enqueue_command(third))
        self.assertEqual(runtime.counters.commands_enqueued, 2)
        self.assertEqual(runtime.counters.commands_dropped, 1)
        self.assertEqual(runtime.drain_commands(), [first, second])
        self.assertEqual(runtime.counters.commands_drained, 2)
        self.assertEqual(runtime.drain_commands(), [])

    def test_event_queue_is_bounded_and_fifo(self):
        runtime = AppRuntime(RuntimeConfig(event_queue_max_size=2))
        first = AppEvent("first")
        second = AppEvent("second")
        third = AppEvent("third")

        self.assertTrue(runtime.publish_event(first))
        self.assertTrue(runtime.publish_event(second))
        self.assertFalse(runtime.publish_event(third))
        self.assertEqual(runtime.counters.events_published, 2)
        self.assertEqual(runtime.counters.events_dropped, 1)
        self.assertEqual(runtime.drain_events(), [first, second])
        self.assertEqual(runtime.counters.events_drained, 2)

    def test_drain_limit_preserves_remaining_items(self):
        runtime = AppRuntime()
        events = [AppEvent(str(index)) for index in range(3)]
        for event in events:
            runtime.publish_event(event)

        self.assertEqual(runtime.drain_events(limit=2), events[:2])
        self.assertEqual(runtime.drain_events(), events[2:])

    def test_sample_counters_are_recorded(self):
        runtime = AppRuntime()

        runtime.record_samples(received=5, dropped=2)

        self.assertEqual(runtime.counters.samples_received, 5)
        self.assertEqual(runtime.counters.samples_dropped, 2)


if __name__ == "__main__":
    unittest.main()