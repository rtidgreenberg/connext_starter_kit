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
"""Tests for rs_gui startup diagnostics."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from preflight import Preflight


class SuccessfulPreflight(Preflight):
    def _check_import(self, module_name: str) -> bool:
        return True

    def _import_error(self, module_name: str) -> str:
        return ""

    def _check_xml_types(self, nddshome: str) -> None:
        self._record("INFO", "XML_FILES", "Required XML type files are present")

    def _check_service_executables(self, nddshome: str) -> None:
        self._record("INFO", "SERVICE_BIN", "Required RTI service executables are available")


class TestPreflightDiagnostics(unittest.TestCase):
    def test_successful_preflight_returns_zero(self):
        preflight = SuccessfulPreflight(
            require_connext=False,
        )

        exit_code = preflight.run()

        self.assertEqual(exit_code, 0)
        codes = {result.code for result in preflight.results}
        self.assertIn("RTI_IMPORT", codes)
        self.assertIn("SUMMARY", codes)


if __name__ == "__main__":
    unittest.main()
