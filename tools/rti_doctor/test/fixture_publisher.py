#!/usr/bin/env python3
"""Separate-process DynamicData publisher for rti_doctor tests.

One script with a --mode switch rather than six near-identical files, because
every negative fixture differs from the healthy baseline in exactly one way, and
that difference is easier to review side by side.

Modes:
  healthy        rich type, everything correct; expect payload FULL
  best_effort    BEST_EFFORT writer (rti_doctor mirrors it, so this verifies
                 mirroring works rather than testing QoS incompatibility -
                 judging a user's own reader QoS is out of scope)
  no_type_info   type propagation disabled via type_object_max_serialized_length=0
  type_conflict  same topic name, deliberately different type
  large_data     samples above the transport MTU, to exercise fragmentation
  partition      writer in a named partition
  bad_pair       BEST_EFFORT writer plus a RELIABLE + TRANSIENT_LOCAL reader in a
                 second participant, i.e. two live endpoints on one topic that can
                 never match - the case rti_doctor exists to catch
"""

import argparse
import glob
import os
import random
import sys
import time

import rti.connextdds as dds

MODES = ("healthy", "best_effort", "no_type_info", "type_conflict",
         "large_data", "partition", "bad_pair", "scale", "mixed_qos")

MIXED_QOS_POLICIES = ("reliability", "durability", "deadline", "ownership")


def configure_rti_environment():
  ndds_home = os.environ.get("NDDSHOME", "")
  if not ndds_home:
    installs = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
    if installs:
      ndds_home = installs[-1]
      os.environ["NDDSHOME"] = ndds_home
  if not os.environ.get("RTI_LICENSE_FILE") and ndds_home:
    license_path = os.path.join(ndds_home, "rti_license.dat")
    if os.path.isfile(license_path):
      os.environ["RTI_LICENSE_FILE"] = license_path


def build_rich_type(name="DoctorRich"):
  """A type exercising every branch of the field walker."""
  nested = dds.StructType(f"{name}Nested")
  nested.add_member(dds.Member("n_id", dds.Int32Type()))
  nested.add_member(dds.Member("n_val", dds.Float64Type()))

  color = dds.EnumType(f"{name}Color")
  color.add_member(dds.EnumMember("RED", 0))
  color.add_member(dds.EnumMember("GREEN", 5))
  color.add_member(dds.EnumMember("BLUE", 9))

  choice = dds.UnionType(f"{name}Choice", dds.Int32Type())
  choice.add_members([
      dds.UnionMember("as_int", dds.Int32Type(), 1),
      dds.UnionMember("as_double", dds.Float64Type(), 2),
  ])

  struct = dds.StructType(name)
  struct.add_member(dds.Member("id", dds.Int32Type(), is_key=True))
  struct.add_member(dds.Member("label", dds.StringType(64)))
  struct.add_member(dds.Member("nested", nested))
  struct.add_member(dds.Member("scores", dds.SequenceType(dds.Float64Type(), 8)))
  struct.add_member(dds.Member("kids", dds.SequenceType(nested, 4)))
  struct.add_member(dds.Member("color", color))
  struct.add_member(dds.Member("choice", choice))
  struct.add_member(dds.Member("maybe", dds.Int32Type(), is_optional=True))
  struct.add_member(dds.Member("fixed", dds.ArrayType(dds.Int32Type(), 3)))
  return struct


def build_conflict_type(name="DoctorRich"):
  """Same type NAME, structurally incompatible: different member types."""
  struct = dds.StructType(name)
  struct.add_member(dds.Member("id", dds.StringType(32), is_key=True))
  struct.add_member(dds.Member("totally_different", dds.Float32Type()))
  return struct


def build_large_type(name="DoctorLarge"):
  """Type whose samples exceed a normal UDP datagram, forcing fragmentation."""
  struct = dds.StructType(name)
  struct.add_member(dds.Member("id", dds.Int32Type(), is_key=True))
  struct.add_member(dds.Member("blob", dds.SequenceType(dds.OctetType(), 200000)))
  return struct


def populate_rich(sample, counter):
  sample["id"] = counter
  sample["label"] = f"sample-{counter}"
  sample["nested.n_id"] = counter * 2
  sample["nested.n_val"] = counter + 0.5
  sample["scores"] = [1.0, 2.0, 3.0]
  sample["kids[0].n_id"] = 10 + counter
  sample["kids[0].n_val"] = 1.5
  sample["kids[1].n_id"] = 20 + counter
  sample["kids[1].n_val"] = 2.5
  sample["color"] = 5
  sample["choice.as_double"] = 9.75
  sample["fixed"] = [1, 2, 3]


def run_scale(args):
  """Many participants and endpoints, so the scan can be measured at scale.

  Every other mode creates one writer and at most one reader, which is why the
  cost of a system scan and the shape of its issue list were, until this mode
  existed, only ever reasoned about. The scan walks the endpoint dictionary once
  per endpoint in the topic-census checks and once per writer in the RxO and
  assignability checks, so its cost is quadratic in endpoint count and nothing
  exercised that.

  Deliberately healthy: the point is cost and issue-count shape on a system with
  nothing wrong with it. A scan that reports N notes about N writers is as much
  of a problem at scale as a wrong verdict.
  """
  dynamic_type = build_rich_type(args.type_name)
  held = []          # every entity, kept referenced or it is finalized at once
  participants = []

  for index in range(args.scale_participants):
    qos = dds.DomainParticipantQos()
    qos.participant_name.name = f"{args.participant_name}_{index:02d}"
    participant = dds.DomainParticipant(args.domain, qos=qos)
    participants.append(participant)

    publisher = dds.Publisher(participant)
    subscriber = dds.Subscriber(participant)
    held += [publisher, subscriber]

    # A DomainParticipant may hold only one Topic per name, and with more
    # endpoints per participant than topics the names necessarily repeat. Real
    # applications share one Topic between several endpoints for exactly this
    # reason, so the fixture does too.
    topics = {}
    for slot in range(args.scale_endpoints_per_participant):
      topic_name = f"{args.topic}{(index * 7 + slot) % args.scale_topics:02d}"
      if topic_name not in topics:
        topics[topic_name] = dds.DynamicData.Topic(
            participant, topic_name, dynamic_type)
        held.append(topics[topic_name])
      topic = topics[topic_name]
      if slot % 2 == 0:
        writer_qos = dds.DataWriterQos()
        writer_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
        writer_qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        held.append(dds.DynamicData.DataWriter(publisher, topic, writer_qos))
      else:
        reader_qos = dds.DataReaderQos()
        reader_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader_qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        held.append(dds.DynamicData.DataReader(subscriber, topic, reader_qos))

  total = args.scale_participants * args.scale_endpoints_per_participant
  print(f"publishing mode=scale domain={args.domain} "
        f"participants={args.scale_participants} endpoints={total} "
        f"topics={args.scale_topics}", flush=True)

  time.sleep(args.duration)
  for participant in participants:
    participant.close()
  return 0


def mixed_qos_plan(topic_count, seed):
  """Two reproducibly chosen incompatible QoS policies for every topic."""
  chooser = random.Random(seed)
  return [tuple(chooser.sample(MIXED_QOS_POLICIES, 2))
          for _ in range(topic_count)]


def _mixed_reader_qos():
  qos = dds.DataReaderQos()
  qos.reliability.kind = dds.ReliabilityKind.RELIABLE
  qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
  qos.deadline.period = dds.Duration(1)
  qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
  return qos


def _mixed_writer_qos(incompatible_policies=()):
  """A compatible writer, optionally weakened on the named QoS policies."""
  qos = dds.DataWriterQos()
  qos.reliability.kind = dds.ReliabilityKind.RELIABLE
  qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
  qos.deadline.period = dds.Duration(1)
  qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
  if "reliability" in incompatible_policies:
    qos.reliability.kind = dds.ReliabilityKind.BEST_EFFORT
  if "durability" in incompatible_policies:
    qos.durability.kind = dds.DurabilityKind.VOLATILE
  if "deadline" in incompatible_policies:
    qos.deadline.period = dds.Duration(3)
  if "ownership" in incompatible_policies:
    qos.ownership.kind = dds.OwnershipKind.SHARED
  return qos


def run_mixed_qos(args):
  """Five applications and six topics with two good and two bad pairs each.

  Every topic has two writers and two readers. The compatible writer offers the
  QoS both readers request, so it matches twice. The other writer is weakened
  on two selected policies, so it mismatches both readers. This produces the
  useful $2 \times 2$ matrix: two matching pairs and two QoS errors per topic.
  """
  dynamic_type = build_rich_type(args.type_name)
  participants, held, topics = [], [], {}
  plan = mixed_qos_plan(args.mixed_topics, args.mixed_seed)

  for index in range(args.mixed_participants):
    qos = dds.DomainParticipantQos()
    qos.participant_name.name = f"{args.participant_name}_app_{index + 1}"
    participant = dds.DomainParticipant(args.domain, qos=qos)
    participants.append(participant)
    topics[index] = {}
    held += [dds.Publisher(participant), dds.Subscriber(participant)]

  def topic_for(participant_index, topic_name):
    topic = topics[participant_index].get(topic_name)
    if topic is None:
      topic = dds.DynamicData.Topic(participants[participant_index], topic_name,
                                    dynamic_type)
      topics[participant_index][topic_name] = topic
      held.append(topic)
    return topic

  writers = []
  for index, incompatible_policies in enumerate(plan):
    topic_name = f"{args.topic}_{index + 1:02d}"
    good_writer_index = index % args.mixed_participants
    bad_writer_index = (index + 1) % args.mixed_participants
    reader_indices = ((index + 2) % args.mixed_participants,
                      (index + 3) % args.mixed_participants)
    good_publisher = held[good_writer_index * 2]
    bad_publisher = held[bad_writer_index * 2]
    writers.append(dds.DynamicData.DataWriter(
        good_publisher, topic_for(good_writer_index, topic_name),
        _mixed_writer_qos()))
    writers.append(dds.DynamicData.DataWriter(
        bad_publisher, topic_for(bad_writer_index, topic_name),
        _mixed_writer_qos(incompatible_policies)))
    held += writers[-2:]
    for reader_index in reader_indices:
      subscriber = held[reader_index * 2 + 1]
      reader = dds.DynamicData.DataReader(
          subscriber, topic_for(reader_index, topic_name), _mixed_reader_qos())
      held.append(reader)
    print(f"mixed QoS topic={topic_name}: 2 matching pairs; 2 incompatible "
          f"pairs ({', '.join(incompatible_policies).upper()})", flush=True)

  print(f"publishing mode=mixed_qos domain={args.domain} "
        f"participants={args.mixed_participants} topics={args.mixed_topics} "
      f"endpoints={args.mixed_topics * 4} "
        f"seed={args.mixed_seed}", flush=True)
  deadline, counter = time.monotonic() + args.duration, 0
  try:
    while time.monotonic() < deadline:
      counter += 1
      for writer in writers:
        sample = dds.DynamicData(dynamic_type)
        populate_rich(sample, counter)
        writer.write(sample)
      time.sleep(args.period)
  except KeyboardInterrupt:
    pass
  finally:
    for participant in participants:
      participant.close()
  return 0


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--mode", choices=MODES, default="healthy")
  parser.add_argument("--domain", type=int, required=True)
  parser.add_argument("--topic", default="DoctorTopic")
  parser.add_argument("--type-name", default="DoctorRich")
  parser.add_argument("--participant-name", default="doctor_fixture")
  parser.add_argument("--partition", default="secret_partition")
  parser.add_argument("--duration", type=float, default=30.0)
  parser.add_argument("--period", type=float, default=0.25)
  parser.add_argument("--scale-participants", type=int, default=6,
                      help="scale mode: how many remote participants to create")
  parser.add_argument("--scale-topics", type=int, default=12,
                      help="scale mode: how many distinct topics to spread over")
  parser.add_argument("--scale-endpoints-per-participant", type=int, default=16,
                      help="scale mode: readers+writers created per participant")
  parser.add_argument("--mixed-participants", type=int, default=5,
                      help="mixed_qos mode: named applications to create")
  parser.add_argument("--mixed-topics", type=int, default=6,
                      help="mixed_qos mode: topics with two good and two bad pairs")
  parser.add_argument("--mixed-seed", type=int, default=42,
                      help="mixed_qos mode: reproducible QoS-policy selection")
  args = parser.parse_args()

  configure_rti_environment()

  participant_qos = dds.DomainParticipantQos()
  participant_qos.participant_name.name = args.participant_name

  if args.mode == "no_type_info":
    # Disables propagation of BOTH TypeObject v1 and v2, so a remote tool sees
    # the topic and type name but can never build a DynamicType.
    try:
      participant_qos.resource_limits.type_object_max_serialized_length = 0
    except Exception as e:
      print(f"WARNING: could not disable type propagation: {e}", file=sys.stderr)

  if args.mode == "scale":
    return run_scale(args)
  if args.mode == "mixed_qos":
    if args.mixed_participants != 5 or args.mixed_topics != 6:
      parser.error("mixed_qos requires exactly 5 participants and 6 topics")
    return run_mixed_qos(args)

  participant = dds.DomainParticipant(args.domain, qos=participant_qos)

  if args.mode == "type_conflict":
    dynamic_type = build_conflict_type(args.type_name)
  elif args.mode == "large_data":
    dynamic_type = build_large_type(args.type_name)
  else:
    dynamic_type = build_rich_type(args.type_name)

  topic = dds.DynamicData.Topic(participant, args.topic, dynamic_type)

  publisher_qos = dds.PublisherQos()
  if args.mode == "partition":
    publisher_qos.partition.name = [args.partition]
  publisher = dds.Publisher(participant, publisher_qos)

  extra_participant = None
  if args.mode == "bad_pair":
    # A separate participant so the reader really is a different application, as
    # it would be in a live system.
    reader_qos_participant = dds.DomainParticipantQos()
    reader_qos_participant.participant_name.name = f"{args.participant_name}_sub"
    extra_participant = dds.DomainParticipant(args.domain, qos=reader_qos_participant)
    reader_topic = dds.DynamicData.Topic(extra_participant, args.topic, dynamic_type)
    reader_qos = dds.DataReaderQos()
    reader_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    reader_qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    reader_qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
    # Held in a local that outlives the loop: dropping the reference lets the
    # reader be finalized immediately, and it then never appears in discovery.
    extra_subscriber = dds.Subscriber(extra_participant)
    extra_reader = dds.DynamicData.DataReader(extra_subscriber, reader_topic,
                                             reader_qos)
    print(f"created mismatched reader: RELIABLE/TRANSIENT_LOCAL/EXCLUSIVE "
          f"({extra_reader is not None})", flush=True)

  writer_qos = dds.DataWriterQos()
  if args.mode in ("best_effort", "bad_pair"):
    writer_qos.reliability.kind = dds.ReliabilityKind.BEST_EFFORT
  else:
    writer_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
  writer_qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
  writer_qos.history.kind = dds.HistoryKind.KEEP_LAST
  writer_qos.history.depth = 10

  writer = dds.DynamicData.DataWriter(publisher, topic, writer_qos)

  print(f"publishing mode={args.mode} topic={args.topic} type={args.type_name} "
        f"domain={args.domain}", flush=True)

  deadline = time.monotonic() + args.duration
  counter = 0
  try:
    while time.monotonic() < deadline:
      sample = dds.DynamicData(dynamic_type)
      counter += 1
      if args.mode == "large_data":
        sample["id"] = counter
        sample["blob"] = [counter % 256] * 150000
      elif args.mode == "type_conflict":
        sample["id"] = f"key-{counter}"
        sample["totally_different"] = float(counter)
      else:
        populate_rich(sample, counter)
      writer.write(sample)
      time.sleep(args.period)
  except KeyboardInterrupt:
    pass
  finally:
    participant.close()
    if extra_participant is not None:
      extra_participant.close()
  return 0


if __name__ == "__main__":
  sys.exit(main())
