"""End-to-end vendor tests: publisher -> rti_doctor -> tshark PCAP evidence.

These are intentionally separate from the normal live tests. They need both a
third-party runtime and packet-capture permission, and the Fast DDS test also
needs the current Docker image built by vendors/fastdds/build_image.sh.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import doctor_e2e  # noqa: E402

VENDORS_DIR = os.path.join(HERE, "vendors")
CYCLONE_FIXTURE = os.path.join(VENDORS_DIR, "cyclone_publisher.py")
CYCLONE_SUBSCRIBER = os.path.join(VENDORS_DIR, "cyclone_subscriber.py")
FASTDDS_DIR = os.path.join(VENDORS_DIR, "fastdds")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")
CAPTURE_INTERFACE = os.environ.get("RTI_DOCTOR_TEST_CAPTURE_INTERFACE", "any")
DOCTOR_SETTLE = 3
# Cyclone DDS's default RTPS port mapping cannot represent domains above 232.
# Keep this vendor-only range below that limit while avoiding the usual examples.
DOMAIN_BASE = 120


def _domain():
  return DOMAIN_BASE + random.randint(1, 100)


def _command_available(command):
  return shutil.which(command) is not None


class VendorWireE2E(unittest.TestCase):
  """Shared CLI-level assertions for a continuously publishing DDS vendor."""

  VENDOR = None
  TOPIC_PREFIX = "DoctorVendorWire"
  EXPECTED_ENCAPSULATION = None
  FIXED_DOMAIN = None
  FIXED_TOPIC = None

  @classmethod
  def setUpClass(cls):
    if cls.VENDOR is None:
      raise unittest.SkipTest("vendor E2E base class")
    if not _command_available("tshark"):
      raise unittest.SkipTest("tshark is not installed")
    cls.domain = cls.FIXED_DOMAIN if cls.FIXED_DOMAIN is not None else _domain()
    cls.topic = cls.FIXED_TOPIC or f"{cls.TOPIC_PREFIX}{cls.domain}"
    cls.publisher = cls.start_publisher()
    time.sleep(2.0)
    if cls.publisher.poll() is not None:
      _, stderr = cls.publisher.communicate()
      raise unittest.SkipTest(
          f"{cls.VENDOR} publisher exited before the test: {stderr.strip()}")

  @classmethod
  def tearDownClass(cls):
    publisher = getattr(cls, "publisher", None)
    if publisher is None:
      return
    publisher.terminate()
    try:
      publisher.wait(timeout=10)
    except subprocess.TimeoutExpired:
      publisher.kill()

  @classmethod
  def start_publisher(cls):
    raise NotImplementedError

  def run_doctor(self):
    command, environment = doctor_e2e.command(
        self.domain, self.topic, settle=DOCTOR_SETTLE, type_wait=5,
        probe_timeout=4, capture_interface=CAPTURE_INTERFACE)
    for attempt in range(3):
      completed = subprocess.run(
          command, text=True, capture_output=True, env=environment,
          timeout=40, check=False)
      if completed.returncode != 2 or attempt == 2:
        break
      time.sleep(1.0)
    self.assertNotEqual(completed.returncode, 2, completed.stderr)
    return doctor_e2e.parse_report(completed)

  def test_discovers_vendor_and_identifies_wire_representation(self):
    payload = self.run_doctor()
    self.assertIn("wire_observation", payload)
    evidence = payload["wire_observation"]
    self.assertNotIn("error", evidence, evidence.get("error"))
    self.assertGreater(evidence["packets"], 0, evidence)
    self.assertGreater(evidence["data_packets"] + evidence["data_fragments"], 0,
                       evidence)
    self.assertTrue(evidence["encapsulation_ids"],
                    "tshark saw RTPS user data but decoded no encapsulation ID")
    if self.EXPECTED_ENCAPSULATION is not None:
      self.assertIn(self.EXPECTED_ENCAPSULATION, evidence["encapsulation_ids"])
    for identifier in evidence["encapsulation_ids"]:
      self.assertRegex(identifier, r"^0x[0-9a-fA-F]{4}$")
    self.assertTrue(os.path.isfile(evidence["source"]), evidence["source"])


class TestCycloneWireE2E(VendorWireE2E):
  VENDOR = "Cyclone DDS"
  # This fixture leaves DataRepresentation unspecified. Its actual user DATA
  # is asserted from the PCAP, not inferred from discovery/type metadata.
  EXPECTED_ENCAPSULATION = "0x0001"

  @classmethod
  def start_publisher(cls):
    cls.reader = subprocess.Popen(
        [sys.executable, CYCLONE_SUBSCRIBER, "--domain", str(cls.domain),
         "--topic", cls.topic, "--duration", "45"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    time.sleep(0.5)
    return subprocess.Popen(
        [sys.executable, CYCLONE_FIXTURE, "--domain", str(cls.domain),
         "--topic", cls.topic, "--duration", "45", "--period", "0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

  @classmethod
  def tearDownClass(cls):
    super().tearDownClass()
    cls.reader.terminate()
    try:
      cls.reader.wait(timeout=10)
    except subprocess.TimeoutExpired:
      cls.reader.kill()


class TestFastDDSWireE2E(VendorWireE2E):
  VENDOR = "Fast DDS"
  # The upstream Fast DDS HelloWorld example uses these defaults.
  FIXED_DOMAIN = 0
  FIXED_TOPIC = "hello_world_topic"

  @classmethod
  def start_publisher(cls):
    if not _command_available("docker"):
      raise unittest.SkipTest("docker is not installed")
    image = subprocess.run(["docker", "image", "inspect", FASTDDS_IMAGE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
    if image.returncode:
      raise unittest.SkipTest(
          f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable; build it with "
          "test/vendors/fastdds/build_image.sh")
    cls.reader = subprocess.Popen(
      ["docker", "run", "--rm", "--network", "host", "-i",
       "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4",
       FASTDDS_IMAGE, "subscriber"],
      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
      text=True)
    time.sleep(0.5)
    return subprocess.Popen(
      ["docker", "run", "--rm", "--network", "host", "-i",
       "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True)

  @classmethod
  def tearDownClass(cls):
    super().tearDownClass()
    cls.reader.terminate()
    try:
      cls.reader.wait(timeout=10)
    except subprocess.TimeoutExpired:
      cls.reader.kill()


if __name__ == "__main__":
  unittest.main()