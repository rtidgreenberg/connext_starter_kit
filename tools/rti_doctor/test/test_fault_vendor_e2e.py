"""P0 cross-vendor fault controls for the RTI Doctor CLI.

Each test proves two things independently: the endpoint pair has the intended
DDS behavior, and Doctor reports the corresponding result. ``--no-probe`` is
intentional: otherwise Doctor's mirroring reader becomes an additional matched
reader and obscures the mismatch fixture's endpoint counters.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "rxo_connext_matrix.py")
CYCLONE = os.path.join(VENDORS, "rxo_cyclone_matrix.py")
CONNEXT_EXTENSIBILITY = os.path.join(VENDORS, "extensibility_connext_endpoint.py")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")
DOMAIN_BASE = 40
SCENARIO = "reliability"


def _domain():
  return DOMAIN_BASE + random.randint(1, 80)


def _last_json(output, command):
  for line in reversed(output.splitlines()):
    if line.startswith("{"):
      return json.loads(line)
  raise AssertionError(f"endpoint emitted no JSON\ncommand={command}\n{output}")


@unittest.skipUnless(
    __import__("importlib").util.find_spec("cyclonedds"),
    "Cyclone DDS Python package not available")
class TestConnextCycloneFaultControls(unittest.TestCase):
  """Exercise Doctor against healthy and intentionally incompatible peers."""

  def _endpoint_command(self, script, domain, topic_prefix, role, mode, duration):
    command = [
        sys.executable, script, "--domain", str(domain),
        "--topic-prefix", topic_prefix, "--role", role, "--mode", mode,
        "--scenarios", SCENARIO, "--duration", str(duration),
    ]
    if script == CONNEXT:
      # The established vendor matrix uses TypeObject v1 for this pair.
      command.append("--type-object-v1-only")
    return command

  def _run_doctor(self, domain, topic):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = TOOL_DIR + os.pathsep + environment.get("PYTHONPATH", "")
    command = [
        sys.executable, "-m", "rti_doctor", "--domain", str(domain),
        "--topic", topic, "--format", "json", "--no-domain-scan",
        "--no-probe", "--settle", "1", "--type-wait", "3",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, env=environment,
                               timeout=20, check=False)
    try:
      payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
      self.fail(f"Doctor did not emit JSON: {error}\n{completed.stderr}\n"
                f"{completed.stdout}")
    return completed, payload

  def _run_case(self, writer_script, reader_script, mode):
    domain = _domain()
    prefix = f"DoctorP0_{uuid.uuid4().hex}"
    topic = f"{prefix}_{SCENARIO}"
    reader_command = self._endpoint_command(
        reader_script, domain, prefix, "reader", mode, 12)
    writer_command = self._endpoint_command(
        writer_script, domain, prefix, "writer", mode, 10)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    writer = None
    try:
      # The existing RxO suite establishes this ordering for endpoint discovery.
      time.sleep(3.0)
      writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      time.sleep(1.0)
      doctor, report = self._run_doctor(domain, topic)
      writer_stdout, writer_stderr = writer.communicate(timeout=15)
      reader_stdout, reader_stderr = reader.communicate(timeout=15)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer_stderr}\n{writer_stdout}")
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      for process in (writer, reader):
        if process is not None and process.poll() is None:
          process.kill()
          process.communicate()
      raise
    return doctor, report, _last_json(writer_stdout, writer_command), _last_json(
        reader_stdout, reader_command)

  def _assert_healthy(self, writer_script, reader_script):
    doctor, report, writer, reader = self._run_case(
        writer_script, reader_script, "compatible")
    self.assertEqual(doctor.returncode, 0, doctor.stderr)
    self.assertGreater(writer["results"][SCENARIO]["matched"], 0, writer)
    self.assertGreater(reader["results"][SCENARIO]["matched"], 0, reader)
    self.assertGreater(reader["results"][SCENARIO]["samples"], 0, reader)
    findings = report["findings"]
    active_errors = [item["id"] for item in findings
             if not item["suppressed_by"] and item["severity"] == "ERROR"]
    self.assertEqual(active_errors, [], report)
    self.assertNotIn("qos.rxo_mismatch", [item["id"] for item in findings], report)

  def _assert_reliability_fault(self, writer_script, reader_script):
    doctor, report, writer, reader = self._run_case(
        writer_script, reader_script, "mismatch")
    self.assertEqual(doctor.returncode, 1, doctor.stderr)
    self.assertGreater(writer["results"][SCENARIO]["samples"], 0, writer)
    self.assertEqual(writer["results"][SCENARIO]["matched"], 0, writer)
    self.assertEqual(reader["results"][SCENARIO]["matched"], 0, reader)
    self.assertEqual(reader["results"][SCENARIO]["samples"], 0, reader)
    findings = [item for item in report["findings"] if not item["suppressed_by"]]
    mismatch = [item for item in findings if item["id"] == "qos.rxo_mismatch"]
    self.assertEqual(len(mismatch), 1, report)
    self.assertEqual(mismatch[0]["severity"], "ERROR", mismatch[0])
    self.assertIn("RELIABILITY", mismatch[0]["title"], mismatch[0])

  def test_connext_writer_to_cyclone_reader_healthy(self):
    self._assert_healthy(CONNEXT, CYCLONE)

  def test_cyclone_writer_to_connext_reader_healthy(self):
    self._assert_healthy(CYCLONE, CONNEXT)

  def test_connext_writer_to_cyclone_reader_reliability_fault(self):
    self._assert_reliability_fault(CONNEXT, CYCLONE)

  def test_cyclone_writer_to_connext_reader_reliability_fault(self):
    self._assert_reliability_fault(CYCLONE, CONNEXT)


@unittest.skipUnless(shutil.which("docker"), "docker is not installed")
class TestConnextFastDdsFaultControls(unittest.TestCase):
  """Exercise Doctor against the current Fast DDS fixture in both directions."""

  @classmethod
  def setUpClass(cls):
    available = subprocess.run(
        ["docker", "image", "inspect", FASTDDS_IMAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if available.returncode:
      raise unittest.SkipTest(
          f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable; build it with "
          "test/vendors/fastdds/build_image.sh")

  def _connext_command(self, domain, topic, role, reliability, duration):
    return [
        sys.executable, CONNEXT_EXTENSIBILITY, "--domain", str(domain),
        "--topic", topic, "--role", role, "--extensibility", "final",
        "--schema", "fastdds", "--reliability", reliability,
        "--duration", str(duration),
    ]

  def _fastdds_command(self, domain, topic, role, reliability, duration, control_dir,
                       start_file, endpoint_ready_file):
    command = [
        "docker", "run", "--rm", "--network", "host", "--entrypoint",
        "/doctor-extensibility-build/doctor_fastdds_final",
        "--mount", f"type=bind,src={control_dir},dst=/control",
        "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
        "--domain", str(domain), "--topic", topic, "--role", role,
        "--extensibility", "final", "--reliability", reliability,
        "--duration", str(duration), "--wait-for-file",
        f"/control/{os.path.basename(start_file)}", "--wait-timeout", "15",
        "--endpoint-ready-file", f"/control/{os.path.basename(endpoint_ready_file)}",
    ]
    return command

  def _doctor_command(self, domain, topic, ready_file, connext_log):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = TOOL_DIR + os.pathsep + environment.get("PYTHONPATH", "")
    command = [
        sys.executable, "-m", "rti_doctor", "--domain", str(domain),
        "--topic", topic, "--format", "json", "--no-domain-scan",
        "--no-probe", "--settle", "4", "--type-wait", "3",
        "--ready-file", ready_file,
        "--connext-log", connext_log, "--connext-verbosity", "silent",
    ]
    return command, environment

  def _doctor_result(self, completed):
    try:
      json_start = completed.stdout.find("{")
      payload = json.loads(completed.stdout[json_start:])
    except json.JSONDecodeError as error:
      self.fail(f"Doctor did not emit JSON: {error}\n{completed.stderr}\n"
                f"{completed.stdout}")
    return payload

  def _run_case(self, writer_vendor, mode):
    domain = _domain()
    topic = f"DoctorFastDdsP0_{uuid.uuid4().hex}"
    writer_reliability = "best-effort" if mode == "mismatch" else "reliable"
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_ready_",
                     dir=os.path.join(TOOL_DIR, "..", "..", "test_output"))
    ready_file = os.path.join(control_dir, "doctor.ready")
    connext_log = os.path.join(control_dir, "doctor_connext.log")
    reader_start_file = os.path.join(control_dir, "reader.start")
    reader_ready_file = os.path.join(control_dir, "reader.ready")
    writer_start_file = os.path.join(control_dir, "writer.start")
    writer_ready_file = os.path.join(control_dir, "writer.ready")
    command_for = (self._fastdds_command if writer_vendor == "fastdds"
             else self._connext_command)
    writer_command = command_for(
      domain, topic, "writer", writer_reliability, 10, control_dir,
      writer_start_file, writer_ready_file) if writer_vendor == "fastdds" else command_for(
        domain, topic, "writer", writer_reliability, 10)
    command_for = (self._connext_command if writer_vendor == "fastdds"
             else self._fastdds_command)
    reader_command = command_for(domain, topic, "reader", "reliable", 12) \
      if writer_vendor == "fastdds" else command_for(
          domain, topic, "reader", "reliable", 12, control_dir,
          reader_start_file, reader_ready_file)
    doctor_command, environment = self._doctor_command(
      domain, topic, ready_file, connext_log)
    doctor = subprocess.Popen(doctor_command, text=True, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, env=environment)
    reader = None
    writer = None
    try:
      reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      deadline = time.monotonic() + 30.0
      while not os.path.exists(ready_file) and time.monotonic() < deadline:
        time.sleep(0.05)
      self.assertTrue(os.path.exists(ready_file), "Doctor did not create its readiness marker")
      if writer_vendor != "fastdds":
        with open(reader_start_file, "w", encoding="utf-8"):
          pass
        deadline = time.monotonic() + 10.0
        while not os.path.exists(reader_ready_file) and time.monotonic() < deadline:
          time.sleep(0.05)
        self.assertTrue(os.path.exists(reader_ready_file),
                        "Fast DDS reader did not create its endpoint marker")
      writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      if writer_vendor == "fastdds":
        with open(writer_start_file, "w", encoding="utf-8"):
          pass
      writer_stdout, writer_stderr = writer.communicate(timeout=30)
      reader_stdout, reader_stderr = reader.communicate(timeout=30)
      doctor_stdout, doctor_stderr = doctor.communicate(timeout=30)
      completed = subprocess.CompletedProcess(
          doctor_command, doctor.returncode, doctor_stdout, doctor_stderr)
      report = self._doctor_result(completed)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer_stderr}\n{writer_stdout}")
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      for process in (doctor, writer, reader):
        if process is None:
          continue
        if process.poll() is None:
          process.kill()
        process.communicate()
      shutil.rmtree(control_dir, ignore_errors=True)
      raise
    shutil.rmtree(control_dir, ignore_errors=True)
    return completed, report, _last_json(writer_stdout, writer_command), _last_json(
        reader_stdout, reader_command)

  def _assert_healthy(self, writer_vendor):
    doctor, report, writer, reader = self._run_case(writer_vendor, "compatible")
    active_errors = [item["id"] for item in report["findings"]
                     if not item["suppressed_by"] and item["severity"] == "ERROR"]
    if writer_vendor == "fastdds":
      # The custom FINAL endpoint intentionally exercises a TypeObject variant
      # that Connext rejects, although its generated Fast DDS metadata resolves.
      self.assertEqual(doctor.returncode, 1, f"{doctor.stderr}\n{report}")
      self.assertEqual(active_errors, ["type.assignability"], report)
      self.assertIn("type.resolved", [item["id"] for item in report["findings"]], report)
    else:
      self.assertEqual(doctor.returncode, 0, f"{doctor.stderr}\n{report}")
      self.assertEqual(active_errors, [], report)
    self.assertGreater(reader["results"]["matched"], 0, reader)
    self.assertGreater(reader["results"]["samples"], 0, reader)
    self.assertNotIn("qos.rxo_mismatch",
                     [item["id"] for item in report["findings"]], report)

  def _assert_reliability_fault(self, writer_vendor):
    doctor, report, writer, reader = self._run_case(writer_vendor, "mismatch")
    self.assertEqual(doctor.returncode, 1, f"{doctor.stderr}\n{report}")
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertEqual(writer["results"]["matched"], 0, writer)
    self.assertEqual(reader["results"]["matched"], 0, reader)
    self.assertEqual(reader["results"]["samples"], 0, reader)
    findings = [item for item in report["findings"] if not item["suppressed_by"]]
    mismatch = [item for item in findings if item["id"] == "qos.rxo_mismatch"]
    self.assertEqual(len(mismatch), 1, report)
    self.assertEqual(mismatch[0]["severity"], "ERROR", mismatch[0])
    self.assertIn("RELIABILITY", mismatch[0]["title"], mismatch[0])

  def test_connext_writer_to_fastdds_reader_healthy(self):
    self._assert_healthy("connext")

  def test_fastdds_writer_to_connext_reader_healthy(self):
    self._assert_healthy("fastdds")

  def test_connext_writer_to_fastdds_reader_reliability_fault(self):
    self._assert_reliability_fault("connext")

  def test_fastdds_writer_to_connext_reader_reliability_fault(self):
    self._assert_reliability_fault("fastdds")


if __name__ == "__main__":
  unittest.main()