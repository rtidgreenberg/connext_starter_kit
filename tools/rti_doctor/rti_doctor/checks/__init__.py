"""Check registry and runner.

A check is a function taking a CheckContext and returning a list of Findings.
Keeping them as plain functions over a plain context is what makes the whole
catalog unit-testable with fake discovery records and no live DDS.
"""

from dataclasses import dataclass, field

from .. import findings as f


@dataclass
class CheckContext:
  """Everything a check may look at.

  Not every check needs every field; a check must tolerate the ones it does not
  get (headless single-topic runs have no `participant_record`, for example).
  """

  registry: object = None
  #: Our own DomainParticipantQos, for the blind-spot audit.
  own_qos: object = None
  #: What configure_type_lookup_qos() actually applied.
  type_lookup_settings: dict = field(default_factory=dict)
  #: Domain we are inspecting.
  domain_id: int = None
  #: Domains seen announcing, from the passive scan (may be empty/unscanned).
  active_domains: set = field(default_factory=set)
  domain_scan_ran: bool = False
  #: Focus of this run.
  endpoint: object = None
  participant_record: object = None
  #: Live probe result, when one was run.
  probe: object = None
  #: Selected endpoint's participant advertised PID_TYPE_INFORMATION in capture.
  #: `None` when no capture looked, which is not the same claim as `False` and
  #: is the common case: a passively opened report, a `Skip`, or a headless run
  #: without `--capture-interface`. Both are falsy, so a check that only gates
  #: on it needs no change.
  type_information_observed: object = None
  type_wait: float = 5.0
  #: Packet counts from an operator-requested capture, or None when none ran.
  #: The reliable-path check reads it because the RTPS handshake is observable
  #: from packets even when the peer's own counters are not reachable - which is
  #: every non-RTI peer, and any Connext build whose bindings do not expose them.
  wire_evidence: object = None
  #: Packet counts from RTI Network Capture of rti_doctor's own participant.
  #: Scoped to us rather than to an interface, and therefore the only packet
  #: evidence that exists when the pair is talking over shared memory.
  participant_evidence: object = None


def run_checks(context, checks, scope=f.SCOPE_OBSERVED):
  """Run `checks` in order, collecting findings, every one stamped with `scope`.

  Stamped here rather than at each `Finding(...)` because scope is a property of
  the CATALOG a check belongs to, not of the condition it found: everything in
  `probe_checks()` reads `context.probe` and everything in `static_checks()`
  reads discovery data, so a check has no way to be wrong about this and no
  reason to repeat it fifty times. The default is the observed system, which is
  what every caller but the probe pass produces.

  A check that raises is reported as an INFO finding rather than aborting the
  run: a broken check must not cost the user every other diagnosis. That one is
  scoped to the tool, not to whichever catalog it came from - it is a bug here,
  and filing it under the system under test would be a claim about the system.
  """
  out = []
  for check in checks:
    try:
      result = check(context)
    except Exception as e:  # noqa: BLE001 - isolate check failures
      out.append(f.Finding(
          id="internal.check_failed",
          rung=f.RUNG_OWN_CONFIG,
          severity=f.Severity.INFO,
          title=f"Check '{getattr(check, '__name__', check)}' failed to run",
          observed=f"{type(e).__name__}: {e}",
          root_cause="Bug in rti_doctor, not a finding about the system under test.",
          remedy="Report this with the surrounding report output.",
          scope=f.SCOPE_TOOL,
      ))
      continue
    for finding in result or ():
      finding.scope = scope
      out.append(finding)
  return out


def type_state_checks():
  """Just the type-resolution state check, for per-participant rollups."""
  from . import type_compat
  return (type_compat.check_type_state,)


def static_checks():
  """Checks that need only discovery data - no reader created.

  Includes the RxO comparison between discovered writers and discovered readers:
  rti_doctor observes a running system, so both sides' QoS come from discovery
  and no reader has to be created to compare them.

  Excludes `blind_spots.OWN_CONFIG_CHECKS`, which read rti_doctor's own QoS - see
  `own_config_checks`. Everything left here reads the system.
  """
  from . import blind_spots, qos_match, static_discovery, type_compat
  return (
      blind_spots.DOMAIN_CHECKS
      + static_discovery.CHECKS
      + type_compat.CHECKS
      + qos_match.CHECKS
  )


def own_config_checks():
  """Checks that read rti_doctor's own participant QoS, not the system.

  Their own catalog because `run_checks` stamps scope per catalog: run with the
  static checks they were stamped SCOPE_OBSERVED, which put "a domain tag is set
  on this participant" under a heading promising nothing there depends on
  rti_doctor's own configuration.
  """
  from . import blind_spots
  return blind_spots.OWN_CONFIG_CHECKS


def probe_checks():
  """Checks that read live probe results."""
  from . import probe_match, probe_payload, reliable_path
  return probe_match.CHECKS + probe_payload.CHECKS + reliable_path.CHECKS


def writer_probe_checks():
  """Checks for a READER target, where the probe created a writer.

  The payload checks are deliberately absent: they read reader-side statuses and
  a delivered sample walk, neither of which exists when the probe is the sending
  side. The reliable-path check handles both directions itself.
  """
  from . import probe_match, reliable_path
  return probe_match.CHECKS + reliable_path.CHECKS


def all_checks():
  return own_config_checks() + static_checks() + probe_checks()
