#!/usr/bin/env python3
"""Connext endpoint for the RxO policy matrix integration test."""

import argparse
import json
import os
import sys
import time

import rti.connextdds as dds

dds.compliance.set_xtypes_mask(dds.compliance.XTypesMask(0x000001A9))


SCENARIOS = (
    "reliability", "durability", "liveliness_kind", "liveliness_lease",
    "destination_order", "presentation_scope", "presentation_coherent",
    "presentation_ordered", "deadline", "latency_budget", "ownership",
    "data_representation", "partition",
)

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


def build_type():
  sample = dds.StructType("DoctorRxO::Sample")
  sample.extensibility_kind = dds.ExtensibilityKind.FINAL
  sample.add_member(dds.Member("id", dds.Int32Type(), id=0, is_key=True))
  return sample


def is_strong(args):
  return args.mode == "mismatch" and args.role == "reader"


def selected_scenarios(args):
  names = tuple(name for name in args.scenarios.split(",") if name)
  unknown = set(names) - set(SCENARIOS)
  if unknown:
    raise ValueError(f"unknown scenarios: {', '.join(sorted(unknown))}")
  return names


def configure_entity_qos(qos, scenario, strong):
  qos.data_representation.value = [int(dds.DataRepresentation.XCDR)]
  if scenario == "reliability":
    qos.reliability.kind = (dds.ReliabilityKind.RELIABLE if strong
                            else dds.ReliabilityKind.BEST_EFFORT)
  elif scenario == "durability":
    qos.durability.kind = (dds.DurabilityKind.TRANSIENT_LOCAL if strong
                           else dds.DurabilityKind.VOLATILE)
  elif scenario == "liveliness_kind":
    qos.liveliness.kind = (dds.LivelinessKind.MANUAL_BY_TOPIC if strong
                           else dds.LivelinessKind.AUTOMATIC)
    qos.liveliness.lease_duration = dds.Duration(3)
  elif scenario == "liveliness_lease":
    qos.liveliness.kind = dds.LivelinessKind.AUTOMATIC
    qos.liveliness.lease_duration = dds.Duration(1 if strong else 3)
  elif scenario == "destination_order":
    qos.destination_order.kind = (dds.DestinationOrderKind.BY_SOURCE_TIMESTAMP
                                  if strong else dds.DestinationOrderKind.BY_RECEPTION_TIMESTAMP)
  elif scenario == "deadline":
    qos.deadline.period = dds.Duration(1 if strong else 3)
  elif scenario == "latency_budget":
    qos.latency_budget.duration = dds.Duration(1 if strong else 3)
  elif scenario == "ownership":
    qos.ownership.kind = (dds.OwnershipKind.EXCLUSIVE if strong
                          else dds.OwnershipKind.SHARED)
  elif scenario == "data_representation":
    qos.data_representation.value = [int(dds.DataRepresentation.XCDR2 if strong
                                         else dds.DataRepresentation.XCDR)]


def configure_group_qos(qos, scenario, strong):
  if scenario == "partition":
    qos.partition.name = ["rxo-reader" if strong else "rxo-writer"]
  elif scenario == "presentation_scope":
    qos.presentation.access_scope = (dds.PresentationAccessScopeKind.GROUP if strong
                                     else dds.PresentationAccessScopeKind.INSTANCE)
  elif scenario == "presentation_coherent":
    qos.presentation.coherent_access = strong
  elif scenario == "presentation_ordered":
    qos.presentation.ordered_access = strong


def create_endpoints(participant, args):
  endpoints = {}
  sample_type = build_type()
  strong = is_strong(args)
  for scenario in selected_scenarios(args):
    topic = dds.DynamicData.Topic(participant, f"{args.topic_prefix}_{scenario}", sample_type)
    if args.role == "writer":
      publisher_qos = dds.PublisherQos()
      configure_group_qos(publisher_qos, scenario, strong)
      writer_qos = dds.DataWriterQos()
      configure_entity_qos(writer_qos, scenario, strong)
      endpoints[scenario] = dds.DynamicData.DataWriter(
          dds.Publisher(participant, publisher_qos), topic, writer_qos)
    else:
      subscriber_qos = dds.SubscriberQos()
      configure_group_qos(subscriber_qos, scenario, strong)
      reader_qos = dds.DataReaderQos()
      configure_entity_qos(reader_qos, scenario, strong)
      endpoints[scenario] = dds.DynamicData.DataReader(
          dds.Subscriber(participant, subscriber_qos), topic, reader_qos)
  return sample_type, endpoints


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic-prefix", required=True)
  parser.add_argument("--role", choices=("writer", "reader"), required=True)
  parser.add_argument("--mode", choices=("compatible", "mismatch"), required=True)
  parser.add_argument("--scenarios", default=",".join(SCENARIOS),
                      help="Comma-separated RxO policy scenarios")
  parser.add_argument("--duration", type=float, default=7.0)
  parser.add_argument("--period", type=float, default=0.05)
  parser.add_argument("--type-object-v1-only", action="store_true",
                      help="Advertise TypeObject v1 and disable TypeLookup v2")
  args = parser.parse_args()

  participant_qos = None
  if args.type_object_v1_only:
    participant_qos = dds.DomainParticipantQos()
    configure_type_object_v1_only(participant_qos)
  participant = (dds.DomainParticipant(args.domain)
                 if participant_qos is None
                 else dds.DomainParticipant(args.domain, qos=participant_qos))
  sample_type, endpoints = create_endpoints(participant, args)
  results = {scenario: {"matched": 0, "samples": 0}
             for scenario in selected_scenarios(args)}
  deadline = time.monotonic() + args.duration
  counter = 0
  while time.monotonic() < deadline:
    counter += 1
    for scenario, endpoint in endpoints.items():
      if args.role == "writer":
        sample = dds.DynamicData(sample_type)
        sample["id"] = counter
        endpoint.write(sample)
        results[scenario]["matched"] = max(
            results[scenario]["matched"], endpoint.publication_matched_status.current_count)
        results[scenario]["samples"] += 1
      else:
        results[scenario]["matched"] = max(
            results[scenario]["matched"], endpoint.subscription_matched_status.current_count)
        results[scenario]["samples"] += sum(1 for sample in endpoint.take() if sample.info.valid)
    time.sleep(args.period)

  participant.close()
  print(json.dumps({"vendor": "connext", "role": args.role, "mode": args.mode,
                    "results": results}), flush=True)


if __name__ == "__main__":
  sys.exit(main())
