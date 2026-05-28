#!/usr/bin/env python3
"""Headless tests for the rs_gui_v2 Dear PyGui shell bridge."""

import os
import sys
import unittest
from dataclasses import replace


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
    CONSOLE_OUTPUT_TAG,
    DOMAIN_ID_INPUT_WIDTH,
    RECORD_LAUNCH_ADMIN_DOMAIN_TAG,
    RECORD_LAUNCH_CONFIG_NAME_TAG,
    RECORD_LAUNCH_CONFIG_PATHS_TAG,
    RECORD_LAUNCH_DATA_DOMAIN_TAG,
    RECORD_LAUNCH_EXTRA_ARGS_TAG,
    RECORD_LAUNCH_LABEL_TAG,
    RECORD_LAUNCH_MONITOR_DOMAIN_TAG,
    RECORD_LAUNCH_VERBOSITY_TAG,
    RECORD_VAR_EXEC_DIR_EXPR_TAG,
    RECORD_VAR_FILENAME_BASE_TAG,
    RECORD_VAR_FILENAME_EXPR_TAG,
    RECORD_VAR_ROLLOVER_ENABLED_TAG,
    RECORD_VAR_ROLLOVER_MB_TAG,
    RECORD_VAR_SESSION_NAME_TAG,
    RECORD_VAR_STORAGE_PATH_EXPR_TAG,
    RECORD_VAR_WORKSPACE_DIR_TAG,
    WORKSPACE_NAME_INPUT_TAG,
    WORKSPACE_PATH_INPUT_TAG,
    DearPyGuiShell,
    _refresh_record_tab,
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
        self.clipboard_text = ""
        self.context_created = False
        self.context_destroyed = False
        self.stopped = False
        self.exit_callback = None
        self.viewport_close_callback = None

    def create_context(self):
        self.context_created = True
        self.calls.append(("create_context", (), {}))

    def destroy_context(self):
        self.context_destroyed = True
        self.calls.append(("destroy_context", (), {}))

    def stop_dearpygui(self):
        self.stopped = True
        self.calls.append(("stop_dearpygui", (), {}))

    def create_viewport(self, *args, **kwargs):
        self.calls.append(("create_viewport", args, kwargs))

    def set_exit_callback(self, callback):
        self.exit_callback = callback
        self.calls.append(("set_exit_callback", (callback,), {}))

    def set_viewport_close_callback(self, callback):
        self.viewport_close_callback = callback
        self.calls.append(("set_viewport_close_callback", (callback,), {}))

    def setup_dearpygui(self):
        self.calls.append(("setup_dearpygui", (), {}))

    def show_viewport(self):
        self.calls.append(("show_viewport", (), {}))

    def start_dearpygui(self):
        self.calls.append(("start_dearpygui", (), {}))
        if self.exit_callback is not None:
            self.exit_callback()

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
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = ""
        self.calls.append(("group", args, kwargs))
        return FakeContext()

    def table(self, *args, **kwargs):
        self.calls.append(("table", args, kwargs))
        return FakeContext()

    def table_row(self, *args, **kwargs):
        self.calls.append(("table_row", args, kwargs))
        return FakeContext()

    def collapsing_header(self, *args, **kwargs):
        self.calls.append(("collapsing_header", args, kwargs))
        return FakeContext()

    def add_text(self, *args, **kwargs):
        self.calls.append(("add_text", args, kwargs))

    def add_combo(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", "")
        self.calls.append(("add_combo", args, kwargs))

    def add_button(self, *args, **kwargs):
        self.calls.append(("add_button", args, kwargs))

    def add_input_text(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", "")
        self.calls.append(("add_input_text", args, kwargs))

    def add_checkbox(self, *args, **kwargs):
        tag = kwargs.get("tag")
        if tag:
            self.values[tag] = kwargs.get("default_value", False)
        self.calls.append(("add_checkbox", args, kwargs))

    def set_value(self, tag, value):
        self.values[tag] = value
        self.calls.append(("set_value", (tag, value), {}))

    def set_clipboard_text(self, value):
        self.clipboard_text = value
        self.calls.append(("set_clipboard_text", (value,), {}))

    def configure_item(self, tag, **kwargs):
        self.calls.append(("configure_item", (tag,), kwargs))

    def does_item_exist(self, tag):
        return tag in self.values

    def delete_item(self, tag, **kwargs):
        self.calls.append(("delete_item", (tag,), kwargs))

    def push_container_stack(self, tag):
        self.calls.append(("push_container_stack", (tag,), {}))

    def pop_container_stack(self):
        self.calls.append(("pop_container_stack", (), {}))

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
            working_dir="services/rs_gui_v2/manual",
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

    def test_console_tab_renders_full_event_output(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
        )

        shell.render_once()

        self.assertIn(CONSOLE_OUTPUT_TAG, fake.values)
        console = fake.values[CONSOLE_OUTPUT_TAG]
        self.assertIn("=== Events ===", console)
        self.assertIn("payload:", console)
        self.assertIn("Monitoring active on domain 0", console)

    def test_console_copy_button_copies_full_output(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
        )

        shell.render_once()
        _button_callback(fake, "Copy Console")()

        self.assertIn("=== Events ===", fake.clipboard_text)
        self.assertIn("Monitoring active on domain 0", fake.clipboard_text)

    def test_record_refresh_rebuilds_action_callbacks_for_selected_service(self):
        fake = FakeDpg()
        commands = []
        shell = DearPyGuiShell(dpg_module=fake, command_sink=commands.append)
        shell.render_once()

        _refresh_record_tab(fake, build_mock_shell_view_model(), commands.append)
        _latest_button_callback(fake, "Shutdown")()

        self.assertTrue(any(command.command_type == "service.shutdown" for command in commands))
        shutdown = next(command for command in commands if command.command_type == "service.shutdown")
        self.assertEqual(shutdown.payload["candidate_id"], "launch-recording-main")

    def test_all_command_buttons_dispatch_expected_command_types(self):
        expected = {
            "Launch Recording Service": {"service.launch_recording"},
            "Pause": {"service.pause"},
            "Apply Tag": {"service.tag"},
            "Shutdown": {"service.shutdown", "replay.shutdown"},
            "Start": {"replay.start"},
            "Select": {"replay.select_target", "topics.select"},
            "Run Conversion": {"convert.run"},
            "Open Output": {"convert.open_output"},
            "Inspect Output": {"convert.inspect_output"},
            "Unsubscribe": {"topics.unsubscribe"},
            "Toggle Internal": {"topics.set_include_internal"},
            "Plot": {"topics.set_plot_field_selected"},
            "Save Workspace": {"workspace.save"},
            "Load Workspace": {"workspace.load"},
        }

        for label, expected_types in expected.items():
            fake = FakeDpg()
            commands = []
            shell = DearPyGuiShell(
                view_provider=build_mock_shell_view_model,
                dpg_module=fake,
                command_sink=commands.append,
            )
            shell.render_once()

            for callback in _enabled_button_callbacks(fake, label):
                callback()

            emitted = {command.command_type for command in commands}
            self.assertTrue(
                emitted & expected_types,
                f"{label!r} emitted {sorted(emitted)}; expected one of {sorted(expected_types)}",
            )

    def test_every_enabled_callback_button_is_invokable(self):
        fake = FakeDpg()
        commands = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            command_sink=commands.append,
        )
        shell.render_once()

        invoked = []
        for label, callback in _enabled_callback_buttons(fake):
            with self.subTest(button=label):
                callback()
                invoked.append(label)

        self.assertIn("Launch Recording Service", invoked)
        self.assertIn("Copy Console", invoked)
        self.assertTrue(any(command.command_type == "service.launch_recording" for command in commands))

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
        fake.values[RECORD_VAR_SESSION_NAME_TAG] = "Manual Recorder Session"
        fake.values[RECORD_VAR_WORKSPACE_DIR_TAG] = "test_output/recordings"
        fake.values[RECORD_VAR_EXEC_DIR_EXPR_TAG] = "manual_%ts%"
        fake.values[RECORD_VAR_FILENAME_EXPR_TAG] = "capture_%auto:0-9%.db"
        fake.values[RECORD_VAR_ROLLOVER_ENABLED_TAG] = "yes"
        fake.values[RECORD_VAR_ROLLOVER_MB_TAG] = "2048"
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
        self.assertIn("-DDB_DIR=test_output/db", launch_command.payload["extra_args"])
        self.assertIn("-DREC_DOMAIN_ID=63", launch_command.payload["extra_args"])
        self.assertIn("-DREC_ADMIN_DOMAIN_ID=61", launch_command.payload["extra_args"])
        self.assertIn("-DREC_MON_DOMAIN_ID=62", launch_command.payload["extra_args"])
        self.assertIn("-DREC_SESSION_NAME=Manual_Recorder_Session", launch_command.payload["extra_args"])
        self.assertIn("-DREC_WORKSPACE_DIR=test_output/recordings", launch_command.payload["extra_args"])
        self.assertIn("-DREC_EXEC_DIR_EXPR=manual_%ts%", launch_command.payload["extra_args"])
        self.assertIn("-DREC_FILENAME_EXPR=capture_%auto:0-9%.db", launch_command.payload["extra_args"])
        self.assertIn("-DREC_ROLLOVER_ENABLED=true", launch_command.payload["extra_args"])
        self.assertIn("-DREC_ROLLOVER_MB=2048", launch_command.payload["extra_args"])
        self.assertNotIn("-DREC_SESSION_NAME=Manual Recorder Session", launch_command.payload["extra_args"])

    def test_record_launch_domain_fields_render_before_advanced_fields(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(dpg_module=fake, command_sink=lambda _command: True)

        shell.render_once()

        text_labels = [args[0] for name, args, _kwargs in fake.calls if name == "add_text" and args]
        self.assertLess(text_labels.index("Domain IDs"), text_labels.index("Storage Naming"))
        self.assertLess(text_labels.index("Domain IDs"), text_labels.index("Logging Verbosity"))
        self.assertIn("Output Root Directory", text_labels)
        self.assertIn("Execution Subdirectory", text_labels)
        self.assertIn("File Name", text_labels)
        self.assertIn("Filename Template", text_labels)
        self.assertIn("Derived Storage Expression", text_labels)
        self.assertIn("Enable Rollover", text_labels)
        self.assertIn("Rollover Size MB", text_labels)
        input_kwargs_by_tag = {
            kwargs.get("tag"): kwargs
            for name, _args, kwargs in fake.calls
            if name == "add_input_text" and kwargs.get("tag")
        }
        self.assertEqual(input_kwargs_by_tag[RECORD_LAUNCH_DATA_DOMAIN_TAG]["width"], DOMAIN_ID_INPUT_WIDTH)
        self.assertEqual(input_kwargs_by_tag[RECORD_LAUNCH_ADMIN_DOMAIN_TAG]["width"], DOMAIN_ID_INPUT_WIDTH)
        self.assertEqual(input_kwargs_by_tag[RECORD_LAUNCH_MONITOR_DOMAIN_TAG]["width"], DOMAIN_ID_INPUT_WIDTH)
        self.assertTrue(input_kwargs_by_tag[RECORD_VAR_STORAGE_PATH_EXPR_TAG]["readonly"])
        self.assertEqual(
            fake.values[RECORD_VAR_STORAGE_PATH_EXPR_TAG],
            "log_dir/recording_%ts%/data_%auto:0-9%.db",
        )

    def test_record_launch_naming_fields_generate_syntax(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(dpg_module=fake, command_sink=lambda _command: True)

        shell.render_once()
        fake.values[RECORD_VAR_WORKSPACE_DIR_TAG] = "test_output/recordings"
        fake.values[RECORD_VAR_EXEC_DIR_EXPR_TAG] = "custom"
        fake.values[RECORD_VAR_FILENAME_BASE_TAG] = "robot run"
        _input_callback(fake, RECORD_VAR_FILENAME_BASE_TAG)()

        self.assertEqual(fake.values[RECORD_VAR_FILENAME_EXPR_TAG], "robot_run_%auto:0-9%.db")
        self.assertEqual(
            fake.values[RECORD_VAR_STORAGE_PATH_EXPR_TAG],
            "test_output/recordings/custom/robot_run_%auto:0-9%.db",
        )
        fake.values[RECORD_VAR_EXEC_DIR_EXPR_TAG] = "recording_%ts%"
        _input_callback(fake, RECORD_VAR_EXEC_DIR_EXPR_TAG)()

        self.assertEqual(
            fake.values[RECORD_VAR_STORAGE_PATH_EXPR_TAG],
            "test_output/recordings/recording_%ts%/robot_run_%auto:0-9%.db",
        )
        fake.values[RECORD_VAR_FILENAME_EXPR_TAG] = "manual_%ts%.db"
        _input_callback(fake, RECORD_VAR_FILENAME_EXPR_TAG)()

        self.assertEqual(
            fake.values[RECORD_VAR_STORAGE_PATH_EXPR_TAG],
            "test_output/recordings/recording_%ts%/manual_%ts%.db",
        )
        button_labels = [
            kwargs.get("label") or (args[0] if args else "")
            for name, args, kwargs in fake.calls
            if name == "add_button"
        ]
        self.assertNotIn("Add Timestamp Dir", button_labels)
        self.assertNotIn("Apply Filename", button_labels)
        self.assertNotIn("Timestamp Filename", button_labels)

    def test_record_details_render_in_collapsed_section(self):
        fake = FakeDpg()
        base_view = build_mock_shell_view_model()
        view = replace(
            base_view,
            record_tab=replace(
                base_view.record_tab,
                diagnostics=("duplicate service admin target", "admin not matched"),
            ),
        )
        shell = DearPyGuiShell(view_provider=lambda: view, dpg_module=fake, command_sink=lambda _command: True)

        shell.render_once()

        header_index = next(
            index for index, (name, _args, kwargs) in enumerate(fake.calls)
            if name == "collapsing_header" and kwargs.get("label") == "Record Details (2 diagnostics)"
        )
        diagnostic_index = next(
            index for index, (name, args, _kwargs) in enumerate(fake.calls)
            if name == "add_text" and args and args[0] == "Diagnostic: duplicate service admin target"
        )
        history_index = next(
            index for index, (name, args, _kwargs) in enumerate(fake.calls)
            if name == "add_text" and args and args[0] == "Command History"
        )
        monitoring_index = next(
            index for index, (name, args, _kwargs) in enumerate(fake.calls)
            if name == "add_text" and args and args[0] == "Monitoring Summary"
        )
        headers = [kwargs for name, _args, kwargs in fake.calls if name == "collapsing_header"]
        record_header = next(kwargs for kwargs in headers if kwargs.get("label") == "Record Details (2 diagnostics)")
        self.assertFalse(record_header["default_open"])
        self.assertLess(header_index, diagnostic_index)
        self.assertLess(header_index, history_index)
        self.assertLess(header_index, monitoring_index)

    def test_close_prompt_uses_window_close_callback_with_detected_processes(self):
        fake = FakeDpg()
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.render_once()
        shell._close_prompt_callback(fake)()

        text_labels = [args[0] for name, args, _kwargs in fake.calls if name == "add_text" and args]
        self.assertIn("Detected RTI service processes", text_labels)
        self.assertTrue(any("Recording Service" in label and "launched by this GUI" in label for label in text_labels))
        self.assertTrue(any("detected externally" in label for label in text_labels))
        self.assertEqual(close_requests, [])
        button_labels = [
            kwargs.get("label") or (args[0] if args else "")
            for name, args, kwargs in fake.calls
            if name == "add_button"
        ]
        self.assertNotIn("Close App", button_labels)

    def test_close_prompt_shutdown_button_targets_only_gui_launched_items(self):
        fake = FakeDpg()
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.render_once()
        shell._close_prompt_callback(fake)()
        _button_callback(fake, "Shutdown GUI-Launched")()

        self.assertTrue(fake.stopped)
        self.assertEqual(close_requests[0][0], "shutdown_gui_launched")
        self.assertIn("record:launch-recording-main", close_requests[0][1])
        self.assertFalse(any("discovery:recording:old" in item_id for item_id in close_requests[0][1]))

    def test_native_window_close_shuts_down_gui_launched_items(self):
        fake = FakeDpg()
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.run()

        self.assertTrue(any(name == "set_exit_callback" for name, _args, _kwargs in fake.calls))
        self.assertTrue(any(name == "set_viewport_close_callback" for name, _args, _kwargs in fake.calls))
        viewport_calls = [kwargs for name, _args, kwargs in fake.calls if name == "create_viewport"]
        self.assertEqual(viewport_calls[0].get("disable_close"), False)
        self.assertEqual(close_requests[0][0], "shutdown_gui_launched")
        self.assertIn("record:launch-recording-main", close_requests[0][1])
        self.assertFalse(any("discovery:recording:old" in item_id for item_id in close_requests[0][1]))

    def test_close_dialog_action_is_not_replayed_by_exit_cleanup(self):
        fake = FakeDpg()
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.render_once()
        shell._close_prompt_callback(fake)()
        _button_callback(fake, "Shutdown GUI-Launched")()
        shell._exit_cleanup_callback()()

        self.assertEqual(len(close_requests), 1)
        self.assertEqual(close_requests[0][0], "shutdown_gui_launched")

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


def _input_callback(fake: FakeDpg, tag: str):
    for name, _args, kwargs in fake.calls:
        if name == "add_input_text" and kwargs.get("tag") == tag:
            return kwargs["callback"]
    raise AssertionError(f"Input callback not rendered: {tag}")


def _latest_button_callback(fake: FakeDpg, label: str):
    for name, args, kwargs in reversed(fake.calls):
        if name != "add_button":
            continue
        button_label = kwargs.get("label") or (args[0] if args else "")
        if button_label == label:
            return kwargs["callback"]
    raise AssertionError(f"Button not rendered: {label}")


def _enabled_button_callbacks(fake: FakeDpg, label: str):
    callbacks = []
    for name, args, kwargs in fake.calls:
        if name != "add_button" or not kwargs.get("enabled", True):
            continue
        button_label = kwargs.get("label") or (args[0] if args else "")
        callback = kwargs.get("callback")
        if button_label == label and callback is not None:
            callbacks.append(callback)
    if not callbacks:
        raise AssertionError(f"Enabled button not rendered: {label}")
    return callbacks


def _enabled_callback_buttons(fake: FakeDpg):
    buttons = []
    for name, args, kwargs in fake.calls:
        if name != "add_button" or not kwargs.get("enabled", True):
            continue
        callback = kwargs.get("callback")
        if callback is None:
            continue
        button_label = kwargs.get("label") or (args[0] if args else "")
        buttons.append((button_label, callback))
    return buttons


if __name__ == "__main__":
    unittest.main()
