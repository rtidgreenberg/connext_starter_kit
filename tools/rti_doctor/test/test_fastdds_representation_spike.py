"""Cross-vendor DATA_REPRESENTATION spike: what a Fast DDS writer advertises.

`test_data_representation_spike.py` settled this for Connext and left one
question open, which is the whole reason the Q3 verdict is still undecided: a
Connext writer that advertises an EMPTY representation sequence means XCDR1, but
"empty" is a wire state, not a vendor-independent meaning. The README's own
Cyclone note says an unspecified policy there can resolve to XCDR2 - the
opposite conclusion from the same bytes - and rti_doctor is pointed at Fast DDS
far more often than at Cyclone.

So this asks the same questions of a Fast DDS peer:

  * What does a Fast DDS writer advertise in discovery when the application
    never sets DATA_REPRESENTATION? (`--representation default`, which leaves
    `DATAWRITER_QOS_DEFAULT` untouched rather than setting it to whatever the
    default resolves to - setting it explicitly is what hides the answer.)
  * Does it advertise XCDR1 concretely, or omit the PID the way Connext does?
  * For each of those, does a Connext reader actually match it - and does
    rti_doctor's verdict agree with that?

The middleware is the oracle again: `subscription_matched_status` and
`requested_incompatible_qos_status` on a real Connext reader, against
`qos_match.compare_endpoints` over the same pair as rti_doctor discovered it.

Vendor tier: needs Docker and the Fast DDS image, plus a Connext license.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)
sys.path.insert(0, HERE)  # noqa: E402
import domains  # noqa: E402

FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")

try:
  import rti.connextdds as dds
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False

if CONNEXT_AVAILABLE:
  from rti_doctor import compat, discovery, paths, records
  from rti_doctor.checks import qos_match

#: Matches `test/vendors/fastdds/final/Sample.idl`, which is what the fixture
#: publishes. A type mismatch would produce a no-match for reasons that have
#: nothing to do with representation, so the schema has to be exact.
def _sample_type():
  sample = dds.StructType("DoctorExtensibility::Sample")
  sample.extensibility_kind = dds.ExtensibilityKind.FINAL
  sample.add_member(dds.Member("index", dds.Uint32Type(), id=0))
  sample.add_member(dds.Member("message", dds.StringType(), id=1))
  return sample


#: How the Fast DDS fixture is asked to configure its writer. "default" needs
#: the fixture built from the 2026-08-11 source; older images reject it, and
#: this suite reports that rather than failing.
WRITER_MODES = ("default", "xcdr1", "xcdr2")

#: What the Connext reader requests. `None` leaves the policy alone.
READER_MODES = (("default", None), ("xcdr1_only", ("XCDR",)),
                ("xcdr2_only", ("XCDR2",)))

#: The writer has to outlive its own discovery plus every reader observed
#: against it, so this is sized from the two waits below rather than guessed.
WRITER_SECONDS = 75

#: Discovering a Fast DDS writer costs container startup, Fast DDS
#: initialization and an SEDP announcement, which together run well past the
#: few seconds a Connext-to-Connext pair needs. Too short a wait here does not
#: fail honestly - it records "not discovered", which reads as an interop
#: result rather than as an impatient test.
WRITER_DISCOVERY_WAIT = 30.0

#: Cross-vendor matching after both endpoints exist.
MATCH_WAIT = 12.0


def _domain():
  return domains.for_suite("test_fastdds_representation_spike")


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
@unittest.skipUnless(shutil.which("docker"), "docker is not installed")
class TestFastDdsRepresentationEvidence(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    available = subprocess.run(["docker", "image", "inspect", FASTDDS_IMAGE],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False)
    if available.returncode:
      raise unittest.SkipTest(f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable")
    compat.configure_rti_environment()
    cls.domain = _domain()
    cls.observations = []
    cls.unsupported_modes = []
    for mode in WRITER_MODES:
      cls._sweep_writer(mode)

  @classmethod
  def tearDownClass(cls):
    if not cls.observations:
      return
    directory = paths.test_output_path("rti_doctor_spikes")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "fastdds_representation_matrix.json")
    with open(path, "w", encoding="utf-8") as handle:
      json.dump(cls.observations, handle, indent=2, sort_keys=True)
    print(f"\nFast DDS DATA_REPRESENTATION evidence written to {path}")
    print(cls._matrix_text())
    if cls.unsupported_modes:
      print(f"\nfixture rejected these writer modes (rebuild the image): "
            f"{', '.join(cls.unsupported_modes)}")

  @classmethod
  def _matrix_text(cls):
    header = (f"{'fastdds writer':15} {'connext reader':15} {'advertised':16} "
              f"{'matched':8} {'incompatible policy':22} doctor")
    rows = [header, "-" * len(header)]
    for item in cls.observations:
      rows.append(
          f"{item['writer_mode']:15} {item['reader_mode']:15} "
          f"{item['advertised']:16} {str(item['matched']):8} "
          f"{str(item['incompatible_policy']):22} {item['doctor_verdict']}")
    return "\n".join(rows)

  # --- Observation -----------------------------------------------------------

  @classmethod
  def _writer_command(cls, topic, mode):
    return ["docker", "run", "--rm", "--network", "host", "--entrypoint",
            "/doctor-extensibility-build/doctor_fastdds_final",
            "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
            "--domain", str(cls.domain), "--topic", topic, "--role", "writer",
            "--extensibility", "final", "--representation", mode,
            "--duration", str(WRITER_SECONDS)]

  @classmethod
  def _sweep_writer(cls, mode):
    """One Fast DDS writer, then each Connext reader against it in turn.

    Readers run sequentially inside one writer's lifetime rather than a fresh
    docker run per pair: three containers instead of nine, and only one reader
    is ever on the topic, so the registry record that gets compared is
    unambiguous.
    """
    topic = f"SpikeFastDdsRepr_{mode}_{uuid.uuid4().hex[:8]}"
    registry = discovery.DiscoveryRegistry(type_wait=4.0)
    observer, _settings = discovery.create_participant(
        cls.domain, name="RTI DOCTOR FASTDDS REPR SPIKE", registry=registry)
    writer = subprocess.Popen(cls._writer_command(topic, mode), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
      deadline = time.monotonic() + WRITER_DISCOVERY_WAIT
      discovered_writer = None
      while time.monotonic() < deadline:
        discovery.refresh_participants(observer, registry)
        discovered_writer = registry.find_writer(topic)
        if discovered_writer is not None:
          break
        if writer.poll() is not None:
          break
        time.sleep(0.25)

      if discovered_writer is None:
        # Stop it before reading its output: it is mid-run with a 75-second
        # duration, so communicate() alone would block until then and report a
        # timeout instead of the reason discovery failed.
        if writer.poll() is None:
          writer.terminate()
        stdout, stderr = writer.communicate(timeout=15)
        if "required: --domain" in stderr:
          # The image predates `--representation default`; say so rather than
          # reporting "not discovered", which reads as an interop result.
          cls.unsupported_modes.append(mode)
          return
        raise AssertionError(
            f"Fast DDS writer for mode '{mode}' was never discovered\n"
            f"stderr={stderr}\nstdout={stdout}")

      for reader_mode, reader_ids in READER_MODES:
        cls._observe_reader(registry, observer, topic, mode, reader_mode,
                            reader_ids)
    finally:
      if writer.poll() is None:
        writer.terminate()
        try:
          writer.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
          writer.kill()
      observer.close()

  @classmethod
  def _observe_reader(cls, registry, observer, topic, writer_mode, reader_mode,
                      reader_ids):
    participant = dds.DomainParticipant(cls.domain)
    try:
      reader_topic = dds.DynamicData.Topic(participant, topic, _sample_type())
      qos = participant.implicit_subscriber.default_datareader_qos
      if reader_ids is not None:
        qos.data_representation.value = [
            getattr(dds.DataRepresentation, name) for name in reader_ids]
      reader = dds.DynamicData.DataReader(
          participant.implicit_subscriber, reader_topic, qos)

      deadline = time.monotonic() + MATCH_WAIT
      matched = False
      while time.monotonic() < deadline:
        discovery.refresh_participants(observer, registry)
        matched = reader.subscription_matched_status.current_count > 0
        if matched and cls._discovered_reader(registry, topic) is not None:
          break
        time.sleep(0.25)

      status = reader.requested_incompatible_qos_status
      incompatible_policy = (
          getattr(status.last_policy, "__name__", str(status.last_policy))
          if status.total_count else None)
      discovered_writer = registry.find_writer(topic)
      discovered_reader = cls._discovered_reader(registry, topic)

      doctor = "not evaluated - endpoints not both discovered"
      unevaluated = []
      if discovered_writer is not None and discovered_reader is not None:
        mismatches, unevaluated_records = qos_match.compare_endpoints(
            discovered_writer, discovered_reader)
        policies = [item["policy"] for item in mismatches]
        unevaluated = [item["policy"] for item in unevaluated_records]
        doctor = ("incompatible: " + ", ".join(policies) if policies
                  else "compatible")

      cls.observations.append({
          "writer_mode": writer_mode,
          "reader_mode": reader_mode,
          "advertised": (records.representation_text(discovered_writer.representation)
                         if discovered_writer is not None else "not discovered"),
          "advertised_reader": (
              records.representation_text(discovered_reader.representation)
              if discovered_reader is not None else "not discovered"),
          "matched": matched,
          "incompatible_policy": incompatible_policy,
          "doctor_verdict": doctor,
          "doctor_unevaluated": unevaluated,
      })
      reader.close()
      reader_topic.close()
    finally:
      participant.close()

  @classmethod
  def _discovered_reader(cls, registry, topic):
    return next((item for item in registry.endpoint_list()
                 if item.topic_name == topic and not item.is_writer), None)

  def _rows(self, **fields):
    return [item for item in self.observations
            if all(item[key] == value for key, value in fields.items())]

  # --- What the sweep established --------------------------------------------

  def test_the_sweep_observed_a_fastdds_writer(self):
    """Guard the evidence: a sweep that discovered nothing proves nothing."""
    self.assertTrue(self.observations,
                    "no Fast DDS writer was discovered at all; the rest of this "
                    "suite would be asserting about an empty matrix")
    self.assertTrue(any(item["matched"] for item in self.observations),
                    "no Connext reader matched any Fast DDS writer, so nothing "
                    "here is evidence about representation:\n"
                    + self._matrix_text())

  def test_what_a_default_fastdds_writer_advertises(self):
    """REP-1's core question, and the reason the Q3 verdict is undecided.

    Records the answer rather than asserting a particular one - that is the
    measurement. What it does assert is that the fixture supports the mode at
    all, because a silently-skipped question looks exactly like an answered one.
    """
    self.assertNotIn("default", self.unsupported_modes,
                     "the Fast DDS image predates `--representation default`; "
                     "rebuild it with test/vendors/fastdds/build_image.sh")
    rows = self._rows(writer_mode="default")
    self.assertTrue(rows)
    advertised = {item["advertised"] for item in rows}
    self.assertEqual(len(advertised), 1, rows)
    print(f"\nFast DDS writer with no DATA_REPRESENTATION set advertises: "
          f"{advertised.pop()!r}")

  def test_an_explicit_fastdds_representation_is_advertised(self):
    """Whether Fast DDS omits the PID for XCDR1 the way Connext does.

    This is the half that decides whether "empty means XCDR1" is a
    vendor-independent reading or a Connext-only one.
    """
    for mode in ("xcdr1", "xcdr2"):
      if mode in self.unsupported_modes:
        continue
      rows = self._rows(writer_mode=mode)
      self.assertTrue(rows, f"no rows for writer mode {mode}")
      for row in rows:
        self.assertNotEqual(row["advertised"], "unreadable", row)

  def test_the_tool_agrees_with_the_middleware_cross_vendor(self):
    """The Q3 question in the direction that matters for a Fast DDS engagement.

    Was an expected failure until Q3's verdict was decided on 2026-08-12. It
    failed on exactly one row: a Fast DDS writer that advertises nothing against
    a Connext reader requesting XCDR2 only, which Connext refuses while naming
    DataRepresentation and rti_doctor called `compatible` at exit 0.

    That row is now an ERROR, because `qos_match` resolves an empty writer
    advertisement to XCDR1 for the vendors where that meaning has been measured
    - Fast DDS among them, by this very suite. The assertion is unchanged; only
    the product moved. It stays here as the regression guard for the whole
    matrix, in both directions and every representation mode.
    """
    disagreements = [
        (item["writer_mode"], item["reader_mode"], item["advertised"],
         item["matched"], item["doctor_verdict"])
        for item in self.observations
        if (item["matched"] and item["doctor_verdict"].startswith("incompatible"))
        or (not item["matched"] and item["doctor_verdict"] == "compatible")]
    self.assertEqual(
        disagreements, [],
        "rti_doctor and Connext disagree about these cross-vendor pairs:\n"
        + self._matrix_text())


if __name__ == "__main__":
  unittest.main()
