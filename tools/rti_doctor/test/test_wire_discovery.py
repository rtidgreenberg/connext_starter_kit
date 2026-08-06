"""Tests for metadata-only RTPS discovery topology parsing."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import wire  # noqa: E402


class TestDiscoveryParsing(unittest.TestCase):

  def test_summary_deduplicates_participants_endpoints_and_topics(self):
    observations = [
        wire.parse_discovery_fields(
            "010f00000000000000000001\t0x000004c2\t0x000004c7\t"
            "0x00000c3f\tStatus\tStatusType\t0x00000001"),
        wire.parse_discovery_fields(
            "010f00000000000000000001\t0x000004c2\t0x000004c7\t"
            "0x00000c3f\tStatus\tStatusType\t0x00000001"),
        wire.parse_discovery_fields(
            "010f00000000000000000002\t0x000003c2\t0x00000000\t"
            "\tCommands\tCommandType\t"),
    ]
    summary = wire.summarize_discovery(observations, "sample.pcapng")
    # `source` is the capture, matching inspect_pcap and what the renderers
    # read; the label lives in `kind`.
    self.assertEqual(summary["kind"], "tshark RTPS discovery")
    self.assertEqual(summary["source"], "sample.pcapng")
    self.assertEqual(summary["participants"], 2)
    self.assertEqual(summary["endpoint_observations"], 2)
    self.assertEqual(summary["topics"], ["Commands", "Status"])
    self.assertEqual(summary["builtin_endpoint_sets"], ["0x00000c3f"])
    self.assertFalse(summary["complete"])


if __name__ == "__main__":
  unittest.main()