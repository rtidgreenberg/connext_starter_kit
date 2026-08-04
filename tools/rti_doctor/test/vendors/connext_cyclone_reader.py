#!/usr/bin/env python3
"""Connext reader for the default Cyclone DDS wire fixture."""

import argparse
import json
import sys
import time

import rti.connextdds as dds

XTYPES_COMPLIANCE_MASK = 0x000001A9
TYPE_OBJECT_V1_MAX_SERIALIZED_LENGTH = 65536


def build_type(appendable=False, final=False, no_key=False):
  prefix = "Appendable" if appendable else ""
  nested = dds.StructType(f"DoctorCyclone::{prefix}Nested")
  if final:
    nested.extensibility_kind = dds.ExtensibilityKind.FINAL
  elif appendable:
    nested.extensibility_kind = dds.ExtensibilityKind.EXTENSIBLE
  nested.add_member(dds.Member("n_id", dds.Int32Type(), id=0))
  nested.add_member(dds.Member("n_val", dds.Float64Type(), id=1))

  sample_type = dds.StructType(f"DoctorCyclone::{prefix}CycloneSample")
  if final:
    sample_type.extensibility_kind = dds.ExtensibilityKind.FINAL
  elif appendable:
    sample_type.extensibility_kind = dds.ExtensibilityKind.EXTENSIBLE
  sample_type.add_member(
      dds.Member("id", dds.Int32Type(), id=0, is_key=not no_key))
  sample_type.add_member(dds.Member("label", dds.StringType(), id=1))
  sample_type.add_member(dds.Member("nested", nested, id=2))
  sample_type.add_member(
      dds.Member("scores", dds.SequenceType(dds.Float64Type()), id=3))
  return sample_type


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
  parser.add_argument("--appendable", action="store_true",
                      help="Use the appendable type matching Cyclone --appendable")
  parser.add_argument("--final", action="store_true",
                      help="Set FINAL extensibility for a compatibility experiment")
  parser.add_argument("--no-key", action="store_true",
                      help="Use an otherwise-identical type without @key")
  parser.add_argument("--accept-both-representations", action="store_true",
                      help="Offer XCDR1 and XCDR2 for Cyclone interoperability")
  parser.add_argument("--representation", choices=("xcdr1", "xcdr2"),
                      help="Request only this data representation")
  parser.add_argument("--other-vendor-profile", action="store_true",
                      help="Apply Connext's other-DDS-vendor participant profile")
  parser.add_argument("--type-object-v1-only", action="store_true",
                      help="Advertise TypeObject v1 and disable TypeLookup v2")
  args = parser.parse_args()

  dds.compliance.set_xtypes_mask(
      dds.compliance.XTypesMask(XTYPES_COMPLIANCE_MASK))
  effective_mask = int(dds.compliance.get_xtypes_mask())
  if effective_mask != XTYPES_COMPLIANCE_MASK:
    raise RuntimeError(
        f"expected XTypes mask 0x{XTYPES_COMPLIANCE_MASK:08x}, "
        f"got 0x{effective_mask:08x}")

  participant_qos = None
  if args.other_vendor_profile:
    participant_qos = dds.QosProvider.default.participant_qos_from_profile(
        "BuiltinQosLib::Generic.OtherDDSVendorCompatibility")
  if args.type_object_v1_only:
    participant_qos = participant_qos or dds.DomainParticipantQos()
    configure_type_object_v1_only(participant_qos)
  participant = (dds.DomainParticipant(args.domain)
                 if participant_qos is None
                 else dds.DomainParticipant(args.domain, qos=participant_qos))
  topic = dds.DynamicData.Topic(participant, args.topic,
                                build_type(args.appendable, args.final,
                                           args.no_key))
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
  reader = dds.DynamicData.DataReader(dds.Subscriber(participant), topic,
                                      reader_qos)

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
      "other_vendor_profile": args.other_vendor_profile,
      "type_object_v1_only": args.type_object_v1_only,
      "no_key": args.no_key,
      "matched": matched,
      "samples": samples,
  }), flush=True)
  participant.close()
  return 0 if samples else 1


if __name__ == "__main__":
  sys.exit(main())