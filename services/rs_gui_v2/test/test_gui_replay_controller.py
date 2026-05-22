#!/usr/bin/env python3
"""Headless tests for rs_gui_v2 Replay tab controller wiring."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand
from gui.tabs import ReplayTabController, ReplayTabControllerConfig, ReplayTargetRow


class TestReplayTabController(unittest.IsolatedAsyncioTestCase):
    async def test_mock_controller_refreshes_seeded_replay_view(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        view = await controller.refresh_view()

        self.assertEqual(view.selected_target.control_name, "replay_service_2d91c4a0")
        self.assertTrue(view.action_by_id["start"].enabled)
        self.assertFalse(view.action_by_id["pause"].enabled)

    async def test_start_pause_resume_and_stop_update_replay_state(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        start = controller.handle_command(AppCommand(
            command_type="replay.start",
            payload={
                "target_id": "launch-replay-main",
                "database_path": "services/replay_input/robot_run_03",
                "playback_rate": 2.0,
                "loop": True,
                "time_window": "00:00:00 - 00:01:00",
            },
            command_id="start-replay",
            created_at=1.0,
        ))
        running_view = await controller.refresh_view()

        self.assertTrue(start.ok)
        self.assertEqual(start.payload["state"], "RUNNING")
        self.assertEqual(running_view.observed_state, "RUNNING")
        self.assertEqual(running_view.playback_rate, 2.0)
        self.assertTrue(running_view.loop)
        self.assertTrue(running_view.action_by_id["pause"].enabled)

        pause = controller.handle_command(AppCommand("replay.pause", command_id="pause-replay", created_at=2.0))
        paused_view = await controller.refresh_view()
        resume = controller.handle_command(AppCommand("replay.resume", command_id="resume-replay", created_at=3.0))
        resumed_view = await controller.refresh_view()
        stop = controller.handle_command(AppCommand("replay.stop", command_id="stop-replay", created_at=4.0))
        stopped_view = await controller.refresh_view()

        self.assertEqual(pause.payload["state"], "PAUSED")
        self.assertTrue(paused_view.action_by_id["resume"].enabled)
        self.assertEqual(resume.payload["state"], "RUNNING")
        self.assertEqual(resumed_view.observed_state, "RUNNING")
        self.assertEqual(stop.payload["state"], "STOPPED")
        self.assertEqual(stopped_view.observed_state, "STOPPED")

    async def test_select_target_updates_selected_row(self):
        controller = ReplayTabController.mock(clock=lambda: 10.0)

        result = controller.handle_command(AppCommand(
            command_type="replay.select_target",
            payload={"target_id": "discovery:replay:archive"},
            command_id="select-replay",
            created_at=5.0,
        ))
        view = await controller.refresh_view()

        self.assertTrue(result.ok)
        self.assertEqual(view.selected_target_id, "discovery:replay:archive")
        self.assertEqual(view.selected_target.control_name, "replay_archive_external")
        selected = {row.control_name: row.selected for row in view.targets}
        self.assertFalse(selected["replay_service_2d91c4a0"])
        self.assertTrue(selected["replay_archive_external"])

    async def test_start_without_database_reports_validation_error(self):
        controller = ReplayTabController(
            targets=(ReplayTargetRow(
                target_id="target",
                label="Replay",
                control_name="replay_service_empty",
                source="local",
                hostname="dev-host",
                state="STOPPED",
                progress="0%",
            ),),
            config=ReplayTabControllerConfig(selected_target_id="target"),
        )

        with self.assertRaisesRegex(ValueError, "recording database path"):
            controller.handle_command(AppCommand("replay.start"))


if __name__ == "__main__":
    unittest.main()
