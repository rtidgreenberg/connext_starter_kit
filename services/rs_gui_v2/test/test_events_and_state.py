#!/usr/bin/env python3
"""Pure unit tests for rs_gui_v2 command, event, and state models."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand, AppEvent, AppState, CommandResult, CommandStatus, LifecyclePhase


class TestAppCommand(unittest.TestCase):
    def test_command_round_trip_to_dict(self):
        command = AppCommand(
            command_type="service.pause",
            target="recording:deploy",
            payload={"resource": "/recording_services/deploy/state"},
            command_id="cmd-1",
            created_at=123.0,
            timeout_sec=5.0,
        )

        self.assertEqual(AppCommand.from_dict(command.to_dict()), command)

    def test_command_payload_is_copied(self):
        payload = {"field": "original"}
        command = AppCommand(command_type="test", payload=payload)

        payload["field"] = "changed"

        self.assertEqual(command.payload["field"], "original")
        with self.assertRaises(TypeError):
            command.payload["new"] = "blocked"


class TestCommandResult(unittest.TestCase):
    def test_ok_for_acknowledged_and_observed_results(self):
        acknowledged = CommandResult("cmd-1", CommandStatus.ACKNOWLEDGED)
        observed = CommandResult("cmd-1", CommandStatus.OBSERVED)
        failed = CommandResult("cmd-1", CommandStatus.FAILED)

        self.assertTrue(acknowledged.ok)
        self.assertTrue(observed.ok)
        self.assertFalse(failed.ok)

    def test_result_status_accepts_serialized_value(self):
        result = CommandResult("cmd-1", "timeout", message="no reply")

        self.assertEqual(result.status, CommandStatus.TIMEOUT)
        self.assertEqual(result.to_dict()["status"], "timeout")


class TestAppEvent(unittest.TestCase):
    def test_lifecycle_event_payload(self):
        event = AppEvent.lifecycle_changed(LifecyclePhase.STOPPED, LifecyclePhase.RUNNING)

        self.assertEqual(event.event_type, "runtime.lifecycle_changed")
        self.assertEqual(event.payload["previous"], "stopped")
        self.assertEqual(event.payload["current"], "running")


class TestAppState(unittest.TestCase):
    def test_state_snapshot_copies_mutable_mappings(self):
        services = {"recorder": {"state": "running"}}
        state = AppState(lifecycle=LifecyclePhase.RUNNING, services=services)

        services["recorder"] = {"state": "paused"}

        self.assertEqual(state.services["recorder"], {"state": "running"})
        with self.assertRaises(TypeError):
            state.services["new"] = {}

    def test_state_round_trip_to_dict(self):
        state = AppState(
            lifecycle=LifecyclePhase.RUNNING,
            dds_enabled=True,
            services={"recording": "ok"},
            recent_errors=("one",),
        )

        restored = AppState.from_dict(state.to_dict())

        self.assertEqual(restored, state)

    def test_with_lifecycle_returns_new_state(self):
        state = AppState()

        running = state.with_lifecycle(LifecyclePhase.RUNNING)

        self.assertEqual(state.lifecycle, LifecyclePhase.STOPPED)
        self.assertEqual(running.lifecycle, LifecyclePhase.RUNNING)


if __name__ == "__main__":
    unittest.main()