"""Unit tests for shared Doctor end-to-end test helpers."""

import os
import subprocess
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import doctor_e2e  # noqa: E402
from rti_doctor import __main__ as doctor_main  # noqa: E402
from rti_doctor import findings, report  # noqa: E402


class TestDoctorE2E(unittest.TestCase):

  def test_connext_logging_is_silent_by_default(self):
    self.assertEqual(doctor_main.parse_args([]).connext_verbosity, "silent")

  def test_command_configures_a_headless_environment(self):
    command, environment = doctor_e2e.command(
        17, "Telemetry", settle=2, type_wait=4, no_probe=True,
        probe_timeout=5, capture_interface="lo", ready_file="ready",
      ready_after_participants=2, ready_timeout=7,
        connext_log="connext.log", connext_verbosity="silent")

    self.assertEqual(command[:7], [
        sys.executable, "-m", "rti_doctor", "--domain", "17", "--topic",
        "Telemetry"])
    # --format is gone: the text report is the only output Doctor produces.
    self.assertNotIn("--format", command)
    self.assertIn("--no-probe", command)
    self.assertIn("--capture-interface", command)
    self.assertIn("--ready-file", command)
    self.assertIn("--ready-after-participants", command)
    self.assertIn("--ready-timeout", command)
    self.assertIn("--connext-log", command)
    self.assertIn("--connext-verbosity", command)
    self.assertEqual(environment["PYTHONPATH"].split(os.pathsep)[0],
                     os.path.dirname(HERE))

class TestParseTextReport(unittest.TestCase):
  """The parser is driven by real renderer output, never a hand-written copy.

  The C1 defect was a hand-written fixture that agreed with the parser and not
  with the producer, so every one of these builds its input with
  `report.render_text` and reads it back.
  """

  MISMATCH = findings.Finding(
      id="qos.rxo_mismatch", rung=4, severity=findings.Severity.ERROR,
      title="QoS incompatible (RELIABILITY): writer-app -> reader-app",
      observed=("RELIABILITY: writer offers BEST_EFFORT, reader requests "
                "RELIABLE. Not evaluated (PARTITION): this pair was neither "
                "confirmed compatible nor found incompatible on these policies."),
      root_cause="These two endpoints are both live and will never communicate.",
      remedy="Change RELIABILITY on one side.",
      refs=["https://example.invalid/rxo", "https://example.invalid/qos"])
  RESOLVED = findings.Finding(
      id="type.resolved", rung=3, severity=findings.Severity.OK,
      title="Type information resolved",
      observed="DynamicType for 'TelemetryType' is available.")

  def _completed(self, all_findings=(), wire_evidence=None, preamble=""):
    data = report.ReportData(domain_id=17, scope="topic 'Telemetry'",
                             all_findings=list(all_findings),
                             wire_evidence=wire_evidence)
    return subprocess.CompletedProcess(
        ["doctor"], 0, preamble + report.render_text(data), "")

  def test_header_and_verdict_are_read_back(self):
    parsed = doctor_e2e.parse_report(self._completed([self.RESOLVED]))
    self.assertEqual(parsed["domain_id"], 17)
    self.assertEqual(parsed["scope"], "topic 'Telemetry'")
    self.assertTrue(parsed["verdict"])

  def test_native_log_preamble_is_skipped(self):
    completed = self._completed(
        [self.RESOLVED],
        preamble="native diagnostics\nRTIOsapi: something happened\n")
    self.assertEqual(doctor_e2e.parse_report(completed)["domain_id"], 17)

  def test_findings_keep_their_id_severity_and_wrapped_text(self):
    parsed = doctor_e2e.parse_report(
        self._completed([self.MISMATCH, self.RESOLVED]))
    by_id = {item["id"]: item for item in parsed["findings"]}
    self.assertEqual(sorted(by_id), ["qos.rxo_mismatch", "type.resolved"])
    mismatch = by_id["qos.rxo_mismatch"]
    self.assertEqual(mismatch["severity"], "ERROR")
    self.assertEqual(mismatch["rung"], 4)
    # Every one of these is wrapped across several report lines; the parser
    # must rejoin them or a substring assertion in a vendor test fails on a
    # line break rather than on the system under test.
    self.assertEqual(mismatch["title"], self.MISMATCH.title)
    self.assertEqual(mismatch["observed"], self.MISMATCH.observed)
    self.assertEqual(mismatch["root_cause"], self.MISMATCH.root_cause)
    self.assertEqual(mismatch["remedy"], self.MISMATCH.remedy)
    self.assertEqual(mismatch["refs"], self.MISMATCH.refs)
    self.assertEqual(by_id["type.resolved"]["severity"], "OK")

  def test_a_report_with_no_wire_capture_carries_no_wire_observation(self):
    parsed = doctor_e2e.parse_report(self._completed([self.RESOLVED]))
    self.assertNotIn("wire_observation", parsed)

  def test_wire_appendix_is_read_back_into_its_summary_shape(self):
    evidence = {
        "source": "/tmp/capture.pcapng",
        "capture_filter": "udp and portrange 7400-7649",
        "packets": 12,
        "data_packets": 4,
        "data_fragments": 0,
        "encapsulation_ids": ["0x0001", "0x0007"],
        "writer_entity_ids": ["000001c2"],
        "payload_bytes": 96,
        "reassembled_bytes": 0,
    }
    parsed = doctor_e2e.parse_report(
        self._completed([self.RESOLVED], wire_evidence=evidence))
    observed = parsed["wire_observation"]
    for key, value in evidence.items():
      self.assertEqual(observed[key], value, key)

  def test_an_unavailable_capture_reports_its_reason(self):
    parsed = doctor_e2e.parse_report(self._completed(
        [self.RESOLVED],
        wire_evidence={"source": "none", "error": "tshark is not installed"}))
    self.assertEqual(parsed["wire_observation"]["error"],
                     "tshark is not installed")

  def test_output_without_a_report_is_rejected(self):
    completed = subprocess.CompletedProcess(
        ["doctor"], 0, "native error: no license found\n", "native error")
    with self.assertRaisesRegex(AssertionError, "Doctor did not emit"):
      doctor_e2e.parse_report(completed)


if __name__ == "__main__":
  unittest.main()
