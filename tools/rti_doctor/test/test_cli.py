"""Unit tests for the CLI entry points, with a fake Session.

`run_headless_all` and `run_headless_domain` had no test of any kind, and both
raised NameError on a module-scope import that was never added - after doing the
whole sweep. These drive them end to end without a participant.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import __main__ as cli, findings as f, records  # noqa: E402
from rti_doctor import discovery  # noqa: E402


class FakeSession:
  """Enough Session surface for the headless paths, with no DDS entities."""

  def __init__(self, findings=(), writers=()):
    self.registry = discovery.DiscoveryRegistry()
    for writer in writers:
      self.registry.endpoints[writer.key] = writer
    self.domain_id = 7
    self.active_domains = set()
    self.domain_scan_ran = False
    self.type_lookup_settings = {}
    self.participant = object()
    self._findings = list(findings)

  def diagnose_domain(self):
    return list(self._findings)

  def sweep(self, progress=None, probe=True):
    from rti_doctor import report
    rows = []
    for writer in self.registry.writers():
      data = report.ReportData(domain_id=self.domain_id,
                               scope=f"topic '{writer.topic_name}'",
                               all_findings=list(self._findings), endpoint=writer)
      rows.append({"topic": writer.topic_name, "vendor": writer.vendor_name,
                   "severity": "OK", "verdict": data.verdict, "findings": [],
                   "report": data})
    return rows, []


def _args(**overrides):
  # settle/type-wait at 0 so these do not sleep; both are real waits on a live
  # domain and neither has anything to wait for against a fake session.
  argv = ["--domain", "7", "--settle", "0", "--type-wait", "0"]
  for key, value in overrides.items():
    argv += [f"--{key.replace('_', '-')}", str(value)]
  return cli.parse_args(argv)


class TestHeadlessPaths(unittest.TestCase):

  def setUp(self):
    self.patch = mock.patch.object(cli, "_settle", lambda session, seconds: None)
    self.patch.start()
    self.addCleanup(self.patch.stop)

  def test_sweep_runs_to_completion_and_emits_a_report(self):
    writer = records.EndpointRecord(key="w1", kind="Writer", topic_name="Telemetry")
    session = FakeSession(writers=[writer])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
      code = cli.run_headless_all(session, _args(format="text"))
    self.assertEqual(code, 0)
    output = buffer.getvalue()
    self.assertIn("RTI DOCTOR INTEROP SWEEP", output)
    self.assertIn("OBSERVED TOPOLOGY", output)
    self.assertIn("Telemetry", output)

  def test_sweep_json_includes_topology(self):
    import json
    session = FakeSession(writers=[
        records.EndpointRecord(key="w1", kind="Writer", topic_name="Telemetry")])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
      cli.run_headless_all(session, _args(format="json"))
    payload = json.loads(buffer.getvalue())
    self.assertEqual(payload["topology"]["selected_domain_id"], 7)
    self.assertEqual(payload["writers"][0]["topic"], "Telemetry")

  def test_domain_audit_runs_to_completion(self):
    session = FakeSession(findings=[f.Finding(
        id="blind.empty_domain", rung=f.RUNG_PARTICIPANT, severity=f.Severity.ERROR,
        title="No participants discovered")])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
      code = cli.run_headless_domain(session, _args())
    self.assertEqual(code, 1)  # an ERROR must reach the exit code
    self.assertIn("blind.empty_domain", buffer.getvalue())


class TestArgumentValidation(unittest.TestCase):
  """argparse accepts negatives, "nan" and "inf" for these; Connext does not."""

  def _rejects(self, argv):
    with self.assertRaises(SystemExit):
      with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
        cli.parse_args(argv)

  def test_negative_domain_is_rejected(self):
    self._rejects(["-d", "-1"])

  def test_negative_timeouts_are_rejected(self):
    self._rejects(["--probe-timeout", "-1"])
    self._rejects(["--type-wait", "-1"])
    self._rejects(["--settle", "-2.5"])
    self._rejects(["--scan-timeout", "-1"])

  def test_non_finite_timeouts_are_rejected(self):
    self._rejects(["--probe-timeout", "nan"])
    self._rejects(["--type-wait", "inf"])

  def test_zero_interval_is_rejected(self):
    self._rejects(["--interval", "0"])

  def test_ordinary_values_are_accepted(self):
    args = cli.parse_args(["-d", "0", "--probe-timeout", "0", "--interval", "0.5"])
    self.assertEqual(args.domain, 0)
    self.assertEqual(args.probe_timeout, 0)


if __name__ == "__main__":
  unittest.main()
