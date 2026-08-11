# RTI Doctor Pre-Ship Checklist

Fast DDS root-cause engagement. 2026-08-11, branch `rti-doctor-review-fixes`,
HEAD `735d555`. Findings cited are in `CODE_REVIEW_2026-08-07.md`; tasks are in
`IMPROVEMENT_BACKLOG.md`.

## Fix before handover

- [x] ~~Pin `textual`, declare `rich`, move `textual-dev` out of the runtime
      requirements~~ — done in `347327b`. `textual==8.2.8` and `rich>=15.0.0`
      are the runtime file; `textual-dev` and `mypy` moved to
      `requirements-dev.txt`; the launcher verifies all three imports after
      install (M16).
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
- [ ] **Doctor will call one specific broken pair healthy, on both vendors.**
      Measured 2026-08-11 for Connext (`4aed446`) and Fast DDS (`ac38165`): a
      writer that never set DATA_REPRESENTATION advertises nothing, which means
      XCDR1 — and against a reader requesting XCDR2 only, the middleware refuses
      the match and names `DataRepresentation`, while rti_doctor reports
      `qos.compatible` and exits 0 (Q3). On any pair reporting `qos.compatible`
      with no data flowing, read the report's `Representation` and
      `Not evaluated` lines before believing the verdict. A writer showing
      `not advertised` against a reader showing `XCDR2` **is** that case.
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

## Re-run if anything changes

All five verified green at `735d555` on 2026-08-11. An expected failure here is
a recorded defect that still executes, not a skip — if one turns into an
*unexpected success*, the behaviour changed and the doc it cites needs revising.

- [ ] `./run_tests.sh unit` — 282 tests
- [ ] `./run_tests.sh live` — 315 tests, 1 expected failure (the Q3 verdict,
      Connext↔Connext)
- [ ] `./run_tests.sh vendor` — 32 tests, 12 skipped (Cyclone absent), 2
      expected failures (Fast DDS v1-only discovery, and the Q3 verdict
      cross-vendor). **Rebuild the Fast DDS image first**
      (`test/vendors/fastdds/build_image.sh`) — the fixture gained
      `--representation default` and an older image skips the spike.
- [ ] `bash scripts/test_python_env.sh` and
      `bash scripts/test_rti_spy_bundle.sh`
- [ ] `./run_lint.sh`

## Known, do not block on

N1 (one capture parsed twice), N4 (capture outlives its screen), N5 (an
explicitly-XCDR1 Connext writer reads as "not advertised"), N8 (`--no-probe`
capture window), N9 (evidence artifact gitignored), CAP-1 and CAP-3, EVD-1, and
ENV-2 (mypy is installable now via `requirements-dev.txt`, but 11 annotation
errors stand between it and being a gate). None affects a diagnosis.
