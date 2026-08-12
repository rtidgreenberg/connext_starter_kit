"""rti_doctor CLI: interactive TUI by default, headless with --system/--topic."""

import argparse
import logging
import os
import sys
import time

from . import compat, discovery, domain_scan, engine, paths, records, report, wire

DEFAULT_SCAN_TIMEOUT = 32.0
DEFAULT_PROBE_TIMEOUT = 10.0
DEFAULT_TYPE_WAIT = 5.0
#: How long to let discovery settle before running headless checks.
DEFAULT_DISCOVERY_SETTLE = 3.0

#: The process exit contract. `1` means one thing only - a diagnosis ran to
#: completion and reported an ERROR-severity finding - because a CI job reading
#: `1` acts on the findings. A startup failure used to reach the shell as `1`
#: too, by way of an uncaught traceback, so "Doctor could not run" and "your
#: system has an error" were indistinguishable to the one consumer that cannot
#: read the message.
#:
#: `2` means the requested target was absent and nothing else. argparse's own
#: default for a rejected command line is also `2`, so until 2026-08-12 a CI job
#: acting on `2` read a mistyped flag as "topic not found" - a clean result from
#: a run that never started. `_Parser` below sends that case to
#: `EXIT_CANNOT_START` instead (L6).
EXIT_OK = 0
EXIT_ERROR_FINDINGS = 1
EXIT_TARGET_ABSENT = 2
EXIT_READINESS_TIMEOUT = 3
EXIT_CANNOT_START = 4
EXIT_INTERRUPTED = 130
CONNEXT_VERBOSITIES = {
  "silent": "SILENT",
  "exception": "EXCEPTION",
  "warning": "WARNING",
  "status-local": "STATUS_LOCAL",
  "status-remote": "STATUS_REMOTE",
  "status-all": "STATUS_ALL",
}


def configure_logging(debug_log_path=None):
  """Attach a file handler for discovery/probe diagnostics when asked."""
  if not debug_log_path:
    logging.getLogger().setLevel(logging.WARNING)
    return
  root_logger = logging.getLogger()
  normalized_path = os.path.abspath(debug_log_path)
  for handler in root_logger.handlers:
    if getattr(handler, "_rti_doctor_log_path", None) == normalized_path:
      return
  directory = os.path.dirname(normalized_path)
  if directory:
    os.makedirs(directory, exist_ok=True)
  file_handler = logging.FileHandler(normalized_path, encoding="utf-8")
  file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
  file_handler._rti_doctor_log_path = normalized_path
  root_logger.addHandler(file_handler)
  root_logger.setLevel(logging.INFO)


def configure_connext_logging(log_path=None, verbosity="silent"):
  """Configure Connext's native logger before Doctor creates DDS entities."""
  import rti.connextdds as dds

  verbosity_name = CONNEXT_VERBOSITIES[verbosity]
  logger = dds.Logger.instance
  logger.verbosity = getattr(dds.Verbosity, verbosity_name)
  settings = {"connext_verbosity": verbosity}
  if log_path:
    path = os.path.abspath(log_path)
    directory = os.path.dirname(path)
    if directory:
      os.makedirs(directory, exist_ok=True)
    logger.output_file(path)
    logger.informational("RTI Doctor native Connext logging enabled")
    settings["connext_log_file"] = path
  else:
    settings["connext_log_file"] = "stderr (Connext default)"
  return settings


class _Parser(argparse.ArgumentParser):
  """An ArgumentParser that does not collide with `EXIT_TARGET_ABSENT`.

  argparse exits `2` on a rejected command line, which is also Doctor's code for
  "the topic was not found" - so a CI job scripting on `2` read a mistyped flag
  as a clean "topic absent" result, and nothing but the stderr text told the two
  apart (L6). A rejected command line is a reason Doctor could not run, so it
  reports `EXIT_CANNOT_START` and joins the other startup failures.

  `EXIT_TARGET_ABSENT` keeps `2` rather than moving: it is the documented
  contract a CI job is most likely to already depend on, and this is the side of
  the collision nobody has scripted against on purpose.
  """

  def error(self, message):
    self.print_usage(sys.stderr)
    self.exit(EXIT_CANNOT_START, f"{self.prog}: error: {message}\n")


def parse_args(argv=None):
  parser = _Parser(
      prog="rti_doctor",
      description="Diagnose DDS interoperability problems between RTI Connext and "
                  "other DDS vendors.")
  parser.add_argument("-d", "--domain", type=int, default=None,
                      help="DDS domain ID (prompts on startup; defaults to 1 when "
                           "non-interactive)")
  parser.add_argument("-t", "--topic", default=None,
                      help="Headless: diagnose one topic and exit")
  parser.add_argument("--system", action="store_true",
                      help="Headless: assess the DDS system - discovery, topology "
                           "and local configuration - and exit")
  parser.add_argument("-o", "--output", default=None,
                      help="Write the report to PATH instead of stdout")
  parser.add_argument("--probe-timeout", type=float, default=DEFAULT_PROBE_TIMEOUT,
                      help=f"Seconds to observe a probed reader "
                           f"(default: {DEFAULT_PROBE_TIMEOUT})")
  parser.add_argument("--type-wait", type=float, default=DEFAULT_TYPE_WAIT,
                      help=f"Seconds to wait for remote type resolution before "
                           f"reporting it unavailable (default: {DEFAULT_TYPE_WAIT})")
  parser.add_argument("--settle", type=float, default=DEFAULT_DISCOVERY_SETTLE,
                      help=f"Seconds to let discovery settle before headless checks "
                           f"(default: {DEFAULT_DISCOVERY_SETTLE})")
  parser.add_argument("--scan-timeout", type=float, default=DEFAULT_SCAN_TIMEOUT,
                      help=f"Seconds to listen for active domains before prompting "
                           f"(default: {DEFAULT_SCAN_TIMEOUT}, just over the 30s "
                           f"default announcement period)")
  parser.add_argument("--no-domain-scan", action="store_true",
                      help="Skip scanning for active domains before prompting")
  parser.add_argument("--no-probe", action="store_true",
                      help="Static checks only; never create a reader")
  parser.add_argument("--type-object-v1-only", action="store_true",
                      help="Advertise inline TypeObject v1 and disable TypeLookup v2 "
                           "for an interoperability experiment")
  packet_group = parser.add_mutually_exclusive_group()
  packet_group.add_argument("--pcap", default=None,
                            help="Analyze RTPS user-data packets in an existing PCAP/PCAPNG")
  packet_group.add_argument("--capture-interface", default=None,
                            help="Interface for packet capture: captured while probing "
                                 "with --topic. In the TUI it answers the capture "
                                 "question up front, so every endpoint report captures "
                                 "on entry without asking (no default: the TUI asks, "
                                 "and Skip is an answer)")
  parser.add_argument("-i", "--interval", type=float, default=2.0,
                      help="UI refresh interval in seconds (default: 2.0)")
  parser.add_argument("--debug-log", default=os.environ.get("RTI_DOCTOR_DEBUG_LOG"),
                      help="Optional path for discovery/probe log output")
  parser.add_argument("--connext-log", default=None,
                      help="Write native Connext middleware diagnostics to PATH")
  parser.add_argument("--connext-verbosity", choices=tuple(CONNEXT_VERBOSITIES),
                      default="silent", help="Native Connext log verbosity "
                      "(default: silent; applies to --connext-log or stderr)")
  parser.add_argument("--ready-file", default=None,
                      help="Write PATH after Doctor creates its DDS participant")
  parser.add_argument("--ready-after-participants", type=int, default=0,
                      help="Test hook: wait for this many remote participants before "
                      "writing --ready-file")
  parser.add_argument("--ready-timeout", type=float, default=15.0,
                      help="Seconds to wait for --ready-after-participants (default: 15)")

  args = parser.parse_args(argv)
  if args.topic and args.system:
    parser.error("--topic and --system are mutually exclusive")
  if args.pcap and not args.topic:
    parser.error("--pcap requires --topic")
  # --capture-interface no longer implies --topic: it is also how the TUI's
  # explicit capture action is pointed at an interface other than "any". It
  # still has no meaning for the passive system assessment, which creates no
  # DDS entities and captures nothing.
  if args.capture_interface and args.system:
    parser.error("--capture-interface is not used by --system; capture during "
                 "a --topic diagnosis, or from an endpoint report in the TUI")
  if args.ready_after_participants < 0 or args.ready_timeout <= 0:
    parser.error("--ready-after-participants must be non-negative and --ready-timeout positive")
  # argparse's type=int/float accepts negatives, and float() accepts "nan" and
  # "inf". A negative probe timeout makes the probe window close before it
  # opens, and a negative domain ID fails deep inside Connext with an error
  # that says nothing about the argument that caused it.
  if args.domain is not None and args.domain < 0:
    parser.error("--domain must be a non-negative integer")
  for name in ("probe_timeout", "type_wait", "settle", "scan_timeout", "interval"):
    value = getattr(args, name)
    flag = "--" + name.replace("_", "-")
    if value != value or value in (float("inf"), float("-inf")):
      parser.error(f"{flag} must be a finite number")
    if value < 0:
      parser.error(f"{flag} must not be negative")
  if args.interval <= 0:
    parser.error("--interval must be greater than zero")
  return args


def is_headless(args):
  """Whether this invocation runs a report and exits rather than the TUI.

  `--system` and `--topic` are the two explicit stages; a non-tty stdin means
  nobody is there to drive the TUI. Without an explicit stage flag a user at a
  shell has no way to ask for stage one, since a tty would always win.
  """
  return bool(args.topic) or bool(args.system) or not sys.stdin.isatty()


def resolve_domain_id(domain_arg, scan_timeout=DEFAULT_SCAN_TIMEOUT, do_scan=True):
  """Same prompt behavior as rti_spy, so the two tools start up alike."""
  if domain_arg is not None:
    return domain_arg, set(), False

  if not sys.stdin.isatty():
    return 1, set(), False

  default_domain = 1
  discovered = set()
  scanned = False

  if do_scan:
    while True:
      try:
        response = input(
            "Enter domain ID to inspect, or press Enter to listen for active domains: "
        ).strip()
      except EOFError:
        return default_domain, discovered, scanned
      except KeyboardInterrupt:
        print()
        raise

      if not response:
        break
      try:
        domain_id = int(response)
      except ValueError:
        print("Please enter an integer domain ID, or press Enter to listen for "
              "active domains.", file=sys.stderr)
        continue
      if domain_id < 0:
        print("Please enter a non-negative domain ID.", file=sys.stderr)
        continue
      return domain_id, discovered, scanned

    print(f"Listening for active DDS domains (up to {scan_timeout:.0f}s, via default "
          f"domain announcements)...")
    print("(Remote apps only re-announce every ~30s, so this can take that long to "
          "find ones already running.)")

    last_shown = {"second": -1, "line_len": 0}

    def _show_scan_progress(elapsed, total, domains_so_far):
      second = int(elapsed)
      if second == last_shown["second"]:
        return
      last_shown["second"] = second
      found = ", ".join(str(d) for d in sorted(domains_so_far)) if domains_so_far else "none yet"
      line = f"  listening... {second}s / {int(total)}s (found: {found})"
      padded = line.ljust(last_shown["line_len"])
      last_shown["line_len"] = len(line)
      print(f"\r{padded}", end="", flush=True)

    discovered = domain_scan.scan_active_domains(
        timeout=scan_timeout, progress_callback=_show_scan_progress)
    scanned = True
    print()
    if discovered:
      ordered = sorted(discovered)
      default_domain = ordered[0]
      print("Active domains detected: " + ", ".join(str(d) for d in ordered))
    else:
      print("No active domains detected (none seen, or remote apps have default "
            "domain announcements disabled).")

  while True:
    try:
      response = input(f"Enter domain ID to inspect [{default_domain}]: ").strip()
    except EOFError:
      return default_domain, discovered, scanned
    except KeyboardInterrupt:
      print()
      raise
    if not response:
      return default_domain, discovered, scanned
    try:
      domain_id = int(response)
    except ValueError:
      print("Please enter an integer domain ID.", file=sys.stderr)
      continue
    if domain_id < 0:
      print("Please enter a non-negative domain ID.", file=sys.stderr)
      continue
    return domain_id, discovered, scanned


def build_session(domain_id, args, active_domains=None, domain_scan_ran=False,
                  compliance=None):
  """Create the diagnostic participant and wrap it in a Session."""
  import rti.connextdds as dds

  registry = discovery.DiscoveryRegistry(type_wait=args.type_wait)
  participant, type_lookup_settings = discovery.create_participant(
      domain_id, name="RTI DOCTOR", registry=registry,
      type_object_v1_only=args.type_object_v1_only)

  # Record the QoS we actually used, so the blind-spot audit inspects reality
  # rather than a freshly-defaulted object.
  own_qos = participant.qos if hasattr(participant, "qos") else dds.DomainParticipantQos()

  settings = dict(type_lookup_settings)
  if compliance is not None:
    settings["xtypes_compliance_mask"] = (
        f"{compat.xtypes_mask_text()} "
        f"({'VENDOR applied' if compliance.get('applied') else compliance.get('note', 'not applied')})")
  type_lookup_settings = settings

  return engine.Session(
      participant=participant,
      registry=registry,
      own_qos=own_qos,
      type_lookup_settings=type_lookup_settings,
      domain_id=domain_id,
      type_wait=args.type_wait,
      probe_timeout=args.probe_timeout,
      active_domains=active_domains or set(),
      domain_scan_ran=domain_scan_ran,
      capture_interface=args.capture_interface,
  ), participant


def _settle(session, seconds):
  """Let discovery arrive before judging it."""
  deadline = time.monotonic() + max(0.0, seconds)
  while time.monotonic() < deadline:
    discovery.refresh_participants(session.participant, session.registry)
    time.sleep(0.25)
  discovery.refresh_participants(session.participant, session.registry)


def _emit(text, output_path):
  if not output_path:
    sys.stdout.write(text)
    return None
  path = os.path.abspath(output_path)
  directory = os.path.dirname(path)
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8") as handle:
    handle.write(text)
  return path


def _write_ready_file(path):
  """Signal that Doctor has joined the domain for an external test fixture."""
  if not path:
    return
  normalized_path = os.path.abspath(path)
  directory = os.path.dirname(normalized_path)
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(normalized_path, "w", encoding="utf-8") as handle:
    handle.write("ready\n")


def _wait_for_remote_participants(session, count, timeout):
  """Wait for a bounded number of peers before a test fixture creates endpoints."""
  if count == 0:
    return True
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    discovery.refresh_participants(session.participant, session.registry)
    if len(session.registry.participant_list()) >= count:
      return True
    time.sleep(0.05)
  return False


def run_headless_topic(session, args):
  """Diagnose one topic and emit a report. Returns a process exit code."""
  from . import findings as f

  _settle(session, args.settle)

  # Wait for the writer to appear AND for its type-wait window to elapse. Both
  # matter: breaking out as soon as the endpoint is discovered would run the
  # rung-3 check while type_state is still PENDING, so a type that simply had not
  # arrived yet would be reported as merely "in flight" instead of resolved or
  # unavailable, making the headless verdict depend on timing.
  deadline = time.monotonic() + args.type_wait + args.settle
  while time.monotonic() < deadline:
    endpoint = session.registry.find_writer(args.topic)
    if endpoint is not None and endpoint.type is not None:
      break
    session.registry.expire_type_waits()
    if endpoint is not None and endpoint.type_state != records.TYPE_PENDING:
      break
    time.sleep(0.2)

  session.registry.expire_type_waits()
  endpoint = session.registry.find_writer(args.topic)
  if endpoint is None:
    topics = session.registry.topic_names()
    print(f"No writer found on topic '{args.topic}' in domain {session.domain_id}.",
          file=sys.stderr)
    if topics:
      print("Discovered topics: " + ", ".join(topics), file=sys.stderr)
    else:
      print("No topics were discovered at all. Run with --system instead of "
            "--topic for the system assessment.", file=sys.stderr)
    return EXIT_TARGET_ABSENT

  # The capture is the engine's, not a second one built here: one code path
  # decides where a capture writes, how long it may run and how its file is
  # read, so the CLI and the TUI cannot drift into capturing differently.
  if args.capture_interface:
    print(f"Capturing RTPS packets on interface '{args.capture_interface}' while "
          f"diagnosing '{args.topic}'.", file=sys.stderr)
  data = session.diagnose_endpoint(endpoint, probe=not args.no_probe,
                                   capture_interface=args.capture_interface)
  if args.pcap:
    data.wire_evidence = wire.inspect_pcap(
        args.pcap, writer_entity_id=wire.endpoint_entity_id(endpoint),
        writer_guid_prefix=wire.endpoint_guid_prefix(endpoint))
  path = _emit(report.render_text(data), args.output)
  if path:
    print(f"Report written to {path}")
    print(f"VERDICT: {data.verdict}")

  worst = max((x.severity for x in data.findings), default=f.Severity.OK)
  return EXIT_ERROR_FINDINGS if worst >= f.Severity.ERROR else EXIT_OK


def run_headless_system(session, args):
  """Stage one: assess the DDS system as a whole and exit.

  The rung-0/1 blind-spot audit that leaves no row to click on, plus the
  system-wide discovery, type and RxO census over everything discovered. It
  creates no reader and probes nothing, so it stays cheap no matter how large
  the system is - unlike diagnosing an endpoint, which is the separate,
  explicitly targeted stage two.

  This is the TUI's scan minus the packet-capture evidence: a capture needs an
  interface, and choosing one is an interactive prompt.
  """
  from . import findings as f

  # Type resolution is asynchronous: expire_type_waits only reclassifies a
  # pending type once --type-wait has elapsed, so scanning before then reports
  # "still in flight" for a type that never arrives, and exits 0. Both waits go
  # through _settle rather than time.sleep, because a participant announcing
  # during the wait is only recorded by polling for it - sleeping through it
  # produced a report with live endpoints under zero participants.
  _settle(session, args.settle)
  _settle(session, args.type_wait)
  snapshot = session.system_scan()
  text = report.render_system_text(
      snapshot, session.domain_id,
      type_lookup_settings=session.type_lookup_settings)
  path = _emit(text, args.output)
  if path:
    print(f"System report written to {path}")
  worst = max((issue.severity for issue in snapshot.issues), default=f.Severity.OK)
  return EXIT_ERROR_FINDINGS if worst >= f.Severity.ERROR else EXIT_OK


def _cannot_start(stage, error):
  """Report an operational failure on one line and return its exit code.

  A traceback is the wrong output for "no license", "domain 500 is out of
  range" or "the participant could not be created": it buries the one sentence
  that matters and, because CPython exits 1 on an uncaught exception, it makes
  a Doctor that never ran indistinguishable from a system Doctor found errors
  in. The traceback still reaches --debug-log, which is where an unexpected
  failure is actually diagnosed.
  """
  logging.exception("[main] %s failed", stage)
  print(f"rti_doctor could not {stage}: {error.__class__.__name__}: {error}",
        file=sys.stderr)
  print("Run with --debug-log PATH for the full traceback.", file=sys.stderr)
  return EXIT_CANNOT_START


def main(argv=None):
  args = parse_args(argv)
  configure_logging(args.debug_log)

  headless = is_headless(args)
  try:
    compat.configure_rti_environment()

    # Native Connext diagnostics include middleware parsing failures that cannot
    # be observed through Python's logging module. Configure them before the
    # first DDS entity is created so discovery startup is captured as well.
    connext_logging = configure_connext_logging(
        args.connext_log, args.connext_verbosity)

    # Before ANY DDS entity exists: Connext's default XTypes compliance mask is not
    # fully OMG-compliant, and RTI's cross-vendor guidance is to use the VENDOR
    # mask. A diagnostic must not fail to decode a peer because of its own encoding
    # defaults. What was actually applied is recorded in every report.
    compliance = compat.set_vendor_xtypes_mask()

    domain_id, active_domains, scanned = resolve_domain_id(
        args.domain,
        scan_timeout=args.scan_timeout,
        do_scan=not args.no_domain_scan)

    session, participant = build_session(
        domain_id, args, active_domains=active_domains, domain_scan_ran=scanned,
        compliance=compliance)
  except Exception as error:  # noqa: BLE001 - reported, not swallowed
    return _cannot_start("start", error)

  # Everything from here on is inside the ownership boundary. The readiness wait
  # and the ready file used to run before the `try`, so anything raising in them
  # left the participant open - and the widest window was the one nobody sees:
  # a Ctrl-C during the wait for `--ready-timeout` unwound straight past this
  # block. The duplicated cleanup that used to sit on the readiness return path
  # is gone with it, because that path now leaves through the same `finally` as
  # every other.
  # Set once the TUI owns the session, so the capture sweep in `finally` knows
  # whether there was a TUI session to sweep after. A plain flag rather than
  # "did it write any artifacts": headless `--topic --capture-interface` writes
  # one too, and that operator asked for it on the command line.
  tui_ran = False
  try:
    session.type_lookup_settings.update(connext_logging)
    if not _wait_for_remote_participants(
        session, args.ready_after_participants, args.ready_timeout):
      print("Doctor did not observe the requested remote participant count before "
            "the readiness timeout.", file=sys.stderr)
      return EXIT_READINESS_TIMEOUT
    _write_ready_file(args.ready_file)

    if args.topic:
      return run_headless_topic(session, args)
    if headless:
      return run_headless_system(session, args)

    from .app import RTIDoctorApp
    _settle(session, min(args.settle, 1.0))
    tui_ran = True
    RTIDoctorApp(session, interval=args.interval).run()
    return EXIT_OK
  except Exception as error:  # noqa: BLE001 - reported, not swallowed
    # An assessment that died is not an assessment that found errors, so this
    # cannot be allowed to reach the shell as the finding-error exit code.
    return _cannot_start("complete this run", error)
  finally:
    # In the `finally`, not on the success path: a TUI that raised is exactly
    # the run whose captures nobody will look at, and leaving them behind is
    # the leak CAP-1 exists to close.
    if tui_ran:
      _sweep_captures(session)
    _close_participant(participant)


def _sweep_captures(session):
  """Remove the TUI session's unsaved captures on the way out (CAP-1).

  The TUI now offers a capture on entry to every endpoint report, so a session
  spent browsing leaves one PCAPNG and one tshark log per report opened, and
  nothing removed them (N2). A saved report cites its capture in Appendix C and
  keeps it; everything else was scaffolding for a report that is already gone.

  TUI only. A headless `--capture-interface` run named the interface on the
  command line and wants the file it asked for.
  """
  removed = session.sweep_capture_artifacts()
  if removed:
    print(f"Removed {len(removed)} unsaved capture artifact(s) from "
          f"{paths.test_output_path('rti_doctor_captures')}. "
          f"Set RTI_DOCTOR_KEEP_ARTIFACTS=1 to keep them, or save a report "
          f"with 's' to keep the capture it cites.")


def _close_participant(participant):
  """Release the one resource main() owns.

  It used to own two: the participant and a startup packet capture that ran for
  the whole session. The capture is gone (nothing captures without being asked
  now), so the ordering that put the failure-prone cleanup first has nothing
  left to order - but the guard stays, because a close that raises must not
  escape a `finally` and replace the run's real exit code.
  """
  try:
    participant.close()
  except Exception as e:
    logging.error(f"[main] error closing participant: {e}")


if __name__ == "__main__":
  try:
    sys.exit(main())
  except KeyboardInterrupt:
    print("Aborted.")
    sys.exit(EXIT_INTERRUPTED)
