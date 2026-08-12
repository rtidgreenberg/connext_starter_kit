# RTI Doctor Pre-Ship Checklist

Fast DDS root-cause engagement. Updated 2026-08-12, branch
`rti-doctor-review-fixes`. Findings cited are in `CODE_REVIEW_2026-08-07.md`;
tasks are in `IMPROVEMENT_BACKLOG.md`.

**Fast DDS status: no open Critical or High finding, and no Fast DDS expected
failure outside the isolated FDD-2 discovery experiment.** Q3 - the one wrong
verdict on the likeliest misconfiguration - was fixed on 2026-08-12, along with
L6. The residual Fast DDS risk is HAR-6, which is unexplained rather than
unfixed. Cyclone carries the two open expected failures (CYC-1, WIRE-2) and does
not bear on a Fast DDS engagement.

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
- [ ] **Packet capture sees nothing from a Cyclone peer.** Not "less" — nothing.
      Measured 2026-08-12 (WIRE-2): the capture's BPF filter is the domain's
      RTPS port range plus the selected endpoint's own locators, and against
      Cyclone both miss. Cyclone advertises no endpoint-level locators, its
      participant sits on an ephemeral port outside the domain range, and a
      writer's user data is addressed to its *reader's* port — a receive
      address the filter never names. In the measured run all 68 user-data
      frames were on the wire and none were in the capture. So a Cyclone peer's
      `Representation` reads `none observed` and the Fast DDS version line
      reads `none observed in this capture` **after a capture that saw
      nothing**, which is indistinguishable from a quiet peer. This is WIRE-1's
      shape in a new place, and it is not fixed. Connext and Fast DDS are
      unaffected — both follow the standard port mapping, and the Fast DDS wire
      test passes through the identical code path. If the engagement needs wire
      evidence from Cyclone, capture by hand with `tshark -i any -f udp` and
      filter afterwards.
- [ ] **`x` in a version means that component was not on the wire.** A peer may
      report as `3.6.x.0` or `3.6.x.x`: major and minor are what the capture
      carried, and `x` is a component the local Wireshark did not render. Read
      it as "3.6-something", which is usually all the engagement needs, and
      never as a literal version string. Before 2026-08-11 that same capture
      reported *no version at all* — one absent subfield discarded the whole
      thing — so a Doctor older than this one showing nothing is not evidence
      that the peer advertised nothing (M2, fixed).
- [ ] **A default-QoS writer against an XCDR2-only reader is now reported
      correctly, and it was not before 2026-08-12.** This is the single most
      likely real misconfiguration in an engagement: a writer that never set
      DATA_REPRESENTATION advertises nothing, which means XCDR1, and a reader
      requesting XCDR2 only will never receive from it — the middleware refuses
      the match and names `DataRepresentation`. Doctor used to report that pair
      `qos.compatible` at exit 0. It now reports `qos.rxo_mismatch` at exit 1,
      with `writer offers not advertised (XCDR1 in effect)` (Q3, fixed). Two
      consequences for the field. A **Doctor older than this one calls that pair
      healthy**, so a clean report from an earlier build is not evidence about
      this policy. And the resolution is claimed only for RTI and Fast DDS
      writers, the two vendors it was measured on: a Cyclone or unrecognized
      writer still shows DATA_REPRESENTATION under `Not evaluated`, which is
      honest rather than a gap.
- [ ] Exit codes: `0` clean, `1` ERROR findings, `2` topic absent, `3` readiness
      timeout, `4` could not run **or the command line was rejected**, `130`
      interrupted. As of 2026-08-12 a rejected command line is `4` and no longer
      collides with `2` (L6, fixed), so a CI job can act on `2` as "topic
      absent" without a typo masquerading as a clean result. A job written
      against an older build should not assume this.
- [ ] HAR-6's three Fast DDS vendor tests pass now — twice on 2026-08-11, and
      on every vendor run since, with no product change that explains it.
      Recorded as "no longer reproduces, cause not established". Repeated greens
      are better evidence than one and still not a cause: an intermittent
      cross-vendor match failure that stops reproducing is the kind that comes
      back in the field. **This is the largest unquantified Fast DDS risk in the
      handover.**

## Field commands

```bash
# Stage one - is the system visible and healthy at all?
./tools/rti_doctor/run_rti_doctor.sh --domain N --system -o system.txt

# Stage two - one topic, with packet evidence
./tools/rti_doctor/run_rti_doctor.sh --domain N --topic Sensor \
    --capture-interface eth0 -o sensor.txt
```

## Re-run if anything changes

All five verified green on 2026-08-12 after the Q3 and L6 fixes, counts as
listed. An expected failure here is a recorded defect that still executes, not a
skip — if one turns into an *unexpected success*, the behaviour changed and the
doc it cites needs revising. That is exactly how Q3 was retired: its two spikes
were expected failures asserting that Doctor and the middleware disagree, and
fixing the product made both pass with their assertions untouched.

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

- [x] `./run_tests.sh unit` — 314 tests. Green, 14.4 s.
- [x] `./run_tests.sh live` — 347 tests, **no expected failures**, 148 s. The
      last one was the Q3 verdict Connext↔Connext, and it went when Q3 was
      fixed on 2026-08-12: the spike's assertion is unchanged and now passes.
      The Q3 spike prints a
      20-row matrix on its way past, which pushes the count line out of
      `tail -40` — this is M15 on a *green* run, so read the counts by running
      the modules directly, per the command above.
- [x] `./run_tests.sh vendor` — **34 tests, 1 skipped, 3 expected failures,
      no failures**, 628 s. Green with Cyclone present, which it has not been
      since 2026-08-06. Image checked and current: created 2026-08-11 13:08,
      fixture last touched 12:31. Takes over ten minutes, so it will not fit
      inside a single foreground command timeout — run it in the background.
      The three expected failures are the Fast DDS v1-only discovery
      experiment (FDD-2, isolated by design) and the two Cyclone ones added on
      2026-08-12: the Cyclone-writer→Connext-reader extensibility matrix
      (CYC-1) and the Cyclone wire capture (WIRE-2). **No Fast DDS expected
      failure remains for Q3** — that one passes now. **Rebuild the Fast DDS image if
      the fixture is newer than the image** — compare
      `test/vendors/fastdds/ExtensibilityEndpoint.cpp` against
      `docker image inspect rti-doctor-fastdds-e2e:3.6.2 --format
      '{{.Created}}'`, and rebuild with `test/vendors/fastdds/build_image.sh`.
      The fixture gained `--representation default` in `ac38165`, and an image
      older than that skips the spike.
- [x] **Cyclone was restored on 2026-08-12, and the nine failures that exposed
      are resolved.** `cyclonedds==11.0.1` is installed and pinned in
      `requirements-dev.txt`; it had been lost on 2026-08-06 when the venv was
      rebuilt for Connext 7.7 on Python 3.11 with the package listed in no
      requirements file, which turned eleven tests into silent skips. Two
      genuine defects came out of the nine failures that followed, both
      pre-existing and neither caused by this branch:
      **CYC-1** — the extensibility matrix asserted delivery under default
      Connext 7.7 TypeObject v2 propagation, which
      `CYCLONE_CONNEXT_INTEROP_FINDINGS.md` says cannot deliver. A 16-run
      matrix settled it: with `--type-object-v1-only` the whole
      Connext→Cyclone direction delivers (all four FINAL/APPENDABLE
      combinations, ~95 samples), and Cyclone→Connext delivers in none. The
      fixture gained the control, the working direction now asserts real data,
      and the other is an expected failure. Those tests cannot have passed
      since the matrix was added on 2026-08-04.
      **WIRE-2** — see the capture bullet above. Not fixed; expected failure.
      Both directions of the matrix now run the same propagation setting, so
      the only variable is which vendor holds the writer.
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
