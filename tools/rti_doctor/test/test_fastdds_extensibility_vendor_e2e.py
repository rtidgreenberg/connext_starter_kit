"""Cross-vendor FINAL/APPENDABLE data-flow matrix for Connext and Fast DDS."""

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
  """Measure every FINAL/APPENDABLE pair in both Connext/Fast DDS directions."""

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
                       duration, start_file=None, ready_file=None):
    command = [
        sys.executable, CONNEXT, "--domain", str(domain), "--topic", topic,
        "--role", role, "--extensibility", extensibility, "--schema", "fastdds",
        "--representation", representation,
        "--duration", str(duration),
    ]
    if start_file is not None:
      command.extend(("--wait-for-file", start_file, "--wait-timeout", "30"))
    if ready_file is not None:
      command.extend(("--endpoint-ready-file", ready_file))
    return command

  def _fastdds_command(self, domain, topic, role, extensibility, representation,
                       duration, control_dir=None, start_file=None, ready_file=None):
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
                      "--wait-timeout", "30"))
    if ready_file is not None:
      command.extend(("--endpoint-ready-file",
                      f"/control/{os.path.basename(ready_file)}"))
    return command

  def _wait_for_file(self, path, description, timeout=30.0):
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
                reader_representation="xcdr1"):
    domain = domains.for_suite("test_fastdds_extensibility_vendor_e2e")
    topic = f"DoctorFastDdsExtensibility_{uuid.uuid4().hex}"
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_repr_", dir=HERE)
    reader_start_file = os.path.join(control_dir, "reader.start")
    reader_ready_file = os.path.join(control_dir, "reader.ready")
    writer_start_file = os.path.join(control_dir, "writer.start")
    writer_ready_file = os.path.join(control_dir, "writer.ready")
    command_for = self._fastdds_command if writer_vendor == "fastdds" else self._connext_command
    writer_kwargs = ({"control_dir": control_dir, "start_file": writer_start_file,
                      "ready_file": writer_ready_file}
                     if writer_vendor == "fastdds" else
                     {"start_file": writer_start_file, "ready_file": writer_ready_file})
    writer_command = command_for(domain, topic, "writer", writer_extensibility,
                                 writer_representation, 8, **writer_kwargs)
    command_for = self._fastdds_command if reader_vendor == "fastdds" else self._connext_command
    reader_kwargs = ({"control_dir": control_dir, "start_file": reader_start_file,
                      "ready_file": reader_ready_file}
                     if reader_vendor == "fastdds" else
                     {"start_file": reader_start_file, "ready_file": reader_ready_file})
    reader_command = command_for(domain, topic, "reader", reader_extensibility,
                                 reader_representation, 10, **reader_kwargs)
    reader = subprocess.Popen(reader_command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    writer = None
    reader_stdout = reader_stderr = writer_stdout = writer_stderr = ""
    try:
      with open(reader_start_file, "w", encoding="utf-8"):
        pass
      self._wait_for_file(reader_ready_file, "reader")
      writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
      with open(writer_start_file, "w", encoding="utf-8"):
        pass
      self._wait_for_file(writer_ready_file, "writer")
      writer_stdout, writer_stderr = writer.communicate(timeout=20)
      self.assertEqual(writer.returncode, 0,
                       f"writer failed: {writer_stderr}\n{writer_stdout}")
      reader_stdout, reader_stderr = reader.communicate(timeout=20)
      self.assertEqual(reader.returncode, 0,
                       f"reader failed: {reader_stderr}\n{reader_stdout}")
    except Exception:
      if writer is not None and writer.poll() is None:
        writer.kill()
      if writer is not None:
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
        self._assert_data_flows(writer, reader)

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
            self.assertGreater(writer["results"]["samples"], 0, writer)
            self.assertEqual(writer["results"]["matched"], 0, writer)
            self.assertEqual(reader["results"]["matched"], 0, reader)
            self.assertEqual(reader["results"]["samples"], 0, reader)


if __name__ == "__main__":
  unittest.main()