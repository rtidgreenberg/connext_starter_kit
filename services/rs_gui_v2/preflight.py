#!/usr/bin/env python3
"""Startup diagnostics for rs_gui_v2 launcher hardening."""

from __future__ import annotations

import argparse
import importlib
import os
from dataclasses import dataclass
from typing import List

from app_core.connext_environment import (
    detect_nddshome,
    detect_rti_license,
    license_setup_message,
    validate_generated_types,
)


REQUIRED_XML_FILES = (
    "ServiceCommon.xml",
    "ServiceAdmin.xml",
    "RecordingServiceTypes.xml",
    "ServiceMonitoring.xml",
    "RecordingServiceMonitoring.xml",
    "RoutingServiceMonitoring.xml",
)

REQUIRED_SERVICE_EXECUTABLES = (
    "rtirecordingservice",
    "rtireplayservice",
    "rticonverter",
)


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    details: str = ""


class Preflight:
    def __init__(self, require_connext: bool, require_dearpygui: bool) -> None:
        self.require_connext = require_connext
        self.require_dearpygui = require_dearpygui
        self.results: List[Diagnostic] = []
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.xml_dir = os.path.join(self.script_dir, "xml_types")

    def _record(self, level: str, code: str, message: str, details: str = "") -> None:
        self.results.append(Diagnostic(level=level, code=code, message=message, details=details))

    def _record_connext(self, code: str, message: str, details: str = "") -> None:
        if self.require_connext:
            self._record("ERROR", code, message, details)
        else:
            self._record("WARNING", code, message, details)

    def _check_import(self, module_name: str) -> bool:
        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

    def _import_error(self, module_name: str) -> str:
        try:
            importlib.import_module(module_name)
            return ""
        except Exception as exc:
            return str(exc)

    def run(self) -> int:
        self._record("INFO", "START", "Running rs_gui_v2 startup diagnostics")

        nddshome = detect_nddshome()
        if nddshome:
            self._record("INFO", "NDDSHOME", f"Detected NDDSHOME: {nddshome}")
        else:
            self._record_connext(
                "NDDSHOME_MISSING",
                "NDDSHOME not detected.",
                "Set NDDSHOME or install RTI Connext to ~/rti_connext_dds-<version>.",
            )

        if self._check_import("rti.connextdds"):
            self._record("INFO", "RTI_IMPORT", "Python RTI API import check passed")
        else:
            self._record_connext(
                "RTI_IMPORT_FAILED",
                "Cannot import rti.connextdds in the active Python environment.",
                "Activate connext_dds_env and install the RTI Python package for this interpreter.",
            )

        if self._check_import("rti.request"):
            self._record("INFO", "RTI_REQUEST_IMPORT", "Python RTI request/reply import check passed")
        else:
            self._record_connext(
                "RTI_REQUEST_IMPORT_FAILED",
                "Cannot import rti.request in the active Python environment.",
                "Live Recording Service Admin control requires RTI Python request/reply support.",
            )

        if self.require_dearpygui:
            import_error = self._import_error("dearpygui.dearpygui")
            if not import_error:
                self._record("INFO", "DEARPYGUI_IMPORT", "Dear PyGui import check passed")
            else:
                details = (
                    "Install it with: ../../connext_dds_env/bin/python -m pip install -r "
                    "services/rs_gui_v2/requirements.txt"
                )
                if "GLIBCXX_" in import_error:
                    details += (
                        "; detected libstdc++ ABI mismatch. Use pinned requirements "
                        "or upgrade host libstdc++."
                    )
                details += f" (Import error: {import_error})"
                self._record(
                    "ERROR",
                    "DEARPYGUI_IMPORT_FAILED",
                    "Cannot import dearpygui.dearpygui.",
                    details,
                )

        license_file = detect_rti_license(nddshome)
        if license_file:
            self._record("INFO", "LICENSE", f"Detected RTI license: {license_file}")
        else:
            self._record_connext(
                "LICENSE_MISSING",
                "RTI license was not found in known locations.",
                license_setup_message(nddshome),
            )

        self._check_xml_types(nddshome)
        self._check_service_executables(nddshome)

        errors = [result for result in self.results if result.level == "ERROR"]
        warnings = [result for result in self.results if result.level == "WARNING"]
        self._record(
            "INFO",
            "SUMMARY",
            f"Diagnostics complete: {len(errors)} error(s), {len(warnings)} warning(s)",
        )

        for result in self.results:
            print(f"[{result.level}] {result.code}: {result.message}")
            if result.details:
                print(f"         {result.details}")

        return 1 if errors else 0

    def _check_xml_types(self, nddshome: str) -> None:
        if not os.path.isdir(self.xml_dir):
            self._record_connext(
                "XML_DIR_MISSING",
                f"XML types directory missing: {self.xml_dir}",
                "Run services/rs_gui_v2/setup.sh to generate XML DynamicData types.",
            )
            return

        missing = [
            xml_name for xml_name in REQUIRED_XML_FILES
            if not os.path.isfile(os.path.join(self.xml_dir, xml_name))
        ]
        if missing:
            self._record_connext(
                "XML_FILES_MISSING",
                "One or more required XML type files are missing.",
                f"Missing: {', '.join(missing)}. Run services/rs_gui_v2/setup.sh.",
            )
        else:
            self._record("INFO", "XML_FILES", "Required XML type files are present")

        try:
            validate_generated_types(self.xml_dir, nddshome)
            self._record("INFO", "XML_STAMP", "XML generated-type stamp matches active NDDSHOME")
        except Exception as exc:
            self._record_connext(
                "XML_STALE",
                "Generated XML metadata does not match the active Connext installation.",
                f"{exc}",
            )

    def _check_service_executables(self, nddshome: str) -> None:
        if not nddshome:
            self._record_connext(
                "SERVICE_BIN_UNKNOWN",
                "Cannot validate RTI service executables without NDDSHOME.",
            )
            return

        missing = []
        for binary in REQUIRED_SERVICE_EXECUTABLES:
            path = os.path.join(nddshome, "bin", binary)
            if not (os.path.isfile(path) and os.access(path, os.X_OK)):
                missing.append(path)

        if missing:
            self._record_connext(
                "SERVICE_BIN_MISSING",
                "One or more RTI service executables are missing or not executable.",
                f"Checked: {', '.join(missing)}",
            )
        else:
            self._record("INFO", "SERVICE_BIN", "Required RTI service executables are available")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="rs_gui_v2 startup diagnostics")
    parser.add_argument(
        "--require-connext",
        action="store_true",
        help="treat Connext-related issues as launch-blocking errors",
    )
    parser.add_argument(
        "--require-dearpygui",
        action="store_true",
        help="treat missing Dear PyGui as an error",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    preflight = Preflight(
        require_connext=args.require_connext,
        require_dearpygui=args.require_dearpygui,
    )
    return preflight.run()


if __name__ == "__main__":
    raise SystemExit(main())