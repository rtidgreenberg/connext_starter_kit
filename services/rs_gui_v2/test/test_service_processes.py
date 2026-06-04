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
    SubprocessServiceProcessSpawner,
)


class FakeHandle:
    def __init__(self, pid=4321, output_path=""):
        self.pid = pid
        self.returncode = None
        self.terminate_calls = 0
        self.output_path = output_path

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


class QueueSpawner:
    def __init__(self, *handles):
        self.handles = list(handles)
        self.calls = []

    def start(self, command_line, working_dir="", environment=None):
        self.calls.append({
            "command_line": tuple(command_line),
            "working_dir": working_dir,
            "environment": dict(environment or {}),
        })
        if not self.handles:
            raise RuntimeError("no fake handles queued")
        return self.handles.pop(0)


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
        repo_root = os.path.dirname(os.path.dirname(PARENT_DIR))
        self.assertEqual(
            command[command.index("-cfgFile") + 1],
            ";".join(
                (
                    os.path.join(repo_root, "recording_service_config.xml"),
                    os.path.join(repo_root, "DDS_QOS_PROFILES.xml"),
                )
            ),
        )
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
    def test_default_spawner_logs_under_rs_gui_service_logs(self):
        spawner = SubprocessServiceProcessSpawner()
        repo_root = os.path.dirname(os.path.dirname(PARENT_DIR))

        self.assertEqual(
            spawner._log_dir,
            os.path.join(repo_root, "services", "rs_gui_v2", "service_logs"),
        )

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
        self.assertEqual(candidate.details["admin_resource_name"], "deploy")
        self.assertEqual(candidate.details["config_name"], "deploy")
        self.assertEqual(candidate.details["working_dir"], "/workspace/services")

    def test_launch_records_process_output_path_for_console_payloads(self):
        output_dir = os.path.join("services", "rs_gui_v2", "service_logs", "service_process_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "recording.log")
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write("startup line\n")
        handle = FakeHandle(pid=4321, output_path=output_path)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle=handle),
            hostname="dev-host",
            clock=iter((10.0, 11.0, 12.0, 13.0)).__next__,
        )

        launch = manager.launch(
            self._request(),
            launch_id="launch-1",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        candidate = candidate_from_process_launch(launch)

        self.assertEqual(launch.to_dict()["output_path"], output_path)
        self.assertEqual(candidate.details["output_path"], output_path)

    def test_process_exit_updates_candidate_alive_state(self):
        output_dir = os.path.join("services", "rs_gui_v2", "service_logs", "service_process_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "early_exit.log")
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write("service startup failed\nmissing config\n")
        handle = FakeHandle(pid=4321, output_path=output_path)
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
        self.assertEqual(candidate.details["output_path"], output_path)
        self.assertIn("missing config", candidate.details["output_tail"])
        self.assertIn(output_path, refreshed.message)

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

    def test_local_termination_not_allowed_includes_output_tail(self):
        output_dir = os.path.join("services", "rs_gui_v2", "service_logs", "service_process_tests")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "terminated_before_button.log")
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write("startup failed before admin endpoint\n")
        handle = FakeHandle(pid=4321, output_path=output_path)
        manager = ServiceProcessManager(
            spawner=FakeSpawner(handle=handle),
            hostname="dev-host",
            clock=iter((1.0, 2.0, 3.0, 4.0, 5.0)).__next__,
        )
        launch = manager.launch(
            self._request(),
            launch_id="launch-1",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        handle.returncode = 7
        selection = manager.candidate_selection(launch.identity.service_ref)

        outcome = manager.request_local_termination(
            selection,
            graceful_shutdown_failed=True,
            local_hostnames=("dev-host",),
        )

        self.assertEqual(outcome.status, ServiceProcessTerminationStatus.NOT_ALLOWED)
        self.assertIn("candidate is not alive", outcome.message)
        self.assertEqual(outcome.to_dict()["output_path"], output_path)
        self.assertIn("startup failed", outcome.to_dict()["output_tail"])

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

    def test_restart_churn_keeps_fresh_control_identity_and_old_exit_evidence(self):
        first_handle = FakeHandle(pid=4321)
        second_handle = FakeHandle(pid=4322)
        manager = ServiceProcessManager(
            spawner=QueueSpawner(first_handle, second_handle),
            hostname="dev-host",
            clock=iter(float(value) for value in range(1, 30)).__next__,
        )

        first = manager.launch(
            self._request(),
            launch_id="launch-old",
            session_guid="11111111-2222-3333-4444-555555555555",
        )
        manager.refresh("launch-old")
        first_handle.returncode = 0
        exited = manager.refresh("launch-old")
        second = manager.launch(
            self._request(),
            launch_id="launch-new",
            session_guid="22222222-3333-4444-5555-666666666666",
        )
        manager.refresh("launch-new")

        launches = {launch.launch_id: launch for launch in manager.launches()}
        new_selection = manager.candidate_selection(second.identity.service_ref)
        old_selection = manager.candidate_selection(first.identity.service_ref)

        self.assertEqual(exited.state, ServiceProcessLaunchState.EXITED)
        self.assertEqual(launches["launch-old"].state, ServiceProcessLaunchState.EXITED)
        self.assertEqual(launches["launch-new"].state, ServiceProcessLaunchState.RUNNING)
        self.assertNotEqual(first.identity.service_ref.name, second.identity.service_ref.name)
        self.assertEqual(new_selection.selected_candidate.candidate_id, "launch-new")
        self.assertTrue(new_selection.selected_candidate.alive)
        self.assertEqual(old_selection.selected_candidate.candidate_id, "launch-old")
        self.assertFalse(old_selection.selected_candidate.alive)
        self.assertEqual(old_selection.selected_candidate.details["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
