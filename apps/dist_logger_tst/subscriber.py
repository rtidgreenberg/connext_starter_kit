#!/usr/bin/env python3
"""
Distributed Logger Subscriber - discovers the rti/distlog writer via the
DCPSPublication builtin topic (same approach as rtispy), gets the DynamicType
from the discovered writer's data.type, and reads log messages checking order.
"""

import argparse
import asyncio
import re
import signal
import threading
import rti.connextdds as dds
import rti.asyncio


DISTLOG_TOPIC = "rti/distlog"

# Regex to extract the publisher's sequence number from the message body
SEQ_PATTERN = re.compile(r"\[seq=(\d+)\]")

# RTI Distributed Logger log level mapping (actual wire values)
LOG_LEVELS = {
    100: "FATAL",
    200: "SEVERE",
    300: "ERROR",
    400: "WARNING",
    500: "NOTICE",
    600: "INFO",
    700: "DEBUG",
    800: "TRACE",
}


def discover_distlog_writer(participant):
    """Discover the rti/distlog writer via DCPSPublication builtin topic.

    Returns (DynamicType, writer_reliability, writer_durability, writer_partition)
    from the discovered PublicationBuiltinTopicData, exactly like rtispy does.
    Uses participant.publication_reader (shortcut for the builtin publication reader).
    """
    pub_reader = participant.publication_reader

    for data, info in pub_reader.take():
        if info.valid and data.topic_name == DISTLOG_TOPIC:
            return (
                data.type,
                data.reliability,
                data.durability,
                data.partition,
            )
    return None


async def wait_for_distlog_writer(participant):
    """Poll until we discover a writer on rti/distlog."""
    print(f"Waiting to discover a writer on '{DISTLOG_TOPIC}' via DCPSPublication...")
    while True:
        result = discover_distlog_writer(participant)
        if result and result[0] is not None:
            return result
        await asyncio.sleep(0.5)


def print_summary(received_seqs, out_of_order_count):
    """Print order analysis summary."""
    print("\n" + "=" * 110)
    print("ORDER ANALYSIS SUMMARY")
    print("=" * 110)
    total = len(received_seqs)
    print(f"  Total messages received: {total}")
    print(f"  Out-of-order messages:   {out_of_order_count}")

    if total == 0:
        print("  No messages received.")
        return

    valid_seqs = [s for s in received_seqs if s >= 0]
    if valid_seqs == sorted(valid_seqs) and len(valid_seqs) == len(set(valid_seqs)):
        print("  Result: PERFECTLY ORDERED (topic-ordered, monotonically increasing)")
    else:
        print("  Result: OUT OF ORDER detected")
        expected = sorted(valid_seqs)
        print(f"\n  Expected order: {expected[:40]}{'...' if len(expected) > 40 else ''}")
        print(f"  Received order: {valid_seqs[:40]}{'...' if len(valid_seqs) > 40 else ''}")

        breaks = []
        for i in range(1, len(valid_seqs)):
            if valid_seqs[i] <= valid_seqs[i - 1]:
                breaks.append((i, valid_seqs[i - 1], valid_seqs[i]))
        if breaks:
            print(f"\n  Order breaks ({len(breaks)} total):")
            for idx, prev, cur in breaks[:20]:
                print(f"    at recv#{idx}: pub_seq went {prev} -> {cur}")

    if valid_seqs:
        expected_set = set(range(min(valid_seqs), max(valid_seqs) + 1))
        received_set = set(valid_seqs)
        missing = sorted(expected_set - received_set)
        dupes = [s for s in valid_seqs if valid_seqs.count(s) > 1]
        if missing:
            print(f"\n  Missing seq numbers ({len(missing)}): {missing[:30]}{'...' if len(missing) > 30 else ''}")
        if dupes:
            print(f"  Duplicate seq numbers: {sorted(set(dupes))}")
        if not missing and not dupes:
            print("  No gaps or duplicates detected.")


async def run_subscriber(domain_id: int, mode: str = "bulk"):
    participant = dds.DomainParticipant(domain_id)

    # Discover the distlog writer via DCPSPublication builtin topic
    # This gives us the DynamicType + writer QoS (same as rtispy)
    log_type, writer_rel, writer_dur, writer_part = await wait_for_distlog_writer(
        participant
    )
    print(f"Discovered distlog writer — type: {log_type.name}")

    # Create DynamicData topic using the discovered type
    topic = dds.DynamicData.Topic(participant, DISTLOG_TOPIC, log_type)

    # Match subscriber partition with writer if set
    subscriber_qos = dds.SubscriberQos()
    if writer_part:
        subscriber_qos.partition.name = writer_part.name
    subscriber = dds.Subscriber(
        participant, subscriber_qos if writer_part else None
    )

    # Match reader QoS with the discovered writer's QoS
    reader_qos = dds.DataReaderQos()
    if writer_rel:
        reader_qos.reliability.kind = writer_rel.kind
    if writer_dur:
        reader_qos.durability.kind = writer_dur.kind
    reader_qos.history.kind = dds.HistoryKind.KEEP_ALL

    reader = dds.DynamicData.DataReader(subscriber, topic, reader_qos)

    print(f"Subscriber ready (mode={mode}). Waiting for log messages...\n")
    print(f"{'RCV#':>5} | {'PUB_SEQ':>7} | {'LEVEL':<14} | {'ORDER':>8} | MESSAGE")
    print("-" * 110)

    received_seqs = []
    out_of_order_count = 0
    recv_count = 0
    last_pub_seq = -1

    def process_sample(data_sample, info_sample):
        nonlocal recv_count, last_pub_seq, out_of_order_count
        if not info_sample.valid:
            return
        try:
            level_val = data_sample["level"]
            level_str = LOG_LEVELS.get(level_val, f"UNKNOWN({level_val})")
            message = data_sample["message"]

            m = SEQ_PATTERN.search(message)
            pub_seq = int(m.group(1)) if m else -1

            if pub_seq >= 0 and last_pub_seq >= 0 and pub_seq <= last_pub_seq:
                order_flag = "**OOO**"
                out_of_order_count += 1
            else:
                order_flag = "OK"

            received_seqs.append(pub_seq)
            pub_seq_display = pub_seq if pub_seq >= 0 else "?"
            print(
                f"{recv_count:>5} | {pub_seq_display:>7} | "
                f"{level_str:<14} | {order_flag:>8} | {message}"
            )
            last_pub_seq = pub_seq if pub_seq >= 0 else last_pub_seq
            recv_count += 1

        except Exception as e:
            print(f"{recv_count:>5} | {'?':>7} | {'RAW':<14} | {'???':>8} | {data_sample}")
            recv_count += 1

    try:
        if mode == "bulk":
            # Bulk take_async: returns samples grouped by instance
            async for data in reader.take_async():
                process_sample(data.data, data.info)
        elif mode == "sorted":
            # Sorted mode: take() then sort by source_timestamp to
            # reconstruct send order across instances
            while True:
                samples = reader.take()
                if samples:
                    samples.sort(key=lambda s: s.info.source_timestamp)
                    for sample in samples:
                        process_sample(sample.data, sample.info)
                await asyncio.sleep(0.01)
        else:
            # Single mode: poll take() in small batches as they arrive
            while True:
                samples = reader.take()
                for sample in samples:
                    process_sample(sample.data, sample.info)
                await asyncio.sleep(0.01)
    except asyncio.CancelledError:
        pass
    finally:
        print_summary(received_seqs, out_of_order_count)


def run_subscriber_listener(domain_id: int):
    """Listener-based subscriber: on_data_available callback instead of waitsets."""
    participant = dds.DomainParticipant(domain_id)

    # Discover writer synchronously (poll)
    print(f"Waiting to discover a writer on '{DISTLOG_TOPIC}' via DCPSPublication...")
    import time
    result = None
    while result is None:
        result = discover_distlog_writer(participant)
        if result is None or result[0] is None:
            result = None
            time.sleep(0.5)

    log_type, writer_rel, writer_dur, writer_part = result
    print(f"Discovered distlog writer — type: {log_type.name}")

    topic = dds.DynamicData.Topic(participant, DISTLOG_TOPIC, log_type)

    subscriber_qos = dds.SubscriberQos()
    if writer_part:
        subscriber_qos.partition.name = writer_part.name
    subscriber = dds.Subscriber(
        participant, subscriber_qos if writer_part else None
    )

    reader_qos = dds.DataReaderQos()
    if writer_rel:
        reader_qos.reliability.kind = writer_rel.kind
    if writer_dur:
        reader_qos.durability.kind = writer_dur.kind
    reader_qos.history.kind = dds.HistoryKind.KEEP_ALL

    received_seqs = []
    out_of_order_count = 0
    recv_count = 0
    last_pub_seq = -1

    class DistlogListener(dds.DynamicData.NoOpDataReaderListener):
        def on_data_available(self, reader):
            nonlocal recv_count, last_pub_seq, out_of_order_count
            for sample in reader.take():
                if not sample.info.valid:
                    continue
                try:
                    level_val = sample.data["level"]
                    level_str = LOG_LEVELS.get(level_val, f"UNKNOWN({level_val})")
                    message = sample.data["message"]

                    m = SEQ_PATTERN.search(message)
                    pub_seq = int(m.group(1)) if m else -1

                    if pub_seq >= 0 and last_pub_seq >= 0 and pub_seq <= last_pub_seq:
                        order_flag = "**OOO**"
                        out_of_order_count += 1
                    else:
                        order_flag = "OK"

                    received_seqs.append(pub_seq)
                    pub_seq_display = pub_seq if pub_seq >= 0 else "?"
                    print(
                        f"{recv_count:>5} | {pub_seq_display:>7} | "
                        f"{level_str:<14} | {order_flag:>8} | {message}"
                    )
                    last_pub_seq = pub_seq if pub_seq >= 0 else last_pub_seq
                    recv_count += 1
                except Exception:
                    print(f"{recv_count:>5} | {'?':>7} | {'RAW':<14} | {'???':>8} | {sample.data}")
                    recv_count += 1

    listener = DistlogListener()
    reader = dds.DynamicData.DataReader(subscriber, topic, reader_qos)
    reader.set_listener(listener, dds.StatusMask.DATA_AVAILABLE)

    print(f"Subscriber ready (mode=listener). Waiting for log messages...\n")
    print(f"{'RCV#':>5} | {'PUB_SEQ':>7} | {'LEVEL':<14} | {'ORDER':>8} | MESSAGE")
    print("-" * 110)

    # Block main thread until SIGINT
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    stop_event.wait()

    # Detach listener before cleanup
    reader.set_listener(None, dds.StatusMask.NONE)
    print_summary(received_seqs, out_of_order_count)


def main():
    parser = argparse.ArgumentParser(description="Distributed Logger Subscriber")
    parser.add_argument("-d", "--domain-id", type=int, default=0, help="DDS domain ID")
    parser.add_argument(
        "-m", "--mode", default="bulk", choices=["bulk", "single", "sorted", "listener"],
        help="Read mode: 'bulk' = take_async (instance-grouped), 'single' = take() poll, 'sorted' = take() sorted by source_timestamp, 'listener' = DataReaderListener callback",
    )
    args = parser.parse_args()

    print(f"Distributed Logger Subscriber on domain {args.domain_id}  [mode={args.mode}]")
    print("Press Ctrl+C to stop and see order analysis summary.\n")

    try:
        if args.mode == "listener":
            run_subscriber_listener(args.domain_id)
        else:
            rti.asyncio.run(run_subscriber(args.domain_id, args.mode))
    except KeyboardInterrupt:
        pass

    print("\nShutdown.")


if __name__ == "__main__":
    main()
