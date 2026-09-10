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
"""Cyclone DDS publisher using types generated from shared_idl/CycloneConnext.idl."""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "shared_idl", "generated", "cyclone"))

from DoctorShared import Nested, Sample
from cyclonedds.domain import DomainParticipant
from cyclonedds.idl import annotations as annotate
from cyclonedds.pub import DataWriter, Publisher
from cyclonedds.qos import Policy, Qos
from cyclonedds.topic import Topic


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", required=True)
  parser.add_argument("--duration", type=float, default=30.0)
  parser.add_argument("--period", type=float, default=0.1)
  parser.add_argument("--representation", choices=("xcdr1", "xcdr2"),
                      help="Offer only this data representation")
  args = parser.parse_args()

  if args.representation == "xcdr1":
    annotate.cdrv0(Sample)
    annotate.cdrv0(Nested)
  elif args.representation == "xcdr2":
    annotate.xcdrv2(Sample)
    annotate.xcdrv2(Nested)

  participant = DomainParticipant(args.domain)
  topic = Topic(participant, args.topic, Sample)
  writer_qos = None
  if args.representation:
    writer_qos = Qos(Policy.DataRepresentation(
        use_cdrv0_representation=args.representation == "xcdr1",
        use_xcdrv2_representation=args.representation == "xcdr2"))
  writer = DataWriter(Publisher(participant), topic, qos=writer_qos)

  deadline = time.monotonic() + args.duration
  counter = 0
  max_matched = 0
  total_matched = 0
  while time.monotonic() < deadline:
    counter += 1
    writer.write(Sample(
        id=counter,
        label=f"shared-{counter}",
        nested=Nested(n_id=counter * 2, n_val=counter + 0.25),
        scores=[1.0, 2.0, 3.0],
    ))
    status = writer.get_publication_matched_status()
    max_matched = max(max_matched, status.current_count)
    total_matched = max(total_matched, status.total_count)
    time.sleep(args.period)
  print(json.dumps({
      "domain": args.domain,
      "topic": args.topic,
      "representation": args.representation or "default",
      "max_matched": max_matched,
      "total_matched": total_matched,
      "samples": counter,
  }))
  return 0


if __name__ == "__main__":
  sys.exit(main())