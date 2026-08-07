"""Unit tests for tshark RTPS field parsing."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import wire  # noqa: E402
from rti_doctor import report  # noqa: E402


class TestTsharkFields(unittest.TestCase):

  class Locator:
    def __init__(self, address, port, kind=1):
      self.address = [0] * 12 + [int(part) for part in address.split(".")]
      self.port = port
      self.kind = kind

  class Endpoint:
    def __init__(self, locators):
      self.unicast_locators = locators

  class Ports:
    port_base = 7400
    domain_id_gain = 250

  class Qos:
    def __init__(self):
      self.wire_protocol = type("WireProtocol", (), {
          "rtps_well_known_ports": TestTsharkFields.Ports()})()

  def test_parses_data_with_encapsulation(self):
    item = wire.parse_tshark_fields(
        "1722780000.1\t0x15\t000001c2\t01010a0b0c0d0e0f10111213\t42\t0x0007\t00:07:00:00:aa:bb\t")
    self.assertEqual(item.submessage_id, "0x15")
    self.assertEqual(item.writer_entity_id, "000001c2")
    self.assertEqual(item.writer_guid_prefix, "01010a0b0c0d0e0f10111213")
    self.assertEqual(item.sequence_number, "42")
    self.assertEqual(item.encapsulation_id, "0x0007")
    self.assertEqual(item.payload_bytes, 6)
    self.assertEqual(item.reassembled_bytes, 0)

  def test_summarizes_multiple_observations(self):
    observations = [
      wire.parse_tshark_fields("1\t0x15\twriter-a\t\t1\t0x0007\t00:01\t"),
      wire.parse_tshark_fields("2\t0x15\twriter-a\t\t2\t0x0007\t00:01:02\t"),
      wire.parse_tshark_fields("3\t0x16\twriter-b\t\t3\t\t\t00:02:03:04"),
    ]
    summary = wire.summarize(observations)
    self.assertEqual(summary["packets"], 3)
    self.assertEqual(summary["data_packets"], 2)
    self.assertEqual(summary["data_fragments"], 1)
    self.assertEqual(summary["encapsulation_ids"], ["0x0007"])
    self.assertEqual(summary["writer_entity_ids"], ["writer-a", "writer-b"])
    self.assertEqual(summary["payload_bytes"], 5)
    self.assertEqual(summary["reassembled_bytes"], 4)

  def test_decodes_xcdr_encapsulation_ids(self):
    self.assertEqual(
        wire.encapsulation_text(["0x0001", "0x0007"]),
        "XCDR1 (little-endian) [0x0001], XCDR2 (little-endian) [0x0007]")

  def test_summarize_filters_to_the_selected_writer_entity(self):
    observations = [
      wire.parse_tshark_fields("1\t0x15\t80000002\t\t1\t0x0001\t00:01\t"),
      wire.parse_tshark_fields("2\t0x15\t80000003\t\t1\t0x0007\t00:01\t"),
    ]
    summary = wire.summarize(observations, "80000002")
    self.assertEqual(summary["packets"], 1)
    self.assertEqual(summary["encapsulation_ids"], ["0x0001"])

  def test_endpoint_entity_id_reads_the_last_guid_word(self):
    endpoint = type("Endpoint", (), {
        "key": "Uint32Seq[16880768, 2662020784, 500195927, 2147483650]"})()
    self.assertEqual(wire.endpoint_entity_id(endpoint), "80000002")

  def test_endpoint_guid_prefix_reads_the_first_three_guid_words(self):
    endpoint = type("Endpoint", (), {
        "key": "Uint32Seq[16880768, 2662020784, 500195927, 2147483650]"})()
    self.assertEqual(wire.endpoint_guid_prefix(endpoint), "010194809eab36b01dd06257")

  def test_summarize_filters_to_selected_writer_guid_prefix(self):
    observations = [
        wire.parse_tshark_fields("1\t0x15\t80000002\t011000000000000000000001\t1\t0x0001\t00:01\t"),
        wire.parse_tshark_fields("2\t0x15\t80000002\t011000000000000000000002\t1\t0x0007\t00:01\t"),
    ]
    summary = wire.summarize(observations, writer_guid_prefix="011000000000000000000001")
    self.assertEqual(summary["encapsulation_ids"], ["0x0001"])

  def test_summarize_applies_every_filter_that_was_given(self):
    """A GUID prefix identifies the participant, so it cannot stand alone.

    Its own SEDP writers share that prefix, and so do its writers on other
    topics. Filtering by prefix alone therefore presented one participant's
    discovery traffic as the selected writer's user payload.
    """
    prefix = "011000000000000000000001"
    observations = [
        # The target writer.
        wire.parse_tshark_fields(f"1\t0x15\t80000002\t{prefix}\t1\t0x0001\t00:01\t"),
        # Same participant, its SEDP publication writer.
        wire.parse_tshark_fields(f"2\t0x15\t000003c2\t{prefix}\t1\t0x0003\t00:01\t"),
        # Same participant, a different user writer on another topic.
        wire.parse_tshark_fields(f"3\t0x15\t80000005\t{prefix}\t1\t0x0007\t00:01\t"),
    ]
    summary = wire.summarize(observations, writer_entity_id="80000002",
                             writer_guid_prefix=prefix)
    self.assertEqual(summary["packets"], 1)
    self.assertEqual(summary["writer_entity_ids"], ["80000002"])
    self.assertEqual(summary["encapsulation_ids"], ["0x0001"])

  def test_summarize_counts_submessages_behind_an_info_ts(self):
    """RTPS coalesces submessages, so the first id in a frame is usually INFO_TS.

    With tshark's occurrence=f the parser only ever saw 0x09, so DATA_FRAG could
    never be counted and every frame was recorded as a plain DATA.
    """
    observations = [
        wire.parse_tshark_fields("1\t0x09,0x15\t80000002\t\t1\t0x0001\t00:01\t"),
        wire.parse_tshark_fields("2\t0x09,0x16\t80000002\t\t2\t0x0001\t\t00:02:03:04"),
    ]
    summary = wire.summarize(observations, writer_entity_id="80000002")
    self.assertEqual(summary["data_packets"], 1)
    self.assertEqual(summary["data_fragments"], 1)

  def test_a_coalesced_frame_is_not_presented_as_writer_attributed(self):
    """One frame carrying the target writer AND another user writer.

    tshark's frame-level fields do not associate bytes with submessages, so the
    frame is admitted whole: the other writer's entity id and its payload bytes
    are inside these totals. That is the aggregation the tool has, and the
    summary must therefore not claim the numbers belong to the target writer.
    A JSON consumer reads the keys alone, so the disclaimer has to be a value in
    the mapping and not only a label in the text appendix.
    """
    prefix = "011000000000000000000001"
    observations = [
        # INFO_TS, the target writer's DATA, and a second user writer's DATA -
        # one frame, so tshark reports each field as a list of occurrences.
        wire.parse_tshark_fields(
            f"1\t0x09,0x15,0x15\t80000002,80000005\t{prefix}\t1,2\t0x0001,0x0007"
            "\t00:01,00:02:03:04\t"),
    ]
    summary = wire.summarize(observations, writer_entity_id="80000002",
                             writer_guid_prefix=prefix)

    self.assertIs(summary["writer_attributed"], False)
    self.assertIn("frames", summary["scope"])
    self.assertIn("filter, not an attribution claim", summary["scope_note"])
    # The frame is counted once, and the second writer is visibly inside it:
    # both are consequences of frame-level filtering, and the scope keys above
    # are what keeps them from reading as the target writer's evidence.
    self.assertEqual(summary["packets"], 1)
    self.assertEqual(summary["writer_entity_ids"], ["80000002", "80000005"])
    self.assertEqual(summary["encapsulation_ids"], ["0x0001", "0x0007"])

  def test_the_scope_marker_survives_into_the_report(self):
    """Both renderers must carry it: the text reader and the JSON consumer."""
    observations = [wire.parse_tshark_fields("1\t0x15\t80000002\t\t1\t0x0007\t00:01\t")]
    data = report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        wire_evidence={"source": "capture.pcapng",
                       **wire.summarize(observations, writer_entity_id="80000002")})

    # The note is wrapped to the report width, so compare against a single line.
    rendered = " ".join(report.render_text(data).split())
    self.assertIn("filter, not an attribution claim", rendered)
    payload = json.loads(report.render_json(data))["wire_observation"]
    self.assertIs(payload["writer_attributed"], False)
    self.assertIn("scope_note", payload)

  def test_wire_appendix_labels_do_not_collide_with_their_values(self):
    """`_kv` pads to a fixed width, and these labels are longer than the default.

    The frame-scope labels run to 36 characters against a default pad of 16, so
    every value rendered flush against its own label until the pad was widened.
    Substring assertions on the labels alone cannot see this.
    """
    observations = [wire.parse_tshark_fields("1\t0x15\t80000002\t\t1\t0x0007\t00:01\t")]
    data = report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        wire_evidence={"source": "capture.pcapng",
                       **wire.summarize(observations, writer_entity_id="80000002")})

    text = report.render_text(data)
    self.assertIn("Frames matching filters               1", text)
    self.assertIn("Observed DDS data representation      XCDR2 (little-endian) [0x0007]",
            text)
    self.assertIn("Encapsulation IDs in matching frames  0x0007", text)

  def test_capture_filter_prefers_selected_writer_locator(self):
    endpoint = self.Endpoint([self.Locator("192.0.2.5", 7411)])
    actual = wire.capture_filter(7, endpoint, self.Qos())
    self.assertEqual(actual, "udp and (portrange 9150-9399 or port 7411)")

  def test_capture_filter_falls_back_to_domain_port_range(self):
    actual = wire.capture_filter(7, self.Endpoint([]), self.Qos())
    self.assertEqual(actual, "udp and (portrange 9150-9399)")

  def test_live_capture_kills_a_tshark_process_that_ignores_terminate(self):
    class Process:
      def __init__(self):
        self.returncode = None
        self.killed = False
        self.calls = 0
      def poll(self):
        return self.returncode
      def terminate(self):
        pass
      def kill(self):
        self.killed = True
        self.returncode = -9
      def wait(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
          raise subprocess.TimeoutExpired("tshark", timeout)
        return self.returncode

    capture = wire.LiveCapture("lo", "capture.pcapng", "udp", tshark_path="tshark")
    capture.process = Process()
    evidence = capture.finish()
    self.assertTrue(capture.process.killed)
    self.assertIn("was killed", evidence["error"])

  def test_live_capture_reports_a_tshark_that_died_mid_capture(self):
    """An already-exited tshark must not be reported as an empty success.

    The status check used to sit inside `if poll() is None`, so a tshark that
    died after start()'s one-second window - interface removed, permission
    revoked, disk full - skipped it entirely and the resulting empty file was
    summarized as a successful capture of zero packets.
    """
    class Process:
      returncode = 2
      def poll(self):
        return self.returncode

    capture = wire.LiveCapture("lo", "capture.pcapng", "udp", tshark_path="tshark")
    capture.process = Process()
    evidence = capture.finish()
    self.assertIn("tshark exited with 2", evidence["error"])
    self.assertNotIn("packets", evidence)

  @mock.patch("rti_doctor.wire.os.path.isfile", return_value=False)
  def test_live_capture_explains_when_tshark_creates_no_file(self, _isfile):
    class Process:
      returncode = 0
      def poll(self):
        return self.returncode

    capture = wire.LiveCapture("lo", "capture.pcapng", "udp", tshark_path="tshark")
    capture.process = Process()
    evidence = capture.finish()
    self.assertIn("without creating a capture file", evidence["error"])

  def test_report_includes_packet_evidence(self):
    data = report.ReportData(
        domain_id=7,
        scope="topic 'Sample'",
        all_findings=[],
        wire_evidence={
            "source": "capture.pcapng",
            "packets": 1,
            "data_packets": 1,
            "data_fragments": 0,
            "encapsulation_ids": ["0x0007"],
            "writer_entity_ids": ["000001c2"],
            "payload_bytes": 12,
            "reassembled_bytes": 0,
        })
    text = report.render_text(data)
    self.assertIn("DIRECT RTPS PACKET OBSERVATION", text)
    self.assertIn("Frames matching filters", text)
    self.assertIn("Encapsulation IDs in matching frames", text)
    self.assertIn("Serialized bytes in matching frames", text)
    self.assertIn("APPENDIX D - RTI_DOCTOR OWN CONFIGURATION", text)
    self.assertIn("0x0007", text)
    self.assertEqual(report.render_json(data).count("wire_observation"), 1)


if __name__ == "__main__":
  unittest.main()