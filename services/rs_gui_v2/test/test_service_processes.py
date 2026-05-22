#!/usr/bin/env python3
"""Pure unit tests for local RTI service process launch/control helpers."""

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
    ServiceProcessLaunchRequest,
    ServiceProcessLaunchState,
    ServiceProcessManager,
    ServiceProcessTerminationStatus,
    build_service_process_command,
    candidate_from_process_launch,
)


class FakeHandle:
    def __init__(self, pid=4321):
        self.pid = pid
        self.returncode = None
        self.terminate_calls = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1


class FakeSpawner:
    def __init__(self, handle=None, error=None):
        self.handle = handle or FakeHandle()
        self.error = error
        self.calls = []

    def start(self, command_line, working_dir="", environment=None):
        self.calls.append({
            "command_line": tuple(command_line),
            "working_dir": working_dir,
            "environment": dict(environment or {}),
        })
        if self.error:
            raise self.error
        return self.handle


class TestServiceProcessCommand(unittest.TestCase):
    def test_recording_command_uses_app_name_and_admin_domains(self):
        intent = ServiceLaunchIntent(
            kind=ServiceKind.RECORDING,
            label="Main Recorder",
            admin_domain_id=54,
            monitoring_domain_id=55,
            config_paths=("recording_service_config.xml", "DDS_QOS_PROFILES.xml"),
        )
        identity = ServiceControlIdentity(
            intent=intent,
            session_guid="11111111-2222-3333-4444-555555555555",
            created_at=1.0,
        )
        request = ServiceProcessLaunchRequest(
            intent=intent,
            config_name="deploy",
            executable="/opt/rti/bin/rtirecordingservice",
            verbosity="WARN:LOCAL",
            domain_id_base=10,
            extra_args=("-DDB_DIR=/tmp/run_001",),
        )

        command = build_service_process_command(identity, request)

        self.assertEqual(command[0], "/opt/rti/bin/rtirecordingservice")
        self.assertIn("-cfgName", command)
        self.assertEqual(command[command.index("-cfgName") + 1], "deploy")
        self.assertIn("-appName", command)
        self.assertEqual(command[command.index("-appName") + 1], "main_recorder_11111111")
        self.assertEqual(command[command.index("-remoteAdministrationDomainId") + 1], "54")
        self.assertEqual(command[command.index("-remoteMonitoringDomainId") + 1], "55")
        self.assertEqual(command[command.index("-cfgFile") + 1], "recording_service_config.xml;DDS_QOS_PROFILES.xml")
        self.assertIn("-DDB_DIR=/tmp/run_001", command)

    def test_replay_command_uses_replay_binary_and_runtime_app_name(self):
        intent = ServiceLaunchIntent(
            kind=ServiceKind.REPLAY,
            label="Replay A",
            config_paths=("replay_service_config.xml",),
        )
        identity = ServiceControlIdentity(
            intent=intent,
            session_guid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            created_at=1.0,
        )
        request = ServiceProcessLaunchRequest(intent=intent, config_name="xcdr")

        command = build_service_process_command(identity, request)

        self.assertTrue(command[0].endswith("rtireplayservice"))
        self.assertEqual(command[command.index("-appName") + 1], "replay_a_aaaaaaaa")
        self.assertEqual(command[command.index("-cfgName") + 1], "xcdr")

    def test_command_uses_request_nddshome_when_executable_is_not_explicit(self):
        intent = ServiceLaunchIntent(kind=ServiceKind.RECORDING, label="Record")
        identity = ServiceControlIdentity(
            intent=intent,
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        request = ServiceProcessLaunchRequest(
            intent=intent,
            config_name="deploy",
            environment={"NDDSHOME": "/opt/rti"},
        )

        command = build_service_process_command(identity, request)

        self.assertEqual(command[0], "/opt/rti/bin/rtirecordingservice")


class TestServiceProcessManager(unittest.TestCase):
    def _request(self):
        return ServiceProcessLaunchRequest(
            intent=ServiceLaunchIntent(
                kind=ServiceKind.RECORDING,
                label="Main Recorder",
                admin_domain_id=1,
                monitoring_domain_id=2,
                config_paths=("record.xml", "qos.xml"),
            ),
            config_name="deploy",
            executable="/opt/rti/bin/rtirecordingservice",
            working_dir="/workspace/services",
            environment={"NDDSHOME": "/opt/rti"},
        )

    def test_launch_records_process_evidence_and_builds_candidate_selection(self):
        handle = FakeHandle(pid=4321)
        spawner = FakeSpawner(handle=handle)
        manager = ServiceProcessManager(
            spawner=spawner,
            hostname="dev-host",
            clock=iter((10.0, 11.0, 12.0, 13.0)).__next__,
        )

        launch = manager.launch(
            self._request(),
            launch_id="launch-1",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        selection = manager.candidate_selection(launch.identity.service_ref)
        candidate = selection.selected_candidate

        self.assertEqual(spawner.calls[0]["working_dir"], "/workspace/services")
        self.assertEqual(spawner.calls[0]["environment"], {"NDDSHOME": "/opt/rti"})
        self.assertEqual(launch.pid, 4321)
        self.assertEqual(launch.hostname, "dev-host")
        self.assertEqual(candidate.candidate_id, "launch-1")
        self.assertEqual(candidate.service.name, "main_recorder_11111111")
        self.assertEqual(candidate.source, ServiceCandidateSource.GUI_LAUNCH)
        self.assertEqual(candidate.pid, 4321)
        self.assertEqual(candidate.hostname, "dev-host")
        self.assertTrue(candidate.owns_process)
        self.assertEqual(candidate.observed_state, ServiceProcessLaunchState.RUNNING.value)
        self.assertEqual(candidate.details["command_line"], list(spawner.calls[0]["command_line"]))
        self.assertEqual(candidate.details["working_dir"], "/workspace/services")

    def test_process_exit_updates_candidate_alive_state(self):
        handle = FakeHandle(pid=4321)
        spawner = FakeSpawner(handle=handle)
        manager = ServiceProcessManager(
            spawner=spawner,
            hostname="dev-host",
            clock=iter((1.0, 2.0, 3.0, 4.0)).__next__,
        )
        launch = manager.launch(
            self._request(),
            launch_id="launch-1",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        handle.returncode = 7

        refreshed = manager.refresh("launch-1")
        candidate = candidate_from_process_launch(refreshed)

        self.assertEqual(refreshed.state, ServiceProcessLaunchState.EXITED)
        self.assertEqual(refreshed.returncode, 7)
        self.assertFalse(candidate.alive)
        self.assertEqual(candidate.details["returncode"], 7)

    def test_local_termination_requires_failed_graceful_shutdown(self):
        handle = FakeHandle(pid=4321)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle=handle),
            hostname="dev-host",
            clock=iter((1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)).__next__,
        )
        launch = manager.launch(
            self._request(),
            launch_id="launch-1",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        selection = manager.candidate_selection(launch.identity.service_ref)

        denied = manager.request_local_termination(
            selection,
            graceful_shutdown_failed=False,
            local_hostnames=("dev-host",),
        )
        allowed = manager.request_local_termination(
            selection,
            graceful_shutdown_failed=True,
            local_hostnames=("dev-host",),
        )

        self.assertEqual(denied.status, ServiceProcessTerminationStatus.NOT_ALLOWED)
        self.assertIn("requires failed graceful shutdown", denied.message)
        self.assertEqual(allowed.status, ServiceProcessTerminationStatus.REQUESTED)
        self.assertTrue(allowed.requested)
        self.assertEqual(handle.terminate_calls, 1)
        self.assertEqual(manager.refresh("launch-1").state, ServiceProcessLaunchState.TERMINATE_REQUESTED)

    def test_remote_discovered_candidate_cannot_be_terminated(self):
        manager = ServiceProcessManager(hostname="dev-host")
        remote = ServiceProcessCandidate(
            candidate_id="remote",
            service=ServiceInstanceRef(ServiceKind.RECORDING, "remote_recording"),
            pid=4321,
            hostname="lab-host",
            owns_process=False,
            observed_state="running",
        )
        selection = ServiceCandidateSelection(candidates=(remote,), selected_candidate_id="remote")

        outcome = manager.request_local_termination(
            selection,
            graceful_shutdown_failed=True,
            local_hostnames=("dev-host",),
        )

        self.assertEqual(outcome.status, ServiceProcessTerminationStatus.NOT_ALLOWED)
        self.assertIn("not verified as local", outcome.message)

    def test_launch_failure_returns_start_failed_candidate(self):
        manager = ServiceProcessManager(
            spawner=FakeSpawner(error=RuntimeError("missing executable")),
            hostname="dev-host",
            clock=iter((1.0, 2.0, 3.0)).__next__,
        )

        launch = manager.launch(
            self._request(),
            launch_id="launch-1",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        candidate = candidate_from_process_launch(launch)

        self.assertEqual(launch.state, ServiceProcessLaunchState.START_FAILED)
        self.assertFalse(candidate.alive)
        self.assertEqual(candidate.details["message"], "missing executable")


if __name__ == "__main__":
    unittest.main()
