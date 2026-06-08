#!/usr/bin/env python3
"""Tests for the rs_gui headless entry point."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import LifecyclePhase
from rs_gui_app import main, run_headless_once


class TestHeadlessEntrypoint(unittest.IsolatedAsyncioTestCase):
    async def test_run_headless_once_stops_runtime(self):
        lifecycle = await run_headless_once()

        self.assertEqual(lifecycle, LifecyclePhase.STOPPED)


class TestHeadlessCli(unittest.TestCase):
    def test_headless_check_returns_success(self):
        self.assertEqual(main(["--headless-check"]), 0)


if __name__ == "__main__":
    unittest.main()