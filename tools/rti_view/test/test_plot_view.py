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
"""Unit tests for rti_view plot setup."""

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rti_view.views.plot_view import run_plot


class TestPlotView(unittest.IsolatedAsyncioTestCase):
    async def test_run_plot_rejects_zero_history(self):
        with self.assertRaisesRegex(ValueError, "history_seconds must be positive"):
            await run_plot(object(), "value", "Telemetry", history_seconds=0)

    async def test_run_plot_rejects_negative_history(self):
        with self.assertRaisesRegex(ValueError, "history_seconds must be positive"):
            await run_plot(object(), "value", "Telemetry", history_seconds=-1)


if __name__ == "__main__":
    unittest.main()