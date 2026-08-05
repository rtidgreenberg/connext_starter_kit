"""Shared helpers for end-to-end tests that invoke the Doctor CLI."""

import json
import os
import re
import subprocess
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
_REPORT_START = re.compile(r'\{(?=\s*"domain_id")')


def command(domain, topic, *, settle, type_wait, no_probe=False,
            probe_timeout=None, capture_interface=None, ready_file=None,
            ready_after_participants=None, ready_timeout=None,
            connext_log=None, connext_verbosity=None):
  """Build a headless Doctor command and its isolated Python environment."""
  environment = dict(os.environ)
  environment["PYTHONPATH"] = TOOL_DIR + os.pathsep + environment.get("PYTHONPATH", "")
  doctor_command = [
      sys.executable, "-m", "rti_doctor", "--domain", str(domain),
      "--topic", topic, "--format", "json", "--no-domain-scan",
      "--settle", str(settle), "--type-wait", str(type_wait),
  ]
  if no_probe:
    doctor_command.append("--no-probe")
  if probe_timeout is not None:
    doctor_command.extend(("--probe-timeout", str(probe_timeout)))
  if capture_interface is not None:
    doctor_command.extend(("--capture-interface", capture_interface))
  if ready_file is not None:
    doctor_command.extend(("--ready-file", ready_file))
  if ready_after_participants is not None:
    doctor_command.extend(("--ready-after-participants",
                           str(ready_after_participants)))
  if ready_timeout is not None:
    doctor_command.extend(("--ready-timeout", str(ready_timeout)))
  if connext_log is not None:
    doctor_command.extend(("--connext-log", connext_log))
  if connext_verbosity is not None:
    doctor_command.extend(("--connext-verbosity", connext_verbosity))
  return doctor_command, environment


def parse_report(completed):
  """Extract Doctor's JSON report despite any native middleware preamble."""
  decoder = json.JSONDecoder()
  for candidate in _REPORT_START.finditer(completed.stdout):
    try:
      report, _ = decoder.raw_decode(completed.stdout[candidate.start():])
      return report
    except json.JSONDecodeError:
      continue
  raise AssertionError(
      "Doctor did not emit a JSON report\n"
      f"command={completed.args}\n"
      f"stderr={completed.stderr}\n"
      f"stdout={completed.stdout}")


def run(domain, topic, *, settle, type_wait, timeout, no_probe=False,
        probe_timeout=None, capture_interface=None, ready_file=None,
  ready_after_participants=None, ready_timeout=None,
  connext_log=None, connext_verbosity=None):
  """Run headless Doctor and return its completed process and decoded report."""
  doctor_command, environment = command(
      domain, topic, settle=settle, type_wait=type_wait, no_probe=no_probe,
      probe_timeout=probe_timeout, capture_interface=capture_interface,
      ready_file=ready_file,
      ready_after_participants=ready_after_participants,
      ready_timeout=ready_timeout, connext_log=connext_log,
      connext_verbosity=connext_verbosity)
  completed = subprocess.run(
      doctor_command, text=True, capture_output=True, env=environment,
      timeout=timeout, check=False)
  return completed, parse_report(completed)
