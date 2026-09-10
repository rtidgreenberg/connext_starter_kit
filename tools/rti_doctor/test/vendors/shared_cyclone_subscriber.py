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