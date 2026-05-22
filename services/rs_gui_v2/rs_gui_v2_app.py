#!/usr/bin/env python3
"""Entry point for rs_gui_v2 headless and GUI checks."""

import argparse
import asyncio
from typing import List, Optional

from app_core import AppRuntime, LifecyclePhase
from gui import build_mock_shell_view_model
from gui.main_window import DearPyGuiShell, DearPyGuiUnavailable


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
        help="build the mocked GUI shell snapshot, then exit",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="run the Dear PyGui shell with mocked Record-tab data",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.headless_check:
        lifecycle = asyncio.run(run_headless_once())
        return 0 if lifecycle == LifecyclePhase.STOPPED else 1
    if args.mock_gui_check:
        view = build_mock_shell_view_model()
        return 0 if view.record_tab.candidates else 1
    if args.gui:
        try:
            DearPyGuiShell().run()
            return 0
        except DearPyGuiUnavailable as exc:
            print(str(exc))
            return 2
    _parse_args(["--help"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())