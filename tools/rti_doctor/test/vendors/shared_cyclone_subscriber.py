#!/usr/bin/env python3
"""Cyclone DDS reader using types generated from shared_idl/CycloneConnext.idl."""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "shared_idl", "generated", "cyclone"))

from DoctorShared import Sample
from cyclonedds.domain import DomainParticipant
from cyclonedds.sub import DataReader, Subscriber
from cyclonedds.topic import Topic


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", required=True)
  parser.add_argument("--duration", type=float, default=10.0)
  args = parser.parse_args()

  participant = DomainParticipant(args.domain)
  topic = Topic(participant, args.topic, Sample)
  reader = DataReader(Subscriber(participant), topic)
  deadline = time.monotonic() + args.duration
  samples = 0
  while time.monotonic() < deadline:
    samples += len(reader.take())
    time.sleep(0.05)

  print(json.dumps({
      "domain": args.domain,
      "topic": args.topic,
      "matched": reader.get_subscription_matched_status().current_count,
      "samples": samples,
  }))


if __name__ == "__main__":
  sys.exit(main())