"""RxO data-flow matrix for Connext and Cyclone DDS.

Each side creates one endpoint per QoS condition. Compatible runs must match and
transfer samples. Mismatched runs must leave writers publishing but produce no
writer/reader match and no reader sample reception. This verifies the requested/
offered rules against real DDS matching, not only Doctor's static comparison.
"""

import json
import os
import subprocess
import sys
import unittest

import domains  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "rxo_connext_matrix.py")
CYCLONE = os.path.join(VENDORS, "rxo_cyclone_matrix.py")
SCENARIOS = (
    "reliability", "durability", "liveliness_kind", "liveliness_lease",
    "destination_order", "presentation_scope", "presentation_coherent",
    "presentation_ordered", "deadline", "latency_budget", "ownership",
    "data_representation", "partition",
)
NON_REPRESENTATION_SCENARIOS = tuple(
    scenario for scenario in SCENARIOS if scenario != "data_representation")


@unittest.skipUnless(
    __import__("importlib").util.find_spec("cyclonedds"),
    "Cyclone DDS Python package not available")
class TestRxOVendorDataFlow(unittest.TestCase):
  """Validate matching and data reception for every RxO diagnostic condition."""

  def _command(self, script, domain, prefix, role, mode, scenarios):
    command = [
        sys.executable, script, "--domain", str(domain), "--topic-prefix", prefix,
        "--role", role, "--mode", mode, "--scenarios", ",".join(scenarios),
        "--duration", "6" if role == "reader" else "4",
    ]
    if script == CONNEXT:
      # Cyclone cannot consistently consume Connext 7.7 TypeObject v2 metadata.
      # The v1 configuration isolates the QoS condition under test.
      command.append("--type-object-v1-only")
    return command

  def _json_result(self, output, command):
    for line in reversed(output.splitlines()):
      if line.startswith("{"):
        return json.loads(line)
    self.fail(f"matrix endpoint produced no JSON\ncommand={command}\n{output}")

  def _run_pair(self, writer_script, reader_script, mode, scenarios):
    domain = domains.for_suite("test_rxo_vendor_e2e")
    prefix = f"RxOE2E_{domain}_{mode}"
    reader_command = self._command(
        reader_script, domain, prefix, "reader", mode, scenarios)
    writer_command = self._command(
        writer_script, domain, prefix, "writer", mode, scenarios)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
      # The reader must exist before the writers announce their endpoints.
      import time
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
    return (self._json_result(writer.stdout, writer_command),
            self._json_result(reader_stdout, reader_command))

  def _assert_compatible_data_flow(self, writer, reader, scenarios):
    for scenario in scenarios:
      with self.subTest(scenario=scenario):
        self.assertGreater(writer["results"][scenario]["matched"], 0, writer)
        self.assertGreater(writer["results"][scenario]["samples"], 0, writer)
        self.assertGreater(reader["results"][scenario]["matched"], 0, reader)
        self.assertGreater(reader["results"][scenario]["samples"], 0, reader)

  def _assert_mismatch_blocks_data_flow(self, writer, reader, scenarios):
    for scenario in scenarios:
      with self.subTest(scenario=scenario):
        self.assertGreater(writer["results"][scenario]["samples"], 0, writer)
        self.assertEqual(writer["results"][scenario]["matched"], 0, writer)
        self.assertEqual(reader["results"][scenario]["matched"], 0, reader)
        self.assertEqual(reader["results"][scenario]["samples"], 0, reader)

  def _verify_pair(self, writer_script, reader_script):
    writer, reader = self._run_pair(
        writer_script, reader_script, "compatible", SCENARIOS)
    self._assert_compatible_data_flow(writer, reader, SCENARIOS)

    writer, reader = self._run_pair(
        writer_script, reader_script, "mismatch", NON_REPRESENTATION_SCENARIOS)
    self._assert_mismatch_blocks_data_flow(
        writer, reader, NON_REPRESENTATION_SCENARIOS)

    writer, reader = self._run_pair(
        writer_script, reader_script, "mismatch", ("data_representation",))
    self._assert_mismatch_blocks_data_flow(
        writer, reader, ("data_representation",))

  def test_connext_to_connext(self):
    self._verify_pair(CONNEXT, CONNEXT)

  def test_connext_to_cyclone(self):
    self._verify_pair(CONNEXT, CYCLONE)

  def test_cyclone_to_connext(self):
    self._verify_pair(CYCLONE, CONNEXT)


if __name__ == "__main__":
  unittest.main()
