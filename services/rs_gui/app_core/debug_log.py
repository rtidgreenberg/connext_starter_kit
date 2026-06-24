"""Lightweight structured debug logger for rs_gui.

Writes debug entries as JSONL events under ``services/rs_gui/rs_gui_logs``.
When the app runtime has already created an event log, debug output is appended
to that same file with ``event_type=debug.log`` and the callsite tag recorded
as the event source.
"""

import json
import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from .events import AppEvent

_DEBUG_ENV = os.environ.get("RS_GUI_DEBUG", "").strip().lower()
_ENABLED = _DEBUG_ENV not in ("0", "false", "no", "off")
_EVENT_LOG_ENV = "RS_GUI_EVENT_LOG_PATH"

_LOG_DIR = Path(os.environ.get(
    "RS_GUI_LOG_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rs_gui_logs"),
))
_LOG_PATH = None
_LOG_LOCK = threading.Lock()
_START_TIME = time.monotonic()


def _get_log_path() -> str:
    global _LOG_PATH
    runtime_log_path = os.environ.get(_EVENT_LOG_ENV, "").strip()
    if runtime_log_path:
        return runtime_log_path
    if _LOG_PATH is not None:
        return _LOG_PATH
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = str(_LOG_DIR / f"rs_gui_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.jsonl")
    return _LOG_PATH


def _write_event(event: AppEvent) -> None:
    log_path = _get_log_path()
    directory = os.path.dirname(log_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with _LOG_LOCK:
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(event.to_dict(), default=str, sort_keys=True) + "\n")


def _debug_event(tag: str, message: str, payload=None) -> AppEvent:
    details = dict(payload or {})
    details.update({
        "level": "debug",
        "message": str(message),
        "elapsed_sec": round(time.monotonic() - _START_TIME, 6),
        "pid": os.getpid(),
        "python": sys.version.split()[0],
    })
    return AppEvent(
        event_type="debug.log",
        source=str(tag),
        payload=details,
        event_id=str(uuid.uuid4()),
        created_at=time.time(),
    )


def dbg(tag: str, message: str, **kwargs) -> None:
    """Write a structured debug event (no-op if debug logging is disabled)."""
    if not _ENABLED:
        return
    _write_event(_debug_event(tag, message, kwargs))


def dbg_exc(tag: str, message: str) -> None:
    """Write a structured debug event with the current exception traceback."""
    if not _ENABLED:
        return
    _write_event(_debug_event(tag, message, {
        "exception": traceback.format_exc(),
    }))


def is_debug() -> bool:
    """Return True if debug logging is active."""
    return _ENABLED


def log_path() -> str:
    """Return the path to the active rs_gui event log file."""
    if not _ENABLED:
        return "(debug logging disabled - set RS_GUI_DEBUG=0 only when needed)"
    return _get_log_path()
