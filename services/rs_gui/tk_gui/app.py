"""App bootstrap helpers for the minimal rs_gui_v2 Tk shell."""

from __future__ import annotations

from typing import Callable, Optional

from .tabs import RecordTabAdapter, ReplayTabAdapter
from .main_window import TkPlaceholderWindow


def build_tk_placeholder_shell(
        workspace_name: str = "rs_gui_v2",
        view_provider: Optional[Callable[[], object]] = None,
        command_sink: Optional[Callable[[object], bool]] = None,
        close_handler: Optional[Callable[[], None]] = None,
        refresh_interval_ms: int = 250,
        record_tab_adapter: Optional[RecordTabAdapter] = None,
        replay_tab_adapter: Optional[ReplayTabAdapter] = None,
) -> TkPlaceholderWindow:
    """Build the minimal Record/Replay placeholder window."""

    return TkPlaceholderWindow(
        workspace_name=workspace_name,
        view_provider=view_provider,
        command_sink=command_sink,
        close_handler=close_handler,
        refresh_interval_ms=refresh_interval_ms,
        record_tab_adapter=record_tab_adapter,
        replay_tab_adapter=replay_tab_adapter,
    )


def build_tk_session_shell(session, refresh_interval_ms: int = 250) -> TkPlaceholderWindow:
    """Build a Tk shell wired to an existing GUI session."""

    record_tab_adapter = RecordTabAdapter(
        command_sink=session.command_sink,
        select_candidate=session.record_controller.select_candidate,
        set_tag_value=session.record_controller.set_tag_value,
        resolve_candidate=lambda candidate_id: next(
            (candidate for candidate in session.record_controller.last_selection.candidates if candidate.candidate_id == candidate_id),
            None,
        ),
    )
    replay_tab_adapter = ReplayTabAdapter(
        command_sink=session.command_sink,
        select_target=session.replay_controller.select_target,
    )

    return build_tk_placeholder_shell(
        workspace_name=session.config.workspace_name or "rs_gui_v2",
        view_provider=session.next_view,
        command_sink=session.command_sink,
        close_handler=lambda: session.handle_close_request("leave_running"),
        refresh_interval_ms=refresh_interval_ms,
        record_tab_adapter=record_tab_adapter,
        replay_tab_adapter=replay_tab_adapter,
    )


def run_tk_placeholder_shell(
        workspace_name: str = "rs_gui_v2",
        view_provider: Optional[Callable[[], object]] = None,
        command_sink: Optional[Callable[[object], bool]] = None,
        close_handler: Optional[Callable[[], None]] = None,
        refresh_interval_ms: int = 250,
        record_tab_adapter: Optional[RecordTabAdapter] = None,
        replay_tab_adapter: Optional[ReplayTabAdapter] = None,
) -> int:
    """Show the placeholder window and enter the Tk event loop."""

    shell = build_tk_placeholder_shell(
        workspace_name=workspace_name,
        view_provider=view_provider,
        command_sink=command_sink,
        close_handler=close_handler,
        refresh_interval_ms=refresh_interval_ms,
        record_tab_adapter=record_tab_adapter,
        replay_tab_adapter=replay_tab_adapter,
    )
    shell.show()
    shell.root.mainloop()
    return 0


def run_tk_session_shell(session, refresh_interval_ms: int = 250) -> int:
    """Show a Tk shell wired to an existing GUI session."""

    shell = build_tk_session_shell(session, refresh_interval_ms=refresh_interval_ms)
    shell.show()
    shell.root.mainloop()
    return 0