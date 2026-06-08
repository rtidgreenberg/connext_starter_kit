#!/usr/bin/env python3
"""Pure unit tests for service control identity and candidate selection."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core.services import (
    ServiceCandidateSelection,
    ServiceCandidateSource,
    ServiceControlIdentity,
    ServiceInstanceRef,
    ServiceKind,
    ServiceLaunchIntent,
    ServiceProcessCandidate,
    service_admin_target_key,
    service_label_prefix,
)


class TestServiceControlIdentity(unittest.TestCase):
    def test_label_prefix_is_service_name_safe(self):
        self.assertEqual(service_label_prefix("Recording Service"), "recording_service")
        self.assertEqual(service_label_prefix("  Replay / Test A  "), "replay_test_a")
        self.assertEqual(service_label_prefix("123"), "svc_123")
        self.assertEqual(service_label_prefix("***", fallback="recording"), "recording")

    def test_session_guid_creates_unique_control_name(self):
        intent = ServiceLaunchIntent(
            kind=ServiceKind.RECORDING,
            label="Recording Service",
            admin_domain_id="54",
            monitoring_domain_id="55",
            config_paths=["record.xml"],
        )

        first = ServiceControlIdentity(
            intent=intent,
            session_guid="11111111-2222-3333-4444-555555555555",
            created_at=1.0,
        )
        second = ServiceControlIdentity(
            intent=intent,
            session_guid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            created_at=2.0,
        )

        self.assertEqual(first.control_name, "recording_service_11111111")
        self.assertEqual(second.control_name, "recording_service_aaaaaaaa")
        self.assertNotEqual(first.control_name, second.control_name)
        self.assertEqual(first.service_ref.name, "recording_service_11111111")
        self.assertEqual(first.service_ref.admin_domain_id, 54)
        self.assertEqual(first.service_ref.monitoring_domain_id, 55)
        self.assertEqual(first.service_ref.config_paths, ("record.xml",))
        self.assertEqual(ServiceControlIdentity.from_dict(first.to_dict()), first)


class TestServiceProcessCandidate(unittest.TestCase):
    def test_candidate_round_trip_and_admin_key(self):
        service = ServiceInstanceRef(ServiceKind.REPLAY, "replay_d34a910f", admin_domain_id=9)
        candidate = ServiceProcessCandidate(
            candidate_id="candidate-1",
            service=service,
            source="discovery",
            display_label="Replay",
            pid="1234",
            hostname="dev-host",
            participant_key="01:02",
            participant_name="ReplayParticipant",
            application_guid="guid-1",
            config_paths=["replay.xml"],
            observed_state="RUNNING",
            metrics={"cpu_percent": 2.0},
            details={"db": "run_001"},
            owns_process=True,
            confidence="0.9",
            first_seen_at=10.0,
            last_seen_at=11.0,
        )

        self.assertEqual(candidate.source, ServiceCandidateSource.DISCOVERY)
        self.assertEqual(candidate.pid, 1234)
        self.assertEqual(candidate.admin_target_key, "replay:replay_d34a910f:admin=9")
        self.assertTrue(candidate.local_process_known)
        self.assertEqual(ServiceProcessCandidate.from_dict(candidate.to_dict()), candidate)


class TestServiceCandidateSelection(unittest.TestCase):
    def _candidate(
            self,
            candidate_id,
            service_name,
            pid=None,
            hostname="",
            owns_process=False,
            alive=True,
    ):
        return ServiceProcessCandidate(
            candidate_id=candidate_id,
            service=ServiceInstanceRef(ServiceKind.RECORDING, service_name, admin_domain_id=0),
            source=ServiceCandidateSource.GUI_LAUNCH if owns_process else ServiceCandidateSource.DISCOVERY,
            pid=pid,
            hostname=hostname,
            owns_process=owns_process,
            alive=alive,
            observed_state="RUNNING" if alive else "STOPPED",
        )

    def test_selection_defaults_to_first_alive_candidate(self):
        stopped = self._candidate("old", "recording_old", alive=False)
        running = self._candidate("new", "recording_new", pid=22, owns_process=True)
        selection = ServiceCandidateSelection(candidates=(stopped, running))

        self.assertEqual(selection.selected_candidate, running)
        self.assertEqual(selection.select("old").selected_candidate, stopped)
        with self.assertRaises(ValueError):
            selection.select("missing")
        self.assertEqual(ServiceCandidateSelection.from_dict(selection.to_dict()), selection)

    def test_duplicate_admin_target_disables_service_admin_controls(self):
        first = self._candidate("first", "recording_dup", pid=100, hostname="dev-host")
        second = self._candidate("second", "recording_dup", pid=101, hostname="dev-host")
        selection = ServiceCandidateSelection(candidates=(first, second), selected_candidate_id="first")

        availability = selection.control_availability(local_hostnames=("dev-host",))

        self.assertFalse(availability.service_admin_enabled)
        self.assertFalse(availability.process_terminate_enabled)
        self.assertTrue(availability.duplicate_admin_target)
        self.assertIn("duplicate service admin target", availability.reasons)
        self.assertEqual(
            [candidate.candidate_id for candidate in selection.candidates_for_admin_target(first.service)],
            ["first", "second"],
        )

    def test_process_termination_requires_failed_shutdown_and_local_identity(self):
        candidate = self._candidate("local", "recording_unique", pid=100, hostname="dev-host")
        selection = ServiceCandidateSelection(candidates=(candidate,), selected_candidate_id="local")

        before_failure = selection.control_availability(local_hostnames=("dev-host",))
        after_failure = selection.control_availability(
            local_hostnames=("dev-host",),
            graceful_shutdown_failed=True,
        )

        self.assertTrue(before_failure.service_admin_enabled)
        self.assertFalse(before_failure.process_terminate_enabled)
        self.assertIn("process termination requires failed graceful shutdown", before_failure.reasons)
        self.assertTrue(after_failure.service_admin_enabled)
        self.assertTrue(after_failure.process_terminate_enabled)

    def test_remote_pid_does_not_enable_process_termination(self):
        candidate = self._candidate("remote", "recording_unique", pid=100, hostname="lab-host")
        selection = ServiceCandidateSelection(candidates=(candidate,), selected_candidate_id="remote")

        availability = selection.control_availability(
            local_hostnames=("dev-host",),
            graceful_shutdown_failed=True,
        )

        self.assertTrue(availability.service_admin_enabled)
        self.assertFalse(availability.process_terminate_enabled)
        self.assertIn("process is not verified as local", availability.reasons)

    def test_owned_process_can_terminate_without_hostname_match(self):
        candidate = self._candidate("owned", "recording_unique", pid=100, owns_process=True)
        selection = ServiceCandidateSelection(candidates=(candidate,), selected_candidate_id="owned")

        availability = selection.control_availability(graceful_shutdown_failed=True)

        self.assertTrue(availability.process_terminate_enabled)

    def test_admin_target_key_ignores_monitoring_domain(self):
        first = ServiceInstanceRef(ServiceKind.RECORDING, "recording", 0, 10)
        second = ServiceInstanceRef(ServiceKind.RECORDING, "recording", 0, 20)

        self.assertEqual(service_admin_target_key(first), service_admin_target_key(second))


if __name__ == "__main__":
    unittest.main()
