#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Run all rs_gui Python tests."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=SCRIPT_DIR,
        pattern="test_*.py",
        top_level_dir=SCRIPT_DIR,
    )
    verbosity = 2 if "-v" in sys.argv else 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())