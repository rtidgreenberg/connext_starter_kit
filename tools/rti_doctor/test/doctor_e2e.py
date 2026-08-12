"""Shared helpers for end-to-end tests that invoke the Doctor CLI.

Doctor emits one report format, the text report, so these tests read that. They
used to run `--format json` and `json.loads` its stdout; that flag is gone, and
with it the second output schema that existed only for this harness. What the
tests actually assert on - finding ids, severities, titles, and the packet
appendix - is all on the face of the text report, so `parse_report` lifts those
back out rather than the tool maintaining a machine format nobody else read.
"""

import os
import re
import subprocess
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)

#: The banner that opens a targeted report. Native Connext diagnostics can be
#: written to the same stdout before it, so the report is located rather than
#: assumed to start at byte zero.
_REPORT_BANNER = "RTI DOCTOR INTEROP REPORT"
_FINDING = re.compile(r"^\[(?P<severity>[A-Z]+)\] rung (?P<rung>\d+)\s+(?P<id>\S+)\s*$")
_CONTINUATION = re.compile(r"^ {15,}(\S.*)$")
#: Field labels `report._render_findings` writes under each finding header.
_FINDING_FIELDS = {
    "Observed": "observed",
    "Root cause": "root_cause",
    "Remedy": "remedy",
    "Likely explained by": "explained_by",
    "Reference": "refs",
}
_FIELD_LINE = re.compile(
    r"^ {2}(" + "|".join(re.escape(label) for label in _FINDING_FIELDS) + r")\s+(\S.*)$")

#: Appendix C labels, longest first so "Capture filter" is not read as
#: "Capture". `int`/`list` say how to read the value back off the line.
_WIRE_FIELDS = (
    # Before "Capture filter" and "Capture" for the same reason they are
    # ordered against each other: a shorter label is a prefix of a longer one.
    ("  Fast DDS versions advertised", "fastdds_product_versions", list),
    ("Capture interface", "capture_interface", str),
    ("Reassembled bytes in matching frames", "reassembled_bytes", int),
    ("Serialized bytes in matching frames", "payload_bytes", int),
    ("Encapsulation IDs in matching frames", "encapsulation_ids", list),
    ("Observed DDS data representation", "representation", str),
    ("DATA_FRAG in matching frames", "data_fragments", int),
    ("Writer IDs in matching frames", "writer_entity_ids", list),
    ("Writer GUID prefix filter", "target_writer_guid_prefix", str),
    ("DATA in matching frames", "data_packets", int),
    ("Frames matching filters", "packets", int),
    ("Writer entity filter", "target_writer_entity_id", str),
    ("Reader entity filter", "target_reader_entity_id", str),
    ("Capture filter", "capture_filter", str),
    ("Capture", "source", str),
    ("Result", "error", str),
)


def command(domain, topic, *, settle, type_wait, no_probe=False,
            probe_timeout=None, capture_interface=None, ready_file=None,
            ready_after_participants=None, ready_timeout=None,
            connext_log=None, connext_verbosity=None):
  """Build a headless Doctor command and its isolated Python environment."""
  environment = dict(os.environ)
  environment["PYTHONPATH"] = TOOL_DIR + os.pathsep + environment.get("PYTHONPATH", "")
  doctor_command = [
      sys.executable, "-m", "rti_doctor", "--domain", str(domain),
      "--topic", topic, "--no-domain-scan",
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
  """Extract Doctor's text report despite any native middleware preamble."""
  lines = completed.stdout.splitlines()
  for index, line in enumerate(lines):
    if line.strip() == _REPORT_BANNER:
      return _read_report(lines[index:])
  raise AssertionError(
      "Doctor did not emit a text report\n"
      f"command={completed.args}\n"
      f"stderr={completed.stderr}\n"
      f"stdout={completed.stdout}")


def _read_report(lines):
  report = {
      "text": "\n".join(lines),
      "domain_id": _header_int(lines, "Domain"),
      "scope": _header_value(lines, "Scope"),
      "verdict": _verdict(lines),
      "findings": _findings(lines),
  }
  wire = _wire_observation(lines)
  if wire is not None:
    report["wire_observation"] = wire
  return report


def _is_rule(line):
  return line.startswith("---") or line.startswith("===")


def _section(lines, title):
  """Body lines of one `report._section` block, or None when it is absent.

  A section is `rule / title / rule`, so its body runs from two lines past the
  title to the rule that opens whatever comes next.
  """
  for index, line in enumerate(lines):
    if index and line.startswith(title) and _is_rule(lines[index - 1]):
      start = index + 2
      end = start
      while end < len(lines) and not _is_rule(lines[end]):
        end += 1
      return lines[start:end]
  return None


def _header_value(lines, label):
  """Value of one `report._kv` line from the report header block."""
  for line in lines:
    if line.startswith(label + " "):
      return line[len(label):].strip()
  return None


def _header_int(lines, label):
  value = _header_value(lines, label)
  return None if value is None else int(value)


def _verdict(lines):
  body = _section(lines, "VERDICT")
  return body[0].strip() if body else None


def _findings(lines):
  """Every finding in the FINDINGS section, in the order it was rendered."""
  body = _section(lines, "FINDINGS")
  if body is None:
    return []
  found = []
  field = None
  for line in body:
    header = _FINDING.match(line)
    if header:
      found.append({"id": header.group("id"),
                    "severity": header.group("severity"),
                    "rung": int(header.group("rung")),
                    "title": "", "observed": "", "root_cause": "",
                    "remedy": "", "explained_by": "", "refs": []})
      field = "title"
      continue
    if not found:
      continue
    labelled = _FIELD_LINE.match(line)
    if labelled:
      field = _FINDING_FIELDS[labelled.group(1)]
      _append(found[-1], field, labelled.group(2))
      continue
    continuation = _CONTINUATION.match(line)
    if continuation and field is not None:
      _append(found[-1], field, continuation.group(1))
  return found


def _append(finding, field, text):
  """Join a wrapped paragraph back together, or collect a repeated field."""
  if field == "refs":
    finding["refs"].append(text)
    return
  finding[field] = f"{finding[field]} {text}".strip()


def _wire_observation(lines):
  """Appendix C read back into the shape `wire.summarize` produced."""
  body = _section(lines, "APPENDIX C - DIRECT RTPS PACKET OBSERVATION")
  if body is None:
    return None
  evidence = {}
  for line in body:
    for label, key, kind in _WIRE_FIELDS:
      if not line.startswith(label + " "):
        continue
      value = line[len(label):].strip()
      if kind is int:
        evidence[key] = int(value)
      elif kind is list:
        evidence[key] = [] if value == "none observed" else [
            item.strip() for item in value.split(",")]
      elif key == "error":
        # "Result" is only rendered when the capture failed, and it renders as
        # "unavailable: <reason>". Tests assert on the reason, not the prefix.
        evidence[key] = value.split("unavailable:", 1)[-1].strip()
      else:
        evidence[key] = value
      break
  return evidence


def run(domain, topic, *, settle, type_wait, timeout, no_probe=False,
        probe_timeout=None, capture_interface=None, ready_file=None,
  ready_after_participants=None, ready_timeout=None,
  connext_log=None, connext_verbosity=None):
  """Run headless Doctor and return its completed process and parsed report."""
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
