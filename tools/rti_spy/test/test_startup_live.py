#!/usr/bin/env python3
"""Live startup smoke test for rti_spy.

Verifies that the app can create a DomainParticipant, attach builtin-topic
listeners, and enter the Textual app startup path on the local Connext
installation. The interactive UI loop is patched out so the test stays
automation-friendly.
"""

import glob
import io
import os
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


class TestRtiSpyStartupLive(unittest.TestCase):
    def setUp(self):
        _configure_rti_environment()
        rtispy.endpoints.clear()
        rtispy.participants.clear()

    def tearDown(self):
        rtispy.endpoints.clear()
        rtispy.participants.clear()

    def test_main_starts_with_real_connext_participant(self):
        domain_id = random.randint(231, 280)
        probe = _make_participant_or_skip(self, domain_id, "rti_spy_env_probe")
        probe.close()

        original_argv = sys.argv[:]

        def fake_run(app_self, *args, **kwargs):
            app_self.participant.close()
            return None

        try:
            sys.argv = ["rtispy.py", "--domain", str(domain_id), "--interval", "1"]
            with patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run) as run_mock:
                rtispy.main()
            run_mock.assert_called_once()
        finally:
            sys.argv = original_argv

    def test_launcher_reaches_running_state_without_domainparticipant_failure(self):
        domain_id = random.randint(281, 330)
        probe = _make_participant_or_skip(self, domain_id, "rti_spy_launcher_probe")
        probe.close()

        env = os.environ.copy()
        env["TERM"] = "dumb"
        root_dir = os.path.dirname(os.path.dirname(ROOT))

        result = subprocess.run(
            [
                "bash",
                "-lc",
                f"cd {root_dir} && timeout 6s ./tools/rti_spy/run_rtispy.sh --domain {domain_id}",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        combined_output = f"{result.stdout}\n{result.stderr}"
        self.assertIn("Starting RTI Spy...", combined_output)
        self.assertNotIn("Failed to create DomainParticipant", combined_output)
        self.assertNotIn("Traceback", combined_output)
        self.assertIn(result.returncode, (0, 124), combined_output)

    def test_main_prompts_for_domain_before_gui_when_missing(self):
        created_domains = []
        original_argv = sys.argv[:]

        class FakeParticipant:
            def close(self):
                return None

        def fake_create_participant(domain_id, name="RTI SPY"):
            created_domains.append(domain_id)
            return FakeParticipant()

        def fake_run(app_self, *args, **kwargs):
            app_self.participant.close()
            return None

        try:
            sys.argv = ["rtispy.py", "--interval", "1"]
            with patch("builtins.input", return_value="37") as input_mock, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            input_mock.assert_called_once_with("DDS domain ID [1]: ")
            self.assertEqual(created_domains, [37])
        finally:
            sys.argv = original_argv

    def test_main_uses_domain_one_without_prompt_when_noninteractive(self):
        created_domains = []
        original_argv = sys.argv[:]

        class FakeParticipant:
            def close(self):
                return None

        def fake_create_participant(domain_id, name="RTI SPY"):
            created_domains.append(domain_id)
            return FakeParticipant()

        def fake_run(app_self, *args, **kwargs):
            app_self.participant.close()
            return None

        try:
            sys.argv = ["rtispy.py", "--interval", "1"]
            with patch("builtins.input") as input_mock, \
                 patch("sys.stdin.isatty", return_value=False), \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            input_mock.assert_not_called()
            self.assertEqual(created_domains, [1])
        finally:
            sys.argv = original_argv


if __name__ == "__main__":
    unittest.main()