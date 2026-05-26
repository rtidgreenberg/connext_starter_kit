#!/usr/bin/env python3
"""Headless tests for the rs_gui_v2 Dear PyGui shell bridge."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppEvent, AppRuntime, CommandStatus, OperatorDiagnostic
from app_core.services import (
    ServiceCandidateSelection,
    ServiceCommand,
    ServiceCommandOutcome,
    ServiceCommandRequest,
    ServiceControlIdentity,
    ServiceKind,
    ServiceLaunchIntent,
    candidate_from_control_identity,
)
from gui import UiFrameScheduler, build_mock_shell_view_model
from gui.main_window import (
    RECORD_LAUNCH_ADMIN_DOMAIN_TAG,
    RECORD_LAUNCH_CONFIG_NAME_TAG,
    RECORD_LAUNCH_CONFIG_PATHS_TAG,
    RECORD_LAUNCH_DATA_DOMAIN_TAG,
    RECORD_LAUNCH_EXTRA_ARGS_TAG,
    RECORD_LAUNCH_LABEL_TAG,
    RECORD_LAUNCH_MONITOR_DOMAIN_TAG,
    RECORD_LAUNCH_VERBOSITY_TAG,
    WORKSPACE_NAME_INPUT_TAG,
    WORKSPACE_PATH_INPUT_TAG,
    DearPyGuiShell,
    build_workspace_action_command,
)
from gui.tabs.record_tab import (
    RecordLaunchViewModel,
    build_record_action_command,
    build_record_launch_command,
    build_record_tab_view_model,
)
from rs_gui_v2_app import main


class FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDpg:
    def __init__(self):
        self.calls = []
        self.values = {}
        self.context_created = False
        self.context_destroyed = False

    def create_context(self):
        self.context_created = True
        self.calls.append(("create_context", (), {}))

    def destroy_context(self):
        self.context_destroyed = True
        self.calls.append(("destroy_context", (), {}))

    def window(self, *args, **kwargs):
        self.calls.append(("window", args, kwargs))
        return FakeContext()

    def tab_bar(self, *args, **kwargs):
        self.calls.append(("tab_bar", args, kwargs))
        return FakeContext()

    def tab(self, *args, **kwargs):
        self.calls.append(("tab", args, kwargs))
        return FakeContext()

    def group(self, *args, **kwargs):
        self.calls.append(("group", args, kwargs))
        return FakeContext()

    def table(self, *args, **kwargs):
        self.calls.append(("table", args, kwargs))
        return FakeContext()

    def table_row(self, *args, **kwargs):
        self.calls.append(("table_row", args, kwargs))
        return FakeContext()

    def add_text(self, *args, **kwargs):
        self.calls.append(("add_text", args, kwargs))

    def add_combo(self, *args, **kwargs):
        self.calls.append(("add_combo", args, kwargs))

    def add_button(self, *args, **kwargs):
        self.calls.append(("add_button", args, kwargs))

    def add_input_text(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", "")
        self.calls.append(("add_input_text", args, kwargs))

    def get_value(self, tag):
        return self.values.get(tag)

    def add_separator(self, *args, **kwargs):
        self.calls.append(("add_separator", args, kwargs))

    def add_table_column(self, *args, **kwargs):
        self.calls.append(("add_table_column", args, kwargs))


class TestMockShellViewModel(unittest.TestCase):
    def test_mock_shell_contains_record_selector_and_history(self):
        view = build_mock_shell_view_model(now=120.0)

        self.assertEqual(view.active_tab, "Record")
        self.assertIn("Robot Run 03", view.title)
        self.assertEqual(view.record_tab.selected_candidate.control_name, "recording_service_8f4f2a1c")
        self.assertEqual(view.replay_tab.selected_target.control_name, "replay_service_2d91c4a0")
        self.assertEqual(view.convert_tab.selected_preset.config_name, "sqlite_to_json")
        self.assertEqual(len(view.record_tab.candidates), 2)
        self.assertEqual(view.record_tab.command_history[0].command_id, "pause-21")
        self.assertTrue(view.record_tab.action_by_id["pause"].enabled)
        self.assertFalse(view.record_tab.action_by_id["terminate_local"].enabled)
        self.assertEqual(view.plots_tab.selected_plot_name, "Robot Motion")
        self.assertEqual(view.plots_tab.total_point_count, 8)

    def test_record_actions_disable_admin_for_duplicate_live_targets(self):
        intent = ServiceLaunchIntent(ServiceKind.RECORDING, "Recorder")
        identity = ServiceControlIdentity(
            intent=intent,
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        first = candidate_from_control_identity(identity, launch_id="launch-1", observed_at=1.0)
        second = candidate_from_control_identity(identity, launch_id="launch-2", observed_at=2.0)
        selection = ServiceCandidateSelection(
            candidates=(first, second),
            selected_candidate_id="launch-1",
        )

        record = build_record_tab_view_model(selection, now=3.0)

        self.assertTrue(record.candidates[0].conflict)
        self.assertFalse(record.action_by_id["pause"].enabled)
        self.assertIn("duplicate service admin target", record.diagnostics)

    def test_record_action_command_preserves_target_and_tag_payload(self):
        view = build_mock_shell_view_model()
        candidate = candidate_from_control_identity(
            ServiceControlIdentity(
                ServiceLaunchIntent(ServiceKind.RECORDING, "Recorder"),
                session_guid="11111111-2222-3333-4444-555555555555",
            ),
            launch_id="launch-1",
            pid=10,
            hostname="dev-host",
            observed_at=1.0,
        )

        command = build_record_action_command(
            "tag",
            candidate,
            tag_name="night_run",
            description="operator tag",
        )

        self.assertEqual(command.command_type, "service.tag")
        self.assertEqual(command.target, candidate.service.key)
        self.assertEqual(command.payload["tag_name"], "night_run")
        self.assertEqual(command.payload["candidate_id"], "launch-1")
        self.assertTrue(view.record_tab.action_by_id["tag"].enabled)
        with self.assertRaises(ValueError):
            build_record_action_command("tag", candidate)

    def test_record_launch_command_preserves_operator_fields(self):
        command = build_record_launch_command(RecordLaunchViewModel(
            label="Main Recorder",
            config_paths=("services/recording_service_config.xml", "dds/qos/DDS_QOS_PROFILES.xml"),
            config_name="deploy",
            data_domain_id=63,
            admin_domain_id=61,
            monitoring_domain_id=62,
            verbosity="WARN:WARN",
            executable="/opt/rti/bin/rtirecordingservice",
            working_dir="test_output/rs_gui_v2/manual",
            extra_args=("-DDB_DIR=test_output/db",),
        ))

        self.assertEqual(command.command_type, "service.launch_recording")
        self.assertEqual(command.payload["label"], "Main Recorder")
        self.assertEqual(command.payload["config_paths"], [
            "services/recording_service_config.xml",
            "dds/qos/DDS_QOS_PROFILES.xml",
        ])
        self.assertEqual(command.payload["config_name"], "deploy")
        self.assertEqual(command.payload["data_domain_id"], 63)
        self.assertEqual(command.payload["admin_domain_id"], 61)
        self.assertEqual(command.payload["monitoring_domain_id"], 62)

    def test_workspace_action_commands_preserve_file_intent(self):
        save = build_workspace_action_command(
            "save",
            path="services/rs_gui_v2/test_output/demo.json",
            workspace_name="Demo Workspace",
        )
        load = build_workspace_action_command(
            "load",
            path="services/rs_gui_v2/test_output/demo.json",
            workspace_name="Ignored",
        )

        self.assertEqual(save.command_type, "workspace.save")
        self.assertEqual(save.payload["path"], "services/rs_gui_v2/test_output/demo.json")
        self.assertEqual(save.payload["workspace_name"], "Demo Workspace")
        self.assertEqual(load.command_type, "workspace.load")
        self.assertEqual(load.payload, {"path": "services/rs_gui_v2/test_output/demo.json"})


class TestUiFrameScheduler(unittest.TestCase):
    def test_scheduler_drains_events_into_bounded_log(self):
        runtime = AppRuntime()
        runtime.publish_event(AppEvent(
            event_type="test.event",
            source="test",
            payload={"message": "first", "level": "debug"},
            created_at=1.0,
        ))
        runtime.publish_event(AppEvent(
            event_type="test.event",
            source="test",
            payload={"message": "second", "level": "info"},
            created_at=2.0,
        ))
        scheduler = UiFrameScheduler(runtime, max_event_log=1)

        view = scheduler.next_view()

        self.assertEqual(len(view.event_log), 1)
        self.assertEqual(view.event_log[0].message, "second")
        self.assertEqual(runtime.drain_events(), [])
        self.assertEqual(runtime.counters.ui_frames_built, 1)
        self.assertEqual(runtime.counters.ui_events_ingested, 2)
        self.assertEqual(runtime.counters.ui_event_log_dropped, 1)

    def test_shell_exposes_runtime_counters_and_operator_diagnostics(self):
        runtime = AppRuntime()
        runtime.record_samples(received=9, dropped=2)
        runtime.set_operator_diagnostics((
            OperatorDiagnostic("service_admin", "warning", "no admin match", "NO_MATCH"),
        ))
        scheduler = UiFrameScheduler(runtime)

        view = scheduler.next_view()

        status = {item.label: item for item in view.status_items}
        self.assertEqual(status["Frames"].value, "1")
        self.assertEqual(status["Drops"].value, "2")
        self.assertEqual(status["Diagnostics"].value, "2")
        self.assertIn("WARNING service_admin: no admin match", view.operator_diagnostics)
        self.assertTrue(any("WARN record:" in item for item in view.operator_diagnostics))
        self.assertTrue(any(line == "Samples: 9 received / 2 dropped" for line in view.inspector_lines))


class TestDearPyGuiRenderer(unittest.TestCase):
    def test_render_once_uses_injected_dearpygui_module(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(dpg_module=fake)

        view = shell.render_once()

        call_names = [name for name, _args, _kwargs in fake.calls]
        self.assertTrue(fake.context_created)
        self.assertTrue(fake.context_destroyed)
        self.assertIn("window", call_names)
        self.assertIn("tab_bar", call_names)
        self.assertIn("add_button", call_names)
        self.assertEqual(view.record_tab.candidates, ())
        self.assertEqual(view.record_tab.target_label, "No Recording Service")

    def test_replay_buttons_dispatch_commands_when_sink_is_present(self):
        fake = FakeDpg()
        commands = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            command_sink=commands.append,
        )

        shell.render_once()
        _button_callback(fake, "Start")()

        self.assertTrue(any(command.command_type == "replay.start" for command in commands))
        replay_command = next(command for command in commands if command.command_type == "replay.start")
        self.assertEqual(replay_command.target, "replay_service_2d91c4a0")
        self.assertEqual(
            replay_command.payload["database_path"],
            "services/replay_input/robot_run_03",
        )

    def test_convert_buttons_dispatch_commands_when_sink_is_present(self):
        fake = FakeDpg()
        commands = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            command_sink=commands.append,
        )

        shell.render_once()
        _button_callback(fake, "Run Conversion")()

        self.assertTrue(any(command.command_type == "convert.run" for command in commands))
        convert_command = next(command for command in commands if command.command_type == "convert.run")
        self.assertEqual(convert_command.target, "convert-robot-run-03")
        self.assertEqual(convert_command.payload["config_name"], "sqlite_to_json")
        self.assertEqual(
            convert_command.payload["output_storage"]["path"],
            "services/converter_output/robot_run_03_json",
        )

    def test_record_launch_button_dispatches_current_form_values(self):
        fake = FakeDpg()
        commands = []
        shell = DearPyGuiShell(dpg_module=fake, command_sink=commands.append)

        shell.render_once()
        fake.values[RECORD_LAUNCH_LABEL_TAG] = "Manual Recorder"
        fake.values[RECORD_LAUNCH_CONFIG_PATHS_TAG] = "record.xml;qos.xml"
        fake.values[RECORD_LAUNCH_CONFIG_NAME_TAG] = "manual_deploy"
        fake.values[RECORD_LAUNCH_DATA_DOMAIN_TAG] = "63"
        fake.values[RECORD_LAUNCH_ADMIN_DOMAIN_TAG] = "61"
        fake.values[RECORD_LAUNCH_MONITOR_DOMAIN_TAG] = "62"
        fake.values[RECORD_LAUNCH_VERBOSITY_TAG] = "WARN:WARN"
        fake.values[RECORD_LAUNCH_EXTRA_ARGS_TAG] = "-DDB_DIR=test_output/db"
        _button_callback(fake, "Launch Recording Service")()

        self.assertTrue(any(command.command_type == "service.launch_recording" for command in commands))
        launch_command = next(command for command in commands if command.command_type == "service.launch_recording")
        self.assertEqual(launch_command.payload["label"], "Manual Recorder")
        self.assertEqual(launch_command.payload["config_paths"], ["record.xml", "qos.xml"])
        self.assertEqual(launch_command.payload["config_name"], "manual_deploy")
        self.assertEqual(launch_command.payload["data_domain_id"], 63)
        self.assertEqual(launch_command.payload["admin_domain_id"], 61)
        self.assertEqual(launch_command.payload["monitoring_domain_id"], 62)
        self.assertEqual(launch_command.payload["verbosity"], "WARN:WARN")
        self.assertEqual(launch_command.payload["extra_args"], ["-DDB_DIR=test_output/db"])

    def test_workspace_buttons_dispatch_commands_from_inputs(self):
        fake = FakeDpg()
        commands = []
        shell = DearPyGuiShell(dpg_module=fake, command_sink=commands.append)

        shell.render_once()
        fake.values[WORKSPACE_PATH_INPUT_TAG] = "services/rs_gui_v2/test_output/robot.json"
        fake.values[WORKSPACE_NAME_INPUT_TAG] = "Robot Workspace"
        _button_callback(fake, "Save Workspace")()
        _button_callback(fake, "Load Workspace")()

        self.assertEqual([command.command_type for command in commands], ["workspace.save", "workspace.load"])
        self.assertEqual(commands[0].payload["path"], "services/rs_gui_v2/test_output/robot.json")
        self.assertEqual(commands[0].payload["workspace_name"], "Robot Workspace")
        self.assertEqual(commands[1].payload, {"path": "services/rs_gui_v2/test_output/robot.json"})


class TestGuiEntrypoint(unittest.TestCase):
    def test_mock_gui_check_returns_success(self):
        self.assertEqual(main(["--mock-gui-check"]), 0)


def _button_callback(fake: FakeDpg, label: str):
    for name, args, kwargs in fake.calls:
        if name != "add_button":
            continue
        button_label = kwargs.get("label") or (args[0] if args else "")
        if button_label == label:
            return kwargs["callback"]
    raise AssertionError(f"Button not rendered: {label}")


if __name__ == "__main__":
    unittest.main()
