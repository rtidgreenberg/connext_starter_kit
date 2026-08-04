#!/usr/bin/env python3
"""Connext reader using types generated from shared_idl/CycloneConnext.idl."""

import argparse
import json
import os
import sys
import time

import rti.connextdds as dds

XTYPES_COMPLIANCE_MASK = 0x000001A9

# Generated types validate this process-global setting when they are imported.
dds.compliance.set_xtypes_mask(
  dds.compliance.XTypesMask(XTYPES_COMPLIANCE_MASK))

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "shared_idl", "generated", "connext"))

from CycloneConnext import DoctorShared

TYPE_OBJECT_V1_MAX_SERIALIZED_LENGTH = 65536


def configure_type_object_v1_only(participant_qos):
  participant_qos.resource_limits.type_code_max_serialized_length = 0
  participant_qos.resource_limits.type_object_max_serialized_length = (
      TYPE_OBJECT_V1_MAX_SERIALIZED_LENGTH)
  type_lookup = getattr(dds.DiscoveryConfigBuiltinChannelKindMask,
                        "TYPE_LOOKUP_SERVICE", None)
  if type_lookup is not None:
    channels = participant_qos.discovery_config.enabled_builtin_channels
    participant_qos.discovery_config.enabled_builtin_channels = (
        dds.DiscoveryConfigBuiltinChannelKindMask(
            int(channels) & ~int(type_lookup)))


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", required=True)
  parser.add_argument("--duration", type=float, default=10.0)
  parser.add_argument("--accept-both-representations", action="store_true",
                      help="Offer XCDR1 and XCDR2 for Cyclone interoperability")
  parser.add_argument("--representation", choices=("xcdr1", "xcdr2"),
                      help="Request only this data representation")
  parser.add_argument("--type-name",
                      help="Register the generated type under this DDS type name")
  parser.add_argument("--type-object-v1-only", action="store_true",
                      help="Advertise TypeObject v1 and disable TypeLookup v2")
  args = parser.parse_args()

  effective_mask = int(dds.compliance.get_xtypes_mask())
  if effective_mask != XTYPES_COMPLIANCE_MASK:
    raise RuntimeError(
        f"expected XTypes mask 0x{XTYPES_COMPLIANCE_MASK:08x}, "
        f"got 0x{effective_mask:08x}")

  participant_qos = None
  if args.type_object_v1_only:
    participant_qos = dds.DomainParticipantQos()
    configure_type_object_v1_only(participant_qos)
  participant = (dds.DomainParticipant(args.domain)
                 if participant_qos is None
                 else dds.DomainParticipant(args.domain, participant_qos))
  topic = dds.Topic(participant, args.topic, DoctorShared.Sample,
                    type_name=args.type_name)
  reader_qos = dds.DataReaderQos()
  if args.representation == "xcdr1":
    reader_qos.data_representation.value = [int(dds.DataRepresentation.XCDR)]
  elif args.representation == "xcdr2":
    reader_qos.data_representation.value = [int(dds.DataRepresentation.XCDR2)]
  elif args.accept_both_representations:
    reader_qos.data_representation.value = [
        int(dds.DataRepresentation.XCDR),
        int(dds.DataRepresentation.XCDR2),
    ]
  reader = dds.DataReader(participant.implicit_subscriber, topic, reader_qos)

  samples = 0
  matched = 0
  deadline = time.monotonic() + args.duration
  while time.monotonic() < deadline:
    matched = max(matched, reader.subscription_matched_status.current_count)
    for sample in reader.take():
      if sample.info.valid:
        samples += 1
    if samples:
      break
    time.sleep(0.1)

  print(json.dumps({
      "domain": args.domain,
      "topic": args.topic,
      "xtypes_compliance_mask": f"0x{effective_mask:08x}",
      "type_object_v1_only": args.type_object_v1_only,
      "matched": matched,
      "samples": samples,
  }), flush=True)
  participant.close()
  return 0 if samples else 1


if __name__ == "__main__":
  sys.exit(main())