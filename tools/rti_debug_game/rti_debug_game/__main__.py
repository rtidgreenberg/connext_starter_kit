"""Command-line entry point for the initial DDS Debug Game implementation."""

import argparse
import json

from .app import DebugGameApp
from .generator import generate, run_root
from .levels import CATALOG
from .runtime import run_once


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="rti_debug_game")
    parser.add_argument("--level", choices=sorted(CATALOG), default="L01")
    parser.add_argument("--generate", action="store_true", help="Generate editable participant scripts")
    parser.add_argument("--reset", action="store_true", help="Regenerate the selected level's scripts")
    parser.add_argument("--run", action="store_true", help="Run one finite validation round")
    parser.add_argument("--timeout", type=float, default=4.0, help="Headless round timeout in seconds")
    parser.add_argument("--headless", action="store_true", help="Do not launch the interactive TUI")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    scenario = CATALOG[args.level]
    if not args.generate and not args.reset and not args.run and not args.headless:
        DebugGameApp(args.level).run()
        return 0
    root = generate(scenario, reset=args.reset)
    if args.generate or not args.run:
        print(f"Generated {scenario.level_id} in {root}")
        return 0
    result = run_once(scenario, root, args.timeout)
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
