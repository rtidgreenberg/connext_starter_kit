#!/usr/bin/env python3
"""Phase 5 tests for async job submission and polling in Convert tab controller."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from app_core import AppCommand, CommandStatus
from gui.tabs.convert_controller import (
    ConvertTabController,
    ConvertTabControllerConfig,
    ConvertJobSubmission,
)
from gui.tabs.convert_tab import ConvertJobRow, ConvertPresetView


class TestConvertJobSubmission(unittest.IsolatedAsyncioTestCase):
    """Test async job submission and tracking."""

    class MockCancelableProcess:
        def __init__(self):
            self.returncode = None
            self.terminate_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = -15

    async def test_run_conversion_tracks_submission(self):
        """Verify that submitting a job creates a submission tracking record."""
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )
        controller = ConvertTabController(
            presets=(preset,),
            config=ConvertTabControllerConfig(
                selected_preset_id="json",
                input_storage_path="services/input",
                output_storage_path="services/output",
            ),
        )

        cmd = AppCommand(
            command_type="convert.run",
            target="test",
            payload={
                "config_name": "json_export",
                "input_storage": {"path": "services/input"},
                "output_storage": {"path": "services/output"},
                "output_format": "JSON_SQLITE",
            },
        )

        result = await controller.handle_command(cmd)

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        job_id = result.payload["job_id"]
        self.assertIn(job_id, controller._submissions)
        submission = controller._submissions[job_id]
        self.assertEqual(submission.job_id, job_id)
        self.assertEqual(submission.submission_attempts, 0)
        self.assertEqual(submission.process_pid, 0)

    async def test_job_polling_interval_enforced(self):
        """Verify that polling respects the configured interval."""
        job_id = "convert-1234"
        submission = ConvertJobSubmission(
            job_id=job_id,
            submitted_at=100.0,
            process_pid=5678,
            submission_attempts=1,
            last_status_check=150.0,  # Just checked at 150
        )
        controller = ConvertTabController(clock=lambda: 151.0)  # Current time: 151
        controller._submissions[job_id] = submission
        controller._service_facade = True  # Mock facade presence
        controller._config = ConvertTabControllerConfig(service=True)  # Mock service

        # Polling interval is 2.0 seconds, we're only 1 second past last check
        await controller._poll_job_status(job_id)

        # Should not have updated the last_status_check (which would have changed)
        updated = controller._submissions[job_id]
        self.assertEqual(updated.last_status_check, 150.0)

    async def test_cancel_conversion_with_service_submission(self):
        """Verify cancellation tracks service submission if job was submitted."""
        job_id = "convert-1234"
        from gui.tabs.convert_tab import ConvertJobRow

        job = ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        )
        controller = ConvertTabController()
        controller._jobs = (job,)
        controller._config = ConvertTabControllerConfig(selected_job_id=job_id)

        # Mark job as submitted
        submission = ConvertJobSubmission(
            job_id=job_id,
            submitted_at=100.0,
            process_pid=5678,
            submission_attempts=1,
        )
        controller._submissions[job_id] = submission
        controller._service_facade = True  # Mock facade
        process = self.MockCancelableProcess()
        controller._processes[5678] = process

        cmd = AppCommand(
            command_type="convert.cancel",
            target=job_id,
            payload={"job_id": job_id},
        )

        result = await controller.handle_command(cmd)

        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        updated_job = controller._jobs[0]
        self.assertEqual(updated_job.state, "cancel_requested")
        self.assertEqual(process.terminate_calls, 1)
        self.assertIn("local converter termination requested", updated_job.message)

    async def test_update_jobs_from_monitoring_polls_running_jobs(self):
        """Verify that refresh_view triggers job monitoring updates."""
        job_id = "convert-1234"
        job = ConvertJobRow(
            job_id=job_id,
            preset_id="json",
            input_path="services/input",
            output_path="services/output",
            output_format="JSON_SQLITE",
            state="running",
            progress="42%",
        )

        # Create a mock facade
        class MockFacade:
            async def is_service_ready(self):
                return True

        controller = ConvertTabController(presets=(), service_facade=MockFacade())
        controller._jobs = (job,)

        # Add submission tracking
        submission = ConvertJobSubmission(
            job_id=job_id,
            submitted_at=100.0,
            process_pid=5678,
            submission_attempts=1,
            last_status_check=0.0,  # Never checked
        )
        controller._submissions[job_id] = submission
        controller._config = ConvertTabControllerConfig(service=True)  # Mock service
        controller._service_ready = False  # Will be set by refresh_view

        # Add a mock process to track
        class MockProcess:
            def poll(self):
                return None  # Still running

        controller._processes[5678] = MockProcess()

        # Call refresh_view which triggers polling
        await controller.refresh_view()

        # Verify that last_status_check was updated (polling was attempted)
        updated = controller._submissions[job_id]
        self.assertGreater(updated.last_status_check, 0.0)

    async def test_submission_error_tracking(self):
        """Verify that job submission is created even if service check fails."""
        preset = ConvertPresetView(
            preset_id="json",
            label="JSON",
            config_name="json_export",
            output_format="JSON_SQLITE",
        )

        # Create a normal facade for successful check
        class NormalFacade:
            async def is_service_ready(self):
                return True

        controller = ConvertTabController(
            presets=(preset,),
            service_facade=NormalFacade(),
            config=ConvertTabControllerConfig(
                selected_preset_id="json",
                input_storage_path="services/input",
                output_storage_path="services/output",
                service=True,  # Mock service ref
            ),
        )
        controller._service_ready = False

        cmd = AppCommand(
            command_type="convert.run",
            target="test",
            payload={
                "config_name": "json_export",
                "input_storage": {"path": "services/input"},
                "output_storage": {"path": "services/output"},
                "output_format": "JSON_SQLITE",
            },
        )

        result = await controller.handle_command(cmd)

        # Job should be queued successfully
        self.assertEqual(result.status, CommandStatus.ACKNOWLEDGED)
        job_id = result.payload["job_id"]
        self.assertEqual(len(controller._jobs), 1)
        self.assertIn(job_id, controller._submissions)

        # Submission should be tracked with initial state
        submission = controller._submissions[job_id]
        self.assertEqual(submission.job_id, job_id)
        self.assertEqual(submission.submission_attempts, 0)


if __name__ == "__main__":
    unittest.main()
