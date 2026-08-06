"""rti_doctor CLI: interactive TUI by default, headless with --topic/--all."""

import argparse
import logging
import os
import sys
import time

from . import (compat, discovery, domain_scan, engine, records, report,
               topology, wire)

DEFAULT_SCAN_TIMEOUT = 32.0
DEFAULT_PROBE_TIMEOUT = 10.0
DEFAULT_TYPE_WAIT = 5.0
#: How long to let discovery settle before running headless checks.
DEFAULT_DISCOVERY_SETTLE = 3.0
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


def parse_args(argv=None):
  parser = argparse.ArgumentParser(
      prog="rti_doctor",
      description="Diagnose DDS interoperability problems between RTI Connext and "
                  "other DDS vendors.")
  parser.add_argument("-d", "--domain", type=int, default=None,
                      help="DDS domain ID (prompts on startup; defaults to 1 when "
                           "non-interactive)")
  parser.add_argument("-t", "--topic", default=None,
                      help="Headless: diagnose one topic and exit")
  parser.add_argument("--all", action="store_true",
                      help="Headless: diagnose every discovered writer and exit")
  parser.add_argument("--format", dest="format", choices=("text", "json"),
                      default="text", help="Headless output format (default: text)")
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
                            help="Capture UDP packets with tshark while probing one topic")
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
  if args.topic and args.all:
    parser.error("--topic and --all are mutually exclusive")
  if (args.pcap or args.capture_interface) and not args.topic:
    parser.error("--pcap and --capture-interface require --topic")
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
      print("No topics were discovered at all. Run without --topic to see the "
            "blind-spot audit.", file=sys.stderr)
    return 2

  capture = None
  if args.capture_interface:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    capture_path = os.path.join(
        "test_output", "rti_doctor_captures",
        f"rti_doctor_domain{session.domain_id}_{timestamp}.pcapng")
    capture = wire.LiveCapture(
      args.capture_interface, capture_path,
      wire.capture_filter(session.domain_id, endpoint, session.own_qos),
      writer_entity_id=wire.endpoint_entity_id(endpoint),
      writer_guid_prefix=wire.endpoint_guid_prefix(endpoint))

  # start() spawns tshark and blocks a second waiting for it to come up, so it
  # belongs inside the try: a Ctrl-C in that window would otherwise leave the
  # capture process running with nothing left to reap it.
  try:
    if capture is not None:
      capture.start()
    data = session.diagnose_endpoint(endpoint, probe=not args.no_probe)
  finally:
    wire_evidence = capture.finish() if capture is not None else None
  if args.pcap:
    wire_evidence = wire.inspect_pcap(
        args.pcap, writer_entity_id=wire.endpoint_entity_id(endpoint),
        writer_guid_prefix=wire.endpoint_guid_prefix(endpoint))
  data.wire_evidence = wire_evidence
  text = (report.render_json(data) if args.format == "json"
          else report.render_text(data))
  path = _emit(text, args.output)
  if path:
    print(f"Report written to {path}")
    print(f"VERDICT: {data.verdict}")

  worst = max((x.severity for x in f.active(data.findings)), default=f.Severity.OK)
  return 1 if worst >= f.Severity.ERROR else 0


def run_headless_all(session, args):
  """Sweep every writer and emit a summary. Returns a process exit code."""
  _settle(session, args.settle)
  time.sleep(max(0.0, args.type_wait))
  session.registry.expire_type_waits()

  rows, _ = session.sweep(probe=not args.no_probe)
  topology_data = topology.snapshot(
      session.registry, session.domain_id, session.active_domains,
      session.domain_scan_ran)
  if args.format == "json":
    import json
    payload = {
        "unstable_schema": True,
        "domain_id": session.domain_id,
        "environment": compat.environment_info(),
        "topology": topology_data,
        "writers": [
            {"topic": row["topic"], "vendor": row["vendor"],
             "severity": row["severity"], "verdict": row["verdict"],
             "findings": [{"id": i, "severity": s, "title": t}
                          for i, s, t in row["findings"]]}
            for row in rows
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
  else:
    text = report.render_sweep_text(rows, session.domain_id)
    text += "\n" + "\n".join(report.render_topology_text(topology_data))

  path = _emit(text, args.output)
  if path:
    errors = sum(1 for r in rows if r["severity"] == "ERROR")
    print(f"Sweep written to {path} ({len(rows)} writer(s), {errors} with ERROR)")
  return 1 if any(r["severity"] == "ERROR" for r in rows) else 0


def run_headless_domain(session, args):
  """No topic given and not interactive: emit the blind-spot audit."""
  from . import findings as f

  _settle(session, args.settle)
  audit = f.rank(f.suppress(session.diagnose_domain()))
  data = report.ReportData(
      domain_id=session.domain_id,
      scope="domain audit (no topic selected)",
      all_findings=audit,
      type_lookup_settings=session.type_lookup_settings,
      topology=topology.snapshot(session.registry, session.domain_id,
                 session.active_domains, session.domain_scan_ran),
  )
  text = (report.render_json(data) if args.format == "json"
          else report.render_text(data))
  path = _emit(text, args.output)
  if path:
    print(f"Report written to {path}")
  worst = max((x.severity for x in f.active(audit)), default=f.Severity.OK)
  return 1 if worst >= f.Severity.ERROR else 0


def main(argv=None):
  args = parse_args(argv)
  configure_logging(args.debug_log)
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

  headless = bool(args.topic) or args.all or not sys.stdin.isatty()

  domain_id, active_domains, scanned = resolve_domain_id(
      args.domain,
      scan_timeout=args.scan_timeout,
      do_scan=not args.no_domain_scan)

  session, participant = build_session(
      domain_id, args, active_domains=active_domains, domain_scan_ran=scanned,
      compliance=compliance)
  session.type_lookup_settings.update(connext_logging)
  if not _wait_for_remote_participants(
      session, args.ready_after_participants, args.ready_timeout):
    print("Doctor did not observe the requested remote participant count before "
          "the readiness timeout.", file=sys.stderr)
    participant.close()
    return 3
  _write_ready_file(args.ready_file)

  try:
    if args.topic:
      return run_headless_topic(session, args)
    if args.all:
      return run_headless_all(session, args)
    if headless:
      return run_headless_domain(session, args)

    from .app import RTIDoctorApp
    _settle(session, min(args.settle, 1.0))
    RTIDoctorApp(session, interval=args.interval).run()
    return 0
  finally:
    try:
      participant.close()
    except Exception as e:
      logging.error(f"[main] error closing participant: {e}")


if __name__ == "__main__":
  try:
    sys.exit(main())
  except KeyboardInterrupt:
    print("Aborted.")
    sys.exit(130)
