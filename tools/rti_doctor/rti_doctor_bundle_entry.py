"""PyInstaller entry point for the standalone RTI Doctor deployment bundle."""

import sys

from rti_doctor.__main__ import EXIT_INTERRUPTED, main


if __name__ == "__main__":
  try:
    sys.exit(main())
  except KeyboardInterrupt:
    print("Aborted.")
    sys.exit(EXIT_INTERRUPTED)