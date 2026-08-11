# RTI Doctor Pre-Ship Checklist

Fast DDS root-cause engagement. 2026-08-11, branch `rti-doctor-review-fixes`,
HEAD `ca32e6f`. Findings cited are in `CODE_REVIEW_2026-08-07.md`; tasks are in
`IMPROVEMENT_BACKLOG.md`.

## Fix before handover

- [ ] Pin `textual==8.2.8` in `requirements.txt` — it is unpinned and installed
      on every launch, so a newer release can break the TUI on the customer's
      first run (M16).
- [ ] Declare `rich>=15.0.0` — imported directly at
      `views/system_overview.py:8`, currently working only as textual's
      transitive dependency (M16).
- [ ] Move `textual-dev` to a new `requirements-dev.txt` — a dev tool that
      currently ships to the customer (M16).
- [ ] Empty `test_output/rti_doctor_captures/` — captures accumulate with no
      retention policy and will otherwise go out with the logs (N2).

## Confirm on the target host

- [ ] `tshark` is installed.
- [ ] The account running Doctor has capture rights on the interface you will
      name.
- [ ] Pick that interface now. Without `--capture-interface` capture falls back
      to `any`, which needs the widest privileges of any choice (N3).

## Brief the engineer

- [ ] Fast DDS version evidence is opt-in as of `ccaaa7b`. Headless:
      `--topic X --capture-interface eth0`. TUI: `c` on a reader or writer
      report.
- [ ] `Run capture to ascertain` in a report means nobody captured — not that
      the peer is on a current version.
- [ ] DATA_REPRESENTATION is unvalidated cross-vendor (Q3, backlog REP-1). On
      any pair reporting `qos.compatible` with no data flowing, read the
      report's `Representation` and `Not evaluated` lines before believing the
      verdict. XCDR1-vs-XCDR2 is a classic Connext/Fast DDS failure.
- [ ] Exit codes: `0` clean, `1` ERROR findings, `2` topic absent, `3`
      readiness timeout, `4` could not run, `130` interrupted.
- [ ] HAR-6's three Fast DDS vendor tests pass now with no product change that
      explains it. Recorded as "no longer reproduces, cause not established" —
      do not treat today's green as settled.

## Field commands

```bash
# Stage one - is the system visible and healthy at all?
./tools/rti_doctor/run_rti_doctor.sh --domain N --system -o system.txt

# Stage two - one topic, with packet evidence
./tools/rti_doctor/run_rti_doctor.sh --domain N --topic Sensor \
    --capture-interface eth0 -o sensor.txt
```

## Re-run if anything changes (all green 2026-08-11)

- [ ] `./run_tests.sh unit` — 281 tests
- [ ] `./run_tests.sh live` — 314 tests, 1 expected failure (Q3)
- [ ] `./run_tests.sh vendor` — 28 tests, 12 skipped (Cyclone absent), 1
      expected failure (Fast DDS v1-only)
- [ ] `bash scripts/test_python_env.sh` and
      `bash scripts/test_rti_spy_bundle.sh`
- [ ] `./run_lint.sh`

## Known, do not block on

N1 (one capture parsed twice), N4 (capture outlives its screen), N8
(`--no-probe` capture window), N9 (evidence artifact gitignored), CAP-1 and
CAP-3, EVD-1, and the missing mypy tooling. None affects a diagnosis.
