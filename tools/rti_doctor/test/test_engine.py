"""Unit tests for `engine.Session` state that needs no DDS entities.

The capture question and the capture-artifact retention policy are both plain
session bookkeeping, so they are tested against a `Session` built with `None` for
everything DDS - the methods under test never reach for the participant or the
registry.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import engine, records  # noqa: E402


def bare_session(capture_interface=None):
  """A Session with no DDS anything; enough for the bookkeeping under test."""
  return engine.Session(participant=None, registry=None, own_qos=None,
                        type_lookup_settings=None, domain_id=7,
                        capture_interface=capture_interface)


class TestTheCaptureQuestion(unittest.TestCase):
  """Who answered, what they answered, and whether it is still being asked.

  A report asks on entry only while the question is unanswered, so "no answer
  yet" and "answered Skip" have to be distinguishable - both leave
  `capture_interface` None.
  """

  def test_a_fresh_session_has_not_answered(self):
    session = bare_session()
    self.assertFalse(session.capture_choice_made)
    self.assertIsNone(session.capture_interface)
    self.assertIsNone(session.capture_off_reason)

  def test_the_command_line_flag_answers_it_up_front(self):
    """`--capture-interface` is the non-interactive answer, so nothing asks."""
    session = bare_session("eth0")
    self.assertTrue(session.capture_choice_made)
    self.assertEqual(session.capture_interface, "eth0")

  def test_skip_is_an_answer_not_the_absence_of_one(self):
    session = bare_session()
    session.record_capture_choice(None)
    self.assertTrue(session.capture_choice_made)
    self.assertIsNone(session.capture_interface)

  def test_a_failure_turns_capture_off_without_reopening_the_question(self):
    session = bare_session("lo")
    session.disable_capture("you don't have permission to capture")
    self.assertIsNone(session.capture_interface)
    self.assertTrue(session.capture_choice_made)
    self.assertIn("permission", session.capture_off_reason)

  def test_choosing_again_is_what_turns_capture_back_on(self):
    """`C` is the re-enable gesture: a new choice retires the old reason."""
    session = bare_session("lo")
    session.disable_capture("tshark was not found on PATH")
    session.record_capture_choice("eth0")
    self.assertIsNone(session.capture_off_reason)
    self.assertEqual(session.capture_interface, "eth0")


class TestTheDiagnosticPassClaimExpires(unittest.TestCase):
  """Single-flight that cannot be left held.

  Only one probe+capture pass may run at a time: two on one topic would each
  observe the other's traffic. The claim has to outlive the screen that took it,
  because `asyncio.to_thread` cannot be cancelled and a popped report leaves
  tshark running - so it cannot simply be released when a screen goes away.

  That makes "the holder never comes back" the failure to design for. It is
  reachable: a worker cancelled between being scheduled and first running
  executes neither its own `finally` nor the thread's, and a flag left set that
  way dead-ends every later report, `c` and `C` included, for the life of the
  session. So the claim is a deadline, like the `-a duration:` ceiling that
  stops an abandoned tshark.
  """

  def test_a_claim_holds_for_its_window(self):
    session = bare_session()
    self.assertFalse(session.pass_in_flight())
    session.claim_pass(60.0)
    self.assertTrue(session.pass_in_flight())

  def test_releasing_ends_it_immediately(self):
    session = bare_session()
    session.claim_pass(60.0)
    session.release_pass()
    self.assertFalse(session.pass_in_flight())

  def test_releasing_twice_is_harmless(self):
    """Released from the worker thread and the coroutine, so it happens twice."""
    session = bare_session()
    session.claim_pass(60.0)
    session.release_pass()
    session.release_pass()
    self.assertFalse(session.pass_in_flight())

  def test_a_claim_nobody_releases_expires_by_itself(self):
    """The case no `finally` can reach, and the reason this is not a flag."""
    session = bare_session()
    session.claim_pass(30.0)
    self.assertTrue(session.pass_in_flight())

    # Nothing releases it - the holder was cancelled before it ever ran.
    with mock.patch.object(engine.time, "monotonic",
                           return_value=time.monotonic() + 31.0):
      self.assertFalse(session.pass_in_flight())

  def test_the_window_outlives_the_capture_it_protects(self):
    """Expiring early would let a second pass overlap a live tshark.

    The claim is taken for the probe window plus the same margin tshark's own
    ceiling gets, so the claim cannot lapse while a capture it was protecting
    is still running.
    """
    session = bare_session()
    probe_window = 10.0
    session.claim_pass(probe_window + engine.CAPTURE_DURATION_MARGIN)

    with mock.patch.object(engine.time, "monotonic",
                           return_value=time.monotonic() + probe_window + 1.0):
      self.assertTrue(session.pass_in_flight())


class TestTypeInformationObservedIsThreeValued(unittest.TestCase):
  """"Nobody looked" is not "the peer did not advertise it".

  The finding records this in its evidence, so `False` where no capture ran
  puts a claim about the peer into a saved report that nothing supports. It is
  the common case, not a corner: a passively opened report, a `Skip`, or any
  headless run without `--capture-interface`.
  """

  def endpoint(self):
    return records.EndpointRecord(key="w1", kind="Writer", participant_key="p1",
                                  topic_name="Telemetry", type_name="T")

  def test_no_capture_is_none_rather_than_false(self):
    self.assertIsNone(engine._type_information_observed(self.endpoint(), None))
    self.assertIsNone(engine._type_information_observed(self.endpoint(), {}))

  def test_a_failed_capture_looked_at_nothing_either(self):
    self.assertIsNone(engine._type_information_observed(
        self.endpoint(), {"error": "you don't have permission to capture"}))

  def test_a_capture_that_saw_none_is_false(self):
    self.assertIs(False, engine._type_information_observed(
        self.endpoint(), {"type_information_participants": ()}))

  def test_a_capture_that_saw_this_peer_is_true(self):
    endpoint = self.endpoint()
    prefix = engine.wire.record_guid_prefix(endpoint)
    self.assertIs(True, engine._type_information_observed(
        endpoint, {"type_information_participants": (prefix,)}))

  def test_every_value_that_is_not_true_stays_falsy(self):
    """The remedy text gates on this, and must not change with the third value."""
    for evidence in (None, {}, {"error": "x"}, {"type_information_participants": ()}):
      self.assertFalse(engine._type_information_observed(self.endpoint(), evidence))


class TestCaptureArtifactsAreBounded(unittest.TestCase):
  """CAP-1/N2: a browsing session must not leave a file per report opened.

  Capture is offered on entry to every endpoint report, so the artifacts that
  H8 made visible are now produced per navigation. Nothing removed them: the
  checkout held 24 leftovers when it was cleared by hand for the 2026-08-11
  handover.
  """

  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.directory = directory.name
    # This policy reads the environment, and a developer with the opt-out set
    # would otherwise see every assertion below invert.
    patcher = mock.patch.dict(os.environ, {}, clear=False)
    patcher.start()
    self.addCleanup(patcher.stop)
    os.environ.pop("RTI_DOCTOR_KEEP_ARTIFACTS", None)

  def capture(self, name):
    """A written capture and the tshark log beside it, as a real one leaves."""
    path = os.path.join(self.directory, name)
    for candidate in (path, f"{path}.tshark.log"):
      with open(candidate, "w", encoding="utf-8") as handle:
        handle.write("x")
    return path

  def test_an_unsaved_capture_and_its_log_are_removed_together(self):
    """The log is only readable against its capture, so it goes with it."""
    session = bare_session()
    path = self.capture("one.pcapng")
    session.capture_artifacts.append(path)

    removed = session.sweep_capture_artifacts()

    self.assertEqual(sorted(removed), sorted([path, f"{path}.tshark.log"]))
    self.assertFalse(os.path.exists(path))
    self.assertFalse(os.path.exists(f"{path}.tshark.log"))

  def test_a_capture_a_saved_report_cites_survives(self):
    """Appendix C names the capture; sweeping it would break the citation."""
    session = bare_session()
    kept, swept = self.capture("kept.pcapng"), self.capture("swept.pcapng")
    session.capture_artifacts.extend([kept, swept])
    session.retain_capture(kept)

    session.sweep_capture_artifacts()

    self.assertTrue(os.path.exists(kept))
    self.assertTrue(os.path.exists(f"{kept}.tshark.log"))
    self.assertFalse(os.path.exists(swept))

  def test_retention_matches_on_the_resolved_path(self):
    """A report cites an absolute path; the session may hold a relative one."""
    session = bare_session()
    path = self.capture("two.pcapng")
    session.capture_artifacts.append(os.path.relpath(path))
    session.retain_capture(path)

    self.assertEqual(session.sweep_capture_artifacts(), [])
    self.assertTrue(os.path.exists(path))

  def test_the_keep_opt_out_sweeps_nothing(self):
    """Matches HAR-3's `RTI_DOCTOR_KEEP_ARTIFACTS`, rather than a second name."""
    session = bare_session()
    path = self.capture("three.pcapng")
    session.capture_artifacts.append(path)

    with mock.patch.dict(os.environ, {"RTI_DOCTOR_KEEP_ARTIFACTS": "1"}):
      self.assertEqual(session.sweep_capture_artifacts(), [])
    self.assertTrue(os.path.exists(path))

  def test_a_missing_artifact_is_not_an_error(self):
    """This runs on the way out; a failed unlink must not become the exit code.

    A capture that tshark never managed to write still gets recorded, because
    the path is taken before the capture runs.
    """
    session = bare_session()
    session.capture_artifacts.append(
        os.path.join(self.directory, "never_written.pcapng"))
    self.assertEqual(session.sweep_capture_artifacts(), [])

  def test_an_undeletable_artifact_is_logged_rather_than_raised(self):
    session = bare_session()
    path = self.capture("locked.pcapng")
    session.capture_artifacts.append(path)

    with mock.patch.object(engine.os, "remove",
                           side_effect=PermissionError("read-only file system")):
      self.assertEqual(session.sweep_capture_artifacts(), [])


if __name__ == "__main__":
  unittest.main()
