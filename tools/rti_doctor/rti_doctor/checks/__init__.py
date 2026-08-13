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


def run_checks(context, checks):
  """Run `checks` in order, collecting findings.

  A check that raises is reported as an INFO finding rather than aborting the
  run: a broken check must not cost the user every other diagnosis.
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
      ))
      continue
    if result:
      out.extend(result)
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
  """
  from . import blind_spots, qos_match, static_discovery, type_compat
  return (
      blind_spots.CHECKS
      + static_discovery.CHECKS
      + type_compat.CHECKS
      + qos_match.CHECKS
  )


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
  return static_checks() + probe_checks()
