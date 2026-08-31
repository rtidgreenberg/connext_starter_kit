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
import collections
import glob
import itertools
import os
import random
import sys
import time

import rti.connextdds as dds

MODES = ("healthy", "best_effort", "no_type_info", "type_conflict",
         "large_data", "partition", "bad_pair", "scale", "mixed_qos")

MIXED_QOS_POLICIES = ("reliability", "durability", "deadline", "ownership")

#: Every distinct pair of policies a weakened writer can break. Dealt as a deck
#: rather than sampled per topic - see `_deal_policy_pairs`.
POLICY_PAIRS = tuple(itertools.combinations(MIXED_QOS_POLICIES, 2))

#: Inclusive bounds on a topic's endpoint counts, so topics are lopsided and
#: differ from each other.
#:
#: The writer floor is 2, not 1, and that is the scenario's contract rather than
#: an arbitrary choice: the first writer on a topic always offers exactly what
#: the readers request and the rest are weakened, so a floor of 2 is what makes
#: every topic carry BOTH a matching pair and a QoS error. A ceiling of 3 is
#: what puts two weakened writers on some topics, which is where EXCLUSIVE
#: ownership is contended three ways instead of two.
MIXED_WRITERS_PER_TOPIC = (2, 3)
MIXED_READERS_PER_TOPIC = (1, 3)

#: One topic's shape. `writer_apps[0]` is the healthy writer; the rest are
#: weakened on `policies`. Apps are indices into the participant list.
TopicPlan = collections.namedtuple(
    "TopicPlan", "name policies writer_apps reader_apps")


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


def _deal_policy_pairs(topic_count, chooser):
  """`topic_count` policy pairs, dealt from a reshuffled deck of all six.

  This used to be an independent `sample(MIXED_QOS_POLICIES, 2)` per topic,
  which made duplicates and gaps ordinary rather than exceptional: with the old
  fixed seed of 42 the six topics came out as RELIABILITY in all six and
  DURABILITY in exactly one, with topics 04 and 05 identical - so a scenario
  named "mixed QoS" spent five sixths of itself on one policy, and the run that
  was supposed to exercise the matrix exercised a corner of it.

  Dealing from a shuffled deck gives every distinct pair once before any pair
  repeats. At the default six topics that is all six pairs exactly once and
  every policy in exactly three topics.
  """
  dealt = []
  while len(dealt) < topic_count:
    deck = list(POLICY_PAIRS)
    chooser.shuffle(deck)
    dealt.extend(deck)
  return dealt[:topic_count]


def _contends_for_ownership(topic):
  """Whether this topic puts two EXCLUSIVE writers in competition.

  Two things have to be true. There must be more than one writer, and OWNERSHIP
  must NOT be one of the broken policies - a writer weakened to SHARED never
  competes with an EXCLUSIVE one for ownership of an instance, because the two
  do not match the same reader at all.
  """
  return len(topic.writer_apps) > 1 and "ownership" not in topic.policies


def _guarantee_ownership_contention(plan, chooser):
  """Force at least one topic where equal-strength EXCLUSIVE writers contend.

  This is the case that motivated the probe's isolation, and it is worth
  spending a topic on deliberately: writers of equal ownership strength
  arbitrate per instance, the loser's samples are dropped at every reader as
  `ownership_dropped_sample_count`, and a diagnostic pointed at the losing
  writer sees silence from a writer that is publishing perfectly well. Which
  writer loses is arbitrary but stable within a run, so the symptom is a coin
  flip and not a constant - all the more reason the scenario must always contain
  it rather than contain it on average.

  An unconstrained shuffle can miss it: `ownership` is in half the pairs, so a
  short run can draw only pairs that break it.
  """
  if any(_contends_for_ownership(topic) for topic in plan):
    return plan
  candidates = [index for index, topic in enumerate(plan)
                if len(topic.writer_apps) > 1]
  if not candidates:
    # No topic has two writers to contend, so there is nothing to force.
    return plan
  index = chooser.choice(candidates)
  keep_ownership = [pair for pair in POLICY_PAIRS if "ownership" not in pair]
  plan[index] = plan[index]._replace(policies=chooser.choice(keep_ownership))
  return plan


def mixed_qos_plan(topic_count, seed, participant_count=5,
                   topic_prefix="DoctorTopic"):
  """The whole shape of one mixed_qos run: which policies break, and where.

  Randomized in three ways and fixed in a fourth. The policy pairs are dealt
  evenly, the endpoint counts vary per topic, and which application hosts each
  endpoint is a fresh shuffle per topic - so no two topics have the same shape
  and no two runs have the same scenario. What is NOT randomized is the QoS
  values themselves: every weakening is the same constant it always was, because
  the point of the fixture is that a diagnostic names the right policy, and a
  deadline of 2.7s rather than 3s tests nothing extra while making a failure
  harder to read.

  Reproducible from `seed` alone. The caller prints the seed it used, so a run
  that turned up something interesting can be replayed exactly.
  """
  chooser = random.Random(seed)
  pairs = _deal_policy_pairs(topic_count, chooser)
  plan = []
  for index in range(topic_count):
    writers = chooser.randint(*MIXED_WRITERS_PER_TOPIC)
    readers = chooser.randint(*MIXED_READERS_PER_TOPIC)
    # A fresh shuffle per topic, then readers taken from the tail: readers land
    # in different applications from the writers wherever there are enough to
    # go round, which is what makes a mismatch a cross-application fault rather
    # than one inside a single process. With more endpoints than applications
    # the wrap is honest overlap rather than a failure.
    apps = list(range(participant_count))
    chooser.shuffle(apps)
    # Tuples, so a TopicPlan is hashable and comparable: a plan is a
    # description of a run, and tests compare and de-duplicate whole plans to
    # assert that two seeds differ and that one seed replays.
    writer_apps = tuple(apps[i % participant_count] for i in range(writers))
    reader_apps = tuple(apps[(writers + i) % participant_count]
                        for i in range(readers))
    plan.append(TopicPlan(name=f"{topic_prefix}_{index + 1:02d}",
                          policies=pairs[index], writer_apps=writer_apps,
                          reader_apps=reader_apps))
  return _guarantee_ownership_contention(plan, chooser)


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
  """Applications and topics carrying both matching and incompatible pairs.

  Every topic gets one healthy writer offering exactly what the readers request,
  one or two writers weakened on two policies, and one to three readers - so
  each topic yields matching pairs AND QoS errors, while the shape of each topic
  and of each run differs. `mixed_qos_plan` decides all of it from a seed, and
  the seed is printed: a run that turned up something interesting replays
  exactly with `--mixed-seed`.
  """
  dynamic_type = build_rich_type(args.type_name)
  seed = (args.mixed_seed if args.mixed_seed is not None
          else random.randrange(1, 2 ** 31))
  plan = mixed_qos_plan(args.mixed_topics, seed, args.mixed_participants,
                        args.topic)

  participants, publishers, subscribers, topics = [], [], [], {}
  held = []
  for index in range(args.mixed_participants):
    qos = dds.DomainParticipantQos()
    qos.participant_name.name = f"{args.participant_name}_app_{index + 1}"
    participant = dds.DomainParticipant(args.domain, qos=qos)
    participants.append(participant)
    publishers.append(dds.Publisher(participant))
    subscribers.append(dds.Subscriber(participant))
    topics[index] = {}
  held += publishers + subscribers

  def topic_for(app, topic_name):
    """One Topic per (application, name). A participant may hold only one."""
    topic = topics[app].get(topic_name)
    if topic is None:
      topic = dds.DynamicData.Topic(participants[app], topic_name, dynamic_type)
      topics[app][topic_name] = topic
      held.append(topic)
    return topic

  writers, endpoints = [], 0
  for entry in plan:
    for position, app in enumerate(entry.writer_apps):
      # Position 0 is the healthy writer, always. Every other writer on the
      # topic is weakened on the same pair, which is what lets a topic carry
      # two competing EXCLUSIVE writers without also carrying two different
      # QoS faults to explain.
      qos = (_mixed_writer_qos() if position == 0
             else _mixed_writer_qos(entry.policies))
      writer = dds.DynamicData.DataWriter(
          publishers[app], topic_for(app, entry.name), qos)
      writers.append(writer)
      held.append(writer)
    for app in entry.reader_apps:
      held.append(dds.DynamicData.DataReader(
          subscribers[app], topic_for(app, entry.name), _mixed_reader_qos()))
    endpoints += len(entry.writer_apps) + len(entry.reader_apps)
    contention = ("; EXCLUSIVE ownership contended by "
                  f"{len(entry.writer_apps)} writers"
                  if _contends_for_ownership(entry) else "")
    print(f"mixed QoS topic={entry.name}: "
          f"{len(entry.writer_apps)} writer(s) "
          f"(1 matching, {len(entry.writer_apps) - 1} weakened on "
          f"{', '.join(entry.policies).upper()}), "
          f"{len(entry.reader_apps)} reader(s) in apps "
          f"{[a + 1 for a in entry.reader_apps]}{contention}", flush=True)

  print(f"publishing mode=mixed_qos domain={args.domain} "
        f"participants={args.mixed_participants} topics={args.mixed_topics} "
        f"endpoints={endpoints} seed={seed}", flush=True)
  # On its own line and last, because it is the one thing an operator needs off
  # this output after a run that found something: without it a randomized
  # scenario is not reproducible, and the bug is not either.
  print(f"REPLAY THIS EXACT SCENARIO WITH: --mixed-seed {seed}", flush=True)
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
                      help="mixed_qos mode: topics, each with one matching "
                           "writer and one or two weakened ones")
  parser.add_argument("--mixed-seed", type=int, default=None,
                      help="mixed_qos mode: seed for the policy, endpoint-count "
                           "and application-assignment draw. Omitted, a fresh "
                           "seed is drawn per run and printed, so successive "
                           "runs cover different scenarios; pass the printed "
                           "seed back to replay one exactly")
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
    # Minimums rather than the exact 5-and-6 this used to demand. That check
    # made sense when the scenario was one fixed shape; now that the shape is
    # drawn per run, pinning the counts would forbid the only two dials that
    # still say how big the run is.
    if args.mixed_participants < 2:
      parser.error("mixed_qos needs at least 2 participants, so a writer and a "
                   "reader can land in different applications")
    if args.mixed_topics < 1:
      parser.error("mixed_qos needs at least 1 topic")
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
