"""Finding model, severity ordering, causal links, and verdict rollup.

A Finding is the single output currency of rti_doctor: every check returns a list
of them, and every renderer consumes them. Findings carry a `rung` from the
visibility ladder (see IMPLEMENTATION_PLAN.md), which drives ordering: a rung-2
locator problem is usually what explains a rung-4 match failure.

That causal relationship is reported as context and never as a filter. Findings
used to be suppressed by any ERROR anywhere in the run that carried a matching
id - no topic, endpoint or pair scope - so an unresolved type on one topic
removed a genuinely independent match failure on another from the active list
and from the counts the operator reads. A likely cause is a hypothesis; an
observed symptom is a fact, and the fact is not deleted by the hypothesis.
"""

from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
  """Ordered so that `max()` and reverse-sorting give the worst finding first."""

  OK = 0
  INFO = 1
  WARN = 2
  ERROR = 3

  @property
  def label(self):
    return self.name


# Visibility ladder rungs. Lower rungs fail earlier and explain higher rungs.
RUNG_OWN_CONFIG = 0
RUNG_PARTICIPANT = 1
RUNG_ENDPOINT = 2
RUNG_TYPE = 3
RUNG_MATCH = 4
RUNG_PAYLOAD = 5

RUNG_NAMES = {
    RUNG_OWN_CONFIG: "own config",
    RUNG_PARTICIPANT: "participant discovery",
    RUNG_ENDPOINT: "endpoint discovery",
    RUNG_TYPE: "type resolution",
    RUNG_MATCH: "QoS matching",
    RUNG_PAYLOAD: "payload decode",
}


@dataclass
class Finding:
  """One diagnosed condition.

  `observed` must contain only measured values - never an inferred or assumed
  number. `root_cause` is explicitly the most likely cause, not a certainty;
  renderers present it as such.
  """

  id: str
  rung: int
  severity: Severity
  title: str
  observed: str = ""
  root_cause: str = ""
  remedy: str = ""
  evidence: dict = field(default_factory=dict)
  refs: list = field(default_factory=list)
  # Set by link_causes(): ids of lower-rung findings in this same run that
  # would explain this one. Context for the reader, never a filter - this
  # finding stays in every list, count and exit-code calculation regardless.
  explained_by: tuple = ()

  @property
  def is_problem(self):
    return self.severity >= Severity.WARN


# A finding id maps to the ids that, if also present, are the likely cause of
# it. This annotates; it does not hide. Ordering within each tuple is the order
# the links are reported in.
CAUSAL_EXPLAINERS = {
    "match.none": (
        "blind.domain_tag",
        "blind.spdp2",
        "blind.security_enabled",
        "blind.unknown_peers_rejected",
        "locator.unroutable",
        "transport.class_mismatch",
        "security.mismatch",
        "type.no_type_info",
        "match.incompatible_qos",
        "repr.no_common",
    ),
    # A reader that could not be created is usually explained entirely by the
    # missing type.
    "probe.not_created": ("type.no_type_info",),
    "data.silent": ("match.none", "match.incompatible_qos"),
    "data.window": ("data.fragmentation",),
    "payload.partial": ("data.deserialize_failure",),
    "endpoint.none": (
        "blind.domain_tag",
        "blind.spdp2",
        "blind.security_enabled",
        "security.mismatch",
    ),
}


def link_causes(findings):
  """Annotate each finding with the ids present that would explain it.

  Nothing is removed, reordered or downgraded. The links are unscoped - they
  match on finding id across the whole run - which is why they are presented
  as "likely explained by" rather than used to decide what the operator sees.
  """
  present = {item.id for item in findings}
  for finding in findings:
    finding.explained_by = tuple(
        explainer for explainer in CAUSAL_EXPLAINERS.get(finding.id, ())
        if explainer in present and explainer != finding.id)
  return findings


def rank(findings):
  """Sort by severity descending, then rung ascending, then id for stability."""
  return sorted(findings, key=lambda f: (-int(f.severity), f.rung, f.id))


def counts(findings):
  """Severity histogram over every finding, worst first.

  There is no active/suppressed split: a finding that was produced is counted.
  """
  out = {}
  for finding in findings:
    out[finding.severity] = out.get(finding.severity, 0) + 1
  return out


# --- Verdict -----------------------------------------------------------------

# Payload verdicts, produced by typewalk.
PAYLOAD_FULL = "FULL"
PAYLOAD_PARTIAL = "PARTIAL"
PAYLOAD_FAILED = "FAILED"
PAYLOAD_NOT_ATTEMPTED = "NOT ATTEMPTED"


@dataclass
class ProbeOutcome:
  """What the live probe actually managed to do. All fields are observed."""

  attempted: bool = False
  matched: bool = False
  samples_received: int = 0
  payload_verdict: str = PAYLOAD_NOT_ATTEMPTED
  members_total: int = 0
  members_unreadable: int = 0
  unreadable_paths: list = field(default_factory=list)
  skip_reason: str = None
  #: The walk stopped at rti_doctor's own element/depth caps, so "every member
  #: read" is a statement about the members visited, not about the sample.
  truncated: bool = False
  #: The probe failed after its reader was created; whatever it did observe is
  #: real, but the run is not a complete observation.
  incomplete_reason: str = None
  #: True when the probe created a WRITER, because the selected endpoint is a
  #: reader. Delivery is then only measurable if the probe also published, which
  #: `wrote_samples` records. Without it, "no samples" describes rti_doctor's own
  #: restraint and must not be phrased as a symptom.
  wrote_entity: bool = False
  wrote_samples: bool = False
  #: Tri-state, and the third value carries meaning: None is "no acknowledgment
  #: was owed", which is the BEST_EFFORT case, and must never render as a reader
  #: that failed to acknowledge.
  acknowledged: object = None


def verdict_line(findings, probe=None):
  """One-line summary opening every report. Derived only from observed state.

  A probe that failed part-way through still has real observations, but it must
  not present them as a finished measurement - so the incompleteness is appended
  rather than allowed to leave "payload FULL" standing on its own.
  """
  probe = probe or ProbeOutcome()
  line = _verdict_body(findings, probe)
  if probe.incomplete_reason:
    line += f"; probe did not complete: {probe.incomplete_reason}"
  return line


def _verdict_body(findings, probe):
  if not probe.attempted:
    reason = probe.skip_reason or "probe not run"
    worst = max((f.severity for f in findings), default=Severity.OK)
    if worst >= Severity.ERROR:
      return f"not probed ({reason}); {_problem_summary(findings)}"
    return f"not probed ({reason})"

  if not probe.matched:
    return f"NOT MATCHED; {_problem_summary(findings)}"

  # A writer probe against a reader target. "No samples received" is meaningless
  # here - the probe is the sending side, and unless it was asked to publish it
  # sent nothing by design. Reporting the match, which is what was measured.
  if probe.wrote_entity and not probe.wrote_samples:
    tail = _problem_summary(findings)
    base = "matched (writer probe; nothing published, so delivery not measured)"
    return f"{base}; {tail}" if tail else base

  # A writer probe that DID publish. Its evidence is acknowledgment, not a
  # payload walk: it serialized the sample itself, so "payload FULL" would be
  # this tool reading back its own bytes and calling that a finding. Falling
  # through to the payload branches reported "payload NOT ATTEMPTED", which
  # reads as a step that failed rather than one that never applied.
  if probe.wrote_entity:
    tail = _problem_summary(findings)
    delivery = {True: "acknowledged by the reader",
                False: "NOT acknowledged",
                None: "acknowledgment not applicable (BEST_EFFORT)"}[
                    probe.acknowledged]
    base = f"matched, {probe.samples_received} sample(s) published, {delivery}"
    return f"{base}; {tail}" if tail else base

  if probe.samples_received == 0:
    return f"matched but no samples received; {_problem_summary(findings)}"

  if probe.payload_verdict == PAYLOAD_FULL:
    tail = _problem_summary(findings)
    base = f"matched, {probe.samples_received} sample(s) received, payload FULL"
    return f"{base}; {tail}" if tail else base

  if probe.payload_verdict == PAYLOAD_PARTIAL:
    if probe.members_unreadable:
      return (
          f"matched, samples arriving, payload PARTIAL "
          f"({probe.members_unreadable} of {probe.members_total} members unreadable)"
      )
    # No member failed, but the walk hit rti_doctor's own caps, so the sample
    # was not read to the end. Calling that FULL would be a completeness claim
    # about members the tool never visited.
    return (
        f"matched, samples arriving, payload PARTIAL (walk truncated at "
        f"rti_doctor's own caps after {probe.members_total} member(s); no "
        f"member that was read failed)"
    )

  return f"matched, samples arriving, payload {probe.payload_verdict}"


def _problem_summary(findings):
  hist = counts(findings)
  parts = []
  for sev in (Severity.ERROR, Severity.WARN):
    if hist.get(sev):
      parts.append(f"{hist[sev]} {sev.label}")
  return ", ".join(parts)
