"""Finding model, severity ordering, causal suppression, and verdict rollup.

A Finding is the single output currency of rti_doctor: every check returns a list
of them, and every renderer consumes them. Findings carry a `rung` from the
visibility ladder (see IMPLEMENTATION_PLAN.md), which drives both ordering and
suppression: a rung-2 locator problem causally explains a rung-4 match failure,
so reporting them as peers would be noise.
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
  # Set by suppress(): the id of the lower-rung finding that explains this one.
  suppressed_by: str = None

  @property
  def is_problem(self):
    return self.severity >= Severity.WARN


# A finding id maps to the set of ids that, if present, causally explain it.
# Only ERROR-severity explainers suppress, because a warning is not proof that
# the higher-rung symptom has been accounted for.
SUPPRESSION_RULES = {
    "match.none": (
        "blind.domain_tag",
        "blind.spdp2",
        "blind.security_enabled",
        "blind.no_multicast_no_peers",
        "blind.unknown_peers_rejected",
        "locator.unroutable",
        "transport.class_mismatch",
        "security.mismatch",
        "type.no_type_info",
        "match.incompatible_qos",
        "repr.no_common",
    ),
    # A reader that could not be created is explained entirely by the missing
    # type; reporting both as peers would imply two independent problems.
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


def suppress(findings):
  """Mark findings that a lower-rung ERROR finding causally explains.

  Suppressed findings are never dropped - renderers list them by id under a
  SUPPRESSED heading so nothing vanishes without a trace.
  """
  fatal_ids = {f.id for f in findings if f.severity >= Severity.ERROR}
  for finding in findings:
    for explainer in SUPPRESSION_RULES.get(finding.id, ()):  # deterministic order
      if explainer in fatal_ids and explainer != finding.id:
        finding.suppressed_by = explainer
        break
  return findings


def rank(findings):
  """Sort by severity descending, then rung ascending, then id for stability."""
  return sorted(findings, key=lambda f: (-int(f.severity), f.rung, f.id))


def active(findings):
  return [f for f in findings if f.suppressed_by is None]


def suppressed(findings):
  return [f for f in findings if f.suppressed_by is not None]


def counts(findings):
  """Severity histogram over active findings, worst first."""
  out = {}
  for finding in active(findings):
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


def verdict_line(findings, probe=None):
  """One-line summary opening every report. Derived only from observed state."""
  probe = probe or ProbeOutcome()

  if not probe.attempted:
    reason = probe.skip_reason or "probe not run"
    worst = max((f.severity for f in active(findings)), default=Severity.OK)
    if worst >= Severity.ERROR:
      return f"not probed ({reason}); {_problem_summary(findings)}"
    return f"not probed ({reason})"

  if not probe.matched:
    return f"NOT MATCHED; {_problem_summary(findings)}"

  if probe.samples_received == 0:
    return f"matched but no samples received; {_problem_summary(findings)}"

  if probe.payload_verdict == PAYLOAD_FULL:
    tail = _problem_summary(findings)
    base = f"matched, {probe.samples_received} sample(s) received, payload FULL"
    return f"{base}; {tail}" if tail else base

  if probe.payload_verdict == PAYLOAD_PARTIAL:
    return (
        f"matched, samples arriving, payload PARTIAL "
        f"({probe.members_unreadable} of {probe.members_total} members unreadable)"
    )

  return f"matched, samples arriving, payload {probe.payload_verdict}"


def _problem_summary(findings):
  hist = counts(findings)
  parts = []
  for sev in (Severity.ERROR, Severity.WARN):
    if hist.get(sev):
      parts.append(f"{hist[sev]} {sev.label}")
  return ", ".join(parts)
