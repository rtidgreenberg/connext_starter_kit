#!/usr/bin/env python3
"""Headless tests for rs_gui_v2 Convert tab controller."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import CommandStatus
from gui.tabs.convert_controller import ConvertTabController, ConvertTabControllerConfig
from gui.tabs.convert_tab import ConvertPresetView, build_mock_convert_tab_view_model


class TestConvertTabController(unittest.TestCase):
    def test_mock_controller_refreshes_seeded_convert_view(self):
        controller = ConvertTabController.mock()

        view = controller.last_view

        self.assertEqual(controller.selected_preset_id, "sqlite_to_json")
        self.assertEqual(view.selected_preset.config_name, "sqlite_to_json")
        self.assertEqual(view.input_storage.path, "services/recording_service_gui/log_dir/xcdr")
        self.assertEqual(view.output_storage.path, "services/converter_output/robot_run_03_json")

    def test_select_preset_updates_selected_row(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        controller = ConvertTabController(presets=(preset,))

        selected = controller.select_preset("json")

        self.assertEqual(selected.preset_id, "json")
        self.assertEqual(controller.selected_preset_id, "json")

    def test_run_conversion_creates_queued_job(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        controller = ConvertTabController(
            presets=(preset,),
            config=ConvertTabControllerConfig(
                selected_preset_id="json",
                input_storage_path="services/input",
                output_storage_path="services/output",
            ),
        )
        from app_core import AppCommand

        cmd = AppCommand(
            command_type="convert.run",
            target="test",
            payload={
                "config_name": "json_export",
                "input_storage": {"path": "services/input"},
                "output_storage": {"path": "services/output"},
                "output_format": "JSON_SQLITE",
            },
        )

        result = controller.handle_command(cmd)

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        self.assertIn("Queued conversion job", result.message)
        self.assertEqual(len(controller._jobs), 1)
        job = controller._jobs[0]
        self.assertEqual(job.state, "queued")
        self.assertEqual(job.preset_id, "json_export")

    def test_cancel_conversion_moves_job_to_cancel_requested(self):
        job_id = "convert-1234"
        from gui.tabs.convert_tab import ConvertJobRow
        from app_core import AppCommand

        job = ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        )
        controller = ConvertTabController()
        controller._jobs = (job,)
        controller._config = ConvertTabControllerConfig(selected_job_id=job_id)

        cmd = AppCommand(
            command_type="convert.cancel",
            target=job_id,
            payload={"job_id": job_id},
        )

        result = controller.handle_command(cmd)

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        self.assertIn("Requested cancellation", result.message)
        updated_job = controller._jobs[0]
        self.assertEqual(updated_job.state, "cancel_requested")

    def test_open_output_requires_completed_job(self):
        job_id = "convert-1234"
        from gui.tabs.convert_tab import ConvertJobRow
        from app_core import AppCommand

        job = ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        )
        controller = ConvertTabController()
        controller._jobs = (job,)

        cmd = AppCommand(
            command_type="convert.open_output",
            target=job_id,
            payload={"job_id": job_id},
        )

        with self.assertRaises(ValueError):
            controller.handle_command(cmd)

    def test_open_output_succeeds_for_completed_job(self):
        job_id = "convert-1234"
        from gui.tabs.convert_tab import ConvertJobRow
        from app_core import AppCommand

        job = ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="completed",
            progress="100%",
        )
        controller = ConvertTabController()
        controller._jobs = (job,)

        cmd = AppCommand(
            command_type="convert.open_output",
            target=job_id,
            payload={"job_id": job_id},
        )

        result = controller.handle_command(cmd)

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        self.assertIn("Opening output directory", result.message)
        self.assertEqual(result.payload["output_path"], "services/output")


if __name__ == "__main__":
    unittest.main()
