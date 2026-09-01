"""Unit tests for generated player-visible Debug Game artifacts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rti_debug_game.generator import generate
from rti_debug_game.levels import L01, L02, L03
from rti_debug_game.app import DebugGameApp
from rti_debug_game.control import ParticipantState, summarize


class GeneratorTests(unittest.TestCase):
    def test_generates_editable_scripts_and_preserves_edits_without_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with patch("rti_debug_game.generator.run_root", return_value=root):
                generate(L01)
                script = root / "participant_aster_vehicle_supervisor.py"
                original = script.read_text(encoding="ascii")
                self.assertIn("class ParticipantQos", original)
                self.assertIn("class EndpointQos", original)
                self.assertIn("class DataModel", original)
                script.write_text("# player edit\n", encoding="ascii")
                generate(L01)
                self.assertEqual("# player edit\n", script.read_text(encoding="ascii"))
                generate(L01, reset=True)
                self.assertEqual(original, script.read_text(encoding="ascii"))

    def test_generates_l02_partition_fault_with_topic_specific_factories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with patch("rti_debug_game.generator.run_root", return_value=root):
                generate(L02, reset=True)
            writer = (root / "participant_aegis_safety_monitor.py").read_text(encoding="ascii")
            reader = (root / "participant_harbor_telemetry_gateway.py").read_text(encoding="ascii")
            self.assertIn("def safety_status_writer", writer)
            self.assertIn("qos.partition.name = ['alerts']", writer)
            self.assertIn("def safety_status_reader", reader)
            self.assertIn("qos.partition.name = ['telemetry']", reader)

    def test_switching_levels_replaces_the_generated_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with patch("rti_debug_game.generator.run_root", return_value=root):
                generate(L01)
                generate(L02)
            self.assertFalse((root / "participant_aster_vehicle_supervisor.py").exists())
            self.assertTrue((root / "participant_aegis_safety_monitor.py").exists())
            expected = (root / "expected.json").read_text(encoding="ascii")
            self.assertIn('"level": "L02"', expected)

    def test_generates_l03_wrong_writer_topic_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            with patch("rti_debug_game.generator.run_root", return_value=root):
                generate(L03, reset=True)
            writer = (root / "participant_navi_route_planner.py").read_text(encoding="ascii")
            reader = (root / "participant_helios_motion_controller.py").read_text(encoding="ascii")
            self.assertIn("TOPIC_NAME = 'VehicleCommandOutbound'", writer)
            self.assertIn("TOPIC_NAME = 'VehicleCommand'", reader)

    def test_app_briefing_uses_the_selected_level(self):
        mission = DebugGameApp("L03")._mission_text()
        self.assertIn("L03: Guidance channel has the wrong identity", mission)
        self.assertIn("navi_route_planner", mission)

    def test_control_summary_keeps_the_latest_state_for_each_process(self):
        summary = summarize((
            ParticipantState("writer", "run-1", "created"),
            ParticipantState("reader", "run-1", "created"),
            ParticipantState("writer", "run-1", "matched", matched_count=1),
            ParticipantState("reader", "run-1", "passed", received_count=10),
        ))
        self.assertEqual("matched", summary["writer"]["lifecycle"])
        self.assertEqual(1, summary["writer"]["matched_count"])
        self.assertEqual("passed", summary["reader"]["lifecycle"])
        self.assertEqual(10, summary["reader"]["received_count"])


if __name__ == "__main__":
    unittest.main()