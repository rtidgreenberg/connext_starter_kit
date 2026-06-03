#!/usr/bin/env python3
"""Live DDS end-to-end integration test for rti_view.

Creates a random DynamicData writer, discovers it through rti_view's builtin-topic
path, subscribes with matched QoS, pumps a selected field, and converts it into
plot-series data. The test is skipped when a local Connext participant cannot be
created, which usually means the license/environment is not configured.
"""

import glob
import os
import random
import select
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import rti.connextdds as dds

from rti_view.discovery import create_participant, refresh_endpoints, registry
from rti_view.fields import enumerate_fields
from rti_view.subscriber import FieldSampleBuffer, pump_reader_once, setup_matched_reader
from rti_view.views.plot_view import plot_series_from_points


def _configure_rti_environment() -> None:
    if os.environ.get("NDDSHOME"):
        ndds_home = os.environ["NDDSHOME"]
    else:
        installs = sorted(glob.glob(os.path.expanduser("~/rti_connext_dds-*")))
        ndds_home = installs[-1] if installs else ""
        if ndds_home:
            os.environ["NDDSHOME"] = ndds_home

    if not os.environ.get("RTI_LICENSE_FILE") and ndds_home:
        license_path = os.path.join(ndds_home, "rti_license.dat")
        if os.path.isfile(license_path):
            os.environ["RTI_LICENSE_FILE"] = license_path


def _make_participant_or_skip(test_case: unittest.TestCase, domain_id: int, name: str):
    try:
        qos = dds.DomainParticipantQos()
        qos.participant_name.name = name
        participant = dds.DomainParticipant(domain_id, qos=qos)
        participant.enable()
        return participant
    except Exception as exc:
        test_case.skipTest(f"Connext live participant unavailable: {exc}")


def _close_all(*entities) -> None:
    for entity in entities:
        close = getattr(entity, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


class TestRtiViewLiveE2EIntegration(unittest.TestCase):
    def setUp(self):
        _configure_rti_environment()
        registry.clear()

    def tearDown(self):
        registry.clear()

    def test_subprocess_dynamic_type_sample_subscribes_and_visualizes(self):
        token = random.randrange(1_000_000, 9_999_999)
        domain_id = random.randint(180, 230)
        topic_name = f"RtiViewE2ETopic_{token}"
        type_name = f"RtiViewE2EType_{token}"
        field_name = f"value_{token}"
        count_name = f"count_{token}"
        nested_member = f"nested_{token}"
        nested_field = f"detail_{token}"
        nested_path = f"{nested_member}.{nested_field}"
        expected_value = random.uniform(10.0, 500.0)
        expected_count = random.randint(1, 10_000)

        viewer_participant = None
        reader = None
        subscriber = None
        publisher_process = None
        try:
            _make_participant_or_skip(self, domain_id, f"rti_view_e2e_env_probe_{token}").close()
            publisher_process = self._start_subprocess_publisher(
                domain_id=domain_id,
                topic_name=topic_name,
                type_name=type_name,
                participant_name=f"rti_view_e2e_writer_{token}",
                field_name=field_name,
                count_name=count_name,
                nested_member=nested_member,
                nested_field=nested_field,
                expected_value=expected_value,
                expected_count=expected_count,
            )

            viewer_participant = create_participant(domain_id, name=f"rti_view_e2e_viewer_{token}")

            endpoint = self._wait_for_discovered_writer(viewer_participant, topic_name)
            self.assertEqual(endpoint.topic_name, topic_name)
            self.assertEqual(endpoint.type_name, type_name)
            self.assertIsNotNone(endpoint.dynamic_type)

            fields = enumerate_fields(endpoint.dynamic_type)
            selected_field = next((field for field in fields if field.path == field_name), None)
            selected_nested_field = next((field for field in fields if field.path == nested_path), None)
            self.assertIsNotNone(selected_field)
            self.assertIsNotNone(selected_nested_field)
            self.assertTrue(selected_field.plottable)
            self.assertTrue(selected_nested_field.plottable)

            setup = setup_matched_reader(viewer_participant, endpoint)
            self.assertTrue(setup.ok, setup.diagnostic)
            reader = setup.reader
            subscriber = setup.subscriber

            buffer = FieldSampleBuffer(max_messages=10, max_points=10)
            accepted = self._wait_for_field_sample(reader, field_name, buffer)
            self.assertGreaterEqual(accepted, 1)
            self.assertAlmostEqual(float(buffer.messages[-1].value), expected_value)
            self.assertAlmostEqual(buffer.points[-1].value, expected_value)

            nested_buffer = FieldSampleBuffer(max_messages=10, max_points=10)
            accepted = self._wait_for_field_sample(reader, nested_path, nested_buffer)
            self.assertGreaterEqual(accepted, 1)
            self.assertAlmostEqual(float(nested_buffer.messages[-1].value), expected_value + 1.0)

            x_values, y_values = plot_series_from_points(buffer.points)
            self.assertEqual(len(x_values), len(y_values))
            self.assertGreaterEqual(len(y_values), 1)
            self.assertAlmostEqual(y_values[-1], expected_value)
        finally:
            _close_all(reader, subscriber, viewer_participant)
            self._stop_process(publisher_process)

    def _start_subprocess_publisher(
            self,
            domain_id: int,
            topic_name: str,
            type_name: str,
            participant_name: str,
            field_name: str,
            count_name: str,
            nested_member: str,
            nested_field: str,
            expected_value: float,
            expected_count: int,
    ) -> subprocess.Popen:
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e_dynamic_publisher.py")
        process = subprocess.Popen(
            [
                sys.executable,
                script,
                "--domain", str(domain_id),
                "--topic", topic_name,
                "--type-name", type_name,
                "--participant-name", participant_name,
                "--field", field_name,
                "--count-field", count_name,
                "--nested-member", nested_member,
                "--nested-field", nested_field,
                "--value", str(expected_value),
                "--count", str(expected_count),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                self.fail(f"E2E publisher exited before READY with code {process.returncode}: {stderr}")
            if process.stdout:
                readable, _, _ = select.select([process.stdout], [], [], 0.05)
                if readable:
                    line = process.stdout.readline()
                    if line.strip() == "READY":
                        return process
            time.sleep(0.05)
        self._stop_process(process)
        self.fail("Timed out waiting for E2E publisher READY")

    def _stop_process(self, process) -> None:
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)
        finally:
            for stream in (process.stdout, process.stderr):
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

    def _wait_for_discovered_writer(self, viewer_participant, topic_name, timeout: float = 8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            refresh_endpoints(viewer_participant)
            endpoint, diagnostics = registry.select_writer_for_topic(topic_name)
            if endpoint and endpoint.type_available:
                return endpoint
            time.sleep(0.1)
        endpoint, diagnostics = registry.select_writer_for_topic(topic_name)
        self.fail(
            f"Timed out discovering writer '{topic_name}' with DynamicType; "
            f"endpoint={endpoint!r}, diagnostics={[diag.code for diag in diagnostics]}"
        )

    def _wait_for_field_sample(self, reader, field_name, buffer, timeout: float = 8.0):
        deadline = time.monotonic() + timeout
        accepted_total = 0
        while time.monotonic() < deadline:
            accepted_total += pump_reader_once(reader, field_name, buffer)
            if accepted_total > 0:
                return accepted_total
            time.sleep(0.1)
        self.fail(f"Timed out receiving field sample for '{field_name}'")


if __name__ == "__main__":
    unittest.main()
