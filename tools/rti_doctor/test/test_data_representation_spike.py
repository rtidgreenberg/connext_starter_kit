"""DATA_REPRESENTATION spike: what a writer advertises vs what actually matches.

Written to settle the open half of Q3 in `docs/CODE_REVIEW_2026-08-07.md`. The
tool skips its only XTypes RxO rule whenever either side's advertised
representation list is empty, and `records.py` records the verified observation
that a Connext 7.7.0 writer on the *default* policy advertises an empty sequence
in discovery. The reporting half of that is closed - the pair's finding now says
DATA_REPRESENTATION was not evaluated - but the verdict is still
`qos.compatible` / Severity.OK, and nobody has established whether that verdict
is right.

Two different questions were being conflated, and this suite separates them:

  * **What is advertised.** The writer's own QoS and what a remote observer reads
    out of discovery are not the same value. A default `DataWriterQos` carries
    `data_representation.value == [-1]` (AUTO) locally; the claim under test is
    that a remote sees an empty sequence.
  * **What actually matches.** Whether Connext itself matches such a writer with
    a reader that requests XCDR2 only, and if not, whether it says
    DATA_REPRESENTATION is the reason.

The middleware is the oracle. `test_the_tool_agrees_with_the_middleware` compares
rti_doctor's verdict for each pair against whether Connext matched it, and **a
failure there is the Q3 evidence, not a flake**: it means the tool called a pair
compatible that the middleware refused, or the reverse. Read the matrix in the
failure message, or the artifact this suite writes to `test_output/`, and record
the outcome as the Q3 decision.

Everything here uses one participant per role on one deterministic domain, so it
needs a license but no Docker and no fixture process.
"""

import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)

# domains lives beside this file. Without this the import resolved only when
# some OTHER test module had already put the test directory on sys.path.
sys.path.insert(0, HERE)  # noqa: E402
import domains  # noqa: E402

try:
  import rti.connextdds as dds
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False

if CONNEXT_AVAILABLE:
  from rti_doctor import compat, discovery, paths, records
  from rti_doctor.checks import qos_match

#: How long to let discovery settle before reading matched counts. Matching is
#: asynchronous, so reading too early records "did not match" for every pair and
#: the whole matrix becomes a fabricated result.
MATCH_WAIT = 6.0


def _domain():
  return domains.for_suite("test_data_representation_spike")


def _final_type(name="SpikeFinal"):
  struct = dds.StructType(name)
  struct.extensibility_kind = dds.ExtensibilityKind.FINAL
  struct.add_member(dds.Member("id", dds.Int32Type(), is_key=True))
  struct.add_member(dds.Member("value", dds.Float64Type()))
  return struct


def _mutable_type(name="SpikeMutable"):
  """XCDR2 is required to encode a mutable type, so it is the interesting case."""
  struct = dds.StructType(name)
  struct.extensibility_kind = dds.ExtensibilityKind.MUTABLE
  struct.add_member(dds.Member("id", dds.Int32Type(), is_key=True))
  struct.add_member(dds.Member("value", dds.Float64Type()))
  return struct


#: The writer/reader configurations the Q3 verdict turns on. `None` means "leave
#: the policy alone", i.e. exactly what an application that never set it gets.
WRITER_QOS = (
    ("default", None),
    ("xcdr1", ("XCDR",)),
    ("xcdr2", ("XCDR2",)),
    ("xcdr1_then_xcdr2", ("XCDR", "XCDR2")),
)
READER_QOS = (
    ("default", None),
    ("xcdr1_only", ("XCDR",)),
    ("xcdr2_only", ("XCDR2",)),
)


def _representation(names):
  return [getattr(dds.DataRepresentation, name) for name in names]


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
class TestDataRepresentationEvidence(unittest.TestCase):
  """One participant per role; every pair observed on the same live domain."""

  @classmethod
  def setUpClass(cls):
    compat.configure_rti_environment()
    cls.domain = _domain()
    cls.writer_participant = dds.DomainParticipant(cls.domain)
    cls.reader_participant = dds.DomainParticipant(cls.domain)
    # A third participant, driven through the tool's own discovery registry, is
    # what a remote observer sees - which is the only thing rti_doctor ever gets
    # to read, and is not the same as either endpoint's local QoS.
    cls.registry = discovery.DiscoveryRegistry(type_wait=2.0)
    cls.observer, _settings = discovery.create_participant(
        cls.domain, name="RTI DOCTOR REPR SPIKE", registry=cls.registry)
    cls.observations = []
    # Measured once, here, rather than per test. Each test used to re-run the
    # sweep, which quadrupled the runtime and wrote the same rows four times
    # into the artifact - and an artifact with duplicate rows invites the reader
    # to think two runs disagreed when they were one run recorded twice.
    cls._sweep_once("final", _final_type())
    cls._sweep_once("mutable", _mutable_type())

  @classmethod
  def tearDownClass(cls):
    for participant in (cls.writer_participant, cls.reader_participant,
                        cls.observer):
      try:
        participant.close()
      except Exception:  # pragma: no cover - teardown is best effort
        pass
    cls._write_artifact()

  @classmethod
  def _write_artifact(cls):
    if not cls.observations:
      return
    directory = paths.test_output_path("rti_doctor_spikes")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "data_representation_matrix.json")
    with open(path, "w", encoding="utf-8") as handle:
      json.dump(cls.observations, handle, indent=2, sort_keys=True)
    print(f"\nDATA_REPRESENTATION evidence written to {path}")
    print(cls._matrix_text())

  @classmethod
  def _matrix_text(cls):
    header = (f"{'type':9} {'writer qos':17} {'reader qos':11} "
              f"{'advertised':23} {'matched':8} {'samples':8} "
              f"{'incompatible policy':22} doctor")
    rows = [header, "-" * len(header)]
    for item in cls.observations:
      rows.append(
          f"{item['extensibility']:9} {item['writer_qos']:17} "
          f"{item['reader_qos']:11} {item['advertised']:23} "
          f"{str(item['matched']):8} {str(item['samples_received']):8} "
          f"{str(item['incompatible_policy']):22} {item['doctor_verdict']}")
    return "\n".join(rows)

  # --- Observation -----------------------------------------------------------

  @classmethod
  def _discovered_reader(cls, topic_name):
    return next((item for item in cls.registry.endpoint_list()
                 if item.topic_name == topic_name and not item.is_writer), None)

  @classmethod
  def _sweep_once(cls, extensibility, struct):
    for writer_name, writer_ids in WRITER_QOS:
      for reader_name, reader_ids in READER_QOS:
        cls._observe(extensibility, struct, writer_name, writer_ids,
                     reader_name, reader_ids)

  @classmethod
  def _observe(cls, extensibility, struct, writer_name, writer_ids,
               reader_name, reader_ids):
    """One pair, from four angles: advertised, matched, delivered, and doctor's."""
    topic_name = f"SpikeRepr_{extensibility}_{writer_name}_{reader_name}"
    writer_topic = dds.DynamicData.Topic(cls.writer_participant, topic_name, struct)
    reader_topic = dds.DynamicData.Topic(cls.reader_participant, topic_name, struct)

    writer_qos = cls.writer_participant.implicit_publisher.default_datawriter_qos
    if writer_ids is not None:
      writer_qos.data_representation.value = _representation(writer_ids)
    reader_qos = cls.reader_participant.implicit_subscriber.default_datareader_qos
    if reader_ids is not None:
      reader_qos.data_representation.value = _representation(reader_ids)

    try:
      writer = dds.DynamicData.DataWriter(
          cls.writer_participant.implicit_publisher, writer_topic, writer_qos)
    except dds.Error as error:
      # Not a test failure: a QoS Connext refuses to create locally is evidence
      # about what a Connext writer can advertise at all, which is half of what
      # the DATA_REPRESENTATION rule assumes about its inputs.
      observation = {
          "extensibility": extensibility,
          "writer_qos": writer_name,
          "reader_qos": reader_name,
          "local_writer_value": list(writer_qos.data_representation.value),
          "local_reader_value": list(reader_qos.data_representation.value),
          "advertised": "writer rejected locally",
          "advertised_reader": "n/a",
          "matched": False,
          "samples_received": 0,
          "incompatible_policy": None,
          "doctor_verdict": "not evaluated - writer could not be created",
          "doctor_unevaluated": [],
          "writer_create_error": str(error),
      }
      cls.observations.append(observation)
      writer_topic.close()
      reader_topic.close()
      return observation

    reader = dds.DynamicData.DataReader(
        cls.reader_participant.implicit_subscriber, reader_topic, reader_qos)
    try:
      # Wait for BOTH endpoints, not just the writer. Breaking out as soon as
      # the writer was discovered recorded "endpoints not both discovered" for
      # the first pairs in a run - which reads as an absent verdict rather than
      # as a race, and silently removed those rows from the comparison the
      # whole suite exists to make.
      deadline = time.monotonic() + MATCH_WAIT
      matched = False
      while time.monotonic() < deadline:
        discovery.refresh_participants(cls.observer, cls.registry)
        matched = writer.publication_matched_status.current_count > 0
        if (matched and cls.registry.find_writer(topic_name) is not None
            and cls._discovered_reader(topic_name) is not None):
          break
        time.sleep(0.25)

      # Matching is necessary but not sufficient: two endpoints can match and
      # still fail to deliver if the encoding is not one the reader can decode.
      samples_received = 0
      if matched:
        sample = dds.DynamicData(struct)
        sample["id"] = 1
        sample["value"] = 2.5
        writer.write(sample)
        delivery_deadline = time.monotonic() + 2.0
        while time.monotonic() < delivery_deadline:
          samples_received = len([item for item in reader.take() if item.info.valid])
          if samples_received:
            break
          time.sleep(0.1)

      status = reader.requested_incompatible_qos_status
      # `last_policy` is the policy CLASS, so str() renders it as
      # "<class 'rti.connextdds.DataRepresentation'>" - unreadable in the
      # artifact this suite exists to produce.
      incompatible_policy = (
          getattr(status.last_policy, "__name__", str(status.last_policy))
          if status.total_count else None)
      discovered_writer = cls.registry.find_writer(topic_name)
      discovered_reader = cls._discovered_reader(topic_name)
      advertised = (records.representation_text(discovered_writer.representation)
                    if discovered_writer is not None else "not discovered")
      advertised_reader = (
          records.representation_text(discovered_reader.representation)
          if discovered_reader is not None else "not discovered")

      doctor = "not evaluated - endpoints not both discovered"
      unevaluated_policies = []
      if discovered_writer is not None and discovered_reader is not None:
        mismatches, unevaluated = qos_match.compare_endpoints(
            discovered_writer, discovered_reader)
        policies = [item["policy"] for item in mismatches]
        unevaluated_policies = [item["policy"] for item in unevaluated]
        doctor = ("incompatible: " + ", ".join(policies) if policies
                  else "compatible")

      observation = {
          "extensibility": extensibility,
          "writer_qos": writer_name,
          "reader_qos": reader_name,
          "local_writer_value": list(writer_qos.data_representation.value),
          "local_reader_value": list(reader_qos.data_representation.value),
          "advertised": advertised,
          "advertised_reader": advertised_reader,
          "matched": matched,
          "samples_received": samples_received,
          "incompatible_policy": incompatible_policy,
          "doctor_verdict": doctor,
          "doctor_unevaluated": unevaluated_policies,
      }
      cls.observations.append(observation)
      return observation
    finally:
      reader.close()
      writer.close()
      reader_topic.close()
      writer_topic.close()

  def _rows(self, **fields):
    return [item for item in self.observations
            if all(item[key] == value for key, value in fields.items())]

  # --- What the sweep established --------------------------------------------

  def test_the_sweep_observed_something(self):
    """Guard the evidence itself: a sweep that matched nothing proves nothing.

    Without this, a license problem or a busy domain produces a matrix of
    "did not match" that reads exactly like a real incompatibility everywhere.
    """
    self.assertEqual(len(self.observations),
                     2 * len(WRITER_QOS) * len(READER_QOS))
    self.assertTrue(
        any(item["matched"] for item in self.observations),
        "no pair matched at all, so nothing here is evidence about "
        "DATA_REPRESENTATION - check the domain and the license first:\n"
        + self._matrix_text())

  def test_a_default_writer_advertises_nothing_and_a_default_reader_advertises_xcdr1(self):
    """Q3's premise, and the asymmetry nobody had noticed.

    A default writer holds AUTO locally and advertises an EMPTY sequence, so
    the check declines. A default reader holds the same AUTO and advertises
    XCDR1 - concretely - so the reader side is always evaluable. The gap the
    check falls into is therefore writer-side only.
    """
    for row in self._rows(writer_qos="default"):
      self.assertEqual(row["local_writer_value"], [-1])
      self.assertEqual(row["advertised"], "not advertised", row)
    # Only where a writer existed to discover the pair through: the rejected
    # two-value rows never created a reader, and asserting over them would be
    # asserting about an endpoint that was never on the domain.
    for row in self._rows(reader_qos="default"):
      self.assertEqual(row["local_reader_value"], [-1])
      if row["advertised"] != "writer rejected locally":
        self.assertEqual(row["advertised_reader"], "XCDR1", row)

  def test_an_explicit_xcdr1_writer_is_indistinguishable_from_a_default_one(self):
    """Connext omits the PID when the effective representation is XCDR1.

    This is what licenses reading an empty advertisement as XCDR1 rather than
    as "unknown": the two configurations that produce it both mean XCDR1, and
    the matching behaviour below is identical for both.
    """
    for extensibility in ("final", "mutable"):
      for reader_qos, _ in READER_QOS:
        default_row = self._rows(extensibility=extensibility,
                                 writer_qos="default", reader_qos=reader_qos)[0]
        explicit_row = self._rows(extensibility=extensibility,
                                  writer_qos="xcdr1", reader_qos=reader_qos)[0]
        self.assertEqual(explicit_row["advertised"], "not advertised")
        self.assertEqual(explicit_row["matched"], default_row["matched"])
        self.assertEqual(explicit_row["samples_received"],
                         default_row["samples_received"])

  def test_an_empty_advertisement_behaves_as_xcdr1_on_the_wire(self):
    """The verdict question: what does a non-advertising writer actually do?

    It matches XCDR1 readers and is refused by XCDR2-only readers, with Connext
    naming DATA_REPRESENTATION as the incompatible policy. So an empty
    advertisement is not "no information" - it is XCDR1, and a reader that does
    not accept XCDR1 will never receive from it.
    """
    for writer_qos in ("default", "xcdr1"):
      for extensibility in ("final", "mutable"):
        accepted = self._rows(extensibility=extensibility,
                              writer_qos=writer_qos, reader_qos="xcdr1_only")[0]
        refused = self._rows(extensibility=extensibility,
                             writer_qos=writer_qos, reader_qos="xcdr2_only")[0]
        self.assertTrue(accepted["matched"], accepted)
        self.assertEqual(accepted["samples_received"], 1, accepted)
        self.assertFalse(refused["matched"], refused)
        self.assertEqual(refused["incompatible_policy"], "DataRepresentation",
                         refused)

  def test_a_connext_writer_cannot_offer_more_than_one_representation(self):
    """The rule's comment assumes a writer list; Connext refuses to create one.

    `qos_match` reasons about "the first entry in the writer's list", which is
    still right for a foreign vendor, but no Connext writer can produce that
    input: the QoS is rejected locally.
    """
    rejected = self._rows(writer_qos="xcdr1_then_xcdr2")
    self.assertTrue(rejected)
    for row in rejected:
      self.assertEqual(row["advertised"], "writer rejected locally")
      self.assertIn("Failed to create DataWriter", row["writer_create_error"])

  def test_the_tool_is_right_when_the_writer_advertises(self):
    """The half of the rule that works, so a fix does not regress it."""
    for extensibility in ("final", "mutable"):
      for reader_qos in ("default", "xcdr1_only"):
        row = self._rows(extensibility=extensibility, writer_qos="xcdr2",
                         reader_qos=reader_qos)[0]
        self.assertFalse(row["matched"], row)
        self.assertEqual(row["doctor_verdict"],
                         "incompatible: DATA_REPRESENTATION", row)
      agreed = self._rows(extensibility=extensibility, writer_qos="xcdr2",
                          reader_qos="xcdr2_only")[0]
      self.assertTrue(agreed["matched"], agreed)
      self.assertEqual(agreed["doctor_verdict"], "compatible", agreed)

  @unittest.expectedFailure
  def test_the_tool_agrees_with_the_middleware(self):
    """Q3's verdict half, executable. Expected to fail until it is decided.

    This is not a skip: it runs every time, and `unittest` reports an
    *unexpected success* the day the verdict changes - which is the signal to
    delete this decorator rather than the test. What it currently proves is
    that rti_doctor reports `qos.compatible` (Severity.OK, exit 0) for pairs
    Connext refuses to match and blames DATA_REPRESENTATION for.

    Remove the decorator as part of the Q3 fix.
    """
    disagreements = [
        (item["extensibility"], item["writer_qos"], item["reader_qos"])
        for item in self.observations
        if (item["matched"] and item["doctor_verdict"].startswith("incompatible"))
        or (not item["matched"] and item["doctor_verdict"] == "compatible")]
    self.assertEqual(
        disagreements, [],
        "rti_doctor and Connext disagree about these pairs:\n"
        + self._matrix_text())


if __name__ == "__main__":
  unittest.main()
