"""Unit tests for tshark RTPS field parsing."""

import os
import subprocess
import sys
import unittest

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
    self.assertIn("APPENDIX D - RTI_DOCTOR OWN CONFIGURATION", text)
    self.assertIn("0x0007", text)
    self.assertEqual(report.render_json(data).count("wire_observation"), 1)


if __name__ == "__main__":
  unittest.main()