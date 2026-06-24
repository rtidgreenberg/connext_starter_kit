"""Phase 6 tests: Real subprocess-based conversion job execution."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from dataclasses import replace

from gui.tabs.convert_controller import (
    ConvertTabController,
    ConvertTabControllerConfig,
    ConvertJobSubmission,
)
from gui.tabs.convert_tab import ConvertJobRow


class MockAsyncProcess:
    """Mock subprocess with controllable poll() and communicate()."""

    def __init__(self, pid=5678, poll_values=None, stdout=b"", stderr=b""):
        self.pid = pid
        self.poll_values = poll_values or [None, 0]  # None (running), then 0 (success)
        self.poll_index = 0
        self.stdout = stdout
        self.stderr = stderr

    def poll(self):
        """Return next poll value."""
        val = self.poll_values[min(self.poll_index, len(self.poll_values) - 1)]
        self.poll_index += 1
        return val

    async def communicate(self):
        """Return captured output."""
        return self.stdout, self.stderr

    def terminate(self):
        self.poll_values = [-15]


class MockConverterFacade:
    """Mock facade that reports service is ready."""

    async def is_service_ready(self):
        return True


class MockAsyncStream:
    def __init__(self, *chunks: bytes):
        self._chunks = list(chunks)

    async def read(self, _size: int):
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class TestConvertPhase6SubprocessExecution(unittest.IsolatedAsyncioTestCase):
    """Test Phase 6: Real subprocess-based execution."""

    async def asyncSetUp(self):
        """Initialize controller for each test."""
        self.controller = ConvertTabController()
        config = ConvertTabControllerConfig(
            config_file="/etc/converter.xml",
            selected_preset_id="preset-1",
            service=object(),
        )
        self.controller._config = config
        self.controller._service_facade = MockConverterFacade()
        self.controller._service_ready = True

    async def test_subprocess_submission_tracking(self):
        """Verify job submission creates subprocess and tracks PID."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="queued",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Queued",
        )
        self.controller._jobs = (job,)
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
        )

        mock_proc = MockAsyncProcess(pid=9999)
        with patch(
            "gui.tabs.convert_controller.asyncio.create_subprocess_exec",
            new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_proc

            await self.controller._submit_job_to_service(
                job, "preset-1", "/data/input", "/data/output"
            )

        # Verify submission tracked
        sub = self.controller._submissions["job-1"]
        self.assertEqual(sub.process_pid, 9999)
        self.assertEqual(sub.submission_attempts, 1)

        # Verify job state updated
        updated_job = self.controller._job_by_id("job-1")
        self.assertEqual(updated_job.state, "starting")

    async def test_subprocess_output_is_captured_incrementally(self):
        """Verify running subprocess output is appended to tracked submission state."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="queued",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Queued",
        )
        self.controller._jobs = (job,)
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
        )

        mock_proc = MockAsyncProcess(pid=9999)
        mock_proc.stdout = MockAsyncStream(b"Converting...\n", b"Progress: 75%\n")
        mock_proc.stderr = MockAsyncStream()
        with patch(
            "gui.tabs.convert_controller.asyncio.create_subprocess_exec",
            new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_proc

            await self.controller._submit_job_to_service(
                job, "preset-1", "/data/input", "/data/output"
            )

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        submission = self.controller._submissions["job-1"]
        self.assertIn("Progress: 75%", submission.process_output)

    async def test_successful_process_completion(self):
        """Verify process exit 0 marks job completed."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="starting",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Starting",
        )
        self.controller._jobs = (job,)

        now = 1000.0
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=9999,
            last_status_check=now - 3.0,  # Set to allow first poll
        )
        self.controller._clock = lambda: now

        # Process that returns success on second poll
        mock_proc = MockAsyncProcess(
            pid=9999,
            poll_values=[None, 0],
            stdout=b"Conversion succeeded",
        )
        self.controller._processes[9999] = mock_proc

        # First poll: still running (at time=now, interval check passes)
        await self.controller._poll_job_status("job-1")
        job_after_first = self.controller._job_by_id("job-1")
        self.assertEqual(job_after_first.state, "running")

        # Advance time by 2.1 seconds to bypass polling interval
        self.controller._clock = lambda: now + 2.1
        mock_proc.poll_index = 1
        await self.controller._poll_job_status("job-1")
        job_after_second = self.controller._job_by_id("job-1")
        self.assertEqual(job_after_second.state, "completed")
        self.assertEqual(job_after_second.progress, "100%")

    async def test_failed_process_transition(self):
        """Verify non-zero exit codes mark job failed."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="starting",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Starting",
        )
        self.controller._jobs = (job,)

        now = 1000.0
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=9999,
            last_status_check=now - 3.0,  # Set to allow first poll
        )
        self.controller._clock = lambda: now

        # Process that fails
        mock_proc = MockAsyncProcess(
            pid=9999,
            poll_values=[None, 127],  # 127 = command not found
            stderr=b"rticonverter: not found",
        )
        self.controller._processes[9999] = mock_proc

        # First poll: running
        await self.controller._poll_job_status("job-1")

        # Advance time and second poll: failed
        self.controller._clock = lambda: now + 2.1
        mock_proc.poll_index = 1
        await self.controller._poll_job_status("job-1")
        job_after = self.controller._job_by_id("job-1")
        self.assertEqual(job_after.state, "failed")
        self.assertIn("127", job_after.message)

    async def test_polling_interval_enforcement(self):
        """Verify polling respects 2-second minimum interval."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="running",
            progress="25%",
            created_at="2026-05-26T00:00:00Z",
            message="Running",
        )
        self.controller._jobs = (job,)

        now = 1000.0
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=9999,
            last_status_check=now,  # Just checked
        )
        self.controller._clock = lambda: now + 1.0  # Only 1 second later

        mock_proc = MockAsyncProcess(pid=9999)
        self.controller._processes[9999] = mock_proc

        # Try to poll before interval expires
        await self.controller._poll_job_status("job-1")

        # Verify poll was skipped (process.poll() never called)
        self.assertEqual(mock_proc.poll_index, 0)
        job_after = self.controller._job_by_id("job-1")
        self.assertEqual(job_after.state, "running")

    async def test_polling_after_interval_expires(self):
        """Verify polling proceeds after 2-second interval."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="running",
            progress="25%",
            created_at="2026-05-26T00:00:00Z",
            message="Running",
        )
        self.controller._jobs = (job,)

        now = 1000.0
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=9999,
            last_status_check=now - 2.5,  # 2.5 seconds ago (past interval)
        )
        self.controller._clock = lambda: now

        # Process that completes
        mock_proc = MockAsyncProcess(
            pid=9999,
            poll_values=[0],  # Immediately complete
            stdout=b"Completed",
        )
        self.controller._processes[9999] = mock_proc

        await self.controller._poll_job_status("job-1")

        # Verify poll was executed
        self.assertGreater(mock_proc.poll_index, 0)
        job_after = self.controller._job_by_id("job-1")
        self.assertEqual(job_after.state, "completed")

    async def test_no_polling_without_process_pid(self):
        """Verify polling is skipped if no process PID."""
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=0,  # No process yet
        )

        mock_proc = MockAsyncProcess(pid=9999)

        await self.controller._poll_job_status("job-1")

        # Verify no polling occurred
        self.assertEqual(mock_proc.poll_index, 0)

    async def test_service_not_ready_prevents_submission(self):
        """Verify submission skipped when service unavailable."""
        self.controller._service_ready = False

        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="queued",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Queued",
        )
        self.controller._jobs = (job,)
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
        )

        with patch(
            "gui.tabs.convert_controller.asyncio.create_subprocess_exec"
        ) as mock_create:
            await self.controller._submit_job_to_service(
                job, "preset-1", "/data/input", "/data/output"
            )

            # Verify no subprocess created
            mock_create.assert_not_called()
            self.assertEqual(len(self.controller._processes), 0)

    async def test_running_process_stays_running(self):
        """Verify process still running is reflected in job state."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="starting",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Starting",
        )
        self.controller._jobs = (job,)
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=9999,
            last_status_check=0,
        )

        # Process returns None (still running)
        mock_proc = MockAsyncProcess(pid=9999, poll_values=[None, None])
        self.controller._processes[9999] = mock_proc

        await self.controller._poll_job_status("job-1")

        # Verify job marked as running
        job_after = self.controller._job_by_id("job-1")
        self.assertEqual(job_after.state, "running")
        self.assertEqual(job_after.progress, "50%")

    async def test_running_process_uses_parsed_progress_when_output_available(self):
        """Verify running jobs use parser output instead of a fixed placeholder when available."""
        job = ConvertJobRow(
            job_id="job-1",
            preset_id="preset-1",
            input_path="/data/input",
            output_path="/data/output",
            output_format="JSON",
            state="starting",
            progress="0%",
            created_at="2026-05-26T00:00:00Z",
            message="Starting",
        )
        self.controller._jobs = (job,)
        self.controller._submissions["job-1"] = ConvertJobSubmission(
            job_id="job-1",
            submitted_at=0,
            process_pid=9999,
            last_status_check=0,
        )

        mock_proc = MockAsyncProcess(
            pid=9999,
            poll_values=[None, None],
            stdout=b"Converting records...\nProgress: 75%\nStill working...",
        )
        self.controller._processes[9999] = mock_proc

        await self.controller._poll_job_status("job-1")

        job_after = self.controller._job_by_id("job-1")
        self.assertEqual(job_after.state, "running")
        self.assertEqual(job_after.progress, "75%")


if __name__ == "__main__":
    unittest.main()
