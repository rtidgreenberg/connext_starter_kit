"""Lightweight debug logger for rs_gui_v2.

Writes timestamped debug lines to a rotating log file. Debug logging is enabled
by default so launch/debug issues always leave a local trace. Disable it by
setting the environment variable RS_GUI_DEBUG=0.

Usage:
    from app_core.debug_log import dbg

    dbg("frame_callback", "view_provider returned", candidates=3)
"""

import os
import sys
import time
import traceback
from pathlib import Path

_DEBUG_ENV = os.environ.get("RS_GUI_DEBUG", "").strip().lower()
_ENABLED = _DEBUG_ENV not in ("0", "false", "no", "off")

_LOG_DIR = Path(os.environ.get(
    "RS_GUI_LOG_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug_logs"),
))
_LOG_FILE = None
_START_TIME = time.monotonic()


def _get_log_file():
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"rs_gui_debug_{os.getpid()}.log"
    _LOG_FILE = open(log_path, "a", buffering=1)  # line-buffered
    _LOG_FILE.write(f"\n{'='*72}\n")
    _LOG_FILE.write(f"  rs_gui_v2 DEBUG session started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _LOG_FILE.write(f"  PID={os.getpid()}  Python={sys.version.split()[0]}\n")
    _LOG_FILE.write(f"{'='*72}\n\n")
    _LOG_FILE.flush()
    return _LOG_FILE


def dbg(tag: str, message: str, **kwargs) -> None:
    """Write a debug line to the log file (no-op if debug logging is disabled)."""
    if not _ENABLED:
        return
    elapsed = time.monotonic() - _START_TIME
    f = _get_log_file()
    extra = ""
    if kwargs:
        extra = "  " + "  ".join(f"{k}={v!r}" for k, v in kwargs.items())
    f.write(f"[{elapsed:9.3f}] [{tag}] {message}{extra}\n")


def dbg_exc(tag: str, message: str) -> None:
    """Write a debug line with the current exception traceback."""
    if not _ENABLED:
        return
    elapsed = time.monotonic() - _START_TIME
    f = _get_log_file()
    f.write(f"[{elapsed:9.3f}] [{tag}] {message}\n")
    traceback.print_exc(file=f)
    f.write("\n")


def is_debug() -> bool:
    """Return True if debug logging is active."""
    return _ENABLED


def log_path() -> str:
    """Return the path to the current debug log file (creates it if needed)."""
    if not _ENABLED:
        return "(debug logging disabled - set RS_GUI_DEBUG=0 only when needed)"
    return str(_get_log_file().name)
