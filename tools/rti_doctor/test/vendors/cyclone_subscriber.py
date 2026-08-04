#!/usr/bin/env python3
"""Cyclone DDS reader that keeps the vendor wire fixture transmitting."""

import argparse
import sys
import time

from cyclone_publisher import CycloneSample
from cyclonedds.domain import DomainParticipant
from cyclonedds.sub import DataReader, Subscriber
from cyclonedds.topic import Topic


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", required=True)
  parser.add_argument("--duration", type=float, default=45.0)
  args = parser.parse_args()

  participant = DomainParticipant(args.domain)
  topic = Topic(participant, args.topic, CycloneSample)
  reader = DataReader(Subscriber(participant), topic)
  print(f"cyclone subscribing topic={args.topic} domain={args.domain}", flush=True)
  deadline = time.monotonic() + args.duration
  while time.monotonic() < deadline:
    reader.take()
    time.sleep(0.05)
  return 0


if __name__ == "__main__":
  sys.exit(main())