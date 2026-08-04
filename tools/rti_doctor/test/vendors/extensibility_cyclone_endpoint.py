#!/usr/bin/env python3
"""Cyclone DDS endpoint for the FINAL/APPENDABLE interoperability matrix."""

import argparse
import json
import sys
import time
from dataclasses import dataclass

from cyclonedds.domain import DomainParticipant
import cyclonedds.idl as idl
from cyclonedds.idl import annotations as annotate
from cyclonedds.idl.types import int32
from cyclonedds.pub import DataWriter, Publisher
from cyclonedds.qos import Policy, Qos
from cyclonedds.sub import DataReader, Subscriber
from cyclonedds.topic import Topic


def build_type(extensibility):
  if extensibility == "final":
    @annotate.final
    @dataclass
    class Sample(idl.IdlStruct, typename="DoctorExtensibility::Sample"):
      id: int32
      annotate.key("id")
  else:
    @annotate.appendable
    @dataclass
    class Sample(idl.IdlStruct, typename="DoctorExtensibility::Sample"):
      id: int32
      annotate.key("id")
  annotate.cdrv0(Sample)
  return Sample


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", required=True)
  parser.add_argument("--role", choices=("writer", "reader"), required=True)
  parser.add_argument("--extensibility", choices=("final", "appendable"), required=True)
  parser.add_argument("--duration", type=float, default=6.0)
  args = parser.parse_args()

  sample_type = build_type(args.extensibility)
  participant = DomainParticipant(args.domain)
  topic = Topic(participant, args.topic, sample_type)
  representation = Qos(Policy.DataRepresentation(
      use_cdrv0_representation=True, use_xcdrv2_representation=False))
  results = {"matched": 0, "samples": 0}
  deadline = time.monotonic() + args.duration

  if args.role == "writer":
    writer = DataWriter(Publisher(participant), topic, qos=representation)
    counter = 0
    while time.monotonic() < deadline:
      counter += 1
      writer.write(sample_type(id=counter))
      results["matched"] = max(
          results["matched"], writer.get_publication_matched_status().current_count)
      results["samples"] += 1
      time.sleep(0.05)
  else:
    reader = DataReader(Subscriber(participant), topic, qos=representation)
    while time.monotonic() < deadline:
      results["matched"] = max(
          results["matched"], reader.get_subscription_matched_status().current_count)
      results["samples"] += len(reader.take())
      time.sleep(0.05)

  print(json.dumps({"vendor": "cyclone", "role": args.role,
                    "extensibility": args.extensibility, "results": results}),
        flush=True)


if __name__ == "__main__":
  sys.exit(main())
