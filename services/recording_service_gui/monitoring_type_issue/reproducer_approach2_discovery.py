#!/usr/bin/env python3
"""
Reproducer Approach 2: Discovery-based DynamicType (Runtime Discovery)

Demonstrates that discovering the Recording Service publisher's DynamicType
at runtime and using it to create a reader still results in 0 matched
publications due to type_name FQN mismatch between the publisher's registered
type_name and the DynamicType's fully-qualified name.

Prerequisites:
  - RTI Connext DDS 7.3.1 installed at $NDDSHOME
  - rti.connext 7.3.1 Python package installed
  - Recording Service running on the same domain (default 0):

      rtirecordingservice -cfgFile reproducer_recorder.xml \
        -cfgName reproducer -DDOMAIN_ID=0 -DADMIN_DOMAIN_ID=0

Usage:
  python3 reproducer_approach2_discovery.py [--domain 0]
"""

import argparse
import os
import sys
import time

import rti.connextdds as dds


MONITORING_TOPIC_NAMES = [
    "rti/service/monitoring/config",
    "rti/service/monitoring/event",
    "rti/service/monitoring/periodic",
]


class PubDiscoveryListener(dds.PublicationBuiltinTopicData.DataReaderListener):
    """Listener that captures discovered publication types."""

    def __init__(self):
        super().__init__()
        self.discovered = {}  # topic_name -> (type_name, DynamicType)

    def on_data_available(self, reader):
        for data, sinfo in reader.take():
            if not sinfo.valid:
                continue
            topic = data.topic_name
            type_name = data.type_name
            if topic in MONITORING_TOPIC_NAMES:
                dtype = data.type
                self.discovered[topic] = {
                    "pub_type_name": type_name,
                    "dynamic_type": dtype,
                    "dynamic_type_name": dtype.name if dtype else "None",
                }
                print(f"  DISCOVERED: topic='{topic}' "
                      f"type_name='{type_name}' "
                      f"DynamicType.name='{dtype.name if dtype else 'None'}'")


QOS_MAP = {
    "rti/service/monitoring/config": {
        "reliability": dds.ReliabilityKind.RELIABLE,
        "durability": dds.DurabilityKind.TRANSIENT_LOCAL,
    },
    "rti/service/monitoring/event": {
        "reliability": dds.ReliabilityKind.RELIABLE,
        "durability": dds.DurabilityKind.TRANSIENT_LOCAL,
    },
    "rti/service/monitoring/periodic": {
        "reliability": dds.ReliabilityKind.BEST_EFFORT,
        "durability": dds.DurabilityKind.VOLATILE,
    },
}


def main():
    parser = argparse.ArgumentParser(
        description="Reproducer Approach 2: Discovery-based DynamicType"
    )
    parser.add_argument(
        "-d", "--domain", type=int, default=0,
        help="DDS domain ID (must match Recording Service admin domain)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Approach 2: Discovery-based DynamicType (Runtime Discovery)")
    print("=" * 60)
    print(f"\nDomain: {args.domain}")

    # Step 1: Create participant in disabled state for discovery
    print("\n[1] Creating participant (disabled) for discovery...")
    pfq = dds.DomainParticipantFactoryQos()
    pfq.entity_factory.autoenable_created_entities = False
    dds.DomainParticipant.participant_factory_qos = pfq

    qos = dds.DomainParticipantQos()
    qos.database.shutdown_cleanup_period = dds.Duration.from_milliseconds(10)
    participant = dds.DomainParticipant(args.domain, qos=qos)

    # Attach listener to publication discovery reader
    listener = PubDiscoveryListener()
    participant.publication_reader.set_listener(
        listener, dds.StatusMask.DATA_AVAILABLE
    )

    # Enable participant to start discovery
    participant.enable()

    # Restore factory QoS
    pfq.entity_factory.autoenable_created_entities = True
    dds.DomainParticipant.participant_factory_qos = pfq

    print("\n[2] Waiting 10 seconds for discovery...")
    time.sleep(10)

    if not listener.discovered:
        print("\n  No monitoring publications discovered!")
        print(f"  Is Recording Service running on domain {args.domain}?")
        participant.close()
        return

    # Step 2: Show what was discovered (the type_name mismatch)
    print("\n--- Discovery Results (showing type_name mismatch) ---")
    for topic, info in listener.discovered.items():
        print(f"\n  Topic: {topic}")
        print(f"    Publisher type_name:     '{info['pub_type_name']}'")
        print(f"    DynamicType.name (FQN):  '{info['dynamic_type_name']}'")
        if info['pub_type_name'] != info['dynamic_type_name']:
            print(f"    ** MISMATCH ** — names differ!")

    # Step 3: Try to create readers using discovered types
    print("\n[3] Attempting to create readers with discovered types...")
    subscriber = dds.Subscriber(participant)

    readers = {}
    for topic_name, info in listener.discovered.items():
        dtype = info["dynamic_type"]
        pub_type_name = info["pub_type_name"]
        if dtype is None:
            print(f"  Skipping {topic_name} — no DynamicType discovered")
            continue

        # Register the discovered type with the publisher's type_name
        participant.register_type(pub_type_name, dtype)
        print(f"  Registered type '{pub_type_name}' "
              f"(DynamicType FQN: '{dtype.name}')")

        # Create topic using the publisher's type_name
        topic = dds.DynamicData.Topic(
            participant, topic_name, pub_type_name, dds.TopicQos()
        )

        # Set QoS
        reader_qos = dds.DataReaderQos()
        qos_cfg = QOS_MAP.get(topic_name, {})
        reader_qos.reliability.kind = qos_cfg.get(
            "reliability", dds.ReliabilityKind.RELIABLE
        )
        reader_qos.durability.kind = qos_cfg.get(
            "durability", dds.DurabilityKind.TRANSIENT_LOCAL
        )

        reader = dds.DynamicData.DataReader(subscriber, topic, reader_qos)
        readers[topic_name] = reader
        print(f"  Created reader for '{topic_name}'")

    print(f"\n[4] Waiting 10 seconds for matching...")
    time.sleep(10)

    print("\n--- Matching Results ---")
    any_matched = False
    for topic_name, reader in readers.items():
        pubs = reader.matched_publications
        print(f"\n  {topic_name}:")
        print(f"    matched_publications = {len(pubs)}")
        if len(pubs) > 0:
            any_matched = True

    # Cleanup
    for reader in readers.values():
        reader.close()
    participant.close()

    print("\n" + "=" * 60)
    if any_matched:
        print("UNEXPECTED: Matched publications found.")
    else:
        print("RESULT: 0 matched publications despite successful discovery.")
        print()
        print("The publisher registers the generic type_name")
        print("  (e.g., 'RTI::Service::Monitoring::Config')")
        print("but the discovered DynamicType has the concrete FQN")
        print("  (e.g., 'RTI::RecordingService::Monitoring::Config')")
        print()
        print("Even with register_type(pub_type_name, dtype),")
        print("force_type_validation=False, and XTypes disabled,")
        print("the XTypes hash derived from the DynamicType FQN")
        print("does not match the publisher's advertised hash.")
    print("=" * 60)


if __name__ == "__main__":
    main()
