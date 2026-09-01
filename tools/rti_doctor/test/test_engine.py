"""Unit tests for `engine.Session` state that needs no DDS entities."""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import engine, records  # noqa: E402


def bare_session(probe_default=True):
  """A Session with no DDS anything; enough for the bookkeeping under test."""
  return engine.Session(participant=None, registry=None, own_qos=None,
                        type_lookup_settings=None, domain_id=7,
                        probe_default=probe_default)


class TestProbeDefaults(unittest.TestCase):
  def test_probe_default_is_configurable_for_the_session(self):
    self.assertTrue(bare_session().probe_default)
    self.assertFalse(bare_session(probe_default=False).probe_default)


class TestTheDiagnosticPassClaimExpires(unittest.TestCase):
  """Single-flight that cannot be left held across a cancelled worker."""

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

class TestTypeInformationObservedIsThreeValued(unittest.TestCase):
  """"Nobody looked" is not "the peer did not advertise it".

  The finding records this in its evidence, so `False` where no capture ran
  puts a claim about the peer into a saved report that nothing supports. It is
  the common case, not a corner: a passively opened report or a headless run.
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
    """Create a written RTI Network Capture artifact."""
    path = os.path.join(self.directory, name)
    with open(path, "w", encoding="utf-8") as handle:
      handle.write("x")
    return path

  def test_an_unsaved_capture_is_removed(self):
    session = bare_session()
    path = self.capture("one.pcapng")
    session.capture_artifacts.append(path)

    removed = session.sweep_capture_artifacts()

    self.assertEqual(removed, [path])
    self.assertFalse(os.path.exists(path))

  def test_a_capture_a_saved_report_cites_survives(self):
    """Appendix C names the capture; sweeping it would break the citation."""
    session = bare_session()
    kept, swept = self.capture("kept.pcapng"), self.capture("swept.pcapng")
    session.capture_artifacts.extend([kept, swept])
    session.retain_capture(kept)

    session.sweep_capture_artifacts()

    self.assertTrue(os.path.exists(kept))
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

    A capture that never produced a file still gets recorded, because the path
    is taken before capture starts.
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
