"""Tests for metadata-only RTPS discovery topology parsing."""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import wire  # noqa: E402


def discovery_line(**values):
  """One tshark output row built from the shared discovery-column layout.

  Hand-writing a fixed column count here is what let the capture command and
  the parser disagree unnoticed, so rows are derived from the same layout the
  command is built from.
  """
  attributes = [attribute for _, attribute in wire.DISCOVERY_FIELDS]
  unknown = set(values) - set(attributes)
  if unknown:
    raise AssertionError(f"not discovery columns: {sorted(unknown)}")
  return "\t".join(str(values.get(attribute, "")) for attribute in attributes)


class TestDiscoveryLayout(unittest.TestCase):

  # Written out rather than derived from wire.DISCOVERY_FIELDS: every other
  # test here builds its rows from that layout, so only a literal pairing can
  # catch a field mapped to the wrong attribute. Update this deliberately when
  # the capture genuinely changes.
  EXPECTED = (
      ("rtps.guidPrefix.src", "guid_prefix"),
      ("rtps.vendorId", "vendor_id"),
      ("rtps.param.product_version.major", "product_version_major"),
      ("rtps.param.product_version.minor", "product_version_minor"),
      ("rtps.param.product_version.release", "product_version_release"),
      ("rtps.param.product_version.revision", "product_version_revision"),
      ("rtps.sm.wrEntityId", "writer_entity_id"),
      ("rtps.sm.rdEntityId", "reader_entity_id"),
      ("rtps.param.builtin_endpoint_set", "builtin_endpoint_set"),
      ("rtps.param.topicName", "topic_name"),
      ("rtps.param.typeName", "type_name"),
      ("rtps.reliability_kind", "reliability_kind"),
  )

  def test_layout_pairs_each_column_with_its_own_field(self):
    self.assertEqual(tuple(wire.DISCOVERY_FIELDS), self.EXPECTED)

  def test_column_names_are_unique(self):
    # tshark emits one column per -e argument even when a name repeats: the
    # earlier duplicate is blank and the value lands one slot to the right, so
    # a repeat shifts every field after it out of the parser's mapping.
    names = [field for field, _ in wire.DISCOVERY_FIELDS]
    self.assertEqual(len(names), len(set(names)))

  def test_layout_attributes_are_observation_fields(self):
    observation = wire.DiscoveryObservation()
    for _, attribute in wire.DISCOVERY_FIELDS:
      self.assertTrue(hasattr(observation, attribute), attribute)

  def test_capture_command_requests_exactly_the_parsed_columns(self):
    captured = {}

    def fake_run(command, **kwargs):
      captured["command"] = command
      return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    original_run = wire.subprocess.run
    wire.subprocess.run = fake_run
    try:
      wire.inspect_discovery_pcap(__file__, tshark_path="/usr/bin/tshark")
    finally:
      wire.subprocess.run = original_run

    command = captured["command"]
    requested = [command[index + 1] for index, item in enumerate(command)
                 if item == "-e"]
    self.assertEqual(requested, [field for field, _ in wire.DISCOVERY_FIELDS])


class TestDiscoveryParsing(unittest.TestCase):

  def test_fields_are_mapped_to_their_own_columns(self):
    observation = wire.parse_discovery_fields(discovery_line(
        guid_prefix="010f00000000000000000001", vendor_id="0x010f",
        product_version_major="3", product_version_minor="6",
        product_version_release="2", product_version_revision="0",
        writer_entity_id="0x000004c2", reader_entity_id="0x000004c7",
        builtin_endpoint_set="0x00000c3f", topic_name="Status",
        type_name="StatusType", reliability_kind="0x00000001"))
    self.assertEqual(observation.guid_prefix, "010f00000000000000000001")
    self.assertEqual(observation.vendor_id, "0x010f")
    self.assertEqual(observation.writer_entity_id, "0x000004c2")
    self.assertEqual(observation.reader_entity_id, "0x000004c7")
    self.assertEqual(observation.builtin_endpoint_set, "0x00000c3f")
    self.assertEqual(observation.topic_name, "Status")
    self.assertEqual(observation.type_name, "StatusType")
    self.assertEqual(observation.reliability_kind, "0x00000001")

  def test_short_rows_pad_rather_than_shift(self):
    observation = wire.parse_discovery_fields("010f0000\t0x010f")
    self.assertEqual(observation.guid_prefix, "010f0000")
    self.assertEqual(observation.vendor_id, "0x010f")
    self.assertEqual(observation.reliability_kind, "")

  def test_summary_deduplicates_participants_endpoints_and_topics(self):
    fastdds = dict(guid_prefix="010f00000000000000000001", vendor_id="0x010f",
                   product_version_major="3", product_version_minor="6",
                   product_version_release="2", product_version_revision="0",
                   writer_entity_id="0x000004c2", reader_entity_id="0x000004c7",
                   builtin_endpoint_set="0x00000c3f", topic_name="Status",
                   type_name="StatusType", reliability_kind="0x00000001")
    observations = [
        wire.parse_discovery_fields(discovery_line(**fastdds)),
        wire.parse_discovery_fields(discovery_line(**fastdds)),
        wire.parse_discovery_fields(discovery_line(
            guid_prefix="010f00000000000000000002", vendor_id="0x0101",
            product_version_major="7", product_version_minor="7",
            product_version_release="0", product_version_revision="0",
            writer_entity_id="0x000003c2", reader_entity_id="0x00000000",
            topic_name="Commands", type_name="CommandType")),
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
    # Only the Fast DDS vendor id (0x010f) contributes a product version.
    self.assertEqual(summary["fastdds_product_versions"], ["3.6.2.0"])
    self.assertFalse(summary["complete"])


if __name__ == "__main__":
  unittest.main()
