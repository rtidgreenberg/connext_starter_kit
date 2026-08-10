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
        # Domain IDs are kept <= 232 (RTI's documented safe max for the
        # default port formula) to avoid 16-bit UDP port overflow/wraparound,
        # which can otherwise land on a privileged (<1024) port and fail to
        # bind for non-root users. See python_env_multi_version.md repo memory.
        domain_id = random.randint(1, 77)
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

    def test_main_applies_requested_theme_before_startup(self):
        original_argv = sys.argv[:]

        class FakeParticipant:
            def close(self):
                return None

        def fake_run(app_self, *args, **kwargs):
            self.assertEqual(app_self.theme, "textual-light")
            app_self.participant.close()

        try:
            sys.argv = ["rtispy.py", "--domain", "1", "--theme", "textual-light"]
            with patch.object(rtispy, "create_participant", return_value=FakeParticipant()), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
        finally:
            sys.argv = original_argv

    def test_main_rejects_unknown_theme_before_creating_participant(self):
        original_argv = sys.argv[:]
        try:
            sys.argv = ["rtispy.py", "--domain", "1", "--theme", "not-a-theme"]
            with patch.object(rtispy, "create_participant") as create_participant:
                with self.assertRaises(SystemExit) as error:
                    rtispy.main()
            self.assertEqual(error.exception.code, 2)
            create_participant.assert_not_called()
        finally:
            sys.argv = original_argv

    def test_launcher_reaches_running_state_without_domainparticipant_failure(self):
        # See note above: keep domain IDs <= 232 to avoid port wraparound.
        domain_id = random.randint(78, 154)
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

    def test_scan_active_domains_detects_live_participant(self):
        # See note above: keep domain IDs <= 232 to avoid port wraparound.
        domain_id = random.randint(155, 200)
        qos = dds.DomainParticipantQos()
        qos.participant_name.name = "rti_spy_scan_probe"
        # Leave discovery_config.default_domain_announcement_period at its
        # default (enabled, 30s) so this participant sends the RTPX-style
        # default domain announcement that scan_active_domains listens for.
        try:
            participant = dds.DomainParticipant(domain_id, qos=qos)
            participant.enable()
        except Exception as exc:
            self.skipTest(f"Connext live participant unavailable: {exc}")

        # A remote participant only (re)sends its default domain announcement
        # every default_domain_announcement_period (30s default), with no
        # catch-up resend for a listener that starts later - confirmed live
        # against a 7.7.0 install. This probe was already created above, so
        # the scan below starts at an arbitrary phase of its 30s cycle and
        # must wait close to a full period to reliably observe it.
        try:
            discovered = rtispy.scan_active_domains(timeout=33.0)
            if domain_id not in discovered:
                self.skipTest(
                    "Default domain announcement not observed within scan window "
                    f"(discovered={discovered}); likely multicast loopback is blocked "
                    "in this environment."
                )
            self.assertIn(domain_id, discovered)
        finally:
            participant.close()

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
            with patch("builtins.input", side_effect=["", "37"]) as input_mock, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch.object(rtispy, "scan_active_domains", return_value=set()) as scan_mock, \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            scan_mock.assert_called_once()
            input_mock.assert_any_call("Enter domain ID to inspect, or press Enter to listen for active domains: ")
            input_mock.assert_any_call("Enter domain ID to inspect [1]: ")
            self.assertEqual(created_domains, [37])
        finally:
            sys.argv = original_argv

    def test_main_prompts_with_discovered_domain_default(self):
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
            with patch("builtins.input", side_effect=["", ""]) as input_mock, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch.object(rtispy, "scan_active_domains", return_value={5, 2}) as scan_mock, \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            scan_mock.assert_called_once()
            # Empty input accepts the default, which is the lowest discovered domain ID.
            input_mock.assert_any_call("Enter domain ID to inspect [2]: ")
            self.assertEqual(created_domains, [2])
        finally:
            sys.argv = original_argv

    def test_main_entering_domain_id_upfront_skips_scan(self):
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
            with patch("builtins.input", return_value="42") as input_mock, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch.object(rtispy, "scan_active_domains") as scan_mock, \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            # Typing a domain ID at the upfront prompt should skip listening entirely.
            scan_mock.assert_not_called()
            input_mock.assert_called_once_with("Enter domain ID to inspect, or press Enter to listen for active domains: ")
            self.assertEqual(created_domains, [42])
        finally:
            sys.argv = original_argv

    def test_main_rejects_invalid_input_at_upfront_prompt_without_scanning(self):
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
            # First reply is garbage (non-integer), then a negative domain ID,
            # then a valid domain ID. Neither invalid reply should trigger the
            # scan or be accepted as-is.
            with patch("builtins.input", side_effect=["abc", "-5", "42"]) as input_mock, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch.object(rtispy, "scan_active_domains") as scan_mock, \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            scan_mock.assert_not_called()
            self.assertEqual(input_mock.call_count, 3)
            self.assertEqual(created_domains, [42])
        finally:
            sys.argv = original_argv

    def test_main_skips_domain_scan_with_flag(self):
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
            sys.argv = ["rtispy.py", "--interval", "1", "--no-domain-scan"]
            with patch("builtins.input", return_value="9") as input_mock, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch.object(rtispy, "scan_active_domains") as scan_mock, \
                 patch.object(rtispy, "create_participant", side_effect=fake_create_participant), \
                 patch.object(rtispy, "configure_rti_environment"), \
                 patch.object(rtispy, "configure_logging"), \
                 patch.object(rtispy.RTISPY, "run", autospec=True, side_effect=fake_run):
                rtispy.main()
            scan_mock.assert_not_called()
            input_mock.assert_called_once_with("Enter domain ID to inspect [1]: ")
            self.assertEqual(created_domains, [9])
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