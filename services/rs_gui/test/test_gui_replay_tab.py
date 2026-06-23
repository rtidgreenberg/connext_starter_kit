#!/usr/bin/env python3
"""Headless tests for rs_gui Replay tab view models."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from gui.tabs.replay_tab import (
    ReplayTargetRow,
    ReplayTimelineRow,
    build_mock_replay_tab_view_model,
    build_replay_action_command,
    build_replay_next_tag_command,
    build_replay_tab_view_model,
)


class TestReplayTabViewModel(unittest.TestCase):
    def test_mock_replay_tab_contains_targets_timeline_and_actions(self):
        view = build_mock_replay_tab_view_model()

        self.assertEqual(view.selected_target_id, "launch-replay-main")
        self.assertEqual(view.selected_target.control_name, "replay_service_2d91c4a0")
        self.assertEqual(view.database_path, "services/replay_input/robot_run_03")
        self.assertEqual(view.qos_file_path, "dds/qos/DDS_QOS_PROFILES.xml")
        self.assertEqual(view.participant_qos_profile, "DPLibrary::DefaultParticipant")
        self.assertEqual(view.writer_qos_profile, "DataPatternsLibrary::replay_writer_transient_local")
        self.assertEqual(view.observed_state, "stopped")
        self.assertEqual(view.target_count, 2)
        self.assertEqual(view.timeline[0].label, "Robot run")
        self.assertTrue(view.action_by_id["start"].enabled)
        self.assertFalse(view.action_by_id["pause"].enabled)
        self.assertEqual(view.action_by_id["pause"].reason, "not running")
        self.assertEqual(view.diagnostics, ())

    def test_empty_replay_tab_reports_missing_service_and_database(self):
        view = build_replay_tab_view_model()

        self.assertEqual(view.target_count, 0)
        self.assertFalse(view.action_by_id["start"].enabled)
        self.assertFalse(view.action_by_id["shutdown"].enabled)
        self.assertIn("No Replay Service candidates discovered", view.diagnostics)
        self.assertIn("No recording database selected", view.diagnostics)

    def test_paused_replay_enables_resume_and_stop(self):
        target = ReplayTargetRow(
            target_id="replay-paused",
            label="Replay",
            control_name="replay_service_paused",
            source="local",
            hostname="dev-host",
            state="PAUSED",
            progress="44%",
            selected=True,
        )

        view = build_replay_tab_view_model(
            targets=(target,),
            selected_target_id="replay-paused",
            database_path="services/replay_input/demo",
            timeline=(ReplayTimelineRow("Window", "1.0", "5.0"),),
        )

        self.assertFalse(view.action_by_id["pause"].enabled)
        self.assertTrue(view.action_by_id["resume"].enabled)
        self.assertTrue(view.action_by_id["stop"].enabled)

    def test_duplicate_target_disables_admin_actions(self):
        target = ReplayTargetRow(
            target_id="duplicate",
            label="Replay",
            control_name="replay_service_duplicate",
            source="discovery",
            hostname="lab-host",
            state="RUNNING",
            progress="12%",
            selected=True,
            conflict=True,
        )

        view = build_replay_tab_view_model(
            targets=(target,),
            selected_target_id="duplicate",
            database_path="services/replay_input/demo",
        )

        self.assertFalse(view.action_by_id["start"].enabled)
        self.assertFalse(view.action_by_id["pause"].enabled)
        self.assertFalse(view.action_by_id["shutdown"].enabled)
        self.assertIn("Duplicate Replay Service target detected", view.diagnostics)

    def test_replay_action_command_preserves_target_and_playback_intent(self):
        view = build_mock_replay_tab_view_model()

        command = build_replay_action_command("start", view)

        self.assertEqual(command.command_type, "replay.start")
        self.assertEqual(command.target, "replay_service_2d91c4a0")
        self.assertEqual(command.payload["target_id"], "launch-replay-main")
        self.assertEqual(
            command.payload["database_path"],
            "services/replay_input/robot_run_03",
        )
        self.assertEqual(command.payload["playback_rate"], 1.0)
        self.assertFalse(command.payload["loop"])
        self.assertEqual(command.payload["time_window"], "00:00:10 - 00:02:30")
        self.assertEqual(command.payload["qos_file_path"], "dds/qos/DDS_QOS_PROFILES.xml")
        self.assertEqual(
            command.payload["participant_qos_profile"],
            "DPLibrary::DefaultParticipant",
        )
        self.assertEqual(
            command.payload["writer_qos_profile"],
            "DataPatternsLibrary::replay_writer_transient_local",
        )
        with self.assertRaises(ValueError):
            build_replay_action_command("rewind", view)

    def test_replay_next_tag_command_preserves_target_and_tag_name(self):
        view = build_mock_replay_tab_view_model()

        command = build_replay_next_tag_command(view, "e2e_tag_beta")

        self.assertEqual(command.command_type, "replay.next_tag")
        self.assertEqual(command.target, "replay_service_2d91c4a0")
        self.assertEqual(command.payload["target_id"], "launch-replay-main")
        self.assertEqual(command.payload["tag_name"], "e2e_tag_beta")
        self.assertEqual(
            command.payload["database_path"],
            "services/replay_input/robot_run_03",
        )
        with self.assertRaises(ValueError):
            build_replay_next_tag_command(view, "  ")


if __name__ == "__main__":
    unittest.main()
