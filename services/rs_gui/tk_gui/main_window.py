"""Minimal Tkinter main-window scaffold for the rs_gui migration."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple, TYPE_CHECKING

from app_core.debug_log import dbg, dbg_exc

from .refresh import TkRefreshBridge
from .tabs import RecordTabAdapter, ReplayTabAdapter, TkRecordTab, TkReplayTab
from .theme import DARK_THEME

if TYPE_CHECKING:
    from app_core import AppCommand
    from gui import ShellViewModel


DEFAULT_CLOSE_WATCHDOG_SEC = 15.0
CLOSE_WATCHDOG_ENV = "RS_GUI_CLOSE_WATCHDOG_SEC"


def default_close_watchdog_sec() -> float:
    """Return the close watchdog deadline, honoring `RS_GUI_CLOSE_WATCHDOG_SEC`."""

    raw = os.environ.get(CLOSE_WATCHDOG_ENV, "").strip()
    if not raw:
        return DEFAULT_CLOSE_WATCHDOG_SEC
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_CLOSE_WATCHDOG_SEC


class TkinterUnavailable(RuntimeError):
    """Raised when Tkinter widgets cannot be initialized."""


def _tk_modules():
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise TkinterUnavailable(
            "Tkinter is not available in this Python environment."
        ) from exc
    return tk, ttk


def _apply_dark_theme(root, ttk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(background=DARK_THEME["bg"])
    # Do not set global Tk option defaults for foreground/background.
    # Native file dialogs on Linux may inherit only part of these options,
    # causing low-contrast file names (light text on white backgrounds).

    style.configure(".",
                    background=DARK_THEME["bg"],
                    foreground=DARK_THEME["text"],
                    fieldbackground=DARK_THEME["panel_alt"],
                    bordercolor=DARK_THEME["border"],
                    darkcolor=DARK_THEME["panel"],
                    lightcolor=DARK_THEME["panel"],
                    troughcolor=DARK_THEME["panel_alt"])
    style.configure("TFrame", background=DARK_THEME["bg"])
    style.configure("TLabel", background=DARK_THEME["bg"], foreground=DARK_THEME["text"])
    style.configure("TLabelframe",
                    background=DARK_THEME["panel"],
                    foreground=DARK_THEME["text"],
                    bordercolor=DARK_THEME["border"],
                    relief="solid")
    style.configure("TLabelframe.Label",
                    background=DARK_THEME["panel"],
                    foreground=DARK_THEME["text"])
    style.configure("TButton",
                    background=DARK_THEME["panel_alt"],
                    foreground=DARK_THEME["text"],
                    bordercolor=DARK_THEME["border"],
                    focusthickness=1,
                    focuscolor=DARK_THEME["accent"])
    style.map("TButton",
              background=[("active", DARK_THEME["accent"]), ("disabled", DARK_THEME["panel_alt"])],
              foreground=[("active", DARK_THEME["bg"]), ("disabled", DARK_THEME["muted"])])
    style.configure("TEntry",
                    fieldbackground=DARK_THEME["panel_alt"],
                    foreground=DARK_THEME["text"],
                    insertcolor=DARK_THEME["text"],
                    bordercolor=DARK_THEME["border"])
    style.configure("TCombobox",
                    fieldbackground=DARK_THEME["panel_alt"],
                    background=DARK_THEME["panel_alt"],
                    foreground=DARK_THEME["text"],
                    arrowcolor=DARK_THEME["text"],
                    bordercolor=DARK_THEME["border"])
    style.map("TCombobox",
              fieldbackground=[("readonly", DARK_THEME["panel_alt"])],
              foreground=[("readonly", DARK_THEME["text"])],
              selectbackground=[("readonly", DARK_THEME["selection"])],
              selectforeground=[("readonly", DARK_THEME["text"])])
    style.configure("TCheckbutton", background=DARK_THEME["panel"], foreground=DARK_THEME["text"])
    style.map("TCheckbutton", background=[("active", DARK_THEME["panel"])])
    style.configure("TNotebook", background=DARK_THEME["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab",
                    background=DARK_THEME["panel_alt"],
                    foreground=DARK_THEME["muted"],
                    padding=(14, 8),
                    borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", DARK_THEME["panel"]), ("active", DARK_THEME["panel_alt"])],
              foreground=[("selected", DARK_THEME["text"]), ("active", DARK_THEME["text"])])


def _apply_rti_window_icon(root, tk) -> None:
    """Keep the image referenced so Tk retains the window icon."""

    try:
        icon = tk.PhotoImage(width=32, height=32)
        icon.put("#004b87", to=(0, 0, 32, 32))
        # Compact RS lettermark: the white strokes remain legible in desktop panels.
        for rectangle in (
                (4, 6, 6, 26), (7, 6, 12, 8), (7, 15, 12, 17), (11, 8, 13, 15), (11, 17, 13, 26),
            (17, 6, 27, 8), (17, 15, 27, 17), (17, 24, 27, 26), (17, 8, 19, 15), (25, 17, 27, 24),
        ):
            icon.put("#ffffff", to=rectangle)
        root._rti_window_icon = icon
        root.iconphoto(True, root._rti_window_icon)
    except Exception:
        dbg_exc("tk", "RTI window icon unavailable")


@dataclass
class TkPlaceholderWindow:
    """Small wrapper around a Record/Replay/Debug Tk window."""

    workspace_name: str = "rs_gui"
    view_provider: Optional[Callable[[], "ShellViewModel"]] = None
    command_sink: Optional[Callable[["AppCommand"], bool]] = None
    close_handler: Optional[Callable[[], None]] = None
    refresh_interval_ms: int = 250
    record_tab_adapter: Optional[RecordTabAdapter] = None
    replay_tab_adapter: Optional[ReplayTabAdapter] = None
    # Last-resort hook invoked from a watchdog thread when `close_handler` wedges
    # inside a non-cancellable native call. Receives the elapsed deadline.
    force_close_handler: Optional[Callable[[float], None]] = None
    close_watchdog_sec: float = field(default_factory=default_close_watchdog_sec)

    def __post_init__(self) -> None:
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise TkinterUnavailable(str(exc)) from exc

        _apply_dark_theme(root, ttk)
        _apply_rti_window_icon(root, tk)

        root.title(f"{self.workspace_name} - Tk Preview")
        root.geometry("960x860")
        root.minsize(960, 820)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_var = tk.StringVar(value="Status: Tk shell ready")
        self.event_log_var = tk.StringVar(value="Events: 0")
        self.record_summary_var = tk.StringVar(value="Recording tab placeholder")
        self.replay_summary_var = tk.StringVar(value="Replay tab placeholder")

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.record_tab_widget = TkRecordTab(notebook, ttk, tk, adapter=self.record_tab_adapter)
        notebook.add(self.record_tab_widget.frame, text="Recording")
        self.replay_tab_widget = TkReplayTab(notebook, ttk, tk, adapter=self.replay_tab_adapter)
        notebook.add(self.replay_tab_widget.frame, text="Replay")

        debug_tab = ttk.Frame(notebook, padding=12)
        debug_tab.columnconfigure(0, weight=1)
        debug_tab.rowconfigure(1, weight=1)
        notebook.add(debug_tab, text="Debug")

        debug_actions = ttk.Frame(debug_tab)
        debug_actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        debug_actions.columnconfigure(0, weight=1)
        ttk.Label(debug_actions, text="Runtime and event diagnostics").grid(row=0, column=0, sticky="w")
        ttk.Button(debug_actions, text="Copy Debug Output", command=self._copy_debug_output).grid(row=0, column=1, sticky="e")

        self.debug_console = tk.Text(
            debug_tab,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
            background=DARK_THEME["panel_alt"],
            foreground=DARK_THEME["text"],
            insertbackground=DARK_THEME["text"],
            selectbackground=DARK_THEME["selection"],
            selectforeground=DARK_THEME["text"],
        )
        self.debug_console.grid(row=1, column=0, sticky="nsew")

        self.root = root
        self.notebook = notebook
        self._closing = False
        self._destroyed = False
        self._close_handler_done = False
        self._close_lock = threading.Lock()
        # Read by run_tk_session_shell so a cleanup failure surfaces in the exit
        # code instead of only in the event log.
        self.close_failed = False
        self._refresh_bridge = None
        if self.view_provider is not None:
            self._refresh_bridge = TkRefreshBridge(
                root=root,
                view_provider=self.view_provider,
                view_consumer=self.render_view,
                interval_ms=self.refresh_interval_ms,
            )

    @staticmethod
    def _build_tab(ttk, title: str, summary_var):
        frame = ttk.Frame()
        ttk.Label(frame, text=title).pack(anchor="w", padx=16, pady=(16, 4))
        ttk.Label(frame, textvariable=summary_var).pack(anchor="w", padx=16, pady=(0, 16))
        return frame

    def show(self) -> None:
        self.root.deiconify()
        if self._refresh_bridge is not None:
            self._refresh_bridge.start()

    def close(self) -> None:
        """Run operator close policy, then destroy the window no matter what."""

        # A second click on the window close button while teardown is in flight
        # must not start a second cleanup pass.
        if self._closing:
            dbg("tk", "close ignored: already closing")
            return
        self._closing = True
        dbg("tk", "close begin", watchdog_sec=self.close_watchdog_sec)

        # Stop the refresh loop before any cleanup runs so a pending `after`
        # tick cannot re-enter app-core while its services are being torn down.
        self._stop_refresh()
        self._show_closing_state()

        watchdog = self._start_close_watchdog()
        try:
            if self.close_handler is not None:
                self.close_handler()
        except BaseException:
            # Tk swallows callback exceptions, which historically left the
            # window alive and unclosable. Record it and keep going.
            self.close_failed = True
            dbg_exc("tk", "close handler failed")
        finally:
            # Mark done before cancelling: Timer.cancel() is a no-op once the timer
            # has already fired, so without this a close that lands near the
            # deadline would hard-exit even though cleanup had succeeded.
            with self._close_lock:
                self._close_handler_done = True
            if watchdog is not None:
                watchdog.cancel()
            self.destroy()
            dbg("tk", "close end")

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._stop_refresh()
        try:
            self.root.destroy()
        except Exception:
            dbg_exc("tk", "root destroy failed")

    def _stop_refresh(self) -> None:
        if self._refresh_bridge is None:
            return
        try:
            self._refresh_bridge.stop()
        except Exception:
            dbg_exc("tk", "refresh bridge stop failed")

    def _show_closing_state(self) -> None:
        """Paint a shutting-down indication before we block the Tk thread."""

        try:
            self.status_var.set("Status: shutting down services...")
            self.root.title(f"{self.workspace_name} - shutting down...")
            self.root.configure(cursor="watch")
            self.root.update_idletasks()
        except Exception:
            dbg_exc("tk", "closing state render failed")

    def _start_close_watchdog(self) -> Optional[threading.Timer]:
        """Arm the last-resort exit for a close that wedges in a native call.

        `close_handler` ends up inside blocking Connext calls dispatched to an
        executor. Those are not cancellable, and `asyncio.run` joins its default
        executor on the way out, so there is no cooperative way to abandon a
        stuck teardown. When the deadline passes, the process exits rather than
        leaving an unclosable window and orphaned services behind.
        """

        deadline = float(self.close_watchdog_sec)
        if deadline <= 0:
            return None
        timer = threading.Timer(deadline, self._on_close_watchdog, args=(deadline,))
        timer.daemon = True
        timer.start()
        return timer

    def _on_close_watchdog(self, deadline: float) -> None:
        with self._close_lock:
            if self._close_handler_done:
                # Cleanup finished in the gap between the timer firing and
                # cancel(); there is nothing to force.
                return
        dbg("tk", "close watchdog expired", deadline_sec=deadline)
        if self.force_close_handler is not None:
            try:
                self.force_close_handler(deadline)
            except BaseException:
                dbg_exc("tk", "force close handler failed")
        self._exit_process(3)

    def _exit_process(self, code: int) -> None:
        """Hard-exit hook, overridden in tests."""

        os._exit(code)

    def refresh_once(self):
        if self._refresh_bridge is None:
            return None
        return self._refresh_bridge.refresh_once()

    def submit_command(self, command: "AppCommand") -> bool:
        if self.command_sink is None:
            raise RuntimeError("No command sink is configured for this Tk shell")
        return bool(self.command_sink(command))

    def tab_titles(self) -> Tuple[str, ...]:
        return tuple(self.notebook.tab(tab_id, option="text") for tab_id in self.notebook.tabs())

    def status_text(self) -> str:
        return self.status_var.get()

    def debug_text(self) -> str:
        return self.debug_console.get("1.0", "end-1c")

    def _set_debug_text(self, value: str) -> None:
        self.debug_console.configure(state="normal")
        self.debug_console.delete("1.0", "end")
        self.debug_console.insert("1.0", value)
        self.debug_console.configure(state="disabled")

    def _copy_debug_output(self) -> None:
        text = self.debug_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def render_view(self, view: "ShellViewModel") -> None:
        self.root.title(f"{view.title} - Tk Preview")
        status_text = " | ".join(
            f"{item.label}: {item.value}"
            for item in view.status_items[:6]
        ) or "Status: no shell state"
        self.status_var.set(status_text)
        self.event_log_var.set(
            f"Events: {len(view.event_log)} | Diagnostics: {len(view.operator_diagnostics)}"
        )
        lines = [
            self.status_var.get(),
            self.event_log_var.get(),
            "",
            "Event log:",
        ]
        lines.extend(
            f"- {entry.level}: {entry.message}"
            for entry in view.event_log[-20:]
        )
        if view.operator_diagnostics:
            lines.append("")
            lines.append("Diagnostics:")
            lines.extend(f"- {item}" for item in view.operator_diagnostics[:20])
        self._set_debug_text("\n".join(lines))
        self.record_summary_var.set(
            f"State: {view.record_tab.observed_state} | Candidates: {len(view.record_tab.candidates)}"
        )
        self.record_tab_widget.render(view.record_tab)
        self.replay_summary_var.set(
            f"State: {view.replay_tab.observed_state} | Targets: {view.replay_tab.target_count}"
        )
        self.replay_tab_widget.render(view.replay_tab)
