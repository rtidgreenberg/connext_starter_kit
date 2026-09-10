#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.

"""Publish RTI Distributed Logger messages on a DDS domain."""

import argparse
import time

from rti.logging import distlog


DEFAULT_APP_KIND = "Distributed Logger Publisher"
DEFAULT_CATEGORY = "example.distributed_logger"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish periodic RTI Distributed Logger messages"
    )
    parser.add_argument(
        "-d", "--domain-id", type=int, default=1,
        help="DDS domain ID (default: 1)",
    )
    parser.add_argument(
        "-i", "--interval", type=float, default=1.0,
        help="Seconds between messages (default: 1.0)",
    )
    parser.add_argument(
        "-c", "--count", type=int, default=0,
        help="Messages to publish; 0 publishes until interrupted (default: 0)",
    )
    parser.add_argument(
        "--category", default=DEFAULT_CATEGORY,
        help=f"Distributed logger category (default: {DEFAULT_CATEGORY})",
    )
    parser.add_argument(
        "--application-kind", default=DEFAULT_APP_KIND,
        help=f"Application kind reported in log messages (default: {DEFAULT_APP_KIND})",
    )
    parser.add_argument(
        "--level", choices=("debug", "info", "warning", "error"), default="info",
        help="Log level to publish (default: info)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval < 0:
        raise ValueError("--interval must be greater than or equal to zero")
    if args.count < 0:
        raise ValueError("--count must be greater than or equal to zero")

    levels = {
        "debug": distlog.LogLevel.DEBUG,
        "info": distlog.LogLevel.INFO,
        "warning": distlog.LogLevel.WARNING,
        "error": distlog.LogLevel.ERROR,
    }
    options = distlog.LoggerOptions()
    options.domain_id = args.domain_id
    options.application_kind = args.application_kind
    options.filter_level = levels[args.level]
    options.echo_to_stdout = True
    options.remote_administration_enabled = True

    distlog.Logger.init(options)
    print(
        f"Publishing distributed logger messages on domain {args.domain_id} "
        f"(Ctrl+C to stop)"
    )
    try:
        message_number = 1
        while args.count == 0 or message_number <= args.count:
            message = f"Distributed logger publisher message {message_number}"
            distlog.Logger.log(levels[args.level], message, args.category)
            message_number += 1
            if args.count == 0 or message_number <= args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopping distributed logger publisher.")
    finally:
        distlog.Logger.finalize()


if __name__ == "__main__":
    main()