#!/usr/bin/env python3
"""Debug log behavior tests for rti_view main window."""

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

from rti_view.discovery import DiscoveredEndpoint, DiscoveredParticipant, registry
from rti_view.subscriber import ReaderSetupResult
from rti_view.views.main_window import (
    DEBUG_LOG_TAG,
    FIELD_LIST_TAG,
    MESSAGE_DATA_TAG,
    PLOT_SERIES_TAG,
    STATUS_TEXT_TAG,
    RtiViewShell,
    _field_tree,
)
from fakes import FakeDynamicType, FakeInfo, FakeMember, FakeReader


class FakeSample:
    def __init__(self, values):
        self._values = dict(values)

    def __getitem__(self, field_path):
        return self.get_value(field_path)

    def get_value(self, field_path):
        value = self
        for part in field_path.split("."):
            value = value._values[part] if isinstance(value, FakeSample) else value[part]
        return value

    def items(self):
        return self._values.items()


class FakeDpg:
    def __init__(self):
        self.values = {}
        self.items = {}
        self.clipboard = ""

    def set_value(self, tag, value):
        self.values[tag] = value

    def get_value(self, tag):
        return self.values.get(tag)

    def configure_item(self, tag, **kwargs):
        self.items.setdefault(tag, {}).update(kwargs)

    def does_item_exist(self, tag):
        return tag in {DEBUG_LOG_TAG, STATUS_TEXT_TAG}

    def set_clipboard_text(self, value):
        self.clipboard = value


class TestMainWindowDebugLog(unittest.TestCase):
    def tearDown(self):
        registry.clear()

    def test_status_messages_update_copyable_debug_log(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=3, dpg_module=dpg)

        shell._set_status(dpg, "Listening on domain 3")
        shell._set_status(dpg, "Refreshed domain 3")

        self.assertIn("Listening on domain 3", shell.debug_log_text)
        self.assertIn("Refreshed domain 3", dpg.values[DEBUG_LOG_TAG])
        self.assertEqual(dpg.values[STATUS_TEXT_TAG], "Refreshed domain 3")

    def test_copy_debug_log_puts_log_on_clipboard(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=3, dpg_module=dpg)
        shell._set_status(dpg, "Discovery refresh failed: sample error")

        shell._copy_debug_log_callback(dpg)()

        self.assertIn("Discovery refresh failed: sample error", dpg.clipboard)

    def test_exception_status_includes_traceback_text(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=3, dpg_module=dpg)

        try:
            raise RuntimeError("sample failure")
        except RuntimeError as exc:
            shell._set_exception_status(dpg, f"Discovery refresh failed: {exc}")

        self.assertIn("Discovery refresh failed: sample failure", shell.debug_log_text)
        self.assertIn("RuntimeError: sample failure", shell.debug_log_text)

    def test_discovered_writer_type_is_logged_once(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=3, dpg_module=dpg)
        dynamic_type = FakeDynamicType("STRUCTURE_TYPE", "Telemetry", (
            FakeMember("temperature", FakeDynamicType("FLOAT_64_TYPE")),
            FakeMember("status", FakeDynamicType("STRING_TYPE")),
        ))
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="Telemetry",
            dynamic_type=dynamic_type,
            kind="Writer",
        ))

        shell._log_discovered_topic_types(dpg)
        shell._log_discovered_topic_types(dpg)

        self.assertEqual(shell.debug_log_text.count("Discovered writer topic 'Telemetry'"), 1)
        self.assertIn("DynamicType: Telemetry", shell.debug_log_text)
        self.assertIn("temperature: FLOAT_64_TYPE plottable", shell.debug_log_text)
        self.assertIn("status: STRING_TYPE", shell.debug_log_text)

    def test_missing_dynamic_type_logs_builtin_type_fields(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=3, dpg_module=dpg)
        registry.add_endpoint(DiscoveredEndpoint(
            key="writer-1",
            participant_key="participant-1",
            topic_name="Square",
            type_name="ShapeType",
            dynamic_type=None,
            kind="Writer",
            type_debug=("type=None", "type_name='ShapeType'", "type_object=None"),
        ))

        shell._log_discovered_topic_types(dpg)

        self.assertIn("Discovered writer topic 'Square' with type 'ShapeType'", shell.debug_log_text)
        self.assertIn("DynamicType: unavailable from discovery", shell.debug_log_text)
        self.assertIn("Builtin type fields:", shell.debug_log_text)
        self.assertIn("type_name='ShapeType'", shell.debug_log_text)

    def test_field_tree_builds_nested_member_paths(self):
        tree = _field_tree(("pose.position.x", "pose.position.y", "status"))

        self.assertEqual(tree["pose"]["position"]["x"]["__path__"], "pose.position.x")
        self.assertEqual(tree["pose"]["position"]["y"]["__path__"], "pose.position.y")
        self.assertEqual(tree["status"]["__path__"], "status")

    def test_field_tree_callback_selects_nested_member(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=0, dpg_module=dpg)
        shell._field_choices = ("pose.position.x",)

        accepted = shell._field_tree_callback(dpg)(user_data="pose.position.x")

        self.assertTrue(accepted)
        self.assertEqual(shell.selection.field_path, "pose.position.x")
        self.assertEqual(dpg.values[FIELD_LIST_TAG], "pose.position.x")

    def test_subscribe_creates_reader_for_selected_field(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=0, dpg_module=dpg)
        shell._participant = object()
        endpoint = DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=object(),
            kind="Writer",
        )
        shell._topic_endpoints = {"Telemetry": endpoint}
        shell._field_choices = ("pose.position.x",)
        shell._set_selection(dpg, shell.selection.__class__(
            domain_id=0,
            topic_name="Telemetry",
            field_path="pose.position.x",
        ))
        reader = FakeReader(((FakeSample({
            "pose": FakeSample({"position": FakeSample({"x": 12})}),
        }), FakeInfo(True)),))

        with patch("rti_view.views.main_window.setup_matched_reader", return_value=ReaderSetupResult(
                reader=reader,
                subscriber=object(),
        )) as setup_reader:
            self.assertTrue(shell._subscribe_selected_field(dpg))

        setup_reader.assert_called_once_with(shell._participant, endpoint)
        self.assertIn("Subscribed to Telemetry.pose.position.x", dpg.values[STATUS_TEXT_TAG])

    def test_pump_subscription_updates_message_and_plot_values(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=0, dpg_module=dpg)
        shell._participant = object()
        endpoint = DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=object(),
            kind="Writer",
        )
        shell._topic_endpoints = {"Telemetry": endpoint}
        shell._field_choices = ("pose.position.x",)
        shell._set_selection(dpg, shell.selection.__class__(
            domain_id=0,
            topic_name="Telemetry",
            field_path="pose.position.x",
        ))
        reader = FakeReader(((FakeSample({
            "pose": FakeSample({"position": FakeSample({"x": 12})}),
        }), FakeInfo(True)),))

        with patch("rti_view.views.main_window.setup_matched_reader", return_value=ReaderSetupResult(
                reader=reader,
                subscriber=object(),
        )):
            shell._subscribe_selected_field(dpg)
        shell._pump_subscription(dpg)

        self.assertIn("Telemetry.pose.position.x = 12", dpg.values[MESSAGE_DATA_TAG])
        self.assertEqual(dpg.values[PLOT_SERIES_TAG][1], [12.0])

    def test_subscribe_can_start_before_field_selection(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=0, dpg_module=dpg)
        shell._participant = object()
        shell._topic_endpoints = {"Telemetry": DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=object(),
            kind="Writer",
        )}
        shell._set_selection(dpg, shell.selection.__class__(domain_id=0, topic_name="Telemetry"))
        reader = FakeReader(())

        with patch("rti_view.views.main_window.setup_matched_reader", return_value=ReaderSetupResult(
                reader=reader,
                subscriber=object(),
        )):
            self.assertTrue(shell._subscribe_selected_field(dpg))

        self.assertEqual(dpg.values[STATUS_TEXT_TAG], "Subscribed to Telemetry")

    def test_mode_toggle_resyncs_existing_subscription_view(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=0, dpg_module=dpg)
        shell._participant = object()
        endpoint = DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=object(),
            kind="Writer",
        )
        shell._topic_endpoints = {"Telemetry": endpoint}
        shell._set_selection(dpg, shell.selection.__class__(
            domain_id=0,
            topic_name="Telemetry",
            field_path="pose.position.x",
            mode="plot",
        ))
        reader = FakeReader(((FakeSample({
            "pose": FakeSample({"position": FakeSample({"x": 12})}),
        }), FakeInfo(True)),))

        with patch("rti_view.views.main_window.setup_matched_reader", return_value=ReaderSetupResult(
                reader=reader,
                subscriber=object(),
        )):
            shell._subscribe_selected_field(dpg)
        shell._pump_subscription(dpg)

        subscription = shell._subscription
        shell._mode_callback(dpg)(app_data="Message Data")

        self.assertIs(shell._subscription, subscription)
        self.assertEqual(shell.selection.mode, "text")
        self.assertIn("Telemetry.pose.position.x = 12", dpg.values[MESSAGE_DATA_TAG])

    def test_direct_launch_target_auto_subscribes_without_process_selection(self):
        dpg = FakeDpg()
        shell = RtiViewShell(
            initial_domain=5,
            initial_topic="Telemetry",
            initial_field="pose.position.x",
            initial_mode="plot",
            history_seconds=45,
            dpg_module=dpg,
        )
        shell._participant = object()
        registry.add_participant(DiscoveredParticipant(key="participant-1", name="TelemetryPublisher", ip="127.0.0.1"))
        endpoint = DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=FakeDynamicType("STRUCTURE_TYPE", "TelemetryType", (
                FakeMember("pose", FakeDynamicType("STRUCTURE_TYPE", members=(
                    FakeMember("position", FakeDynamicType("STRUCTURE_TYPE", members=(
                        FakeMember("x", FakeDynamicType("FLOAT_64_TYPE")),
                    ))),
                ))),
            )),
            kind="Writer",
        )
        registry.add_endpoint(endpoint)

        with patch("rti_view.views.main_window.refresh_endpoints"), \
             patch("rti_view.views.main_window.refresh_participants"), \
             patch("rti_view.views.main_window.setup_matched_reader", return_value=ReaderSetupResult(
                 reader=FakeReader(()),
                 subscriber=object(),
             )) as setup_reader:
            shell._update_discovery_view(dpg, force=True)

        setup_reader.assert_called_once_with(shell._participant, endpoint)
        self.assertIsNotNone(shell._subscription)
        self.assertEqual(shell.selection.topic_name, "Telemetry")
        self.assertEqual(shell.selection.field_path, "pose.position.x")
        self.assertEqual(shell.selection.mode, "plot")
        self.assertIn("-m plot", shell.selection.startup_command())

    def test_unselected_subscription_populates_fields_from_sample_items(self):
        dpg = FakeDpg()
        shell = RtiViewShell(initial_domain=0, dpg_module=dpg)
        shell._participant = object()
        endpoint = DiscoveredEndpoint(
            key="writer-a",
            participant_key="participant-1",
            topic_name="Telemetry",
            type_name="TelemetryType",
            dynamic_type=object(),
            kind="Writer",
        )
        shell._topic_endpoints = {"Telemetry": endpoint}
        shell._set_selection(dpg, shell.selection.__class__(domain_id=0, topic_name="Telemetry"))
        sample = FakeSample({"x": 12, "pose": FakeSample({"y": 8.5})})
        reader = FakeReader(((sample, FakeInfo(True)),))

        with patch("rti_view.views.main_window.setup_matched_reader", return_value=ReaderSetupResult(
                reader=reader,
                subscriber=object(),
        )):
            shell._subscribe_selected_field(dpg)
        shell._pump_subscription(dpg)

        self.assertEqual(shell._field_choices, ("x", "pose.y"))
        self.assertIn("pose.y", dpg.items[FIELD_LIST_TAG]["items"])
        self.assertIn("pose.y = 8.5", dpg.values[MESSAGE_DATA_TAG])


if __name__ == "__main__":
    unittest.main()
