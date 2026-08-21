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

from . import (compat, findings as f, probe as probe_mod, records, typewalk,
               vendors, wire)

#: Every wrappable line in both reports is laid out against this. 80 is the
#: width a report survives being pasted into: a terminal at its default size, a
#: mail client, a bug comment. Prose, rules and section bars all follow it; the
#: single-token exemption below (a path, a URL, a command line) does not.
WIDTH = 80
RULE = "=" * WIDTH
THIN = "-" * WIDTH

#: What a field observable only in RTPS packets says when no capture has been
#: run. Rendering the field as absent, or omitting its section, made "nobody
#: looked" indistinguishable from "there is nothing there" - and a capture is
#: still only ever started when someone asked for one, so "nobody looked" stays
#: a normal state: a report opened passively, or one where Skip was the answer.
CAPTURE_PLACEHOLDER = "Run capture to ascertain"

#: Label pad for the CAPTURE EVIDENCE summary. Its labels are indented two
#: spaces and run to 21 characters, past `_kv`'s default 16, which collides the
#: value against the label rather than wrapping it.
CAPTURE_LABEL_PAD = 24

#: How to ascertain it, stated wherever the placeholder appears. Opening an
#: endpoint report for diagnosis offers a capture, but a report can reach here
#: having been opened passively or with Skip as the answer, so name the key too.
CAPTURE_HINT = ("Open an endpoint report for diagnosis and choose a capture "
                "interface when it opens to capture RTPS packets for that "
                "endpoint.")


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


def _kv_block(label, value, pad=16):
  """`_kv` for a value long enough to need wrapping, with a hanging indent.

  Prose in a header column has to wrap like prose everywhere else. The topology
  coverage note ran to 274 characters on one line - the only unwrapped paragraph
  in the report, sitting in a block of short labelled counts, and wide enough to
  break any terminal it was read in.
  """
  block = _wrap(value, indent=pad)
  if not block:
    return []
  return [_kv(label, block[0][pad:], pad=pad)] + block[1:]


#: Where the fixed-column tables - Appendix B's counters, the own-configuration
#: blocks - put their value. The widest counter name Connext supplies is 48
#: characters, so a pad of 52 leaves a visible gap after even that one. It also
#: leaves only WIDTH - 54 columns for the value, which `_table_row` folds past.
TABLE_PAD = 52


def _table_row(name, value, gutter="  ", pad=TABLE_PAD):
  """One `name value` row of a fixed-column table.

  A value too long for its column moves below its name rather than running past
  WIDTH, with the gutter mark staying on the name's line. That is safe here and
  is not safe for `_kv` (see below): nothing parses these tables - the report's
  own parser reads the header, the verdict, the findings and Appendix C - and
  the value gets the width of the page instead of the 26 columns left beside a
  48-character name, which is narrower than a single DDS enum name like
  REJECTED_BY_SAMPLES_PER_REMOTE_WRITER_LIMIT.
  """
  text = str(value)
  row = f"{gutter}{str(name).ljust(pad)}{text}"
  if len(row) <= WIDTH:
    return row
  return "\n".join([f"{gutter}{name}"] + _wrap(text, indent=len(gutter) + 2))


# A path, a URL or a command line stays on its label's line however far it runs
# past WIDTH. Moving it to its own line under the label was tried and reverted:
# the text report is this tool's only output contract, its parser reads a field
# as "label, then value on the same line", and the split silently emptied every
# `refs` list - every reference URL here is longer than WIDTH - and dropped
# `source` from the wire appendix, which the vendor tier asserts is a real file.
# A value that overflows is a cosmetic problem; one the parser cannot find is
# not. See `test_a_long_value_stays_parseable_on_its_label_line`.
#
# So WIDTH binds every line the report writes EXCEPT the ones a consumer parses
# as a single line. Besides paths and URLs, those are:
#
#   * Appendix C's list-valued fields. "Writer IDs in matching frames" passes
#     WIDTH at five writers, and a capture on a busy topic sees more.
#   * The VERDICT line, which the parser reads as `body[0]` of the section - so
#     wrapping it would not widen the verdict, it would truncate it. A run with
#     findings in two scopes passes WIDTH on its own.
#
# Folding any of these means teaching every consumer of the report, not just this
# repo's parser, to join continuation lines. The fixed-column tables fold instead
# because nothing parses them (`_table_row`).


def _is_live(name, text):
  """Whether a rendered counter says something happened.

  Any non-zero number counts, including a negative one: `current_count_change`
  of -1 is a peer that unmatched during the probe, which is exactly the kind of
  line this mark exists to surface. The one exception is the -1 that sequence
  number fields use for "none" - a sentinel, not a measurement, and marking
  three of those on every healthy report would spend the mark on the lines it is
  meant to make findable.
  """
  try:
    value = float(text)
  except (TypeError, ValueError):
    return False
  if value == -1 and str(name).endswith("sequence_number"):
    return False
  return value != 0


def _counter(name, value, notable=None):
  """One Appendix B counter, marked in the gutter when it is not zero.

  About 45 of that appendix's 55 lines read zero on a healthy run, and the one
  or two carrying the whole story - a sample_lost total, an out-of-range
  rejection - are typographically identical to them. The mark makes the appendix
  skimmable without dropping the zeros, which are evidence in their own right: a
  counter that exists and reads zero is a different claim from one this Connext
  version cannot supply at all.
  """
  text = str(value)
  if notable is None:
    notable = _is_live(name, text)
  return _table_row(name, text, gutter=f"{'*' if notable else ' '} ")


def _notable_reason(text):
  """Whether a last_reason line says anything happened.

  The rendered form carries its enum name - "SampleLostState.NOT_LOST" - so the
  quiet values are matched anywhere in the string, not as a prefix. They are
  listed exactly; a bare "UNKNOWN" was tried and silenced
  LOST_BY_UNKNOWN_INSTANCE, which is a real loss and the opposite of quiet.

  `compat.REASON_UNSAMPLED` is that same trap from the other side: it is what
  `reason_text` returns when there was no status to read, so it was marked as
  something that happened - `* last_reason  unknown`, on a probe that sampled
  nothing, under a legend saying the mark means a counter moved. Matched by
  equality, which LOST_BY_UNKNOWN_INSTANCE does not satisfy.
  """
  upper = str(text or "").upper()
  if upper == compat.REASON_UNSAMPLED.upper():
    return False
  return bool(upper) and not any(
      quiet in upper for quiet in ("NOT_LOST", "NOT_REJECTED", "N/A"))


def _labelled(label, text, indent=15):
  """"  Label   wrapped text..." with the label on the first line."""
  indent = max(indent, len(label) + 3)
  block = _wrap(text, indent=indent)
  if not block:
    return []
  first = block[0]
  prefix = f"  {label}".ljust(indent)
  return [prefix + first[indent:]] + block[1:]


def _is_preformatted(line):
  """Whether a line is a fixed-column table row rather than prose.

  The requested/offered table aligns on `|`, under a rule of dashes and pluses.
  Reflowing either destroys the alignment that makes the table readable, so both
  pass through an observation verbatim while the prose around them wraps.
  """
  stripped = line.strip()
  return "|" in stripped or (bool(stripped) and set(stripped) <= set("-+"))


def _labelled_observation(label, text, indent=15):
  """Render an observation, retaining intentional table and paragraph lines.

  A single-paragraph observation wraps like any other field. A multi-line one
  carries a fixed-column table, so its table rows pass through verbatim - but
  only those. Passing the whole block through unwrapped left the prose that
  frames the table (the unevaluated-policy note, the counterpart census) as
  single lines of 340 and 98 characters, well past WIDTH.
  """
  text = str(text or "")
  if "\n" not in text:
    return _labelled(label, text, indent)
  indent = max(indent, len(label) + 3)
  pad = " " * indent
  body = []
  for line in text.splitlines():
    if not line.strip():
      # A blank line separates the table from its prose; keep it, without
      # trailing indent whitespace.
      body.append("")
    elif _is_preformatted(line):
      body.append(pad + line)
    else:
      body.extend(_wrap(line, indent=indent))
  if not body:
    return []
  prefix = f"  {label}".ljust(indent)
  return [prefix + body[0][indent:]] + body[1:]


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
    # The hint is a paragraph, so it wraps like one. Appended whole it was the
    # system report's only line past WIDTH, at 131 characters.
    lines += ([_kv("Observed", CAPTURE_PLACEHOLDER)]
              + _wrap(CAPTURE_HINT, indent=0) + [""])
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
    lines += _labelled_observation("Observed", issue.observed)
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
      lines.append(_table_row(key, value))
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
               topology=None, discovery_evidence=None, capture_interface=None,
               participant_evidence=None):
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
    # RTI Network Capture of rti_doctor's OWN participant. Kept separate from
    # `wire_evidence` rather than merged into it because the two have different
    # scopes and a merged number would belong to neither: an interface capture
    # sees every participant on the wire and no shared memory at all, while this
    # sees one participant on every transport.
    self.participant_evidence = participant_evidence
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
    outcome.wrote_entity = getattr(result, "probe_kind", "reader") == "writer"
    outcome.wrote_samples = getattr(result, "wrote_samples", False)
    outcome.acknowledged = getattr(result, "acknowledged", None)
    if outcome.wrote_entity and outcome.wrote_samples:
      # The writer probe's delivery evidence is what it published and got
      # acknowledged, not what it read back.
      outcome.samples_received = result.samples_written
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
  # Same position as in render_text. The summary was added to the saved report
  # first and not here, so pressing `c` in the TUI put the version in the Wire
  # tab and nothing on Overview - the operator who ran the capture was the one
  # person who could not see what it produced.
  overview += _render_capture_summary(data)
  overview += _render_peer(data)
  overview += _render_topology(data)
  return {
      "overview": "\n".join(overview),
      "findings": "\n".join(_render_findings(data)),
      "type": "\n".join(_render_type_appendix(data)),
      "probe": "\n".join(_render_counter_appendix(data)),
      "wire": "\n".join(_render_wire_appendix(data) or _wire_placeholder(data)),
      "config": "\n".join(_render_config_appendix(data)),
  }


def _wire_placeholder(data):
  """What an uncaptured Wire tab offers, named for what THIS peer would gain.

  The old text advertised a Fast DDS version on every endpoint, so on a Connext
  peer it offered the one thing a capture there cannot produce.
  """
  lines = ["No direct RTPS packet capture was requested.", ""]
  if _peer_may_have_fastdds_version(data):
    lines.append(f"Fast DDS version: {CAPTURE_PLACEHOLDER}.")
  lines += [
      f"RTPS reliable handshake (HEARTBEAT/ACKNACK/GAP): {CAPTURE_PLACEHOLDER}.",
      "Packet capture is selected when an endpoint report is opened.", ""]
  return lines


def render_text(data):
  """The shareable report file."""
  lines = _header_lines(data)
  lines += _section("VERDICT")
  lines += [data.verdict, ""]

  lines += _render_capture_summary(data)
  lines += _render_peer(data)
  lines += _render_topology(data)
  lines += _render_findings(data)
  lines += _render_type_appendix(data)
  lines += _render_counter_appendix(data)
  lines += _render_wire_appendix(data)
  lines += _render_config_appendix(data)
  return "\n".join(lines) + "\n"


def _render_capture_summary(data):
  """What the capture added that discovery could not, near the top.

  The full counts stay in Appendix C. This answers the question an engineer
  actually has after pressing `c`: what do I know now that I did not know
  before? Two things can only come from packets - the peer's product version,
  which is an RTI discovery extension and therefore absent for every other
  vendor, and the encapsulation actually used on the wire, as opposed to the
  DataRepresentation the endpoint advertised it would use.

  It renders only when a capture was run, so a report without one is unchanged.
  """
  wire_evidence = data.wire_evidence
  discovery = data.discovery_evidence
  if wire_evidence is None and discovery is None:
    return []

  lines = _section("CAPTURE EVIDENCE")
  wire_error = (wire_evidence or {}).get("error")
  discovery_error = (discovery or {}).get("error")
  if wire_error and (discovery_error or discovery is None):
    # Nothing was read at all. Say why, and do not let it read as "the wire was
    # quiet" - those are opposite conclusions for whoever reads this next.
    lines.append(_kv("Result", f"capture unavailable: {wire_error}",
                     CAPTURE_LABEL_PAD))
    lines.append("")
    return lines

  gained, unchanged = [], []

  versions = _peer_fastdds_versions(data)
  if versions and not discovery_error:
    gained.append(("Fast DDS version", ", ".join(versions),
                   "packets only - the discovery API cannot report a product "
                   "version for a non-RTI vendor"))

  encapsulations = (wire_evidence or {}).get("encapsulation_ids") or []
  if encapsulations:
    observed = wire.encapsulation_text(encapsulations)
    gained.append(("Wire representation", observed,
                   _representation_agreement(data.endpoint, observed)))

  data_frames = ((wire_evidence or {}).get("data_packets", 0)
                 + (wire_evidence or {}).get("data_fragments", 0))
  if wire_evidence is not None and not wire_error and not data_frames:
    unchanged.append(
        "No user DATA from the selected endpoint was captured. That is what a "
        "writer with no matched reader looks like, and it is also what an "
        "endpoint the capture filter could not reach looks like - the counts "
        "and the filter in Appendix C separate the two.")
  if not gained and not unchanged:
    unchanged.append("The capture added nothing beyond what discovery already "
                     "reported.")

  if gained:
    lines.append("New from packets, not available from discovery")
    for label, value, note in gained:
      # These labels are this summary's own, not the parsed Appendix C field
      # names, so a value too wide for the column folds under it rather than
      # running past WIDTH - a wire representation naming several encodings does.
      lines.append(_table_row(label, value, pad=CAPTURE_LABEL_PAD - 2))
      lines.extend(_wrap(note, indent=4))
  for note in unchanged:
    lines.extend(_wrap(note, indent=2))
  lines.append("")
  lines.append("Full counts, filters and announcement details in Appendix C.")
  lines.append("")
  return lines


def _peer_may_have_fastdds_version(data):
  """Whether a Fast DDS product version could describe THIS report's peer.

  The test is deliberately "not known to be RTI" rather than "known to be Fast
  DDS". Suppressing on a positive Fast DDS identification only would also
  suppress every report that carries no participant record at all - a headless
  single-topic run, or a peer whose vendor id could not be read - and those are
  cases where the packet-read version is the only version evidence there is.

  An RTI peer is the one case that is certain: the product version comes from a
  Fast DDS vendor-specific discovery PID that an RTI participant never sends, so
  any version in the capture belongs to somebody else on the domain.
  """
  participant = data.participant
  return participant is None or not vendors.is_rti(participant.vendor_id)


def _peer_fastdds_versions(data):
  """Fast DDS versions attributable to THIS report's peer.

  A capture is scoped to a domain, not to an endpoint, so it hears every
  participant on the wire. `fastdds_product_versions` is that whole set, and
  rendering it on an endpoint report attributed another participant's version to
  the selected peer - a Connext reader report led with "Fast DDS version 3.6.2.0"
  read off the unrelated Fast DDS writer sharing its domain.

  Narrowed in two steps, each only as far as the evidence allows:

    * A peer known to be RTI gets nothing; see `_peer_may_have_fastdds_version`.
    * When the peer's GUID prefix is known AND the evidence carries the
      per-participant pairing, keep only versions that prefix advertised. A
      prefix that appears in a populated pairing and owns no version really did
      not advertise one, so that yields `[]` rather than falling back - falling
      back is what re-attributes a neighbour's version.

  Anything less determined than that returns the unpaired set, which is what
  every caller rendered before there was a pairing to narrow by.
  """
  discovery = data.discovery_evidence or {}
  everything = sorted(discovery.get("fastdds_product_versions") or [])
  if not _peer_may_have_fastdds_version(data):
    return []
  pairs = [pair for pair in (discovery.get("fastdds_participant_versions") or [])
           if isinstance(pair, (list, tuple)) and len(pair) == 2]
  prefix = wire.record_guid_prefix(data.participant) if data.participant else None
  if not prefix or not pairs:
    return everything
  return sorted({str(pair[1]) for pair in pairs
                 if str(pair[0]).replace(":", "").lower() == prefix})


def _representation_agreement(endpoint, observed):
  """Whether the wire agrees with what a *writer* advertised, when that is knowable.

  Deliberately narrow. The claim only holds for a writer, whose effective
  representation is the first entry in its list; a reader's list is the set it
  *accepts*, so a reader advertising [XCDR1, XCDR2] and receiving XCDR2 agrees
  with the wire rather than contradicting it, and capture is supported on reader
  reports. AUTO is excluded because its effective value is not determinable from
  discovery at all - `qos_match` declines to compare it for the same reason, and
  a summary claiming a disagreement it declines to claim would be the report
  arguing with itself.

  Returns a plain statement of fact when no comparison can honestly be made.
  """
  neutral = "what the writer actually serialized"
  if endpoint is None or not getattr(endpoint, "is_writer", False):
    return "observed on the wire"
  ids = records.representation_ids(endpoint.representation)
  if not ids or -1 in ids:
    return neutral
  advertised = records.REPRESENTATION_NAMES.get(ids[0])
  if not advertised:
    return neutral
  if advertised.lower() in observed.lower():
    return f"agrees with the advertised {advertised}"
  return f"**disagrees with the advertised {advertised}**"


def capture_headline(data):
  """One line naming what a capture actually parsed, for the TUI status bar.

  The status line used to report only a frame count, so the commonest real
  result - "0 matching frames" - said nothing about whether the two facts a
  capture exists to recover were recovered. A Fast DDS version can be read from
  a capture carrying no user data at all, so the count alone is actively
  misleading about what the operator just got.

  Written for one line of status bar: no padding, no wrapping, present tense.
  Kept beside `_render_capture_summary` so the headline and the report section
  cannot drift into disagreeing about the same capture.
  """
  wire_evidence = data.wire_evidence or {}
  discovery = data.discovery_evidence or {}
  parts = []

  # Never for a peer known to be RTI. There the headline led with "no Fast DDS
  # version advertised", which is true of every RTI endpoint that ever existed
  # and told the operator nothing about the capture they just ran.
  if _peer_may_have_fastdds_version(data):
    versions = _peer_fastdds_versions(data)
    if discovery.get("error"):
      parts.append("version unreadable")
    elif versions:
      parts.append(f"Fast DDS version {', '.join(versions)}")
    else:
      parts.append("no Fast DDS version advertised")

  encapsulations = wire_evidence.get("encapsulation_ids") or []
  if encapsulations:
    parts.append(f"representation {wire.encapsulation_text(encapsulations)}")
  else:
    # Name the reason rather than the absence: no user DATA and no readable
    # representation are the same observation, and the operator needs to know
    # which question went unanswered.
    parts.append("no user DATA, so no wire representation")

  # The reliable handshake, when there was any of it. This is what the version
  # line used to occupy on a Connext peer, and it is the fact an operator is
  # actually after: heartbeats answered by ACKNACKs is a working reliable path.
  heartbeats = wire_evidence.get("heartbeats", 0)
  acknacks = wire_evidence.get("acknacks", 0)
  if heartbeats or acknacks:
    parts.append(f"{heartbeats} HEARTBEAT / {acknacks} ACKNACK")

  frames = wire_evidence.get("packets", 0)
  parts.append(f"{frames} matching frame{'' if frames == 1 else 's'}")
  return "; ".join(parts)


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
  lines += _counterpart_lines(data)
  lines.append("")
  return lines


def _counterpart_lines(data):
  """The application endpoints on the other side of this topic, named here.

  The RxO findings state the pair properly - "Writer in 'X' (Fast DDS) -> Reader
  in 'Y' (Connext)" - but that is buried in the findings list, and PEER, which
  is where a reader looks first, described only one end. Naming both here is
  most of what stops the probe's own match reading as the system's.

  Read from the RxO findings' evidence rather than recomputed: they already did
  the pairing, and a second implementation would be free to disagree with the
  first about who the counterparts are.
  """
  labels, key = [], "reader" if getattr(data.endpoint, "is_writer", False) else "writer"
  discovered = 0
  for finding in data.findings:
    # Every per-pair verdict qos_match can produce. A counterpart that will not
    # match for a non-RxO reason is still a counterpart, and leaving it out
    # would make PEER disagree with the findings below it.
    if finding.id in ("qos.compatible", "qos.rxo_mismatch",
                      "qos.partition_disjoint", "qos.mismatch_undescribed"):
      # The count comes from the pairing itself, not from the names below it.
      # `_label` is "Reader in 'app' (Connext)" - participant, not endpoint - so
      # two readers in one participant are one label and PEER printed "1
      # discovered" directly above findings reading "Counterpart 1 of 2".
      discovered = max(discovered,
                       finding.evidence.get("counterparts_discovered") or 0)
      label = finding.evidence.get(key)
      if label and label not in labels:
        labels.append(label)
  if not labels:
    return []
  count = max(discovered, len(labels))
  text = f"{count} discovered on this topic: {', '.join(labels)}."
  if count > len(labels):
    # Said rather than silently listing fewer names than the count promises.
    text += (f" That is {len(labels)} distinct name(s): a participant with more "
             "than one endpoint on this topic is named once here, and numbered "
             "once per pair in the findings below.")
  return _kv_block("Counterparts",
                   f"{text} rti_doctor's own probe is not among them.")


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
  lines.extend(_kv_block("Coverage", topology["completion_note"]))
  lines.append("")
  return lines


def _severity_summary(findings):
  hist = f.counts(findings)
  summary = ", ".join(f"{hist[s]} {s.label}" for s in
                      (f.Severity.ERROR, f.Severity.WARN, f.Severity.INFO, f.Severity.OK)
                      if hist.get(s))
  return summary or "none"


def _render_one_finding(finding):
  lines = [f"[{finding.severity.label}] rung {finding.rung}  {finding.id}"]
  lines += _labelled("", finding.title)
  lines += _labelled_observation("Observed", finding.observed)
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


def _render_findings(data):
  """Findings in scoped blocks: the observed system first, the probe after.

  The system comes first deliberately. It is what the operator came to find out,
  and it is true whether or not rti_doctor ran; the probe is this tool's own
  experiment, and putting it second stops its success being read as the headline.

  Sub-headers are plain left-aligned lines. They must NOT be rule lines - the
  report's parser ends a section at the next `---`, so an underlined sub-header
  here would truncate the findings section and silently drop everything below it.
  """
  findings = list(data.findings)
  lines = _section(f"FINDINGS  ({_severity_summary(findings)})")

  if not findings:
    lines += ["No findings.", ""]
    return lines

  # The system first, since that is what the operator came to find out, then what
  # rti_doctor's own configuration may be hiding from it - which is the first
  # thing to read when the section above is thin or empty.
  for scope in (f.SCOPE_OBSERVED, f.SCOPE_OWN_CONFIG, f.SCOPE_PROBE,
                f.SCOPE_TOOL):
    group = f.in_scope(findings, scope)
    if not group:
      continue
    lines.append(f"{f.SCOPE_TITLES[scope]}  ({_severity_summary(group)})")
    lines.extend(_wrap(f.SCOPE_NOTES[scope], indent=2))
    lines.append("")
    for finding in group:
      lines.extend(_render_one_finding(finding))
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

  wrote = getattr(result, "probe_kind", "reader") == "writer"
  if wrote:
    lines.append(f"probe window: {result.elapsed:.2f}s; samples written: "
                 f"{result.samples_written}"
                 + ("" if result.wrote_samples
                    else " (the probe published nothing - see the note below)"))
  else:
    lines.append(f"probe window: {result.elapsed:.2f}s; valid samples taken: "
                 f"{result.samples_taken}")
  lines.append("* marks a counter above zero, or a reason that is not the quiet default.")
  # Paired with the marker's terse form. A reader who takes "n/a" for zero draws
  # the opposite conclusion from the one the line supports.
  lines.append("n/a marks a counter this Connext version cannot supply. It is not a zero.")
  lines.append("")

  lines.append("publication_matched" if wrote else "subscription_matched")
  for name in ("current_count", "current_count_change", "total_count",
               "total_count_change"):
    lines.append(_counter(name, compat.counter_text(result.subscription_matched, name)))

  # Which incompatible-QoS status exists at all depends on which entity the
  # probe created. Printing the reader's on a writer probe reported a status
  # that was never read as one the middleware could not supply.
  if wrote:
    lines.append("offered_incompatible_qos")
    for name in ("total_count", "total_count_change"):
      lines.append(_counter(
          name, compat.counter_text(result.offered_incompatible_qos, name)))
    policy = compat.get(result.offered_incompatible_qos, "last_policy", None)
    lines.append(_counter("last_policy",
                          policy if policy is not None else compat.na_text(),
                          notable=policy is not None))
    policies = compat.incompatible_policies(result.offered_incompatible_qos)
    if policies:
      policy_text = ", ".join(f"{name} (x{count})" for name, count in policies)
    elif result.offered_incompatible_qos is None:
      policy_text = compat.na_text()
    else:
      policy_text = "none"
    lines.append(_counter("policies", policy_text, notable=bool(policies)))
  else:
    lines.append("requested_incompatible_qos")
    for name in ("total_count", "total_count_change"):
      lines.append(_counter(
          name, compat.counter_text(result.requested_incompatible_qos, name)))
    policy = compat.get(result.requested_incompatible_qos, "last_policy", None)
    lines.append(_counter("last_policy",
                          policy if policy is not None else compat.na_text(),
                          notable=policy is not None))
    # `last_policy` names one policy; `policies` names all of them. Kept side by
    # side rather than replacing it, because a reader comparing this report
    # against the middleware's own status output should find both fields.
    policies = compat.incompatible_policies(result.requested_incompatible_qos)
    if policies:
      policy_text = ", ".join(f"{name} (x{count})" for name, count in policies)
    elif result.requested_incompatible_qos is None:
      policy_text = compat.na_text()
    else:
      policy_text = "none"
    lines.append(_counter("policies", policy_text, notable=bool(policies)))

  if wrote:
    # The whole reader block is omitted rather than printed as unavailable.
    # `n/a on Connext X` is a claim about the middleware, and
    # every reader status read that way on this path was really "no reader was
    # ever created" - the probe made a writer, because the selected endpoint is
    # a reader. Those statuses exist on this Connext version; nothing asked for
    # them.
    lines.append("datawriter_protocol_status")
    for name in probe_mod.WRITER_PROTOCOL_COUNTERS:
      value = result.writer_protocol.get(name)
      lines.append(_counter(name, compat.na_text() if value is None else value))

    lines.append("reliable_writer_cache_changed_status")
    for name in probe_mod.WRITER_CACHE_COUNTERS:
      value = result.writer_cache.get(name)
      lines.append(_counter(name, compat.na_text() if value is None else value))
  else:
    lines.append("sample_lost")
    for name in ("total_count", "total_count_change"):
      lines.append(_counter(name, compat.counter_text(result.sample_lost, name)))
    reason = compat.reason_text(compat.get(result.sample_lost, "last_reason", None))
    lines.append(_counter("last_reason", reason, notable=_notable_reason(reason)))

    lines.append("sample_rejected")
    for name in ("total_count", "total_count_change"):
      lines.append(_counter(name, compat.counter_text(result.sample_rejected, name)))
    reason = compat.reason_text(compat.get(result.sample_rejected, "last_reason", None))
    lines.append(_counter("last_reason", reason, notable=_notable_reason(reason)))

    lines.append("datareader_protocol_status")
    for name in probe_mod.PROTOCOL_COUNTERS:
      value = result.protocol.get(name)
      lines.append(_counter(name, compat.na_text() if value is None else value))

    lines.append("datareader_cache_status")
    for name in probe_mod.CACHE_COUNTERS:
      value = result.cache.get(name)
      lines.append(_counter(name, compat.na_text() if value is None else value))

  lines.append("topic")
  count = result.inconsistent_topic_count
  lines.append(_counter("inconsistent_topic_status.total_count",
                        compat.na_text() if count is None else count))
  lines.append("")

  if wrote and not result.wrote_samples:
    lines.extend(_wrap(
        "The probe created a matching writer but published nothing, so the "
        "counters above describe discovery and the reliable handshake only - "
        "not delivery. rti_doctor does not write into a system it is "
        "diagnosing unless asked: publishing synthetic samples would deliver "
        "them to the real subscriber, which cannot distinguish them from "
        "production data. Zero pushed samples here is rti_doctor's own "
        "restraint, never a fault of the peer."))
    lines.append("")
  elif wrote and result.acknowledged is not None:
    lines.append(_kv("acknowledged by the selected reader",
                     "yes" if result.acknowledged else
                     "no - wait_for_acknowledgments timed out", 52))
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
  # Either mechanism alone earns the appendix. RTI Network Capture needs no
  # interface and no capture privileges, so a run can produce participant
  # evidence and no interface evidence at all - and gating the whole appendix on
  # `wire_evidence` would then discard the only packet evidence there was.
  if evidence is None:
    if data.participant_evidence is None:
      return []
    return (_section("APPENDIX C - DIRECT RTPS PACKET OBSERVATION")
            + _render_participant_evidence(data))
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
    lines += _render_participant_evidence(data)
    lines += _render_discovery_evidence(data)
    return lines
  lines.append(_kv("Frames matching filters", str(evidence.get("packets", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("DATA in matching frames", str(evidence.get("data_packets", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("DATA_FRAG in matching frames", str(evidence.get("data_fragments", 0)),
                   WIRE_LABEL_PAD))
  # The reliable protocol, counted separately from user data. These four are
  # what makes "matched but silent" diagnosable from packets alone: heartbeats
  # with no ACKNACK is a reader that is not answering, and no heartbeats at all
  # from a RELIABLE writer is a match that only one side believes in.
  lines.append(_kv("HEARTBEAT in matching frames", str(evidence.get("heartbeats", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("ACKNACK in matching frames", str(evidence.get("acknacks", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("GAP in matching frames", str(evidence.get("gaps", 0)),
                   WIRE_LABEL_PAD))
  lines.append(_kv("NACK_FRAG in matching frames",
                   str(evidence.get("nack_fragments", 0)), WIRE_LABEL_PAD))
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
  lines += _render_participant_evidence(data)
  lines += _render_discovery_evidence(data)
  return lines


def _render_participant_evidence(data):
  """RTI Network Capture of our own participant: the shared-memory half.

  Rendered inside Appendix C rather than as its own appendix, because it answers
  the same question as the section above it - what crossed between these two
  endpoints - and an operator comparing the two needs them adjacent. What
  differs is the scope, and every line here says so.
  """
  evidence = data.participant_evidence
  if evidence is None:
    return []
  lines = ["RTI Network Capture of rti_doctor's own participant"]
  lines.extend(_wrap(
      "Recorded by instrumenting the participant rather than an interface, so "
      "it includes SHARED MEMORY traffic that no interface capture can see - "
      "and only rti_doctor's own frames, never traffic between two other "
      "participants.", indent=2))
  error = evidence.get("error")
  if error:
    lines.append(_kv("  Result", f"unavailable: {error}", WIRE_LABEL_PAD))
    lines.append("")
    return lines
  lines.append(_kv("  Capture", evidence.get("source", "unknown"), WIRE_LABEL_PAD))
  # Every count below is FRAMES CONTAINING that submessage, which is what
  # `wire.summarize` measures - not submessages. One RTPS frame routinely
  # carries several kinds at once, so these sum to more than the frame count,
  # and labelled "DATA 3 / HEARTBEAT 5" beside "Frames 6" the appendix read like
  # a tool that cannot add up. The interface-capture block above already says
  # "in matching frames" for the same numbers; this now says it too.
  lines.append(_kv("  Frames from this participant",
                   str(evidence.get("packets", 0)), WIRE_LABEL_PAD))
  for label, key in (("DATA in these frames", "data_packets"),
                     ("DATA_FRAG in these frames", "data_fragments"),
                     ("HEARTBEAT in these frames", "heartbeats"),
                     ("ACKNACK in these frames", "acknacks"),
                     ("GAP in these frames", "gaps"),
                     ("NACK_FRAG in these frames", "nack_fragments")):
    lines.append(_kv(f"  {label}", str(evidence.get(key, 0)), WIRE_LABEL_PAD))
  lines.extend(_wrap("A frame may carry several submessage kinds, so these "
                     "count frames and not submessages, and they sum to more "
                     "than the frame count above.", indent=2))
  encapsulations = evidence.get("encapsulation_ids") or []
  lines.append(_kv("  Observed DDS data representation",
                   wire.encapsulation_text(encapsulations) if encapsulations
                   else "none observed", WIRE_LABEL_PAD))
  lines.append("")
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
  # Skipped for a peer known to be RTI, and narrowed to this peer's own GUID
  # prefix where the evidence supports it. See `_peer_fastdds_versions`: the
  # capture hears the whole domain, so the unfiltered set belongs to no endpoint
  # in particular.
  if _peer_may_have_fastdds_version(data):
    versions = _peer_fastdds_versions(data)
    lines.append(_kv("  Fast DDS versions advertised",
                     ", ".join(versions) if versions
                     else "none observed in this capture", WIRE_LABEL_PAD))
  type_information = evidence.get("type_information_participants") or []
  lines.append(_kv("  TypeInformation participants",
                   ", ".join(type_information) if type_information
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
  # Keyed on whether Appendix C rendered AT ALL, not on `wire_evidence` alone.
  # RTI Network Capture produces an Appendix C with no interface capture behind
  # it, and testing only `wire_evidence` then emitted a second "APPENDIX C" -
  # two sections with one letter, in a report whose whole contract is a fixed,
  # citable section order.
  has_packet_appendix = (data.wire_evidence is not None
                         or data.participant_evidence is not None)
  label = "APPENDIX D" if has_packet_appendix else "APPENDIX C"
  lines = _section(f"{label} - RTI_DOCTOR OWN CONFIGURATION")
  lines.append("Settings rti_doctor applied to its own participant, so that any")
  lines.append("finding above can be judged against how it was measured.")
  lines.append("")
  if data.type_lookup_settings:
    for key, value in sorted(data.type_lookup_settings.items()):
      lines.append(_table_row(key, value))
  else:
    lines.append("  (no type-lookup settings recorded)")
  result = data.probe_result
  if result is not None and result.applied_reader_qos:
    lines.append("")
    # Named for the entity the probe actually created. On a reader target the
    # probe builds a writer mirroring the reader, and calling that "reader QoS
    # mirrored from the writer" described neither side of what ran.
    if getattr(result, "probe_kind", "reader") == "writer":
      lines.append("  probe writer/publisher QoS, offering what the reader requests:")
    else:
      lines.append("  probe reader/subscriber QoS mirrored from the writer:")
    for key, value in sorted(result.applied_reader_qos.items()):
      # Nested a level under its heading, so the value column matches the rows
      # above it: two more of indent against two less of pad.
      lines.append(_table_row(key, value, gutter="    ", pad=TABLE_PAD - 2))
  lines.append("")
  return lines

