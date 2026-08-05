"""Unit tests for shared Doctor end-to-end test helpers."""

import os
import subprocess
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import doctor_e2e  # noqa: E402


class TestDoctorE2E(unittest.TestCase):

  def test_command_configures_headless_json_environment(self):
    command, environment = doctor_e2e.command(
        17, "Telemetry", settle=2, type_wait=4, no_probe=True,
        probe_timeout=5, capture_interface="lo", ready_file="ready",
      ready_after_participants=2, ready_timeout=7,
        connext_log="connext.log", connext_verbosity="silent")

    self.assertEqual(command[:8], [
        sys.executable, "-m", "rti_doctor", "--domain", "17", "--topic",
        "Telemetry", "--format"])
    self.assertIn("--no-probe", command)
    self.assertIn("--capture-interface", command)
    self.assertIn("--ready-file", command)
    self.assertIn("--ready-after-participants", command)
    self.assertIn("--ready-timeout", command)
    self.assertIn("--connext-log", command)
    self.assertIn("--connext-verbosity", command)
    self.assertEqual(environment["PYTHONPATH"].split(os.pathsep)[0],
                     os.path.dirname(HERE))

  def test_parse_report_accepts_native_log_preamble(self):
    completed = subprocess.CompletedProcess(
        ["doctor"], 0,
        "native diagnostics\n{\"domain_id\": 17, \"findings\": []}\n", "")

    self.assertEqual(doctor_e2e.parse_report(completed)["domain_id"], 17)

  def test_parse_report_skips_malformed_native_json(self):
    completed = subprocess.CompletedProcess(
        ["doctor"], 0,
        "{\"domain_id\": broken}\n{\"domain_id\": 19, \"findings\": []}\n", "")

    self.assertEqual(doctor_e2e.parse_report(completed)["domain_id"], 19)

  def test_parse_report_rejects_non_report_json(self):
    completed = subprocess.CompletedProcess(
        ["doctor"], 0, "{\"not_a_report\": true}\n", "native error")

    with self.assertRaisesRegex(AssertionError, "Doctor did not emit"):
      doctor_e2e.parse_report(completed)


if __name__ == "__main__":
  unittest.main()
