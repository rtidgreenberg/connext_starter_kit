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

sys.path.insert(0, TOOL_DIR)
from rti_doctor import paths  # noqa: E402

# domains lives beside this file. Without this the import resolved only when
# some OTHER test module had already put the test directory on sys.path,
# so the suite passed in a full run and failed when run on its own.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E402
import domains  # noqa: E402

try:
  import rti.connextdds  # noqa: F401
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

  def _assert_fastdds_type_object_deserializes(self, type_object_v1_only=False):
    """Require the custom Fast DDS TypeObject to resolve in Connext."""
    compat.configure_rti_environment()
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
          "--duration", "10", "--wait-for-file", "/control/start",
          "--endpoint-ready-file", "/control/writer.ready",
      ]
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
      stdout, stderr = writer.communicate(timeout=30)
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

  @unittest.expectedFailure
  def test_fastdds_writer_type_object_deserializes_with_connext_v1_only(self):
    """Track the v1-only discovery experiment separately from default support."""
    self._assert_fastdds_type_object_deserializes(type_object_v1_only=True)


if __name__ == "__main__":
  unittest.main()