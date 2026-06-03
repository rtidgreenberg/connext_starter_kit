"""Debug file logger for rti_view.

When enabled via enable(path), all debug() calls write timestamped lines
to the specified log file. When disabled, calls are no-ops.
"""

import os
import time
from typing import Optional

_log_file = None
_log_path: Optional[str] = None
_start_time: float = 0.0


def enable(path: str = "rti_view_debug.log") -> None:
    """Enable debug logging to the given file path."""
    global _log_file, _log_path, _start_time
    _log_path = os.path.abspath(path)
    _log_file = open(_log_path, "w")
    _start_time = time.monotonic()
    _log_file.write(f"=== rti_view debug log started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    _log_file.write(f"=== Log file: {_log_path} ===\n\n")
    _log_file.flush()


def enabled() -> bool:
    return _log_file is not None


def debug(category: str, message: str) -> None:
    """Write a debug message if logging is enabled."""
    if _log_file is None:
        return
    elapsed = time.monotonic() - _start_time
    _log_file.write(f"[{elapsed:8.3f}] [{category}] {message}\n")
    _log_file.flush()


def close() -> None:
    """Close the log file."""
    global _log_file
    if _log_file is not None:
        _log_file.write(f"\n=== rti_view debug log ended at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _log_file.close()
        _log_file = None
