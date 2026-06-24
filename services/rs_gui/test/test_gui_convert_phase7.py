"""Phase 7 Tests: Progress tracking, file browser, and result display."""

import unittest
from app_core import AppCommand
from gui.tabs.convert_controller import ConvertTabController


class TestPhase7ProgressParsing(unittest.TestCase):
    """Test progress extraction from converter output."""

    def setUp(self) -> None:
        self.controller = ConvertTabController.mock()

    def test_parse_progress_percentage_from_output(self) -> None:
        """Test explicit 'Progress: X%' pattern."""
        output = "Converting records...\nProgress: 75%\nStill working..."
        result = self.controller._parse_progress_from_output(output)
        self.assertEqual(result, "75%")

    def test_parse_progress_from_record_count(self) -> None:
        """Test 'record N of M' pattern for progress calculation."""
        output = "Processing record 150 of 300"
        result = self.controller._parse_progress_from_output(output)
        self.assertEqual(result, "50%")

    def test_progress_clamped_to_range(self) -> None:
        """Test progress is clamped to 0-100% range."""
        # Over 100%
        output = "Progress: 150%"
        result = self.controller._parse_progress_from_output(output)
        self.assertEqual(result, "100%")
        
        # Negative from calculation
        output = "record 5 of 300"
        result = self.controller._parse_progress_from_output(output)
        self.assertEqual(result, "1%")  # 5/300 = 1.6% clamped to 1%

    def test_progress_default_fallback(self) -> None:
        """Test default progress when no pattern matches."""
        output = "Some random output with no progress info"
        result = self.controller._parse_progress_from_output(output)
        self.assertEqual(result, "50%")


class TestPhase7ResultParsing(unittest.TestCase):
    """Test result summary construction."""

    def setUp(self) -> None:
        self.controller = ConvertTabController.mock()

    def test_parse_record_count_from_output(self) -> None:
        """Test record count extraction."""
        output = "Conversion complete: 1250 records processed"
        result = self.controller._parse_record_count_from_output(output)
        self.assertEqual(result, 1250)

    def test_parse_record_count_case_insensitive(self) -> None:
        """Test case-insensitive record pattern."""
        output = "Wrote 500 RECORDS to output"
        result = self.controller._parse_record_count_from_output(output)
        self.assertEqual(result, 500)

    def test_parse_record_count_default(self) -> None:
        """Test default value when no pattern matches."""
        output = "No records found in this output"
        result = self.controller._parse_record_count_from_output(output)
        self.assertEqual(result, 0)

    def test_parse_result_summary_with_stats(self) -> None:
        """Test result summary generation with elapsed time and record count."""
        output = "Processed 1000 records successfully"
        result = self.controller._parse_result_summary(output, elapsed_seconds=10)
        self.assertIn("Duration: 10s", result)
        self.assertIn("Records: 1000", result)
        self.assertIn("100.0 records/sec", result)

    def test_parse_result_summary_no_records(self) -> None:
        """Test result summary when no records found."""
        output = "Conversion completed"
        result = self.controller._parse_result_summary(output, elapsed_seconds=5)
        self.assertEqual(result, "Duration: 5s")

    def test_parse_result_summary_zero_duration(self) -> None:
        """Test result summary with zero elapsed time."""
        output = "Processed 500 records"
        result = self.controller._parse_result_summary(output, elapsed_seconds=0)
        self.assertEqual(result, "Records: 500")


class TestPhase7FileBrowser(unittest.TestCase):
    """Test file browser intent commands."""

    def setUp(self) -> None:
        self.controller = ConvertTabController.mock()

    def test_browse_input_handler(self) -> None:
        """Test convert.browse_input command handler."""
        command = AppCommand(command_id="test-1", command_type="convert.browse_input")
        result = self.controller._handle_browse_input(command, {})
        
        self.assertIsNotNone(result)
        self.assertEqual(result.command_id, "test-1")
        self.assertIn("current_path", result.payload)
        self.assertEqual(result.payload["storage_kind"], "sqlite")

    def test_browse_output_handler(self) -> None:
        """Test convert.browse_output command handler."""
        command = AppCommand(command_id="test-2", command_type="convert.browse_output")
        result = self.controller._handle_browse_output(command, {})
        
        self.assertIsNotNone(result)
        self.assertEqual(result.command_id, "test-2")
        self.assertIn("current_path", result.payload)
        self.assertEqual(result.payload["storage_kind"], "sqlite")


class TestPhase7JobResultFields(unittest.TestCase):
    """Test that ConvertJobRow includes Phase 7 result fields."""

    def test_job_row_includes_result_fields(self) -> None:
        """Test ConvertJobRow has all Phase 7 fields."""
        controller = ConvertTabController.mock()
        jobs = controller.last_view.jobs
        
        # Mock view should have at least one job
        self.assertGreater(len(jobs), 0)
        job = jobs[0]
        
        # Verify Phase 7 fields exist and are initialized
        self.assertTrue(hasattr(job, 'started_at'))
        self.assertTrue(hasattr(job, 'completed_at'))
        self.assertTrue(hasattr(job, 'elapsed_seconds'))
        self.assertTrue(hasattr(job, 'record_count'))
        self.assertTrue(hasattr(job, 'result_summary'))
        
        # Verify default values
        self.assertEqual(job.started_at, "")
        self.assertEqual(job.completed_at, "")
        self.assertEqual(job.elapsed_seconds, 0)
        self.assertEqual(job.record_count, 0)
        self.assertEqual(job.result_summary, "")


if __name__ == "__main__":
    unittest.main()
