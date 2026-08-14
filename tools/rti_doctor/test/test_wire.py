"""Unit tests for tshark RTPS field parsing."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from rti_doctor import paths, wire  # noqa: E402
from rti_doctor import probe as probe_module  # noqa: E402
from rti_doctor import records, report  # noqa: E402
import doctor_e2e  # noqa: E402


class FakeVendorId:
  """Vendor ids are read through `.value`; a bare list is not one."""

  def __init__(self, octets):
    self.value = list(octets)


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

  def test_the_builtin_servicerequest_channel_is_not_a_handshake(self):
    """RTI's ServiceRequest channel is builtin but does not use the c2/c3 kinds.

    Measured on a live participant capture: `0x00020082` -> `0x00020087`
    contributed 7 HEARTBEAT and 7 ACKNACK on a participant with no user
    endpoints at all. It only became reachable when this module started counting
    protocol submessages - they carry no payload, so the old encapsulation-only
    display filter had excluded them - and the reliable check would have read it
    as a verified handshake on a topic with no traffic.
    """
    observations = [
        wire.parse_tshark_fields("1\t0x0e,0x07\t0x00020082\t\t\t\t\t0x00020087"),
        wire.parse_tshark_fields("2\t0x0e,0x06\t0x00020082\t\t\t\t\t0x00020087"),
    ]
    summary = wire.summarize(observations)
    self.assertEqual(summary["heartbeats"], 0)
    self.assertEqual(summary["acknacks"], 0)
    self.assertEqual(summary["packets"], 0)

  def test_a_user_writer_whose_id_ends_in_the_kind_digits_is_kept(self):
    """The suffix test matches the entity KIND byte, which users never share.

    A user writer's kind is 0x02/0x03, so its id ends "02"/"03" and can never
    collide with "c2", "c3" or "82" - this guards the suffix match from being
    loosened into one that would silently drop real user traffic.
    """
    observations = [
        wire.parse_tshark_fields("1\t0x07\t0x80000082\t\t\t\t\t"),
        wire.parse_tshark_fields("2\t0x07\t0x800000c2\t\t\t\t\t"),
        wire.parse_tshark_fields("3\t0x07\t0x80000002\t\t\t\t\t"),
    ]
    # The first two carry builtin KIND bytes (0x82, 0xc2) and are excluded; only
    # the third is a user writer.
    self.assertEqual(wire.summarize(observations)["heartbeats"], 1)

  def test_summarize_counts_the_reliable_protocol_submessages(self):
    """HEARTBEAT/ACKNACK/GAP/NACK_FRAG are the evidence a reliable path works."""
    observations = [
        wire.parse_tshark_fields("1\t0x15\t80000002\t\t1\t0x0001\t00:01\t"),
        wire.parse_tshark_fields("2\t0x07\t80000002\t\t\t\t\t"),
        wire.parse_tshark_fields("3\t0x06\t80000002\t\t\t\t\t"),
        wire.parse_tshark_fields("4\t0x08\t80000002\t\t\t\t\t"),
        wire.parse_tshark_fields("5\t0x12\t80000002\t\t\t\t\t"),
    ]
    summary = wire.summarize(observations, writer_entity_id="80000002")
    self.assertEqual(summary["heartbeats"], 1)
    self.assertEqual(summary["acknacks"], 1)
    self.assertEqual(summary["gaps"], 1)
    self.assertEqual(summary["nack_fragments"], 1)
    # The protocol frames carry no payload and must not inflate the data counts.
    self.assertEqual(summary["data_packets"], 1)

  def test_summarize_keeps_an_acknack_sent_from_the_readers_participant(self):
    """The half of the handshake that proves the reliable path works both ways.

    `writer_guid_prefix` is matched against `rtps.guidPrefix.src`, the sender.
    An ACKNACK travels from the READER's participant back to the writer, so its
    source prefix is the reader's - and applying the prefix filter to it dropped
    every acknowledgment before it could be counted, leaving a working reliable
    path indistinguishable from a writer nobody was answering.
    """
    writer_prefix = "011000000000000000000001"
    reader_prefix = "011000000000000000000002"
    observations = [
        # The writer's own DATA and HEARTBEAT.
        wire.parse_tshark_fields(f"1\t0x15\t80000002\t{writer_prefix}\t1\t0x0001\t00:01\t"),
        wire.parse_tshark_fields(f"2\t0x07\t80000002\t{writer_prefix}\t\t\t\t"),
        # The reader answering, from its own participant.
        wire.parse_tshark_fields(f"3\t0x06\t80000002\t{reader_prefix}\t\t\t\t"),
    ]
    summary = wire.summarize(observations, writer_entity_id="80000002",
                             writer_guid_prefix=writer_prefix)
    self.assertEqual(summary["heartbeats"], 1)
    self.assertEqual(summary["acknacks"], 1)

  def test_summarize_still_excludes_another_participants_data(self):
    """Relaxing the prefix filter for ACKNACK must not relax it for DATA."""
    writer_prefix = "011000000000000000000001"
    other_prefix = "011000000000000000000002"
    observations = [
        wire.parse_tshark_fields(f"1\t0x15\t80000002\t{writer_prefix}\t1\t0x0001\t00:01\t"),
        wire.parse_tshark_fields(f"2\t0x15\t80000002\t{other_prefix}\t1\t0x0007\t00:01\t"),
    ]
    summary = wire.summarize(observations, writer_entity_id="80000002",
                             writer_guid_prefix=writer_prefix)
    self.assertEqual(summary["data_packets"], 1)
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
                      endpoint=None, participant=None,
                      participant_evidence=None):
    return report.render_text(report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[], endpoint=endpoint,
        participant=participant,
        wire_evidence=wire_evidence, discovery_evidence=discovery_evidence,
        participant_evidence=participant_evidence))

  def test_a_connext_peer_report_carries_no_fastdds_version(self):
    """A capture hears the whole domain; the report is about one endpoint.

    Measured on a live domain 42: selecting a Connext reader that shared its
    domain with a Fast DDS writer produced a report whose CAPTURE EVIDENCE
    section led with "Fast DDS version 3.6.2.0" - a fact about the other
    participant entirely. The product version is a Fast DDS vendor-specific
    discovery PID, so an RTI peer can never be the one that advertised it.
    """
    text = self._capture_report(
        participant=records.ParticipantRecord(key="p1", vendor_id=FakeVendorId((0x01, 0x01))),
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"],
                            "participants": 2})
    self.assertNotIn("3.6.2.0", text)
    self.assertNotIn("Fast DDS version", text)

  def test_a_fastdds_peer_report_still_carries_its_version(self):
    text = self._capture_report(
        participant=records.ParticipantRecord(key="p1", vendor_id=FakeVendorId((0x01, 0x0F))),
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"],
                            "participants": 2})
    self.assertIn("3.6.2.0", text)

  def test_a_version_is_narrowed_to_the_peer_that_advertised_it(self):
    """Two Fast DDS participants on one domain, only one of them this peer."""
    peer = records.ParticipantRecord(
        key="Uint32Seq[16880768, 2662020784, 500195927, 1]",
        vendor_id=FakeVendorId((0x01, 0x0F)))
    prefix = report.wire.record_guid_prefix(peer)
    text = self._capture_report(
        participant=peer,
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={
            "fastdds_product_versions": ["3.6.2.0", "2.14.0.0"],
            "fastdds_participant_versions": [[prefix, "3.6.2.0"],
                                             ["ffffffffffffffffffffffff",
                                              "2.14.0.0"]],
            "participants": 2})
    self.assertIn("3.6.2.0", text)
    self.assertNotIn("2.14.0.0", text)

  def test_an_unidentified_peer_keeps_the_version_evidence(self):
    """No participant record is a headless run, not a Connext peer.

    Suppressing on anything short of a positive RTI identification would drop
    the only version evidence a `--topic` run ever has.
    """
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        discovery_evidence={"fastdds_product_versions": ["3.6.2.0"]})
    self.assertIn("3.6.2.0", text)

  def test_a_writer_probe_does_not_blame_connext_for_reader_counters(self):
    """The false claim in a saved report: "n/a on Connext 7.7.0".

    Selecting a READER makes the probe create a WRITER, so no reader status was
    ever sampled - `datareader_protocol_status` and `datareader_cache_status`
    stayed empty and every line rendered as unavailable on this Connext version.
    Those statuses do exist on 7.7; nothing asked for them. The appendix must
    report the writer's own counters instead of a version limitation that is not
    real.
    """
    result = probe_module.ProbeResult()
    result.attempted = True
    result.created = True
    result.probe_kind = "writer"
    result.writer_protocol = {"sent_heartbeat_count": 4, "received_ack_count": 4}
    result.writer_cache = {"unacknowledged_sample_count": 0}
    text = report.render_text(report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        probe_result=result))
    self.assertIn("datawriter_protocol_status", text)
    self.assertIn("reliable_writer_cache_changed_status", text)
    self.assertNotIn("datareader_protocol_status", text)
    self.assertNotIn("datareader_cache_status", text)
    # The reader's incompatible-QoS status does not exist on a writer either.
    self.assertIn("offered_incompatible_qos", text)
    self.assertNotIn("requested_incompatible_qos", text)

  def test_a_non_writing_probe_says_so_instead_of_implying_a_fault(self):
    result = probe_module.ProbeResult()
    result.attempted = True
    result.created = True
    result.probe_kind = "writer"
    text = report.render_text(report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        probe_result=result))
    self.assertIn("published nothing", text)
    self.assertIn("rti_doctor's own restraint", text)

  def test_a_reader_probe_still_reports_the_reader_counters(self):
    result = probe_module.ProbeResult()
    result.attempted = True
    result.created = True
    result.protocol = {"received_heartbeat_count": 3}
    text = report.render_text(report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        probe_result=result))
    self.assertIn("datareader_protocol_status", text)
    self.assertNotIn("datawriter_protocol_status", text)

  def test_the_applied_qos_renders_values_not_object_reprs(self):
    """A saved report showed `<rti.connextdds.Deadline object at 0x...>`.

    This block exists so an operator can check the probe requested what it says
    it did, and an object repr is exactly where that check fails.
    """
    result = probe_module.ProbeResult()
    result.attempted = True
    result.created = True
    result.probe_kind = "writer"
    result.applied_reader_qos = {"reliability": "ReliabilityKind.RELIABLE"}
    text = report.render_text(report.ReportData(
        domain_id=7, scope="topic 'Sample'", all_findings=[],
        probe_result=result))
    self.assertIn("probe writer/publisher QoS", text)
    self.assertNotIn("object at 0x", text)

  def test_participant_evidence_renders_its_own_scope(self):
    """CAP-4. The shared-memory half, and what it can and cannot claim."""
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0},
        participant_evidence={
            "source": "p.pcap", "kind": "rti network capture",
            "packets": 81, "data_packets": 53, "data_fragments": 0,
            "heartbeats": 15, "acknacks": 14, "gaps": 0, "nack_fragments": 0})
    self.assertIn("RTI Network Capture", text)
    self.assertIn("SHARED MEMORY", text)
    # The scope caveat is the point: it sees one participant, ours, and no
    # traffic between two others. It is wrapped to the report width, so compare
    # against a single line.
    self.assertIn("only rti_doctor's own frames", " ".join(text.split()))
    self.assertIn("81", text)
    self.assertIn("15", text)

  def test_participant_evidence_alone_still_earns_the_appendix(self):
    """RTI Network Capture needs no interface and no capture privileges.

    A run can therefore produce participant evidence and no interface evidence
    at all, and gating Appendix C on `wire_evidence` would discard the only
    packet evidence such a run has.
    """
    text = self._capture_report(participant_evidence={
        "source": "p.pcap", "packets": 12, "heartbeats": 4, "acknacks": 4})
    self.assertIn("APPENDIX C", text)
    self.assertIn("RTI Network Capture", text)

  def test_a_reader_target_is_filtered_as_a_reader(self):
    """`--topic` can select a reader, so `--pcap` must filter like one.

    `inspect_pcap` matches `writer_entity_id` against `rtps.sm.wrEntityId`.
    Passing a READER's id there yields a filter nothing can match, so every
    reader-target `--pcap` run reported "No user DATA from the selected endpoint
    was captured" regardless of what the file held. `engine.diagnose_endpoint`
    branches on `is_writer` correctly; the `--pcap` call site did not.
    """
    # Nine tab-separated columns; the reader entity id is the last.
    observations = [
        # A writer sending to the selected reader: matched by reader id.
        wire.parse_tshark_fields("1\t0x15\t0x80000002\t\t1\t0x0001\t00:01\t\t0x80000004"),
        # Another reader's traffic on the same topic.
        wire.parse_tshark_fields("2\t0x15\t0x80000002\t\t1\t0x0001\t00:01\t\t0x80000104"),
    ]
    as_reader = wire.summarize(observations, reader_entity_id="80000004")
    self.assertEqual(as_reader["data_packets"], 1)
    # The bug: the same id passed as a writer filter matches nothing.
    as_writer = wire.summarize(observations, writer_entity_id="80000004")
    self.assertEqual(as_writer["data_packets"], 0)

  def test_appendix_letters_are_never_reused(self):
    """Found live: participant evidence alone produced two "APPENDIX C"s.

    The config appendix chose its letter from `wire_evidence` alone, so an RTI
    Network Capture run - which needs no interface and therefore has no
    `wire_evidence` - emitted a packet Appendix C and then a configuration
    Appendix C. The report's whole contract is a fixed, citable section order.
    """
    for kwargs in (
        {"participant_evidence": {"source": "p.pcap", "packets": 1}},
        {"wire_evidence": {"source": "c.pcapng", "packets": 1, "data_packets": 1}},
        {"participant_evidence": {"source": "p.pcap", "packets": 1},
         "wire_evidence": {"source": "c.pcapng", "packets": 1, "data_packets": 1}},
        {},
    ):
      text = self._capture_report(**kwargs)
      letters = [line.split()[1] for line in text.splitlines()
                 if line.startswith("APPENDIX ")]
      self.assertEqual(letters, sorted(set(letters)),
                       f"appendix letters repeat or are out of order: {letters} "
                       f"for {sorted(kwargs)}")

  def test_a_failed_participant_capture_says_why(self):
    text = self._capture_report(participant_evidence={
        "source": "p.pcap", "error": "network capture was not enabled at startup"})
    self.assertIn("unavailable: network capture was not enabled", text)

  def test_no_participant_capture_leaves_the_report_unchanged(self):
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 0, "data_packets": 0})
    self.assertNotIn("RTI Network Capture", text)

  def test_the_wire_appendix_reports_the_reliable_handshake(self):
    text = self._capture_report(
        wire_evidence={"source": "c.pcapng", "packets": 9, "data_packets": 4,
                       "data_fragments": 0, "heartbeats": 3, "acknacks": 2,
                       "gaps": 1, "nack_fragments": 0})
    self.assertIn("HEARTBEAT in matching frames", text)
    self.assertIn("ACKNACK in matching frames", text)
    self.assertIn("GAP in matching frames", text)

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