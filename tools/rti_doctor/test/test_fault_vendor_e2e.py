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
sys.path.insert(0, HERE)

import doctor_e2e  # noqa: E402

VENDORS = os.path.join(HERE, "vendors")
CONNEXT = os.path.join(VENDORS, "rxo_connext_matrix.py")
CYCLONE = os.path.join(VENDORS, "rxo_cyclone_matrix.py")
CONNEXT_EXTENSIBILITY = os.path.join(VENDORS, "extensibility_connext_endpoint.py")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")
DOMAIN_BASE = 40
RELIABILITY_SCENARIO = "reliability"
DURABILITY_SCENARIO = "durability"
OUTPUT_ROOT = os.path.join(TOOL_DIR, "..", "..", "test_output")
ARTIFACT_ROOT = os.path.join(OUTPUT_ROOT, "rti_doctor_faults")


def _domain():
  return DOMAIN_BASE + random.randint(1, 80)


def _last_json(output, command):
  for line in reversed(output.splitlines()):
    if line.startswith("{"):
      return json.loads(line)
  raise AssertionError(f"endpoint emitted no JSON\ncommand={command}\n{output}")


def _wait_for_file(path, description, timeout=20.0):
  deadline = time.monotonic() + timeout
  while not os.path.exists(path) and time.monotonic() < deadline:
    time.sleep(0.05)
  if not os.path.exists(path):
    raise AssertionError(f"{description} did not create its readiness marker")


def _reap(process):
  if process is None:
    return "", ""
  if process.poll() is None:
    process.kill()
  return process.communicate()


def _preserve_artifacts(case_name, commands, outputs, control_dir):
  """Persist the evidence needed to reproduce a failed vendor control."""
  os.makedirs(ARTIFACT_ROOT, exist_ok=True)
  artifact_dir = tempfile.mkdtemp(prefix=f"{case_name}_", dir=ARTIFACT_ROOT)
  with open(os.path.join(artifact_dir, "commands.json"), "w", encoding="utf-8") as file:
    json.dump(commands, file, indent=2)
    file.write("\n")
  for name, content in outputs.items():
    with open(os.path.join(artifact_dir, f"{name}.txt"), "w", encoding="utf-8") as file:
      file.write(content or "")
  if control_dir and os.path.isdir(control_dir):
    shutil.copytree(control_dir, os.path.join(artifact_dir, "control"))
  return artifact_dir


def _finish_control_dir(case_name, commands, outputs, control_dir, failed):
  keep_artifacts = failed or os.environ.get("RTI_DOCTOR_KEEP_ARTIFACTS")
  artifact_dir = None
  if keep_artifacts:
    artifact_dir = _preserve_artifacts(case_name, commands, outputs, control_dir)
  shutil.rmtree(control_dir, ignore_errors=True)
  return artifact_dir


@unittest.skipUnless(
    __import__("importlib").util.find_spec("cyclonedds"),
    "Cyclone DDS Python package not available")
class TestConnextCycloneFaultControls(unittest.TestCase):
  """Exercise Doctor against healthy and intentionally incompatible peers."""

  def _endpoint_command(self, script, domain, topic_prefix, role, mode, scenario,
                        duration, ready_file):
    command = [
        sys.executable, script, "--domain", str(domain),
        "--topic-prefix", topic_prefix, "--role", role, "--mode", mode,
        "--scenarios", scenario, "--duration", str(duration),
        "--ready-file", ready_file,
    ]
    if script == CONNEXT:
      # The established vendor matrix uses TypeObject v1 for this pair.
      command.append("--type-object-v1-only")
    return command

  def _run_doctor(self, domain, topic):
    return doctor_e2e.run(
        domain, topic, settle=1, type_wait=3, no_probe=True, timeout=20)

  def _run_case(self, writer_script, reader_script, mode, scenario):
    domain = _domain()
    prefix = f"DoctorP0_{uuid.uuid4().hex}"
    topic = f"{prefix}_{scenario}"
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_cyclone_ready_", dir=OUTPUT_ROOT)
    reader_ready_file = os.path.join(control_dir, "reader.ready")
    writer_ready_file = os.path.join(control_dir, "writer.ready")
    reader_command = self._endpoint_command(
      reader_script, domain, prefix, "reader", mode, scenario, 12, reader_ready_file)
    writer_command = self._endpoint_command(
      writer_script, domain, prefix, "writer", mode, scenario, 10, writer_ready_file)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    writer = None
    doctor = None
    report = None
    writer_stdout = writer_stderr = reader_stdout = reader_stderr = ""
    try:
      _wait_for_file(reader_ready_file, "reader")
      writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      _wait_for_file(writer_ready_file, "writer")
      doctor, report = self._run_doctor(domain, topic)
      writer_stdout, writer_stderr = writer.communicate(timeout=15)
      reader_stdout, reader_stderr = reader.communicate(timeout=15)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer_stderr}\n{writer_stdout}")
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      writer_stdout, writer_stderr = _reap(writer)
      reader_stdout, reader_stderr = _reap(reader)
      doctor_stdout = doctor.stdout if doctor is not None else ""
      doctor_stderr = doctor.stderr if doctor is not None else ""
      _finish_control_dir(
          "cyclone", {"reader": reader_command, "writer": writer_command},
          {"reader_stdout": reader_stdout, "reader_stderr": reader_stderr,
           "writer_stdout": writer_stdout, "writer_stderr": writer_stderr,
           "doctor_stdout": doctor_stdout, "doctor_stderr": doctor_stderr},
          control_dir, failed=True)
      raise
    _finish_control_dir(
        "cyclone", {"reader": reader_command, "writer": writer_command},
        {"reader_stdout": reader_stdout, "reader_stderr": reader_stderr,
         "writer_stdout": writer_stdout, "writer_stderr": writer_stderr,
         "doctor_stdout": doctor.stdout, "doctor_stderr": doctor.stderr},
        control_dir, failed=False)
    return doctor, report, _last_json(writer_stdout, writer_command), _last_json(
        reader_stdout, reader_command)

  def _assert_healthy(self, writer_script, reader_script, scenario=RELIABILITY_SCENARIO):
    doctor, report, writer, reader = self._run_case(
        writer_script, reader_script, "compatible", scenario)
    self.assertEqual(doctor.returncode, 0, doctor.stderr)
    self.assertGreater(writer["results"][scenario]["matched"], 0, writer)
    self.assertGreater(reader["results"][scenario]["matched"], 0, reader)
    self.assertGreater(reader["results"][scenario]["samples"], 0, reader)
    findings = report["findings"]
    active_errors = [item["id"] for item in findings
             if not item["suppressed_by"] and item["severity"] == "ERROR"]
    self.assertEqual(active_errors, [], report)
    self.assertNotIn("qos.rxo_mismatch", [item["id"] for item in findings], report)

  def _assert_rxo_fault(self, writer_script, reader_script, scenario):
    doctor, report, writer, reader = self._run_case(
        writer_script, reader_script, "mismatch", scenario)
    self.assertEqual(doctor.returncode, 1, doctor.stderr)
    self.assertGreater(writer["results"][scenario]["samples"], 0, writer)
    self.assertEqual(writer["results"][scenario]["matched"], 0, writer)
    self.assertEqual(reader["results"][scenario]["matched"], 0, reader)
    self.assertEqual(reader["results"][scenario]["samples"], 0, reader)
    findings = [item for item in report["findings"] if not item["suppressed_by"]]
    mismatch = [item for item in findings if item["id"] == "qos.rxo_mismatch"]
    self.assertEqual(len(mismatch), 1, report)
    self.assertEqual(mismatch[0]["severity"], "ERROR", mismatch[0])
    self.assertIn(scenario.upper(), mismatch[0]["title"], mismatch[0])

  def test_connext_writer_to_cyclone_reader_healthy(self):
    self._assert_healthy(CONNEXT, CYCLONE)

  def test_cyclone_writer_to_connext_reader_healthy(self):
    self._assert_healthy(CYCLONE, CONNEXT)

  def test_connext_writer_to_cyclone_reader_reliability_fault(self):
    self._assert_rxo_fault(CONNEXT, CYCLONE, RELIABILITY_SCENARIO)

  def test_cyclone_writer_to_connext_reader_reliability_fault(self):
    self._assert_rxo_fault(CYCLONE, CONNEXT, RELIABILITY_SCENARIO)

  def test_connext_writer_to_cyclone_reader_durability_fault(self):
    self._assert_rxo_fault(CONNEXT, CYCLONE, DURABILITY_SCENARIO)


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

  def _connext_command(self, domain, topic, role, reliability, durability,
                       deadline_seconds, ownership, representation, duration,
                       control_dir, start_file, endpoint_ready_file):
    return [
        sys.executable, CONNEXT_EXTENSIBILITY, "--domain", str(domain),
        "--topic", topic, "--role", role, "--extensibility", "final",
        "--schema", "fastdds", "--reliability", reliability,
        "--durability", durability,
        "--deadline-seconds", str(deadline_seconds),
        "--ownership", ownership,
        "--representation", representation,
        "--duration", str(duration), "--wait-for-file", start_file,
        "--wait-timeout", "45", "--endpoint-ready-file", endpoint_ready_file,
    ]

  def _fastdds_command(self, domain, topic, role, reliability, durability,
                       deadline_seconds, ownership, representation, duration,
                       control_dir, start_file, endpoint_ready_file):
    command = [
        "docker", "run", "--rm", "--network", "host", "--entrypoint",
        "/doctor-extensibility-build/doctor_fastdds_final",
        "--mount", f"type=bind,src={control_dir},dst=/control",
        "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
        "--domain", str(domain), "--topic", topic, "--role", role,
        "--extensibility", "final", "--reliability", reliability,
        "--durability", durability,
        "--deadline-seconds", str(deadline_seconds),
        "--ownership", ownership,
        "--representation", representation,
        "--duration", str(duration), "--wait-for-file",
        f"/control/{os.path.basename(start_file)}", "--wait-timeout", "45",
        "--endpoint-ready-file", f"/control/{os.path.basename(endpoint_ready_file)}",
    ]
    return command

  def _doctor_command(self, domain, topic, ready_file, connext_log):
    return doctor_e2e.command(
        domain, topic, settle=4, type_wait=3, no_probe=True,
        ready_file=ready_file, connext_log=connext_log,
        connext_verbosity="silent", ready_after_participants=2,
        ready_timeout=40)

  def _doctor_result(self, completed):
    return doctor_e2e.parse_report(completed)

  def _run_case(self, writer_vendor, mode, scenario="reliability"):
    domain = _domain()
    topic = f"DoctorFastDdsP0_{uuid.uuid4().hex}"
    writer_reliability = (
      "best-effort" if scenario == "reliability" and mode == "mismatch"
      else "reliable")
    writer_durability = "volatile"
    reader_durability = "transient-local" if scenario == "durability" and mode == "mismatch" else "volatile"
    writer_deadline_seconds = 3 if scenario == "deadline" and mode == "mismatch" else 1
    reader_deadline_seconds = 1 if scenario == "deadline" and mode == "mismatch" else 3
    writer_ownership = "shared"
    reader_ownership = "exclusive" if scenario == "ownership" and mode == "mismatch" else "shared"
    writer_representation = "xcdr1"
    reader_representation = "xcdr2" if scenario == "data_representation" and mode == "mismatch" else "xcdr1"
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_ready_", dir=OUTPUT_ROOT)
    ready_file = os.path.join(control_dir, "doctor.ready")
    connext_log = os.path.join(control_dir, "doctor_connext.log")
    reader_start_file = os.path.join(control_dir, "reader.start")
    reader_ready_file = os.path.join(control_dir, "reader.ready")
    writer_start_file = os.path.join(control_dir, "writer.start")
    writer_ready_file = os.path.join(control_dir, "writer.ready")
    if writer_vendor == "fastdds":
      writer_command = self._fastdds_command(
          domain, topic, "writer", writer_reliability, writer_durability,
          writer_deadline_seconds, writer_ownership, writer_representation, 10,
          control_dir,
          writer_start_file, writer_ready_file)
      reader_command = self._connext_command(
          domain, topic, "reader", "reliable", reader_durability,
          reader_deadline_seconds, reader_ownership, reader_representation, 12,
          control_dir,
          reader_start_file, reader_ready_file)
    else:
      writer_command = self._connext_command(
          domain, topic, "writer", writer_reliability, writer_durability,
          writer_deadline_seconds, writer_ownership, writer_representation, 10,
          control_dir,
          writer_start_file, writer_ready_file)
      reader_command = self._fastdds_command(
          domain, topic, "reader", "reliable", reader_durability,
          reader_deadline_seconds, reader_ownership, reader_representation, 12,
          control_dir,
          reader_start_file, reader_ready_file)
    doctor_command, environment = self._doctor_command(
      domain, topic, ready_file, connext_log)
    reader = None
    writer = None
    doctor = None
    writer_stdout = writer_stderr = reader_stdout = reader_stderr = ""
    doctor_stdout = doctor_stderr = ""
    try:
      reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      doctor = subprocess.Popen(doctor_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=environment)
      _wait_for_file(ready_file, "Doctor", timeout=30.0)
      with open(reader_start_file, "w", encoding="utf-8"):
        pass
      _wait_for_file(reader_ready_file, "reader")
      with open(writer_start_file, "w", encoding="utf-8"):
        pass
      _wait_for_file(writer_ready_file, "writer")
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
      doctor_stdout, doctor_stderr = _reap(doctor)
      writer_stdout, writer_stderr = _reap(writer)
      reader_stdout, reader_stderr = _reap(reader)
      _finish_control_dir(
          "fastdds", {"doctor": doctor_command, "reader": reader_command,
                      "writer": writer_command},
          {"doctor_stdout": doctor_stdout, "doctor_stderr": doctor_stderr,
           "reader_stdout": reader_stdout, "reader_stderr": reader_stderr,
           "writer_stdout": writer_stdout, "writer_stderr": writer_stderr},
          control_dir, failed=True)
      raise
    _finish_control_dir(
        "fastdds", {"doctor": doctor_command, "reader": reader_command,
                    "writer": writer_command},
        {"doctor_stdout": doctor_stdout, "doctor_stderr": doctor_stderr,
         "reader_stdout": reader_stdout, "reader_stderr": reader_stderr,
         "writer_stdout": writer_stdout, "writer_stderr": writer_stderr},
        control_dir, failed=False)
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

  def _assert_rxo_fault(self, writer_vendor, scenario):
    doctor, report, writer, reader = self._run_case(
        writer_vendor, "mismatch", scenario)
    self.assertEqual(doctor.returncode, 1, f"{doctor.stderr}\n{report}")
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertEqual(writer["results"]["matched"], 0, writer)
    self.assertEqual(reader["results"]["matched"], 0, reader)
    self.assertEqual(reader["results"]["samples"], 0, reader)
    findings = [item for item in report["findings"] if not item["suppressed_by"]]
    mismatch = [item for item in findings if item["id"] == "qos.rxo_mismatch"]
    self.assertEqual(len(mismatch), 1, report)
    self.assertEqual(mismatch[0]["severity"], "ERROR", mismatch[0])
    self.assertIn(scenario.upper(), mismatch[0]["title"], mismatch[0])

  def _assert_representation_blind_spot(self, writer_vendor):
    doctor, report, writer, reader = self._run_case(
        writer_vendor, "mismatch", "data_representation")
    self.assertEqual(doctor.returncode, 0, f"{doctor.stderr}\n{report}")
    self.assertGreater(writer["results"]["samples"], 0, writer)
    self.assertEqual(writer["results"]["matched"], 0, writer)
    self.assertEqual(reader["results"]["matched"], 0, reader)
    self.assertEqual(reader["results"]["samples"], 0, reader)
    findings = [item for item in report["findings"] if not item["suppressed_by"]]
    self.assertIn("qos.compatible", [item["id"] for item in findings], report)
    self.assertIn("repr.not_advertised", [item["id"] for item in findings], report)

  def test_connext_writer_to_fastdds_reader_healthy(self):
    self._assert_healthy("connext")

  def test_fastdds_writer_to_connext_reader_healthy(self):
    self._assert_healthy("fastdds")

  def test_connext_writer_to_fastdds_reader_reliability_fault(self):
    self._assert_rxo_fault("connext", "reliability")

  def test_fastdds_writer_to_connext_reader_reliability_fault(self):
    self._assert_rxo_fault("fastdds", "reliability")

  def test_connext_writer_to_fastdds_reader_durability_fault(self):
    self._assert_rxo_fault("connext", "durability")

  def test_fastdds_writer_to_connext_reader_durability_fault(self):
    self._assert_rxo_fault("fastdds", "durability")

  def test_connext_writer_to_fastdds_reader_deadline_fault(self):
    self._assert_rxo_fault("connext", "deadline")

  def test_fastdds_writer_to_connext_reader_deadline_fault(self):
    self._assert_rxo_fault("fastdds", "deadline")

  def test_connext_writer_to_fastdds_reader_ownership_fault(self):
    self._assert_rxo_fault("connext", "ownership")

  def test_fastdds_writer_to_connext_reader_ownership_fault(self):
    self._assert_rxo_fault("fastdds", "ownership")

  def test_connext_writer_to_fastdds_reader_data_representation_fault(self):
    self._assert_representation_blind_spot("connext")

  def test_fastdds_writer_to_connext_reader_data_representation_fault(self):
    self._assert_rxo_fault("fastdds", "data_representation")


if __name__ == "__main__":
  unittest.main()