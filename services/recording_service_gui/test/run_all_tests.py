#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

"""
Run all Recording Service GUI Python tests.

Usage:
    ../../connext_dds_env/bin/python test/run_all_tests.py          # run all tests
    ../../connext_dds_env/bin/python test/run_all_tests.py -v       # verbose

Individual test files can also be run directly:
    ../../connext_dds_env/bin/python test/test_monitoring.py -v
    ../../connext_dds_env/bin/python test/test_gui.py -v
    ../../connext_dds_env/bin/python test/test_control.py -v
    ../../connext_dds_env/bin/python test/test_e2e_tags.py -v

Services-level E2E tests (start scripts) live in services/test/.
"""

import os
import sys
import unittest

# Ensure the parent directory (recording_service_gui/) is on the path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))
VENV_PYTHON = os.path.join(REPO_ROOT, "connext_dds_env", "bin", "python")


def _reexec_with_repo_venv():
    if not os.path.isfile(VENV_PYTHON):
        return
    if os.path.realpath(sys.executable) == os.path.realpath(VENV_PYTHON):
        return
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)


_reexec_with_repo_venv()

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Discover all test_*.py files in this directory
    discovered = loader.discover(
        start_dir=SCRIPT_DIR,
        pattern="test_*.py",
        top_level_dir=SCRIPT_DIR,
    )
    suite.addTests(discovered)

    # Run with verbosity from command line (-v flag)
    verbosity = 2 if "-v" in sys.argv else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
