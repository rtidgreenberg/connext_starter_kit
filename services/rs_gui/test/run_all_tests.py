#!/usr/bin/env python3
"""Run all rs_gui Python tests."""

import os
import sys
import unittest


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.normpath(os.path.join(PARENT_DIR, "..", ".."))
VENV_PYTHON = os.path.join(REPO_ROOT, "connext_dds_env", "bin", "python")


def _reexec_with_repo_venv() -> None:
    if not os.path.isfile(VENV_PYTHON):
        return
    if os.path.realpath(sys.executable) == os.path.realpath(VENV_PYTHON):
        return
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)


_reexec_with_repo_venv()

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