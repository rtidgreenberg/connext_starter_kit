#!/usr/bin/env python3
"""Entry point for rs_gui_v2 headless and GUI checks."""

import argparse
import asyncio
from typing import List, Optional

from app_core import AppRuntime, LifecyclePhase
from gui import (
    GuiShellSessionFactoryConfig,
    GuiShellSessionMode,
    build_default_gui_shell_session,
    build_gui_shell_assembly,
)
from gui.main_window import DearPyGuiUnavailable


async def run_headless_once() -> LifecyclePhase:
    """Start and stop the headless runtime without DDS or GUI entities."""
    runtime = AppRuntime()
    runtime.start()
    await runtime.shutdown()
    return runtime.lifecycle


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="rs_gui_v2 headless runtime")
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
        help="run the Dear PyGui shell with explicit mock/demo data",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="run the Dear PyGui shell without mock/demo data",
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
    if args.gui or args.mock_gui:
        try:
            mode = GuiShellSessionMode.MOCK if args.mock_gui else GuiShellSessionMode.LIVE
            assembly = build_gui_shell_assembly(GuiShellSessionFactoryConfig(mode=mode))
            assembly.shell().run()
            return 0
        except DearPyGuiUnavailable as exc:
            print(str(exc))
            return 2
    _parse_args(["--help"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())