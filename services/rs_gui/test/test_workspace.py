#!/usr/bin/env python3
"""Pure unit tests for rs_gui workspace persistence."""

import json
import os
import shutil
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
TEST_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "test_output", "workspace")
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import (
    WORKSPACE_SCHEMA_VERSION,
    TopicSelection,
    TopicSelectionState,
    TopicSubscriptionRequest,
    WorkspaceDocument,
    WorkspaceFormatError,
    WorkspacePlotDefinition,
    WorkspacePlotSeries,
    load_workspace,
    migrate_workspace_dict,
    save_workspace,
)


class TestWorkspacePersistence(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)
        os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)

    def test_workspace_round_trips_to_json(self):
        document = self._workspace_document()

        loaded = WorkspaceDocument.from_json(document.to_json())

        self.assertEqual(loaded, document)
        self.assertEqual(loaded.version, WORKSPACE_SCHEMA_VERSION)
        self.assertEqual(loaded.topic_selections.selected_for(0, "Telemetry").plot_fields, ("pose.x",))
        self.assertEqual(loaded.plots[0].series[0].field_path, "pose.x")

    def test_workspace_saves_and_loads_from_file(self):
        path = os.path.join(TEST_OUTPUT_DIR, "workspace.json")
        document = self._workspace_document()

        save_workspace(document, path)
        loaded = load_workspace(path)

        self.assertEqual(loaded, document)
        with open(path, "r", encoding="utf-8") as workspace_file:
            raw = json.load(workspace_file)
        self.assertEqual(raw["version"], WORKSPACE_SCHEMA_VERSION)

    def test_v1_workspace_migrates_to_current_shape(self):
        v1_document = {
            "version": 1,
            "name": "Legacy",
            "domains": [0, "1"],
            "include_internal": True,
            "topics": [
                {
                    "domain_id": 0,
                    "topic_name": "Telemetry",
                    "type_name": "TelemetryType",
                    "selected_fields": ["pose.x", "pose.y"],
                    "plot_fields": ["pose.x"],
                },
            ],
            "xml_type_paths": ["types/Telemetry.xml"],
            "metadata": {"source": "legacy-test"},
        }

        migrated = WorkspaceDocument.from_dict(v1_document)

        self.assertEqual(migrated.version, WORKSPACE_SCHEMA_VERSION)
        self.assertEqual(migrated.domains, (0, 1))
        self.assertTrue(migrated.topic_selections.include_internal)
        self.assertEqual(
            migrated.topic_selections.selected_for(0, "Telemetry").selected_fields,
            ("pose.x", "pose.y"),
        )
        self.assertEqual(migrated.xml_type_paths, ("types/Telemetry.xml",))
        self.assertEqual(migrated.metadata["source"], "legacy-test")

    def test_unknown_future_fields_are_ignored(self):
        data = self._workspace_document().to_dict()
        data["future_top_level"] = {"ignored": True}
        data["topic_selections"]["future_nested"] = "ignored"
        data["plots"][0]["future_plot_field"] = "ignored"

        loaded = WorkspaceDocument.from_dict(data)

        self.assertFalse(hasattr(loaded, "future_top_level"))
        self.assertEqual(loaded.name, "Robot Workspace")
        self.assertEqual(loaded.plots[0].name, "Pose")

    def test_malformed_workspaces_raise_format_error(self):
        cases = (
            [],
            {"version": 99},
            {"version": WORKSPACE_SCHEMA_VERSION, "plots": [{"series": []}]},
            {
                "version": WORKSPACE_SCHEMA_VERSION,
                "plots": [{
                    "name": "Broken",
                    "series": [{"domain_id": 0, "topic_name": "Telemetry"}],
                }],
            },
            {
                "version": WORKSPACE_SCHEMA_VERSION,
                "plots": [{
                    "name": "Broken",
                    "series": [{
                        "domain_id": 0,
                        "topic_name": "Telemetry",
                        "field_path": "pose..x",
                    }],
                }],
            },
        )

        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(WorkspaceFormatError):
                    WorkspaceDocument.from_dict(data)

    def test_json_output_contains_only_serializable_declarative_state(self):
        document = self._workspace_document()

        payload = json.loads(document.to_json())

        self.assertIn("topic_selections", payload)
        self.assertIn("subscriptions", payload)
        self.assertIn("plots", payload)
        self.assertNotIn("participant", payload)
        self.assertNotIn("reader", payload)
        self.assertNotIn("dynamic_data", payload)

    def test_migrate_workspace_dict_reports_current_version(self):
        migrated = migrate_workspace_dict({"version": 1, "domains": [7]})

        self.assertEqual(migrated["version"], WORKSPACE_SCHEMA_VERSION)
        self.assertEqual(migrated["domains"], [7])
        self.assertEqual(migrated["topic_selections"], {
            "include_internal": False,
            "selections": [],
        })

    def _workspace_document(self):
        selection = TopicSelection(
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            selected_fields=("pose.x", "pose.y", "label"),
            plot_fields=("pose.x",),
            created_at=10.0,
            updated_at=11.0,
        )
        subscription = TopicSubscriptionRequest(
            domain_id=0,
            topic_name="Telemetry",
            type_name="TelemetryType",
            selected_fields=("pose.x", "pose.y"),
            max_samples=128,
            created_at=12.0,
        )
        plot = WorkspacePlotDefinition(
            name="Pose",
            series=(WorkspacePlotSeries(
                domain_id=0,
                topic_name="Telemetry",
                type_name="TelemetryType",
                field_path="pose.x",
                label="X position",
                style={"color": "blue"},
            ),),
            history_seconds=30.0,
            max_points=500,
            created_at=13.0,
            updated_at=14.0,
        )
        return WorkspaceDocument(
            name="Robot Workspace",
            domains=(0, 1),
            topic_selections=TopicSelectionState(selections={selection.key: selection}),
            subscriptions=(subscription,),
            plots=(plot,),
            xml_type_paths=("xml_types/Telemetry.xml",),
            recent_files=("recordings/session_001",),
            metadata={"operator": "test"},
        )


if __name__ == "__main__":
    unittest.main()