"""The mixed_qos scenario's own shape, asserted without a domain.

`mixed_qos_plan` decides the entire scenario - which policies each topic breaks,
how many endpoints it carries and which application hosts each - so it is worth
testing where it can be tested exhaustively, over many seeds in milliseconds,
rather than only by watching one live run at a time.

The bug this suite exists against was invisible for exactly that reason: the
plan was drawn per topic with an independent `sample()`, and with the fixed seed
of 42 that produced RELIABILITY in all six topics and DURABILITY in one. Nothing
failed. The scenario simply stopped covering most of what it claimed to.
"""

import collections
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fixture_publisher as fixture  # noqa: E402

SEEDS = range(60)


def plans(topic_count=6, participants=5):
  """One plan per seed, so a property can be asserted over many draws.

  Sixty seeds rather than one: every assertion here is about the DISTRIBUTION a
  random plan produces, and a property checked against a single draw is exactly
  the mistake that let the old skew through.
  """
  return [fixture.mixed_qos_plan(topic_count, seed, participants, "T")
          for seed in SEEDS]


class TestPolicyCoverageIsEven(unittest.TestCase):

  def test_six_topics_use_all_six_distinct_pairs(self):
    """A full deck deals every pair exactly once before any repeats."""
    for seed, plan in zip(SEEDS, plans()):
      with self.subTest(seed=seed):
        pairs = [frozenset(topic.policies) for topic in plan]
        self.assertEqual(len(set(pairs)), 6, "a pair repeated inside one deck")

  def test_every_policy_appears_in_exactly_three_of_six_topics(self):
    """The property the old fixed seed violated 6-to-1."""
    for seed, plan in zip(SEEDS, plans()):
      with self.subTest(seed=seed):
        counts = collections.Counter(
            policy for topic in plan for policy in topic.policies)
        self.assertEqual(set(counts), set(fixture.MIXED_QOS_POLICIES))
        self.assertEqual(set(counts.values()), {3})

  def test_more_topics_than_pairs_exhausts_the_deck_before_repeating(self):
    """Eight topics must still use all six pairs, not six of them twice."""
    for seed in SEEDS:
      with self.subTest(seed=seed):
        plan = fixture.mixed_qos_plan(8, seed, 5, "T")
        pairs = [frozenset(topic.policies) for topic in plan]
        self.assertEqual(len(set(pairs[:6])), 6)
        self.assertEqual(len(set(pairs)), 6)

  def test_fewer_topics_than_pairs_still_never_repeats(self):
    for seed in SEEDS:
      with self.subTest(seed=seed):
        plan = fixture.mixed_qos_plan(3, seed, 5, "T")
        pairs = [frozenset(topic.policies) for topic in plan]
        self.assertEqual(len(set(pairs)), 3)


class TestOwnershipContentionIsGuaranteed(unittest.TestCase):
  """The case the probe's isolation exists for must never be absent.

  It only arises where OWNERSHIP is not one of the broken policies, so an
  unconstrained draw can miss it entirely - and because which writer loses
  arbitration is arbitrary but stable within a run, a scenario that contains it
  only on average would report the bug only sometimes.
  """

  def test_every_seed_produces_a_contended_topic(self):
    for seed, plan in zip(SEEDS, plans()):
      with self.subTest(seed=seed):
        self.assertTrue(
            any(fixture._contends_for_ownership(topic) for topic in plan),
            "no topic puts two EXCLUSIVE writers in competition")

  def test_it_holds_for_a_single_topic_run_too(self):
    """One topic is where an unconstrained draw is most likely to miss it."""
    for seed in SEEDS:
      with self.subTest(seed=seed):
        plan = fixture.mixed_qos_plan(1, seed, 5, "T")
        self.assertTrue(fixture._contends_for_ownership(plan[0]))

  def test_contention_needs_both_two_writers_and_an_intact_ownership(self):
    """The predicate itself, since everything above rests on it."""
    def topic(policies, writers):
      return fixture.TopicPlan("T_01", policies, list(range(writers)), [0])
    self.assertTrue(fixture._contends_for_ownership(
        topic(("reliability", "deadline"), 2)))
    self.assertFalse(fixture._contends_for_ownership(
        topic(("reliability", "ownership"), 2)),
        "a SHARED writer does not compete with an EXCLUSIVE one")
    self.assertFalse(fixture._contends_for_ownership(
        topic(("reliability", "deadline"), 1)),
        "one writer contends with nobody")


class TestTheTopologyVaries(unittest.TestCase):

  def test_endpoint_counts_stay_within_their_bounds(self):
    low_w, high_w = fixture.MIXED_WRITERS_PER_TOPIC
    low_r, high_r = fixture.MIXED_READERS_PER_TOPIC
    for seed, plan in zip(SEEDS, plans()):
      for topic in plan:
        with self.subTest(seed=seed, topic=topic.name):
          self.assertTrue(low_w <= len(topic.writer_apps) <= high_w)
          self.assertTrue(low_r <= len(topic.reader_apps) <= high_r)

  def test_every_topic_keeps_one_matching_and_one_weakened_writer(self):
    """The scenario's contract, and why the writer floor is 2 rather than 1."""
    for seed, plan in zip(SEEDS, plans()):
      for topic in plan:
        with self.subTest(seed=seed, topic=topic.name):
          self.assertGreaterEqual(len(topic.writer_apps), 2)

  def test_every_application_index_is_addressable(self):
    for seed, plan in zip(SEEDS, plans(participants=3)):
      for topic in plan:
        with self.subTest(seed=seed, topic=topic.name):
          for app in list(topic.writer_apps) + list(topic.reader_apps):
            self.assertIn(app, range(3))

  def test_readers_avoid_the_writer_applications_when_there_is_room(self):
    """A mismatch should be a fault between applications, not inside one."""
    for seed, plan in zip(SEEDS, plans(participants=5)):
      for topic in plan:
        if len(topic.writer_apps) + len(topic.reader_apps) > 5:
          continue          # more endpoints than applications: overlap is honest
        with self.subTest(seed=seed, topic=topic.name):
          self.assertFalse(set(topic.writer_apps) & set(topic.reader_apps))

  def test_the_shape_actually_differs_between_topics_and_runs(self):
    """Otherwise "randomized" would be a claim nothing here checks."""
    shapes = {(len(topic.writer_apps), len(topic.reader_apps))
              for plan in plans() for topic in plan}
    self.assertGreater(len(shapes), 1, "every topic came out the same shape")
    first = [tuple(t.policies) for t in plans()[0]]
    self.assertTrue(any([tuple(t.policies) for t in plan] != first
                        for plan in plans()[1:]),
                    "every seed produced the same policy order")


class TestAPlanIsReproducible(unittest.TestCase):
  """A randomized scenario is only usable if a run can be replayed.

  The fixture prints its seed for this reason; if the same seed did not rebuild
  the same scenario, that print would be a lie and a bug found in a random run
  could never be reproduced.
  """

  def test_the_same_seed_rebuilds_an_identical_plan(self):
    for seed in SEEDS:
      with self.subTest(seed=seed):
        self.assertEqual(fixture.mixed_qos_plan(6, seed, 5, "T"),
                         fixture.mixed_qos_plan(6, seed, 5, "T"))

  def test_different_seeds_generally_differ(self):
    distinct = {tuple(fixture.mixed_qos_plan(6, seed, 5, "T"))
                for seed in SEEDS}
    self.assertGreater(len(distinct), len(list(SEEDS)) // 2)

  def test_topics_are_named_from_the_prefix_in_order(self):
    plan = fixture.mixed_qos_plan(3, 1, 5, "DoctorManualMixed")
    self.assertEqual([topic.name for topic in plan],
                     ["DoctorManualMixed_01", "DoctorManualMixed_02",
                      "DoctorManualMixed_03"])


if __name__ == "__main__":
  unittest.main()
