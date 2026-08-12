# RTI Doctor Pre-Ship Checklist

Fast DDS root-cause engagement. 2026-08-11, branch `rti-doctor-review-fixes`,
HEAD `11b6776`. Findings cited are in `CODE_REVIEW_2026-08-07.md`; tasks are in
`IMPROVEMENT_BACKLOG.md`.

## Fix before handover

- [x] ~~Pin `textual`, declare `rich`, move `textual-dev` out of the runtime
      requirements~~ — done in `347327b`. `textual==8.2.8` and `rich>=15.0.0`
      are the runtime file; `textual-dev` and `mypy` moved to
      `requirements-dev.txt`; the launcher verifies all three imports after
      install (M16).
- [x] ~~Empty `test_output/rti_doctor_captures/`~~ — cleared 2026-08-11, 24
      files and 204 KB, along with the leaked spike directory
      `test/rti_doctor_fastdds_repr_fb18he4a/`. **It comes back.** The suites
      write into that same directory: it gained two files during the vendor run
      that verified this checklist. Clearing it is therefore the *last* step
      before handover, not the first — see "Clear the tree, last" below (N2).

## Confirm on the target host

- [ ] `tshark` is installed.
- [ ] The account running Doctor has capture rights on the interface you will
      name.
- [ ] Pick that interface now. Without `--capture-interface` capture falls back
      to `any`, which needs the widest privileges of any choice (N3).

## Brief the engineer

- [ ] Packet capture is opt-in as of `ccaaa7b`. Headless:
      `--topic X --capture-interface eth0`. TUI: `c` on a reader or writer
      report.
- [ ] `Run capture to ascertain` in a report means nobody captured — not that
      the peer is on a current version.
- [ ] **The version now comes from the parameter's own bytes, and it did not
      before 2026-08-11.** Wireshark decodes `rtps.param.product_version.*`
      only for RTI's vendor id `0x0101` and dissects the identical PID from
      eProsima's `0x010f` as `Unknown (0x8000)`, so Doctor asked for columns
      that a Fast DDS peer never fills: the version was in the capture and
      absent from the report at the same time. It is now read from parameter
      `0x8000` directly (WIRE-1). Two consequences for the field: a Doctor
      older than this one shows nothing for a Fast DDS peer no matter how long
      you capture, and the version you now see has been checked against ground
      truth — the vendor suite asserts it against the container image's own
      tag, which is the check that was missing.
- [ ] **`x` in a version means that component was not on the wire.** A peer may
      report as `3.6.x.0` or `3.6.x.x`: major and minor are what the capture
      carried, and `x` is a component the local Wireshark did not render. Read
      it as "3.6-something", which is usually all the engagement needs, and
      never as a literal version string. Before 2026-08-11 that same capture
      reported *no version at all* — one absent subfield discarded the whole
      thing — so a Doctor older than this one showing nothing is not evidence
      that the peer advertised nothing (M2, fixed).
- [ ] **Doctor will call one specific broken pair healthy, on both vendors.**
      Measured 2026-08-11 for Connext (`4aed446`) and Fast DDS (`ac38165`): a
      writer that never set DATA_REPRESENTATION advertises nothing, which means
      XCDR1 — and against a reader requesting XCDR2 only, the middleware refuses
      the match and names `DataRepresentation`, while rti_doctor reports
      `qos.compatible` and exits 0 (Q3). On any pair reporting `qos.compatible`
      with no data flowing, read the report's `Representation` and
      `Not evaluated` lines before believing the verdict. A writer showing
      `not advertised` against a reader showing `XCDR2` **is** that case.
- [ ] Exit codes: `0` clean, `1` ERROR findings, `2` topic absent **or the
      command line was rejected**, `3` readiness timeout, `4` could not run,
      `130` interrupted. Those two meanings of `2` are argparse's and Doctor's,
      and nothing but the stderr message separates them — a CI job scripting on
      `2` reads a mistyped flag as "topic not found" (L6, open).
- [ ] HAR-6's three Fast DDS vendor tests pass now — twice on 2026-08-11, the
      second time at `11b6776` — with no product change that explains it.
      Recorded as "no longer reproduces, cause not established". Two greens are
      better evidence than one and still not a cause: an intermittent
      cross-vendor match failure that stops reproducing is the kind that comes
      back in the field.

## Field commands

```bash
# Stage one - is the system visible and healthy at all?
./tools/rti_doctor/run_rti_doctor.sh --domain N --system -o system.txt

# Stage two - one topic, with packet evidence
./tools/rti_doctor/run_rti_doctor.sh --domain N --topic Sensor \
    --capture-interface eth0 -o sensor.txt
```

## Re-run if anything changes

All five verified green on 2026-08-11 at `11b6776`, and again after each of the
M2 and WIRE-1 fixes on that same branch, counts as listed. An
expected failure here is a recorded defect that still executes, not a skip — if
one turns into an *unexpected success*, the behaviour changed and the doc it
cites needs revising.

`run_tests.sh` pipes the run through `tail -40`, so a red re-run reports its
counts honestly but scrolls all but the last traceback or two out of the window
(M15). Read the counts there, then re-run the failing module on its own before
concluding anything about it. From the repo root, with the interpreter
`run_tests.sh` names on its own first line — the venv one, not a bare `python`,
which will not have `rti.connextdds`:

```bash
PYTHONPATH=tools/rti_doctor <that interpreter> \
    -m unittest tools.rti_doctor.test.<module> -v
```

- [x] `./run_tests.sh unit` — 304 tests. Green at `7b57c51`, 13.8 s.
- [x] `./run_tests.sh live` — 337 tests, 1 expected failure (the Q3 verdict,
      Connext↔Connext). Green at `7b57c51`, 114 s. The Q3 spike prints a
      20-row matrix on its way past, which pushes the count line out of
      `tail -40` — this is M15 on a *green* run, so read the counts by running
      the modules directly, per the command above.
- [x] `./run_tests.sh vendor` — **34 tests, 9 failures, 1 skipped, 2 expected
      failures** at `7b57c51`, 640 s. Read the next bullet before treating the
      red as a blocker. Image checked and current: created 2026-08-11 13:08,
      fixture last touched 12:31. Takes over ten minutes now, so it will not
      fit inside a single foreground command timeout — run it in the
      background. **Rebuild the Fast DDS image if
      the fixture is newer than the image** — compare
      `test/vendors/fastdds/ExtensibilityEndpoint.cpp` against
      `docker image inspect rti-doctor-fastdds-e2e:3.6.2 --format
      '{{.Created}}'`, and rebuild with `test/vendors/fastdds/build_image.sh`.
      The fixture gained `--representation default` in `ac38165`, and an image
      older than that skips the spike.
- [x] **The vendor tier's nine failures are one known interop condition, not
      new breakage** (CYC-1). Cyclone was reinstalled on 2026-08-12 —
      `cyclonedds==11.0.1`, now pinned in `requirements-dev.txt` — after being
      lost on 2026-08-06 when the venv was rebuilt for Connext 7.7 on Python
      3.11 with the package listed in no requirements file. That turned eleven
      silent skips into nine real failures. Every one is the same shape:
      whichever endpoint is Cyclone reports `matched: 0` while the Connext side
      writes 75–77 samples. It is `CYCLONE_CONNEXT_INTEROP_FINDINGS.md` —
      under default Connext 7.7 TypeObject v2 propagation Cyclone never
      reciprocally associates, and only `--type-object-v1-only` restores
      delivery — and the fixtures set no such control. **These tests therefore
      cannot have passed since the matrix was added on 2026-08-04**, and
      Cyclone vanished two days later, which is what kept it invisible.
      Unit (304), live (337) and lint are green at the same commit, so nothing
      on this branch caused it. The honest handover statement is that the
      vendor tier is red for a documented cross-vendor reason, with 22 of its
      34 tests passing — including all five Connext/Cyclone fault controls,
      both RxO vendor directions, and the Fast DDS wire test that asserts the
      WIRE-1 version against the image tag — not that it is green.
- [x] `bash scripts/test_python_env.sh` and
      `bash scripts/test_rti_spy_bundle.sh` — both PASS at `7b57c51`.
- [x] `./run_lint.sh` — clean at `7b57c51`: no undefined names, no unused
      imports.

## Clear the tree, last

After the final re-run, not before — the suites write into these same places.
None of it is tracked by git, so it matters only if the handover is a copy of
the tree rather than a clone.

- [ ] `rm -rf tools/rti_doctor/test_output/rti_doctor_captures` — one PCAPNG
      and one `.tshark.log` per capture, with nothing removing them (N2,
      CAP-1). `wire.py` recreates the directory on the next capture.
- [ ] `rm -rf tools/rti_doctor/test/rti_doctor_*/` — the vendor spikes leave
      their control directories behind, one of them holding a file written as
      root by a container.
- [x] ~~`test_output/rti_doctor_py39_validation/`~~ — a 96 MB Python 3.9 venv
      left by an earlier validation run, no part of any diagnosis and the
      largest thing in the tree by two orders of magnitude. Removed
      2026-08-11. Nothing in the repo references or recreates it — it was made
      by hand for a one-off check, which is why nothing was cleaning it up.
- [ ] Keep `test_output/rti_doctor_spikes/` if the Q3 evidence is meant to
      travel: those two matrices are what `DESIGN_DECISIONS.md` Q3 cites, they
      are gitignored, and a clone therefore does not have them (EVD-1).

## Known, do not block on

N1 (one capture parsed twice), N4 (capture outlives its screen), N5 (an
explicitly-XCDR1 Connext writer reads as "not advertised"), N8 (`--no-probe`
capture window), N9 (evidence artifact gitignored), CAP-1 and CAP-3, EVD-1, and
ENV-2 (mypy is installable now via `requirements-dev.txt`, but 11 annotation
errors stand between it and being a gate). None affects a diagnosis.
