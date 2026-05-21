#!/usr/bin/env python3
"""Headless entry point for rs_gui_v2."""

import argparse
import asyncio
from typing import List, Optional

from app_core import AppRuntime, LifecyclePhase


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
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.headless_check:
        lifecycle = asyncio.run(run_headless_once())
        return 0 if lifecycle == LifecyclePhase.STOPPED else 1
    _parse_args(["--help"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())