"""Filesystem paths owned by RTI Doctor."""

import os


TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_OUTPUT_ROOT = os.path.join(TOOL_ROOT, "test_output")


def test_output_path(*parts):
  """Return a path below RTI Doctor's single test-output root."""
  return os.path.join(TEST_OUTPUT_ROOT, *parts)