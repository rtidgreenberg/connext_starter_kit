# RTI Doctor Code Review — 2026-08-06

Review date: 2026-08-06
Reviewer: static multi-perspective review. Every conclusion below is derived
from reading the source at the cited lines, plus one AST analysis (recorded
under H1).

**All findings in this document have been fixed. See
[Implementation status](#implementation-status) for what each fix does and the
test evidence.** The line citations below describe the code *as reviewed*, not
as it stands now.

Scope: `tools/rti_doctor/rti_doctor/` (all implementation modules), the CLI and
TUI execution paths, packet-capture handling, and the tests under
`tools/rti_doctor/test/`. Working tree at review time: branch
`rti-doctor-review-fixes`, HEAD `e4c8b7a`, with uncommitted changes to
`README.md`, `views/system_overview.py`, and `test/test_live_integration.py`.

Relationship to the prior reviews:

* `CODE_REVIEW.md` (2026-08-03) — seven findings, all superseded.
* `CODE_REVIEW_2026-08-04.md` — 32 findings. Eight were applied (H1, H2, H4, H8,
  M1, M4, M5, M6). The rest were reported and left open. This review does not
  re-explain them; it re-verifies each against current source and records the
  outcome in [Carried over](#carried-over-from-2026-08-04).

The new material since 2026-08-04 is the **system scanner** (`8711052`):
`system_scan.py`, `topology.py`, the five screens in `views/system_overview.py`,
and the Issues-first navigation replacing the participant-list landing screen.
Most of the new findings live there.

## Verification status

**Confirmed** means the exact code at the cited lines was read during this
review and the defect follows from it alone. **Confirmed (conditional)** means
the code is as described but whether it fires depends on runtime state that was
not exercised — the condition is stated in the finding.

---

## Summary

| # | Sev | Finding | Area |
|---|---|---|---|
| [H1](#h1) | High | `topology` is never imported at module scope, so `--all` and the no-TTY headless path raise `NameError` after doing all the work | CLI |
| [H2](#h2) | High | Five registry queries comprehend over live dicts while three threads mutate them; the system scan walks those dicts O(E²) times per refresh | Discovery / concurrency |
| [H3](#h3) | High | One unreadable participant sample deletes that peer **and every one of its endpoints** from the registry | Discovery |
| [H4](#h4) | High | `probe.correlated` latches True and is never cleared, so topic-wide counts get reported under a writer-correlated scope line | Probe |
| [H5](#h5) | High | The system scan runs `check_type_state` on DataReaders; every reader whose type never resolves becomes an ERROR titled "for this **writer**" | Type / system scan |
| [M1](#m1) | Med | Topic- and participant-level conditions are annotated with an `endpoint_key`, so one fault becomes N duplicate issues | System scan |
| [M2](#m2) | Med | `_local_networks()` runs `getaddrinfo` + a UDP connect once **per endpoint**, and five screens each trigger their own full scan | Performance |
| [M3](#m3) | Med | The landing screen's counts are computed once at mount and never refresh; it has no refresh key | TUI |
| [M4](#m4) | Med | Four new refresh actions use bare `asyncio.create_task`; the task is unreferenced and writes to widgets after the screen is popped | TUI |
| [M5](#m5) | Med | `SweepScreen` and `ParticipantListScreen` are unreachable — ~190 lines of dead code still carried and partly tested | Dead code |
| [M6](#m6) | Med | `find_writer()` selects by dict insertion order, so `--topic` on a multi-writer topic picks a different writer between runs | Discovery |
| [L1–L6](#low) | Low | See [Low](#low) | Various |

Plus 18 findings from 2026-08-04 re-verified as still open — see
[Carried over](#carried-over-from-2026-08-04). Those are fixed too.

Plus 9 found **while implementing the fixes above and building the guards that
protect them**, none of which this review's reading caught — see
[Found during implementation](#found-during-implementation). Two of those are
High, and both were found by running the code at a scale or in a state no test
had ever put it in.

| # | Sev | Finding | Area |
|---|---|---|---|
| [I1](#i1) | Med | A fully-read primitive collection was flagged `truncated`, so the M8 fix would have turned healthy large-data reports into PARTIAL | Payload |
| [I2](#i2) | Med | A second existing test asserted a defect — two of the suite's assertions were written from observed output, not intended behaviour | Tests |
| [I3](#i3) | Low | `_local_networks()` built a /24 network set that its only consumer never reads | Static |
| [I4](#i4) | Low | `_merge_endpoint` still carries the `in (None, "")` predicate `_merge_participant` was fixed for | Discovery |
| [I5](#i5) | Low | A background refresh that raises is silent; the screen keeps showing stale data | TUI |
| [I6](#i6) | Low | Five modules carried unused imports | Hygiene |
| [I7](#i7) | High | A healthy 96-endpoint domain produced 150 issues — one note per endpoint, none of them a condition | System scan |
| [I8](#i8) | High | A domain with no DDS on it reported an ERROR and exited 1, with nothing wrong anywhere | Blind spots |
| [I9](#i9) | Med | Deleting the dead screens took `import asyncio` with it while `ReportScreen` still used it; the suite stayed green | TUI |

---

## Implementation status

Every finding above and every open item in the carried-over table has been
fixed, and five of the six found during implementation. The one exception is
**[I5](#i5)** — a background refresh that raises is still silent — which is left
open deliberately, for the reason given there.

The behaviour changes worth knowing about:

| Finding | Fix |
|---|---|
| H1 | `topology` added to the module-scope import; the dead function-local import removed. New `test/test_cli.py` drives `run_headless_all` and `run_headless_domain` end to end against a fake session — the coverage whose absence let this ship. |
| H2 | The five unsafe queries now filter `endpoint_list()`, which is one atomic `list(...)` copy. The registry docstring's snapshot claim is now true of every query rather than two of them. |
| H3 | `refresh_participants` counts unreadable handles and skips the departure sweep entirely for that cycle, logging why. Only a complete read proves a participant departed. |
| H4 | `_correlate` writes `correlated`, `matched_other_count` and `matched_unreadable_count` together on every path via a local `uncorrelated()`. The three can no longer disagree. |
| H5 | `check_type_state` and `check_assignability` are both gated on `is_writer` in the system scan. A reader no longer produces an ERROR whose title and remedy name a writer. |
| M1 | A check may declare `"scope": "topic"` or `"participant"` in its own evidence; `_annotate` then withholds endpoint identity, so `_issue_key` collapses what used to be N duplicate issues into one. `check_type_name_conflict` and the no-locator branch of `check_locators` declare theirs. |
| M2 | `_local_networks()` is `lru_cache`d — it describes the host, not the endpoint. `Session.system_scan` grew a `max_age`, and screens being *opened* reuse a snapshot up to `SCAN_REUSE_SECONDS` old while `r` always re-scans. `check_type_name_conflict` runs once per topic instead of once per endpoint, removing the largest O(E²) term. |
| M3 | `SystemOverviewScreen` gained `r` and an `on_screen_resume`, so returning from a child screen refreshes the counts. |
| M4 | All six detached `asyncio.create_task` calls (four new, two in `ReportScreen`) are now `run_worker`, whose lifetime Textual ties to the screen. |
| M5 | `SweepScreen` and `ParticipantListScreen` deleted (~190 lines). `EndpointListScreen` stays; `render_sweep_text` stays, since `--all` still uses it. |
| M6 | `find_writer` sorts candidates by key, so `--topic` on a multi-writer topic selects the same writer every run. |
| L1–L6 | Dead dataclass fields removed; metrics table computes its own column width; `_jsonable` dispatches on `Mapping` so `MappingProxyType` survives; `_snapshot` initialised and guarded; `IssueSeverityScreen` refreshes on resume; sweep truncation marks itself with `~`. |
| 08-04 H3 | `summarize` applies *every* filter it was given. A GUID prefix identifies the participant, so on its own it admitted that participant's SEDP writers and its writers on other topics. |
| 08-04 H5 | New `ProbeResult.error` for a post-creation failure, surfaced as a `probe.incomplete` WARN and appended to the verdict line, so "payload FULL" can no longer stand alone on a probe that raised. |
| 08-04 H6 | `LiveCapture.finish()` checks the exit status outside the `poll() is None` guard, so a tshark that died mid-capture is no longer an empty success. |
| 08-04 M2 | tshark's stderr goes to `<capture>.tshark.log` instead of an undrained pipe that blocks at 64KB. |
| 08-04 M3 | `-E occurrence=a`, and the parsers split on the aggregator. `rtps.sm.id` used to read `0x09` (INFO_TS) on nearly every frame, so DATA_FRAG could never be counted. |
| 08-04 M7 | `type.name_conflict` is WARN and points at `type.assignability`. A name difference is not proof: the reader's TypeConsistencyEnforcement is not in discovery. |
| 08-04 M8 | A truncated walk verdicts as PARTIAL, not FULL, and reports `payload.truncated`. This also exposed a real bug — a bulk-read primitive collection set `truncated` although it read every element — now fixed in `_walk_collection`. |
| 08-04 M9/N2 | Both `subprocess.run` calls take `timeout=TSHARK_READ_TIMEOUT`. |
| 08-04 M12 | SPDP2 is resolved from the binding's mask flag and tested as a bit, with the substring only as fallback. `str(mask)` can render as a number, in which case the old check could not fire at all. |
| 08-04 M13 | `check_no_multicast_locators` dropped from the *system scan* (one Note per writer, saying it does not affect correctness). It still runs in a targeted per-endpoint report. |
| 08-04 M14 | `check_window` WARNs only on an actual rejection; a bare `uncommitted_sample_count` is INFO, since it is the ordinary in-flight state of a reliable reader read at an arbitrary instant. |
| 08-04 N3/N4 | The discovery filter is `rtps.param.builtin_endpoint_set or rtps.param.topicName`, not `rtps`, so user DATA/HEARTBEAT/ACKNACK no longer count as participants. Endpoint tuples zip the occurrence lists positionally instead of crossing them. |
| 08-04 N5 | `summarize_discovery` returns `source` (the capture) and `kind` (the label), matching `inspect_pcap` and what the renderers read. |
| 08-04 N6 | `topology.snapshot` returns `selected_domain_id` and `other_domains_announcing` separately; the report prints the other domains below the counts, labelled as not described by them. |
| 08-04 H7 | Substantially addressed: `SweepScreen` is gone and `ReportScreen`'s probe is a screen-owned worker, so navigating away cancels it. The residual is unchanged — `probe_endpoint` itself has no cancellation, so a quit during a probe still waits out the current `--probe-timeout` window. |
| I1 | `truncated` is set inside the aggregate-element branch of `_walk_collection` only. The bulk read below it covers every element, so a long primitive collection is no longer reported as a partial walk. |
| I2 | No code change; both tests rewritten to state the intended behaviour in their docstrings. |
| I3 | `_local_networks` → `_local_addresses`, returning a `frozenset` (it is now a shared cached value); the dead `/24` set and the parameter that ignored it are gone. |
| I4 | `_merge_endpoint` uses the explicit `is None or == ""` form, matching `_merge_participant`, with the reason in a comment. |
| I5 | **Not fixed** — see [I5](#i5). |
| I6 | Five unused imports removed, and a pyflakes runner added so they cannot accumulate again. |
| I7 | Findings that say nothing is wrong are `Severity.OK`, so they render in a targeted report and never reach the issue list. 150 issues on a healthy 96-endpoint domain became 0. |
| I8 | `blind.empty_domain` is OK, and the empty case is stated explicitly everywhere a zero count would otherwise imply a healthy system. |
| I9 | `import asyncio` restored in `report_screen.py`; a TUI test now opens a report. |

### Infrastructure added alongside the fixes

The pattern across three review rounds was that fixes were reasoned about rather
than guarded. Four things now guard them:

* **`run_lint.sh`** — pyflakes over `rti_doctor/` and `test/`, honoring `# noqa`
  and skipping generated IDL. Verified to flag H1's `undefined name 'topology'`,
  and it found [I9](#i9) on its first run.
* **`run_tests.sh`** — one place defining the `unit` / `live` / `vendor` tiers,
  so CI and humans cannot drift. The unit tier needs no Connext install and no
  license.
* **`.github/workflows/rti-doctor.yml`** — lint and the unit tier on every push
  touching the tool. The live and vendor tiers still need a licensed
  self-hosted runner; that is the next step, and the workflow says so.
* **`test/domains.py`** — deterministic, port-safe domain assignment replacing
  seven private `random.randint` bands, one of which reached domain 230. A
  failure is now reproducible from the test name, and
  `RTI_DOCTOR_DOMAIN_OFFSET` lets a second machine claim its own band.

Plus the two guards for findings that had none: `TestScanUnderConcurrentDiscovery`
for [H2](#h2), verified to fail 3/3 runs against the pre-fix code, and
`test_scale` for behaviour above two endpoints, which found [I7](#i7)
immediately.

### Test evidence

```text
tools/rti_doctor/run_lint.sh        OK: no undefined names or unused imports.
tools/rti_doctor/run_tests.sh unit  Ran 166 tests   OK   (no NDDSHOME, no license)
tools/rti_doctor/run_tests.sh live  Ran 195 tests   OK   (Connext 7.7.0)

  scale: 0.080s over 96 endpoints (0.83 ms/endpoint), 0 issue(s)
```

125 before, 195 after. Two pre-existing tests were **rewritten** rather than
extended, because each asserted a defect — see [I2](#i2):

* `test_wire.py::test_summarize_filters_to_selected_writer_guid_prefix` used
  entity id `000200c2` — a builtin discovery writer — and asserted it was
  counted as user payload. That is 08-04 H3.
* `test_live_integration.py::test_large_sample_still_deserializes` asserted
  `payload FULL` on a walk that reported itself truncated. That is 08-04 M8, and
  chasing it surfaced [I1](#i1); with that fixed the fixture is genuinely FULL
  and the assertion stands unchanged.

Two more changed because the data they read was renamed on purpose:
`test_topology.py` (N6) and `test_wire_discovery.py` (N5).

Live verification against a Connext 7.7.0 fixture publisher, beyond the
integration suite:

```text
rti_doctor -d 61 --all     -> 1 writer, "matched, 58 sample(s) received, payload FULL", exit 0
rti_doctor -d 62 -t ... --format json  -> verdict FULL, topology.selected_domain_id 62
rti_doctor -d 99 (no topic, empty domain) -> blind.empty_domain ERROR
```

The first two of those three paths raised `NameError` before H1 was fixed.

---

## High

### H1

**`topology` is never imported at module scope, so `--all` and the no-TTY
headless path raise `NameError` after the full sweep completes.**

Confirmed.

[`__main__.py:9`](rti_doctor/__main__.py#L9) imports
`compat, discovery, domain_scan, engine, records, report, wire` — not
`topology`. The only `topology` import is function-local at
[`__main__.py:306`](rti_doctor/__main__.py#L306), inside `run_headless_topic`,
where it is never used. A function-local `import` binds a **local**, never a
module global. So both remaining uses resolve against a global that does not
exist:

* [`__main__.py:378`](rti_doctor/__main__.py#L378) — `run_headless_all`
* [`__main__.py:419`](rti_doctor/__main__.py#L419) — `run_headless_domain`

Verified by AST analysis of the module: after collecting module-level imports,
function-level imports, parameters, assignment targets and builtins, `topology`
is the only genuinely unresolved name in either function.

Note that `engine.py:9` does `from . import ... topology`, which sets
`topology` as an attribute of the **package**, not of `__main__`. It does not
rescue this.

Impact: `rti_doctor --all` runs the whole sweep — creating a probe reader per
writer, up to `--probe-timeout` each — and then crashes at the reporting step
with no output. The no-TTY blind-spot path (`run_headless_domain`) crashes the
same way, which is the path CI hits when Doctor is invoked without a topic.

This was reported as **N1** on 2026-08-04 with the same one-line fix. It shipped
unfixed, and it is listed first here because it is a hard crash on a shipped
path with **zero** test coverage: no test in `test/` invokes `--all` or
`run_headless_all` (grep over `test/*.py` for `--all` / `run_headless_all`
returns nothing).

Fix: add `topology` to the module-scope import at
[`__main__.py:9`](rti_doctor/__main__.py#L9) and delete it from the local import
at line 306.

### H2

**Five registry queries comprehend over live dicts while three threads mutate
them, and the system scan now walks those dicts O(E²) times per refresh.**

Confirmed.

`DiscoveryRegistry`'s docstring
([`discovery.py:18-25`](rti_doctor/discovery.py#L18-L25)) claims "every consumer
takes a snapshot via the list/dict copies below, so no explicit lock is needed".
That is true of `participant_list()` and `endpoint_list()`, which wrap
`list(...)` — a single atomic C-level operation. It is **not** true of:

* [`writers()`](rti_doctor/discovery.py#L83-L84)
* [`readers()`](rti_doctor/discovery.py#L86-L87)
* [`endpoints_for()`](rti_doctor/discovery.py#L89-L90)
* [`endpoints_on_topic()`](rti_doctor/discovery.py#L92-L93)
* [`topic_names()`](rti_doctor/discovery.py#L106-L107)

Each is a Python-level comprehension over `self.endpoints.values()`, which
raises `RuntimeError: dictionary changed size during iteration` if the dict
gains or loses a key mid-walk.

Three writers mutate that dict concurrently:

1. **Connext receive threads** — `_drain_endpoints`
   ([`discovery.py:333-340`](rti_doctor/discovery.py#L333-L340)) calls
   `upsert_endpoint` / `remove_endpoint` from the builtin listener callbacks.
2. **The Textual event-loop thread** — `RTIDoctorApp._refresh`
   ([`app.py:35-38`](rti_doctor/app.py#L35-L38)) is registered as a *synchronous*
   `set_interval` callback at [`app.py:33`](rti_doctor/app.py#L33) and calls
   `refresh_participants`, whose removal loop
   ([`discovery.py:460-461`](rti_doctor/discovery.py#L460-L461) →
   [`remove_participant`, `discovery.py:68-73`](rti_doctor/discovery.py#L68-L73))
   pops endpoints. Default interval: 2 seconds.
3. **The `asyncio.to_thread` worker** — every `session.system_scan()`.

This was **T3** on 2026-08-04, then rated as widened by `topology.snapshot`.
It is materially worse now. One `system_scan.scan()` walks the endpoint dict:

* once for `registry.endpoint_list()` ([`system_scan.py:76`](rti_doctor/system_scan.py#L76)) — safe,
* once for `registry.writers()` ([`system_scan.py:94`](rti_doctor/system_scan.py#L94)) — unsafe,
* once per participant via `check_no_endpoints` → `endpoints_for()`,
* **once per endpoint** via `check_type_name_conflict` → `endpoints_on_topic()`,
* **once per writer** via `check_assignability` → `endpoints_on_topic()`,
* **once per writer** via `check_rxo_pairs` → `endpoints_on_topic()`,
* twice more inside `topology.snapshot` via `writers()` + `readers()`.

That is O(E²) unsafe iterations per scan, against a mutator firing every 2
seconds on the UI thread plus whatever discovery traffic arrives. `run_checks`
catches the exception per check
([`checks/__init__.py:47-59`](rti_doctor/checks/__init__.py#L47-L59)) and
converts it into an `internal.check_failed` INFO — so the user does not see a
crash, they see a scan that silently drops findings and reports "0 Errors" on a
domain that has them. `topology.snapshot` is *not* inside `run_checks` and will
propagate.

Fix: make the five queries iterate `list(self.endpoints.values())`, and give the
system scan one endpoint snapshot to work from instead of re-querying per check.

### H3

**One unreadable participant sample deletes that peer and every one of its
endpoints from the registry.**

Confirmed.

[`refresh_participants`](rti_doctor/discovery.py#L410-L461) builds `live_keys`
from the participants it successfully read, then at
[`discovery.py:460-461`](rti_doctor/discovery.py#L460-L461):

```python
for key in set(registry.participants) - live_keys:
    registry.remove_participant(key)
```

But the read is guarded at
[`discovery.py:420-424`](rti_doctor/discovery.py#L420-L424):

```python
try:
    data = participant.discovered_participant_data(handle)
except Exception as e:
    logging.debug(f"[refresh_participants] unreadable participant: {e}")
    continue
```

A `continue` there skips `live_keys.add(record.key)`. The participant is still
*live* — its handle was returned by `discovered_participants()` on the same
call — but because one field read raised, it is treated as departed and
`remove_participant` pops it **and every endpoint whose `participant_key`
matches** ([`discovery.py:68-73`](rti_doctor/discovery.py#L68-L73)).

This is the same defect class as M6 (batch isolation) from 2026-08-04, which was
fixed for `_drain_endpoints` and missed here. The consequence is worse: a
transient read failure on a Connext receive thread does not lose one sample, it
erases a whole peer. The next scan then reports `endpoint.none`,
`qos.no_counterpart`, or `blind.empty_domain` — fabricated diagnoses caused by
Doctor's own bookkeeping. Because this runs every 2 s from the TUI timer, one
unlucky read is enough.

Confirmed (conditional) on whether `discovered_participant_data` actually raises
for a live handle. It plainly can — the code catches it — and the surrounding
module treats binding reads as fallible everywhere else.

Fix: only remove a participant when its handle is genuinely absent from
`discovered_participants()`. Track the handle set, not the successfully-parsed
set: add `record.key` to `live_keys` (or track by handle) before attempting the
detailed read, or keep a separate `unreadable` set and exclude it from the
removal sweep.

### H4

**`probe.correlated` latches True and is never cleared, so topic-wide counts
get reported under a writer-correlated scope line.**

Confirmed.

`_correlate` sets `result.correlated = True` at
[`probe.py:276`](rti_doctor/probe.py#L276) and never sets it back to False on
any of its three `return None` paths
([`probe.py:253`](rti_doctor/probe.py#L253),
[`:257`](rti_doctor/probe.py#L257),
[`:274`](rti_doctor/probe.py#L274)).

The probe loop calls `_correlate` once per poll iteration
([`probe.py:338`](rti_doctor/probe.py#L338)) and
`_snapshot_statuses` calls it once more, last, as the authoritative reading
([`probe.py:384`](rti_doctor/probe.py#L384)). So:

1. Iteration 1 resolves every matched publication → `correlated = True`.
2. A later iteration — or the final `_snapshot_statuses` call — sees one
   publication whose key will not read, hits the
   `if not target and unreadable: return None` bail-out, and returns None.
3. `_snapshot_statuses` falls back to the **topic-wide**
   `subscription_matched.current_count`
   ([`probe.py:386-388`](rti_doctor/probe.py#L386-L388)) — correct.
4. But `correlated` is still `True`, and `matched_other_count` /
   `matched_unreadable_count` still hold values from step 1.

Every downstream consumer then reads a writer-scoped answer off topic-wide data:

* `_scope_text` ([`checks/probe_match.py:60-75`](rti_doctor/checks/probe_match.py#L60-L75))
  prints *"Scope: the selected writer, correlated by publication handle; it is
  the only writer this reader matched"* over a topic-wide count.
* `check_incompatible_qos`'s `attributable` test
  ([`checks/probe_match.py:134-135`](rti_doctor/checks/probe_match.py#L134-L135))
  can be True on stale counters, promoting `match.incompatible_qos_topic` (WARN,
  deliberately non-suppressing) to `match.incompatible_qos` (ERROR, a registered
  explainer for `match.none` and `data.silent`). A stale True therefore
  suppresses a real symptom **and** flips the process exit code to 1.
* `check_matched` ([`checks/probe_match.py:209`](rti_doctor/checks/probe_match.py#L209))
  titles the finding "Reader matched **the writer**" instead of "a writer on
  this topic".

This is the same class of over-claim as the three regressions corrected in
`d5d457d` — the comment at
[`probe.py:277-283`](rti_doctor/probe.py#L277-L283) explains at length that
`matched_other_count` must be present-tense rather than a running max, but
`correlated` itself was left as a latch.

Fix: have `_correlate` write `result.correlated` on **every** path (False on the
three `return None` branches), and reset `matched_other_count` /
`matched_unreadable_count` to 0 alongside it, so the trio always describes the
same reading.

### H5

**The system scan runs `check_type_state` on DataReaders, so every reader whose
type never resolves becomes an ERROR titled "for this writer".**

Confirmed (wording); Confirmed (conditional) on the ERROR volume.

[`system_scan.py:80-87`](rti_doctor/system_scan.py#L80-L87) runs
`type_compat.check_type_state` for **every** endpoint in the registry, readers
included. `check_assignability` is correctly gated on `endpoint.is_writer`
([`system_scan.py:88-89`](rti_doctor/system_scan.py#L88-L89)), and
`check_representation` self-gates
([`type_compat.py:286-287`](rti_doctor/checks/type_compat.py#L286-L287)) — but
`check_type_state` does neither.

Two consequences:

1. **Certain**: the UNAVAILABLE branch is titled *"No type information available
   for this writer"* ([`type_compat.py:96`](rti_doctor/checks/type_compat.py#L96)),
   and its remedy talks about "enable full type propagation on the publisher"
   and "upgrade the publisher to Fast DDS 3.6.2"
   ([`type_compat.py:81-90`](rti_doctor/checks/type_compat.py#L81-L90)). Pointed
   at a DataReader, that names the wrong entity and sends the operator to the
   wrong side of the system.
2. **Conditional**: it is ERROR severity. Whether Doctor resolves a *remote
   reader's* type depends on TypeLookup behaviour — `request_types_filter = "*"`
   makes Connext request unknown remote types
   ([`discovery.py:229-234`](rti_doctor/discovery.py#L229-L234)), but a peer
   that does not serve reader-side TypeObjects leaves every one of its readers
   at UNAVAILABLE. On such a domain the Issues view reports one ERROR per
   reader, which is exactly the noise the ladder's suppression rules exist to
   prevent — and `type.no_type_info` has no suppressor of its own, so none of it
   collapses.

Note this is genuinely new: before the system scanner, `check_type_state` only
ran on the selected endpoint (`diagnose_endpoint`) or on a participant's writers
(`engine.diagnose_participant:76-80`). The system scan is the first caller to
point it at readers.

Fix: either gate `check_type_state` on `endpoint.is_writer` in the system scan,
or make the check itself reader-aware — a reader with no resolvable type is a
real observation, but it is INFO about Doctor's visibility, not an ERROR about
the peer, and the text must say "reader".

---

## Medium

### M1

**Topic- and participant-level conditions are annotated with an `endpoint_key`,
so one fault becomes N duplicate issues.**

Confirmed.

`_annotate` unconditionally sets `endpoint_key`, `writer_key`/`reader_key` and
`participant_key` on every finding returned from the endpoint loop
([`system_scan.py:136-145`](rti_doctor/system_scan.py#L136-L145)), and
`_issue_key` folds all four into the issue identity
([`system_scan.py:190-200`](rti_doctor/system_scan.py#L190-L200)). Two checks in
the endpoint loop return findings that are *not* about that endpoint:

* `check_type_name_conflict`
  ([`type_compat.py:114-148`](rti_doctor/checks/type_compat.py#L114-L148)) is a
  statement about the **topic**. Its evidence carries `topic_name` and
  `type_names` only. Run once per endpoint on a topic with one writer and one
  reader disagreeing about the type name, it produces two findings with two
  distinct issue keys → **two identical ERROR issues**, and the Issues screen
  counts them twice.
* `check_locators`'s "No unicast locators advertised" branch
  ([`static_discovery.py:138-148`](rti_doctor/checks/static_discovery.py#L138-L148))
  falls back to `participant.default_unicast_locators`, so it is a statement
  about the **participant**. A participant with ten endpoints and no locators
  yields ten identical WARN issues.

The RxO path shows the correct pattern by contrast: `check_rxo_pairs` sets both
`writer_key` and `reader_key` in its own evidence
([`qos_match.py:335-340`](rti_doctor/checks/qos_match.py#L335-L340)), so one
pair produces exactly one issue — which is what
`test_rxo_fault_has_one_identity_bearing_issue` asserts. No equivalent test
exists for the topic- or participant-scoped conditions.

Fix: let a check declare its own identity scope. The cheapest version is for
`_annotate` to skip `endpoint_key` when the finding's evidence already names a
broader scope, and for `check_type_name_conflict` / the locator fallback to set
`"scope": "topic"` / `"participant"` themselves.

### M2

**`_local_networks()` runs `getaddrinfo` plus a UDP connect once per endpoint,
and five screens each trigger their own full scan.**

Confirmed.

`check_locators` calls `_local_networks()` at
[`static_discovery.py:150`](rti_doctor/checks/static_discovery.py#L150), and
`_local_networks` ([`static_discovery.py:94-123`](rti_doctor/checks/static_discovery.py#L94-L123))
does a `socket.getaddrinfo(socket.gethostname(), ...)` and opens a UDP socket
on every call. The result depends only on the host, never on the endpoint — but
the system scan invokes `check_locators` once per endpoint
([`system_scan.py:81`](rti_doctor/system_scan.py#L81)). On a domain with 200
endpoints that is 200 `getaddrinfo` calls per scan. On a host whose hostname
does not resolve locally, each one can block on a DNS timeout.

Combined with the O(E²) `endpoints_on_topic` walks noted in H2, one
`session.system_scan()` is expensive. And it is invoked independently by five
screens — `SystemOverviewScreen.refresh_summary`
([`views/system_overview.py:57`](rti_doctor/views/system_overview.py#L57)),
`IssueSeverityScreen._refresh` ([`:124`](rti_doctor/views/system_overview.py#L124)),
`IssueListScreen._refresh` ([`:197`](rti_doctor/views/system_overview.py#L197)),
`TopologyHealthScreen._refresh` ([`:380`](rti_doctor/views/system_overview.py#L380)),
`MetricsScreen._refresh` ([`:596`](rti_doctor/views/system_overview.py#L596)) —
with no sharing. Navigating Overview → Issues → Errors → back → Topology →
Metrics runs six full scans.

Fix: memoize `_local_networks()` for the lifetime of a scan (module-level cache
or a field on `CheckContext`), and let `Session` cache the snapshot with a
short TTL so screens opened back-to-back reuse one scan.

### M3

**The landing screen's counts are computed once at mount and never refresh, and
it has no refresh key.**

Confirmed.

`SystemOverviewScreen.refresh_summary` is called exactly once, from `on_mount`
([`views/system_overview.py:54`](rti_doctor/views/system_overview.py#L54)).
The screen's `BINDINGS`
([`:24-25`](rti_doctor/views/system_overview.py#L24-L25)) are `m` / `s` / `q` —
no `r`, unlike every other screen in the file. `Screen.on_screen_resume` is not
implemented, so returning from a child screen does not refresh either.

Meanwhile `RTIDoctorApp._refresh` keeps polling discovery every 2 s
([`app.py:33`](rti_doctor/app.py#L33)), so the registry moves on while the
landing screen keeps showing the participant/reader/writer/topic counts and
Error/Warning/Note totals from the moment the app started. On a domain that is
still settling — the common case, since `main()` only settles for
`min(args.settle, 1.0)` before launching the TUI
([`__main__.py:476`](rti_doctor/__main__.py#L476)) — the first screen the
operator sees is the one most likely to be wrong, and there is no way to correct
it short of drilling in and back out.

Fix: add an `r` binding and an `on_screen_resume` that re-runs
`refresh_summary`.

### M4

**Four new refresh actions use bare `asyncio.create_task`.**

Confirmed.

[`views/system_overview.py:150`](rti_doctor/views/system_overview.py#L150),
[`:242`](rti_doctor/views/system_overview.py#L242),
[`:453`](rti_doctor/views/system_overview.py#L453),
[`:611`](rti_doctor/views/system_overview.py#L611) all do
`asyncio.create_task(self._refresh())` and discard the handle. Two problems,
both already reported as M15 on 2026-08-04 for `ReportScreen`
([`views/report_screen.py:74`](rti_doctor/views/report_screen.py#L74)) and
`SweepScreen` ([`:158`](rti_doctor/views/report_screen.py#L158)), and both
reproduced verbatim in the new code:

1. The event loop holds only a weak reference to a bare task, so it can be
   garbage-collected mid-flight and the refresh silently never completes.
2. Nothing cancels the task when the screen is popped. `_refresh` awaits
   `asyncio.to_thread(self.session.system_scan)` for potentially seconds, then
   calls `self._render_menu()` / `self._render_snapshot()` / `self._render_table()`,
   which write to `DataTable` and `Static` widgets that are no longer mounted.

Textual's `Widget.run_worker` exists for exactly this and ties the task's
lifetime to the widget. Use it, or keep the handle and cancel it in `on_unmount`.

### M5

**`SweepScreen` and `ParticipantListScreen` are unreachable.**

Confirmed.

Grep across `rti_doctor/**.py` for `SweepScreen` returns two hits — its own
`class` statement ([`views/report_screen.py:122`](rti_doctor/views/report_screen.py#L122))
and its own log line. `ParticipantListScreen` returns five, all inside
[`views/browse.py`](rti_doctor/views/browse.py#L18). Nothing pushes either one.
`app.py` now pushes `SystemOverviewScreen`
([`app.py:31-32`](rti_doctor/app.py#L31-L32)), and the topology screen reaches
`EndpointListScreen` directly
([`views/system_overview.py:483`](rti_doctor/views/system_overview.py#L483)),
bypassing the participant list entirely.

That is roughly 190 lines of screen code — including the `D` sweep workflow the
README just stopped documenting — that is still maintained, still imported, and
in `ParticipantListScreen`'s case still carries the only in-TUI surface for the
blind-spot audit (`_refresh_blind_spots`,
[`views/browse.py:77-93`](rti_doctor/views/browse.py#L77-L93)). Nothing in the
new Issues workflow replaces that panel; the blind-spot findings do reach the
Issues list through `system_scan`, but the "press d on any row for the full
audit" affordance is gone with no successor.

Note `render_sweep_text` is **not** dead — `run_headless_all` still uses it.

Fix: delete both screens, or reconnect them. If deleting, confirm the
blind-spot findings are still visible somewhere the operator will look before
`ParticipantListScreen` goes.

### M6

**`find_writer()` selects by dict insertion order, so `--topic` picks a
different writer between runs.**

Confirmed.

[`discovery.py:98-104`](rti_doctor/discovery.py#L98-L104):

```python
candidates = [e for e in self.writers() if e.topic_name == topic_name]
resolved = [e for e in candidates if e.type is not None]
return (resolved or candidates)[0]
```

`self.writers()` iterates `self.endpoints.values()` in insertion order, which is
discovery arrival order — nondeterministic across runs on a topic with more than
one writer. `run_headless_topic` feeds that choice into the report scope, the
probe, the peer section, and the tshark GUID-prefix filter
([`__main__.py:346-348`](rti_doctor/__main__.py#L346-L348)). Two consecutive
`rti_doctor -t Telemetry` runs can therefore produce different verdicts and
different exit codes on an unchanged system, with nothing in the report saying
which writer was chosen or that a choice was made at all.

Fix: sort candidates by `key` for determinism, and state in the report how many
writers were on the topic and which was selected. `qos.no_counterpart` already
sets the precedent of naming what was and was not compared.

---

## Low

### L1

`SystemScanSnapshot.wire_evidence` ([`system_scan.py:40`](rti_doctor/system_scan.py#L40))
and `SystemIssue.suppressed_finding_ids` ([`system_scan.py:29`](rti_doctor/system_scan.py#L29))
are declared with defaults and never written by `scan()` or `_issues()`. Neither
is read by `render_system_text`. Dead fields on a frozen dataclass read as
"populated elsewhere" to the next maintainer.

### L2

`MetricsScreen._refresh` ([`views/system_overview.py:598-608`](rti_doctor/views/system_overview.py#L598-L608))
pads `"Domain ID"` and `"Remote participants"` to 26 columns but
`"Remote DataReaders"`, `"Remote DataWriters"`, `"Unique topics"`,
`"Topic names"`, `"Source"` and `"Coverage"` to 27, so the value column is
ragged. Separately, `m` / Metrics is not in the README key table, which the
working-tree diff just rewrote.

### L3

`_freeze` returns `MappingProxyType`
([`system_scan.py:211-216`](rti_doctor/system_scan.py#L211-L216)), which is
**not** a `dict` subclass. `report._jsonable`
([`report.py:481-488`](rti_doctor/report.py#L481-L488)) dispatches on
`isinstance(value, dict)` and would fall through to `str(value)`, emitting
`"mappingproxy({...})"` instead of a JSON object. Latent today — no JSON
renderer consumes a `SystemScanSnapshot` — but it will fire the moment
`--format json` grows a system-scan mode. Add `MappingProxyType` to the
`_jsonable` dict branch.

### L4

`SystemOverviewScreen.action_save` guards with
`getattr(self, "_snapshot", None)` ([`views/system_overview.py:79`](rti_doctor/views/system_overview.py#L79)),
but `on_data_table_row_selected` reads `self._snapshot` unguarded
([`:71`](rti_doctor/views/system_overview.py#L71)) and `__init__` never
initialises it ([`:27-32`](rti_doctor/views/system_overview.py#L27-L32)).
Textual's sequential per-screen message pump appears to serialise the
`RowSelected` message behind the awaiting `on_mount`, so I could not construct a
reachable `AttributeError` — but the inconsistency is doing the guarding by
accident. Initialise `self._snapshot = None` in `__init__` and guard both.

### L5

`IssueSeverityScreen` passes its snapshot down to `IssueListScreen`
([`views/system_overview.py:146-147`](rti_doctor/views/system_overview.py#L146-L147)).
If the operator presses `r` in the child, the child re-scans but the parent's
counts are not updated, so going back shows severity counts that disagree with
the list just seen.

### L6

`render_sweep_text` truncates topic names to 32 characters with no ellipsis
([`report.py:512-513`](rti_doctor/report.py#L512-L513)). Two topics sharing a
32-character prefix render as identical rows in the summary table, with nothing
marking the truncation.

---

## Found during implementation

Six defects that this review's own reading missed, surfaced only by changing the
code and running it. Recorded here rather than folded silently into the fixes,
because two of them say something about how the earlier findings were reached.

### I1

**A fully-read primitive collection was flagged `truncated`, so the M8 fix would
have turned every healthy large-data report into PARTIAL.**

Found by: the M8 fix turning `test_large_sample_still_deserializes` red.

`_walk_collection` set `report.truncated` whenever a collection had more than
`MAX_ELEMENTS_PER_COLLECTION` (64) elements, before deciding *how* to read it:

```python
limit = min(length, MAX_ELEMENTS_PER_COLLECTION)
if limit < length:
    report.truncated = True

if element_type is not None and is_aggregation(element_type):
    for index in range(limit):    # <- only this branch actually skips elements
        ...
    return

bulk_ok, bulk_value, bulk_detail = _read_member(data, name)   # <- reads ALL of them
```

Only the aggregate-element branch walks element by element and stops at `limit`.
The primitive/string branch below it does one bulk read that covers every
element however long the collection is — so a 1000-element `sequence<octet>`
was fully read and still reported as a truncated walk.

This was invisible for as long as it existed, because `WalkReport.verdict` never
consulted `truncated` — which is precisely what 08-04 M8 was about. Fixing M8
made the latent flag load-bearing, and it immediately mislabelled the healthy
large-data fixture as `payload PARTIAL`.

Worth stating plainly: had M8 been fixed without a live large-data test in the
suite, this would have shipped as a false PARTIAL on every large-data topic —
the fix for an over-claim becoming an under-claim.

Fixed: `truncated` is set inside the aggregate branch only.

### I2

**A second existing test asserted a defect.**

Found by: running the live suite after the M8 fix.

The review already flagged that `test_wire.py:80-86` locked in 08-04 H3 by using
a builtin discovery writer as its fixture. It turns out that was not isolated —
`test_live_integration.py::test_large_sample_still_deserializes` asserted
`payload FULL` on a walk that had set `truncated=True`.

Both assertions are the same shape: written from what the tool printed at the
time rather than from what it should print. That makes them
change-detectors that actively defend the defect, and it is why both fixes
required *rewriting* a test rather than adding one — a signal worth watching for
in this suite, since a test that must be rewritten to land a fix is the point at
which a reviewer is most likely to conclude the fix is wrong.

No code fix. Both tests were rewritten with the intended behaviour stated in the
docstring, so the next person to see them red knows which way is correct.

### I3

**`_local_networks()` built a /24 network set that its only consumer never
reads.**

Found by: making the function cacheable for M2 and checking what callers do with
its return value.

`_local_networks` returned `(networks, addresses)` and `check_locators` passed
both into `_address_problem(ip, networks, local_addresses)` — whose body never
mentions `networks`. The comment inside it explains why: flagging an address
merely outside this host's own subnets was deliberately abandoned, because the
real prefix length is unknown and assuming /24 warns on healthy routed systems.
The `ipaddress.ip_network` loop that computed the set was left behind.

So every `check_locators` call — once per endpoint, per scan, before the M2
caching fix — built a set of network objects that nothing read.

Fixed: the function is now `_local_addresses()`, returns a `frozenset`, and
`_address_problem` lost the parameter. The frozenset matters now that the value
is `lru_cache`d and therefore shared between callers.

### I4

**`_merge_endpoint` still carries the predicate `_merge_participant` was fixed
for.**

Found by: reading both merge functions side by side while working on H3.

`_merge_participant` was corrected in `8c1395d` because `value not in (None, "")`
compares by equality and `False == 0` is True in Python, so an incoming
`partial_configuration=False` — the sample announcing that discovery had
completed — was read as an absent field and discarded.

`_merge_endpoint`, ten lines below, still used the identical predicate. This is
**not a live bug**: none of the fields in its list is numeric or boolean, so
nothing it merges can compare equal to `""` or `None` by accident. It is one
added field away from being the same defect, in the function whose sibling
already demonstrated it.

Fixed: rewritten as the explicit `if value is None or value == "": continue`,
matching `_merge_participant`, with the reasoning in a comment so the next
person does not "simplify" it back.

### I5

**A background refresh that raises is silent.**

Found by: converting the detached tasks to workers for M4 and asking what
happens on failure.

`_refresh` is not wrapped in try/except on any of the five screens, and both the
old `asyncio.create_task` and the new `run_worker(..., exit_on_error=False)`
swallow the exception. The screen keeps rendering the previous snapshot with no
marker, so a scan that has been failing for minutes looks identical to one that
found nothing to change. `ReportScreen` does this correctly — both `_render_static`
and `_run_probe` catch and write the error to the status line.

Not fixed. `exit_on_error=False` is deliberate — a failed refresh must not tear
down the app — but the screens need `ReportScreen`'s treatment: catch, and put
the error where the snapshot timestamp goes. Left open rather than fixed
half-way, because doing it properly means giving all five screens a shared
status convention and that is a change worth making on its own.

### I6

**Five modules carried unused imports.**

Found by: an AST sweep for imported-but-unreferenced names, run to confirm the
`SweepScreen` / `ParticipantListScreen` deletion had not orphaned anything.

`asyncio` in `app.py`, `records` in `probe.py` and `checks/probe_match.py`,
`PAYLOAD_FULL` in `checks/probe_payload.py`, `TYPE_UNAVAILABLE` in
`checks/type_compat.py`. All pre-existing. Removed.

No linter runs over this tool, which is why they accumulated; the sweep is three
lines of `ast` and would be worth wiring into CI.

### I7

**A healthy 96-endpoint domain produced 150 issues, none of which was a
condition.**

Found by: `test_scale`, the first thing in this project ever to run a scan
against more than two endpoints.

The breakdown was exact and entirely structural:

| Count | Severity | Finding |
|---|---|---|
| 96 | INFO | `type.extensibility` — one per endpoint, all describing the same shared type |
| 48 | INFO | `repr.not_advertised` — one per writer, all default QoS |
| 6 | INFO | `vendor.identify` — one per participant |

Every one is an *observation*, and `system_scan._issues` promotes every non-OK
finding into the issue list. So the Issues screen on a domain with nothing wrong
with it was 150 rows deep, which is worse than useless: it is the state in which
an operator stops reading the list, and the one real ERROR on a bad day is row
87.

This is the same defect as 08-04 M13, which the review caught for
`locator.no_multicast` and fixed by dropping that one check from the system
scan. What the review missed was that M13 was an instance of a class. The
general rule, applied here: **a finding that explicitly says nothing is wrong
should be `Severity.OK`.** `_issues` skips OK, while `_render_findings` still
prints it — so the observation survives in a targeted report, where the operator
asked about that one endpoint, and disappears from the domain-wide triage list.

Fixed: `type.extensibility` (clean case), `repr.not_advertised`, `repr.offered`
and `vendor.identify` (recognized vendor) are OK. The non-clean branches are
untouched — FINAL/mixed extensibility still WARNs, XCDR2-only still WARNs, an
unrecognized vendor still WARNs, and a recognized-but-unvalidated vendor stays
INFO because that caveat is real and is bounded by participant count.

After: the same domain reports **0 issues**, and a scan costs 0.83 ms/endpoint.

### I8

**A domain with no DDS on it reported an ERROR and exited 1.**

`check_empty_domain` raised `blind.empty_domain` at `Severity.ERROR` whenever no
participants were discovered. Pointing Doctor at a quiet domain therefore
produced an issue list with a red count, and `run_headless_domain` returned exit
1 — with nothing wrong anywhere, and nothing observed at all.

Finding nothing is the answer to the question the tool was asked, not a fault in
a system. Worse, it is the one case where "1 Error" is actively misleading:
there is no system under test to have an error.

Fixed: `blind.empty_domain` is `Severity.OK`. Its guidance is unchanged and
still renders in a report, and its `root_cause` was reworded — at ERROR it
asserted "participant discovery (SPDP) is not completing", which is a diagnosis;
it now leads with the likely truth ("nothing is running on this domain ID") and
keeps the SPDP causes for the case where peers *were* expected.
`blind.other_domain_active` is untouched: peers alive on a *different* domain is
genuinely something to report.

The counterpart matters as much as the fix. "No issues" over a domain where
nothing was observed reads as a clean bill of health, so the empty case is now
stated explicitly rather than implied by a zero:

* `render_system_text` — "No DDS participants were discovered on domain N, so
  there is nothing to report. This is not a clean bill of health: nothing was
  observed."
* `SystemOverviewScreen` — replaces the counts line entirely rather than showing
  "0 Errors | 0 Warnings | 0 Notes".
* `IssueListScreen` — same, in its snapshot status line.

### I9

**Deleting the dead screens took `import asyncio` with it while `ReportScreen`
still used it.**

Found by: the pyflakes runner added for P3, on its first run —
`undefined name 'asyncio'` at three sites in `views/report_screen.py`.

Removing `SweepScreen` (M5) left `ReportScreen` as the module's only class, and
the unused-import sweep that followed dropped `asyncio` from the header. But
`ReportScreen._render_static` and `_run_probe` both call `asyncio.to_thread`.
Opening any report from the TUI would have raised `NameError` on the first
keypress.

The full 171-test suite stayed green, because the navigation test stopped at
`EndpointListScreen` and nothing ever pushed `ReportScreen`. This is H1's exact
failure class — a name used and never imported — reintroduced by the change that
fixed H1's siblings, and caught only because the linter went in.

Fixed: import restored, and `test_opening_a_report_renders_it` now drills
Topology → writers → `o` and asserts the report body renders. Verified it fails
without the import.

### Considered and deliberately not changed

`check_rxo_pairs` emits one `qos.no_counterpart` INFO per writer with no reader,
which is the same shape as 08-04 M13 — a per-writer Note that inflates the
Issues view on a publish-only domain. It is **not** being treated the same way.
M13's note says the same thing about every writer regardless of the system
("multicast is not advertised; this is normal"), so it carries no per-writer
information. `qos.no_counterpart` names a specific topic nobody is subscribing
to, which is exactly the question an operator opens this tool to answer.
Recorded so the next reviewer does not re-litigate it.

---

## Carried over from 2026-08-04

Re-verified against current source. None of these are re-explained here; see
`CODE_REVIEW_2026-08-04.md` for the analysis.

| 08-04 # | Status | Current location / note |
|---|---|---|
| H3 — GUID-prefix filter *replaces* builtin-writer exclusion | **Open** | [`wire.py:110-117`](rti_doctor/wire.py#L110-L117). When both `writer_guid_prefix` and `writer_entity_id` are passed — which is exactly what [`__main__.py:347-348`](rti_doctor/__main__.py#L347-L348) does — the entity-id filter is skipped (`and writer_guid_prefix is None`) and so is `_is_builtin_writer`. `test_wire.py:80-86` now *locks this in*: its fixture uses entity id `000200c2`, a builtin discovery writer, and asserts it is counted. Fixing H3 requires changing that test. |
| H5 — a probe that throws after reader creation still reports `payload FULL` | **Open** | `_snapshot_statuses` is inside the `try` at [`probe.py:368-371`](rti_doctor/probe.py#L368-L371); a raise sets `create_error` but leaves `created=True`, and `ReportData.outcome` ([`report.py:162-165`](rti_doctor/report.py#L162-L165)) only consults `create_error` when `created` is False. |
| H6 — a tshark that dies mid-capture is a successful, empty capture | **Open** | [`wire.py:316-331`](rti_doctor/wire.py#L316-L331). The whole error branch is inside `if ... poll() is None`. A tshark that exits after `start()`'s 1 s window skips it entirely. |
| H7 — quitting the TUI mid-sweep hangs; second Ctrl-C closes the participant under a live probe thread | **Open** | No cancellation anywhere in `engine.sweep` ([`engine.py:120-142`](rti_doctor/engine.py#L120-L142)) or `probe_endpoint`. Partly mooted by M5: `SweepScreen` is now unreachable, but `ReportScreen`'s probe task has the same shape. |
| H9 — three incompatible Doctor-JSON parsers in the test suite | **Largely fixed** | `test/doctor_e2e.py:parse_report` is now the single Doctor-report parser, used by `test_fault_vendor_e2e.py` and `test_vendor_wire_e2e.py`. The remaining `_last_json` / `_json_result` helpers parse *fixture* output, not Doctor's. |
| M2 — tshark's stderr is an undrained PIPE | **Open** | [`wire.py:306`](rti_doctor/wire.py#L306) sets `stderr=subprocess.PIPE`; nothing reads it until `finish()`. |
| M3 — `-E occurrence=f` contradicts the multi-submessage parsing | **Open** | [`wire.py:221`](rti_doctor/wire.py#L221). `_has_submessage` splits on `","` ([`wire.py:161-162`](rti_doctor/wire.py#L161-L162)), which only makes sense with `occurrence=a`. With `occurrence=f` and INFO_TS preceding DATA, `rtps.sm.id` is `0x09` and `data_fragments` can never be nonzero. |
| M7 — `type.name_conflict` ERROR contradicts the tool's own assignability evidence | **Open** | Still `Severity.ERROR` at [`type_compat.py:135`](rti_doctor/checks/type_compat.py#L135), with no cross-reference to `type.assignability`. Now also duplicated per endpoint — see [M1](#m1). |
| M8 — a truncated payload walk is reported as `FULL` | **Open** | [`typewalk.py:82-83`](rti_doctor/typewalk.py#L82-L83): `if not self.failed: return PAYLOAD_FULL`, with no `self.truncated` test. `check_payload_walk` mentions truncation in `observed` ([`probe_payload.py:390-391`](rti_doctor/checks/probe_payload.py#L390-L391)) but the verdict line still says FULL. |
| M9 — `inspect_pcap` has no subprocess timeout and buffers every payload as hex | **Open** | [`wire.py:229`](rti_doctor/wire.py#L229): `subprocess.run(..., capture_output=True)` with no `timeout=`, over an `-e rtps.issueData` field list. |
| M10 — timeout/interval/domain arguments accept zero, negative and NaN | **Open** | [`__main__.py:126-131`](rti_doctor/__main__.py#L126-L131) validates only `--ready-after-participants` and `--ready-timeout`. `--probe-timeout`, `--type-wait`, `--settle`, `--scan-timeout`, `-i/--interval` and `-d/--domain` are unchecked. |
| M11 — `capture.start()` sits outside the `try/finally` | **Open** | [`__main__.py:349`](rti_doctor/__main__.py#L349) vs the `try` at [`:351`](rti_doctor/__main__.py#L351). `start()` also contains a blocking `time.sleep(1.0)` ([`wire.py:308`](rti_doctor/wire.py#L308)), widening the window. |
| M12 — SPDP2 detection substring-matches the string form of a bitmask | **Open** | [`blind_spots.py:75-77`](rti_doctor/checks/blind_spots.py#L75-L77). |
| M13 — `check_no_multicast_locators` fires on every writer | **Open** | [`static_discovery.py:230-247`](rti_doctor/checks/static_discovery.py#L230-L247). Now materially worse: the system scan runs it once per writer and each result becomes a separate INFO issue in the Issues view. |
| M14 — `check_window` / `check_fragmentation` convert weak evidence into verdicts | **Half fixed** | `check_fragmentation` now requires `samples_taken == 0 and not reassembled` before calling reassembly broken ([`probe_payload.py:161`](rti_doctor/checks/probe_payload.py#L161)), with the two observed false positives documented in-place. `check_window` still WARNs on any nonzero `uncommitted_sample_count` ([`probe_payload.py:215`](rti_doctor/checks/probe_payload.py#L215)), which is normal transient state mid-window. |
| M15 — TUI uses bare `asyncio.create_task` | **Open, and extended** | See [M4](#m4). |
| N2 — `inspect_discovery_pcap` repeats M9 | **Open** | [`wire.py:268`](rti_doctor/wire.py#L268). |
| N3 / N4 — `-Y rtps` + `occurrence=f` fabricates `(prefix, wr, rd)` tuples and miscounts participants | **Open** | [`wire.py:259-266`](rti_doctor/wire.py#L259-L266), [`wire.py:78-105`](rti_doctor/wire.py#L78-L105). |
| N5 — discovery path returns `pcap_source` while renderers read `source` | **Open** | [`wire.py:89`](rti_doctor/wire.py#L89) vs [`report.py:383`](rti_doctor/report.py#L383). Still latent: `inspect_discovery_pcap` has no caller. |
| N6 — `topology.snapshot` merges scanned domains into `domain_ids` | **Open** | [`topology.py:18-24`](rti_doctor/topology.py#L18-L24). `render_topology_text` prints `Domain IDs` directly above counts drawn from a single-domain registry ([`report.py:253-256`](rti_doctor/report.py#L253-L256)). `MetricsScreen` avoids this by not showing `domain_ids` at all. |
| T3 — registry queries comprehend over live dicts | **Open, escalated to High** | See [H2](#h2). |

---

## Recommended order of work

1. **H1** — one line, and it is a hard crash on a shipped path. Nothing else in
   this list matters if `--all` cannot finish. Add a test that runs
   `run_headless_all` against a fake session in the same change.
2. **H3, H2** — registry integrity. H3 fabricates diagnoses from Doctor's own
   bookkeeping; H2 silently drops findings under the same concurrency. Both are
   small, and the system scanner made both routine rather than rare.
3. **H5, M1** — system-scan correctness. Together these decide whether the
   Issues screen's counts mean anything. Both are contained in
   `system_scan.py`'s two check lists.
4. **H4** — probe correlation. Same class as the `d5d457d` regressions, same
   fix shape: make the trio (`correlated`, `matched_other_count`,
   `matched_unreadable_count`) always describe one reading.
5. **M2, M3, M4** — the TUI. M3 is the first thing an operator sees; M2 is what
   makes every screen slow; M4 is what makes a slow screen also unsafe.
6. **M5** — delete the dead screens, but resolve the blind-spot-panel gap first.
7. **H3 (wire), H6, M2 (wire), M3 (wire), M9** from the carried-over table —
   the packet path. Until these land, Appendix C should be labelled
   interface-wide observation rather than evidence about the selected writer.
8. **M6, M10, M11** — determinism and input validation.
9. Everything else.

## Test gaps implied by these findings

None of these tests exist today, and each would have caught a finding above.

| Missing test | Would have caught |
|---|---|
| Any invocation of `run_headless_all` / `--all` at all | H1 |
| `system_scan.scan` against a registry mutated from a second thread mid-scan | H2 |
| `refresh_participants` where `discovered_participant_data` raises for one of two live handles | H3 |
| `_correlate` returning None on the final call after an earlier success, asserting `correlated is False` | H4 |
| A registry with a type-UNAVAILABLE **reader**, asserting no ERROR names it a writer | H5 |
| A topic with two endpoints disagreeing on type name, asserting exactly one `type.name_conflict` issue | M1 |
| A participant with N endpoints and no locators, asserting one `locator.unroutable` issue | M1 |
| A scan over ≥2 endpoints asserting `_local_networks` is called once | M2 |
| `SystemOverviewScreen` counts after a registry change, asserting they update | M3 |
| Popping a screen mid-`_refresh` and asserting no write to an unmounted widget | M4 |
| Two writers on one topic, asserting `find_writer` is stable across registry insertion orders | M6 |
| `wire.summarize` with both `writer_guid_prefix` and `writer_entity_id`, using a *user* entity id, asserting builtin `…c2`/`…c3` writers are excluded | H3 (08-04) — and `test_wire.py:80-86` must be rewritten, not extended |
| `WalkReport.verdict` with `truncated=True` and no failures, asserting the verdict is not `FULL` | M8 (08-04) |
| A screen whose `_refresh` raises, asserting the failure reaches the status line | I5 — still open, and still a gap |

`test_large_sample_still_deserializes` now asserts `walk.truncated is False`
explicitly rather than only checking the verdict, which makes it the precise
regression guard for [I1](#i1): the fixture's `sequence<octet, 200000>` is the
exact shape that was mis-flagged.
| `LiveCapture` whose process exits between `start()` and `finish()` | H6 (08-04) |
| `--probe-timeout -1` / `--type-wait -1` / `-d -1` argument validation | M10 (08-04) |

Separately, `test_fault_vendor_e2e._domain()` and `test_rxo_vendor_e2e._run_pair`
still pick domains with `random.randint`
(`test/test_fault_vendor_e2e.py:38-39`, `test/test_rxo_vendor_e2e.py:57`), which
is the open `HAR-2` item in `IMPROVEMENT_BACKLOG.md`. Until that lands, a fix
and a domain collision produce the same red — which is the reason `S1`/`S5` were
prerequisites in the 2026-08-04 ordering, and they still are.
