#!/usr/bin/env python3
"""Live discovery and subscription integration test for rti_spy."""

import glob
import os
import random
import select
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(ROOT))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import rti.connextdds as dds

import rtispy


def _configure_rti_environment() -> None:
    rtispy.configure_rti_environment()


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


class TestRtiSpyLiveE2EIntegration(unittest.TestCase):
    def setUp(self):
        _configure_rti_environment()
        rtispy.endpoints.clear()
        rtispy.participants.clear()

    def tearDown(self):
        rtispy.endpoints.clear()
        rtispy.participants.clear()

    def test_detects_writer_and_receives_dynamicdata_samples_with_log_output(self):
        token = random.randrange(1_000_000, 9_999_999)
        domain_id = random.randint(331, 380)
        topic_name = f"RtiSpyE2ETopic_{token}"
        type_name = f"RtiSpyE2EType_{token}"
        field_name = f"value_{token}"
        count_name = f"count_{token}"
        nested_member = f"nested_{token}"
        nested_field = f"detail_{token}"
        expected_value = random.uniform(10.0, 500.0)
        expected_count = random.randint(1, 10_000)
        log_path = os.path.join(REPO_ROOT, "test_output", f"rti_spy_e2e_{token}.log")

        viewer_participant = None
        subscriber = None
        topic = None
        reader = None
        publisher_process = None

        try:
            probe = _make_participant_or_skip(self, domain_id, f"rti_spy_e2e_env_probe_{token}")
            probe.close()

            if os.path.exists(log_path):
                os.remove(log_path)
            rtispy.configure_logging(log_path)

            publisher_process = self._start_subprocess_publisher(
                domain_id=domain_id,
                topic_name=topic_name,
                type_name=type_name,
                participant_name=f"rti_spy_e2e_writer_{token}",
                field_name=field_name,
                count_name=count_name,
                nested_member=nested_member,
                nested_field=nested_field,
                expected_value=expected_value,
                expected_count=expected_count,
            )

            viewer_participant = rtispy.create_participant(domain_id, name=f"rti_spy_e2e_viewer_{token}")
            endpoint = self._wait_for_discovered_writer(topic_name)
            self.assertEqual(endpoint.topic_name, topic_name)
            self.assertEqual(endpoint.type_name, type_name)
            self.assertIsNotNone(endpoint.type)

            subscriber, topic, reader = rtispy.create_topic_subscription(viewer_participant, endpoint)
            sample, info, participant_data = self._wait_for_sample(reader)

            self.assertAlmostEqual(float(sample[field_name]), expected_value)
            self.assertEqual(int(sample[count_name]), expected_count)
            self.assertAlmostEqual(float(sample[f"{nested_member}.{nested_field}"]), expected_value + 1.0)

            self.assertTrue(os.path.isfile(log_path), f"Missing log output: {log_path}")
            with open(log_path, encoding="utf-8") as handle:
                log_text = handle.read()

            self.assertIn("[PublicationListener] Discovered Writer", log_text)
            self.assertIn(topic_name, log_text)
            self.assertIn("[create_topic_subscription] Subscribed to topic", log_text)

            ip_list = participant_data.default_unicast_locators[0].address[-4:]
            address_str = '.'.join(str(byte) for byte in ip_list)
            domain = participant_data.domain_id
            self.assertIn(f"[sample_received] topic='{topic_name}'", log_text)
            self.assertIn(f"source='{address_str}", log_text)
            self.assertIn(f"domain={domain}", log_text)
        finally:
            _close_all(reader, topic, subscriber, viewer_participant)
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

    def _wait_for_discovered_writer(self, topic_name, timeout: float = 8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for endpoint in rtispy.endpoints.values():
                if endpoint.kind == "Writer" and endpoint.topic_name == topic_name and endpoint.type is not None:
                    return endpoint
            time.sleep(0.1)
        self.fail(f"Timed out discovering writer '{topic_name}'")

    def _wait_for_sample(self, reader, timeout: float = 8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data, info, participant_data = rtispy.take_discovered_sample(reader)
            if data is not None:
                return data, info, participant_data
            time.sleep(0.1)
        self.fail("Timed out receiving DynamicData sample")


if __name__ == "__main__":
    unittest.main()