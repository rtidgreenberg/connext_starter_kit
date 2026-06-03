#!/usr/bin/env python3
"""Headless tests for the rs_gui_v2 Dear PyGui shell bridge."""

import os
import sys
import unittest
from dataclasses import replace
from unittest.mock import patch


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
    CLOSE_POLICY_NOTE_TAG,
    CLOSE_POLICY_NOTE_TEXT,
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
from gui.view_models import build_empty_shell_view_model
from gui.tabs.record_tab import (
    RecordLaunchViewModel,
    build_record_action_command,
    build_record_launch_command,
    build_record_tab_view_model,
)
from rs_gui_v2_app import main
from fakes import FakeContext, FakeDpg, NoViewportCloseFakeDpg, ManualFrameFakeDpg


class FrameCallbackFakeDpg(FakeDpg):
    def __init__(self, frame_count=2, call_exit_callback=True):
        super().__init__()
        self.frame_count = int(frame_count)
        self.call_exit_callback = bool(call_exit_callback)
        self.current_frame = 0
        self.frame_callbacks = {}

    def get_frame_count(self):
        return self.current_frame

    def set_frame_callback(self, frame, callback, **kwargs):
        self.frame_callbacks[int(frame)] = callback
        self.calls.append(("set_frame_callback", (frame, callback), kwargs))

    def is_dearpygui_running(self):
        return True

    def render_dearpygui_frame(self):
        self.calls.append(("render_dearpygui_frame", (), {}))

    def start_dearpygui(self):
        self.calls.append(("start_dearpygui", (), {}))
        for frame in range(1, self.frame_count + 1):
            self.current_frame = frame
            callback = self.frame_callbacks.pop(frame, None)
            if callback is not None:
                callback()
        if self.call_exit_callback and self.exit_callback is not None:
            self.exit_callback()
        self.calls.append(("start_dearpygui_returned", (), {}))


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
        self.assertEqual(view.event_log[0].source, "scheduler")
        self.assertIn("1 event log entries dropped", view.event_log[0].message)
        self.assertEqual(view.event_log[0].level, "warning")
        self.assertEqual(runtime.drain_events(), [])
        self.assertEqual(runtime.counters.ui_frames_built, 1)
        self.assertEqual(runtime.counters.ui_events_ingested, 2)
        self.assertEqual(runtime.counters.ui_event_log_dropped, 1)

    def test_scheduler_overflow_warning_accumulates_across_frames(self):
        runtime = AppRuntime()
        scheduler = UiFrameScheduler(runtime, max_event_log=2)

        # First batch: 4 events, cap=2 → 2 dropped
        for i in range(4):
            runtime.publish_event(AppEvent(
                event_type="test.event",
                source="test",
                payload={"message": f"msg{i}", "level": "info"},
                created_at=float(i),
            ))
        view = scheduler.next_view()
        self.assertEqual(len(view.event_log), 2)
        self.assertEqual(view.event_log[-1].source, "scheduler")
        self.assertIn("2 event log entries dropped", view.event_log[-1].message)
        self.assertEqual(runtime.counters.ui_event_log_dropped, 2)

        # Second batch: 1 event, fits within cap, no new warning
        runtime.publish_event(AppEvent(
            event_type="test.event",
            source="test",
            payload={"message": "fits", "level": "info"},
            created_at=10.0,
        ))
        view2 = scheduler.next_view()
        # Previous 2 entries + new event = 3, cap=2, so 1 more dropped
        self.assertEqual(runtime.counters.ui_event_log_dropped, 3)  # 2 + 1

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

    def test_record_refresh_renders_current_file_for_selected_service(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(dpg_module=fake, command_sink=lambda _command: True)
        shell.render_once()
        identity = ServiceControlIdentity(
            ServiceLaunchIntent(ServiceKind.RECORDING, "Recorder"),
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        candidate = candidate_from_control_identity(
            identity,
            launch_id="launch-1",
            pid=100,
            hostname="dev-host",
            observed_state="RUNNING",
            details={"current_file": "log_dir/recording_123/data_0.db"},
            observed_at=1.0,
        )
        record = build_record_tab_view_model(
            ServiceCandidateSelection(candidates=(candidate,), selected_candidate_id="launch-1"),
            now=2.0,
        )
        view = replace(build_empty_shell_view_model(), record_tab=record)

        _refresh_record_tab(fake, view, lambda _command: True)

        rendered_text = [args[0] for name, args, _kwargs in fake.calls if name == "add_text" and args]
        self.assertIn("log_dir/recording_123/data_0.db", rendered_text)

    def test_interactive_command_sink_paints_refreshed_record_frame(self):
        fake = ManualFrameFakeDpg(frame_count=0)
        views = (build_empty_shell_view_model(), build_mock_shell_view_model())
        view_calls = []
        commands = []

        def _view_provider():
            index = min(len(view_calls), len(views) - 1)
            view_calls.append(index)
            return views[index]

        shell = DearPyGuiShell(
            view_provider=_view_provider,
            dpg_module=fake,
            command_sink=lambda command: commands.append(command) or True,
        )
        shell.render_once()

        shell._interactive_command_sink(fake)(build_record_launch_command(views[1].record_tab.launch))

        self.assertTrue(commands)
        self.assertTrue(any(
            name == "add_text" and args and str(args[0]).startswith("Recording target: Recording Service")
            for name, args, _kwargs in fake.calls
        ))
        self.assertTrue(any(name == "render_dearpygui_frame" for name, _args, _kwargs in fake.calls))

    def test_all_command_buttons_dispatch_expected_command_types(self):
        expected = {
            "Launch Recording Service": {"service.launch_recording"},
            "Pause": {"service.pause"},
            "Apply Tag": {"service.tag"},
            "Shutdown": {"service.shutdown", "replay.shutdown"},
            "Start": {"replay.start"},
            "Select": {"replay.select_target"},
            "Run Conversion": {"convert.run"},
            "Open Output": {"convert.open_output"},
            "Inspect Output": {"convert.inspect_output"},
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
        debug_index = next(
            index for index, (name, args, _kwargs) in enumerate(fake.calls)
            if name == "add_text" and args and args[0] == "Debug"
        )
        runtime_index = next(
            index for index, (name, args, _kwargs) in enumerate(fake.calls)
            if name == "add_text" and args and args[0].startswith("Runtime: ")
        )
        dds_index = next(
            index for index, (name, args, _kwargs) in enumerate(fake.calls)
            if name == "add_text" and args and args[0].startswith("DDS: ")
        )
        headers = [kwargs for name, _args, kwargs in fake.calls if name == "collapsing_header"]
        record_header = next(kwargs for kwargs in headers if kwargs.get("label") == "Record Details (2 diagnostics)")
        self.assertFalse(record_header["default_open"])
        self.assertLess(header_index, diagnostic_index)
        self.assertLess(header_index, history_index)
        self.assertLess(header_index, monitoring_index)
        self.assertLess(header_index, debug_index)
        self.assertLess(debug_index, runtime_index)
        self.assertLess(debug_index, dds_index)

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

    def test_main_window_hides_internal_close_button(self):
        fake = FakeDpg()
        shell = DearPyGuiShell(
            view_provider=build_empty_shell_view_model,
            dpg_module=fake,
        )

        shell.render_once()

        main_window = next(
            kwargs for name, _args, kwargs in fake.calls
            if name == "window" and kwargs.get("tag") == "rs_gui_v2_main_window"
        )
        self.assertTrue(main_window["no_close"])
        self.assertEqual(fake.values[CLOSE_POLICY_NOTE_TAG], CLOSE_POLICY_NOTE_TEXT)

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

    def test_native_window_close_exits_when_no_active_processes_remain(self):
        fake = FakeDpg()
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_empty_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.render_once()
        result = shell._close_prompt_callback(fake)()

        self.assertTrue(result)
        self.assertTrue(fake.stopped)
        self.assertEqual(close_requests, [("leave_running", ())])
        self.assertFalse(any(
            name == "window" and kwargs.get("tag") == "rs_gui_v2_close_modal"
            for name, _args, kwargs in fake.calls
        ))

    def test_manual_frame_loop_refreshes_record_tab_snapshots(self):
        fake = ManualFrameFakeDpg(frame_count=2)
        initial_view = build_mock_shell_view_model()
        exited_rows = tuple(
            replace(row, state="exited") if row.selected else row
            for row in initial_view.record_tab.candidates
        )
        exited_view = replace(
            initial_view,
            record_tab=replace(
                initial_view.record_tab,
                observed_state="exited",
                candidates=exited_rows,
            ),
        )
        views = [initial_view, exited_view]
        view_calls = []

        def _view_provider():
            index = min(len(view_calls), len(views) - 1)
            view_calls.append(index)
            return views[index]

        shell = DearPyGuiShell(view_provider=_view_provider, dpg_module=fake)

        shell.run()

        self.assertGreaterEqual(len(view_calls), 2)
        self.assertTrue(any(name == "render_dearpygui_frame" for name, _args, _kwargs in fake.calls))
        self.assertTrue(any(
            name == "delete_item"
            and args == ("rs_gui_v2_record_tab_dynamic",)
            and kwargs.get("children_only") is True
            for name, args, kwargs in fake.calls
        ))
        self.assertTrue(any(
            name == "add_text" and args and args[0] == "exited"
            for name, args, _kwargs in fake.calls
        ))

    def test_frame_callback_survives_view_provider_exception(self):
        fake = FrameCallbackFakeDpg(frame_count=4)
        call_count = {"value": 0}

        def _failing_then_ok_provider():
            call_count["value"] += 1
            if call_count["value"] in (2, 3):
                raise RuntimeError("transient error")
            return build_mock_shell_view_model()

        shell = DearPyGuiShell(view_provider=_failing_then_ok_provider, dpg_module=fake)
        shell.run()

        # Frame callback should have been re-registered after exceptions
        self.assertGreaterEqual(call_count["value"], 4)
        # The successful calls should have rendered content
        self.assertTrue(any(
            name == "add_text"
            for name, _args, _kwargs in fake.calls
        ))

    def test_frame_callback_refresh_uses_half_second_cadence(self):
        fake = FrameCallbackFakeDpg(frame_count=6)
        view_calls = []

        def _view_provider():
            view_calls.append(len(view_calls))
            return build_mock_shell_view_model()

        shell = DearPyGuiShell(view_provider=_view_provider, dpg_module=fake)

        with patch(
                "gui.main_window.time.monotonic",
                side_effect=(0.10, 0.49, 0.50, 0.75, 0.99, 1.00),
        ):
            shell.run()

        # Initial render plus refreshes at 0.50s and 1.00s only.
        self.assertEqual(len(view_calls), 3)
        self.assertEqual(sum(
            1 for name, args, kwargs in fake.calls
            if name == "delete_item"
            and args == ("rs_gui_v2_record_tab_dynamic",)
            and kwargs.get("children_only") is True
        ), 2)

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

    def test_native_window_close_fallback_cleans_up_when_viewport_callback_is_unavailable(self):
        fake = NoViewportCloseFakeDpg()
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.run()

        self.assertTrue(any(name == "set_exit_callback" for name, _args, _kwargs in fake.calls))
        self.assertFalse(any(name == "set_viewport_close_callback" for name, _args, _kwargs in fake.calls))
        self.assertEqual(close_requests[0][0], "shutdown_gui_launched")
        self.assertIn("record:launch-recording-main", close_requests[0][1])

    def test_native_exit_cleanup_is_deferred_until_dearpygui_loop_returns(self):
        fake = FrameCallbackFakeDpg(frame_count=2)
        close_request_call_count = []

        def _close_handler(action, item_ids):
            close_request_call_count.append((action, item_ids, len(fake.calls)))
            return True

        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=_close_handler,
        )

        shell.run()

        self.assertEqual(close_request_call_count[0][0], "shutdown_gui_launched")
        returned_index = next(
            index for index, (name, _args, _kwargs) in enumerate(fake.calls)
            if name == "start_dearpygui_returned"
        )
        destroy_index = next(
            index for index, (name, _args, _kwargs) in enumerate(fake.calls)
            if name == "destroy_context"
        )
        self.assertGreater(close_request_call_count[0][2], returned_index)
        self.assertEqual(close_request_call_count[0][2], destroy_index)
        self.assertTrue(any(name == "set_frame_callback" for name, _args, _kwargs in fake.calls))
        self.assertFalse(any(name == "render_dearpygui_frame" for name, _args, _kwargs in fake.calls))

    def test_dearpygui_loop_return_triggers_cleanup_without_exit_callback(self):
        fake = FrameCallbackFakeDpg(frame_count=2, call_exit_callback=False)
        close_requests = []
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
            close_handler=lambda action, item_ids: close_requests.append((action, item_ids)) or True,
        )

        shell.run()

        self.assertEqual(close_requests[0][0], "shutdown_gui_launched")
        self.assertIn("record:launch-recording-main", close_requests[0][1])
        returned_index = next(
            index for index, (name, _args, _kwargs) in enumerate(fake.calls)
            if name == "start_dearpygui_returned"
        )
        destroy_index = next(
            index for index, (name, _args, _kwargs) in enumerate(fake.calls)
            if name == "destroy_context"
        )
        self.assertLess(returned_index, destroy_index)

    def test_close_policy_note_replaces_explicit_exit_button(self):
        fake = ManualFrameFakeDpg(frame_count=0)
        shell = DearPyGuiShell(
            view_provider=build_mock_shell_view_model,
            dpg_module=fake,
        )

        shell.run()

        button_labels = [
            kwargs.get("label") or (args[0] if args else "")
            for name, args, kwargs in fake.calls
            if name == "add_button"
        ]
        self.assertNotIn("Exit", button_labels)
        self.assertEqual(fake.values[CLOSE_POLICY_NOTE_TAG], CLOSE_POLICY_NOTE_TEXT)

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
