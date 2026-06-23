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
Run all services-level tests (E2E tests for start scripts).

Usage:
    cd services
    python3 test/run_all_tests.py          # run all tests
    python3 test/run_all_tests.py -v       # verbose

Individual test files can also be run directly:
    python3 test/test_e2e_services.py -v
"""

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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
