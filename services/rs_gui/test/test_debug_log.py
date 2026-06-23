#!/usr/bin/env python3
"""Unit tests for structured debug logging in rs_gui."""

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


class TestDebugLog(unittest.TestCase):
    def setUp(self):
        self._original_env = {
            "RS_GUI_DEBUG": os.environ.get("RS_GUI_DEBUG"),
            "RS_GUI_LOG_DIR": os.environ.get("RS_GUI_LOG_DIR"),
            "RS_GUI_EVENT_LOG_PATH": os.environ.get("RS_GUI_EVENT_LOG_PATH"),
        }
        self._temp_dirs = []

    def tearDown(self):
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for path in self._temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        import app_core.debug_log as debug_log_module
        importlib.reload(debug_log_module)

    def _reload_debug_log(self):
        import app_core.debug_log as debug_log_module
        return importlib.reload(debug_log_module)

    def test_dbg_writes_structured_event_to_runtime_log_path(self):
        temp_dir = tempfile.mkdtemp(prefix="rs_gui_debug_runtime_")
        self._temp_dirs.append(temp_dir)
        log_path = os.path.join(temp_dir, "runtime.jsonl")
        os.environ["RS_GUI_DEBUG"] = "1"
        os.environ["RS_GUI_EVENT_LOG_PATH"] = log_path

        debug_log = self._reload_debug_log()

        debug_log.dbg("record", "launch preview", config_name="template")

        with open(log_path, "r", encoding="utf-8") as log_file:
            lines = [json.loads(line) for line in log_file if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["event_type"], "debug.log")
        self.assertEqual(lines[0]["source"], "record")
        self.assertEqual(lines[0]["payload"]["message"], "launch preview")
        self.assertEqual(lines[0]["payload"]["config_name"], "template")
        self.assertEqual(lines[0]["payload"]["level"], "debug")
        self.assertEqual(debug_log.log_path(), log_path)

    def test_dbg_falls_back_to_rs_gui_logs_directory(self):
        temp_dir = tempfile.mkdtemp(prefix="rs_gui_debug_fallback_")
        self._temp_dirs.append(temp_dir)
        os.environ["RS_GUI_DEBUG"] = "1"
        os.environ["RS_GUI_LOG_DIR"] = temp_dir
        os.environ.pop("RS_GUI_EVENT_LOG_PATH", None)

        debug_log = self._reload_debug_log()

        debug_log.dbg("session", "refresh view", candidates=3)

        log_files = [name for name in os.listdir(temp_dir) if name.endswith(".jsonl")]
        self.assertEqual(len(log_files), 1)
        log_path = os.path.join(temp_dir, log_files[0])
        with open(log_path, "r", encoding="utf-8") as log_file:
            line = json.loads(next(iter(log_file)).strip())
        self.assertEqual(line["event_type"], "debug.log")
        self.assertEqual(line["source"], "session")
        self.assertEqual(line["payload"]["candidates"], 3)
        self.assertEqual(debug_log.log_path(), log_path)
