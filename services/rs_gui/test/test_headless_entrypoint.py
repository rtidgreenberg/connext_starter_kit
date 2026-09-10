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