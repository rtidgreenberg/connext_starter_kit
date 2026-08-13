"""Unit tests for the findings model: ranking, causal links, verdicts.

No DDS required - this is pure logic over plain objects.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rti_doctor import findings as f  # noqa: E402


def make(id_, rung, severity):
  return f.Finding(id=id_, rung=rung, severity=severity, title=f"title {id_}")


class TestRanking(unittest.TestCase):

  def test_severity_dominates_rung(self):
    items = [make("a.low", 0, f.Severity.INFO), make("b.high", 5, f.Severity.ERROR)]
    self.assertEqual([x.id for x in f.rank(items)], ["b.high", "a.low"])

  def test_rung_ascending_within_severity(self):
    items = [make("late", 5, f.Severity.ERROR), make("early", 1, f.Severity.ERROR)]
    self.assertEqual([x.id for x in f.rank(items)], ["early", "late"])

  def test_id_breaks_ties_for_stability(self):
    items = [make("z", 2, f.Severity.WARN), make("a", 2, f.Severity.WARN)]
    self.assertEqual([x.id for x in f.rank(items)], ["a", "z"])


class TestCausalLinks(unittest.TestCase):
  """Links annotate. They must never remove, reorder or downgrade a finding."""

  def test_a_likely_cause_is_recorded_as_context(self):
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("match.none", 4, f.Severity.ERROR)]
    f.link_causes(items)
    by_id = {x.id: x for x in items}
    self.assertEqual(by_id["match.none"].explained_by, ("type.no_type_info",))
    self.assertEqual(by_id["type.no_type_info"].explained_by, ())

  def test_every_finding_stays_active_and_counted(self):
    """The regression: one ERROR removed an unrelated symptom from the counts.

    Suppression matched on finding id across the whole run - no topic, no
    endpoint, no pair - so a type failure on one topic deleted a real, separate
    match failure on another from the active list, the issue counts and the
    exit code.
    """
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("match.none", 4, f.Severity.ERROR)]
    f.link_causes(items)
    self.assertEqual(len(items), 2)
    self.assertEqual(f.counts(items), {f.Severity.ERROR: 2})

  def test_a_link_needs_the_cause_to_be_present(self):
    items = [make("vendor.identify", 1, f.Severity.ERROR),
             make("payload.partial", 5, f.Severity.ERROR)]
    f.link_causes(items)
    self.assertEqual(items[1].explained_by, ())

  def test_severity_does_not_gate_a_link(self):
    """A WARN cause is still worth naming now that naming hides nothing."""
    items = [make("locator.unroutable", 1, f.Severity.WARN),
             make("match.none", 4, f.Severity.ERROR)]
    f.link_causes(items)
    self.assertEqual(items[1].explained_by, ("locator.unroutable",))

  def test_links_are_recomputed_not_accumulated(self):
    finding = make("match.none", 4, f.Severity.ERROR)
    f.link_causes([make("type.no_type_info", 3, f.Severity.ERROR), finding])
    f.link_causes([finding])
    self.assertEqual(finding.explained_by, ())


class TestCounts(unittest.TestCase):

  def test_counts_include_every_finding(self):
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("match.none", 4, f.Severity.ERROR)]
    f.link_causes(items)
    self.assertEqual(f.counts(items), {f.Severity.ERROR: 2})


class TestVerdict(unittest.TestCase):

  def test_not_probed_reports_reason(self):
    outcome = f.ProbeOutcome(attempted=False, skip_reason="no type information")
    self.assertIn("not probed (no type information)", f.verdict_line([], outcome))

  def test_not_matched(self):
    outcome = f.ProbeOutcome(attempted=True, matched=False)
    items = [make("match.none", 4, f.Severity.ERROR)]
    self.assertTrue(f.verdict_line(items, outcome).startswith("NOT MATCHED"))

  def test_matched_but_silent(self):
    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=0)
    self.assertIn("no samples received", f.verdict_line([], outcome))

  def test_a_writer_probe_that_published_nothing_is_not_called_silent(self):
    """A reader target: the probe IS the sending side.

    "matched but no samples received" described the probe's own restraint as a
    symptom of the peer. Verified against a saved report on a Connext reader,
    where the writer probe never published by design and the verdict read as
    though the system were broken.
    """
    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=0,
                             wrote_entity=True, wrote_samples=False)
    line = f.verdict_line([], outcome)
    self.assertIn("nothing published", line)
    self.assertNotIn("no samples received", line)

  def test_a_writer_probe_that_did_publish_is_judged_on_delivery(self):
    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=3,
                             wrote_entity=True, wrote_samples=True,
                             payload_verdict=f.PAYLOAD_FULL)
    self.assertIn("3 sample(s)", f.verdict_line([], outcome))

  def test_full_payload(self):
    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=5,
                             payload_verdict=f.PAYLOAD_FULL)
    self.assertIn("payload FULL", f.verdict_line([], outcome))

  def test_partial_payload_counts_members(self):
    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=5,
                             payload_verdict=f.PAYLOAD_PARTIAL,
                             members_total=41, members_unreadable=2)
    line = f.verdict_line([], outcome)
    self.assertIn("payload PARTIAL", line)
    self.assertIn("2 of 41", line)

  def test_truncated_walk_is_not_reported_as_full(self):
    """FULL is a completeness claim the walk did not earn."""
    from rti_doctor import typewalk
    walk = typewalk.WalkReport()
    walk.add(typewalk.MemberResult("a", typewalk.MemberResult.READABLE, "int32"))
    walk.truncated = True
    self.assertEqual(walk.verdict, f.PAYLOAD_PARTIAL)

    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=1,
                             payload_verdict=f.PAYLOAD_PARTIAL, members_total=1,
                             members_unreadable=0, truncated=True)
    line = f.verdict_line([], outcome)
    self.assertIn("walk truncated", line)
    self.assertNotIn("unreadable", line)

  def test_incomplete_probe_is_appended_to_the_verdict(self):
    """A probe that failed part-way must not leave "payload FULL" standing."""
    outcome = f.ProbeOutcome(attempted=True, matched=True, samples_received=5,
                             payload_verdict=f.PAYLOAD_FULL,
                             incomplete_reason="RuntimeError: status read failed")
    line = f.verdict_line([], outcome)
    self.assertIn("payload FULL", line)
    self.assertIn("probe did not complete: RuntimeError", line)


if __name__ == "__main__":
  unittest.main()
