"""Unit tests for tshark RTPS field parsing."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from rti_doctor import paths, wire  # noqa: E402
from rti_doctor import records, report  # noqa: E402
import doctor_e2e  # noqa: E402


class TestOutputPaths(unittest.TestCase):

  def test_output_root_is_anchored_to_rti_doctor(self):
    expected = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "test_output"))
    with mock.patch("os.getcwd", return_value="/unrelated/working/directory"):
      actual = paths.test_output_path("rti_doctor_captures", "capture.pcapng")
    self.assertEqual(
        actual, os.path.join(expected, "rti_doctor_captures", "capture.pcapng"))


class TestTsharkFields(unittest.TestCase):

  class Locator:
    def __init__(self, address, port, kind=1):
      self.address = [0] * 12 + [int(part) for part in address.split(".")]
      self.port = port
      self.kind = kind

  class Endpoint:
    def __init__(self, locators):
      self.unicast_locators = locators

  class Owner:
    """A participant record, which is where an endpoint's defaults live."""

    def __init__(self, locators):
      self.default_unicast_locators = locators

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
    The disclaimer travels as a value in the mapping, not as a fixed label in
    the renderer, so it cannot be separated from the numbers it qualifies.
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
    """The caveat must reach the reader, not just the summary that carries it.

    `writer_attributed` is a machine flag; the report is read by a person, so
    the sentence it stands for has to be rendered rather than the flag.
    """
    observations = [wire.parse_tshark_fields("1\t0x15\t80000002\t\t1\t0x0007\t00:01\t")]
    summary = wire.summarize(observations, writer_entity_id="80000002")
    self.assertIs(summary["writer_attributed"], False)
    self.assertIn("scope_note", summary)
    data = report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        wire_evidence={"source": "capture.pcapng", **summary})

    # The note is wrapped to the report width, so compare against a single line.
    rendered = " ".join(report.render_text(data).split())
    self.assertIn("filter, not an attribution claim", rendered)

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

  def _capture_report(self, wire_evidence=None, discovery_evidence=None,
                      endpoint=None):
    return report.render_text(report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[], endpoint=endpoint,
        wire_evidence=wire_evidence, discovery_evidence=discovery_evidence))

  def test_capture_summary_puts_the_packet_only_version_near_the_top(self):
    """The version is the one fact no DDS-level observation can produce.

    It was reachable only in Appendix C, below every finding, which is the
    wrong place for the main thing a capture just bought you.
    """
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"],
                            "participants": 1})
    self.assertIn("CAPTURE EVIDENCE", text)
    summary, appendix = text.split("APPENDIX", 1)
    self.assertIn("3.6.2.0", summary)
    # Still in the appendix too: the summary is a pointer, not a replacement.
    self.assertIn("3.6.2.0", appendix)

  def test_capture_summary_labels_do_not_collide_with_their_values(self):
    """`_kv` defaults to a 16-char pad and these labels run to 21.

    Caught in a live run rendering "Fast DDS version3.6.2.0". A substring
    assertion on the label alone cannot see it, so assert the gap.
    """
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"]})
    self.assertIn("  Fast DDS version      3.6.2.0", text)

  def test_no_capture_leaves_the_report_unchanged(self):
    self.assertNotIn("CAPTURE EVIDENCE", self._capture_report())

  def test_a_failed_capture_does_not_read_as_a_quiet_wire(self):
    """"Nobody looked" and "there was nothing there" are opposite conclusions."""
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "error": "tshark not found"})
    self.assertIn("capture unavailable: tshark not found", text)
    self.assertNotIn("No user DATA", text)

  def test_capture_summary_flags_a_wire_representation_the_peer_did_not_advertise(self):
    """The comparison only a capture can make: advertised versus serialized."""
    class Representation:
      value = [0]  # XCDR1 advertised...

    endpoint = records.EndpointRecord(key="w", kind="Writer",
                                      representation=Representation())
    text = self._capture_report(
        # ...while 0x0007 on the wire is XCDR2.
        wire_evidence={"source": "c.pcapng", "packets": 1, "data_packets": 1,
                       "encapsulation_ids": ["0x0007"]},
        endpoint=endpoint)
    self.assertIn("disagrees with the advertised XCDR1", text)

  def test_capture_summary_makes_no_claim_about_a_reader(self):
    """The "first entry is effective" rule is writer-only.

    A reader's list is the set it *accepts*, so a reader advertising both and
    receiving XCDR2 agrees with the wire. Capture is supported on reader
    reports, so applying the writer rule there reported a contradiction that
    does not exist.
    """
    class Both:
      value = [0, 2]

    endpoint = records.EndpointRecord(key="r", kind="Reader",
                                      representation=Both())
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 1, "data_packets": 1,
                       "encapsulation_ids": ["0x0007"]},
        endpoint=endpoint)
    self.assertIn("observed on the wire", text)
    self.assertNotIn("disagrees", text)

  def test_capture_summary_makes_no_claim_about_auto(self):
    """AUTO's effective representation is not determinable from discovery.

    `qos_match` declines to compare it for exactly that reason, so a summary
    calling it a disagreement would be the report arguing with itself.
    """
    class Auto:
      value = [-1]

    endpoint = records.EndpointRecord(key="w", kind="Writer",
                                      representation=Auto())
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 1, "data_packets": 1,
                       "encapsulation_ids": ["0x0007"]},
        endpoint=endpoint)
    summary = text.split("CAPTURE EVIDENCE", 1)[1].split("PEER", 1)[0]
    self.assertNotIn("disagrees", summary)
    # AUTO still belongs in the PEER block as the advertised fact; what must
    # not happen is the summary drawing a conclusion from it.
    self.assertNotIn("AUTO", summary)
    self.assertIn("Representation  AUTO", text)

  def test_capture_summary_confirms_a_matching_representation(self):
    class Representation:
      value = [2]

    endpoint = records.EndpointRecord(key="w", kind="Writer",
                                      representation=Representation())
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 1, "data_packets": 1,
                       "encapsulation_ids": ["0x0007"]},
        endpoint=endpoint)
    self.assertIn("agrees with the advertised XCDR2", text)
    self.assertNotIn("disagrees", text)

  def test_capture_filter_prefers_selected_writer_locator(self):
    endpoint = self.Endpoint([self.Locator("192.0.2.5", 7411)])
    actual = wire.capture_filter(7, endpoint, self.Qos())
    self.assertEqual(actual, "udp and (portrange 9150-9399 or port 7411)")

  def test_capture_filter_falls_back_to_domain_port_range(self):
    actual = wire.capture_filter(7, self.Endpoint([]), self.Qos())
    self.assertEqual(actual, "udp and (portrange 9150-9399)")

  def test_capture_filter_uses_participant_locators_when_the_endpoint_has_none(self):
    """WIRE-2: Cyclone advertises its data port only at participant level.

    Measured 2026-08-12 against a real Cyclone writer: its endpoint's
    `unicast_locators` is empty, its participant advertises one UDPv4 locator,
    and that port is outside the domain's RTPS range - so the range term alone
    excluded every user DATA frame it sent, and the capture reported "none
    observed" after seeing none of it. An endpoint inheriting its
    participant's default locators is legal RTPS, not a Cyclone quirk.
    """
    owner = self.Owner([self.Locator("192.0.2.9", 41050)])
    actual = wire.capture_filter(7, self.Endpoint([]), self.Qos(), owner=owner)
    self.assertEqual(actual, "udp and (portrange 9150-9399 or port 41050)")

  def test_capture_filter_prefers_endpoint_locators_over_participant_defaults(self):
    """The fallback must not widen the filter when the endpoint is specific.

    Connext and Fast DDS both name endpoint locators. Adding participant
    defaults on top would broaden every capture to fix the one vendor that
    needs it, so the participant list is consulted only when the endpoint's is
    empty.
    """
    owner = self.Owner([self.Locator("192.0.2.9", 41050)])
    endpoint = self.Endpoint([self.Locator("192.0.2.5", 7411)])
    actual = wire.capture_filter(7, endpoint, self.Qos(), owner=owner)
    self.assertEqual(actual, "udp and (portrange 9150-9399 or port 7411)")

  def test_capture_filter_without_an_owner_is_unchanged(self):
    """`owner` is optional, and omitting it must behave as it did before."""
    self.assertEqual(wire.capture_filter(7, self.Endpoint([]), self.Qos()),
                     wire.capture_filter(7, self.Endpoint([]), self.Qos(),
                                         owner=None))

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

  def test_a_capture_bounds_itself_with_a_duration(self):
    """H9: nothing may run tshark without a stop condition of its own.

    `finish()` is the normal end, but an owner that never reaches it - a popped
    screen, a killed interpreter - used to leave tshark writing until something
    else stopped it. The ceiling is tshark's own, so it survives losing us.
    """
    commands = []

    class Process:
      def poll(self):
        return None

    def record(command, **kwargs):
      commands.append(command)
      return Process()

    capture = wire.LiveCapture("lo", "capture.pcapng", "udp", tshark_path="tshark",
                               duration=23.4)
    with mock.patch("rti_doctor.wire.subprocess.Popen", record), \
         mock.patch("rti_doctor.wire.time.sleep", lambda seconds: None), \
         mock.patch("rti_doctor.wire.os.makedirs"), \
         mock.patch("builtins.open", mock.mock_open()):
      capture.start()
    self.assertIsNone(capture.error)
    self.assertIn("-a", commands[0])
    self.assertEqual(commands[0][commands[0].index("-a") + 1], "duration:23")

  def test_a_capture_without_a_duration_asks_for_none(self):
    """`-a duration:0` means "no limit" to tshark, so 0 must not be emitted."""
    commands = []

    class Process:
      def poll(self):
        return None

    capture = wire.LiveCapture("lo", "capture.pcapng", "udp", tshark_path="tshark")
    with mock.patch("rti_doctor.wire.subprocess.Popen",
                    lambda command, **kwargs: commands.append(command) or Process()), \
         mock.patch("rti_doctor.wire.time.sleep", lambda seconds: None), \
         mock.patch("rti_doctor.wire.os.makedirs"), \
         mock.patch("builtins.open", mock.mock_open()):
      capture.start()
    self.assertNotIn("-a", commands[0])

  def test_one_capture_can_be_read_as_user_data_and_as_discovery(self):
    """The two questions share one file, so only the first read stops tshark."""
    class Process:
      def __init__(self):
        self.returncode = None
        self.terminates = 0

      def poll(self):
        return self.returncode

      def terminate(self):
        self.terminates += 1
        self.returncode = -15

      def wait(self, timeout=None):
        return self.returncode

    capture = wire.LiveCapture("lo", "capture.pcapng", "udp", tshark_path="tshark")
    capture.process = Process()
    with mock.patch("rti_doctor.wire.os.path.isfile", return_value=True), \
         mock.patch("rti_doctor.wire.inspect_pcap",
                    return_value={"packets": 3}) as user_data, \
         mock.patch("rti_doctor.wire.inspect_discovery_pcap",
                    return_value={"fastdds_product_versions": ["3.5.4.0"]}) as meta:
      packets = capture.finish()
      discovery_evidence = capture.finish_discovery()
    self.assertEqual(capture.process.terminates, 1)
    self.assertEqual(user_data.call_count, 1)
    self.assertEqual(meta.call_count, 1)
    self.assertEqual(packets["packets"], 3)
    self.assertEqual(discovery_evidence["fastdds_product_versions"], ["3.5.4.0"])

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
    # Once, and only in the appendix: the packet evidence used to be emitted a
    # second time alongside it.
    self.assertEqual(text.count("DIRECT RTPS PACKET OBSERVATION"), 1)
    self.assertEqual(text.count("Frames matching filters"), 1)

  def test_report_carries_the_discovery_evidence_from_the_same_capture(self):
    """One capture, two questions: what crossed the wire, and who announced.

    The Fast DDS product version is the one fact in this tool that no DDS-level
    observation can produce, so a report that captured packets has to render it
    - and a machine reading the report back has to be able to find it.
    """
    data = report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        capture_interface="eth0",
        wire_evidence={"source": "capture.pcapng", "packets": 1,
                       "data_packets": 1, "data_fragments": 0,
                       "encapsulation_ids": ["0x0007"],
                       "writer_entity_ids": ["000001c2"],
                       "payload_bytes": 12, "reassembled_bytes": 0},
        discovery_evidence={"fastdds_product_versions": ["3.5.4.0"],
                            "participants": 2, "topics": ["Sample"]})
    text = report.render_text(data)
    self.assertIn("Capture interface", text)
    self.assertIn("eth0", text)
    self.assertIn("RTPS discovery observed in the same capture", text)
    self.assertIn("3.5.4.0", text)

    completed = subprocess.CompletedProcess(args=["rti_doctor"], returncode=0,
                                            stdout=text, stderr="")
    parsed = doctor_e2e.parse_report(completed)["wire_observation"]
    self.assertEqual(parsed["source"], "capture.pcapng")
    self.assertEqual(parsed["capture_interface"], "eth0")
    self.assertEqual(parsed["fastdds_product_versions"], ["3.5.4.0"])

  def test_a_failed_capture_still_reports_what_discovery_it_read(self):
    data = report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        wire_evidence={"source": "capture.pcapng", "error": "no permission"},
        discovery_evidence={"error": "no permission"})
    text = report.render_text(data)
    self.assertIn("unavailable: no permission", text)
    self.assertIn("RTPS discovery observed in the same capture", text)


if __name__ == "__main__":
  unittest.main()