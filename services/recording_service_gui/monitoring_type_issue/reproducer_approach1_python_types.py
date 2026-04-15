#!/usr/bin/env python3
"""
Reproducer Approach 1: Python Generated Types (rtiddsgen -language Python)

Demonstrates that Python-generated type support from the same Connext 7.3.1
IDL files results in 0 matched publications due to XTypes hash mismatch
between Python-generated types and the C++ Recording Service publisher.

Prerequisites:
  - RTI Connext DDS 7.3.1 installed at $NDDSHOME
  - rti.connext 7.3.1 Python package installed
  - Recording Service running on the same domain (default 0):

      rtirecordingservice -cfgFile reproducer_recorder.xml \
        -cfgName reproducer -DDOMAIN_ID=0 -DADMIN_DOMAIN_ID=0

  - Python types generated (already included in python_types/):
      cd python_types
      rtiddsgen -language Python -d . ../idl_source/ServiceCommon.idl
      rtiddsgen -language Python -d . ../idl_source/RoutingServiceMonitoring.idl
      rtiddsgen -language Python -d . ../idl_source/RecordingServiceMonitoring.idl
      rtiddsgen -language Python -d . ../idl_source/ServiceMonitoring.idl

Usage:
  python3 reproducer_approach1_python_types.py [--domain 0]
"""

import argparse
import os
import sys
import time

# Add python_types to path so we can import generated types
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_TYPES_DIR = os.path.join(SCRIPT_DIR, "python_types")
sys.path.insert(0, PYTHON_TYPES_DIR)

import rti.connextdds as dds

# Import generated Python types
try:
    import ServiceMonitoring
    from ServiceMonitoring import (
        RTI_Service_Monitoring_Config,
        RTI_Service_Monitoring_Event,
        RTI_Service_Monitoring_Periodic,
    )
except ImportError as e:
    print(f"ERROR: Could not import generated Python types: {e}")
    print(f"Looked in: {PYTHON_TYPES_DIR}")
    print("Generate them with:")
    print("  cd python_types")
    print("  rtiddsgen -language Python -d . ../idl_source/ServiceCommon.idl")
    print("  rtiddsgen -language Python -d . ../idl_source/RoutingServiceMonitoring.idl")
    print("  rtiddsgen -language Python -d . ../idl_source/RecordingServiceMonitoring.idl")
    print("  rtiddsgen -language Python -d . ../idl_source/ServiceMonitoring.idl")
    sys.exit(1)


MONITORING_TOPICS = {
    "config": {
        "topic": "rti/service/monitoring/config",
        "type": RTI_Service_Monitoring_Config,
        "reliability": dds.ReliabilityKind.RELIABLE,
        "durability": dds.DurabilityKind.TRANSIENT_LOCAL,
    },
    "event": {
        "topic": "rti/service/monitoring/event",
        "type": RTI_Service_Monitoring_Event,
        "reliability": dds.ReliabilityKind.RELIABLE,
        "durability": dds.DurabilityKind.TRANSIENT_LOCAL,
    },
    "periodic": {
        "topic": "rti/service/monitoring/periodic",
        "type": RTI_Service_Monitoring_Periodic,
        "reliability": dds.ReliabilityKind.BEST_EFFORT,
        "durability": dds.DurabilityKind.VOLATILE,
    },
}


def main():
    parser = argparse.ArgumentParser(
        description="Reproducer Approach 1: Python Generated Types"
    )
    parser.add_argument(
        "-d", "--domain", type=int, default=0,
        help="DDS domain ID (must match Recording Service admin domain)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Approach 1: Python Generated Types (rtiddsgen -language Python)")
    print("=" * 60)
    print(f"\nDomain: {args.domain}")
    print(f"Python types dir: {PYTHON_TYPES_DIR}")

    # Create participant
    qos = dds.DomainParticipantQos()
    qos.database.shutdown_cleanup_period = dds.Duration.from_milliseconds(10)
    participant = dds.DomainParticipant(args.domain, qos=qos)
    subscriber = dds.Subscriber(participant)

    readers = {}
    for key, cfg in MONITORING_TOPICS.items():
        topic_type = cfg["type"]
        topic = dds.Topic(participant, cfg["topic"], topic_type)
        reader_qos = dds.DataReaderQos()
        reader_qos.reliability.kind = cfg["reliability"]
        reader_qos.durability.kind = cfg["durability"]
        reader = dds.DataReader(subscriber, topic, reader_qos)
        readers[key] = reader
        print(f"  Created reader: {cfg['topic']}")

    print(f"\nWaiting 10 seconds for matching...")
    time.sleep(10)

    print("\n--- Results ---")
    any_matched = False
    for key, reader in readers.items():
        pubs = reader.matched_publications
        print(f"\n  {MONITORING_TOPICS[key]['topic']}:")
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
        print("RESULT: 0 matched publications on all 3 topics.")
        print()
        print("The XTypes type hash computed from Python-generated type")
        print("support does not match the hash advertised by the C++")
        print("Recording Service publisher. Endpoints never match.")
    print("=" * 60)


if __name__ == "__main__":
    main()
