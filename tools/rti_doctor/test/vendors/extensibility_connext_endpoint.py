#!/usr/bin/env python3
"""Connext endpoint for the FINAL/APPENDABLE interoperability matrix."""

import argparse
import json
import os
import sys
import time

import rti.connextdds as dds


dds.compliance.set_xtypes_mask(dds.compliance.XTypesMask(0x000001A9))
dds.Logger.instance.verbosity = dds.Verbosity.SILENT

#: Positive cap required alongside `type_code_max_serialized_length = 0` for
#: the TypeObject-v1-only control below. Same value as the manual fixtures.
TYPE_OBJECT_V1_MAX_SERIALIZED_LENGTH = 65536


def configure_type_object_v1_only(participant_qos):
  """Restrict type propagation to TypeObject v1, as Cyclone needs.

  `CYCLONE_CONNEXT_INTEROP_FINDINGS.md` establishes that Connext 7.7's default
  TypeObject v2 / TypeInformation propagation is what stops Cyclone
  reciprocally associating: under it Cyclone reports `max_matched=0` however
  long the writer runs, and with this control it matches and data flows. This
  is independent of application `DataRepresentation` and of the process-global
  XTypes compliance mask set above.

  Copied deliberately rather than imported: `connext_cyclone_reader` and
  `shared_connext_reader` each hold their own copy, and all three are manual
  and vendor-matrix fixtures whose participants are built differently. Sharing
  it means one import path across three fixtures that are otherwise
  standalone scripts.
  """
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


def build_type(extensibility, schema):
  sample = dds.StructType("DoctorExtensibility::Sample")
  sample.extensibility_kind = (
      dds.ExtensibilityKind.FINAL if extensibility == "final"
      else dds.ExtensibilityKind.EXTENSIBLE)
  if schema == "fastdds":
    sample.add_member(dds.Member("index", dds.Uint32Type(), id=0))
    sample.add_member(dds.Member("message", dds.StringType(), id=1))
  else:
    sample.add_member(dds.Member("id", dds.Int32Type(), id=0, is_key=True))
  return sample


def wait_for_file(path, timeout):
  if not path:
    return
  deadline = time.monotonic() + timeout
  while not os.path.exists(path) and time.monotonic() < deadline:
    time.sleep(0.05)
  if not os.path.exists(path):
    raise TimeoutError(f"timed out waiting for start signal: {path}")


def write_ready_file(path):
  if not path:
    return
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8") as ready_file:
    ready_file.write("ready\n")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", required=True)
  parser.add_argument("--role", choices=("writer", "reader"), required=True)
  parser.add_argument("--extensibility", choices=("final", "appendable"), required=True)
  parser.add_argument("--schema", choices=("keyed-int32", "fastdds"),
                      default="keyed-int32")
  parser.add_argument("--reliability", choices=("reliable", "best-effort"),
                      default="reliable")
  parser.add_argument("--durability", choices=("volatile", "transient-local"),
                      default="volatile")
  parser.add_argument("--deadline-seconds", type=int, default=1)
  parser.add_argument("--ownership", choices=("shared", "exclusive"),
                      default="shared")
  parser.add_argument("--representation", choices=("xcdr1", "xcdr2"),
                      default="xcdr1")
  parser.add_argument("--duration", type=float, default=6.0)
  parser.add_argument("--wait-for-file",
                      help="Wait for PATH after participant creation")
  parser.add_argument("--wait-timeout", type=float, default=15.0)
  parser.add_argument("--endpoint-ready-file",
                      help="Write PATH after creating the requested endpoint")
  parser.add_argument("--type-object-v1-only", action="store_true",
                      help="Propagate TypeObject v1 only, which is what lets "
                           "Cyclone reciprocally associate (see "
                           "CYCLONE_CONNEXT_INTEROP_FINDINGS.md)")
  args = parser.parse_args()
  if args.deadline_seconds <= 0:
    parser.error("--deadline-seconds must be positive")

  participant_qos = dds.DomainParticipantQos()
  if args.type_object_v1_only:
    # Must precede participant creation: the propagation settings are read
    # when the participant is built, not when an endpoint is added to it.
    configure_type_object_v1_only(participant_qos)
  participant = dds.DomainParticipant(args.domain, qos=participant_qos)
  wait_for_file(args.wait_for_file, args.wait_timeout)
  sample_type = build_type(args.extensibility, args.schema)
  topic = dds.DynamicData.Topic(participant, args.topic, sample_type)
  results = {"matched": 0, "samples": 0}
  deadline = time.monotonic() + args.duration

  if args.role == "writer":
    writer_qos = dds.DataWriterQos()
    writer_qos.data_representation.value = [int(
      dds.DataRepresentation.XCDR2 if args.representation == "xcdr2"
      else dds.DataRepresentation.XCDR)]
    writer_qos.reliability.kind = (
        dds.ReliabilityKind.RELIABLE if args.reliability == "reliable"
        else dds.ReliabilityKind.BEST_EFFORT)
    writer_qos.durability.kind = (
      dds.DurabilityKind.TRANSIENT_LOCAL if args.durability == "transient-local"
      else dds.DurabilityKind.VOLATILE)
    writer_qos.deadline.period = dds.Duration(args.deadline_seconds)
    writer_qos.ownership.kind = (
      dds.OwnershipKind.EXCLUSIVE if args.ownership == "exclusive"
      else dds.OwnershipKind.SHARED)
    writer = dds.DynamicData.DataWriter(dds.Publisher(participant), topic, writer_qos)
    write_ready_file(args.endpoint_ready_file)
    counter = 0
    while time.monotonic() < deadline:
      counter += 1
      sample = dds.DynamicData(sample_type)
      if args.schema == "fastdds":
        sample["index"] = counter
        sample["message"] = "DoctorExtensibility"
      else:
        sample["id"] = counter
      writer.write(sample)
      results["matched"] = max(results["matched"], writer.publication_matched_status.current_count)
      results["samples"] += 1
      time.sleep(0.05)
  else:
    reader_qos = dds.DataReaderQos()
    reader_qos.data_representation.value = [int(
      dds.DataRepresentation.XCDR2 if args.representation == "xcdr2"
      else dds.DataRepresentation.XCDR)]
    reader_qos.reliability.kind = (
        dds.ReliabilityKind.RELIABLE if args.reliability == "reliable"
        else dds.ReliabilityKind.BEST_EFFORT)
    reader_qos.durability.kind = (
      dds.DurabilityKind.TRANSIENT_LOCAL if args.durability == "transient-local"
      else dds.DurabilityKind.VOLATILE)
    reader_qos.deadline.period = dds.Duration(args.deadline_seconds)
    reader_qos.ownership.kind = (
      dds.OwnershipKind.EXCLUSIVE if args.ownership == "exclusive"
      else dds.OwnershipKind.SHARED)
    reader = dds.DynamicData.DataReader(dds.Subscriber(participant), topic, reader_qos)
    write_ready_file(args.endpoint_ready_file)
    while time.monotonic() < deadline:
      results["matched"] = max(results["matched"], reader.subscription_matched_status.current_count)
      results["samples"] += sum(1 for sample in reader.take() if sample.info.valid)
      time.sleep(0.05)

  participant.close()
  print(json.dumps({"vendor": "connext", "role": args.role,
                    "extensibility": args.extensibility,
                    "reliability": args.reliability, "durability": args.durability,
                    "deadline_seconds": args.deadline_seconds,
                    "ownership": args.ownership,
                    "representation": args.representation,
                    "type_object_v1_only": args.type_object_v1_only,
                    "results": results}),
        flush=True)


if __name__ == "__main__":
  sys.exit(main())
