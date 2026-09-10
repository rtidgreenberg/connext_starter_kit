#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
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
