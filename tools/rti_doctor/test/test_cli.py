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
    self.probe_timeout = 0.0
    self.capture_interface = None
    self.capture_choice_made = False
    self.capture_off_reason = None
    self.pass_deadline = 0.0
    self.capture_artifacts = []
    self.retained_artifacts = set()
    self.swept = 0
    self._last_scan = None
    self._fastdds_product_versions = ()
    self._fastdds_participant_versions = ()

  def system_scan(self, captured_at=None, max_age=0.0):
    return engine.Session.system_scan(self, captured_at=captured_at,
                                      max_age=max_age)

  def sweep_capture_artifacts(self):
    # The real method, so the TUI exit path's CAP-1 sweep stays under test
    # rather than being stubbed out of the run it is part of. Counted as well,
    # because whether it was reached at all is its own question.
    self.swept += 1
    return engine.Session.sweep_capture_artifacts(self)


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

  A `Session` method that `main()` calls in a cleanup `except` once went
  missing and broke every invocation without failing anything: the
  AttributeError was swallowed there, so the participant was never closed.
  pyflakes checks undefined names, not missing attributes.
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
                           "capture_interface"}
    self.assertEqual([name for name in missing if name not in instance_attributes],
                     [])


class MainHarness(unittest.TestCase):
  """Drives `main()` with a fake session, participant and headless run."""

  class FakeParticipant:
    def __init__(self):
      self.closed = 0

    def close(self):
      self.closed += 1

  def _run(self, argv=("--domain", "7", "--system", "--no-domain-scan"),
           session=None, **patches):
    session = session or FakeSession()
    participant = self.FakeParticipant()
    defaults = {
        "build_session": lambda *a, **k: (session, participant),
        "_wait_for_remote_participants": lambda *a, **k: True,
        "_write_ready_file": lambda *a, **k: None,
        "run_headless_system": lambda *a, **k: 0,
    }
    defaults.update(patches)
    errors = io.StringIO()
    with contextlib.ExitStack() as stack:
      for name, value in defaults.items():
        stack.enter_context(mock.patch.object(cli, name, value))
      stack.enter_context(redirect_stdout(io.StringIO()))
      stack.enter_context(mock.patch.object(sys, "stderr", errors))
      try:
        code = cli.main(list(argv))
      except BaseException as error:  # noqa: BLE001 - the point of the test
        code = error
    self.stderr = errors.getvalue()
    return session, participant, code


class TestMainReleasesWhatItOwns(MainHarness):
  """H7: the participant must be released on every exit path.

  `main()` used to create it and then run capture startup, the readiness wait
  and the ready-file write *before* entering its cleanup `try`. Anything raising
  in that stretch - the widest window being Ctrl-C during the up-to-15-second
  readiness wait - unwound straight past the `finally`, leaving a
  DomainParticipant open. H9 removed the second owned resource, the startup
  packet capture, so the participant is now the whole ownership boundary.
  """

  def test_a_clean_run_closes_the_participant_exactly_once(self):
    _session, participant, code = self._run()
    self.assertEqual(code, 0)
    self.assertEqual(participant.closed, 1)

  def test_an_interrupt_during_the_readiness_wait_still_closes_it(self):
    def interrupt(*args, **kwargs):
      raise KeyboardInterrupt()

    _session, participant, code = self._run(_wait_for_remote_participants=interrupt)
    self.assertIsInstance(code, KeyboardInterrupt)
    self.assertEqual(participant.closed, 1)

  def test_an_unwritable_ready_file_still_closes_it(self):
    def unwritable(*args, **kwargs):
      raise OSError("read-only file system")

    with self.assertLogs(level="ERROR"):
      _session, participant, code = self._run(_write_ready_file=unwritable)
    # M13: an operational failure is exit 4, not the finding-error exit code.
    self.assertEqual(code, cli.EXIT_CANNOT_START)
    self.assertEqual(participant.closed, 1)

  def test_the_readiness_timeout_closes_it_exactly_once(self):
    """It used to close it itself as well as returning; now it just returns."""
    _session, participant, code = self._run(
        _wait_for_remote_participants=lambda *a, **k: False)
    self.assertEqual(code, cli.EXIT_READINESS_TIMEOUT)
    self.assertEqual(participant.closed, 1)

  def test_a_raising_close_does_not_replace_the_run_result(self):
    class RefusingParticipant:
      closed = 0

      def close(self):
        raise OSError("participant handle is already closed")

    participant = RefusingParticipant()
    with self.assertLogs(level="ERROR"):
      with contextlib.ExitStack() as stack:
        for name, value in (
            ("build_session", lambda *a, **k: (FakeSession(), participant)),
            ("_wait_for_remote_participants", lambda *a, **k: True),
            ("_write_ready_file", lambda *a, **k: None),
            ("run_headless_system", lambda *a, **k: 1)):
          stack.enter_context(mock.patch.object(cli, name, value))
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(mock.patch.object(sys, "stderr", io.StringIO()))
        code = cli.main(["--domain", "7", "--system", "--no-domain-scan"])
    self.assertEqual(code, 1)


class TestNothingIsCapturedWithoutBeingAsked(MainHarness):
  """H8/H9: startup must not capture packets, and must not offer to.

  Startup used to prompt for a capture interface and then run `tshark` over the
  domain's whole RTPS port range - all user traffic, not just discovery - for
  the entire session, with nothing bounding the file on disk and a full re-parse
  at exit whose result was discarded.
  """

  def test_starting_up_creates_no_capture(self):
    captures = []

    class Recorded:
      def __init__(self, *args, **kwargs):
        captures.append((args, kwargs))

    with mock.patch.object(cli.wire, "LiveCapture", Recorded):
      _session, _participant, code = self._run()
    self.assertEqual(code, 0)
    self.assertEqual(captures, [])

  def test_the_interactive_startup_neither_prompts_nor_captures(self):
    """The TUI path is the one that used to do both.

    Startup listed tshark's interfaces, prompted for one, and then captured the
    domain's whole RTPS port range for as long as the session lasted. Nothing
    on this path may run tshark or ask about it now: capture is a `c` away, on
    an endpoint report, or not at all.
    """
    captures = []
    output = io.StringIO()

    class Recorded:
      def __init__(self, *args, **kwargs):
        captures.append((args, kwargs))

    class FakeApp:
      def __init__(self, session, interval=2.0):
        self.session = session

      def run(self):
        return None

    with contextlib.ExitStack() as stack:
      for name, value in (
          ("build_session",
           lambda *a, **k: (FakeSession(), self.FakeParticipant())),
          ("_wait_for_remote_participants", lambda *a, **k: True),
          ("_write_ready_file", lambda *a, **k: None),
          ("_settle", lambda session, seconds: None)):
        stack.enter_context(mock.patch.object(cli, name, value))
      stack.enter_context(mock.patch.object(cli.wire, "LiveCapture", Recorded))
      stack.enter_context(mock.patch("rti_doctor.app.RTIDoctorApp", FakeApp))
      stack.enter_context(mock.patch.object(
          sys, "stdin", mock.Mock(isatty=lambda: True)))
      stack.enter_context(redirect_stdout(output))
      stack.enter_context(mock.patch.object(sys, "stderr", io.StringIO()))
      code = cli.main(["--domain", "7", "--no-domain-scan"])

    self.assertEqual(code, 0)
    self.assertEqual(captures, [])
    self.assertNotIn("Capture interface", output.getvalue())
    self.assertNotIn("capture", output.getvalue().lower())

  def test_the_startup_capture_entry_points_are_gone(self):
    for name in ("start_discovery_capture", "select_discovery_capture_interface"):
      self.assertFalse(hasattr(cli, name), f"{name} still exists")

  def _run_tui(self, app_run):
    """Run main() down the TUI path with `app_run` as the app's run method."""
    session = FakeSession()

    class FakeApp:
      def __init__(self, session, interval=2.0):
        self.session = session

      def run(self):
        return app_run()

    with contextlib.ExitStack() as stack:
      for name, value in (
          ("build_session",
           lambda *a, **k: (session, self.FakeParticipant())),
          ("_wait_for_remote_participants", lambda *a, **k: True),
          ("_write_ready_file", lambda *a, **k: None),
          ("_settle", lambda s, seconds: None)):
        stack.enter_context(mock.patch.object(cli, name, value))
      stack.enter_context(mock.patch("rti_doctor.app.RTIDoctorApp", FakeApp))
      stack.enter_context(mock.patch.object(
          sys, "stdin", mock.Mock(isatty=lambda: True)))
      stack.enter_context(redirect_stdout(io.StringIO()))
      stack.enter_context(mock.patch.object(sys, "stderr", io.StringIO()))
      code = cli.main(["--domain", "7", "--no-domain-scan"])
    return session, code

  def test_a_tui_that_raises_still_sweeps_its_captures(self):
    """CAP-1's leak is worst on exactly the run that failed.

    The sweep sat on the success path, so any exception out of the TUI left
    every PCAPNG and tshark log the session had written - and a session that
    crashed is the one whose captures nobody is coming back for.
    """
    def explode():
      raise RuntimeError("the terminal went away")

    session, code = self._run_tui(explode)

    self.assertEqual(code, cli.EXIT_CANNOT_START)
    self.assertEqual(session.swept, 1)

  def test_a_headless_run_sweeps_nothing(self):
    """`--topic --capture-interface` wrote the file that operator asked for."""
    session, _participant, _code = self._run()
    self.assertEqual(session.swept, 0)

  def test_a_capture_interface_is_accepted_without_a_topic(self):
    """It selects the TUI's capture interface; it does not start a capture."""
    args = cli.parse_args(["-d", "1", "--capture-interface", "lo"])
    self.assertEqual(args.capture_interface, "lo")

  def test_a_capture_interface_is_rejected_for_the_system_assessment(self):
    with self.assertRaises(SystemExit):
      with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
        cli.parse_args(["-d", "1", "--system", "--capture-interface", "lo"])

  def test_the_session_carries_the_requested_interface(self):
    session, _participant, _code = self._run()
    self.assertIsNone(session.capture_interface)


class TestExitContract(MainHarness):
  """M13: `1` must mean "a diagnosis ran and found an ERROR", and only that."""

  def test_a_startup_failure_is_four_and_not_one(self):
    def no_license(*args, **kwargs):
      raise RuntimeError("DDS_DomainParticipantFactory_create_participant: license")

    with self.assertLogs(level="ERROR"):
      _session, participant, code = self._run(build_session=no_license)
    self.assertEqual(code, cli.EXIT_CANNOT_START)
    self.assertIn("could not start", self.stderr)
    self.assertIn("license", self.stderr)
    # No traceback on stderr; --debug-log is where it goes instead.
    self.assertNotIn("Traceback", self.stderr)
    self.assertIn("--debug-log", self.stderr)
    # Nothing was created, so nothing is closed - and no NameError for it.
    self.assertEqual(participant.closed, 0)

  def test_a_run_that_dies_mid_diagnosis_is_four_and_not_one(self):
    def explode(*args, **kwargs):
      raise RuntimeError("participant handle is closed")

    with self.assertLogs(level="ERROR"):
      _session, participant, code = self._run(run_headless_system=explode)
    self.assertEqual(code, cli.EXIT_CANNOT_START)
    self.assertIn("could not complete this run", self.stderr)
    self.assertEqual(participant.closed, 1)

  def test_a_completed_assessment_with_errors_is_one(self):
    _session, _participant, code = self._run(
        run_headless_system=lambda *a, **k: cli.EXIT_ERROR_FINDINGS)
    self.assertEqual(code, 1)

  def test_an_interrupt_is_not_reported_as_an_operational_failure(self):
    """Ctrl-C is 130, so it must pass straight through the exit-4 guard."""
    def interrupt(*args, **kwargs):
      raise KeyboardInterrupt()

    _session, _participant, code = self._run(run_headless_system=interrupt)
    self.assertIsInstance(code, KeyboardInterrupt)

  def test_every_documented_exit_code_is_distinct(self):
    codes = (cli.EXIT_OK, cli.EXIT_ERROR_FINDINGS, cli.EXIT_TARGET_ABSENT,
             cli.EXIT_READINESS_TIMEOUT, cli.EXIT_CANNOT_START,
             cli.EXIT_INTERRUPTED)
    self.assertEqual(len(set(codes)), len(codes))
    self.assertEqual(codes, (0, 1, 2, 3, 4, 130))


class TestArgumentValidation(unittest.TestCase):
  """argparse accepts negatives, "nan" and "inf" for these; Connext does not."""

  def _rejects(self, argv):
    with self.assertRaises(SystemExit) as raised:
      with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
        cli.parse_args(argv)
    # L6: never EXIT_TARGET_ABSENT. A rejected command line and "the topic was
    # not found" were both 2, so a CI job acting on 2 read a typo as a clean
    # result from a run that never started.
    self.assertEqual(raised.exception.code, cli.EXIT_CANNOT_START)
    return raised.exception.code

  def test_a_rejected_command_line_is_not_the_topic_absent_code(self):
    """The collision itself, stated once rather than only via `_rejects`.

    Covers argparse's own rejections as well as the hand-written
    `parser.error` calls, because the two reach `SystemExit` by different
    paths and only the latter is exercised by the validation tests below.
    """
    for argv, why in (
        (["--no-such-flag"], "unknown flag"),
        (["-d", "not-a-number"], "argparse type conversion"),
        (["--topic", "T", "--system"], "hand-written parser.error"),
    ):
      with self.subTest(why=why):
        code = self._rejects(argv)
        self.assertNotEqual(code, cli.EXIT_TARGET_ABSENT)

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
