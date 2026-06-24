#!/usr/bin/env python3
"""Tests for Convert tab workspace persistence."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from gui.tabs.convert_controller import ConvertTabController, ConvertTabControllerConfig
from gui.tabs.convert_tab import ConvertPresetView
from gui.workspace import GuiWorkspaceController


class TestConvertWorkspacePersistence(unittest.TestCase):
    def test_workspace_config_exports_all_fields(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON Export",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        config = ConvertTabControllerConfig(
            config_file="services/converter.xml",
            selected_preset_id="json",
            selected_job_id="convert-123",
            input_storage_path="/data/input",
            output_storage_path="/data/output",
            data_selection="subset",
            verbosity="DEBUG",
        )
        controller = ConvertTabController(presets=(preset,), config=config)

        workspace_config = controller.workspace_config()

        self.assertEqual(workspace_config["config_file"], "services/converter.xml")
        self.assertEqual(workspace_config["selected_preset_id"], "json")
        self.assertEqual(workspace_config["selected_job_id"], "convert-123")
        self.assertEqual(workspace_config["input_storage_path"], "/data/input")
        self.assertEqual(workspace_config["output_storage_path"], "/data/output")
        self.assertEqual(workspace_config["data_selection"], "subset")
        self.assertEqual(workspace_config["verbosity"], "DEBUG")

    def test_workspace_metadata_includes_service_status(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON Export",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        controller = ConvertTabController(presets=(preset,))

        metadata = controller.workspace_metadata()

        self.assertEqual(metadata["preset_count"], 1)
        self.assertIn("service_available", metadata)
        self.assertFalse(metadata["service_available"])

    def test_apply_workspace_intent_restores_config(self):
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON Export",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        controller = ConvertTabController(presets=(preset,))

        saved_config = {
            "config_file": "saved.xml",
            "selected_preset_id": "json",
            "selected_job_id": "convert-999",
            "input_storage_path": "/saved/input",
            "output_storage_path": "/saved/output",
            "data_selection": "all",
            "verbosity": "INFO",
        }

        controller.apply_workspace_intent(saved_config)

        self.assertEqual(controller._config.config_file, "saved.xml")
        self.assertEqual(controller._config.selected_preset_id, "json")
        self.assertEqual(controller._config.selected_job_id, "convert-999")
        self.assertEqual(controller._config.input_storage_path, "/saved/input")
        self.assertEqual(controller._config.output_storage_path, "/saved/output")
        self.assertEqual(controller._config.data_selection, "all")
        self.assertEqual(controller._config.verbosity, "INFO")


class TestGuiWorkspaceControllerWithConvert(unittest.TestCase):
    def test_workspace_controller_accepts_convert_controller(self):
        convert_controller = ConvertTabController.mock()
        workspace_controller = GuiWorkspaceController(convert_controller=convert_controller)

        self.assertEqual(workspace_controller._convert_controller, convert_controller)

    def test_workspace_document_includes_convert_state(self):
        convert_controller = ConvertTabController.mock()
        workspace_controller = GuiWorkspaceController(convert_controller=convert_controller)

        document = workspace_controller.build_document(workspace_name="Test", path="test.json")

        gui_metadata = document.metadata.get("gui", {})
        self.assertIn("convert", gui_metadata)
        convert_state = gui_metadata["convert"]
        self.assertEqual(convert_state["selected_preset_id"], "sqlite_to_json")

    def test_workspace_restoration_applies_convert_state(self):
        convert_controller = ConvertTabController.mock()
        workspace_controller = GuiWorkspaceController(convert_controller=convert_controller)

        # Simulate building and loading a workspace
        document = workspace_controller.build_document(workspace_name="Test", path="test.json")

        # Create a new controller and restore the document
        new_convert = ConvertTabController.mock()
        new_workspace = GuiWorkspaceController(convert_controller=new_convert)

        new_workspace.apply_document(document)

        # Verify state was restored
        self.assertEqual(new_convert._config.selected_preset_id, "sqlite_to_json")


class TestGuiWorkspaceControllerSaveLoad(unittest.TestCase):
    """Tests for workspace save/load/error paths."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _path(self, name="test_workspace.json"):
        return os.path.join(self._tmp, name)

    def test_save_persists_and_load_restores(self):
        convert = ConvertTabController.mock()
        ctrl = GuiWorkspaceController(convert_controller=convert, clock=lambda: 100.0)

        ctrl.save(self._path(), workspace_name="SavedWS")

        self.assertTrue(os.path.isfile(self._path()))
        self.assertEqual(ctrl.last_path, self._path())
        self.assertEqual(ctrl.last_document.name, "SavedWS")

        new_convert = ConvertTabController.mock()
        ctrl2 = GuiWorkspaceController(convert_controller=new_convert)
        doc = ctrl2.load(self._path())

        self.assertEqual(doc.name, "SavedWS")
        self.assertEqual(ctrl2.last_path, self._path())

    def test_save_raises_on_empty_path(self):
        ctrl = GuiWorkspaceController()
        with self.assertRaises(ValueError):
            ctrl.save("")

    def test_load_raises_on_empty_path(self):
        ctrl = GuiWorkspaceController()
        with self.assertRaises(ValueError):
            ctrl.load("")

    def test_load_raises_on_nonexistent_file(self):
        ctrl = GuiWorkspaceController()
        with self.assertRaises((FileNotFoundError, OSError)):
            ctrl.load("/nonexistent/path.json")

    def test_handle_command_save(self):
        from app_core import AppCommand, CommandStatus
        convert = ConvertTabController.mock()
        ctrl = GuiWorkspaceController(convert_controller=convert, clock=lambda: 200.0)
        cmd = AppCommand(command_type="workspace.save", payload={"path": self._path(), "workspace_name": "CmdSave"})

        result = ctrl.handle_command(cmd, workspace_name="Fallback")

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        self.assertIn("CmdSave", result.message)
        self.assertTrue(os.path.isfile(self._path()))

    def test_handle_command_load(self):
        from app_core import AppCommand, CommandStatus
        convert = ConvertTabController.mock()
        ctrl = GuiWorkspaceController(convert_controller=convert, clock=lambda: 300.0)
        ctrl.save(self._path(), workspace_name="LoadMe")

        cmd = AppCommand(command_type="workspace.load", payload={"path": self._path()})
        result = ctrl.handle_command(cmd)

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        self.assertIn("LoadMe", result.message)

    def test_handle_command_unknown_type_raises(self):
        from app_core import AppCommand
        ctrl = GuiWorkspaceController()
        cmd = AppCommand(command_type="workspace.delete", payload={})
        with self.assertRaises(ValueError):
            ctrl.handle_command(cmd)


if __name__ == "__main__":
    unittest.main()
