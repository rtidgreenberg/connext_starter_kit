"""Cross-vendor FINAL/APPENDABLE data-flow matrix for Connext and Fast DDS."""

import json
import os
import random
import shutil
import subprocess
import sys
import time
import unittest
import uuid


HERE = os.path.dirname(os.path.abspath(__file__))
VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "extensibility_connext_endpoint.py")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:2.14.6")
DOMAIN_BASE = 80


class TestFastDdsExtensibilityVendorDataFlow(unittest.TestCase):
  """Measure every FINAL/APPENDABLE pair in both Connext/Fast DDS directions."""

  @classmethod
  def setUpClass(cls):
    if shutil.which("docker") is None:
      raise unittest.SkipTest("docker is not installed")
    available = subprocess.run(["docker", "image", "inspect", FASTDDS_IMAGE],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False)
    if available.returncode:
      raise unittest.SkipTest(f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable")

  def _connext_command(self, domain, topic, role, extensibility, duration):
    return [
        sys.executable, CONNEXT, "--domain", str(domain), "--topic", topic,
        "--role", role, "--extensibility", extensibility, "--schema", "fastdds",
        "--duration", str(duration),
    ]

  def _fastdds_command(self, domain, topic, role, extensibility, duration):
    return [
      "docker", "run", "--rm", "--network", "host", "--entrypoint",
      f"/doctor-extensibility-build/doctor_fastdds_{extensibility}",
        "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
        "--domain", str(domain), "--topic", topic, "--role", role,
        "--extensibility", extensibility, "--duration", str(duration),
    ]

  def _result(self, output, command):
    for line in reversed(output.splitlines()):
      if line.startswith("{"):
        return json.loads(line)
    self.fail(f"endpoint emitted no JSON\ncommand={command}\n{output}")

  def _run_pair(self, writer_vendor, writer_extensibility,
                reader_vendor, reader_extensibility):
    domain = DOMAIN_BASE + random.randint(1, 70)
    topic = f"DoctorFastDdsExtensibility_{uuid.uuid4().hex}"
    command_for = self._fastdds_command if writer_vendor == "fastdds" else self._connext_command
    writer_command = command_for(domain, topic, "writer", writer_extensibility, 4)
    command_for = self._fastdds_command if reader_vendor == "fastdds" else self._connext_command
    reader_command = command_for(domain, topic, "reader", reader_extensibility, 6)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
      time.sleep(1.0)
      writer = subprocess.run(writer_command, text=True, capture_output=True,
                              timeout=20, check=False)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer.stderr}\n{writer.stdout}")
      reader_stdout, reader_stderr = reader.communicate(timeout=20)
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      reader.kill()
      reader.communicate()
      raise
    writer_result = self._result(writer.stdout, writer_command)
    reader_result = self._result(reader_stdout, reader_command)
    self.assertEqual(writer_result["extensibility"], writer_extensibility,
             writer_result)
    self.assertEqual(reader_result["extensibility"], reader_extensibility,
             reader_result)
    return writer_result, reader_result

  def _assert_data_flows(self, writer, reader):
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertGreater(writer["results"]["matched"], 0, writer)
    self.assertGreater(reader["results"]["matched"], 0, reader)
    self.assertGreater(reader["results"]["samples"], 0, reader)

  def _run_matrix(self, writer_vendor, reader_vendor):
    for writer_extensibility, reader_extensibility in (
        ("final", "final"),
        ("appendable", "appendable"),
        ("final", "appendable"),
        ("appendable", "final"),
    ):
      with self.subTest(writer=writer_extensibility, reader=reader_extensibility):
        writer, reader = self._run_pair(
            writer_vendor, writer_extensibility, reader_vendor, reader_extensibility)
        self._assert_data_flows(writer, reader)

  def test_connext_writer_to_fastdds_reader_matrix(self):
    self._run_matrix("connext", "fastdds")

  def test_fastdds_writer_to_connext_reader_matrix(self):
    self._run_matrix("fastdds", "connext")


if __name__ == "__main__":
  unittest.main()