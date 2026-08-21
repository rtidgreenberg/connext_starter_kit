"""Fast DDS TypeInformation interoperability regression test.

The assertion is intentionally against Doctor's discovered ``DynamicType``:
Connext only exposes ``endpoint.type`` after it has accepted the endpoint
TypeInformation and obtained a usable TypeObject. Topic and type-name strings
alone are insufficient evidence because SEDP carries them independently.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
VENDORS = os.path.join(HERE, "vendors")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")
TYPE_OBJECT_PROFILE = os.environ.get("RTI_DOCTOR_TYPEOBJECT_PROFILE", "default-v2")
TYPE_OBJECT_PROFILES = {
  "default-v2": ("default", False),
  "vendor-v2": ("vendor", False),
  "vendor-v1": ("vendor", True),
}

sys.path.insert(0, TOOL_DIR)
from rti_doctor import paths  # noqa: E402

# domains lives beside this file. Without this the import resolved only when
# some OTHER test module had already put the test directory on sys.path,
# so the suite passed in a full run and failed when run on its own.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E402
import domains  # noqa: E402

try:
  import rti.connextdds as dds
  from rti_doctor import compat, discovery, records
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False


def _domain():
  return domains.for_suite("test_fastdds_type_object_e2e")


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
@unittest.skipUnless(shutil.which("docker"), "docker is not installed")
class TestFastDdsTypeObjectInterop(unittest.TestCase):
  """Require Fast DDS endpoint metadata to yield a usable Connext DynamicType."""

  @classmethod
  def setUpClass(cls):
    available = subprocess.run(
        ["docker", "image", "inspect", FASTDDS_IMAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if available.returncode:
      raise unittest.SkipTest(
          f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable; build it with "
          "test/vendors/fastdds/build_image.sh")

  def _assert_fastdds_type_object_deserializes(self, type_object_v1_only=False,
                                               read_samples=False,
                                               fastdds_qos_defaults=False):
    """Require a Fast DDS TypeObject to resolve, optionally reading its data."""
    compat.configure_rti_environment()
    try:
      xtypes_mode, profile_v1_only = TYPE_OBJECT_PROFILES[TYPE_OBJECT_PROFILE]
    except KeyError:
      self.fail(
          f"unsupported RTI_DOCTOR_TYPEOBJECT_PROFILE: {TYPE_OBJECT_PROFILE!r}")
    compat.configure_xtypes_mask(xtypes_mode)
    type_object_v1_only = type_object_v1_only or profile_v1_only
    domain = _domain()
    topic = f"DoctorFastDdsTypeObject_{uuid.uuid4().hex}"
    registry = discovery.DiscoveryRegistry(type_wait=10.0)
    output_root = paths.TEST_OUTPUT_ROOT
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_type_object_",
                                   dir=output_root)
    start_file = os.path.join(control_dir, "start")
    endpoint_ready_file = os.path.join(control_dir, "writer.ready")
    participant, _ = discovery.create_participant(
      domain, name="RTI DOCTOR TYPEOBJECT TEST", registry=registry,
      type_object_v1_only=type_object_v1_only)
    writer = None
    try:
      command = [
          "docker", "run", "--rm", "--network", "host", "--entrypoint",
          "/doctor-extensibility-build/doctor_fastdds_final",
          "--mount", f"type=bind,src={control_dir},dst=/control",
          "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
          "--domain", str(domain), "--topic", topic, "--role", "writer",
          "--extensibility", "final", "--reliability", "reliable",
          "--duration", "30", "--wait-for-file", "/control/start",
          "--endpoint-ready-file", "/control/writer.ready",
      ]
      if fastdds_qos_defaults:
        command.append("--qos-defaults")
      writer = subprocess.Popen(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      with open(start_file, "w", encoding="utf-8"):
        pass
      # This budget covers `docker run` plus Fast DDS initialization, not just
      # the endpoint creation. Measured on this host, that costs 1-3s warm and
      # 22-25s once the tier has been churning containers for a while, so the
      # 10s this used to allow expired on load alone and reported it as "the
      # writer did not create its endpoint marker" - a type-metadata failure
      # message for what was really a slow container (HAR-6, 2026-08-13). The
      # assertions this gate protects are about TypeObject resolution, so the
      # gate must not be the thing that fails first.
      deadline = time.monotonic() + 90.0
      while not os.path.exists(endpoint_ready_file) and time.monotonic() < deadline:
        time.sleep(0.05)
      self.assertTrue(os.path.exists(endpoint_ready_file),
                      "Fast DDS writer did not create its endpoint marker")
      deadline = time.monotonic() + 12.0
      endpoint = None
      while time.monotonic() < deadline:
        discovery.refresh_participants(participant, registry)
        endpoint = registry.find_writer(topic)
        if endpoint is not None and endpoint.type is not None:
          break
        registry.expire_type_waits()
        time.sleep(0.2)
      registry.expire_type_waits()

      self.assertIsNotNone(endpoint, "Fast DDS writer was not discovered")
      self.assertEqual(
          endpoint.type_state, records.TYPE_RESOLVED,
          "Connext discovered Fast DDS endpoint strings but did not deserialize "
          "a usable DynamicType from its TypeInformation")
      self.assertIsNotNone(endpoint.type)
      if read_samples:
        dynamic_topic = dds.DynamicData.Topic(
            participant, topic, endpoint.type)
        dynamic_reader = dds.DynamicData.DataReader(
            participant.implicit_subscriber, dynamic_topic, dds.DataReaderQos())
        try:
          received_sample = None
          deadline = time.monotonic() + 8.0
          while time.monotonic() < deadline:
            received_sample = next(
                (sample.data for sample in dynamic_reader.take()
                 if sample.info.valid), None)
            if received_sample is not None:
              break
            time.sleep(0.1)
          self.assertIsNotNone(
              received_sample,
              "a DynamicData reader created from the Fast DDS TypeObject "
              "received no valid samples")
          self.assertEqual("DoctorExtensibility", received_sample["message"])
          self.assertGreater(received_sample["index"], 0)
        finally:
          dynamic_reader.close()
          dynamic_topic.close()
      stdout, stderr = writer.communicate(timeout=45)
      self.assertEqual(writer.returncode, 0, f"Fast DDS writer failed:\n{stderr}\n{stdout}")
    finally:
      if writer is not None:
        if writer.poll() is None:
          writer.kill()
        writer.communicate()
      participant.close()
      shutil.rmtree(control_dir, ignore_errors=True)

  def test_fastdds_writer_type_object_deserializes_in_connext(self):
    self._assert_fastdds_type_object_deserializes()

  def test_fastdds_type_object_dynamic_data_reader_deserializes_samples(self):
    self._assert_fastdds_type_object_deserializes(read_samples=True)

  def test_fastdds_default_qos_type_object_dynamic_data_deserializes_samples(self):
    self._assert_fastdds_type_object_deserializes(
        read_samples=True, fastdds_qos_defaults=True)

  @unittest.expectedFailure
  def test_fastdds_writer_type_object_deserializes_with_connext_v1_only(self):
    """Track the v1-only discovery experiment separately from default support."""
    self._assert_fastdds_type_object_deserializes(type_object_v1_only=True)


if __name__ == "__main__":
  unittest.main()