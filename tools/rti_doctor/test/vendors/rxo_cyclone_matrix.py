#!/usr/bin/env python3
"""Cyclone DDS endpoint for the RxO policy matrix integration test."""

import argparse
import json
import os
import sys
import time

from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "shared_idl", "generated", "cyclone"))

from cyclonedds.domain import DomainParticipant
import cyclonedds.idl as idl
from cyclonedds.idl import annotations as annotate
from cyclonedds.idl.types import int32
from cyclonedds.pub import DataWriter, Publisher
from cyclonedds.qos import Policy, Qos
from cyclonedds.sub import DataReader, Subscriber
from cyclonedds.topic import Topic
from cyclonedds.util import duration


SCENARIOS = (
    "reliability", "durability", "liveliness_kind", "liveliness_lease",
    "destination_order", "presentation_scope", "presentation_coherent",
    "presentation_ordered", "deadline", "latency_budget", "ownership",
    "data_representation", "partition",
)


@annotate.final
@dataclass
class Sample(idl.IdlStruct, typename="DoctorRxO::Sample"):
  id: int32
  annotate.key("id")


def is_strong(args):
  return args.mode == "mismatch" and args.role == "reader"


def selected_scenarios(args):
  names = tuple(name for name in args.scenarios.split(",") if name)
  unknown = set(names) - set(SCENARIOS)
  if unknown:
    raise ValueError(f"unknown scenarios: {', '.join(sorted(unknown))}")
  return names


def entity_policies(scenario, strong):
  representation = Policy.DataRepresentation(
      use_cdrv0_representation=True, use_xcdrv2_representation=False)
  if scenario == "reliability":
    return [Policy.Reliability.Reliable(max_blocking_time=duration(seconds=1))
            if strong else Policy.Reliability.BestEffort]
  if scenario == "durability":
    return [Policy.Durability.TransientLocal if strong else Policy.Durability.Volatile]
  if scenario == "liveliness_kind":
    constructor = (Policy.Liveliness.ManualByTopic if strong
                   else Policy.Liveliness.Automatic)
    return [constructor(lease_duration=duration(seconds=3))]
  if scenario == "liveliness_lease":
    return [Policy.Liveliness.Automatic(
        lease_duration=duration(seconds=1 if strong else 3))]
  if scenario == "destination_order":
    return [Policy.DestinationOrder.BySourceTimestamp if strong
            else Policy.DestinationOrder.ByReceptionTimestamp]
  if scenario == "deadline":
    return [Policy.Deadline(deadline=duration(seconds=1 if strong else 3))]
  if scenario == "latency_budget":
    return [Policy.LatencyBudget(duration(seconds=1 if strong else 3))]
  if scenario == "ownership":
    return [Policy.Ownership.Exclusive if strong else Policy.Ownership.Shared]
  if scenario == "data_representation":
    return [Policy.DataRepresentation(
        use_cdrv0_representation=not strong, use_xcdrv2_representation=strong)]
  return [representation]


def group_policies(scenario, strong):
  if scenario == "partition":
    return [Policy.Partition(partitions=["rxo-reader" if strong else "rxo-writer"])]
  if scenario == "presentation_scope":
    constructor = Policy.PresentationAccessScope.Group if strong else Policy.PresentationAccessScope.Instance
    return [constructor(coherent_access=False, ordered_access=False)]
  if scenario == "presentation_coherent":
    return [Policy.PresentationAccessScope.Instance(
        coherent_access=strong, ordered_access=False)]
  if scenario == "presentation_ordered":
    return [Policy.PresentationAccessScope.Instance(
        coherent_access=False, ordered_access=strong)]
  return []


def create_endpoints(participant, args):
  endpoints = {}
  strong = is_strong(args)
  for scenario in selected_scenarios(args):
    topic = Topic(participant, f"{args.topic_prefix}_{scenario}", Sample)
    if args.role == "writer":
      publisher = Publisher(participant, qos=Qos(*group_policies(scenario, strong)))
      endpoints[scenario] = DataWriter(
          publisher, topic, qos=Qos(*entity_policies(scenario, strong)))
    else:
      subscriber = Subscriber(participant, qos=Qos(*group_policies(scenario, strong)))
      endpoints[scenario] = DataReader(
          subscriber, topic, qos=Qos(*entity_policies(scenario, strong)))
  return endpoints


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
  parser.add_argument("--topic-prefix", required=True)
  parser.add_argument("--role", choices=("writer", "reader"), required=True)
  parser.add_argument("--mode", choices=("compatible", "mismatch"), required=True)
  parser.add_argument("--scenarios", default=",".join(SCENARIOS),
                      help="Comma-separated RxO policy scenarios")
  parser.add_argument("--duration", type=float, default=7.0)
  parser.add_argument("--period", type=float, default=0.05)
  parser.add_argument("--ready-file",
                      help="Write PATH after creating the requested endpoints")
  args = parser.parse_args()

  if args.scenarios == "data_representation" and is_strong(args):
    annotate.xcdrv2(Sample)
  else:
    annotate.cdrv0(Sample)
  participant = DomainParticipant(args.domain)
  endpoints = create_endpoints(participant, args)
  write_ready_file(args.ready_file)
  results = {scenario: {"matched": 0, "samples": 0}
             for scenario in selected_scenarios(args)}
  deadline = time.monotonic() + args.duration
  counter = 0
  while time.monotonic() < deadline:
    counter += 1
    for scenario, endpoint in endpoints.items():
      if args.role == "writer":
        endpoint.write(Sample(id=counter))
        results[scenario]["matched"] = max(
            results[scenario]["matched"], endpoint.get_publication_matched_status().current_count)
        results[scenario]["samples"] += 1
      else:
        results[scenario]["matched"] = max(
            results[scenario]["matched"], endpoint.get_subscription_matched_status().current_count)
        results[scenario]["samples"] += len(endpoint.take())
    time.sleep(args.period)

  print(json.dumps({"vendor": "cyclone", "role": args.role, "mode": args.mode,
                    "results": results}), flush=True)


if __name__ == "__main__":
  sys.exit(main())
