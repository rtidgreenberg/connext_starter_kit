#!/usr/bin/env python3
"""Headless tests for rs_gui_v2 Topics-tab view models and rendering."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    AppState,
    DiscoveredTopic,
    FieldCatalog,
    FieldDescriptor,
    LifecyclePhase,
    SampleEnvelope,
    SubscriptionStatus,
    TopicDiscoveryState,
    TopicSelection,
    TopicSelectionState,
    TopicSubscriptionRequest,
    TopicSubscriptionState,
    TypeAvailabilityStatus,
    TypeResolution,
)
from gui import (
    build_mock_topics_tab_view_model,
    build_shell_view_model,
    build_topic_action_command,
    build_topic_field_command,
    build_topic_select_command,
    build_topics_tab_view_model,
)
from gui.main_window import DearPyGuiShell, _render_topics_tab
from gui.tabs.record_tab import build_mock_record_tab_view_model


from fakes import FakeDpg


class TestTopicsTabViewModel(unittest.TestCase):
    def test_mock_topics_snapshot_contains_discovery_fields_and_samples(self):
        topics = build_mock_topics_tab_view_model(now=120.0)

        self.assertEqual(topics.selected_topic.topic_name, "RobotTelemetry")
        self.assertEqual([row.topic_name for row in topics.rows], ["CameraStatus", "RobotTelemetry"])
        self.assertEqual(topics.selected_topic.subscription_status, SubscriptionStatus.RECEIVING.value)
        self.assertEqual(topics.selected_topic.sample_count, 42)
        self.assertTrue(topics.action_by_id["unsubscribe"].enabled)
        self.assertFalse(topics.action_by_id["subscribe"].enabled)
        self.assertIn("1 internal topic(s) hidden", topics.diagnostics)
        field_by_path = {field.path: field for field in topics.fields}
        self.assertTrue(field_by_path["velocity"].plot_selected)
        self.assertTrue(field_by_path["velocity"].plottable)
        sample_by_path = {row.path: row.value for row in topics.sample_rows}
        self.assertEqual(sample_by_path["pose.x"], "12.5")
        self.assertEqual(sample_by_path["mode"], "AUTO")

    def test_filtering_and_internal_toggle_preserve_selected_topic_when_visible(self):
        topics = build_topics_tab_view_model(
            topics=_fixture_topics(),
            selections=TopicSelectionState(include_internal=True).select(TopicSelection(
                domain_id=4,
                topic_name="rti/service/monitoring/periodic",
                type_name="RTI::Service::Monitoring::Periodic",
            )),
            include_internal=True,
            selected_topic_key="4:rti/service/monitoring/periodic",
            search_text="monitoring",
        )

        self.assertEqual([row.topic_name for row in topics.rows], ["rti/service/monitoring/periodic"])
        self.assertEqual(topics.selected_topic_key, "4:rti/service/monitoring/periodic")
        self.assertTrue(topics.selected_topic.internal)
        self.assertTrue(topics.action_by_id["subscribe"].enabled)

    def test_unresolved_type_disables_subscribe_and_reports_diagnostic(self):
        topics = build_topics_tab_view_model(
            topics=_fixture_topics(),
            selected_topic_key="4:CameraStatus",
        )

        self.assertEqual(topics.selected_topic.topic_name, "CameraStatus")
        self.assertFalse(topics.action_by_id["subscribe"].enabled)
        self.assertIn("type is not available", topics.action_by_id["subscribe"].reason)
        self.assertTrue(any("type is not available" in item for item in topics.diagnostics))

    def test_field_catalog_and_samples_follow_selected_topic(self):
        request = TopicSubscriptionRequest(4, "RobotTelemetry", "Robot::Telemetry")
        state = TopicSubscriptionState(
            request=request,
            status=SubscriptionStatus.MATCHED,
            received_samples=3,
        )
        sample = SampleEnvelope(
            subscription_key=request.key,
            domain_id=4,
            topic_name="RobotTelemetry",
            type_name="Robot::Telemetry",
            data={"pose": {"x": 8.0}, "status": "OK"},
        )
        topics = build_topics_tab_view_model(
            topics=_fixture_topics(),
            selections=TopicSelectionState().select(TopicSelection(
                domain_id=4,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                selected_fields=("pose.x",),
            )),
            field_catalogs={"Robot::Telemetry": FieldCatalog(
                type_name="Robot::Telemetry",
                fields=(FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),),
            )},
            subscription_states=(state,),
            samples=(sample,),
            selected_topic_key="4:RobotTelemetry",
        )

        self.assertEqual(topics.selected_topic.subscription_status, SubscriptionStatus.MATCHED.value)
        self.assertEqual(topics.fields[0].path, "pose.x")
        self.assertTrue(topics.fields[0].selected)
        self.assertEqual(topics.sample_rows[0].path, "pose.x")
        self.assertEqual(topics.sample_rows[0].value, "8")

    def test_topic_command_builders_preserve_selected_context(self):
        topics = build_mock_topics_tab_view_model(now=120.0)
        field_by_path = {field.path: field for field in topics.fields}

        unsubscribe = build_topic_action_command("unsubscribe", topics)
        select_camera = build_topic_select_command(topics.rows[0])
        clear_plot = build_topic_field_command(field_by_path["velocity"], topics, plot=True, selected=False)
        search = build_topic_action_command("set_search", topics, value="camera")

        self.assertEqual(unsubscribe.command_type, "topics.unsubscribe")
        self.assertEqual(unsubscribe.payload["topic_name"], "RobotTelemetry")
        self.assertEqual(unsubscribe.payload["selected_fields"], ("pose.x", "pose.y", "velocity"))
        self.assertEqual(select_camera.command_type, "topics.select")
        self.assertEqual(select_camera.payload["topic_key"], topics.rows[0].topic_key)
        self.assertEqual(clear_plot.command_type, "topics.set_plot_field_selected")
        self.assertEqual(clear_plot.payload["field_path"], "velocity")
        self.assertFalse(clear_plot.payload["selected"])
        self.assertEqual(search.command_type, "topics.set_search")
        self.assertEqual(search.payload["search_text"], "camera")


class TestTopicsShellRendering(unittest.TestCase):
    def test_shell_renders_topics_tab_snapshot(self):
        topics = build_mock_topics_tab_view_model()
        fake = FakeDpg()

        _render_topics_tab(fake, topics, command_sink=None)

        text_values = [args[0] for name, args, _kwargs in fake.calls if name == "add_text" and args]
        self.assertIn("RobotTelemetry", text_values)
        self.assertIn("Field Picker", text_values)
        self.assertIn("Sample Inspector", text_values)

    def test_topics_buttons_emit_commands_when_command_sink_is_present(self):
        commands = []
        topics = build_mock_topics_tab_view_model()
        fake = FakeDpg()

        _render_topics_tab(fake, topics, command_sink=lambda cmd: commands.append(cmd) or True)

        unsubscribe = next(
            kwargs["callback"] for name, args, kwargs in fake.calls
            if name == "add_button" and (kwargs.get("label") == "Unsubscribe" or (args and args[0] == "Unsubscribe"))
        )
        star_callbacks = tuple(
            kwargs["callback"] for name, args, kwargs in fake.calls
            if name == "add_button" and (kwargs.get("label") == "*" or (args and args[0] == "*"))
        )

        self.assertTrue(unsubscribe())
        for callback in star_callbacks:
            self.assertTrue(callback())

        self.assertEqual(commands[0].command_type, "topics.unsubscribe")
        self.assertTrue(any(command.command_type.startswith("topics.") for command in commands[1:]))


def _fixture_topics():
    available = TypeResolution(
        type_name="Robot::Telemetry",
        status=TypeAvailabilityStatus.AVAILABLE,
        candidates=("Robot::Telemetry",),
    )
    monitoring = TypeResolution(
        type_name="RTI::Service::Monitoring::Periodic",
        status=TypeAvailabilityStatus.AVAILABLE,
        candidates=("RTI::Service::Monitoring::Periodic",),
    )
    missing = TypeResolution(
        type_name="Camera::Status",
        status=TypeAvailabilityStatus.MISSING,
        message="type is not available in the local catalog",
    )
    return (
        DiscoveredTopic(
            4,
            "RobotTelemetry",
            ("Robot::Telemetry",),
            writer_count=1,
            reader_count=1,
            state=TopicDiscoveryState.TYPE_AVAILABLE,
            type_resolution=available,
            partitions=("/robot",),
        ),
        DiscoveredTopic(
            4,
            "CameraStatus",
            ("Camera::Status",),
            writer_count=1,
            reader_count=0,
            state=TopicDiscoveryState.UNRESOLVED,
            type_resolution=missing,
        ),
        DiscoveredTopic(
            4,
            "rti/service/monitoring/periodic",
            ("RTI::Service::Monitoring::Periodic",),
            writer_count=1,
            reader_count=0,
            internal=True,
            state=TopicDiscoveryState.INTERNAL,
            type_resolution=monitoring,
        ),
    )


if __name__ == "__main__":
    unittest.main()
