"""Live spike: does ignoring a matched exclusive writer re-arbitrate ownership?

The probe normally ignores competing publications before creating its reader.
This experiment verifies the recovery path when a competing writer has already
matched: an EXCLUSIVE reader first accepts the higher-strength writer and drops
the lower-strength writer, then `ignore_datawriter(high.instance_handle)` is
called while the reader is still alive. The lower-strength writer must then
become accepted without recreating the reader.
"""

import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, TOOL_DIR)
sys.path.insert(0, HERE)

import domains  # noqa: E402

try:
  import rti.connextdds as dds
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False

if CONNEXT_AVAILABLE:
  from rti_doctor import compat

MATCH_WAIT = 6.0
SAMPLE_WAIT = 2.0


def _domain():
  return domains.for_suite("test_ownership_ignore_spike")


def _type():
  struct = dds.StructType("OwnershipIgnoreSpike")
  struct.add_member(dds.Member("id", dds.Int32Type(), is_key=True))
  struct.add_member(dds.Member("source", dds.StringType(32)))
  return struct


def _writer_qos(strength):
  qos = dds.DataWriterQos()
  qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
  qos.ownership_strength.value = strength
  return qos


def _reader_qos():
  qos = dds.DataReaderQos()
  qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
  return qos


def _sample(dynamic_type, source):
  sample = dds.DynamicData(dynamic_type)
  sample["id"] = 1
  sample["source"] = source
  return sample


def _take_sources(reader):
  return [sample.data["source"] for sample in reader.take() if sample.info.valid]


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
class TestOwnershipIgnoreSpike(unittest.TestCase):
  """Use separate participants so the ignored publication is genuinely remote."""

  @classmethod
  def setUpClass(cls):
    compat.configure_rti_environment()
    cls.high_participant = dds.DomainParticipant(_domain())
    cls.low_participant = dds.DomainParticipant(_domain())
    cls.reader_participant = dds.DomainParticipant(_domain())
    dynamic_type = _type()
    topic_name = "OwnershipIgnoreSpike"
    cls.high_writer = dds.DynamicData.DataWriter(
        cls.high_participant.implicit_publisher,
        dds.DynamicData.Topic(cls.high_participant, topic_name, dynamic_type),
        _writer_qos(10))
    cls.low_writer = dds.DynamicData.DataWriter(
        cls.low_participant.implicit_publisher,
        dds.DynamicData.Topic(cls.low_participant, topic_name, dynamic_type),
        _writer_qos(1))
    cls.reader = dds.DynamicData.DataReader(
        cls.reader_participant.implicit_subscriber,
        dds.DynamicData.Topic(cls.reader_participant, topic_name, dynamic_type),
        _reader_qos())
    cls.dynamic_type = dynamic_type

  @classmethod
  def tearDownClass(cls):
    for participant in (cls.reader_participant, cls.low_participant,
                        cls.high_participant):
      try:
        participant.close()
      except Exception:  # pragma: no cover - teardown is best effort
        pass

  def _wait_for(self, predicate, message):
    deadline = time.monotonic() + MATCH_WAIT
    while time.monotonic() < deadline:
      if predicate():
        return
      time.sleep(0.1)
    self.fail(message)

  def _wait_for_sources(self):
    deadline = time.monotonic() + SAMPLE_WAIT
    sources = []
    while time.monotonic() < deadline:
      sources.extend(_take_sources(self.reader))
      if sources:
        break
      time.sleep(0.05)
    return sources

  def test_ignoring_a_matched_stronger_writer_rearbitrates_ownership(self):
    self._wait_for(
        lambda: self.reader.subscription_matched_status.current_count == 2,
        "reader never matched both exclusive writers")

    self.high_writer.write(_sample(self.dynamic_type, "high-before-ignore"))
    self.assertIn("high-before-ignore", self._wait_for_sources())

    self.low_writer.write(_sample(self.dynamic_type, "low-before-ignore"))
    self.assertNotIn("low-before-ignore", self._wait_for_sources())

    self.reader_participant.ignore_datawriter(self.high_writer.instance_handle)
    self._wait_for(
        lambda: self.reader.subscription_matched_status.current_count == 1,
        "ignoring the high writer did not unmatch it from the existing reader")

    self.low_writer.write(_sample(self.dynamic_type, "low-after-ignore"))
    self.assertIn("low-after-ignore", self._wait_for_sources())
