"""Record Fast DDS dynamic data with RTI Recording Service and validate it.

This exercises the service path relevant to runtime-discovered types: Fast DDS
publishes a full TypeObject without endpoint-QoS overrides, Recording Service
selects the topic without a registered local type, and Converter Service emits
the persisted samples as CSV for field-value assertions.
"""

import csv
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from xml.sax.saxutils import escape


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
VENDORS = os.path.join(HERE, "vendors")
FASTDDS_IMAGE = os.environ.get("RTI_DOCTOR_FASTDDS_IMAGE",
                               "rti-doctor-fastdds-e2e:3.6.2")

sys.path.insert(0, TOOL_DIR)
sys.path.insert(0, HERE)
from rti_doctor import compat, paths  # noqa: E402
import domains  # noqa: E402


def _domain():
  return domains.for_suite("test_fastdds_recording_service_e2e")


def _recording_config(domain, topic, workspace):
  return f"""<?xml version="1.0" encoding="UTF-8"?>
<dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation="https://community.rti.com/schema/7.7.0/rti_recording_service.xsd">
  <recording_service name="fastdds_dynamic">
    <storage>
      <sqlite>
        <storage_format>XCDR_AUTO</storage_format>
        <fileset>
          <workspace_dir>{escape(workspace)}</workspace_dir>
          <execution_dir_expression>recording</execution_dir_expression>
          <filename_expression>data_%auto:0-9%.dat</filename_expression>
        </fileset>
      </sqlite>
    </storage>
    <domain_participant name="RecordingServiceParticipant">
      <domain_id>{domain}</domain_id>
    </domain_participant>
    <session name="RecordFastDds" default_participant_ref="RecordingServiceParticipant">
      <topic_group name="FastDdsTopic">
        <allow_topic_name_filter>{escape(topic)}</allow_topic_name_filter>
        <deny_topic_name_filter>rti/*</deny_topic_name_filter>
      </topic_group>
    </session>
  </recording_service>
</dds>
"""


def _converter_config(domain, topic, database_dir, workspace):
  return f"""<?xml version="1.0" encoding="UTF-8"?>
<dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation="https://community.rti.com/schema/7.7.0/rti_converter.xsd">
  <converter name="fastdds_csv">
    <input_storage>
      <sqlite>
        <storage_format>XCDR_AUTO</storage_format>
        <database_dir>{escape(database_dir)}</database_dir>
      </sqlite>
    </input_storage>
    <output_storage>
      <csv>
        <workspace_dir>{escape(workspace)}</workspace_dir>
        <merge_files>false</merge_files>
      </csv>
    </output_storage>
    <domain_participant name="ConverterParticipant">
      <domain_id>{domain}</domain_id>
    </domain_participant>
    <session name="ConvertFastDds" default_participant_ref="ConverterParticipant">
      <topic_group name="FastDdsTopic">
        <allow_topic_name_filter>{escape(topic)}</allow_topic_name_filter>
      </topic_group>
    </session>
  </converter>
</dds>
"""


def _terminate(process):
  if process.poll() is None:
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
  try:
    return process.wait(timeout=15)
  except subprocess.TimeoutExpired:
    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    return process.wait(timeout=5)


@unittest.skipUnless(shutil.which("docker"), "docker is not installed")
class TestFastDdsRecordingService(unittest.TestCase):
  """Prove Recording Service persists Fast DDS dynamic payload values."""

  @classmethod
  def setUpClass(cls):
    compat.configure_rti_environment()
    cls.nddshome = os.environ.get("NDDSHOME", "")
    cls.recorder = os.path.join(cls.nddshome, "bin", "rtirecordingservice")
    cls.converter = os.path.join(cls.nddshome, "bin", "rticonverter")
    if not os.path.isfile(cls.recorder):
      raise unittest.SkipTest(f"rtirecordingservice not found: {cls.recorder}")
    if not os.path.isfile(cls.converter):
      raise unittest.SkipTest(f"rticonverter not found: {cls.converter}")
    available = subprocess.run(
        ["docker", "image", "inspect", FASTDDS_IMAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if available.returncode:
      raise unittest.SkipTest(
          f"Fast DDS image '{FASTDDS_IMAGE}' is unavailable; build it with "
          "test/vendors/fastdds/build_image.sh")

  def test_records_fastdds_typeobject_payload_values(self):
    domain = _domain()
    topic = f"DoctorFastDdsRecording_{uuid.uuid4().hex}"
    output_root = paths.TEST_OUTPUT_ROOT
    os.makedirs(output_root, exist_ok=True)
    control_dir = tempfile.mkdtemp(prefix="rti_doctor_fastdds_recording_",
                                   dir=output_root)
    recording_workspace = os.path.join(control_dir, "recordings")
    recording_dir = os.path.join(recording_workspace, "recording")
    csv_workspace = os.path.join(control_dir, "csv")
    recording_config = os.path.join(control_dir, "recording.xml")
    converter_config = os.path.join(control_dir, "converter.xml")
    recorder_log = os.path.join(control_dir, "recording_service.log")
    with open(recording_config, "w", encoding="utf-8") as handle:
      handle.write(_recording_config(domain, topic, recording_workspace))
    with open(converter_config, "w", encoding="utf-8") as handle:
      handle.write(_converter_config(domain, topic, recording_dir, csv_workspace))

    environment = os.environ.copy()
    environment["NDDSHOME"] = self.nddshome
    recorder = writer = None
    succeeded = False
    try:
      with open(recorder_log, "w", encoding="utf-8") as log_handle:
        recorder = subprocess.Popen(
            [self.recorder, "-cfgName", "fastdds_dynamic", "-cfgFile",
             recording_config, "-verbosity", "WARN:WARN"],
            env=environment, stdout=log_handle, stderr=subprocess.STDOUT,
            start_new_session=True)
        time.sleep(5)
        self.assertIsNone(recorder.poll(), "Recording Service exited during startup")

        writer_command = [
            "docker", "run", "--rm", "--network", "host", "--entrypoint",
            "/doctor-extensibility-build/doctor_fastdds_final",
            "-e", "FASTDDS_BUILTIN_TRANSPORTS=UDPv4", FASTDDS_IMAGE,
            "--domain", str(domain), "--topic", topic, "--role", "writer",
            "--extensibility", "final", "--qos-defaults", "--duration", "20",
        ]
        writer = subprocess.Popen(writer_command, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        writer_stdout, writer_stderr = writer.communicate(timeout=35)
        self.assertEqual(writer.returncode, 0,
                         f"Fast DDS writer failed:\n{writer_stderr}\n{writer_stdout}")
        self.assertIn('"matched":', writer_stdout)
        self.assertNotIn('"matched":0', writer_stdout)

      time.sleep(3)
      _terminate(recorder)
      recorder = None

      self.assertTrue(os.path.isfile(os.path.join(recording_dir, "metadata.db")),
                      f"Recording Service created no metadata database in {recording_dir}")
      data_files = [name for name in os.listdir(recording_dir)
                    if name.endswith(".dat")]
      self.assertTrue(data_files, f"Recording Service created no data files in {recording_dir}")
      self.assertTrue(any(
          os.path.getsize(os.path.join(recording_dir, name)) > 0
          for name in data_files), "Recording Service data files are empty")

      converted = subprocess.run(
          [self.converter, "-cfgName", "fastdds_csv", "-cfgFile", converter_config,
           "-verbosity", "WARN:WARN"],
          env=environment, capture_output=True, text=True, timeout=45)
      self.assertEqual(converted.returncode, 0,
                       f"Converter Service failed:\n{converted.stderr}\n{converted.stdout}")
      csv_files = []
      for root, _, files in os.walk(csv_workspace):
        csv_files.extend(os.path.join(root, name) for name in files
                         if name.endswith(".csv"))
      self.assertTrue(csv_files, "Converter Service created no CSV output")

      rows = []
      for csv_file in csv_files:
        with open(csv_file, newline="", encoding="utf-8") as handle:
          reader = csv.reader(handle)
          topic_metadata = next(reader, [])
          self.assertIn(topic, ",".join(topic_metadata))
          header = next(reader, [])
          self.assertIn("index", header)
          self.assertIn("message", header)
          rows.extend(dict(zip(header, row)) for row in reader)
      self.assertTrue(rows, "Converted Fast DDS recording has no data rows")
      self.assertTrue(any(
          row.get("message") == "DoctorExtensibility" and int(row["index"]) > 0
          for row in rows),
          f"Converted rows did not contain the expected payload: {rows[:5]}")
      succeeded = True
    finally:
      if writer is not None and writer.poll() is None:
        writer.kill()
        writer.communicate()
      if recorder is not None:
        _terminate(recorder)
      if succeeded and not os.environ.get("RTI_DOCTOR_KEEP_ARTIFACTS"):
        shutil.rmtree(control_dir, ignore_errors=True)
      elif not succeeded:
        print(f"Recording Service artifacts retained at {control_dir}")


if __name__ == "__main__":
  unittest.main()