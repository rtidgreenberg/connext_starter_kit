"""Report rendering: the shareable text file and the Textual-friendly sections.

The text report is the only output contract. There was a second, `--format
json`, described in its own docstring as an unstable dump with no schema - so
it could not be relied on, while still having to be kept working, tested, and
free of anything the text report did not also carry. Everything a consumer
needs is in the text: fixed section order, one line per finding id and
severity, and labelled fields underneath.

Its rules:

  * Only observed values. A counter unavailable on this Connext version renders
    as compat.na_text(), never as 0 and never omitted.
  * Fixed section order, so two reports diff cleanly against each other.
  * An environment header, so a recipient needs no follow-up questions.
  * A complete raw counter appendix, so a reader who doubts a finding can check.
  * Every finding rendered. A finding whose likely cause is also present says
    so on a "Likely explained by" line; nothing is filtered out by that guess.
"""

import time

from . import compat, findings as f, probe as probe_mod, records, typewalk, wire

WIDTH = 100
RULE = "=" * WIDTH
THIN = "-" * WIDTH

#: What a field observable only in RTPS packets says when no capture has been
#: run. Rendering the field as absent, or omitting its section, made "nobody
#: looked" indistinguishable from "there is nothing there" - and since captures
#: are now only ever started when an operator asks, "nobody looked" is the
#: normal state rather than an unusual one.
CAPTURE_PLACEHOLDER = "Run capture to ascertain"

#: How to ascertain it, stated wherever the placeholder appears.
CAPTURE_HINT = ("Open an endpoint report and press c to capture RTPS packets for "
                "that endpoint.")


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
  indent = max(indent, len(label) + 3)
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


def system_filename(domain_id, timestamp=None):
  """Ticket-friendly filename for a saved passive system scan."""
  stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp or time.time()))
  return f"rti_doctor_system_{domain_id}_{stamp}.txt"


def render_system_text(snapshot, domain_id, environment=None,
                       type_lookup_settings=None):
  """Render an immutable system-scan snapshot without refreshing it."""
  environment = environment or compat.environment_info()
  stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(snapshot.captured_at))
  topology_data = snapshot.topology
  counts = {severity: 0 for severity in f.Severity}
  for issue in snapshot.issues:
    counts[issue.severity] = counts.get(issue.severity, 0) + 1
  lines = [RULE, "RTI DOCTOR SYSTEM REPORT", RULE,
           _kv("Generated", stamp),
           _kv("Tool", "rti_doctor (tools/rti_doctor)"),
           _kv("Command", environment.get("argv", "unknown")),
           _kv("Host", f"{environment.get('host')}  {environment.get('os')}  "
                       f"{environment.get('machine')}"),
           _kv("Connext", f"{environment.get('connext')}  "
                          f"(NDDSHOME={environment.get('nddshome')})"),
           _kv("Python", environment.get("python")),
           _kv("Domain", str(domain_id)), ""]
  lines += render_topology_text(topology_data)
  # Always rendered, including when nothing was captured. A Fast DDS peer
  # advertises its product version only in RTPS discovery packets, so no
  # passive DDS-level scan can supply this; omitting the section when no
  # capture had been run made an unasked question look like a settled one.
  lines += _section("FAST DDS VERSION EVIDENCE")
  if snapshot.fastdds_product_versions:
    lines += [_kv("Observed", ", ".join(snapshot.fastdds_product_versions)), ""]
  else:
    lines += [_kv("Observed", CAPTURE_PLACEHOLDER), CAPTURE_HINT, ""]
  lines += _section("ISSUE SUMMARY")
  lines += [_kv("Errors", str(counts[f.Severity.ERROR])),
            _kv("Warnings", str(counts[f.Severity.WARN])),
            _kv("Notes", str(counts[f.Severity.INFO])), ""]
  lines += _section("ISSUES")
  if not snapshot.issues:
    # "No issues" over an empty domain would read as a clean bill of health for
    # a system that was never found. Say which of the two it is.
    if not topology_data["participants"]:
      lines += [f"No DDS participants were discovered on domain {domain_id}, so "
                "there is nothing to report.",
                "This is not a clean bill of health: nothing was observed.", ""]
    else:
      lines += ["No active issues in this snapshot.", ""]
  for number, issue in enumerate(snapshot.issues, 1):
    lines.append(f"[{number}] [{issue.severity.label}] {', '.join(issue.finding_ids)}")
    lines += _labelled("Title", issue.title)
    lines += _labelled("Topic", issue.topic_name or "(domain-wide)")
    lines += _labelled("Scope", issue.scope)
    if issue.writer_keys:
      lines += _labelled("Writers", ", ".join(issue.writer_keys))
    if issue.reader_keys:
      lines += _labelled("Readers", ", ".join(issue.reader_keys))
    if issue.participant_keys:
      lines += _labelled("Participants", ", ".join(issue.participant_keys))
    lines += _labelled("Observed", issue.observed)
    lines += _labelled("Root cause", issue.root_cause)
    lines += _labelled("Recommendation", issue.recommendation)
    # Context, not a filter: this issue is listed and counted regardless.
    if issue.explained_by:
      lines += _labelled("Likely explained by",
                         ", ".join(issue.explained_by) +
                         " - confirm it applies here before acting on it, "
                         "since the link is by finding id alone.")
    lines.append("")
  lines += _section("RTI_DOCTOR OWN CONFIGURATION")
  lines += ["Settings rti_doctor applied to its own participant, so that any",
            "issue above can be judged against how it was measured.", ""]
  if type_lookup_settings:
    for key, value in sorted(type_lookup_settings.items()):
      lines.append(f"  {str(key).ljust(52)}{value}")
  else:
    lines.append("  (no type-lookup settings recorded)")
  lines.append("")
  lines += _section("SNAPSHOT LIMITATIONS")
  lines += ["This report is an observed passive snapshot, not proof of complete",
            "historical topology or end-to-end data flow. Targeted writer debug",
            "results are intentionally not run or refreshed while saving this report.", ""]
  return "\n".join(lines) + "\n"


class ReportData:
  """Everything one report needs. Built by the caller, consumed by renderers."""

  def __init__(self, domain_id, scope, all_findings, probe_result=None,
               endpoint=None, participant=None, type_lookup_settings=None,
               environment=None, generated_at=None, wire_evidence=None,
               topology=None, discovery_evidence=None, capture_interface=None):
    self.domain_id = domain_id
    self.scope = scope
    self.findings = f.rank(f.link_causes(list(all_findings)))
    self.probe_result = probe_result
    self.endpoint = endpoint
    self.participant = participant
    self.type_lookup_settings = type_lookup_settings or {}
    self.environment = environment or compat.environment_info()
    self.generated_at = generated_at or time.time()
    self.wire_evidence = wire_evidence
    # Discovery metadata read from the same capture as `wire_evidence`. It
    # carries the packet-only facts - Fast DDS product versions above all -
    # that no DDS-level observation can supply.
    self.discovery_evidence = discovery_evidence
    self.capture_interface = capture_interface
    self.topology = topology

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
    outcome.incomplete_reason = result.error
    if result.walk is not None:
      outcome.payload_verdict = result.walk.verdict
      outcome.members_total = result.walk.total
      outcome.members_unreadable = len(result.walk.failed)
      outcome.unreadable_paths = result.walk.failed_paths
      outcome.truncated = result.walk.truncated
    return outcome

  @property
  def verdict(self):
    return f.verdict_line(self.findings, self.outcome)


# --- Text renderer -----------------------------------------------------------

def _header_lines(data):
  lines = [RULE, "RTI DOCTOR INTEROP REPORT", RULE]
  env = data.environment
  stamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(data.generated_at))
  return lines + [
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


def render_view_sections(data):
  """Sections for the interactive report tabs."""
  overview = _header_lines(data)
  overview += _section("VERDICT")
  overview += [data.verdict, ""]
  overview += _render_peer(data)
  overview += _render_topology(data)
  return {
      "overview": "\n".join(overview),
      "findings": "\n".join(_render_findings(data)),
      "type": "\n".join(_render_type_appendix(data)),
      "probe": "\n".join(_render_counter_appendix(data)),
      "wire": "\n".join(_render_wire_appendix(data) or [
          "No direct RTPS packet capture was requested.",
          "",
          f"Fast DDS version: {CAPTURE_PLACEHOLDER}.",
          "Press c to capture RTPS packets for this endpoint. Nothing is "
          "captured until you do.", ""]),
      "config": "\n".join(_render_config_appendix(data)),
  }


def render_text(data):
  """The shareable report file."""
  lines = _header_lines(data)
  lines += _section("VERDICT")
  lines += [data.verdict, ""]

  lines += _render_peer(data)
  lines += _render_topology(data)
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


def _render_topology(data):
  return render_topology_text(data.topology)


def render_topology_text(topology):
  """Render an observed-topology section for reports and sweep summaries."""
  if topology is None:
    return []
  lines = _section("OBSERVED TOPOLOGY")
  lines.append(_kv("Source", topology["source"]))
  lines.append(_kv("Scope", topology["scope"]))
  lines.append(_kv("Domain", str(topology["selected_domain_id"])))
  lines.append(_kv("Participants", str(topology["participants"])))
  lines.append(_kv("Readers", str(topology["readers"])))
  lines.append(_kv("Writers", str(topology["writers"])))
  lines.append(_kv("Topics", ", ".join(topology["topics"]) or "(none observed)"))
  # After the counts, and labelled as a different observation: these domains
  # were heard announcing, and nothing above describes them.
  others = topology.get("other_domains_announcing") or ()
  if others:
    lines.append(_kv("Other domains", ", ".join(str(item) for item in others)
                     + " (heard announcing; no counts above apply to them)"))
  lines.append(_kv("Coverage", topology["completion_note"]))
  lines.append("")
  return lines


def _render_findings(data):
  findings = list(data.findings)
  hist = f.counts(findings)
  summary = ", ".join(f"{hist[s]} {s.label}" for s in
                      (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO, f.Severity.OK)
                      if hist.get(s))
  lines = _section(f"FINDINGS  ({summary or 'none'})")

  if not findings:
    lines += ["No findings.", ""]
  for finding in findings:
    lines.append(f"[{finding.severity.label}] rung {finding.rung}  {finding.id}")
    lines += _labelled("", finding.title)
    lines += _labelled("Observed", finding.observed)
    lines += _labelled("Root cause", finding.root_cause)
    lines += _labelled("Remedy", finding.remedy)
    # Context, not a filter: this finding is listed, counted and carried into
    # the exit code whether or not something here would explain it.
    if finding.explained_by:
      lines += _labelled("Likely explained by",
                         ", ".join(finding.explained_by) +
                         " - confirm it applies to this endpoint before acting "
                         "on it, since the link is by finding id alone.")
    for ref in finding.refs:
      lines.append(f"  {'Reference'.ljust(13)}{ref}")
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


#: Appendix C labels name the frame scope explicitly ("... in matching frames"),
#: which puts the longest of them at 36 characters. `_kv`'s default pad of 16 is
#: shorter than that, so it would return the value glued to the label.
WIRE_LABEL_PAD = 38


def _render_wire_appendix(data):
  evidence = data.wire_evidence
  if evidence is None:
    return []
  lines = _section("APPENDIX C - DIRECT RTPS PACKET OBSERVATION")
  if data.capture_interface:
    lines.append(_kv("Capture interface", data.capture_interface, WIRE_LABEL_PAD))
  lines.append(_kv("Capture", evidence.get("source", "unknown"), WIRE_LABEL_PAD))
  if evidence.get("capture_filter"):
    lines.append(_kv("Capture filter", evidence["capture_filter"], WIRE_LABEL_PAD))
  if evidence.get("target_writer_entity_id"):
    lines.append(_kv("Writer entity filter", evidence["target_writer_entity_id"],
                     WIRE_LABEL_PAD))
  if evidence.get("target_writer_guid_prefix"):
    lines.append(_kv("Writer GUID prefix filter", evidence["target_writer_guid_prefix"],
                     WIRE_LABEL_PAD))
  if evidence.get("target_reader_entity_id"):
    lines.append(_kv("Reader entity filter", evidence["target_reader_entity_id"],
                     WIRE_LABEL_PAD))
  error = evidence.get("error")
  if error:
    lines.append(_kv("Result", f"unavailable: {error}", WIRE_LABEL_PAD))
    lines.append("")
    lines += _render_discovery_evidence(data)
    return lines
  lines.append(_kv("Frames matching filters", str(evidence.get("packets", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("DATA in matching frames", str(evidence.get("data_packets", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("DATA_FRAG in matching frames", str(evidence.get("data_fragments", 0)),
                   WIRE_LABEL_PAD))
  encapsulations = evidence.get("encapsulation_ids", [])
  lines.append(_kv("Observed DDS data representation",
                   wire.encapsulation_text(encapsulations) if encapsulations
                   else "none observed", WIRE_LABEL_PAD))
  lines.append(_kv("Encapsulation IDs in matching frames",
                   ", ".join(encapsulations) if encapsulations else "none observed",
                   WIRE_LABEL_PAD))
  writers = evidence.get("writer_entity_ids", [])
  lines.append(_kv("Writer IDs in matching frames",
                   ", ".join(writers) if writers else "none observed", WIRE_LABEL_PAD))
  lines.append(_kv("Serialized bytes in matching frames",
                   str(evidence.get("payload_bytes", 0)), WIRE_LABEL_PAD))
  lines.append(_kv("Reassembled bytes in matching frames",
                   str(evidence.get("reassembled_bytes", 0)), WIRE_LABEL_PAD))
  if evidence.get("scope_note"):
    lines.append("Scope")
    lines.extend(_wrap(evidence["scope_note"], indent=2))
  lines.append("")
  lines += _render_discovery_evidence(data)
  return lines


def _render_discovery_evidence(data):
  """The packet-only discovery facts read from the same capture.

  Separate from the user-data block above it because it answers a different
  question - who announced themselves, and as what - and because the Fast DDS
  product version is the one fact in this tool that no DDS-level observation
  can produce at all.
  """
  evidence = data.discovery_evidence
  if evidence is None:
    return []
  lines = ["RTPS discovery observed in the same capture"]
  error = evidence.get("error")
  if error:
    lines.append(_kv("  Result", f"unavailable: {error}", WIRE_LABEL_PAD))
    lines.append("")
    return lines
  versions = evidence.get("fastdds_product_versions") or []
  lines.append(_kv("  Fast DDS versions advertised",
                   ", ".join(versions) if versions
                   else "none observed in this capture", WIRE_LABEL_PAD))
  lines.append(_kv("  Participants announcing",
                   str(evidence.get("participants", 0)), WIRE_LABEL_PAD))
  topics = evidence.get("topics") or []
  lines.append(_kv("  Topics announced",
                   ", ".join(topics) if topics else "none observed",
                   WIRE_LABEL_PAD))
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

