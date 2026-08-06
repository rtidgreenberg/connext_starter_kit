"""Fast DDS TypeInformation suppression spike observed through Connext logs."""

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
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")

sys.path.insert(0, TOOL_DIR)

import domains  # noqa: E402

try:
  import rti.connextdds  # noqa: F401
  from rti_doctor import compat, discovery
  from rti_doctor import __main__ as doctor_main
  CONNEXT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
  CONNEXT_AVAILABLE = False


def _domain():
  return domains.for_suite("test_fastdds_type_metadata_spike")


@unittest.skipUnless(CONNEXT_AVAILABLE, "RTI Connext Python API not available")
@unittest.skipUnless(shutil.which("docker"), "docker is not installed")
class TestFastDdsTypeMetadataSpike(unittest.TestCase):
  """Distinguish rejected Fast DDS metadata from deliberately omitted metadata."""

  @classmethod
  def setUpClass(cls):
    available = subprocess.run(
        ["docker", "image", "inspect", FASTDDS_IMAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if available.returncode:
      raise unittest.SkipTest(
          f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable; build it with "
          "test/vendors/fastdds/build_image.sh")

  def _observe_metadata(self, type_metadata, type_lookup="disabled"):
    compat.configure_rti_environment()
    domain = _domain()
    topic = f"DoctorFastDdsMetadata{type_metadata}_{uuid.uuid4().hex}"
    registry = discovery.DiscoveryRegistry(type_wait=6.0)
    output_root = os.path.join(TOOL_DIR, "..", "..", "test_output")
    os.makedirs(output_root, exist_ok=True)
    artifact_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_metadata_",
                                    dir=output_root)
    connext_log = os.path.join(artifact_dir, "connext.log")
    writer = None
    participant = None

    try:
      doctor_main.configure_connext_logging(connext_log, "status-all")
      participant, _ = discovery.create_participant(
          domain, name="RTI DOCTOR TYPE METADATA SPIKE", registry=registry)
      command = [
          "docker", "run", "--rm", "--network", "host", "--entrypoint",
          "/doctor-extensibility-build/doctor_fastdds_final",
          "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
          "--domain", str(domain), "--topic", topic, "--role", "writer",
          "--extensibility", "final", "--reliability", "reliable",
          "--type-metadata", type_metadata, "--type-lookup", type_lookup,
          "--duration", "10",
      ]
      writer = subprocess.Popen(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      deadline = time.monotonic() + 8.0
      endpoint = None
      while time.monotonic() < deadline:
        discovery.refresh_participants(participant, registry)
        endpoint = registry.find_writer(topic)
        if endpoint is not None:
          break
        time.sleep(0.2)
      registry.expire_type_waits()
      stdout, stderr = writer.communicate(timeout=20)
      self.assertEqual(writer.returncode, 0, f"Fast DDS writer failed:\n{stderr}\n{stdout}")
      with open(connext_log, encoding="utf-8") as log_file:
        log_text = log_file.read()
      return endpoint, log_text
    finally:
      if writer is not None and writer.poll() is None:
        writer.kill()
        writer.communicate()
      if participant is not None:
        participant.close()
      if not os.environ.get("RTI_DOCTOR_KEEP_ARTIFACTS"):
        shutil.rmtree(artifact_dir, ignore_errors=True)

  def test_default_metadata_resolves_dynamic_type(self):
    """Current Fast DDS metadata must resolve a Connext DynamicType."""
    endpoint, log_text = self._observe_metadata("full")
    self.assertIsNotNone(endpoint, "Fast DDS writer was not discovered")
    self.assertIsNotNone(endpoint.type,
                         "Fast DDS metadata did not resolve a DynamicType")
    self.assertIsInstance(log_text, str)

  def test_metadata_suppression_does_not_trigger_typeinformation_deserialize_error(self):
    """No metadata must not be mistaken for a decoded dynamic type."""
    endpoint, log_text = self._observe_metadata("none")
    self.assertIsNotNone(endpoint, "Fast DDS writer was not discovered")
    self.assertIsNone(endpoint.type,
                      "suppressed TypeInformation must not yield a DynamicType")
    self.assertNotIn("DISCBuiltin_deserializeTypeInformation: FAILED TO DESERIALIZE",
                     log_text)

  def test_fastdds_typelookup_resolves_dynamic_type_in_connext(self):
    """Fast DDS TypeLookup must preserve DynamicType resolution."""
    endpoint, log_text = self._observe_metadata("full", type_lookup="enabled")
    self.assertIsNotNone(endpoint, "Fast DDS writer was not discovered")
    self.assertIsNotNone(endpoint.type,
                         "Fast DDS TypeLookup did not resolve a DynamicType")
    self.assertNotIn("DISCBuiltin_deserializeTypeInformation: FAILED TO DESERIALIZE",
                     log_text)


if __name__ == "__main__":
  unittest.main()