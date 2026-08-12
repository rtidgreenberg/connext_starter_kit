"""Cross-vendor FINAL/APPENDABLE type-extensibility data-flow matrix."""

import json
import os
import subprocess
import sys
import time
import unittest

# domains lives beside this file. Without this the import resolved only when
# some OTHER test module had already put the test directory on sys.path,
# so the suite passed in a full run and failed when run on its own.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E402
import domains  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "extensibility_connext_endpoint.py")
CYCLONE = os.path.join(VENDORS, "extensibility_cyclone_endpoint.py")


@unittest.skipUnless(
    __import__("importlib").util.find_spec("cyclonedds"),
    "Cyclone DDS Python package not available")
class TestExtensibilityVendorDataFlow(unittest.TestCase):
  """Measure all FINAL/APPENDABLE cross-vendor data-flow combinations."""

  def _command(self, script, domain, topic, role, extensibility, duration):
    command = [
        sys.executable, script, "--domain", str(domain), "--topic", topic,
        "--role", role, "--extensibility", extensibility,
        "--duration", str(duration),
    ]
    # Both directions run TypeObject-v1-only propagation, so the only variable
    # between the two matrices below is which vendor holds the writer. The
    # flag exists only on the Connext endpoint; Cyclone needs no equivalent.
    if script == CONNEXT:
      command.append("--type-object-v1-only")
    return command

  def _result(self, output, command):
    for line in reversed(output.splitlines()):
      if line.startswith("{"):
        return json.loads(line)
    self.fail(f"endpoint emitted no JSON\ncommand={command}\n{output}")

  def _run_pair(self, writer_script, writer_extensibility,
                reader_script, reader_extensibility):
    domain = domains.for_suite("test_extensibility_vendor_e2e")
    topic = f"DoctorExtensibility{domain}"
    reader_command = self._command(
        reader_script, domain, topic, "reader", reader_extensibility, 6)
    writer_command = self._command(
        writer_script, domain, topic, "writer", writer_extensibility, 4)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
      time.sleep(1.0)
      writer = subprocess.run(writer_command, text=True, capture_output=True,
                              timeout=15, check=False)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer.stderr}\n{writer.stdout}")
      reader_stdout, reader_stderr = reader.communicate(timeout=15)
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      reader.kill()
      reader.communicate()
      raise
    return (self._result(writer.stdout, writer_command),
            self._result(reader_stdout, reader_command))

  def _assert_data_flows(self, writer, reader):
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertGreater(writer["results"]["matched"], 0, writer)
    self.assertGreater(reader["results"]["matched"], 0, reader)
    self.assertGreater(reader["results"]["samples"], 0, reader)

  # Delivery here depends on TypeObject-v1-only propagation, which `_command`
  # sets: under Connext 7.7's default TypeObject v2 / TypeInformation
  # propagation none of these four combinations delivers, which is what
  # CYCLONE_CONNEXT_INTEROP_FINDINGS.md establishes. Measured 2026-08-12: with
  # the control, all four deliver ~95 samples; without it, all four deliver
  # none. That also answers MAT-3 for this vendor pair - the two
  # cross-extensibility combinations really do deliver, so asserting it is
  # measured rather than assumed.
  def test_connext_writer_to_cyclone_reader_matrix(self):
    for writer_extensibility, reader_extensibility in (
        ("final", "final"),
        ("appendable", "appendable"),
        ("final", "appendable"),
        ("appendable", "final"),
    ):
      with self.subTest(writer=writer_extensibility, reader=reader_extensibility):
        writer, reader = self._run_pair(
            CONNEXT, writer_extensibility, CYCLONE, reader_extensibility)
        self._assert_data_flows(writer, reader)

  # Cyclone never reciprocally associates when it holds the writer, so no
  # combination in this direction delivers. Measured 2026-08-12 across all four
  # combinations, with and without TypeObject-v1-only propagation on the
  # Connext reader: the Cyclone writer reports matched=0 after ~78 writes in
  # all eight runs, while the same control makes all four combinations of the
  # opposite direction deliver. So this is a property of Cyclone's
  # writer-side assignability evaluation against a Connext reader, and not
  # something this suite's configuration can resolve.
  #
  # Recorded as an expected failure rather than asserted-as-broken, so that it
  # still executes: if it starts passing, unittest reports an unexpected
  # success and CYC-1 needs revisiting. Note this narrows what
  # CYCLONE_CONNEXT_INTEROP_FINDINGS.md concluded - that doc measured a
  # Cyclone writer delivering to a Connext reader under v1-only, but with a
  # richer, in some rows unkeyed type. The control is therefore
  # type-dependent, which the doc does not claim either way (CYC-3).
  @unittest.expectedFailure
  def test_cyclone_writer_to_connext_reader_matrix(self):
    for writer_extensibility, reader_extensibility in (
        ("final", "final"),
        ("appendable", "appendable"),
        ("final", "appendable"),
        ("appendable", "final"),
    ):
      with self.subTest(writer=writer_extensibility, reader=reader_extensibility):
        writer, reader = self._run_pair(
            CYCLONE, writer_extensibility, CONNEXT, reader_extensibility)
        self._assert_data_flows(writer, reader)


if __name__ == "__main__":
  unittest.main()
