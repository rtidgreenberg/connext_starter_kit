"""Unit tests for the CLI entry points, with a fake Session.

The headless paths had no test of any kind, and raised NameError on a
module-scope import that was never added - after doing all the work. These
drive them end to end without a participant.
"""

import contextlib
import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import __main__ as cli, records  # noqa: E402
from rti_doctor import discovery, engine  # noqa: E402


class FakeSession:
  """Enough Session surface for the headless paths, with no DDS entities.

  `system_scan` is the real `engine.Session.system_scan` running over a real
  registry, not a canned snapshot: a fake that hardcodes the values the exit
  code is derived from cannot fail when production stops producing them.
  """

  def __init__(self, endpoints=(), participants=()):
    self.registry = discovery.DiscoveryRegistry(type_wait=0.0)
    for participant in participants:
      self.registry.participants[participant.key] = participant
    for endpoint in endpoints:
      self.registry.endpoints[endpoint.key] = endpoint
    self.domain_id = 7
    self.active_domains = set()
    self.domain_scan_ran = False
    self.type_lookup_settings = {"request_types_filter": "*"}
    self.participant = object()
    # State engine.Session.system_scan reads. Borrowing the real method keeps
    # the scan's own ordering - expiring type waits before scanning - under
    # test instead of re-implementing it here.
    self.own_qos = None
    self.type_wait = 0.0
    self.discovery_capture = None
    self._last_scan = None
    self._fastdds_product_versions = ()
    self._fastdds_participant_versions = ()

  def system_scan(self, captured_at=None, max_age=0.0):
    return engine.Session.system_scan(self, captured_at=captured_at,
                                      max_age=max_age)


class Policy:
  def __init__(self, kind):
    self.kind = kind


def incompatible_pair():
  """A live writer/reader pair that can never match: BEST_EFFORT vs RELIABLE."""
  participants = [records.ParticipantRecord(key="p-w", name="writer-app"),
                  records.ParticipantRecord(key="p-r", name="reader-app")]
  endpoints = [
      records.EndpointRecord(key="w1", kind="Writer", participant_key="p-w",
                             topic_name="Telemetry", type_name="TelemetryType",
                             reliability=Policy("BEST_EFFORT"), first_seen=1.0),
      records.EndpointRecord(key="r1", kind="Reader", participant_key="p-r",
                             topic_name="Telemetry", type_name="TelemetryType",
                             reliability=Policy("RELIABLE"), first_seen=1.0),
  ]
  return endpoints, participants


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

  def test_system_assessment_reports_a_real_incompatibility(self):
    """A system-wide ERROR must reach the report and the exit code.

    --all used to be what a CI job ran to catch this. Stage one has to catch
    it too, or removing --all would have removed the gate with it.
    """
    endpoints, participants = incompatible_pair()
    session = FakeSession(endpoints=endpoints, participants=participants)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
      code = cli.run_headless_system(session, _args())
    self.assertEqual(code, 1)
    output = buffer.getvalue()
    self.assertIn("qos.rxo_mismatch", output)
    self.assertIn("Telemetry", output)

  def test_system_assessment_of_a_quiet_system_exits_zero(self):
    session = FakeSession()
    buffer = io.StringIO()
    with redirect_stdout(buffer):
      code = cli.run_headless_system(session, _args())
    self.assertEqual(code, 0)
    self.assertIn("RTI DOCTOR SYSTEM REPORT", buffer.getvalue())

  def test_system_assessment_waits_out_type_resolution(self):
    """A type that never resolves must not be reported as still in flight.

    Type resolution is asynchronous, so scanning before --type-wait has
    elapsed leaves the endpoint PENDING and the run exits 0 on a writer whose
    schema never arrives. The wait goes through _settle rather than
    time.sleep, because a participant announcing during it is only recorded by
    polling for it.
    """
    participants = [records.ParticipantRecord(key="p-w")]
    endpoints = [records.EndpointRecord(
        key="w1", kind="Writer", participant_key="p-w", topic_name="Telemetry",
        type_name="TelemetryType", first_seen=time.monotonic())]
    session = FakeSession(endpoints=endpoints, participants=participants)
    session.registry.type_wait = session.type_wait = 0.05

    waits = []

    def polling_settle(session, seconds):
      waits.append(seconds)
      time.sleep(seconds)

    with mock.patch.object(cli, "_settle", polling_settle):
      with redirect_stdout(io.StringIO()):
        cli.run_headless_system(session, cli.parse_args(
            ["--domain", "7", "--settle", "0", "--type-wait", "0.05"]))
    self.assertEqual(waits, [0.0, 0.05])
    self.assertEqual(session.registry.endpoints["w1"].type_state,
                     records.TYPE_UNAVAILABLE)

  def test_system_assessment_does_not_diagnose_each_endpoint(self):
    """The point of removing --all: assessment must not scale per endpoint.

    diagnose_endpoint is the expensive path - it probes, waits for types and
    can start a capture. Stage one must never reach it, however large the
    system is.
    """
    endpoints = [records.EndpointRecord(key=f"w{n}", kind="Writer",
                                        participant_key="p-w",
                                        topic_name=f"T{n}", first_seen=1.0)
                 for n in range(50)]
    session = FakeSession(endpoints=endpoints,
                          participants=[records.ParticipantRecord(key="p-w")])
    session.diagnose_endpoint = lambda *a, **k: self.fail(
        "system assessment diagnosed an individual endpoint")
    with redirect_stdout(io.StringIO()):
      cli.run_headless_system(session, _args())


class TestWorkflowFlags(unittest.TestCase):
  """The two stages must both be reachable from an interactive terminal.

  `--all` was removed, and stage one is otherwise only reachable when stdin is
  not a tty - so a user at a shell had no way to ask for a system assessment.
  """

  def test_the_removed_format_flag_is_rejected(self):
    """One report format, so there is no format to choose.

    `--format json` was an explicitly unstable second schema that had to be
    kept working for one test harness. Accepting the flag and ignoring it
    would leave a CI job believing it was still getting JSON.
    """
    for argv in (["-d", "1", "-t", "Telemetry", "--format", "json"],
                 ["-d", "1", "--system", "--format", "text"]):
      with self.subTest(argv=argv):
        with self.assertRaises(SystemExit):
          with redirect_stdout(io.StringIO()), \
               mock.patch.object(sys, "stderr", io.StringIO()):
            cli.parse_args(argv)

  def test_a_targeted_diagnosis_renders_the_text_report(self):
    self.assertFalse(hasattr(cli.parse_args(["-d", "1", "-t", "Telemetry"]),
                             "format"))

  def test_the_removed_sweep_flag_is_rejected(self):
    with self.assertRaises(SystemExit):
      with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
        cli.parse_args(["-d", "1", "--all"])

  def test_system_is_headless_even_on_a_terminal(self):
    with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)):
      self.assertTrue(cli.is_headless(cli.parse_args(["-d", "1", "--system"])))
      self.assertTrue(cli.is_headless(cli.parse_args(["-d", "1", "-t", "T"])))
      self.assertFalse(cli.is_headless(cli.parse_args(["-d", "1"])))

  def test_system_and_topic_are_mutually_exclusive(self):
    with self.assertRaises(SystemExit):
      with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
        cli.parse_args(["-d", "1", "--system", "-t", "Telemetry"])


class TestSessionSurface(unittest.TestCase):
  """main() is not covered by these tests, so guard what it depends on.

  Removing engine.Session.close_discovery_capture broke every invocation -
  the AttributeError was swallowed by main()'s cleanup `except`, so the
  participant was never closed - and nothing failed. pyflakes checks undefined
  names, not missing attributes.
  """

  def test_every_session_attribute_main_uses_exists(self):
    import inspect
    import re
    source = inspect.getsource(cli)
    used = sorted(set(re.findall(r"\bsession\.([A-Za-z_][A-Za-z0-9_]*)", source)))
    self.assertTrue(used, "expected to find session attribute uses in __main__")
    missing = [name for name in used
               if not hasattr(engine.Session, name)
               and name not in vars(engine.Session).get("__annotations__", {})]
    # Instance attributes assigned in __init__ are not on the class, so allow
    # the ones FakeSession models; anything else must be a real class member.
    instance_attributes = {"registry", "domain_id", "active_domains",
                           "domain_scan_ran", "type_lookup_settings",
                           "participant", "own_qos", "type_wait",
                           "discovery_capture"}
    self.assertEqual([name for name in missing if name not in instance_attributes],
                     [])


class TestMainReleasesWhatItOwns(unittest.TestCase):
  """H7/M11: the participant and the capture must survive every exit path.

  `main()` used to create both and then run capture startup, the readiness wait
  and the ready-file write *before* entering its cleanup `try`. Anything raising
  in that stretch - and the widest window is Ctrl-C during
  `LiveCapture.start()`'s one-second settle, or during the up-to-15-second
  readiness wait - unwound straight past the `finally`, leaving a DomainParticipant
  open and a `tshark` writing into `test_output/` with nothing left to reap it.
  """

  class FakeParticipant:
    def __init__(self):
      self.closed = 0

    def close(self):
      self.closed += 1

  def _run(self, argv=("--domain", "7", "--system", "--no-domain-scan"),
           closes_raise=False, **patches):
    session = FakeSession()
    session.closed_capture = 0
    participant = self.FakeParticipant()

    def close_discovery_capture():
      session.closed_capture += 1
      if closes_raise:
        raise OSError("tshark log file is already closed")

    session.close_discovery_capture = close_discovery_capture
    defaults = {
        "build_session": lambda *a, **k: (session, participant),
        "start_discovery_capture": lambda *a, **k: None,
        "_wait_for_remote_participants": lambda *a, **k: True,
        "_write_ready_file": lambda *a, **k: None,
        "run_headless_system": lambda *a, **k: 0,
    }
    defaults.update(patches)
    with contextlib.ExitStack() as stack:
      for name, value in defaults.items():
        stack.enter_context(mock.patch.object(cli, name, value))
      stack.enter_context(redirect_stdout(io.StringIO()))
      stack.enter_context(mock.patch.object(sys, "stderr", io.StringIO()))
      try:
        code = cli.main(list(argv))
      except BaseException as error:  # noqa: BLE001 - the point of the test
        code = error
    return session, participant, code

  def test_a_clean_run_closes_both_exactly_once(self):
    session, participant, code = self._run()
    self.assertEqual(code, 0)
    self.assertEqual(participant.closed, 1)
    self.assertEqual(session.closed_capture, 1)

  def test_an_interrupt_during_capture_startup_still_closes_both(self):
    def interrupt(*args, **kwargs):
      raise KeyboardInterrupt()

    session, participant, code = self._run(start_discovery_capture=interrupt)
    self.assertIsInstance(code, KeyboardInterrupt)
    self.assertEqual(participant.closed, 1)
    self.assertEqual(session.closed_capture, 1)

  def test_an_interrupt_during_the_readiness_wait_still_closes_both(self):
    def interrupt(*args, **kwargs):
      raise KeyboardInterrupt()

    session, participant, code = self._run(_wait_for_remote_participants=interrupt)
    self.assertIsInstance(code, KeyboardInterrupt)
    self.assertEqual(participant.closed, 1)
    self.assertEqual(session.closed_capture, 1)

  def test_an_unwritable_ready_file_still_closes_both(self):
    def unwritable(*args, **kwargs):
      raise OSError("read-only file system")

    session, participant, code = self._run(_write_ready_file=unwritable)
    self.assertIsInstance(code, OSError)
    self.assertEqual(participant.closed, 1)
    self.assertEqual(session.closed_capture, 1)

  def test_the_readiness_timeout_closes_both_exactly_once(self):
    """It used to close them itself as well as returning; now it just returns."""
    session, participant, code = self._run(
        _wait_for_remote_participants=lambda *a, **k: False)
    self.assertEqual(code, 3)
    self.assertEqual(participant.closed, 1)
    self.assertEqual(session.closed_capture, 1)

  def test_a_raising_capture_teardown_still_closes_the_participant(self):
    """M11: one `try` around both put the likelier failure in front."""
    with self.assertLogs(level="ERROR"):
      session, participant, code = self._run(closes_raise=True)
    self.assertEqual(code, 0)
    self.assertEqual(session.closed_capture, 1)
    self.assertEqual(participant.closed, 1)


class TestCaptureDetachesBeforeItFinishes(unittest.TestCase):
  """M11: a raising teardown left the capture attached for a doomed retry."""

  class ExplodingCapture:
    def __init__(self):
      self.finishes = 0

    def finish_discovery(self):
      self.finishes += 1
      raise OSError("tshark log file is already closed")

  def test_a_failed_close_does_not_leave_the_capture_attached(self):
    capture = self.ExplodingCapture()
    session = engine.Session(
        participant=object(), registry=discovery.DiscoveryRegistry(type_wait=0.0),
        own_qos=None, type_lookup_settings={}, domain_id=7,
        discovery_capture=capture)

    with self.assertRaises(OSError):
      session.close_discovery_capture()
    self.assertIsNone(session.discovery_capture)
    # A second close is a no-op rather than terminating a dead process again.
    session.close_discovery_capture()
    self.assertEqual(capture.finishes, 1)


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
