#!/usr/bin/env python3
"""Separate-process DynamicData publisher for rti_spy live E2E tests."""

import argparse
import glob
import os
import time

import rti.connextdds as dds


def _configure_rti_environment() -> None:
    if os.environ.get("NDDSHOME"):
        ndds_home = os.environ["NDDSHOME"]
    else:
        installs = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
        ndds_home = installs[-1] if installs else ""
        if ndds_home:
            os.environ["NDDSHOME"] = ndds_home

    if not os.environ.get("RTI_LICENSE_FILE") and ndds_home:
        license_path = os.path.join(ndds_home, "rti_license.dat")
        if os.path.isfile(license_path):
            os.environ["RTI_LICENSE_FILE"] = license_path


def _create_writer(args):
    qos = dds.DomainParticipantQos()
    qos.participant_name.name = args.participant_name
    participant = dds.DomainParticipant(args.domain, qos=qos)
    participant.enable()

    dynamic_type = dds.StructType(args.type_name)
    nested_type = dds.StructType(f"{args.type_name}Nested")
    nested_type.add_member(dds.Member(args.nested_field, dds.Float64Type()))
    dynamic_type.add_member(dds.Member(args.field, dds.Float64Type()))
    dynamic_type.add_member(dds.Member(args.count_field, dds.Int32Type()))
    dynamic_type.add_member(dds.Member(args.nested_member, nested_type))

    topic = dds.DynamicData.Topic(participant, args.topic, dynamic_type)
    publisher = dds.Publisher(participant)
    writer = dds.DynamicData.DataWriter(publisher, topic)
    return participant, topic, publisher, writer, dynamic_type


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", type=int, required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--type-name", required=True)
    parser.add_argument("--participant-name", required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--count-field", required=True)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--nested-field", required=True)
    parser.add_argument("--value", type=float, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--period", type=float, default=0.05)
    args = parser.parse_args()

    _configure_rti_environment()
    participant, topic, publisher, writer, dynamic_type = _create_writer(args)
    try:
        sample = dds.DynamicData(dynamic_type)
        sample[args.field] = args.value
        sample[args.count_field] = args.count
        sample[f"{args.nested_member}.{args.nested_field}"] = args.value + 1.0
        print("READY", flush=True)
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            writer.write(sample)
            time.sleep(args.period)
    finally:
        for entity in (writer, publisher, topic, participant):
            close = getattr(entity, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())