#!/usr/bin/env python3
"""Tests for rs_gui_v2 startup diagnostics."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from preflight import Preflight


class DearPyGuiFailurePreflight(Preflight):
    def _check_import(self, module_name: str) -> bool:
        return module_name == "rti.connextdds"

    def _import_error(self, module_name: str) -> str:
        if module_name == "dearpygui.dearpygui":
            return "libstdc++.so.6: version `GLIBCXX_3.4.30' not found"
        return ""

    def _check_xml_types(self, nddshome: str) -> None:
        self._record("INFO", "XML_FILES", "Required XML type files are present")

    def _check_service_executables(self, nddshome: str) -> None:
        self._record("INFO", "SERVICE_BIN", "Required RTI service executables are available")


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
    def test_dearpygui_abi_failure_is_actionable(self):
        preflight = DearPyGuiFailurePreflight(
            require_connext=False,
            require_dearpygui=True,
        )

        exit_code = preflight.run()

        self.assertEqual(exit_code, 1)
        matching = [
            result for result in preflight.results
            if result.code == "DEARPYGUI_IMPORT_FAILED"
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("GLIBCXX_3.4.30", matching[0].details)
        self.assertIn("pinned requirements", matching[0].details)

    def test_successful_gui_preflight_returns_zero(self):
        preflight = SuccessfulPreflight(
            require_connext=False,
            require_dearpygui=True,
        )

        exit_code = preflight.run()

        self.assertEqual(exit_code, 0)
        codes = {result.code for result in preflight.results}
        self.assertIn("DEARPYGUI_IMPORT", codes)
        self.assertIn("SUMMARY", codes)


if __name__ == "__main__":
    unittest.main()
