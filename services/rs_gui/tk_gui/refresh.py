# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Tk refresh-loop helpers for the rs_gui migration shell."""

from __future__ import annotations

from typing import Any, Callable, Optional


class TkRefreshBridge:
    """Drive Tk shell refreshes from a synchronous view provider."""

    def __init__(
            self,
            root: Any,
            view_provider: Callable[[], object],
            view_consumer: Callable[[object], None],
            interval_ms: int = 250,
    ) -> None:
        self._root = root
        self._view_provider = view_provider
        self._view_consumer = view_consumer
        self._interval_ms = max(1, int(interval_ms))
        self._after_id: Optional[str] = None
        self._running = False
        self._last_view = None

    @property
    def last_view(self):
        return self._last_view

    def refresh_once(self):
        view = self._view_provider()
        self._view_consumer(view)
        self._last_view = view
        return view

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._schedule_next()

    def stop(self) -> None:
        self._running = False
        if self._after_id is not None:
            self._root.after_cancel(self._after_id)
            self._after_id = None

    def _schedule_next(self) -> None:
        self._after_id = self._root.after(self._interval_ms, self._tick)

    def _tick(self) -> None:
        self._after_id = None
        try:
            self.refresh_once()
        except KeyboardInterrupt:
            # Ctrl+C during shutdown can interrupt asyncio.run() inside the view
            # provider; stop the Tk refresh loop without surfacing a callback
            # traceback.
            self._running = False
            try:
                self._root.quit()
            except Exception:
                pass
            return
        if self._running:
            self._schedule_next()