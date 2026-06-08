#!/usr/bin/env python3
"""Entry point for rs_gui headless and GUI checks."""

import argparse
import asyncio
from typing import List, Optional

from app_core import AppRuntime, LifecyclePhase
from app_core.debug_log import dbg, is_debug, log_path
from gui import (
    GuiShellSessionFactoryConfig,
    GuiShellSessionMode,
    build_default_gui_shell_session,
    build_gui_shell_assembly,
)
from tk_gui import TkinterUnavailable, build_tk_placeholder_shell, run_tk_session_shell


async def run_headless_once() -> LifecyclePhase:
    """Start and stop the headless runtime without DDS or GUI entities."""
    runtime = AppRuntime()
    runtime.start()
    await runtime.shutdown()
    return runtime.lifecycle


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="rs_gui headless runtime")
    parser.add_argument(
        "--headless-check",
        action="store_true",
        help="start and stop the app core, then exit",
    )
    parser.add_argument(
        "--mock-gui-check",
        action="store_true",
        help="build the session-backed mock GUI shell, then exit",
    )
    parser.add_argument(
        "--mock-gui",
        action="store_true",
        help="run the Tk shell with explicit mock/demo data",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="run the Tk shell without mock/demo data",
    )
    parser.add_argument(
        "--tk-gui-check",
        action="store_true",
        help="build the minimal Tk shell scaffold, then exit",
    )
    parser.add_argument(
        "--tk-gui",
        action="store_true",
        help="run the minimal Tk shell scaffold",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.headless_check:
        lifecycle = asyncio.run(run_headless_once())
        return 0 if lifecycle == LifecyclePhase.STOPPED else 1
    if args.mock_gui_check:
        session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.MOCK,
        ))
        view = session.next_view()
        return 0 if view.record_tab.candidates else 1
    if args.tk_gui_check:
        session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(
            mode=GuiShellSessionMode.MOCK,
        ))
        try:
            shell = build_tk_placeholder_shell(
                workspace_name="rs_gui",
                view_provider=session.next_view,
                command_sink=session.command_sink,
            )
            try:
                shell.refresh_once()
                ok = (
                    shell.tab_titles() == ("Recording", "Replay", "Debug")
                    and "Robot Run 03" in shell.root.title()
                    and "Runtime:" in shell.status_text()
                )
                return 0 if ok else 1
            finally:
                shell.destroy()
        except TkinterUnavailable as exc:
            print(str(exc))
            return 2
        finally:
            asyncio.run(session.runtime.shutdown())
    if args.gui or args.mock_gui:
        try:
            mode = GuiShellSessionMode.MOCK if args.mock_gui else GuiShellSessionMode.LIVE
            session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(mode=mode))
            if session.runtime.event_log_path:
                if is_debug():
                    print(f"[DEBUG] RS GUI log: {log_path()}", flush=True)
                else:
                    print(f"[DEBUG] Event log: {session.runtime.event_log_path}", flush=True)
            dbg(
                "app",
                "rs_gui starting",
                mode="mock" if args.mock_gui else "live",
                event_log=session.runtime.event_log_path,
                ui="tk",
            )
            return run_tk_session_shell(session)
        except TkinterUnavailable as exc:
            print(str(exc))
            return 2
    if args.tk_gui:
        try:
            session = build_default_gui_shell_session(GuiShellSessionFactoryConfig(
                mode=GuiShellSessionMode.LIVE,
            ))
            return run_tk_session_shell(session)
        except TkinterUnavailable as exc:
            print(str(exc))
            return 2
    _parse_args(["--help"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())