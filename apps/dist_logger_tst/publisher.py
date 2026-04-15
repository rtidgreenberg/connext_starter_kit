#!/usr/bin/env python3
"""
Distributed Logger Publisher - sends log messages in different ordering patterns
to test whether reception order matches send order across levels.
"""

import argparse
import time
import rti.connextdds as dds
import rti.logging.distlog as distlog


# Only use levels that pass the default filter (FATAL through INFO)
SEND_FUNCTIONS = {
    "FATAL":   distlog.Logger.fatal,
    "ERROR":   distlog.Logger.error,
    "WARNING": distlog.Logger.warning,
    "NOTICE":  distlog.Logger.notice,
    "INFO":    distlog.Logger.info,
}

LEVEL_NAMES = list(SEND_FUNCTIONS.keys())


def pattern_round_robin(count, delay, seq=0):
    """Original pattern: cycle through all levels in order each round."""
    for i in range(count):
        for level_name, fn in SEND_FUNCTIONS.items():
            fn(f"[seq={seq}] {level_name} rr#{i}")
            print(f"  Sent {level_name:>7} seq={seq}")
            seq += 1
            if delay > 0:
                time.sleep(delay)
    return seq


def pattern_burst_per_level(count, delay, seq=0):
    """Send a burst of N messages at one level, then move to next level."""
    for level_name, fn in SEND_FUNCTIONS.items():
        for i in range(count):
            fn(f"[seq={seq}] {level_name} burst#{i}")
            print(f"  Sent {level_name:>7} seq={seq}")
            seq += 1
            if delay > 0:
                time.sleep(delay)
    return seq


def pattern_reverse_severity(count, delay, seq=0):
    """Send from lowest severity to highest (INFO -> FATAL)."""
    reversed_items = list(reversed(SEND_FUNCTIONS.items()))
    for i in range(count):
        for level_name, fn in reversed_items:
            fn(f"[seq={seq}] {level_name} rev#{i}")
            print(f"  Sent {level_name:>7} seq={seq}")
            seq += 1
            if delay > 0:
                time.sleep(delay)
    return seq


def pattern_interleaved_pairs(count, delay, seq=0):
    """Alternate between two levels: FATAL/INFO, ERROR/NOTICE, WARNING/FATAL, ..."""
    pairs = [
        ("FATAL", "INFO"),
        ("ERROR", "NOTICE"),
        ("WARNING", "FATAL"),
        ("INFO", "ERROR"),
        ("NOTICE", "WARNING"),
    ]
    for i in range(count):
        for a, b in pairs:
            SEND_FUNCTIONS[a](f"[seq={seq}] {a} pair#{i}")
            print(f"  Sent {a:>7} seq={seq}")
            seq += 1
            if delay > 0:
                time.sleep(delay)

            SEND_FUNCTIONS[b](f"[seq={seq}] {b} pair#{i}")
            print(f"  Sent {b:>7} seq={seq}")
            seq += 1
            if delay > 0:
                time.sleep(delay)
    return seq


def pattern_same_level_burst(count, delay, seq=0):
    """Send all messages at one level (WARNING) to isolate single-instance ordering."""
    for i in range(count * len(SEND_FUNCTIONS)):
        distlog.Logger.warning(f"[seq={seq}] WARNING only#{i}")
        print(f"  Sent WARNING seq={seq}")
        seq += 1
        if delay > 0:
            time.sleep(delay)
    return seq


PATTERNS = {
    "round-robin":      ("Cycle all levels each round",        pattern_round_robin),
    "burst-per-level":  ("N msgs per level, then next level",  pattern_burst_per_level),
    "reverse":          ("Lowest to highest severity",         pattern_reverse_severity),
    "interleaved":      ("Alternating level pairs",            pattern_interleaved_pairs),
    "same-level":       ("All WARNING to test single level",   pattern_same_level_burst),
    "all":              ("Run all patterns sequentially",      None),
}


def main():
    parser = argparse.ArgumentParser(
        description="Distributed Logger Publisher — multiple send patterns",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-d", "--domain-id", type=int, default=0, help="DDS domain ID")
    parser.add_argument("-n", "--count", type=int, default=5, help="Messages per level per pattern")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between messages (seconds)")
    pattern_help = "\n".join(f"  {k:<18} {v[0]}" for k, v in PATTERNS.items())
    parser.add_argument(
        "-p", "--pattern", default="all",
        choices=PATTERNS.keys(),
        help=f"Send pattern:\n{pattern_help}",
    )
    args = parser.parse_args()

    participant = dds.DomainParticipant(args.domain_id)

    logger_options = distlog.LoggerOptions()
    logger_options.domain_id = args.domain_id
    logger_options.application_kind = "DistLoggerTestPublisher"
    logger_options.participant = participant
    distlog.Logger.init(logger_options)

    print(f"Distributed Logger Publisher on domain {args.domain_id}")
    print(f"Pattern: {args.pattern}  |  count={args.count}  |  delay={args.delay}s")
    print("Waiting 2s for discovery...")
    time.sleep(2)

    try:
        total = 0
        if args.pattern == "all":
            for name, (desc, fn) in PATTERNS.items():
                if fn is None:
                    continue
                print(f"\n{'='*60}")
                print(f"PATTERN: {name} — {desc}  (seq starts at {total})")
                print(f"{'='*60}")
                total = fn(args.count, args.delay, seq=total)
                print(f"  → seq now at {total}")
        else:
            desc, fn = PATTERNS[args.pattern]
            print(f"\n{'='*60}")
            print(f"PATTERN: {args.pattern} — {desc}")
            print(f"{'='*60}")
            total = fn(args.count, args.delay, seq=0)

        print(f"\nDone. Sent {total} total log messages.")
        # Wait for reliable delivery to complete before destroying the writer.
        # Without this, the writer is destroyed before ACK/repair finishes and
        # subscribers miss most of the burst.
        print("Waiting 3s for reliable delivery...")
        time.sleep(3)

    except KeyboardInterrupt:
        print("\nShutdown requested.")
    finally:
        distlog.Logger.finalize()


if __name__ == "__main__":
    main()
