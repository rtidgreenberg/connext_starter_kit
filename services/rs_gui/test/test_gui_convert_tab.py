#!/usr/bin/env python3
"""Headless tests for rs_gui Convert tab view models."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from gui.tabs.convert_tab import (
    ConvertJobRow,
    ConvertPresetView,
    ConvertStorageView,
    build_convert_action_command,
    build_convert_tab_view_model,
    build_mock_convert_tab_view_model,
)


class TestConvertTabViewModel(unittest.TestCase):
    def test_mock_convert_tab_contains_preset_jobs_logs_and_previews(self):
        view = build_mock_convert_tab_view_model()

        self.assertEqual(view.selected_preset_id, "sqlite_to_json")
        self.assertEqual(view.selected_preset.config_name, "sqlite_to_json")
        self.assertEqual(view.input_storage.kind, "sqlite")
        self.assertEqual(view.output_storage.storage_format, "JSON_SQLITE")
        self.assertEqual(view.jobs[0].state, "completed")
        self.assertEqual(view.logs[0].severity, "INFO")
        self.assertIn("rticonverter", view.cli_preview)
        self.assertIn("<converter name=\"sqlite_to_json\">", view.xml_preview)
        self.assertTrue(view.action_by_id["run"].enabled)
        self.assertFalse(view.action_by_id["cancel"].enabled)
        self.assertTrue(view.action_by_id["open_output"].enabled)
        self.assertEqual(view.diagnostics, ())

    def test_empty_convert_tab_reports_missing_preset_and_paths(self):
        view = build_convert_tab_view_model()

        self.assertFalse(view.action_by_id["run"].enabled)
        self.assertFalse(view.action_by_id["open_output"].enabled)
        self.assertIn("No Converter preset selected", view.diagnostics)
        self.assertIn("No input storage path selected", view.diagnostics)
        self.assertIn("No output storage path selected", view.diagnostics)

    def test_running_job_enables_cancel_but_not_output_actions(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        )

        view = build_convert_tab_view_model(
            presets=(preset,),
            jobs=(job,),
            selected_preset_id="json",
            selected_job_id="job-1",
            input_storage=ConvertStorageView("sqlite", "services/input", "XCDR_AUTO"),
            output_storage=ConvertStorageView("sqlite", "services/output", "JSON_SQLITE"),
        )

        self.assertTrue(view.action_by_id["run"].enabled)
        self.assertTrue(view.action_by_id["cancel"].enabled)
        self.assertFalse(view.action_by_id["open_output"].enabled)
        self.assertFalse(view.action_by_id["inspect_output"].enabled)

    def test_convert_action_command_preserves_structured_execution_intent(self):
        view = build_mock_convert_tab_view_model()

        command = build_convert_action_command("run", view)

        self.assertEqual(command.command_type, "convert.run")
        self.assertEqual(command.target, "convert-robot-run-03")
        self.assertEqual(command.payload["job_id"], "convert-robot-run-03")
        self.assertEqual(command.payload["config_file"], "services/converter_service_config.xml")
        self.assertEqual(command.payload["config_name"], "sqlite_to_json")
        self.assertEqual(command.payload["preset_id"], "sqlite_to_json")
        self.assertEqual(command.payload["input_storage"]["kind"], "sqlite")
        self.assertEqual(
            command.payload["input_storage"]["path"],
            "services/recording_service_gui/log_dir/xcdr",
        )
        self.assertEqual(command.payload["output_storage"]["storage_format"], "JSON_SQLITE")
        self.assertEqual(command.payload["output_format"], "JSON_SQLITE")
        self.assertEqual(command.payload["verbosity"], "WARN:ERROR")
        self.assertIn("rticonverter", command.payload["cli_preview"])
        self.assertIn("<dds>", command.payload["xml_preview"])
        with self.assertRaises(ValueError):
            build_convert_action_command("publish", view)


if __name__ == "__main__":
    unittest.main()
