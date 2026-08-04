"""Cross-vendor FINAL/APPENDABLE type-extensibility data-flow matrix."""

import json
import os
import random
import subprocess
import sys
import time
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "extensibility_connext_endpoint.py")
CYCLONE = os.path.join(VENDORS, "extensibility_cyclone_endpoint.py")
DOMAIN_BASE = 140


@unittest.skipUnless(
    __import__("importlib").util.find_spec("cyclonedds"),
    "Cyclone DDS Python package not available")
class TestExtensibilityVendorDataFlow(unittest.TestCase):
  """Measure all FINAL/APPENDABLE cross-vendor data-flow combinations."""

  def _command(self, script, domain, topic, role, extensibility, duration):
    return [
        sys.executable, script, "--domain", str(domain), "--topic", topic,
        "--role", role, "--extensibility", extensibility,
        "--duration", str(duration),
    ]

  def _result(self, output, command):
    for line in reversed(output.splitlines()):
      if line.startswith("{"):
        return json.loads(line)
    self.fail(f"endpoint emitted no JSON\ncommand={command}\n{output}")

  def _run_pair(self, writer_script, writer_extensibility,
                reader_script, reader_extensibility):
    domain = DOMAIN_BASE + random.randint(1, 80)
    topic = f"DoctorExtensibility{domain}"
    reader_command = self._command(
        reader_script, domain, topic, "reader", reader_extensibility, 6)
    writer_command = self._command(
        writer_script, domain, topic, "writer", writer_extensibility, 4)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
      time.sleep(1.0)
      writer = subprocess.run(writer_command, text=True, capture_output=True,
                              timeout=15, check=False)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer.stderr}\n{writer.stdout}")
      reader_stdout, reader_stderr = reader.communicate(timeout=15)
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      reader.kill()
      reader.communicate()
      raise
    return (self._result(writer.stdout, writer_command),
            self._result(reader_stdout, reader_command))

  def _assert_data_flows(self, writer, reader):
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertGreater(writer["results"]["matched"], 0, writer)
    self.assertGreater(reader["results"]["matched"], 0, reader)
    self.assertGreater(reader["results"]["samples"], 0, reader)

  def test_connext_writer_to_cyclone_reader_matrix(self):
    for writer_extensibility, reader_extensibility in (
        ("final", "final"),
        ("appendable", "appendable"),
        ("final", "appendable"),
        ("appendable", "final"),
    ):
      with self.subTest(writer=writer_extensibility, reader=reader_extensibility):
        writer, reader = self._run_pair(
            CONNEXT, writer_extensibility, CYCLONE, reader_extensibility)
        self._assert_data_flows(writer, reader)

  def test_cyclone_writer_to_connext_reader_matrix(self):
    for writer_extensibility, reader_extensibility in (
        ("final", "final"),
        ("appendable", "appendable"),
        ("final", "appendable"),
        ("appendable", "final"),
    ):
      with self.subTest(writer=writer_extensibility, reader=reader_extensibility):
        writer, reader = self._run_pair(
            CYCLONE, writer_extensibility, CONNEXT, reader_extensibility)
        self._assert_data_flows(writer, reader)


if __name__ == "__main__":
  unittest.main()
