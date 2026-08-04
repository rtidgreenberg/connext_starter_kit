#!/usr/bin/env python3
"""Eclipse Cyclone DDS publisher, for cross-vendor validation of rti_doctor.

Publishes a type with nested struct, sequence, enum, and string members so that
rti_doctor's field walk is genuinely exercised against a non-RTI writer rather
than only against Connext-produced samples.

Requires the `cyclonedds` pip package. Exits 77 (skip) when it is unavailable so
callers can treat "vendor not installed" as a skip rather than a failure.
"""

import argparse
import json
import sys
import time

SKIP_EXIT = 77

try:
  from dataclasses import dataclass

  import cyclonedds.idl as idl
  import cyclonedds.idl.annotations as annotate
  from cyclonedds.domain import DomainParticipant
  from cyclonedds.idl.types import float64, int32, sequence
  from cyclonedds.pub import DataWriter, Publisher
  from cyclonedds.qos import Policy, Qos
  from cyclonedds.topic import Topic
except Exception as e:  # pragma: no cover - environment dependent
  print(f"cyclonedds unavailable: {e}", file=sys.stderr)
  sys.exit(SKIP_EXIT)


@annotate.final
@dataclass
class Nested(idl.IdlStruct, typename="DoctorCyclone::Nested"):
  n_id: int32
  n_val: float64


@annotate.final
@dataclass
class CycloneSample(idl.IdlStruct, typename="DoctorCyclone::CycloneSample"):
  id: int32
  annotate.key("id")
  label: str
  nested: Nested
  scores: sequence[float64]


@annotate.final
@dataclass
class UnkeyedCycloneSample(
  idl.IdlStruct, typename="DoctorCyclone::CycloneSample"):
  id: int32
  label: str
  nested: Nested
  scores: sequence[float64]


@annotate.appendable
@dataclass
class AppendableNested(idl.IdlStruct, typename="DoctorCyclone::AppendableNested"):
  n_id: int32
  n_val: float64


@annotate.appendable
@dataclass
class AppendableCycloneSample(
    idl.IdlStruct, typename="DoctorCyclone::AppendableCycloneSample"):
  id: int32
  annotate.key("id")
  label: str
  nested: AppendableNested
  scores: sequence[float64]


@annotate.appendable
@dataclass
class AppendableUnkeyedCycloneSample(
  idl.IdlStruct, typename="DoctorCyclone::AppendableCycloneSample"):
  id: int32
  label: str
  nested: AppendableNested
  scores: sequence[float64]


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", default="CycloneTopic")
  parser.add_argument("--duration", type=float, default=40.0)
  parser.add_argument("--period", type=float, default=0.25)
  parser.add_argument("--appendable", action="store_true",
                      help="Publish the RTI-recommended appendable type")
  parser.add_argument("--no-key", action="store_true",
                      help="Publish an otherwise-identical type without @key")
  parser.add_argument("--representation", choices=("xcdr1", "xcdr2"),
                      default="xcdr1",
                      help="Offer only this data representation")
  args = parser.parse_args()

  if args.appendable:
    sample_type = (AppendableUnkeyedCycloneSample if args.no_key
                   else AppendableCycloneSample)
  else:
    sample_type = UnkeyedCycloneSample if args.no_key else CycloneSample
  nested_type = AppendableNested if args.appendable else Nested
  if args.representation == "xcdr1":
    annotate.cdrv0(sample_type)
    annotate.cdrv0(nested_type)
  else:
    annotate.xcdrv2(sample_type)
    annotate.xcdrv2(nested_type)

  participant = DomainParticipant(args.domain)
  topic = Topic(participant, args.topic, sample_type)
  writer_qos = Qos(Policy.DataRepresentation(
      use_cdrv0_representation=args.representation == "xcdr1",
      use_xcdrv2_representation=args.representation == "xcdr2"))
  writer = DataWriter(Publisher(participant), topic, qos=writer_qos)

  print(
      f"cyclone publishing topic={args.topic} domain={args.domain} "
      f"representation={args.representation} no_key={args.no_key}",
      flush=True)

  deadline = time.monotonic() + args.duration
  counter = 0
  max_matched = 0
  total_matched = 0
  while time.monotonic() < deadline:
    counter += 1
    writer.write(sample_type(
        id=counter,
        label=f"cyclone-{counter}",
        nested=nested_type(n_id=counter * 2, n_val=counter + 0.25),
        scores=[1.0, 2.0, 3.0],
    ))
    status = writer.get_publication_matched_status()
    max_matched = max(max_matched, status.current_count)
    total_matched = max(total_matched, status.total_count)
    time.sleep(args.period)
  print(json.dumps({
      "domain": args.domain,
      "topic": args.topic,
      "representation": args.representation,
      "no_key": args.no_key,
      "max_matched": max_matched,
      "total_matched": total_matched,
      "samples": counter,
  }), flush=True)
  return 0


if __name__ == "__main__":
  sys.exit(main())
