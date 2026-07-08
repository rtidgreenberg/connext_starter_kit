#!/usr/bin/env python3
"""Startup command config tests for rti_view."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import tempfile

from rti_view.config import ViewConfig, load_config


class TestConfig(unittest.TestCase):
    def test_startup_string_for_plot(self):
        config = ViewConfig(domain_id=5, topic_name="SensorData", field_path="position.x", mode="plot", history_seconds=60)

        self.assertEqual(
            config.to_startup_string(),
            "./run_rti_view.sh -d 5 -t SensorData -f position.x -m plot --history 60 --direct-view",
        )

    def test_startup_string_round_trip(self):
        config = ViewConfig.from_startup_string("./run_rti_view.sh -d 5 -t SensorData -f position.x -m plot --history 60 --direct-view")

        self.assertEqual(config.domain_id, 5)
        self.assertEqual(config.topic_name, "SensorData")
        self.assertEqual(config.field_path, "position.x")
        self.assertEqual(config.mode, "plot")
        self.assertEqual(config.history_seconds, 60)
        self.assertTrue(config.direct_view)

    def test_legacy_startup_string_defaults_direct_view_for_field_shortcuts(self):
        config = ViewConfig.from_startup_string("./run_rti_view.sh -d 5 -t SensorData -f position.x -m plot --history 60")

        self.assertTrue(config.direct_view)


    def test_malformed_startup_string_raises_value_error(self):
        for bad in (
            "./run_rti_view.sh --bogus-flag",
            "./run_rti_view.sh -d not_a_number",
            "./run_rti_view.sh -m invalid_mode",
            "./run_rti_view.sh -t 'unbalanced quote",
        ):
            with self.assertRaises(ValueError, msg=bad):
                ViewConfig.from_startup_string(bad)

    def test_load_config_returns_none_for_corrupt_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
            f.write("./run_rti_view.sh --bogus-flag\n")
            path = f.name
        try:
            self.assertIsNone(load_config(path))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
