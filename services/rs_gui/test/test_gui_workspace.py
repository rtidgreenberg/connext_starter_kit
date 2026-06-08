#!/usr/bin/env python3
"""Headless tests for rs_gui_v2 GUI workspace persistence wiring."""

import os
import shutil
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
TEST_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "test_output", "gui_workspace")
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    AppCommand,
    FieldCatalog,
    FieldDescriptor,
    PlotBufferSnapshot,
    PlotSamplePoint,
    PlotSeriesSnapshot,
    SubscriptionStatus,
    TopicDiscoveryFacade,
    WorkspaceDocument,
    load_workspace,
)
from gui import (
    GuiWorkspaceController,
    PlotsTabController,
    PlotsTabControllerConfig,
    TopicsTabController,
    TopicsTabControllerConfig,
    build_gui_shell_assembly,
)
from test_gui_topics_controller import _fake_discovery_client


class TestGuiWorkspaceController(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)
        os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)

    async def test_build_document_projects_topics_and_plots_intent(self):
        topics = _topics_controller()
        plots = _plots_controller()
        await _seed_topic_intent(topics)
        await plots.refresh_view()
        controller = GuiWorkspaceController(topics_controller=topics, plots_controller=plots, clock=lambda: 77.0)

        document = controller.build_document(
            workspace_name="Robot Workspace",
            path=os.path.join(TEST_OUTPUT_DIR, "robot.json"),
        )

        self.assertEqual(document.name, "Robot Workspace")
        self.assertEqual(document.domains, (7,))
        self.assertTrue(document.topic_selections.include_internal)
        selection = document.topic_selections.selected_for(7, "RobotTelemetry")
        self.assertEqual(selection.selected_fields, ("pose.x",))
        self.assertEqual(selection.plot_fields, ("velocity",))
        self.assertEqual(document.subscriptions[0].topic_name, "RobotTelemetry")
        self.assertEqual(document.plots[0].name, "Robot Motion")
        self.assertEqual(document.plots[0].series[0].field_path, "velocity")
        self.assertEqual(document.metadata["gui"]["topics"]["search_text"], "robot")
        self.assertEqual(document.metadata["gui"]["plots"]["selected_plot_name"], "Robot Motion")
        self.assertNotIn("reader", document.to_json())

    async def test_save_and_load_restore_gui_intent(self):
        path = os.path.join(TEST_OUTPUT_DIR, "restore.json")
        source_topics = _topics_controller()
        source_plots = _plots_controller()
        await _seed_topic_intent(source_topics)
        await source_plots.refresh_view()
        source = GuiWorkspaceController(source_topics, source_plots, clock=lambda: 88.0)
        saved = source.save(path, workspace_name="Restored Workspace")

        target_topics = _topics_controller()
        target_plots = PlotsTabController(config=PlotsTabControllerConfig())
        target = GuiWorkspaceController(target_topics, target_plots)
        loaded = target.load(path)
        topics_view = await target_topics.refresh_view()
        plots_view = await target_plots.refresh_view()

        self.assertEqual(loaded, saved)
        self.assertEqual(topics_view.search_text, "robot")
        self.assertTrue(topics_view.include_internal)
        self.assertEqual(topics_view.selected_topic.topic_name, "RobotTelemetry")
        self.assertEqual(topics_view.selected_topic.subscription_status, SubscriptionStatus.READER_CREATED.value)
        fields = {field.path: field for field in topics_view.fields}
        self.assertTrue(fields["pose.x"].selected)
        self.assertTrue(fields["velocity"].plot_selected)
        self.assertEqual(plots_view.selected_plot_name, "Robot Motion")
        self.assertEqual(plots_view.series[0].field_path, "velocity")
        self.assertEqual(plots_view.total_point_count, 0)

    async def test_workspace_commands_route_through_default_session(self):
        path = os.path.join(TEST_OUTPUT_DIR, "session.json")
        assembly = build_gui_shell_assembly()
        assembly.session.command_sink(AppCommand(
            command_type="workspace.save",
            payload={"path": path, "workspace_name": "Session Workspace"},
            command_id="save-workspace",
            created_at=1.0,
        ))

        saved_view = await assembly.session.next_view_async()
        saved = load_workspace(path)

        self.assertTrue(os.path.isfile(path))
        self.assertEqual(saved.name, "Session Workspace")
        self.assertFalse(saved_view.title.endswith("*"))
        self.assertTrue(any(entry.message == "Dispatched workspace.save" for entry in saved_view.event_log))

        saved_dict = saved.to_dict()
        saved_dict["name"] = "Loaded Workspace"
        WorkspaceDocument.from_dict(saved_dict).to_json()
        with open(path, "w", encoding="utf-8") as workspace_file:
            workspace_file.write(WorkspaceDocument.from_dict(saved_dict).to_json())

        assembly.session.command_sink(AppCommand(
            command_type="workspace.load",
            payload={"path": path},
            command_id="load-workspace",
            created_at=2.0,
        ))
        loaded_view = await assembly.session.next_view_async()

        self.assertIn("Loaded Workspace", loaded_view.title)
        self.assertTrue(any(entry.message == "Dispatched workspace.load" for entry in loaded_view.event_log))

    async def test_missing_workspace_path_is_reported_as_command_failure(self):
        assembly = build_gui_shell_assembly()
        assembly.session.command_sink(AppCommand(
            command_type="workspace.save",
            command_id="save-without-path",
            created_at=3.0,
        ))

        view = await assembly.session.next_view_async()

        self.assertTrue(any(entry.level == "error" for entry in view.event_log))
        self.assertTrue(any("workspace.save requires a path" in entry.message for entry in view.event_log))


def _topics_controller():
    return TopicsTabController(
        discovery_facade=TopicDiscoveryFacade(_fake_discovery_client()),
        field_catalogs={"Robot::Telemetry": FieldCatalog(
            type_name="Robot::Telemetry",
            fields=(
                FieldDescriptor("pose.x", "x", "float64", scalar_kind="float"),
                FieldDescriptor("velocity", "velocity", "float32", scalar_kind="float"),
            ),
        )},
        config=TopicsTabControllerConfig(domain_id=7, selected_topic_key="7:RobotTelemetry"),
        clock=lambda: 50.0,
    )


def _plots_controller():
    return PlotsTabController(
        plot_snapshots=(PlotBufferSnapshot(
            name="Robot Motion",
            history_seconds=30.0,
            max_points=512,
            series=(PlotSeriesSnapshot(
                series_key="7:RobotTelemetry:velocity",
                label="Velocity",
                domain_id=7,
                topic_name="RobotTelemetry",
                type_name="Robot::Telemetry",
                field_path="velocity",
                points=(PlotSamplePoint(timestamp=1.0, value=1.5),),
            ),),
        ),),
        config=PlotsTabControllerConfig(selected_plot_name="Robot Motion"),
        clock=lambda: 60.0,
    )


async def _seed_topic_intent(topics):
    await topics.handle_command(AppCommand("topics.set_search", payload={"search_text": "robot"}))
    await topics.handle_command(AppCommand("topics.set_include_internal", payload={"include_internal": True}))
    await topics.handle_command(AppCommand(
        "topics.set_field_selected",
        payload={
            "domain_id": 7,
            "topic_name": "RobotTelemetry",
            "type_name": "Robot::Telemetry",
            "field_path": "pose.x",
            "selected": True,
        },
    ))
    await topics.handle_command(AppCommand(
        "topics.set_plot_field_selected",
        payload={
            "domain_id": 7,
            "topic_name": "RobotTelemetry",
            "type_name": "Robot::Telemetry",
            "field_path": "velocity",
            "selected": True,
        },
    ))
    await topics.handle_command(AppCommand(
        "topics.subscribe",
        payload={
            "domain_id": 7,
            "topic_name": "RobotTelemetry",
            "type_name": "Robot::Telemetry",
            "selected_fields": ("pose.x",),
        },
    ))
    await topics.refresh_view()


if __name__ == "__main__":
    unittest.main()
