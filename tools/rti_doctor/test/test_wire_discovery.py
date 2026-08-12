"""Tests for metadata-only RTPS discovery topology parsing."""

import contextlib
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import wire  # noqa: E402


#: The one optional column at the time of writing: the same release octet the
#: dissector renders under a second name on some builds.
RELEASE_STRING = "rtps.param.product_version.release_string"


def probed_field(command):
  """The field a field-support probe is asking about, or None for a real read.

  A probe is the run that reads `os.devnull` - it opens no capture and exists
  only to be told whether the name is valid.
  """
  if os.devnull not in command:
    return None
  return command[command.index("-e") + 1]


@contextlib.contextmanager
def fake_tshark(unsupported=(), probe_raises=None, commands=None):
  """Stand in for tshark, answering field probes the way the real one does.

  An unknown field is rejected by message before the capture is opened; a known
  one gets as far as complaining about the file. Both are what `_probe_field`
  reads, so a change to either end of that contract fails here.
  """
  commands = commands if commands is not None else []

  def fake_run(command, **kwargs):
    commands.append(command)
    field = probed_field(command)
    if field is None:
      return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    if probe_raises is not None:
      raise probe_raises
    if field in unsupported:
      return subprocess.CompletedProcess(
          command, 1, stdout="",
          stderr=f"tshark: Some fields aren't valid:\n\t{field}\n")
    return subprocess.CompletedProcess(
        command, 3, stdout="",
        stderr=f'tshark: The file "{os.devnull}" is a "special file" or '
               f'socket or other non-regular file.\n')

  original_run = wire.subprocess.run
  wire.subprocess.run = fake_run
  try:
    yield commands
  finally:
    wire.subprocess.run = original_run


def run_discovery_capture(unsupported=(), reset=True):
  """Drive `inspect_discovery_pcap` against a fake tshark.

  Returns the fields the capture command actually asked for, and how many
  probes it paid to decide that.
  """
  if reset:
    wire.reset_field_support_cache()
  with fake_tshark(unsupported=unsupported) as commands:
    wire.inspect_discovery_pcap(__file__, tshark_path="/usr/bin/tshark")
  probes = [command for command in commands if probed_field(command)]
  # Not "the last non-probe command": reading a capture also makes a second,
  # PDML pass for the product-version parameter, and that one carries no -e.
  read = [command for command in commands
          if not probed_field(command) and "fields" in command][-1]
  requested = [read[index + 1] for index, item in enumerate(read)
               if item == "-e"]
  return requested, len(probes)


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
      ("rtps.param.product_version.release_string", "product_version_release_string"),
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
    requested, _ = run_discovery_capture()
    self.assertEqual(requested, [field for field, _ in wire.DISCOVERY_FIELDS])

  def test_a_field_this_tshark_rejects_is_not_requested_at_all(self):
    # tshark validates every -e before it opens the capture and exits rather
    # than run, so one unknown optional field would cost the whole capture
    # rather than the single column it names.
    requested, _ = run_discovery_capture(unsupported={RELEASE_STRING})
    self.assertNotIn(RELEASE_STRING, requested)
    self.assertEqual(requested, [field for field, _ in wire.DISCOVERY_FIELDS
                                 if field != RELEASE_STRING])

  def test_a_dropped_column_is_dropped_from_the_parse_too(self):
    # The layout is positional: a column dropped from the request but not from
    # the parse reads every later column one slot to the left.
    with fake_tshark(unsupported={RELEASE_STRING}):
      layout = wire.discovery_fields("/usr/bin/tshark")
    row = "\t".join(("010f00000000000000000001", "0x010f", "3", "6", "2", "0",
                     "0x000004c2", "0x000004c7", "0x00000c3f", "Status",
                     "StatusType", "0x00000001"))
    observation = wire.parse_discovery_fields(row, layout)
    self.assertEqual(observation.product_version_release, "2")
    self.assertEqual(observation.product_version_revision, "0")
    self.assertEqual(observation.product_version_release_string, "")
    self.assertEqual(observation.topic_name, "Status")
    self.assertEqual(observation.reliability_kind, "0x00000001")

  def test_the_probe_is_paid_once_per_field_not_once_per_capture(self):
    _, probes = run_discovery_capture()
    self.assertEqual(probes, len(wire.OPTIONAL_DISCOVERY_FIELDS))
    _, again = run_discovery_capture(reset=False)
    self.assertEqual(again, 0)

  def test_a_probe_that_cannot_run_drops_the_column(self):
    # Losing one optional column costs a line of evidence. Keeping a field this
    # tshark might reject costs every capture.
    with fake_tshark(probe_raises=OSError("tshark vanished")):
      layout = wire.discovery_fields("/usr/bin/tshark")
    self.assertNotIn(RELEASE_STRING, [field for field, _ in layout])


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
    # And it is attributed to the participant that advertised it, so a caller
    # can say which peer is on which version rather than only that some peer
    # was. The 0x0101 participant contributes no pair.
    self.assertEqual(summary["fastdds_participant_versions"],
                     [["010f00000000000000000001", "3.6.2.0"]])
    self.assertFalse(summary["complete"])


def pdml_parameter(identifier, data):
  """One RTPS parameter node, nested the way tshark's PDML writer nests it."""
  return (f'<field name="" show="param" value="">'
          f'<field name="rtps.param.id" show="{identifier}"/>'
          f'<field name="rtps.param.length" show="4"/>'
          f'<field name="rtps.parameter_data" show="raw" value="{data}"/>'
          f'</field>')


def pdml(*messages):
  """A PDML document of one packet, carrying `(prefix, vendor, params)` each.

  Several messages in one packet is the coalesced-frame case: attribution has
  to follow document order rather than assuming one participant per packet.
  """
  body = ""
  for prefix, vendor, parameters in messages:
    body += (f'<field name="rtps.guidPrefix.src" show="{prefix}"/>'
             f'<field name="rtps.vendorId" show="{vendor}"/>'
             + "".join(parameters))
  return f'<pdml><packet><proto name="rtps">{body}</proto></packet></pdml>'


class TestProductVersionFromParameterBytes(unittest.TestCase):
  """WIRE-1: the version Wireshark declines to name for a non-RTI vendor.

  Wireshark decodes `rtps.param.product_version.*` only for RTI's `0x0101`.
  The identical PID from eProsima's `0x010f` dissects as `Unknown (0x8000)`,
  so the bytes are in the capture while the named columns are empty.
  """

  FASTDDS = "01:0f:65:91:01:00:df:ea:00:00:00:00"
  CONNEXT = "01:01:b5:86:41:e6:1a:b8:2e:53:a4:dd"

  def test_the_version_is_read_from_the_parameter_data(self):
    document = pdml((self.FASTDDS, "0x010f",
                     [pdml_parameter("0x8000", "03060200")]))
    self.assertEqual(wire.product_versions_from_pdml(document),
                     [("010f65910100dfea00000000", "3.6.2.0")])

  def test_another_vendors_version_is_not_a_fastdds_one(self):
    # The report says "Fast DDS versions advertised", so RTI's own version
    # through the same PID must not appear under it.
    document = pdml((self.CONNEXT, "0x0101",
                     [pdml_parameter("0x8000", "07070000")]))
    self.assertEqual(wire.product_versions_from_pdml(document), [])

  def test_each_message_in_a_coalesced_frame_keeps_its_own_prefix(self):
    document = pdml(
        (self.FASTDDS, "0x010f", [pdml_parameter("0x8000", "03060200")]),
        ("01:0f:00:00:00:00:00:00:00:00:00:02", "0x010f",
         [pdml_parameter("0x8000", "02:14:00:00".replace(":", ""))]))
    self.assertEqual(wire.product_versions_from_pdml(document),
                     [("010f00000000000000000002", "2.20.0.0"),
                      ("010f65910100dfea00000000", "3.6.2.0")])

  def test_another_parameter_is_not_mistaken_for_a_version(self):
    document = pdml((self.FASTDDS, "0x010f",
                     [pdml_parameter("0x8007", "deadbeef"),
                      pdml_parameter("0x8000", "03060200")]))
    self.assertEqual([version for _, version
                      in wire.product_versions_from_pdml(document)],
                     ["3.6.2.0"])

  def test_parameter_data_of_the_wrong_size_claims_nothing(self):
    document = pdml((self.FASTDDS, "0x010f",
                     [pdml_parameter("0x8000", "0306")]))
    self.assertEqual(wire.product_versions_from_pdml(document), [])

  def test_unreadable_parameter_data_claims_nothing(self):
    document = pdml((self.FASTDDS, "0x010f",
                     [pdml_parameter("0x8000", "zzzzzzzz")]))
    self.assertEqual(wire.product_versions_from_pdml(document), [])

  def test_a_document_that_is_not_pdml_claims_nothing(self):
    self.assertEqual(wire.product_versions_from_pdml("not xml <"), [])

  def test_a_failed_tshark_run_claims_nothing_rather_than_raising(self):
    def fake_run(command, **kwargs):
      return subprocess.CompletedProcess(command, 2, stdout="", stderr="boom")

    original_run = wire.subprocess.run
    wire.subprocess.run = fake_run
    try:
      self.assertEqual(
          wire.read_product_versions("capture.pcapng",
                                     tshark_path="/usr/bin/tshark"), [])
    finally:
      wire.subprocess.run = original_run

  def test_the_pass_is_narrowed_to_frames_carrying_the_parameter(self):
    # PDML renders the whole protocol tree, so an unfiltered pass would read a
    # discovery capture of any size as XML for nothing.
    captured = {}

    def fake_run(command, **kwargs):
      captured["command"] = command
      return subprocess.CompletedProcess(command, 0, stdout="<pdml/>", stderr="")

    original_run = wire.subprocess.run
    wire.subprocess.run = fake_run
    try:
      wire.read_product_versions("capture.pcapng", tshark_path="/usr/bin/tshark")
    finally:
      wire.subprocess.run = original_run
    self.assertIn("-T", captured["command"])
    self.assertIn("pdml", captured["command"])
    self.assertIn(f"rtps.param.id == {wire.PRODUCT_VERSION_PID}",
                  captured["command"])

  def test_the_summary_merges_the_two_sources_without_repeating_itself(self):
    # A Wireshark that does name the subfields must agree with itself rather
    # than report the same peer twice.
    prefix = "010f65910100dfea00000000"
    observation = wire.parse_discovery_fields(discovery_line(
        guid_prefix=prefix, vendor_id="0x010f", product_version_major="3",
        product_version_minor="6", product_version_release="2",
        product_version_revision="0", builtin_endpoint_set="0x00000c3f"))
    summary = wire.summarize_discovery(
        [observation], "sample.pcapng",
        participant_versions=[(prefix, "3.6.2.0")])
    self.assertEqual(summary["fastdds_product_versions"], ["3.6.2.0"])
    self.assertEqual(summary["fastdds_participant_versions"],
                     [[prefix, "3.6.2.0"]])


class TestFastDdsProductVersions(unittest.TestCase):
  """M2: what a version reports when the capture carried only part of one.

  `zip` truncated to its shortest input, so one absent subfield discarded the
  whole version - major and minor included - and subfields of unequal length
  paired survivors into a version that was never advertised.
  """

  def versions(self, **values):
    values.setdefault("vendor_id", "0x010f")
    return wire._fastdds_product_versions(
        wire.parse_discovery_fields(discovery_line(**values)))

  def test_a_complete_version_is_unchanged(self):
    self.assertEqual(self.versions(
        product_version_major="3", product_version_minor="6",
        product_version_release="2", product_version_revision="0"), ["3.6.2.0"])

  def test_an_absent_release_keeps_the_major_and_minor_that_were_readable(self):
    self.assertEqual(self.versions(
        product_version_major="3", product_version_minor="6",
        product_version_revision="0"), ["3.6.x.0"])

  def test_everything_after_the_minor_can_be_unknown(self):
    self.assertEqual(self.versions(
        product_version_major="3", product_version_minor="6"), ["3.6.x.x"])

  def test_the_release_string_stands_in_for_the_numeric_column(self):
    # The dissector renders the one release octet under either name depending
    # on the build, so the string form answers the same question.
    self.assertEqual(self.versions(
        product_version_major="3", product_version_minor="6",
        product_version_release_string="2", product_version_revision="0"),
        ["3.6.2.0"])

  def test_a_short_column_is_unknown_rather_than_mispaired(self):
    # Two participants' PIDs coalesced into one frame, one release octet
    # between them: pairing by position would hand the second participant the
    # first's release, and truncating would discard the second entirely.
    self.assertEqual(self.versions(
        product_version_major="3,2", product_version_minor="6,14",
        product_version_release="2", product_version_revision="0,1"),
        ["3.6.x.0", "2.14.x.1"])

  def test_nothing_is_claimed_when_the_major_and_minor_cannot_be_paired(self):
    self.assertEqual(self.versions(
        product_version_major="3,2", product_version_minor="6",
        product_version_release="2,0"), [])

  def test_a_version_with_no_major_is_no_version(self):
    self.assertEqual(self.versions(
        product_version_release="2", product_version_revision="0"), [])

  def test_only_fastdds_advertises_one(self):
    self.assertEqual(self.versions(
        vendor_id="0x0101", product_version_major="7",
        product_version_minor="7"), [])


if __name__ == "__main__":
  unittest.main()
