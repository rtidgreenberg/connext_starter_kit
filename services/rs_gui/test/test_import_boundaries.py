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
"""Import-boundary tests for the rs_gui headless app core."""

import ast
import os
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
APP_CORE_DIR = os.path.join(PARENT_DIR, "app_core")
GUI_DIR = os.path.join(PARENT_DIR, "gui")


def _allows_connext_import(path):
    filename = os.path.basename(path)
    return filename.startswith("rti_") or filename.startswith("dds_")


class TestImportBoundaries(unittest.TestCase):
    def test_app_core_has_no_v1_or_ui_imports(self):
        banned_roots = {
            "recording_service_control",
            "recording_service_environment",
            "recording_service_monitor",
            "tkinter",
        }
        violations = []

        for root, _dirs, files in os.walk(APP_CORE_DIR):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                with open(path, "r", encoding="utf-8") as source_file:
                    tree = ast.parse(source_file.read(), filename=path)
                for node in ast.walk(tree):
                    imported_modules = []
                    if isinstance(node, ast.Import):
                        imported_modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_modules = [node.module]
                    for module_name in imported_modules:
                        root_name = module_name.split(".")[0]
                        if root_name in banned_roots:
                            relative_path = os.path.relpath(path, PARENT_DIR)
                            violations.append(f"{relative_path}: {module_name}")

        self.assertEqual([], violations)

    def test_connext_imports_are_limited_to_adapter_modules(self):
        violations = []

        for root, _dirs, files in os.walk(APP_CORE_DIR):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                with open(path, "r", encoding="utf-8") as source_file:
                    tree = ast.parse(source_file.read(), filename=path)
                for node in ast.walk(tree):
                    imported_modules = []
                    if isinstance(node, ast.Import):
                        imported_modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_modules = [node.module]
                    for module_name in imported_modules:
                        if module_name.split(".")[0] != "rti":
                            continue
                        if not _allows_connext_import(path):
                            relative_path = os.path.relpath(path, PARENT_DIR)
                            violations.append(f"{relative_path}: {module_name}")

        self.assertEqual([], violations)

    def test_gui_modules_do_not_import_dds_or_v1(self):
        banned_roots = {
            "recording_service_control",
            "recording_service_environment",
            "recording_service_monitor",
            "rti",
            "tkinter",
        }
        violations = []

        for root, _dirs, files in os.walk(GUI_DIR):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                with open(path, "r", encoding="utf-8") as source_file:
                    tree = ast.parse(source_file.read(), filename=path)
                for node in ast.walk(tree):
                    imported_modules = []
                    if isinstance(node, ast.Import):
                        imported_modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported_modules = [node.module]
                    for module_name in imported_modules:
                        root_name = module_name.split(".")[0]
                        if root_name in banned_roots:
                            relative_path = os.path.relpath(path, PARENT_DIR)
                            violations.append(f"{relative_path}: {module_name}")

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
