"""CLI entry point for rti_view."""

import argparse


def parse_args(argv=None):
    """Parse command-line arguments for rti_view."""
    parser = argparse.ArgumentParser(
        prog="rti_view",
        description="Single-pane DDS data viewer. Discovers topics, subscribes, and displays field values.",
    )
    parser.add_argument("-d", "--domain", type=int, default=0, help="DDS domain ID (default: 0)")
    parser.add_argument("-t", "--topic", type=str, default=None, help="Topic name to subscribe to")
    parser.add_argument("-f", "--field", type=str, default=None, help="Field path to display/plot (e.g. 'x' or 'position.x')")
    parser.add_argument("-m", "--mode", choices=["text", "plot"], default="text", help="View mode: text or plot (default: text)")
    parser.add_argument("--history", type=int, default=30, help="Plot history in seconds (default: 30)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Discovery timeout in seconds (default: 10)")
    parser.add_argument(
        "--direct-view",
        action="store_true",
        help="Skip the interactive shell and open only the direct text or plot view for the selected topic and field",
    )
    parser.add_argument("--debug", type=str, nargs="?", const="rti_view_debug.log",
                        default=None, metavar="LOGFILE",
                        help="Enable debug logging to file (default: rti_view_debug.log)")
    args = parser.parse_args(argv)
    if bool(args.topic) != bool(args.field):
        parser.error("--topic and --field must be provided together for direct view mode")
    if args.direct_view and not (args.topic and args.field):
        parser.error("--direct-view requires --topic and --field")
    return args


def main():
    """Main entry point."""
    args = parse_args()

    if args.debug:
        from . import debug_log
        debug_log.enable(args.debug)

    if args.direct_view:
        from .subscriber import run_direct_view
        run_direct_view(
            domain_id=args.domain,
            topic_name=args.topic,
            field_path=args.field,
            mode=args.mode,
            history_seconds=args.history,
            timeout=args.timeout,
        )
        return

    from .views.main_window import run_interactive
    run_interactive(
        domain_id=args.domain,
        topic_name=args.topic or "",
        field_path=args.field or "",
        mode=args.mode,
        history_seconds=args.history,
    )


if __name__ == "__main__":
    main()
