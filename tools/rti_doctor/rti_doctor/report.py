"""Report rendering: the shareable text file, JSON, and Textual-friendly text.

The text file is the primary artifact. Its rules:

  * Only observed values. A counter unavailable on this Connext version renders
    as compat.na_text(), never as 0 and never omitted.
  * Fixed section order, so two reports diff cleanly against each other.
  * An environment header, so a recipient needs no follow-up questions.
  * A complete raw counter appendix, so a reader who doubts a finding can check.
  * Suppressed findings listed by id, so causal ordering hides noise without
    making anything vanish.
"""

import json
import time

from . import compat, findings as f, probe as probe_mod, records, typewalk

WIDTH = 100
RULE = "=" * WIDTH
THIN = "-" * WIDTH


def _section(title):
  return [THIN, title, THIN]


def _kv(label, value, pad=16):
  """Header line. `pad` must exceed the longest label used, or values collide."""
  return f"{label.ljust(pad)}{value}"


def _wrap(text, indent=15, width=WIDTH):
  """Wrap a paragraph to the report width with a hanging indent."""
  if not text:
    return []
  words = str(text).split()
  lines = []
  current = ""
  limit = width - indent
  for word in words:
    candidate = f"{current} {word}".strip()
    if len(candidate) > limit and current:
      lines.append(current)
      current = word
    else:
      current = candidate
  if current:
    lines.append(current)
  pad = " " * indent
  return [pad + line for line in lines]


def _labelled(label, text, indent=15):
  """"  Label   wrapped text..." with the label on the first line."""
  block = _wrap(text, indent=indent)
  if not block:
    return []
  first = block[0]
  prefix = f"  {label}".ljust(indent)
  return [prefix + first[indent:]] + block[1:]


def default_filename(domain_id, scope, timestamp=None):
  """rti_doctor_<domain>_<scope>_<timestamp>.txt with a filesystem-safe scope."""
  stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp or time.time()))
  safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(scope))
  return f"rti_doctor_{domain_id}_{safe}_{stamp}.txt"


class ReportData:
  """Everything one report needs. Built by the caller, consumed by renderers."""

  def __init__(self, domain_id, scope, all_findings, probe_result=None,
               endpoint=None, participant=None, type_lookup_settings=None,
               environment=None, generated_at=None, blind_spot_findings=None,
               wire_evidence=None):
    self.domain_id = domain_id
    self.scope = scope
    self.findings = f.rank(f.suppress(list(all_findings)))
    self.probe_result = probe_result
    self.endpoint = endpoint
    self.participant = participant
    self.type_lookup_settings = type_lookup_settings or {}
    self.environment = environment or compat.environment_info()
    self.generated_at = generated_at or time.time()
    self.blind_spot_findings = blind_spot_findings or []
    self.wire_evidence = wire_evidence

  @property
  def outcome(self):
    """ProbeOutcome derived from the probe result, for the verdict line."""
    outcome = f.ProbeOutcome()
    result = self.probe_result
    if result is None:
      outcome.skip_reason = "no probe requested"
      return outcome
    outcome.attempted = result.attempted
    outcome.matched = result.matched
    outcome.samples_received = result.samples_taken
    if not result.created:
      outcome.skip_reason = result.create_error or "reader could not be created"
      outcome.attempted = False
      return outcome
    if result.walk is not None:
      outcome.payload_verdict = result.walk.verdict
      outcome.members_total = result.walk.total
      outcome.members_unreadable = len(result.walk.failed)
      outcome.unreadable_paths = result.walk.failed_paths
    return outcome

  @property
  def verdict(self):
    return f.verdict_line(self.findings, self.outcome)


# --- Text renderer -----------------------------------------------------------

def render_text(data):
  """The shareable report file."""
  lines = [RULE, "RTI DOCTOR INTEROP REPORT", RULE]
  env = data.environment
  stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(data.generated_at))
  lines += [
      _kv("Generated", stamp),
      _kv("Tool", "rti_doctor (tools/rti_doctor)"),
      _kv("Command", env.get("argv", "unknown")),
      _kv("Host", f"{env.get('host')}  {env.get('os')}  {env.get('machine')}"),
      _kv("Connext", f"{env.get('connext')}  (NDDSHOME={env.get('nddshome')})"),
      _kv("Python", env.get("python")),
      _kv("Domain", str(data.domain_id)),
      _kv("Scope", data.scope),
      "",
  ]

  lines += _section("VERDICT")
  lines += [data.verdict, ""]

  lines += _render_peer(data)
  lines += _render_findings(data)
  lines += _render_type_appendix(data)
  lines += _render_counter_appendix(data)
  lines += _render_wire_appendix(data)
  lines += _render_config_appendix(data)
  return "\n".join(lines) + "\n"


def _render_peer(data):
  endpoint = data.endpoint
  participant = data.participant
  if endpoint is None and participant is None:
    return []

  lines = _section("PEER")
  if participant is not None:
    lines.append(_kv("Participant", f"{participant.name or '(unnamed)'}  @ "
                                    f"{participant.ip or 'unknown'}"))
    lines.append(_kv("Vendor", f"{participant.vendor_name} ({participant.vendor_hex})"))
    lines.append(_kv("RTPS", participant.protocol_text))
    if participant.domain_id is not None:
      lines.append(_kv("Peer domain", str(participant.domain_id)))
  if endpoint is not None:
    lines.append(_kv("Topic", endpoint.topic_name or "(none)"))
    lines.append(_kv("Type name", endpoint.type_name or "(none)"))
    state = endpoint.type_state
    delay = endpoint.type_resolution_delay
    if state == records.TYPE_RESOLVED and delay is not None:
      state = f"{state} ({delay:.1f}s after discovery)"
    lines.append(_kv("Type state", state))
    lines.append(_kv("Endpoint", endpoint.kind))
    lines.append(_kv("Representation", records.representation_text(endpoint.representation)))
    locators = endpoint.unicast_locators or (
        participant.default_unicast_locators if participant else [])
    if locators:
      lines.append(_kv("Locators", ", ".join(records.locator_text(l) for l in locators)))
  lines.append("")
  return lines


def _render_findings(data):
  active = f.active(data.findings)
  hist = f.counts(data.findings)
  summary = ", ".join(f"{hist[s]} {s.label}" for s in
                      (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO, f.Severity.OK)
                      if hist.get(s))
  lines = _section(f"FINDINGS  ({summary or 'none'})")

  if not active:
    lines += ["No findings.", ""]
  for finding in active:
    lines.append(f"[{finding.severity.label}] rung {finding.rung}  {finding.id}")
    lines += _labelled("", finding.title)
    lines += _labelled("Observed", finding.observed)
    lines += _labelled("Root cause", finding.root_cause)
    lines += _labelled("Remedy", finding.remedy)
    for ref in finding.refs:
      lines.append(f"  {'Reference'.ljust(13)}{ref}")
    lines.append("")

  hidden = f.suppressed(data.findings)
  if hidden:
    lines.append(f"SUPPRESSED ({len(hidden)}) - real findings that a lower-rung "
                 f"failure already explains:")
    for finding in hidden:
      lines.append(f"  {finding.id} (explained by {finding.suppressed_by})")
    lines.append("")
  return lines


def _render_type_appendix(data):
  lines = _section("APPENDIX A - DISCOVERED TYPE (IDL)")
  endpoint = data.endpoint
  if endpoint is None or endpoint.type is None:
    lines += ["(no type information available for this endpoint)", ""]
    return lines

  lines.append(typewalk.idl_text(endpoint.type))
  lines.append("")
  keys = typewalk.key_member_paths(endpoint.type)
  lines.append(_kv("Key members", ", ".join(keys) if keys else "(none - keyless type)"))
  ext = typewalk.extensibility_map(endpoint.type)
  if ext:
    lines.append(_kv("Extensibility", "; ".join(f"{k}={v}" for k, v in sorted(ext.items()))))
  lines.append("")
  return lines


def _render_counter_appendix(data):
  lines = _section("APPENDIX B - RAW STATUS COUNTERS")
  result = data.probe_result
  if result is None or not result.created:
    reason = "probe not run" if result is None else (
        result.create_error or "reader not created")
    lines += [f"(no counters: {reason})", ""]
    return lines

  lines.append(f"probe window: {result.elapsed:.2f}s; valid samples taken: "
               f"{result.samples_taken}")
  lines.append("")

  lines.append("subscription_matched")
  for name in ("current_count", "current_count_change", "total_count",
               "total_count_change"):
    lines.append(f"  {name.ljust(52)}{compat.counter_text(result.subscription_matched, name)}")

  lines.append("requested_incompatible_qos")
  for name in ("total_count", "total_count_change"):
    lines.append(f"  {name.ljust(52)}"
                 f"{compat.counter_text(result.requested_incompatible_qos, name)}")
  policy = compat.get(result.requested_incompatible_qos, "last_policy", None)
  lines.append(f"  {'last_policy'.ljust(52)}{policy if policy is not None else compat.na_text()}")

  lines.append("sample_lost")
  for name in ("total_count", "total_count_change"):
    lines.append(f"  {name.ljust(52)}{compat.counter_text(result.sample_lost, name)}")
  lines.append(f"  {'last_reason'.ljust(52)}"
               f"{compat.reason_text(compat.get(result.sample_lost, 'last_reason', None))}")

  lines.append("sample_rejected")
  for name in ("total_count", "total_count_change"):
    lines.append(f"  {name.ljust(52)}{compat.counter_text(result.sample_rejected, name)}")
  lines.append(f"  {'last_reason'.ljust(52)}"
               f"{compat.reason_text(compat.get(result.sample_rejected, 'last_reason', None))}")

  lines.append("datareader_protocol_status")
  for name in probe_mod.PROTOCOL_COUNTERS:
    value = result.protocol.get(name)
    lines.append(f"  {name.ljust(52)}{compat.na_text() if value is None else value}")

  lines.append("datareader_cache_status")
  for name in probe_mod.CACHE_COUNTERS:
    value = result.cache.get(name)
    lines.append(f"  {name.ljust(52)}{compat.na_text() if value is None else value}")

  lines.append("topic")
  count = result.inconsistent_topic_count
  lines.append(f"  {'inconsistent_topic_status.total_count'.ljust(52)}"
               f"{compat.na_text() if count is None else count}")
  lines.append("")

  if result.listener_events:
    lines.append("listener events (in order observed)")
    for event in result.listener_events:
      lines.append(f"  {event}")
    lines.append("")

  if result.sample_repr:
    lines.append("first valid sample")
    for line in str(result.sample_repr).splitlines():
      lines.append(f"  {line}")
    lines.append("")
  return lines


def _render_wire_appendix(data):
  evidence = data.wire_evidence
  if evidence is None:
    return []
  lines = _section("APPENDIX C - DIRECT RTPS PACKET OBSERVATION")
  lines.append(_kv("Capture", evidence.get("source", "unknown")))
  if evidence.get("capture_filter"):
    lines.append(_kv("Capture filter", evidence["capture_filter"]))
  if evidence.get("target_writer_entity_id"):
    lines.append(_kv("Writer entity filter", evidence["target_writer_entity_id"]))
  if evidence.get("target_writer_guid_prefix"):
    lines.append(_kv("Writer GUID prefix filter", evidence["target_writer_guid_prefix"]))
  error = evidence.get("error")
  if error:
    lines.append(_kv("Result", f"unavailable: {error}"))
    lines.append("")
    return lines
  lines.append(_kv("User-data packets", str(evidence.get("packets", 0))))
  lines.append(_kv("DATA submessages", str(evidence.get("data_packets", 0))))
  lines.append(_kv("DATA_FRAG submessages", str(evidence.get("data_fragments", 0))))
  encapsulations = evidence.get("encapsulation_ids", [])
  lines.append(_kv("Encapsulation IDs", ", ".join(encapsulations) if encapsulations
                   else "none observed"))
  writers = evidence.get("writer_entity_ids", [])
  lines.append(_kv("Writer entity IDs", ", ".join(writers) if writers else "none observed"))
  lines.append(_kv("Serialized bytes", str(evidence.get("payload_bytes", 0))))
  lines.append(_kv("Reassembled bytes", str(evidence.get("reassembled_bytes", 0))))
  lines.append("")
  return lines


def _render_config_appendix(data):
  label = "APPENDIX D" if data.wire_evidence is not None else "APPENDIX C"
  lines = _section(f"{label} - RTI_DOCTOR OWN CONFIGURATION")
  lines.append("Settings rti_doctor applied to its own participant, so that any")
  lines.append("finding above can be judged against how it was measured.")
  lines.append("")
  if data.type_lookup_settings:
    for key, value in sorted(data.type_lookup_settings.items()):
      lines.append(f"  {key.ljust(52)}{value}")
  else:
    lines.append("  (no type-lookup settings recorded)")
  result = data.probe_result
  if result is not None and result.applied_reader_qos:
    lines.append("")
    lines.append("  probe reader/subscriber QoS mirrored from the writer:")
    for key, value in sorted(result.applied_reader_qos.items()):
      lines.append(f"    {key.ljust(50)}{value}")
  lines.append("")
  return lines


# --- JSON renderer -----------------------------------------------------------

def render_json(data):
  """Unstable JSON dump.

  Deliberately has no schema contract: field names and structure may change
  between releases. The text report is the shareable artifact.
  """
  payload = {
      "unstable_schema": True,
      "generated_at": data.generated_at,
      "environment": data.environment,
      "domain_id": data.domain_id,
      "scope": data.scope,
      "verdict": data.verdict,
      "findings": [
          {
              "id": finding.id,
              "rung": finding.rung,
              "severity": finding.severity.label,
              "title": finding.title,
              "observed": finding.observed,
              "root_cause": finding.root_cause,
              "remedy": finding.remedy,
              "evidence": _jsonable(finding.evidence),
              "refs": list(finding.refs),
              "suppressed_by": finding.suppressed_by,
          }
          for finding in data.findings
      ],
  }
  result = data.probe_result
  if result is not None:
    payload["probe"] = {
        "attempted": result.attempted,
        "created": result.created,
        "create_error": result.create_error,
        "matched_count": result.matched_count,
        "samples_taken": result.samples_taken,
        "elapsed_seconds": round(result.elapsed, 3),
        "protocol_status": _jsonable(result.protocol),
        "cache_status": _jsonable(result.cache),
        "payload_verdict": result.walk.verdict if result.walk else None,
        "unreadable_paths": result.walk.failed_paths if result.walk else [],
    }
  if data.wire_evidence is not None:
    payload["wire_observation"] = _jsonable(data.wire_evidence)
  return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def _jsonable(value):
  if isinstance(value, dict):
    return {str(k): _jsonable(v) for k, v in value.items()}
  if isinstance(value, (list, tuple, set)):
    return [_jsonable(v) for v in value]
  if isinstance(value, (str, int, float, bool)) or value is None:
    return value
  return str(value)


# --- Sweep summary -----------------------------------------------------------

def render_sweep_text(rows, domain_id, environment=None, generated_at=None):
  """One-line-per-writer summary table for --all / the sweep screen."""
  environment = environment or compat.environment_info()
  generated_at = generated_at or time.time()
  stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(generated_at))

  lines = [RULE, "RTI DOCTOR INTEROP SWEEP", RULE,
           _kv("Generated", stamp),
           _kv("Command", environment.get("argv", "unknown")),
           _kv("Host", f"{environment.get('host')}  {environment.get('os')}"),
           _kv("Connext", f"{environment.get('connext')}"),
           _kv("Domain", str(domain_id)),
           _kv("Writers", str(len(rows))),
           ""]

  lines += _section("SUMMARY")
  header = f"{'SEV':6} {'TOPIC':32} {'VENDOR':26} VERDICT"
  lines += [header, "-" * len(header)]
  for row in rows:
    lines.append(f"{row['severity']:6} {row['topic'][:32]:32} "
                 f"{row['vendor'][:26]:26} {row['verdict']}")
  lines.append("")

  lines += _section("DETAIL")
  for row in rows:
    lines.append(f"topic '{row['topic']}' ({row['vendor']})")
    lines.append(f"  verdict: {row['verdict']}")
    for finding_id, severity, title in row["findings"]:
      lines.append(f"  [{severity}] {finding_id}: {title}")
    lines.append("")
  return "\n".join(lines) + "\n"
