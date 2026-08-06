"""Unit tests for deterministic, port-safe domain selection."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import domains  # noqa: E402


class TestPortSafety(unittest.TestCase):

  def test_the_standard_mapping_is_used(self):
    self.assertEqual(domains.port_range(0), (7400, 7649))
    self.assertEqual(domains.port_range(1), (7650, 7899))

  def test_ranges_do_not_overlap(self):
    _, last = domains.port_range(4)
    first, _ = domains.port_range(5)
    self.assertEqual(first, last + 1)

  def test_a_domain_whose_ports_exceed_the_ceiling_is_unsafe(self):
    ceiling = domains.last_safe_domain()
    self.assertTrue(domains.is_safe(ceiling))
    self.assertFalse(domains.is_safe(ceiling + 1))
    self.assertLessEqual(domains.port_range(ceiling)[1], 65535)
    self.assertGreater(domains.port_range(ceiling + 1)[1], 65535)

  def test_negative_domains_are_unsafe(self):
    self.assertFalse(domains.is_safe(-1))

  def test_the_old_random_bands_could_exceed_the_ceiling(self):
    """Regression context: DOMAIN_BASE=210 + randint(1,20) reached domain 230.

    That is inside the ceiling but leaves only 20 domains of headroom, and the
    suites using base 120 with a span of 100 reached 220. The point of the
    helper is that no caller has to reason about this.
    """
    self.assertLess(domains.last_safe_domain(), 240)


class TestSuiteAssignment(unittest.TestCase):

  def test_the_same_key_always_gives_the_same_domain(self):
    self.assertEqual(domains.for_suite("test_live_integration"),
                     domains.for_suite("test_live_integration"))

  def test_every_assigned_domain_is_safe_and_above_the_reserved_band(self):
    for key in ("a", "b", "test_wire", "test_live_integration", "x" * 200):
      domain = domains.for_suite(key)
      self.assertTrue(domains.is_safe(domain), key)
      self.assertGreaterEqual(domain, domains.FIRST_TEST_DOMAIN, key)

  def test_the_repo_s_own_suites_do_not_collide(self):
    keys = ["test_live_integration", "test_fault_vendor_e2e", "test_rxo_vendor_e2e",
            "test_vendor_wire_e2e", "test_fastdds_type_object_e2e",
            "test_fastdds_extensibility_vendor_e2e",
            "test_fastdds_type_metadata_spike", "test_extensibility_vendor_e2e"]
    assigned = {key: domains.for_suite(key) for key in keys}
    self.assertEqual(len(set(assigned.values())), len(keys),
                     f"two suites share a domain: {assigned}")

  @mock.patch.dict(os.environ, {"RTI_DOCTOR_DOMAIN_OFFSET": "7"})
  def test_the_offset_shifts_the_whole_band(self):
    self.assertEqual(domains.offset(), 7)
    with mock.patch.dict(os.environ, {"RTI_DOCTOR_DOMAIN_OFFSET": "0"}):
      base = domains.for_suite("test_live_integration")
    shifted = domains.for_suite("test_live_integration")
    self.assertNotEqual(base, shifted)
    self.assertTrue(domains.is_safe(shifted))

  @mock.patch.dict(os.environ, {"RTI_DOCTOR_DOMAIN_OFFSET": "not-a-number"})
  def test_a_malformed_offset_is_ignored_rather_than_crashing_every_suite(self):
    self.assertEqual(domains.offset(), 0)


if __name__ == "__main__":
  unittest.main()
