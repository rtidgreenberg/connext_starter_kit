"""Unit tests for the findings model: ranking, suppression, verdicts.

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


class TestSuppression(unittest.TestCase):

  def test_lower_rung_error_suppresses_match_failure(self):
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("match.none", 4, f.Severity.ERROR)]
    f.suppress(items)
    by_id = {x.id: x for x in items}
    self.assertEqual(by_id["match.none"].suppressed_by, "type.no_type_info")
    self.assertIsNone(by_id["type.no_type_info"].suppressed_by)

  def test_warning_explainer_does_not_suppress(self):
    """A WARN is not proof the symptom is accounted for, so it must not hide it."""
    items = [make("locator.unroutable", 1, f.Severity.WARN),
             make("match.none", 4, f.Severity.ERROR)]
    f.suppress(items)
    self.assertIsNone(items[1].suppressed_by)

  def test_probe_not_created_explained_by_missing_type(self):
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("probe.not_created", 4, f.Severity.ERROR)]
    f.suppress(items)
    self.assertEqual(items[1].suppressed_by, "type.no_type_info")

  def test_suppressed_findings_are_retained_not_dropped(self):
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("match.none", 4, f.Severity.ERROR)]
    f.suppress(items)
    self.assertEqual(len(f.active(items)), 1)
    self.assertEqual(len(f.suppressed(items)), 1)
    self.assertEqual(len(items), 2, "suppression must never remove a finding")

  def test_unrelated_error_does_not_suppress(self):
    items = [make("vendor.identify", 1, f.Severity.ERROR),
             make("payload.partial", 5, f.Severity.ERROR)]
    f.suppress(items)
    self.assertIsNone(items[1].suppressed_by)


class TestCounts(unittest.TestCase):

  def test_counts_exclude_suppressed(self):
    items = [make("type.no_type_info", 3, f.Severity.ERROR),
             make("match.none", 4, f.Severity.ERROR)]
    f.suppress(items)
    self.assertEqual(f.counts(items), {f.Severity.ERROR: 1})


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


if __name__ == "__main__":
  unittest.main()
