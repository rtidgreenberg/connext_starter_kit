"""Unit tests for generated player-visible Debug Game artifacts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rti_debug_game.generator import generate
from rti_debug_game.levels import L01


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


if __name__ == "__main__":
    unittest.main()