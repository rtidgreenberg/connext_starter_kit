# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Filesystem paths owned by RTI Doctor."""

import os


TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_OUTPUT_ROOT = os.path.join(TOOL_ROOT, "test_output")


def test_output_path(*parts):
  """Return a path below RTI Doctor's single test-output root."""
  return os.path.join(TEST_OUTPUT_ROOT, *parts)