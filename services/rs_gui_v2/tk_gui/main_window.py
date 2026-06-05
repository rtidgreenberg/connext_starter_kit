"""Minimal Tkinter main-window scaffold for the rs_gui_v2 migration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple, TYPE_CHECKING

from .refresh import TkRefreshBridge
from .tabs import RecordTabAdapter, ReplayTabAdapter, TkRecordTab, TkReplayTab
from .theme import DARK_THEME

if TYPE_CHECKING:
    from app_core import AppCommand
    from gui import ShellViewModel


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
    root.option_add("*Foreground", DARK_THEME["text"])
    root.option_add("*Background", DARK_THEME["bg"])

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


@dataclass
class TkPlaceholderWindow:
    """Small wrapper around a Record/Replay/Debug Tk window."""

    workspace_name: str = "rs_gui_v2"
    view_provider: Optional[Callable[[], "ShellViewModel"]] = None
    command_sink: Optional[Callable[["AppCommand"], bool]] = None
    close_handler: Optional[Callable[[], None]] = None
    refresh_interval_ms: int = 250
    record_tab_adapter: Optional[RecordTabAdapter] = None
    replay_tab_adapter: Optional[ReplayTabAdapter] = None

    def __post_init__(self) -> None:
        tk, ttk = _tk_modules()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            raise TkinterUnavailable(str(exc)) from exc

        _apply_dark_theme(root, ttk)

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
        if self.close_handler is not None:
            self.close_handler()
        self.destroy()

    def destroy(self) -> None:
        if self._refresh_bridge is not None:
            self._refresh_bridge.stop()
        self.root.destroy()

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
