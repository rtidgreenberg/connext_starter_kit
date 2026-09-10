#!/usr/bin/env python3
# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
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