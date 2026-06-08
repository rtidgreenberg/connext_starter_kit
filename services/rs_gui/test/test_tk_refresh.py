#!/usr/bin/env python3
"""Unit tests for Tk refresh-loop shutdown behavior."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from tk_gui.refresh import TkRefreshBridge


class _FakeRoot:
    def __init__(self):
        self._next_id = 0
        self.after_calls = []
        self.canceled = []
        self.quit_calls = 0

    def after(self, interval_ms, callback):
        self._next_id += 1
        token = f"after-{self._next_id}"
        self.after_calls.append((interval_ms, callback, token))
        return token

    def after_cancel(self, token):
        self.canceled.append(token)

    def quit(self):
        self.quit_calls += 1


class TestTkRefreshBridge(unittest.TestCase):
    def test_tick_handles_keyboard_interrupt_and_stops_loop(self):
        root = _FakeRoot()
        captured = {"consumed": 0}

        def _provider():
            raise KeyboardInterrupt()

        def _consumer(_view):
            captured["consumed"] += 1

        bridge = TkRefreshBridge(
            root=root,
            view_provider=_provider,
            view_consumer=_consumer,
            interval_ms=10,
        )

        bridge.start()
        self.assertTrue(root.after_calls)

        # Simulate Tk invoking scheduled callback.
        bridge._tick()

        self.assertEqual(captured["consumed"], 0)
        self.assertEqual(root.quit_calls, 1)
        self.assertFalse(bridge._running)
        self.assertIsNone(bridge._after_id)


if __name__ == "__main__":
    unittest.main()
