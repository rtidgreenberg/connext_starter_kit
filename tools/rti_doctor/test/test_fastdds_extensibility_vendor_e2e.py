"""Cross-vendor FINAL/APPENDABLE compatibility matrix for Connext and Fast DDS."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

# domains lives beside this file. Without this the import resolved only when
# some OTHER test module had already put the test directory on sys.path,
# so the suite passed in a full run and failed when run on its own.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # noqa: E402
import domains  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "extensibility_connext_endpoint.py")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")


class TestFastDdsExtensibilityVendorDataFlow(unittest.TestCase):
  """Verify matching kinds exchange data and mixed kinds remain incompatible."""

  @classmethod
  def setUpClass(cls):
    if shutil.which("docker") is None:
      raise unittest.SkipTest("docker is not installed")
    available = subprocess.run(["docker", "image", "inspect", FASTDDS_IMAGE],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False)
    if available.returncode:
      raise unittest.SkipTest(f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable")

  def _connext_command(self, domain, topic, role, extensibility, representation,
                       duration, start_file=None, ready_file=None,
                       qos_defaults=False):
    command = [
        sys.executable, CONNEXT, "--domain", str(domain), "--topic", topic,
        "--role", role, "--extensibility", extensibility, "--schema", "fastdds",
        "--representation", representation,
        "--duration", str(duration),
    ]
    if start_file is not None:
      # Must exceed the ready wait above: the in-process side is now released
      # only after the container reports ready, so it sits on this gate for the
      # whole of container startup. `wait_for_file` returns silently when it
      # expires rather than failing, so a short timeout here does not error -
      # it starts the countdown early, which is the bug this ordering fixes.
      command.extend(("--wait-for-file", start_file, "--wait-timeout", "120"))
    if ready_file is not None:
      command.extend(("--endpoint-ready-file", ready_file))
    if qos_defaults:
      command.append("--qos-defaults")
    return command

  def _fastdds_command(self, domain, topic, role, extensibility, representation,
                       duration, control_dir=None, start_file=None, ready_file=None,
                       qos_defaults=False):
    command = [
      "docker", "run", "--rm", "--network", "host", "--entrypoint",
      f"/doctor-extensibility-build/doctor_fastdds_{extensibility}",
    ]
    if control_dir is not None:
      command.extend(("--mount", f"type=bind,src={control_dir},dst=/control"))
    command.extend((
        "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
        "--domain", str(domain), "--topic", topic, "--role", role,
        "--extensibility", extensibility, "--representation", representation,
        "--duration", str(duration),
    ))
    if start_file is not None:
      command.extend(("--wait-for-file", f"/control/{os.path.basename(start_file)}",
                      "--wait-timeout", "120"))
    if ready_file is not None:
      command.extend(("--endpoint-ready-file",
                      f"/control/{os.path.basename(ready_file)}"))
    if qos_defaults:
      command.append("--qos-defaults")
    return command

  # 30s was under the observed worst case: a `docker run` on a loaded host has
  # taken 25s here, and the wait has to cover container startup plus Fast DDS
  # initialization, not just one of them.
  def _wait_for_file(self, path, description, timeout=90.0):
    deadline = time.monotonic() + timeout
    while not os.path.exists(path) and time.monotonic() < deadline:
      time.sleep(0.05)
    self.assertTrue(os.path.exists(path), f"{description} did not become ready")

  def _result(self, output, command):
    for line in reversed(output.splitlines()):
      if line.startswith("{"):
        return json.loads(line)
    self.fail(f"endpoint emitted no JSON\ncommand={command}\n{output}")

  def _run_pair(self, writer_vendor, writer_extensibility,
                reader_vendor, reader_extensibility, writer_representation="xcdr1",
                reader_representation="xcdr1", writer_qos_defaults=False,
                reader_qos_defaults=False):
    domain = domains.for_suite("test_fastdds_extensibility_vendor_e2e")
    topic = f"DoctorFastDdsExtensibility_{uuid.uuid4().hex}"
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_repr_", dir=HERE)
    reader_start_file = os.path.join(control_dir, "reader.start")
    reader_ready_file = os.path.join(control_dir, "reader.ready")
    writer_start_file = os.path.join(control_dir, "writer.start")
    writer_ready_file = os.path.join(control_dir, "writer.ready")
    command_for = self._fastdds_command if writer_vendor == "fastdds" else self._connext_command
    writer_kwargs = ({"control_dir": control_dir, "start_file": writer_start_file,
                      "ready_file": writer_ready_file,
                      "qos_defaults": writer_qos_defaults}
                     if writer_vendor == "fastdds" else
                     {"start_file": writer_start_file, "ready_file": writer_ready_file,
                      "qos_defaults": writer_qos_defaults})
    writer_command = command_for(domain, topic, "writer", writer_extensibility,
                                 writer_representation, 8, **writer_kwargs)
    command_for = self._fastdds_command if reader_vendor == "fastdds" else self._connext_command
    reader_kwargs = ({"control_dir": control_dir, "start_file": reader_start_file,
                      "ready_file": reader_ready_file,
                      "qos_defaults": reader_qos_defaults}
                     if reader_vendor == "fastdds" else
                     {"start_file": reader_start_file, "ready_file": reader_ready_file,
                      "qos_defaults": reader_qos_defaults})
    reader_command = command_for(domain, topic, "reader", reader_extensibility,
                                 reader_representation, 10, **reader_kwargs)
    # Launch both before releasing either. Each fixture creates its participant,
    # then blocks on its start file, and only begins its --duration countdown
    # once released - so a process launched here costs nobody anything yet.
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    reader_stdout = reader_stderr = writer_stdout = writer_stderr = ""
    try:
      # Release the containerized side FIRST and wait for it to be ready before
      # releasing the in-process one. `docker run` costs 1s on a warm host and
      # 25s on a loaded one, and whichever side is released first pays that wait
      # out of its own budget. Releasing the Connext side first - which is what
      # this did - spent the container's entire startup against a 10s duration,
      # so under load the Connext endpoint had already exited before the
      # container existed: `matched: 0`, no remote participant ever seen, and
      # the writer publishing 100+ samples to nobody. That is HAR-6, and it is
      # why only the direction with the container second ever failed.
      sides = [("reader", reader_vendor, reader_start_file, reader_ready_file),
               ("writer", writer_vendor, writer_start_file, writer_ready_file)]
      sides.sort(key=lambda side: 0 if side[1] == "fastdds" else 1)
      for name, _vendor, start_file, ready_file in sides:
        with open(start_file, "w", encoding="utf-8"):
          pass
        self._wait_for_file(ready_file, name)
      writer_stdout, writer_stderr = writer.communicate(timeout=20)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer_stderr}\n{writer_stdout}")
      reader_stdout, reader_stderr = reader.communicate(timeout=20)
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      if writer.poll() is None:
        writer.kill()
      writer_stdout, writer_stderr = writer.communicate()
      if reader.poll() is None:
        reader.kill()
      reader_stdout, reader_stderr = reader.communicate()
      print("Fast DDS fixture failure:\n"
            f"reader command: {reader_command}\nreader stderr:\n{reader_stderr}\n"
            f"reader stdout:\n{reader_stdout}\n"
            f"writer command: {writer_command}\nwriter stderr:\n{writer_stderr}\n"
            f"writer stdout:\n{writer_stdout}", file=sys.stderr)
      raise
    finally:
      shutil.rmtree(control_dir, ignore_errors=True)
    writer_result = self._result(writer_stdout, writer_command)
    reader_result = self._result(reader_stdout, reader_command)
    self.assertEqual(writer_result["extensibility"], writer_extensibility,
             writer_result)
    self.assertEqual(reader_result["extensibility"], reader_extensibility,
             reader_result)
    self.assertEqual(writer_result["representation"], writer_representation,
             writer_result)
    self.assertEqual(reader_result["representation"], reader_representation,
             reader_result)
    return writer_result, reader_result

  def _assert_data_flows(self, writer, reader):
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertGreater(writer["results"]["matched"], 0, writer)
    self.assertGreater(reader["results"]["matched"], 0, reader)
    self.assertGreater(reader["results"]["samples"], 0, reader)

  def _assert_made_contact(self, writer, reader):
    """Evidence the two endpoints actually found each other.

    A negative expectation - no match, or no data - is vacuous on its own: it
    is equally satisfied by a correct refusal and by a run in which nothing
    discovered anything, so these subtests reported `ok` through exactly the
    failure the compatible subtests were failing on (HAR-6, 2026-08-13). The
    Connext half of the pair reports how many remote participants SPDP turned
    up; requiring that to be non-zero makes the subtest mean "refused after
    contact" rather than "silent". Only the Connext side carries the field -
    the Fast DDS fixture lives in the image and is not rebuilt for this - so
    whichever side is Connext is the one that has to show contact.
    """
    connext_side = self._connext_side(writer, reader)
    self.assertGreater(
        connext_side["results"].get("remote_participants", 0), 0,
        "no remote participant was ever discovered: this pair proves nothing "
        f"about incompatibility, only that nothing talked. {connext_side}")

  def _connext_side(self, writer, reader):
    """Whichever half of the pair is Connext, and so reports RTI statuses."""
    side = next(
        (end for end in (writer, reader) if end["vendor"] == "connext"), None)
    self.assertIsNotNone(side, (writer, reader))
    return side

  def _assert_representation_blocks_the_match(self, writer, reader):
    """Mismatched DATA_REPRESENTATION: no match, and the middleware says why.

    The policy name comes from RequestedIncompatibleQosStatus.policies (or the
    offered equivalent), which reports every policy that blocked the match with
    a count each. Asserting on it turns this from "nothing matched" into "the
    middleware rejected this pair on DATA_REPRESENTATION specifically", which
    is the claim the subtest is actually making.
    """
    self._assert_made_contact(writer, reader)
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertEqual(writer["results"]["matched"], 0, writer)
    self.assertEqual(reader["results"]["matched"], 0, reader)
    self.assertEqual(reader["results"]["samples"], 0, reader)
    connext_side = self._connext_side(writer, reader)
    policies = connext_side["results"].get("incompatible_policies", {})
    self.assertIn(
        "DataRepresentation", policies,
        "the endpoints did not match, but the middleware never named "
        "DATA_REPRESENTATION as the reason - so this is not evidence that the "
        f"representation mismatch is what blocked it. reported: {policies}")

  def _assert_extensibility_blocks_the_data(self, writer, reader):
    """Mismatched extensibility: data must not cross, but a match may form.

    Deliberately weaker than the representation case, and not merged with it.
    DATA_REPRESENTATION is a QoS policy, so a mismatch is refused during
    matching and `matched` stays 0. Extensibility is a property of the type,
    and Connext and Fast DDS are observed to match `final` against
    `appendable` endpoints and then fail to deliver - so asserting `matched
    == 0` here fails against correct behaviour. What the pair must show is
    that no sample crossed.
    """
    self._assert_made_contact(writer, reader)
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertEqual(reader["results"]["samples"], 0, reader)

  def _run_matrix(self, writer_vendor, reader_vendor):
    for writer_extensibility, reader_extensibility in (
        ("final", "final"),
        ("appendable", "appendable"),
        ("final", "appendable"),
        ("appendable", "final"),
    ):
      with self.subTest(writer=writer_extensibility, reader=reader_extensibility):
        writer, reader = self._run_pair(
            writer_vendor, writer_extensibility, reader_vendor, reader_extensibility)
        if writer_extensibility == reader_extensibility:
          self._assert_data_flows(writer, reader)
        else:
          self._assert_extensibility_blocks_the_data(writer, reader)

  def test_connext_writer_to_fastdds_reader_matrix(self):
    self._run_matrix("connext", "fastdds")

  def test_fastdds_writer_to_connext_reader_matrix(self):
    self._run_matrix("fastdds", "connext")

  def test_data_representation_compatibility_matrix(self):
    for writer_vendor, reader_vendor in (("connext", "fastdds"),
                                         ("fastdds", "connext")):
      for writer_representation, reader_representation in (
          ("xcdr1", "xcdr1"),
          ("xcdr2", "xcdr2"),
          ("xcdr1", "xcdr2"),
          ("xcdr2", "xcdr1"),
      ):
        with self.subTest(writer_vendor=writer_vendor, reader_vendor=reader_vendor,
                          writer_representation=writer_representation,
                          reader_representation=reader_representation):
          writer, reader = self._run_pair(
              writer_vendor, "final", reader_vendor, "final",
              writer_representation, reader_representation)
          if writer_representation == reader_representation:
            self._assert_data_flows(writer, reader)
          else:
            self._assert_representation_blocks_the_match(writer, reader)

  def test_fastdds_and_connext_default_endpoint_qos_deserialize(self):
    writer, reader = self._run_pair(
        "fastdds", "final", "connext", "final",
        writer_representation="default", writer_qos_defaults=True,
        reader_qos_defaults=True)
    self.assertTrue(writer["qos_defaults"], writer)
    self.assertTrue(reader["qos_defaults"], reader)
    self._assert_data_flows(writer, reader)


if __name__ == "__main__":
  unittest.main()