# RTI Doctor Code Review — 2026-08-07

Review date: 2026-08-07
Scope: the **whole** `rti_doctor` application — all 27 implementation modules, the
CLI and TUI execution paths, the shell tooling, and the ~19-module test suite.
Working tree: branch `rti-doctor-review-fixes`, HEAD `290707c`, clean apart from
an untracked `.github/prompts/cleanup.prompt.md`.

This is a **static** review. No test, no entry point, and no DDS participant was
executed at any point, because a test suite was running on the host throughout.
The only things run were: `pyflakes` (via `run_lint.sh`), `mypy`, `bash -n`,
`git blame`, and one `tshark` read of an **already-captured** PCAP file in
`test_output/` to confirm finding [C1](#c1).

## Method

Six independent reviewers were run in parallel over disjoint slices of the app,
each told to suppress anything it could not substantiate from cited source, and
each given the prior reviews so it would not re-report closed items. A seventh
slice (DDS/RxO/XTypes semantics) stalled on its first attempt and was re-run as
two narrower reviewers.

| Slice | Files | Findings |
|---|---|---|
| Untrusted-input parsing | `wire.py`, `probe.py`, `typewalk.py`, `vendors.py`, `system_scan.py` | 6 |
| Core orchestration & lifecycle | `engine.py`, `app.py`, `discovery.py`, `records.py`, `compat.py`, `domain_scan.py` | 10 |
| Finding model, report, TUI | `findings.py`, `report.py`, `topology.py`, `views/*` | 13 |
| CLI & shell tooling | `__main__.py`, `run_*.sh`, `test/run_manual_scenario.sh`, `fixture_publisher.py`, `requirements.txt` | 13 |
| Test-suite integrity | `test/**` | 13 |
| RxO QoS semantics | `checks/qos_match.py` | 7 |
| XTypes & blind spots | `checks/type_compat.py`, `checks/blind_spots.py`, `findings.py` | 10 |

A separate diff-scoped review of `290707c` itself ran first; its four findings are
folded in below as [C1a](#c1a), [C1b](#c1b), [C1c](#c1c) and [S12](#s12).

## Summary

**71 findings: 6 Critical, 18 High, 31 Medium, 13 Low** (68 top-level plus three
sub-findings under [C1](#c1)). 43 are marked Confirmed or Re-verified; the rest
are Plausible and should be reproduced before being scheduled.

The single most important result is that **the tool's failure modes are
concentrated at the reporting boundary, not in its DDS logic.** The RxO comparison
and the XTypes assignability delegation were audited policy by policy and are
substantially correct — the defects are that unreadable input is rendered as a
verdict in both directions: as a clean OK in [Q3](#q3), [Q4](#q4), [X1](#x1),
[X4](#x4), [X5](#x5) and [X8](#x8), and as a false ERROR with exit code 1 in
[Q1](#q1), [Q2](#q2) and [X3](#x3). For a tool whose entire product is a trusted
verdict, those are the findings to fix first, and
[cross-cutting theme 2](#2-unreadable-is-rendered-as-fine--except-where-it-is-rendered-as-broken)
argues they share one root cause and one fix.

Second: the Fast DDS version-evidence feature added in the most recent commit
cannot fire at all, because the discovery capture's tshark field list and its
parser disagree on column count ([C1](#c1)). That one-line defect also makes three
of the four findings from the diff review of that commit latent rather than live.

## Verification conventions

* **Re-verified** — I read the cited code (and where noted, ran `git blame` or
  `tshark` over an existing capture) and re-derived the defect myself.
* **Confirmed** — the reviewer traced it through cited source and the reasoning
  is sound on its face; I did not independently re-derive it.
* **Plausible** — the code is as described, but whether it fires depends on
  runtime state that static reading cannot settle. The dependency is stated.

Nothing marked Plausible should be scheduled as a fix before it is reproduced.

## Static tooling baseline

| Tool | Result |
|---|---|
| `run_lint.sh` (pyflakes, `rti_doctor` + `test`) | **Clean.** No undefined names, no unused imports. |
| `mypy --ignore-missing-imports rti_doctor` | 11 errors in 4 files, **all annotation hygiene, no defects.** |
| `bash -n` on all five shell scripts | Clean. `shellcheck` is not installed on this host. |
| Pattern sweep | No bare `except:`, no mutable default args, no TODO/FIXME markers. |

The mypy errors are dataclass fields declared `str`/`int`/`float` but defaulted to
`None` — `findings.py:64`, `:159`, `:165`; `records.py:33`, `:39`, `:40`, `:41`,
`:92`; `checks/__init__.py:27` — plus two harmless `except … as error` name
reuses at `wire.py:369` and `:425`. None is a bug; the consequence is that mypy
cannot currently be used as a gate, so the class of defect it *would* catch
(`Optional` misuse on exactly the fields this codebase threads `None` through)
stays invisible. Annotating those nine fields `Optional[...]` would make
`mypy --strict-optional` a viable third static gate alongside pyflakes.

---

# Findings

## Index

| ID | Severity | One line |
|---|---|---|
| [C1](#c1) | **Critical** | The discovery-capture tshark command has 13 `-e` fields and the parser maps 12; every field but the GUID prefix is off by one, and the Fast DDS version feature is dead |
| [C2](#c2) | **Critical** | `--all` never runs the blind-spot audit, so an unreachable domain reports a clean sweep and exit 0 |
| [C3](#c3) | **Critical** | On an empty domain the TUI prints "nothing to report" while three screens simultaneously disagree about the error count |
| [X1](#x1) | **Critical** | The multicast blind-spot check's `initial_peers` half is dead code, so multicast-off-with-defaults produces no finding at all |
| [X2](#x2) | **Critical** | Suppression matches on finding `id` alone, globally, so an explainer on one topic hides a real independent failure on another |
| [Q1](#q1) | **Critical** | An unreadable PARTITION policy is converted into a positive claim of the default partition, producing a false ERROR and exit 1 |
| [H1](#h1) | High | `--format json` is not valid JSON through the documented entry point, and prompts/progress go to stdout |
| [Q2](#q2) | High | An absent writer-side PRESENTATION boolean is treated as `false`, producing a false ERROR |
| [Q3](#q3) | High | DATA_REPRESENTATION is silently skipped for default-QoS writers — the most common configuration — and the result is reported as OK |
| [X3](#x3) | High | `check_type_state` emits a writer-phrased ERROR for a DataReader on two of its three call paths |
| [X4](#x4) | High | The assignability OK finding reports the evaluated reader count under a "resolved" label, so an all-clear can cover 1 of 3 readers |
| [H2](#h2) | High | `type.extensibility` still emits one WARN per endpoint — 96 identical warnings for one type |
| [H3](#h3) | High | `o` on the issue-detail screen can never work for `qos.rxo_mismatch`, the flagship ERROR |
| [H4](#h4) | High | Topic-scoped dedup withholds participant identity, so `type.name_conflict` shows every involved participant as "OK" |
| [H5](#h5) | High | `TopologyHealthScreen` raises `AttributeError` from four key handlers when the first scan failed |
| [H6](#h6) | High | Every `cleanup` EXIT trap in `run_manual_scenario.sh` reads function-locals, so it aborts before `docker rm` and fails a successful run |
| [H7](#h7) | High | The participant and startup tshark are created outside the `try/finally` that closes them |
| [H8](#h8) | High | Every TUI report probe spawns a `tshark -i any` capture, undisclosed and unconditional |
| [H9](#h9) | High | The startup discovery capture is unbounded on disk, and its full re-parse at exit is computed and discarded |
| [H10](#h10) | High | `refresh_participants` guards only the data fetch, so one unreadable field aborts the whole poll cycle |
| [S1](#s1) | High | The scale suite skips itself when the regression it exists to catch occurs |
| [S2](#s2) | High | The discovery field-name mapping is asserted by nothing, and `compat.get` turns a wrong name into a silent default |
| [S3](#s3) | High | `unittest.main()` sits mid-file in `test_checks.py`; 13 of 20 classes are unreachable when run directly |
| [S4](#s4) | High | `FakeSession.sweep` hardcodes the two values `--all` is judged by |
| [Q4](#q4) | Medium | The `qos.compatible` OK finding records nothing about which policies were actually evaluated |
| [Q5](#q5) | Medium | The AUTO-sentinel guard tests membership anywhere in the list, so a determinate writer skips the comparison |
| [Q7](#q7) | Medium | A focused *reader* with no writers on its topic yields no finding at all |
| [X5](#x5) | Medium | The SPDP2 bit-test fix degrades silently to the substring path it replaced |
| [X6](#x6) | Medium | The SPDP2 finding never tests whether standard SPDP is *also* enabled, so a false ERROR can suppress domain-wide |
| [X7](#x7) | Medium | Secure-vs-unsecure detection keys on the substring `secur` in a user-chosen plugin alias |
| [X8](#x8) | Medium | A wrong guess about `PropertyQosPolicy`'s shape silently disables two rung-0 checks |
| [M1](#m1) | Medium | `typewalk`'s type-graph recursion has no visited set and runs once per endpoint per scan |
| [M2](#m2) | Medium | `_fastdds_product_versions` zips four occurrence lists with no length check |
| [M3](#m3) | Medium | `_walk_union` conflates "unparseable labels" with "this is the default member" |
| [M4](#m4) | Medium | `Session.system_scan` is not re-entrant and nothing serialises scans |
| [M5](#m5) | Medium | The scan copies the whole endpoint dict `P + T + 2W` times, re-paid every 3 s of navigation |
| [M6](#m6) | Medium | The discovery poll runs synchronously on the Textual event-loop thread |
| [M7](#m7) | Medium | The type-resolution state machine is mutated from two threads and can latch UNAVAILABLE on a resolved type |
| [M8](#m8) | Medium | Topology rows come from the live registry while the Health column comes from a stale snapshot |
| [M9](#m9) | Medium | `IssueListScreen`'s key filter is frozen at push time and mislabels itself "All" |
| [M10](#m10) | Medium | The verdict line drops the problem summary on every non-FULL payload |
| [M11](#m11) | Medium | Both cleanups share one `try`, so a capture-teardown failure skips `participant.close()` |
| [M12](#m12) | Medium | `--format json` produces no JSON at all on the two non-zero non-error exits |
| [M13](#m13) | Medium | A startup failure and "found ERROR findings" are both exit 1 |
| [M14](#m14) | Medium | `--ready-timeout` is the one numeric flag omitted from the finiteness check; `inf` hangs forever |
| [M15](#m15) | Medium | `run_tests.sh` truncates failure output to 40 lines, and `all` does not run all suites |
| [M16](#m16) | Medium | `rich` is imported but undeclared, `textual` is unpinned, and a dev-only package ships to users |
| [M17](#m17) | Medium | The `no_type_info` fault fixture degrades to a healthy fixture on a warning |
| [S5](#s5) | Medium | The SPDP2 bitmask path is never executed by its own tests |
| [S6](#s6) | Medium | Four `static_discovery` checks and one `blind_spots` check have zero tests |
| [S7](#s7) | Medium | The scan cache's freshness contract is untested; the stub ignores `max_age` |
| [S8](#s8) | Medium | `typewalk.py` is 584 lines with one test, and the stated reason it cannot be unit-tested is false |
| [S9](#s9) | Medium | Five probe checks are invoked by no test, and `FakeProbe`'s defaults make two unfireable |
| [S10](#s10) | Medium | Two RxO guard clauses — the AUTO sentinel and partition wildcards — have no test |
| [S11](#s11) | Medium | `run_headless_topic`, the primary headless entry point, has no test outside the licensed tiers |
| [Q6](#q6) | Low | Partition wildcard-vs-wildcard matching is more permissive than DDS partition-expression matching |
| [X10](#x10) | Low | XCDR2-only detection uses exact list equality, so `[2, 1]` is missed |
| [L1](#l1) | Low | `records.locator_ip` ignores the locator kind and reports a fabricated IPv4 for an IPv6/SHMEM peer |
| [L2](#l2) | Low | `listener_events` grows without bound and is rendered in full |
| [L3](#l3) | Low | `selected_key` survives a re-render that resets the cursor |
| [L4](#l4) | Low | `check_extensibility` passes the raw type map as `evidence`, sharing a namespace with `_annotate` |
| [L5](#l5) | Low | `s` on a severity-filtered issue list saves an unfiltered report with different numbering |
| [L6](#l6) | Low | Exit code 2 means both "bad command line" and "topic not found" |
| [L7](#l7) | Low | The cleanup trap is installed after the background children are started |
| [L8](#l8) | Low | `fixture_publisher` scale mode has no cleanup path and divides by an unvalidated argument |
| [S12](#s12) | Low | `read -rsn1` EOF matches the Enter branch, so Ctrl-D launches a fixture instead of cancelling |
| [S13](#s13) | Low | `test_fastdds_type_metadata_spike.py` is in no `run_tests.sh` tier |
| [S14](#s14) | Low | Assorted test hazards: a collision guard that omits a suite, wall-clock assertions in the unit tier |

---

## Critical

### C1

**The discovery-capture tshark command requests 13 fields and the parser maps 12, so every discovery field except the GUID prefix is off by one — and the entire Fast DDS version feature added in `290707c` can never fire.**
`../rti_doctor/wire.py#L406` and `#L412` both pass `-e rtps.sm.wrEntityId`.
**Re-verified.** The `-e` list at `wire.py:397-415` has 13 entries, positions 2
and 8 being the same field name. `parse_discovery_fields` (`wire.py:116-126`)
pads to 12 and assigns positionally. Deleting the duplicate at position 2 aligns
the remaining 12 exactly with the parser's slot order, which is what makes this
an accidental insertion rather than an intended layout; `git blame` puts it in
`edac7d46` (2026-08-05).

tshark emits one column per `-e`, and a repeated field name resolves to a single
output index, so the *first* duplicate column is always empty. Run against
`test_output/rti_doctor_captures/rti_doctor_discovery_domain42_20260807_140520.pcapng`:

```
0101fb2cf1704f904a4bd975||0x0101,0x0101|7|7|0|0|0x000004c2|0x00000000||DoctorManual_bad_pair|DoctorRich|0x00000002
 col0 = guidPrefix         ^ col1 EMPTY (the duplicate)
```

| parser field | reads col | actually contains |
|---|---|---|
| `guid_prefix` | 0 | guidPrefix — the only correct one |
| `vendor_id` | 1 | **always empty** |
| `product_version_major` | 2 | `rtps.vendorId` |
| `_minor` / `_release` / `_revision` | 3/4/5 | major / minor / release |
| `writer_entity_id` | 6 | revision |
| `reader_entity_id` | 7 | writer entity id |
| `builtin_endpoint_set` | 8 | reader entity id |
| `topic_name` | 9 | builtin_endpoint_set |
| `type_name` | 10 | **the real topic name** |
| `reliability_kind` | 11 | type name |
| — | 12 | reliability_kind, dropped |

Consequences, each traced:

1. **The Fast DDS version feature is dead on arrival.**
   `_fastdds_product_versions` (`wire.py:131`) gates on `observation.vendor_id`
   containing `010f`; that is the always-empty column, so it returns `[]` for
   every frame. `summarize_discovery` → `engine.py:85` →
   `system_scan._version_notes` therefore never sees a version,
   `environment.fastdds_version_older_than_validated` can never fire, and the
   "FAST DDS VERSION EVIDENCE" section (`report.py:104-106`) never renders — even
   against a live Fast DDS peer. The capture above contains Fast DDS traffic
   (GUID prefix `010f6591…`), so this is not a peer-availability question.
2. **`topics` / `topic_count` are garbage.** `topic_name` reads col 9 — empty for
   SEDP, `0x0000fc3f` for SPDP — so the summary reports
   `topics: ["0x0000fc3f"], topic_count: 1` for a capture whose real topic is
   `DoctorManual_bad_pair`. The real name lands in `type_name`, which
   `summarize_discovery` ignores.
3. **`builtin_endpoint_sets` reports reader entity ids**, and
   `endpoint_observations` zips revision digits against writer entity ids
   (`wire.py:150-156`).

Why the tests miss it: `test/test_wire_discovery.py:17-25` hand-writes 12-column
lines, validating the parser against a column layout tshark never produces. The
9-field `inspect_pcap` command was checked too and **is** correctly aligned, so
the defect is isolated to the discovery path.

**Fix:** delete `-e rtps.sm.wrEntityId` at `wire.py:406` (or move `rtps.vendorId`
ahead of it), and make the `test_wire_discovery.py` fixture derive its column
count from the command instead of hard-coding 12.

#### C1a

**All `environment.fastdds_version_older_than_validated` findings share one
`_issue_key`, so N distinct out-of-baseline versions collapse into one issue
naming one version.** `../rti_doctor/system_scan.py#L139` + `#L235-L247`.
`_version_notes` emits one WARN per distinct `product_version`, but the
distinguishing value lives only in `evidence["fastdds_product_version"]`, which
`_issue_key` does not read; every identity slot is empty, so all of them hash to
`environment.fastdds_version_older_than_validated:::::`. Reproduced during the
diff review: `('3.5.4.0','3.4.0.0','2.14.0.0')` → 1 issue naming only
`2.14.0.0`. **Re-verified. Latent behind [C1](#c1)** — unreachable until the
column mapping is fixed, and it will start mattering the moment it is.

#### C1b

**The same finding declares `RUNG_PARTICIPANT` but bypasses `_annotate()`, so it
carries no `participant_key`.** `../rti_doctor/system_scan.py#L142`.
`system_overview._health()` and `_linked_issue_keys()` never link it, leaving the
offending Fast DDS participant's Health cell at "OK" and its per-participant
Issues filter empty; the report labels it `Scope domain`. `_version_notes` at
`system_scan.py:59` is the only finding producer in the module not routed through
`_annotate`. **Re-verified. Latent behind [C1](#c1).** Same shape as [H4](#h4),
different producer.

#### C1c

**`_fastdds_product_versions` is latched on the first Fast DDS-bearing scan and
`discovery_capture` is nulled, so the WARN keeps firing on every later refresh
after that participant departs, as long as any participant remains.**
`../rti_doctor/engine.py#L85`. **Re-verified. Latent behind [C1](#c1).**

### C2

**`--all` never runs the blind-spot audit, so an unreachable or empty domain
reports a clean sweep and exits 0.**
`../rti_doctor/__main__.py#L434-L468`. `run_headless_all` calls only
`session.sweep()`; `diagnose_domain()` — the rung-0/1 audit that
`run_headless_domain` runs at `__main__.py:476` — is not invoked on this path, and
`rows` is empty when nothing was discovered.
Scenario: `rti_doctor -d 99 --all --format json` on a domain where SPDP is
blocked → `{"writers": [], …}`, exit **0**. The README's own design section says
rungs 0-1 "leave no row to click on, so they get a separate blind-spot audit" —
and `--all`, the flag most likely to be scripted into CI, is the one that drops
it. A domain tag mismatch, `accept_unknown_peers = false`, or SPDP2 on our side
all present as a passing build. **Confirmed.**

### C3

**On an empty domain the TUI prints "there is nothing to report" while three
screens simultaneously disagree about the error count, and the saved text report
disagrees with all of them.**
`../rti_doctor/views/system_overview.py#L150-L155` and `#L333-L337`.
Both branch on `topology["participants"] == 0` and then print "nothing was
observed / there is nothing to report", discarding `counts` entirely. But the
rung-0 blind-spot checks run unconditionally (`system_scan.py:61-62`) and are
exactly the ones that fire on an empty domain: `blind.domain_tag` (ERROR),
`blind.unknown_peers_rejected` (ERROR), `blind.no_multicast_no_peers`,
`blind.nonstandard_ports`, `blind.other_domain_active`.
Scenario: a domain tag is set, so nothing is discovered, and `blind.domain_tag`
ERROR is produced. The landing screen says "No DDS discovered … this is not a
clean bill of health" and shows **no** error count; the Issues list at `:333`
renders the ERROR row in the table while the status line directly above it says
"there is nothing to report"; the severity menu (`:236-244`, unguarded) says
"Errors 1". `report.py:111-120` gets this right — it tests `if not
snapshot.issues` *first* — so the saved report and the TUI diverge on the single
scenario the tool exists for. **Confirmed.**

### X1

**The multicast blind-spot check's entire `initial_peers` half is dead code, so
the most common real multicast blind spot produces no finding at all — and the
one case it does catch cannot reach the severity its own suppression rule
requires.**
`../rti_doctor/checks/blind_spots.py#L169-L188`.
**Re-verified.** Both arms return the same thing: if `receive_list` is truthy the
first `if` returns `[]`, and if that guard's `(has_multicast_peer or
len(peer_list) > 1)` clause is False, control falls through to
`if not receive_list:` — also False — and returns `[]` at `:188`. So
`has_multicast_peer` and `len(peer_list) > 1`, and therefore `_looks_multicast`
(`:191`), have **zero effect on the verdict**. The check reduces to "is
`multicast_receive_addresses` empty?".

Missed blind spot: `discovery.multicast_receive_addresses = ["239.255.0.1"]` (the
default) on a host where multicast does not work —
`dds.transport.UDPv4.builtin.multicast_enabled = 0`, or a switch or firewall
dropping it — with `initial_peers = ["localhost"]`. Nothing is reachable, yet the
check returns `[]`. A repo-wide grep finds no code anywhere that reads
`multicast_enabled` or any UDPv4 transport property, so this configuration
produces no finding whatsoever; `blind.empty_domain` is severity OK
(`:321`), so the run ends with zero problems and exit 0 on a participant that is
structurally unable to discover anyone. This is the exact false "you are fine"
that the blind-spot audit exists to prevent.

Compounding it, the severity is hardcoded `WARN` (`:175`) even in the genuinely
fatal case `multicast_receive_addresses = []` **and** `initial_peers = []`.
Because `suppress()` only accepts explainers at `>= ERROR`
(`findings.py:109`), the `"blind.no_multicast_no_peers"` entry in
`SUPPRESSION_RULES["match.none"]` (`findings.py:79`) is **unreachable** — it can
never explain anything. `"repr.no_common"` (`findings.py:86`) is dead for the
same reason: `type_compat.py:335` always emits it as WARN.

### X2

**Suppression matches on finding `id` alone, globally, across every endpoint,
topic and pair — so a rung-0 or rung-3 explainer in one scope silently hides a
genuinely independent failure in another.**
`../rti_doctor/findings.py#L103-L115` + `../rti_doctor/system_scan.py#L111`.
`system_scan` pools findings from the domain scope, every participant, every
endpoint and every writer/reader pair, then calls `f.suppress(findings)` **once**.
`fatal_ids` is a flat set of ids with no topic, endpoint or scope key — even
though `_annotate` has already attached that identity to each finding. Nothing
prevents an explainer in one scope from suppressing a symptom in an unrelated
one, and the README's design claim is specifically that "a lower-rung failure
suppresses the higher-rung symptoms **it explains**".

Two scenarios, both traced:

* **Cross-topic.** A writer on topic `Alarms` never resolves its schema →
  `type.no_type_info` ERROR. An unrelated pair on topic `Telemetry` yields
  `match.none`. `type.no_type_info` is in `SUPPRESSION_RULES["match.none"]`
  (`findings.py:84`), so the `Telemetry` failure is filed as "explained by
  type.no_type_info" and drops out of the active issue list — while `Telemetry`'s
  type resolved fine. The same mechanism lets `match.incompatible_qos` on topic A
  suppress `match.none` on topic B.
* **No liveness guard.** `blind.unknown_peers_rejected` (ERROR) suppresses
  `match.none` unconditionally. With `accept_unknown_peers = false` but every peer
  host present in `initial_peers`, discovery completes normally — 40
  participants, both endpoints discovered — and a `match.none` whose real cause is
  a PARTITION or DURABILITY mismatch is reported as "explained by
  accept_unknown_peers", sending the operator to `NDDS_DISCOVERY_PEERS`.

A rung-0 explainer should suppress only when the rung-0 condition demonstrably
blocked *that* pair (participant count 0, or that specific peer undiscovered),
and a per-topic/per-pair explainer should suppress only within its own scope. The
mechanism is otherwise sound — see [Re-verified as genuinely fixed](#re-verified-as-genuinely-fixed);
the defect is scope, not design. Note that suppressed findings are still rendered
in a SUPPRESSED FINDINGS section (`report.py:136-140`), so nothing is *lost* — but
they leave the active issue list and the counts the operator reads.
**Confirmed.**

### Q1

**An unreadable PARTITION policy is silently converted into a positive claim of
the default partition, producing a false ERROR — and PARTITION is the one rule in
the file that decides a mismatch from data it could not read.**
`../rti_doctor/checks/qos_match.py#L111-L116`, `#L123-L128`, `#L251-L259`, fed by
`discovery.py:327` and `:169-184`.
**Re-verified.** `_partition_names()` returns `[]` for three different
situations — a genuinely empty name list, `policy is None`, and an unreadable or
non-iterable attribute — and `_partitions_overlap()` then maps `[]` to `[""]` as
if the endpoint had *asserted* the default partition.
Scenario: the writer really has `PARTITION = ["telemetry"]`, but
`compat.get(data, "partition", None)` at `discovery.py:327` returned `None` —
the attribute is absent on that Connext version, or the property access raised
and `compat.get` swallowed it (`compat.py:86-99`), or only a sparse first SEDP
sample has arrived, since `_merge_endpoint` skips `None` and never back-fills
before the check runs. The reader has `PARTITION = ["telemetry"]`. Verdict:
`qos.rxo_mismatch`, **severity ERROR** (so exit code 1), "PARTITION: writer
offers (default), reader requests telemetry", root cause "these two endpoints …
will never communicate", plus a remedy telling the operator to change PARTITION
on one side. The two endpoints are in fact matched and communicating.
Every `_ordered_rule`/`_duration_rule` correctly declines on unreadable input
(`:83-84`, `:99-100`), and `records.representation_ids` even documents the
discipline — "An empty list means 'could not read' … callers must not treat it as
evidence of incompatibility" (`records.py:180-183`) — which this path violates.
The fix is to have `_partition_names` distinguish "unreadable" from "empty" and
have `_partitions_overlap` decline on the former. **Confirmed.**

---

## High

### H1

**`--format json` is not valid JSON through the documented entry point, and the
interactive prompt and domain scan are not suppressed by the headless flags.**
Two independent causes, both on the path a CI job would use:

* `../rti_doctor/__main__.py#L156` vs `#L511-L516` — `headless` is computed at
  `:511`, but `resolve_domain_id` decides on `sys.stdin.isatty()` alone at
  `:156`. `rti_doctor -t SensorData --format json > out.json` from a terminal
  blocks on `Enter domain ID to inspect…` (written to **stdout** by `input()`),
  then `print("Listening for active DDS domains…")` (`:188-191`) and the
  `\r listening… Ns` progress line (`:204`) also go to stdout. `out.json` is
  prompt + progress + JSON. Fix: pass `headless` into `resolve_domain_id`, and
  route prompts and progress to stderr.
* `../run_rti_doctor.sh#L12-L28` — `echo "=== RTI Doctor ==="`,
  `echo "Starting RTI Doctor..."`, and `python_env_sync_requirements` (which runs
  `pip install -v --progress-bar on`, `scripts/python_env.sh:521`) all write to
  stdout before `:28` runs the tool. Every README example invokes this wrapper,
  and the README documents the exit status as "usable directly in CI".

**Confirmed.**

### Q2

**An absent writer-side PRESENTATION boolean is treated as `false`, producing a
false ERROR — while the sibling rule on the same policy object correctly
declines.**
`../rti_doctor/checks/qos_match.py#L212-L221`.
`compat.get(writer.presentation, name, None)` yields `None` when the writer's
presentation policy is unreadable or was never populated (`discovery.py:326`),
and the predicate `if reader_value and not writer_value` cannot distinguish
`False` — a real offer of "no coherent access" — from `None`, no claim at all.
Scenario: the reader's Subscriber has
`PRESENTATION{access_scope=TOPIC, coherent_access=true}`; the writer's
`presentation` is unreadable so `writer.presentation is None`. Verdict: ERROR
"PRESENTATION coherent_access: writer offers False, reader requests True" — while
`PRESENTATION access_scope` (`:178-185`), reading the *same* policy object,
correctly declines to evaluate for exactly that input. **Confirmed.**

### Q3

**DATA_REPRESENTATION — the only XTypes RxO rule in the tool — is silently
skipped for the most common writer configuration, and the result is reported as a
clean OK.**
`../rti_doctor/checks/qos_match.py#L238-L241`, with `../rti_doctor/records.py#L204-L218`.
The guard `if writer_ids and reader_ids …` skips the check whenever either list is
empty, and `records.py:207-211` records the *verified observation* that a Connext
7.7.0 writer using the default policy advertises an **empty** representation
sequence in discovery. So for default-QoS writers this rule never runs.
Scenario: writer on default QoS (empty sequence advertised, effective
representation XCDR1 for a final type), reader explicitly
`DATA_REPRESENTATION value = [XCDR2]` only → no mismatch appended →
`qos.compatible`, Severity.OK, "No observable QoS mismatch". The pair does not
match in the real system.
The guard itself is defensible — "no claim" beats guessing — but the resulting OK
finding does not say the policy was unevaluated, so the operator acts on it as a
clean bill of health. This is the specific instance of the general problem in
[Q4](#q4), and it is the one that matters most, because
`repr.not_advertised` (`type_compat.py:305-324`) already exists to describe
exactly this state and is not cross-referenced from the QoS verdict.
**Confirmed** for the code path (empty list ⇒ check skipped ⇒ OK finding);
**Plausible** for the concrete verdict being wrong, since that depends on the
effective representation implied by an empty advertised sequence.

### X3

**`check_type_state` emits a writer-phrased ERROR when the target endpoint is a
DataReader, on two of its three call paths.**
`../rti_doctor/checks/type_compat.py#L96`, `#L105`.
`system_scan.py:92-97` guards this with `if endpoint.is_writer:` and a comment
stating exactly this hazard — that guard is the 08-06 H5 fix — but it exists
**only in the system scan**. `check_type_state` has no `is_writer` test of its own
(`:26-28`) and is reachable for readers through two other paths:
`checks/__init__.py:88` (`type_compat.CHECKS` → `static_checks()` →
`engine.py:160`, the targeted single-endpoint run, which explicitly supports a
reader target at `engine.py:163`), and `checks/__init__.py:74`
(`type_state_checks()` → `engine.py:116`, the per-participant rollup over all
endpoints).
Scenario: the operator targets a **DataReader** on topic `Sensor` whose
`SubscriptionBuiltinTopicData` type never resolved. Output: ERROR "No type
information available for this writer", remedy "enable full type propagation on
the publisher". The publisher may be perfectly healthy — the unresolved
TypeObject belongs to the subscriber side — and the operator is sent to the wrong
host. **Confirmed.** The 08-06 fix belongs inside the check, not at one call
site.

### X4

**The assignability OK finding reports the *evaluated* reader count under a
"resolved" label, so an all-clear can cover one reader out of three — and a
wholly unevaluable comparison is recorded as nothing at all.**
`../rti_doctor/checks/type_compat.py#L175-L181`, `#L216-L229`.
`_assignable` returns `None` both when the binding lacks `is_assignable_from` and
when the call raises (`:233-241`), and those readers are `continue`d out of
`results`. But `readers` was already filtered on `type is not None` — every one of
them is *resolved* — so the OK text "every resolved reader type <- W = True (N
reader(s))" and `evidence["resolved_reader_count"] = len(results)` both report the
evaluated count under a resolved label.
Scenario: topic `Sensor` has 3 resolved readers; 2 are Fast DDS readers whose
DynamicType exposes no `is_assignable_from`, 1 is a Connext reader with an
identical type. Output: OK, "every resolved reader type <- SensorType = True (1
reader(s))" — an all-clear covering 1 of 3, on precisely the cross-vendor case
this tool exists to diagnose. If all 3 are unevaluable, `results` is empty and the
check returns `[]`: an unevaluable comparison is recorded as *nothing*, never as
"unknown", so its absence is indistinguishable from a topic with no readers.
**Confirmed.**

### H2

**`type.extensibility` is still emitted once per endpoint, so 96 endpoints
sharing one FINAL type produce 96 byte-identical WARNs.**
`../rti_doctor/checks/type_compat.py#L243-L293`, keyed at
`../rti_doctor/system_scan.py#L100-L101`. The 08-06 I7 fix demoted only the
*clean* branch to `Severity.OK`; its own comment states the problem ("One note
per endpoint about a type shared by all of them put 96 identical entries in the
issue list"). The `finals or mixed` branch at `:274-293` is unchanged, runs for
readers and writers alike, and carries no `"scope"` declaration, so `_annotate`
stamps a distinct `endpoint_key` on each. The Issues screen and ISSUE SUMMARY
then report 96 warnings for one type-design problem. The scale suite's "0 issues
over 96 endpoints" result does not cover this because its fixture type is not
FINAL. **Confirmed** — the recorded fix is narrower than the problem it
describes.
Second, independent half of the same defect: the FINAL branch always yields
**WARN** (`type_compat.py:271`), which makes `is_problem` True
(`findings.py:67-68`) and so enters both the issue list and the nonzero exit
path — even when the tool's own `type.assignability` returned True for every pair
on the topic. This is the same overstatement class as the now-fixed 08-04 M7.
Consider INFO by default, escalating to WARN only when `type.assignability` is
False or a name conflict is present.

### H3

**`o` on the issue-detail screen can never work for `qos.rxo_mismatch`, and the
parent screen contradicts it for the same row.**
`../rti_doctor/views/system_overview.py#L424-L435`. `_endpoint()` unions
`writer_keys | reader_keys` and requires `len(keys) == 1`.
`qos.rxo_mismatch` (`checks/qos_match.py:324-338`) always sets both
`writer_key` and `reader_key`, so `len(keys) == 2` → `None`. Drill into a
QoS-incompatible pair — the most actionable ERROR the scan produces — press `o`,
and get "Open report requires an issue with exactly one writer", which is also
factually wrong about what the code accepts. `IssueListScreen.action_open_report`
(`:377`) tests `len(issue.writer_keys) != 1` and **does** open the same issue.
**Confirmed.**

### H4

**Topic-scoped dedup withholds participant identity, so `type.name_conflict`
shows every involved participant as "OK" and its `i` filter is empty.**
`../rti_doctor/system_scan.py#L178-L181` + `../rti_doctor/checks/type_compat.py#L155`,
consumed at `views/system_overview.py:524-536` and `:571-581`.
`_issue_key` folds entity identity into the key, so the only way `_annotate` can
dedup a topic-wide condition is to *withhold* endpoint/participant identity —
which is also the identity the Health column and the `i` filter read.
`check_type_name_conflict` declares `"scope": "topic"`, so its
`participant_keys` and `writer_keys` are empty.
Scenario: two vendors publish topic `Sensor` as `Sensor` and `sensors::Sensor`. A
`type.name_conflict` WARN exists; in Participants mode both participants render
Health "OK"; highlighting either and pressing `i` (README: "the issues linked to
the highlighted row") yields an empty list. Only Topics mode links it.
**Confirmed.** This is a direct consequence of the 08-06 M1 fix — the dedup key
and the linkage identity need to be separate fields, not one field doing both.

### H5

**`TopologyHealthScreen` raises `AttributeError` out of four key handlers
whenever the first scan failed — a deliberately reachable state.**
`../rti_doctor/views/system_overview.py#L527`, `#L573`, `#L612`.
`_health()`, `_linked_issue_keys()` and `action_save()` dereference
`self.snapshot.issues` / pass `self.snapshot` with no null guard, but `None` is
supported: `_scan()` (`:80-88`) returns `None` on a failed scan and `on_mount`
leaves `self.snapshot = None` while `_report()` writes "Press r to retry".
Scenario: open Topology while the scan raises (no license, unreachable domain) →
the documented retry screen → press `1`/`2`/`3`/`4` (`:545-559` → `_render_table`
→ `_health`), or `i` (`:568`), or `s` (`:612`) → `AttributeError: 'NoneType' has
no attribute 'issues'` inside a Textual action handler, which kills the
interaction silently. `s` additionally leaves a **zero-byte report file** on disk,
because `open(…, "w")` runs before the raise. The two sibling screens guard this
(`:179-181`, `:368-369`), so the omission is asymmetric rather than a convention.
Even in the no-participants case where `_health` is never reached,
`_render_table` ends by overwriting the "Scan failed" banner at `:521`.
**Confirmed**, independently by two reviewers.

### H6

**Every `cleanup` EXIT trap in `run_manual_scenario.sh` dereferences function
*locals*, so under `set -u` it dies on its first line — failing a successful run
and skipping `docker rm`.**
`../test/run_manual_scenario.sh#L250-L255`, `#L337-L344`, `#L373-L380`.
`cleanup` reads `$reader_pid`/`$writer_pid`/`$docker_pid`/`$reader_container`,
which are `local` to `run_rxo_pair` (`:235`), `run_fastdds_pair` (`:301`) and
`run_fastdds_no_type_info` (`:349`). The `EXIT` trap fires *after* the function
returns, when those locals no longer exist, and `set -u` (`:4`) makes the first
line fatal.
Scenario: `./test/run_manual_scenario.sh -s rxo-compatible` (or any of the 10
pair/fastdds scenarios) → after `--duration` (default 300 s) elapses and `wait`
returns, the script prints `line 251: reader_pid: unbound variable` and exits
**1** on a scenario that succeeded. Because `kill "$reader_pid"` is the *first*
statement in `cleanup`, the abort happens before `docker rm --force`, so the
Fast DDS scenarios leave their `rti-doctor-manual-*` containers running —
contradicting the README's claim that they "explicitly stop and remove their
Docker containers during that cleanup". Ctrl-C is unaffected (the trap fires
while the locals are still in scope), so this only bites the normal-completion
path — the one nobody watches. The reviewer confirmed the mechanism with an
isolated 8-line bash reproduction. **Confirmed.**

### H7

**The participant and the startup tshark are created outside the `try/finally`
that closes them.**
`../rti_doctor/__main__.py#L519-L533` (creation) vs `#L545-L550` (cleanup).
Anything raising in `:522-531` leaves the participant open and the tshark process
orphaned. Structurally the same defect as carried-over M11, which was fixed for
`run_headless_topic` (`:412-414`) and `engine.diagnose_endpoint`
(`engine.py:149-155`) but not here, where the leak is larger.
Scenario: interactive run, operator picks a capture interface at the prompt
(`:517`). `start_discovery_capture` → `LiveCapture.start()` → `Popen(tshark …)`
then `time.sleep(1.0)` (`wire.py:474-475`). Ctrl-C inside that one-second sleep
raises at `:522`; `main()` unwinds without entering the `try`; the `__main__`
guard prints "Aborted." and exits 130. The tshark writing into
`test_output/rti_doctor_captures/` outlives rti_doctor with nothing to reap it,
and the DomainParticipant is never closed. `--ready-after-participants` widens
the window to `--ready-timeout` seconds (default 15) at `:524`, and
`_write_ready_file` (`:531`) can raise `OSError` on an unwritable path for the
same result. The author's duplicated cleanup at `:528-529` shows this was
recognised for the *timeout* return path but not the *exception* path.
**Confirmed.**

### H8

**Every TUI report probe spawns a `tshark -i any` packet capture, undisclosed and
with no way to decline.**
`../rti_doctor/views/report_screen.py#L108-L109` passes `"any"` as the third
positional argument to `session.diagnose_endpoint`, i.e.
`capture_interface="any"` (`engine.py:126`).
**Re-verified, with a correction to how this was first reported:** this is
*deliberate*, not an argument-mapping slip — `git blame` attributes it to
`9f7fc95 "feat(rti_doctor): capture Fast DDS discovery evidence"`, which added it
to populate the report's `wire` tab. The consequences are still defects:

* In the CLI, capture is gated behind `--capture-interface` and `parse_args` even
  requires `--topic` alongside it (`__main__.py:129`). In the TUI, navigating
  Topology → Writers → Enter on any writer spawns `tshark -n -i any -f <bpf> -w …`
  with no prompt and no mention on screen.
* It contradicts the tool's stated contract (`probe.py:3-5`: the probe "is the
  only part of rti_doctor that creates DDS entities beyond the diagnostic
  participant") by spawning a privileged subprocess instead.
* It creates `test_output/rti_doctor_captures/` relative to the process CWD
  (`engine.py:140`) plus a `.tshark.log` per report, and never removes either.
* It adds ≥1 s and up to ~9 s of wall clock to every probe (`wire.py:470-475`,
  the `4.0 - elapsed` sleep in `finish()`), and routes through the
  known-unbounded `inspect_pcap` memory path (08-04 M9 residual).
* On a host without capture privileges, `start()` records tshark's stderr into
  `self.error`, so **every** report grows a spurious wire-evidence error about a
  capture the operator never asked for.

Note the `wire` tab's own fallback text is "No direct RTPS packet capture was
requested" (`report.py:228-229`) — written for a path that can no longer happen
in the TUI. Either gate this behind an explicit key/flag, or state on screen that
a capture is being taken and where it lands.

### H9

**The startup discovery capture is unbounded on disk, captures all user traffic,
and its full re-parse at exit is computed and thrown away.**
`../rti_doctor/wire.py#L470-L473` spawns `tshark -n -i IFACE -f FILTER -w PATH`
with no `-a duration:`, `-b filesize:` or `-c`. `capture_filter` with the
placeholder endpoint (`__main__.py:308`, no locators) yields
`udp and (portrange <base+250·d>-<+249>)` — the whole RTPS port range for the
domain, i.e. **all user data traffic, not just discovery**. Confirmed against the
leftover artifacts: `rti_doctor_discovery_domain42_20260807_140520.pcapng` is
320 KB / 474 frames over ~9 minutes on a near-idle test domain.
The capture is stopped only when a Fast DDS participant appears
(`engine.py:80-84`) — which per [C1](#c1) can never be detected from the capture
itself — so on a domain with no Fast DDS peer it runs for the entire session. At
exit, `engine.close_discovery_capture` (`engine.py:60-64`) calls
`finish_discovery()`, which at `wire.py:550-553` runs a **full
`inspect_discovery_pcap` over the whole file** — a blocking `subprocess.run(…,
capture_output=True, timeout=120)` — and then **discards the returned dict
entirely**. Quitting a long session therefore pays an unexplained
multi-second-to-2-minute stall plus tshark's buffered stdout in RAM, for a result
nobody reads. Nothing deletes the `.pcapng` or the sibling `.tshark.log`
(`wire.py:451`); `rti_doctor_captures/` in this checkout already holds 20+
leftovers. **Confirmed.**

### H10

**`refresh_participants` guards only the data fetch, so one unreadable field on
one participant aborts the whole poll cycle and silently drops the rest.**
`../rti_doctor/discovery.py#L436-L476`. The `try/except` covers
`discovered_participant_data(handle)` (`:438-442`) and the key decode
(`:447-452`). Everything else in the per-handle body is unguarded and can raise:
`list(compat.get(data, "transport_info", []) or [])` (`:466`) and the
`default_unicast_locators` equivalent (`:454`) invoke
`__bool__`/`__len__`/`__iter__` on a Connext sequence; `str(key_value)` (`:458`)
invokes the binding's `__str__`; `records.first_locator_ip` catches only
`TypeError`/`ValueError` around `[int(b) for b in address]`
(`records.py:151-154`) and nothing around the iteration itself.
This is exactly the hazard `_drain_endpoints` was written to avoid, with the
rationale spelled out at `discovery.py:338-342` ("losing endpoints silently makes
rti_doctor report 'none of its endpoints are visible', a fabricated diagnosis
caused by its own dropped samples"). `refresh_participants` has the same
requirement and no per-handle isolation.
Scenario: handles `[P1, P2, P3]`, P2's `transport_info` raises on iteration. P1
is upserted, P2 raises at `:466`, the exception leaves the function — P3 is never
upserted and the departure sweep never runs. In the TUI it escapes the
`set_interval` callback at `app.py:33`; headless it escapes `_settle`
(`__main__.py:320`) or `_wait_for_remote_participants` (`:356`), and in the latter
case out of `main()` *before* the `try` at `:533`, compounding [H7](#h7). If P3
was the only peer on the topic being diagnosed, the report says the domain is
empty. **Confirmed** for the unguarded region; **Plausible** that a binding field
raises there in practice.

### S1

**The scale suite skips itself when the regression it exists to catch occurs.**
`../test/run_tests.sh` `live` tier, `../test/test_scale.py#L91-L94`.
**Re-verified.** `setUp` calls `self.skipTest(...)` whenever
`self.discovered < EXPECTED_ENDPOINTS` (96). Because `setUp` runs before *every*
method, it also skips `test_the_domain_really_is_at_scale` at `:101`, whose
docstring reads "Guards the guard: the rest of this suite is meaningless on 2
endpoints."
Surviving defect: reintroduce the sample-dropping bug in
`discovery._drain_endpoints` (`discovery.py:349-356`) or the departure-sweep bug
in `refresh_participants` (`:484-490`) so only 40 of 96 endpoints reach the
registry — every scale test *skips*, `run_tests.sh live` prints
`OK (skipped=7)`, exit 0. The guard can never fire, because the guard is behind
the same gate as the thing it guards. Fix: make the domain-really-is-at-scale
assertion a `setUpClass`-level hard failure, not a per-test skip.

### S2

**The discovery field-name mapping is asserted by nothing in the unit tier, and
`compat.get` turns a wrong field name into a silent default.**
`../rti_doctor/discovery.py#L310-L331` and `#L457-L474`.
Every check test constructs `records.EndpointRecord(...)` /
`ParticipantRecord(...)` directly (`test_checks.py:99-112`,
`test_system_scan.py:29-38`), bypassing `_endpoint_from_data` entirely. The only
tests that reach it feed fakes carrying just
`key`/`topic_name`/`type_name`/`participant_key` (`test_checks.py:1003-1014`) or
`key`/`participant_name` (`:1184-1199`). `compat.get(obj, name, default)` catches
everything and returns the default (`compat.py:86-99`), so a renamed field is
indistinguishable from an absent one.
Surviving defect: change `vendor_id=compat.get(data, "rtps_vendor_id", None)` at
`discovery.py:463` to any wrong name. Every peer's `vendor_name` becomes unknown,
`check_vendor_identify` emits **WARN "unrecognized vendor"** for every
participant on every domain, and `check_vendor_notes` goes silent. Nothing fails:
no unit test exercises the read, and all three "a healthy system must be quiet"
assertions filter `severity >= ERROR` (`test_checks.py:128`,
`test_live_integration.py:123`, `test_fault_vendor_e2e.py:172`).
The same seam covers the RxO policies: a wrong name for `destination_order`,
`presentation`, `liveliness`, `latency_budget`, `partition` or `representation`
(`discovery.py:319-328`) makes `_ordered_rule` return `None`
(`qos_match.py:83-84`) — i.e. the finding silently becomes `qos.compatible`,
which is exactly what `test_unreadable_policies_produce_no_claim`
(`test_checks.py:731-735`) asserts as *correct*. Of those policies only
`reliability`, `durability`, `ownership` and `deadline` are covered end-to-end at
all. **Confirmed.** This is the single highest-leverage test gap in the suite:
one table-driven test that feeds a realistic fake `data` object through
`_endpoint_from_data` and asserts every field arrives non-`None` would close it.

### S3

**`unittest.main()` sits mid-file in `test_checks.py`; 13 of the 20 test classes
are defined after it and are unreachable when the file is run directly.**
`../test/test_checks.py#L504-L505`. **Re-verified.** Classes at `:508`, `:519`,
`:745`, `:819`, `:877`, `:947`, `:992`, `:1036`, `:1058`, `:1132`, `:1167`,
`:1181`, `:1222` — including the entire `TestRxO` matrix, `TestProbeCorrelation`,
`TestParticipantMerge`, `TestParticipantDepartureSweep` and
`TestWriterSelectionIsDeterministic` — are never collected by
`python test/test_checks.py`, which runs 7 classes and prints `OK`.
`run_tests.sh` uses `-m unittest` so CI is unaffected, but a developer verifying
an RxO change the obvious way gets a green run that never touched a single RxO
test. Fix: move the `if __name__` block to the end of the file.

### S4

**`FakeSession.sweep` hardcodes the two values `--all` is judged by, so both are
dead in the tests.**
`../test/test_cli.py#L38-L48`. It returns `"severity": "OK"` and
`"findings": []`, so `run_headless_all`'s exit-code branch (`__main__.py:468`,
`any(r["severity"] == "ERROR")`) and its JSON three-tuple unpack (`:454-455`) are
never exercised. `engine.sweep` and `engine._sweep_row` — the real producers of
`row["severity"]` (`worst.label`) and `row["findings"]` (3-tuples) — are called by
no test at all.
Surviving defect: change `"severity": worst.label` to `worst.name.lower()` at
`engine.py:212` and `--all` exits 0 on a domain full of ERRORs
(`"error" != "ERROR"`); or add a fourth element to the findings tuple at
`engine.py:214` and `--all --format json` raises `ValueError: too many values to
unpack` **after completing the entire sweep** — the same after-all-the-work crash
class as 08-06 H1, which `test_cli.py` was added to prevent. This is 08-04 S5
surviving the fix credited with closing it. **Confirmed.**

---

## Medium

### Q4

**The `qos.compatible` OK finding records nothing about which policies were
actually evaluated, so "compatible" is indistinguishable from "almost nothing was
readable".**
`../rti_doctor/checks/qos_match.py#L300-L315`. Every individual rule declines on
unreadable input — which is correct — and `mismatches == []` then yields
Severity.OK. A pair where reliability, durability, deadline, liveliness,
presentation and representation were *all* `None` produces a byte-for-byte
identical finding to a pair where all ten policies were read and compared; the
`evidence` dict carries only keys, labels and topic, with no per-policy
evaluation record. Since `Severity.ERROR` drives the exit code
(`__main__.py:431`), OK is the verdict an operator ships on.
The fix is cheap and closes [Q3](#q3)'s reporting half too: record
`evidence["policies_compared"]` and `evidence["policies_unreadable"]`, and have
the `observed` line say "8 of 10 policies compared" rather than an unqualified
"No observable QoS mismatch". **Confirmed.**

### Q5

**The AUTO-sentinel guard tests membership anywhere in the list rather than at
position 0, so a writer with a determinate effective representation skips the
comparison.**
`../rti_doctor/checks/qos_match.py#L240` — `-1 not in writer_ids`.
Scenario: writer `value = [XCDR2(2), AUTO(-1)]`, whose effective representation is
unambiguously XCDR2; reader `value = [XCDR1(0)]`. A real incompatibility; the
guard skips the comparison and the pair is reported compatible. The positional
check the surrounding comment itself describes (`:234-237`, "the first in its
list") would catch it — only `writer_ids[0] == -1` needs to disable the rule.
**Confirmed** (a genuine miss, not a false positive). Note this is the *same
guard* that [S10](#s10) shows is untested: it is both necessary and too wide, so
narrowing it needs the AUTO test written first.

### Q7

**A focused *reader* with no writers on its topic yields no finding at all.**
`../rti_doctor/checks/qos_match.py#L272-L287`. The `qos.no_counterpart` INFO is
emitted only when `endpoint.is_writer`; the reader case falls through to
`return []`. A reader nobody publishes to — a common real failure, and one an
operator would specifically point this tool at — produces silence from the match
rung rather than the INFO its writer-side counterpart gets. **Confirmed**
(missing finding, not a wrong one).

### X5

**The SPDP2 bit-test fix degrades silently to the substring path it replaced.**
`../rti_doctor/checks/blind_spots.py#L76-L83`. The *structure* of the 08-04 M12
fix is right — bit test first, substring only as fallback — but the flag lookup is
an unvalidated `getattr`:
`compat.get(getattr(dds, "DiscoveryConfigBuiltinPluginKindMask", None), "SPDP2", None)`.
If the binding spells the flag differently, or exposes it as a static-method or
property object rather than an int-able value, either `flag is None` or
`int(flag)` raises `TypeError` — and both land on
`"SPDP2" in str(plugins).upper()`, the exact path M12 fixed, with no diagnostic
and no observable difference in output. `int(plugins)` failing on a mask without
`__int__` reaches the same fallback.
Scenario: `builtin_discovery_plugins = SPDP2|SEDP`, `str(mask)` renders as `18` or
`<…: 18>`, the flag lookup misses, no finding fires, and the tool reports a
healthy domain while this participant cannot discover any Fast DDS, Cyclone or
OpenDDS peer. Recommend a hardcoded numeric mask constant plus a WARN/INFO when
neither the flag nor a name-rendered mask is available, so an *unverifiable* check
does not read as a *passing* one. **Plausible.**

### X6

**The SPDP2 finding never tests whether standard SPDP is also enabled, so a false
ERROR can suppress genuine failures domain-wide.**
`../rti_doctor/checks/blind_spots.py#L97-L113`. The bit test fires on SPDP2
alone. For `builtin_discovery_plugins = SPDP|SPDP2|SEDP` the ERROR "SPDP2
discovery is enabled, which cannot discover standard-SPDP peers" is simply
false — the standard plugin is running. And because it is an ERROR it is an
explainer for both `match.none` and `endpoint.none` (`findings.py:76`, `:96`), so
this one false positive suppresses genuine match and endpoint failures across the
whole domain (see [X2](#x2) for why the suppression is domain-wide). The
condition should require the SPDP2 bit set **and** the SPDP bit clear.
**Plausible.**

### X7

**Secure-vs-unsecure detection keys on the substring `secur` in a user-chosen
plugin alias.**
`../rti_doctor/checks/blind_spots.py#L121-L123`. In RTI's property model
`com.rti.serv.load_plugin` holds an arbitrary alias, with the real identity in
`<alias>.library` / `<alias>.create_function`.
Scenario: `com.rti.serv.load_plugin = crypto1`,
`crypto1.library = nddssecurity`,
`crypto1.create_function = RTI_Security_PluginSuite_create`. `"secur" in
"crypto1"` is False → no finding. A secure participant is then reported as having
no rung-0 blind spot; pointed at an unsecure peer it sees nothing, and with
`blind.empty_domain` at OK severity the run is a clean bill of health. Detect
instead on `com.rti.serv.load_plugin` being non-empty at all, or any
`<alias>.library` naming `nddssecurity`, or the presence of any
`com.rti.serv.secure.*` / `dds.sec.*` property. **Plausible.**

### X8

**A wrong guess about `PropertyQosPolicy`'s shape silently disables two rung-0
checks.**
`../rti_doctor/checks/blind_spots.py#L29-L36`. `_property_value` tries
`policy[name]`, then iterates expecting entry objects with `.name`/`.value`. If
iteration yields plain strings or `(name, value)` tuples,
`compat.get(entry, "name", None)` is `None` for every entry and the function
returns `None`. `compat.get` swallows all exceptions by design
(`compat.py:86-99`), so nothing surfaces. Both `check_domain_tag` and
`check_security_enabled` then return `[]` — indistinguishable from "correctly
configured". A participant with
`dds.domain_participant.domain_tag = 'prod'` would be reported as having no blind
spot, which is the single most common cause of "same domain ID, sees nothing".
Worth an explicit INFO/WARN when the property policy is present but unreadable,
so absence of evidence is not rendered as evidence of absence. **Plausible.**

### M1

**`extensibility_map` / `key_member_paths` recurse the peer's type graph with no
visited set, once per endpoint per scan.**
`../rti_doctor/typewalk.py#L569-L584` and `#L550-L566` bound only *depth*
(`> MAX_DEPTH`, so 13 levels) — no memoization, no visited-type set, and no
global node budget like the `MAX_MEMBERS` one `_walk_aggregate` gets
(`typewalk.py:340`). Because DDS types form a DAG and struct reuse is normal in
real IDL, cost is `fan-out ^ 13`, not linear in the type.
Scenario: a peer advertises a type where each of 13 nested levels reuses a struct
with 8 members. `extensibility_map` visits 8¹³ ≈ 5.5·10¹⁰ nodes, each doing a
`resolve_alias` plus several `compat.get` reads. `system_scan.py:84` adds
`check_extensibility` for **every** endpoint, and it calls
`extensibility_map(endpoint.type)` unconditionally
(`checks/type_compat.py:250`), so the walk runs per endpoint on every scan — and
every TUI screen open triggers a scan. The result dict is keyed by type name, so
it already dedups on output; a `seen` set makes it linear with no behaviour
change. `report.py:348-350` hits both functions on the report path.
Related: `count_members` (`typewalk.py:239-249`) has the identical shape and no
callers anywhere — dead code worth deleting rather than leaving as a trap.
**Plausible** (depends on a peer advertising a wide reused type graph).

### M2

**`_fastdds_product_versions` zips four independently-parsed occurrence lists
with no length check, so one missing subfield discards the whole version.**
`../rti_doctor/wire.py#L135-L136`. `zip` truncates to the shortest list, so if
tshark omits or renames any one of the four `product_version` subfields the
version is dropped wholesale — including the major/minor that *were* present —
and unequal lengths across a multi-occurrence frame mispair the survivors into a
version never on the wire. `zip(*[["3"],["6"],[],["0"]])` is empty, so an empty
`release` silently discards a fully-readable 3.6.x.
The trigger is real: `tshark -G fields` on the installed Wireshark 4.4.9 lists
**both** `rtps.param.product_version.release` and
`…release_string`, i.e. the dissector renders that octet under a second field
name on at least one branch, and `wire.py:411` requests only the numeric one.
Independent of [C1](#c1) and survives fixing it. Suggest requiring all four lists
to be the same non-zero length (or zipping with an explicit fill and reporting
the partial form), plus `-e …release_string` as a fallback.
**Confirmed** (behaviour) / **Plausible** (trigger).

### M3

**`_walk_union` treats unparseable labels as "this is the default member", and an
unparseable discriminator as "no member matches".**
`../rti_doctor/typewalk.py#L383-L391`. Two distinct conditions collapse into
`label_values == []`: a genuinely label-less member (correctly the IDL default)
and a member whose labels could not be converted. For an enum-discriminated union
whose `labels` come back as enumerator objects rather than ints, the *first*
member becomes `default_member` and — since `int(disc_value)` also raises and
`continue`s past every member — is walked as the active one. Reading an inactive
union member makes DynamicData raise, `_walk_member` records `FAILED`, and
`WalkReport.verdict` (`typewalk.py:87-89`) downgrades a perfectly readable
cross-vendor sample to `PAYLOAD_FAILED`/`PARTIAL`. If no member is label-less,
the walk instead emits "no union member matches discriminator …" (`:395`) for a
healthy sample. Track `labels_unreadable` separately from `labels == []`, hoist
`int(disc_value)` out of the loop, and report its failure as "discriminator not
comparable". No union fixture exists in `test/vendors/shared_idl/`, so neither
path has coverage. **Plausible.**

### M4

**`Session.system_scan` is not re-entrant and nothing in the app serialises
scans.**
`../rti_doctor/engine.py#L66-L102`, with `views/system_overview.py:43` and `:80`.
There is no lock anywhere in the package (`grep -rn "Lock\|threading"
rti_doctor/` returns nothing). `_spawn` calls `screen.run_worker(...)` without
`exclusive=True`, and `_scan` dispatches
`asyncio.to_thread(screen.session.system_scan, None, max_age)`, so two `r`
presses in quick succession run `system_scan` in two executor threads against one
`Session`.
Scenario, traced through `engine.py:80-89`: with a Fast DDS peer present and a
startup capture attached, thread A passes the `discovery_capture is not None`
guard; before it reaches `:84` (`self.discovery_capture = None`), thread B passes
the same guard. Both call `finish_discovery()` on the same `LiveCapture`: two
`terminate()`/`wait()` sequences and two `inspect_discovery_pcap` reads of the
same file. If A executes `self._log = None` (`wire.py:542`) between B's
`if self._log is not None` check and B's `self._log.close()` (`:540-541`), B
raises `AttributeError` which propagates into `_scan`'s handler and renders as
"Scan failed" — a capture-teardown race reported to the operator as a failed DDS
scan, with `discovery_capture` still set so the next refresh repeats it.
Independently and unconditionally: both threads write `self._last_scan` (`:101`),
so if the earlier-started scan finishes last the snapshot timestamp goes
backwards and `_last_scan` serves the older snapshot to the next screen within
`SCAN_REUSE_SECONDS`. **Plausible** (the missing lock and missing `exclusive=`
are confirmed; the interleaving is timing-dependent).

### M5

**The scan copies the whole endpoint dict `P + T + 2W` times, and screen
navigation re-pays it every 3 s.**
`../rti_doctor/system_scan.py#L64-L109` plus `../rti_doctor/discovery.py#L92-L96`.
Every registry query materialises a fresh `list(self.endpoints.values())` and
then filters it (that materialisation *is* the 08-06 H2 fix), so each call is
2·E. Per scan: P from `endpoints_for` (`static_discovery.py:357`), T from
`endpoints_on_topic` (`type_compat.py:120`), W from `type_compat.py:168`, W from
`qos_match.py:270`, plus 4 constants.
At E=600, W=300, T=150, P=60 that is ~814 full copies, ~1M element visits. The
08-06 review's own measurement is 0.080 s at 96 endpoints
(`CODE_REVIEW_2026-08-06.md:162`); scaling quadratically gives ~3 s at 600 and
~13 s at 1200. `SCAN_REUSE_SECONDS = 3.0` (`system_overview.py:21`) means any
screen opened more than 3 s after the last scan pays it again, five screens deep.
Building `{topic_name: [endpoints]}` and `{participant_key: [endpoints]}` once per
scan removes every term but the four constants — and would also close the O(E²)
term the 08-06 M2 note claimed to remove, which is only partly gone.
Secondary, same loop: `check_assignability` (`type_compat.py:166-180`) runs
`_assignable(reader.type, writer.type)` for every writer×reader pair on a topic,
so a topic with 50 writers and 50 readers costs 2500 full schema comparisons per
scan.
The UI side of the same problem: `views/system_overview.py:492-536` calls
`endpoints_for` once per participant and `_health` once per row, and `_health`
walks all `snapshot.issues` per row — so at 500 participants / 5 000 endpoints /
300 issues, pressing `1` performs ~2.5M record comparisons plus 150k issue
comparisons **synchronously on the event loop**, with no worker and no progress
indication. **Confirmed** (call counts follow from the cited lines; the timing
extrapolation is from the 08-06 measurement).

### M6

**The discovery poll runs synchronously on the Textual event-loop thread.**
`../rti_doctor/app.py#L31-L36`. `_refresh` is a plain function, so Textual's
timer invokes it inline in the event-loop task. Per tick it makes one
`discovered_participants()` call plus one `discovered_participant_data()` C call
per remote participant — each copying the full `ParticipantBuiltinTopicData`
including locator and transport sequences — then allocates and merges a fresh
`ParticipantRecord` per peer (`discovery.py:436-476`), then walks all E endpoints
in `expire_type_waits`. At 300 remote participants that is 300 binding
round-trips + 300 record constructions + E state checks every `--interval`
seconds (default 2.0), with the UI blocked and keystrokes queued behind it.
This is also the mutator that races the worker-thread scans in [M4](#m4) and the
record state machine in [M7](#m7), so moving it to `run_worker(thread=True)`
would fix the stall but *increase* the concurrency exposure — the two need fixing
together. **Confirmed** for the synchronous invocation; the stall magnitude is
**Plausible**.

### M7

**The type-resolution state machine is mutated from two threads with no
synchronisation, and can latch UNAVAILABLE on an endpoint whose type is
present.**
`../rti_doctor/records.py#L124-L140` (`expire_type_wait`) vs `#L109-L122`
(`note_type`), reached from `discovery.py:189-190`. `expire_type_waits()` runs on
the event-loop thread (`app.py:36`) and on scan worker threads (`engine.py:79`,
`:106`, `:128`, `:182`); `note_type` runs on Connext receive threads via
`_merge_endpoint`. No lock.
Interleaving: thread A enters `expire_type_wait`, reads
`type_state != TYPE_PENDING` → False, `type is not None` → False, computes the
timeout → True, and is about to execute `:138`. Thread B runs `note_type(t)`:
sets `type = t` (`:119`), `type_state = TYPE_RESOLVED` (`:121-122`). Thread A then
executes `type_state = TYPE_UNAVAILABLE`.
The resulting state is self-contradictory and sticky: every later
`expire_type_wait` returns False at `:130` because the state is no longer
PENDING, so only another re-delivered discovery sample can repair it. Meanwhile
`check_type_state` (`type_compat.py:24-57`) falls through both the RESOLVED
(`:30`) and PENDING (`:43`) branches and emits the `type.no_type_info` **ERROR**,
while `check_assignability` (`:166`, gated on `endpoint.type is None`) happily
compares that same endpoint's schema and `probe_endpoint` (`probe.py:386`)
creates a reader from it. One report then says the type never arrived *and* uses
it. The window is a few bytecodes wide but centred on exactly the instant type
resolution lands, and `expire_type_waits()` fires every `--interval` seconds plus
once per scan and per diagnosis. The `DiscoveryRegistry` docstring's safety
argument (`discovery.py:18-28`) covers dict-level atomicity only, not per-record
state. **Plausible.**

### M8

**Topology rows come from the live registry while the Health column comes from
the stored snapshot, so one row mixes two observation times.**
`../rti_doctor/views/system_overview.py#L496-L520` vs `#L524-L536`.
`_render_table` reads `self.session.registry` (mutating continuously from
discovery listeners) but `_health` reads `self.snapshot.issues` (frozen at the
last scan, up to `SCAN_REUSE_SECONDS` stale on open and *unbounded* afterwards,
since `action_participants`/`readers`/`writers`/`topics` re-render without
re-scanning).
Scenario: a participant with an unroutable locator is discovered after the last
scan, or the operator has been switching modes with `1`-`4` for a minute. Its row
appears with current reader/writer/topic counts and Health "OK", because no issue
in the stale snapshot references it. **Confirmed.**

### M9

**`IssueListScreen`'s `issue_keys` filter is frozen at push time and mislabels
itself "All".**
`../rti_doctor/views/system_overview.py#L282`, `#L313-L321`, `#L332`, `#L343`.
`TopologyHealthScreen.action_issues` (`:567-569`) passes a set of issue keys
captured from the current snapshot; `_refresh` re-scans but `_visible_issues`
keeps filtering against that stale set, and `scope` at `:332` is `"All"` whenever
`severity is None`, never accounting for `issue_keys`.
Scenario (a): press `i` on a participant, then `r` — a genuinely new issue on
that participant cannot appear, because its key is not in the frozen set; the
operator sees a fresh timestamp over a stale filter. Scenario (b): press `i` on a
participant whose only problems are domain-scoped (see [H4](#h4)) and the screen
reads "All issues, snapshot 12:34:56: 0 Errors | 0 Warnings | 0 Notes" —
indistinguishable from a clean domain. **Confirmed.**

### M10

**The verdict line drops the problem summary on every non-FULL payload.**
`../rti_doctor/findings.py#L196-L216`. `_problem_summary` is appended in the
`PAYLOAD_FULL` branch (`:196-199`) but in neither `PARTIAL` branch (`:201-214`)
nor the `FAILED` fallthrough (`:216`).
Scenario: probe matched, samples arriving, payload PARTIAL, plus two unrelated
ERROR findings. The verdict reads "…payload PARTIAL (3 of 40 members
unreadable)" with no mention of the errors — while the *better* outcome (FULL)
would have said "; 2 ERROR". `render_sweep_text` (`report.py:585`) prints this
verdict as the sweep row, so the summary table hides them too. The exit code is
derived from findings (`__main__.py:430`), so exit-status correctness is
unaffected. **Confirmed.**

### M11

**The two cleanups share one `try`, so a capture-teardown failure skips
`participant.close()`.**
`../rti_doctor/__main__.py#L546-L550` and `#L528-L529`.
`close_discovery_capture` (`engine.py:60-64`) is not exception-free:
`self._log.close()` (`wire.py:541`) can raise `OSError`, the
`kill()`/`wait()` after a `TimeoutExpired` (`:534-535`) is unguarded, and
`inspect_discovery_pcap` only catches `OSError`/`TimeoutExpired` around the
subprocess. Any of those and the `except Exception` at `:549` logs one line with
the participant still open at interpreter exit. The early-return path at
`:528-529` is worse: unguarded, so a raising `close_discovery_capture()` skips
`participant.close()` *and* the `return 3`. `engine.close_discovery_capture` also
assigns `self.discovery_capture = None` only after `finish_discovery()` returns,
so a raise leaves the capture attached for a retry that will re-terminate a dead
process. **Confirmed** (the ordering skips the close); **Plausible** that
`finish_discovery` raises in practice.

### M12

**`--format json` produces no JSON at all on the two non-zero non-error exits.**
`../rti_doctor/__main__.py#L386-L395` and `#L524-L530`. The topic-not-found path
(exit 2) prints three human sentences to stderr and returns without calling
`render_json`/`_emit`; the readiness-timeout path (exit 3) does the same. Neither
honours `--output`.
Scenario: `rti_doctor -d 1 -t Absent --format json -o r.json; jq . r.json` →
`r.json` does not exist, exit 2. A JSON consumer has to special-case "no output"
as a third state, which is what `--format json` exists to avoid. **Confirmed.**

### M13

**A startup failure and "found ERROR findings" are both exit 1, so the documented
exit contract cannot express "could not run".**
`../rti_doctor/__main__.py#L519` (no guard) + `#L553-L558`.
`build_session` → `discovery.create_participant` is outside any `try`, and the
`__main__` guard catches only `KeyboardInterrupt`, so any startup exception
(out-of-range domain, missing or expired license, participant creation failure)
becomes an uncaught traceback → CPython exit **1**.
Scenario: `rti_doctor -d 500 --all --format json` — `parse_args` only rejects
negatives (`:137`), so 500 reaches Connext, which raises; CI reads exit 1 as
"ERROR findings were found on domain 500" and gets no JSON. Recommend a distinct
code (e.g. 4) for "could not run". **Confirmed** (mechanism); **Plausible** for
this specific trigger.

### M14

**`--ready-timeout` is the one numeric flag omitted from the finiteness check,
and `inf` produces an unbounded hang.**
`../rti_doctor/__main__.py#L131-L132`, `#L139-L145`, `#L354`. The
`for name in ("probe_timeout", "type_wait", "settle", "scan_timeout",
"interval")` loop rejects NaN/inf; `ready_timeout` is validated only by `<= 0`
(`:131`), which both `inf` and `nan` pass.
Scenario: `--ready-after-participants 1 --ready-timeout inf` →
`deadline = time.monotonic() + inf`, `while time.monotonic() < inf` never
terminates, so the process spins forever instead of failing at the timeout.
`--ready-timeout nan` inverts the flag instead: the loop is skipped and it
returns exit 3 immediately. This is a residual of 08-04 M10, which the 08-06
review lists as Open but which is otherwise fixed in current source.
**Confirmed.**

### M15

**`run_tests.sh` truncates failure output to 40 lines, and `all` does not run all
suites.**
`../run_tests.sh#L78` and `#L39-L46`. `… -m unittest "${QUALIFIED[@]}" -v 2>&1 |
tail -40`: the exit status does propagate (`pipefail` at `:18`) and the
`OK (skipped=N)` summary is inside the window, so skips are reported honestly —
but with `-v` over 166 tests, `unittest` prints each `FAIL`/`ERROR` traceback
*before* the summary, so more than one or two failures are truncated away and the
developer sees only the count. Separately,
`test/test_fastdds_type_metadata_spike.py` appears in none of
`UNIT`/`LIVE`/`VENDOR`, so the header comment "`all` everything" is false —
see [S13](#s13). **Confirmed.**

### M16

**`rich` is imported directly but undeclared, `textual` is unpinned, and a
dev-only package ships to users.**
`../requirements.txt#L4-L5`. `views/system_overview.py:8` does
`from rich.markup import escape`, which works only because `rich` is a transitive
dependency of `textual`; a future textual release that drops or vendors it breaks
the TUI with no requirements change. `textual` itself is unpinned while the code
uses churn-prone APIs (`TabbedContent`/`TabPane`, `run_worker`,
`on_screen_resume`), and `run_rti_doctor.sh:19` installs this file on **every
end-user launch**, so a breaking textual release lands on users silently.
`textual-dev` is a development tool and does not belong in the runtime file the
launcher syncs. **Plausible.**

### M17

**The `no_type_info` fault fixture degrades to a healthy fixture on a warning.**
`../test/fixture_publisher.py#L196-L199`. If
`resource_limits.type_object_max_serialized_length` is ever renamed, the `except`
prints one `WARNING:` line to stderr and the fixture then publishes **with** full
type propagation while still announcing itself as `no_type_info`.
`./test/run_manual_scenario.sh -s no-type-info` would print "Expected result:
type.no_type_info" over a fixture that cannot produce it, and the warning scrolls
past under the pip-sync output from `:185-187`. A hard `sys.exit` is the right
behaviour for a fault-injection fixture that cannot inject its fault.
**Plausible.**

### S5

**The SPDP2 bitmask path is never executed by its own tests.**
`../rti_doctor/checks/blind_spots.py#L76-L83`. `_spdp2_enabled` resolves the mask
flag and tests it as a bit *first*, with substring matching only as a fallback —
that ordering is the 08-06 M12 fix and the docstring explains why. But both tests
pass a plain Python string: `FakeDiscoveryConfig("SPDP2_DISCOVERY")`
(`test_checks.py:142`) and `FakeDiscoveryConfig("SDP")` (`:147`).
`int("SPDP2_DISCOVERY")` raises `ValueError`, which is caught, so control always
reaches the substring fallback.
Surviving defect: invert the bit test to `not bool(int(plugins) & int(flag))` and
both tests still pass — `blind.spdp2` then fires on every standard-SPDP
participant, and it is an ERROR that suppresses `match.none` and `endpoint.none`
(`findings.py:76-77`, `:95-96`), i.e. it hides the real symptoms.
**Confirmed.**

### S6

**Four `static_discovery` checks and one `blind_spots` check have zero tests, and
the "must stay quiet" tests cannot see them because they only look at ERROR.**
No test references `check_security_enabled` (`blind_spots.py:116`),
`check_transport` (`static_discovery.py:249`), `check_security_mismatch`
(`:281`) or `check_partial_configuration` (`:330`). All four emit WARN/INFO, and
`test_clean_config_produces_no_blind_spot_errors` filters
`severity >= f.Severity.ERROR` (`test_checks.py:128`), as do the live and vendor
healthy-path assertions.
Surviving defect: change `has_udp = "UDP" in joined` to `"TCP" in joined` at
`static_discovery.py:255`. Every healthy UDPv4+SHMEM peer gets **WARN "Peer
advertises no UDP transport"** in every scan, and unit, live and vendor tiers all
stay green. `records.transport_text` (`records.py:221-228`), which renders its
`observed`, is likewise untested. Same shape for `check_security_mismatch`:
invert the guard at `:311` and every peer whose extended endpoint mask differs
from its base mask gets a spurious "security posture differs" INFO — the only
registries that reach it in tests have both masks `None`, so the function returns
at `:291` before the logic runs. **Confirmed.** The generalisable fix is to add
one healthy-system assertion that requires *zero findings at any severity*, not
zero ERRORs.

### S7

**The scan cache's freshness contract is untested, and the stub session ignores
`max_age` entirely.**
`../rti_doctor/engine.py#L74-L77`. `Session.system_scan` reuses `_last_scan` only
when `max_age > 0 and captured_at is None`; the `captured_at is None` clause is
what makes an operator's explicit `r` always re-scan while merely opening a
screen may reuse (`system_overview.py:141`, `:219`, `:300`, `:482`, `:710` pass
`SCAN_REUSE_SECONDS`; `:143`, `:229`, `:305`, `:485`, `:712` pass 0). Every test
of `system_scan` passes `captured_at=123.0` (`test_system_scan.py:49`, `:66`,
`:80`, `:99`), bypassing the cache; `test_views.StubSession.system_scan`
(`test_views.py:68-72`) accepts `max_age` and ignores it, and its first parameter
is still named `scope` — a stale name that survived because `_scan` calls it
positionally (`system_overview.py:80`).
Surviving defect: change `captured_at is None` to `captured_at is not None` at
`engine.py:75` and every explicit operator refresh silently returns the cached
snapshot forever — the exact "stale data with no marker" failure
`test_views.py:135` was written to close — with no test failing, because the stub
never has a cache. **Confirmed.**

### S8

**`typewalk.py` is 584 lines with one test, and the recorded reason it cannot be
unit-tested is false.**
`typewalk` touches `dds` only through two defensive `getattr` calls
(`../rti_doctor/typewalk.py#L112`, `#L223`); `walk_sample`, `_walk_aggregate`,
`_walk_union`, `_walk_member`, `_walk_collection`, `_read_member`,
`_member_present`, `_collection_length`, `_enum_sanity`, `count_members`,
`key_member_paths` and `extensibility_map` are entirely duck-typed and testable
in the unit tier, which already imports `rti.connextdds` (`run_tests.sh:12-13`).
08-04 S3's premise that "the traversal needs `dds`" is wrong, which is presumably
why the gap is still open. The only unit coverage is `WalkReport.verdict` with
`truncated=True` (`test_findings.py:109-122`).
Two named branches never executed by any test: the over-bound collection FAILED
branch at `typewalk.py:462-467` — the single path that converts a
length/encoding disagreement into a `FAILED` member, and no fixture publishes an
over-bound sequence — and `_collection_length` returning `None` (`:302-313`),
whose "length not reported by this version" branch a real Connext reader cannot
reach. Deleting either changes no test result. **Confirmed.** This module
produces the headline verdict, so it is the highest-value place to spend test
effort.

### S9

**Five probe checks are invoked by no test, and `FakeProbe`'s defaults make two
of them unfireable.**
`check_probe_error` (`probe_match.py:78`), `check_inconsistent_topic` (`:269`),
`check_partition_overlap` (`:292`), `check_cache_drops`
(`probe_payload.py:342`) and `check_payload_walk` (`:387`) appear in no test.
`FakeProbe` (`test_checks.py:433-461`) hardcodes `inconsistent_topic_count = 0`
and `cache = {}`, so two of them cannot fire even if a test tried.
Surviving defect: change `if not failed and walk.truncated` to
`if not failed or walk.truncated` at `probe_payload.py:410` and every fully-read
sample is reported as `payload.partial`; `test_findings.py` covers
`WalkReport.verdict` and `verdict_line`, not this check, so nothing fails.
Related smell: `probe_match.py:101` reads `getattr(probe, "error", None)` rather
than `probe.error`, because `FakeProbe` omits an attribute the real
`ProbeResult` always sets (`probe.py:64`) — production defensiveness added to
accommodate a fake. **Confirmed.**

### S10

**Two guard clauses in the RxO comparison have no test.**
No test passes `-1` — Connext's AUTO sentinel (`records.py:201`) — in a
representation list; every case uses only ids 0 and 2
(`test_checks.py:598-611`, `:700-701`). Delete
`and -1 not in writer_ids and -1 not in reader_ids` at
`../rti_doctor/checks/qos_match.py#L240` and a default-AUTO writer against an
XCDR2-only reader produces a false ERROR `qos.rxo_mismatch` between two endpoints
that match perfectly — and `qos.rxo_mismatch` is an exit-code-1 finding.
`_partitions_overlap`'s wildcard branch (`#L135`, `fnmatchcase` in both
directions) and the empty-default-vs-named case are likewise untested — the only
partition case is literal `["writer"]` vs `["reader"]`
(`test_checks.py:702-703`). Delete the `fnmatchcase` line and every
wildcard-partition pair in a real system is reported as a PARTITION
incompatibility, with no test failing. **Confirmed.**

### S11

**`run_headless_topic`, the primary headless entry point, has no test outside the
licensed and dockered tiers.**
`test_cli.py` drives `run_headless_all` and `run_headless_domain` only. Two
branches of `run_headless_topic` are executed by nothing: the `--pcap` path
(`../rti_doctor/__main__.py#L418-L421`) and the `-o/--output` path (`#L425-L428`,
i.e. `_emit` plus the "Report written to" / "VERDICT:" lines a CI job would
parse). `run_headless_domain --format json` (`#L485`) is also never exercised —
`_args()` defaults to text (`test_cli.py:54`). This is where [M12](#m12) lives.
**Confirmed.**

---

## Low

### Q6

**Partition wildcard-vs-wildcard matching is more permissive than DDS
partition-expression matching.**
`../rti_doctor/checks/qos_match.py#L134-L136` runs `fnmatchcase` in both
directions unconditionally, so two *expressions* can match each other.
Scenario: writer `PARTITION = ["A*"]`, reader `PARTITION = ["*"]` →
`fnmatchcase("A*", "*")` is True → overlap → no PARTITION finding. The DDS rule
matches a wildcard expression against a literal partition *name*;
expression-vs-expression is matched by string equality. The direction of error is
a miss (false OK), not a false alarm, and only for double-wildcard
configurations. **Plausible** — RTI's exact expression-vs-expression behaviour was
not confirmed against spec text during this review, so verify before changing.

### X10

**XCDR2-only detection uses exact list equality.**
`../rti_doctor/checks/type_compat.py#L331` — `if ids == [2]` misses `[2, 1]`
(XCDR2 + XML) and `[2, 2]`, both of which still share no representation with an
XCDR1-only reader; those fall through to the OK `repr.offered` finding.
`2 in ids and 0 not in ids` is the correct test. Low practical weight — XML
representation is rare — but it is a false negative in the direction that matters.
**Plausible.**

### L1

**`records.locator_ip` ignores the locator kind, so a non-UDPv4 participant is
reported with a fabricated IPv4 address.**
`../rti_doctor/records.py#L143-L157`, consumed at `discovery.py:460` →
`report.py:259`. `locator_ip` returns `".".join(octets[-4:])` with no check of
the locator's `kind`. For an IPv6 (`kind=2`) or SHMEM locator this renders the
last four bytes of a 16-byte address as a dotted quad, and `first_locator_ip`
takes the first locator that yields anything — so `ParticipantRecord.ip` for an
IPv6-only peer is a plausible-looking IPv4 address that exists nowhere, printed
as the peer's address. `wire.capture_filter` gets this right (`wire.py:284`
explicitly skips `kind != 1` before calling the same helper), so the guard exists
in the codebase, just not on the report path. This contradicts the module
contract at `compat.py:8-11`: "A diagnostic that quietly invents a zero is worse
than one that admits it cannot see." **Confirmed** that no kind check exists;
**Plausible** that an IPv6/SHMEM-first participant is encountered.

### L2

**`listener_events` grows without bound from middleware callbacks and is
rendered in full.**
`../rti_doctor/probe.py#L112` appends one string per `SAMPLE_LOST` /
`SAMPLE_REJECTED` / `SUBSCRIPTION_MATCHED` / `REQUESTED_INCOMPATIBLE_QOS`
callback, and also emits a `logging.info` per event, from the Connext callback
thread. On a lossy cross-vendor link a fast remote writer fires `on_sample_lost`
per lost sample for the whole `--probe-timeout` window, and
`report.py:410-413` prints **every** entry with no cap. A cap with an "N earlier
events elided" marker matches how `_short_repr`/`_sample_repr` already bound
peer-controlled text in these modules. **Confirmed.**

### L3

**`selected_key` survives a re-render that resets the cursor.**
`../rti_doctor/views/system_overview.py#L466`, `#L485-L490`, `#L538-L543`.
`_render_table` does `clear(columns=True)` and rebuilds without restoring or
clearing `self.selected_key`, unlike `IssueListScreen._render_snapshot`
(`:343-345`) which explicitly restores the cursor to the previously selected key.
Scenario: highlight participant #7, press `r`, and the participant has since
departed. The cursor is visibly on row 0 but `selected_key` still holds the
departed key, so `o` → `registry.participants.get(stale_key)` → `None` → silent
no-op with no status message (`:588-600`), and `i` → an issue list filtered on a
key nothing matches → the empty "0 Errors" screen of [M9](#m9).
**Plausible** (depends on whether Textual re-emits `RowHighlighted` after the
rebuild; the departed-key half is unconditional).

### L4

**`check_extensibility` passes the raw type map as `evidence`, sharing a
namespace with `_annotate`'s injected identity keys.**
`../rti_doctor/checks/type_compat.py#L268`, `#L289` (`evidence=mapping`) vs
`../rti_doctor/system_scan.py#L176-L194`. `extensibility_map` returns
`{type name: extensibility}` (`typewalk.py:569-584`), and `_annotate` then
`setdefault`s `scope`, `endpoint_key`, `participant_key`, `topic_name`,
`writer_key` into that same dict.
Scenario: an IDL aggregate named `topic_name` or `scope` → the `setdefault` is a
no-op → `_issue_key` and `SystemIssue.topic_name` take the extensibility kind
(`"APPENDABLE"`) as the topic, so the Issues table shows Topic "APPENDABLE" and
`_health(topic_name=…)` never links it; a type named `scope` sets
`SystemIssue.scope` to "FINAL". Low likelihood, but the fix is free — nest the
map under one key. **Plausible.**

### L5

**`s` on a severity-filtered issue list saves an unfiltered report with different
issue numbers.**
`../rti_doctor/views/system_overview.py#L367-L373` vs `../rti_doctor/report.py#L121`.
The screen numbers rows 1..N over `_visible_issues()`; `render_system_text`
numbers 1..M over `snapshot.issues`. Filter to Errors, see two rows numbered 1-2,
press `s`, and the file contains all 40 issues with `[1]`/`[2]` being different
issues than the ones on screen. Defensible as "a system report is always whole",
but the numbering makes screen references unusable against the file.
**Confirmed.**

### L6

**Exit code 2 means both "bad command line" and "topic not found".**
`parser.error()` exits 2 (argparse default) — `../rti_doctor/__main__.py#L128`,
`#L130`, `#L132`, `#L138`, `#L143`, `#L145` — which is the same code the README
documents for "the named topic was not found" (`#L395`). A CI wrapper written to
treat 2 as "topic absent, retry later" retries forever on
`rti_doctor -t X --format jsn` (typo) or `--probe-timeout -1`. **Confirmed.**

### L7

**The cleanup trap is installed after the background children are started.**
`../test/run_manual_scenario.sh#L244-L254` and `#L324-L342`.
`start_rxo_endpoint … &` (`:244`), `sleep 1` (`:246`), second `&` (`:247`), and
only then `trap cleanup EXIT INT TERM` (`:254`). The `sleep 1` guarantees at
least a one-second window in which Ctrl-C leaves the first child — or, at
`:326-333`, a `docker run --network host` container — orphaned with nothing to
reap it. Install the trap before the first `&`. **Confirmed.**

### L8

**`fixture_publisher` scale mode has no cleanup path and divides by an
unvalidated argument.**
`../test/fixture_publisher.py#L164-L167` and `#L142`. Every other mode wraps its
publish loop in `try/except KeyboardInterrupt … finally: participant.close()`
(`:256-275`); `run_scale` calls a bare `time.sleep(args.duration)` then closes,
so a SIGINT during the sleep propagates out of `main()` as a traceback and exit 1
with 6 participants unclosed — a harness that stops the fixture with SIGINT sees
a failure on a successful fixture. Separately
`topic_name = f"…{(index * 7 + slot) % args.scale_topics:02d}"` raises
`ZeroDivisionError` for `--scale-topics 0`, which argparse does not reject.
**Plausible.**

### S12

**`read -rsn1` EOF yields an empty key that matches the Enter branch, so Ctrl-D
launches the highlighted fixture instead of cancelling the menu.**
`../test/run_manual_scenario.sh#L93`. `set -e` is suppressed inside the function
because it is called in a `||` list. **Re-verified** during the diff review, with
stdin from `/dev/null`.

### S13

**`test/test_fastdds_type_metadata_spike.py` is in no `run_tests.sh` tier.**
The UNIT/LIVE/VENDOR lists (`../run_tests.sh#L26-L46`) cover 18 of the 19
`test_*.py` modules; this one (132 lines, 3 tests) is absent, so no documented
entry point ever runs it — despite the header comment saying the list lives there
"so the two cannot drift". Its `self.assertIsInstance(log_text, str)` at `:111`
is also a tautology (`log_text` is always `handle.read()`). **Confirmed.**

### S14

**Assorted test hazards.**
* `../test/test_domains.py#L57-L60` — the "suites do not collide" guard lists 8
  keys and omits `test_scale`, one of only two suites that create real
  participants in the same `live` tier (`test_live_integration` → 104,
  `test_scale` → 203 today). A future key colliding with `test_scale` would be
  accepted by the guard.
* `../test/test_system_scan.py#L248-L249`, `#L305` — `DURATION = 1.5` × three
  tests plus `assertGreater(self.mutations, 100)` is a wall-clock- and
  load-sensitive assertion in the **unit** tier, the one CI runs; `setUp` also
  drops the global `sys.setswitchinterval` to 1e-6. On a loaded machine this
  fails for reasons unrelated to the race it guards.

---

# Cross-cutting themes

## 1. Dedup identity and linkage identity are the same field, and they conflict

`_issue_key` (`system_scan.py:235-247`) folds entity identity into the dedup key,
and `_annotate` (`:176-194`) stamps that same identity for the Health column and
the `i` filter to read. One field cannot do both jobs, and every combination
currently fails somewhere:

| Finding | Declares | Consequence |
|---|---|---|
| `type.name_conflict` | `scope: topic` | dedups correctly, participants show "OK" ([H4](#h4)) |
| `type.extensibility` | no scope | links correctly, 96 duplicate WARNs ([H2](#h2)) |
| `environment.fastdds_…` | neither | one issue for N versions *and* no linkage ([C1a](#c1a), [C1b](#c1b)) |

The fix is structural: give `SystemIssue` a dedup key that is independent of the
identity set it carries, so a topic-scoped issue can dedup once and still name
every participant involved. Until that exists, each new check will land in one of
the three failure modes above.

## 2. "Unreadable" is rendered as "fine" — except where it is rendered as "broken"

This is the most consequential theme in the review, and it spans four modules.
The codebase has an explicit, well-argued discipline for missing data:
`compat.py:8-11` — "A diagnostic that quietly invents a zero is worse than one
that admits it cannot see" — and `records.py:180-183` restates it for
representation ids. Most of the code honours it. The failures are all at the
*reporting* boundary, and they split two ways:

**Unreadable rendered as compatible (false negative).** [Q3](#q3) skips
DATA_REPRESENTATION entirely for default-QoS writers and reports OK.
[Q4](#q4) makes a pair where ten policies were unreadable indistinguishable from
one where ten were compared and matched. [X4](#x4) reports "every resolved reader
is assignable (1 reader)" when 3 were resolved and 2 were unevaluable, and reports
*nothing at all* when none could be evaluated. [X8](#x8) silently disables the
domain-tag and security blind-spot checks if `PropertyQosPolicy` has an
unexpected shape. [X5](#x5) silently reverts the SPDP2 check to the substring
matching that was already found not to work. [X1](#x1) misses the multicast blind
spot entirely. [S2](#s2) is the test-side twin: because `compat.get` cannot
distinguish "field absent" from "field name wrong", and no test asserts the field
names, a one-character typo is indistinguishable at runtime from a peer that does
not advertise the policy — and that is reported as fine.

**Unreadable rendered as incompatible (false positive).** [Q1](#q1) converts an
unreadable PARTITION into a positive claim of the default partition and emits an
ERROR with exit code 1 against two endpoints that are communicating.
[Q2](#q2) treats an absent PRESENTATION boolean as an offer of `false` and emits
an ERROR. [X3](#x3) tells the operator to fix the publisher for a *reader*'s
unresolved type.

Both directions come from the same root: a finding's severity is computed from
comparison results without any record of *how much was comparable*. A single
structural change addresses most of it — make every check carry an explicit
`evaluated` / `unreadable` account in its evidence, render that in the observed
line, and forbid any `Severity >= WARN` that rests on a value the tool did not
actually read. That is a bigger change than any individual fix above, and it is
the one worth designing deliberately.

## 3. Broad exception swallowing in a tool whose product is trust

There are 57 `except Exception` sites across `rti_doctor/`, a dozen of which
`pass` silently (`engine.py:200`, `checks/qos_match.py:69`, `compat.py:213`,
`:217`, `typewalk.py:227`, `:231`, `discovery.py:277`, `:298`, and others). Most
are deliberate and documented — `compat.get`'s "never replaced by an assumed
value" contract is exactly right, and it is what makes theme 2 a *reporting*
problem rather than a data-handling one. The swallowing is defensible; what is
not is that nothing downstream distinguishes a swallowed read from a real answer.

## 4. Where a recorded fix is narrower than the problem it describes

Six findings are cases where a recorded fix correctly addressed the instance in
front of it and left the general case open — in several cases with a comment in
the source accurately describing the general case:

| Finding | Recorded fix | What was left |
|---|---|---|
| [H2](#h2) | 08-06 I7 | only the clean branch was demoted to OK |
| [H4](#h4) | 08-06 M1 | dedup was achieved by withholding the identity the UI needs |
| [M5](#m5) | 08-06 M2 | the `lru_cache` removed one O(E²) term of several |
| [X3](#x3) | 08-06 H5 | the `is_writer` guard went at one call site, not in the check |
| [X5](#x5) | 08-04 M12 | the bit test is right but falls back to the broken path unannounced |
| [M14](#m14) | 08-04 M10 | five of six numeric flags validated |

These are not regressions; they are unfinished fixes, and they are worth
reopening under their original IDs rather than filing fresh. The pattern is
consistent enough to be worth a habit: when fixing a finding, check whether the
same call is reachable from another path, and whether the fix belongs in the
callee rather than the caller.

## 5. The machine-readable contract is not machine-readable

[H1](#h1), [C2](#c2), [M12](#m12), [M13](#m13) and [L6](#l6) compound: through
the documented entry point, `--format json` emits non-JSON preamble; `--all`
silently skips the rung-0/1 audit; two exit paths emit no JSON at all; exit 1
conflates "found errors" with "crashed"; and exit 2 conflates "bad flag" with
"topic not found". A CI job written against the README today cannot reliably
distinguish a healthy domain from a tool that failed to start. `DOC-3` in
`IMPROVEMENT_BACKLOG.md` anticipates part of this; the scope is larger than that
entry suggests.

---

# Re-verified as genuinely fixed

Checked against current source and confirmed correct, so they should not be
re-litigated:

* **08-06 H1** — `topology` is imported at `__main__.py:9-10`; the `--all`
  NameError is gone.
* **08-06 H2** — all five registry queries filter a materialised
  `endpoint_list()`; the mid-scan mutation crash is closed (at the cost
  quantified in [M5](#m5)).
* **08-06 H3** — `refresh_participants` guards the unreadable-handle fetch (but
  see [H10](#h10) for the rest of the loop).
* **08-06 H4** — `_correlate`'s `uncorrelated()` path is correct.
* **08-06 H5** — `check_type_state` is gated on `is_writer` at
  `system_scan.py:93-99`.
* **08-06 M6** — `find_writer` is sorted and stable.
* **08-06 I5** — all five system screens share the failed-scan status-line
  convention, driven headlessly by `test/test_views.py`.
* **08-04 M9 (timeout half)** — `inspect_pcap` now passes
  `timeout=TSHARK_READ_TIMEOUT` (`wire.py:362`). The memory half remains open, as
  the 08-06 review states.
* **08-04 M10** — validated for five of six numeric flags; see [M14](#m14) for
  the sixth.
* **08-04 M11** — `capture.start()` is inside the `try` for
  `run_headless_topic` (`__main__.py:412-414`). See [H7](#h7) for the path where
  it still is not.
* **08-04 M12** — the SPDP2 bit test genuinely precedes the substring fallback.
  See [S5](#s5) (the tests do not reach it) and [X5](#x5) (it falls back
  silently).
* **08-04 M7 — now genuinely fixed**, and the 08-06 carried-over table is out of
  date on this one. `type.name_conflict` is `Severity.WARN` at
  `type_compat.py:140`, with a root cause referring the operator to
  `type.assignability`; it no longer asserts ERROR against the tool's own schema
  comparison, and it now runs once per topic rather than per endpoint
  (`system_scan.py:88-90`). What remains on that finding is [H4](#h4), its
  linkage.

### RxO QoS comparison — audited policy by policy

The whole of `compare_endpoints` was checked against DDS 1.4. Everything below is
correct; the defects are [Q1](#q1)–[Q7](#q7) and nothing else.

* **Direction of every comparison.** `_ordered_rule` (`qos_match.py:78-92`) flags
  only `offered < requested`, and all five call sites pass `writer.X` then
  `reader.X`: RELIABILITY `:149-152`, DURABILITY `:156-159`, LIVELINESS kind
  `:163-166`, DESTINATION_ORDER `:170-176`, PRESENTATION access_scope `:178-185`.
  `_duration_rule` (`:95-108`) flags only `offered > requested` — correctly
  inverted — at DEADLINE `:187-193`, LATENCY_BUDGET `:195-201`, LIVELINESS
  lease_duration `:203-210`. Writer/reader roles are assigned at `:291-292` after
  the opposite-kind peer filter at `:270-271`.
* **All five orderings** match the spec: `:19` BEST_EFFORT<RELIABLE; `:20`
  VOLATILE<TRANSIENT_LOCAL<TRANSIENT<PERSISTENT; `:21`
  AUTOMATIC<MANUAL_BY_PARTICIPANT<MANUAL_BY_TOPIC; `:22`
  BY_RECEPTION_TIMESTAMP<BY_SOURCE_TIMESTAMP (correctly treated as *ordered*, not
  exact-match — a common error); `:27` INSTANCE<TOPIC<GROUP.
* **PRESENTATION HIGHEST_OFFERED** is deliberately left unranked (`:23-27`) so
  `_ordered_rule` declines — correct; ranking it would fail every writer.
* **OWNERSHIP** is correctly exact-match rather than ordered (`:223-232`), and
  skipped when either kind is unreadable.
* **DATA_REPRESENTATION is correctly directional** — `writer_ids[0] in
  set(reader_ids)`, not a set intersection (`:241`), with the reasoning stated at
  `:234-237`. This is the 08-04 M4 fix and it is right.
* **PARTITION empty-default semantics** are right: empty-vs-empty matches,
  empty-vs-named does not, and `fnmatchcase` rather than `fnmatch` is correct
  because partition matching is case-sensitive.
* **No non-RxO policy is compared.** HISTORY, RESOURCE_LIMITS, LIFESPAN,
  WRITER_DATA_LIFECYCLE, TIME_BASED_FILTER and DURABILITY_SERVICE appear nowhere
  in `compare_endpoints`; a grep across `checks/` finds them only as report prose
  in `probe_payload.py`. No false ERROR from this class.
* **No RxO policy is silently omitted.** All of RELIABILITY, DURABILITY,
  PRESENTATION (scope + both booleans), DEADLINE, LATENCY_BUDGET, OWNERSHIP,
  LIVELINESS (kind + lease), DESTINATION_ORDER, PARTITION and DATA_REPRESENTATION
  are covered. TYPE_CONSISTENCY_ENFORCEMENT is genuinely unreadable from
  discovery on all three supported Connext versions, documented at
  `compat.py:22-24`.
* **Infinity handling** (`_seconds`, `:56-75`): infinite renders as a huge float,
  so it sorts as the loosest value, which is what the inverted rules require;
  infinite-vs-infinite compares equal and passes.
* **Enum reading is version-agnostic** (`:31-53`): compares trailing enum names,
  uses `compat.first` so PRESENTATION's `access_scope` is not silently read as a
  missing `kind`, and returns `None` — i.e. declines — rather than a guessed rank
  for any unrecognised name.

### XTypes and the blind-spot audit — what is right

* **Assignability direction** (`type_compat.py:175`, `:233-241`):
  `_assignable(reader.type, endpoint.type)` → `reader.type.is_assignable_from(writer.type)`,
  i.e. target ← source. Correct per XTypes, not reversed, and the asymmetry is
  preserved.
* **Extensibility rules are not reimplemented.** FINAL/APPENDABLE/MUTABLE
  semantics, member ids, optional and key members are delegated entirely to the
  binding's `is_assignable_from`, so there is no path by which one extensibility
  kind is treated as another. This is the right call, and it is why this review
  has no finding of that shape. `extensibility_map` (`typewalk.py:569-584`) is
  descriptive only and feeds no verdict.
* **TYPE_CONSISTENCY_ENFORCEMENT is correctly scoped and hedged.** Both
  `type.assignability` (`type_compat.py:196-200`) and `type.name_conflict`
  (`:143-150`) state explicitly that the remote reader's enforcement QoS is not
  published in discovery, so the result cannot say whether the reader enforces or
  relaxes the check.
* **A missing TypeObject is framed as "no schema", never as an incompatibility.**
  `check_type_state` separates PENDING (INFO, `:43-59`) from UNAVAILABLE, and the
  UNAVAILABLE branch enumerates candidate causes — listing rti_doctor's *own*
  `request_types_filter != "*"` first — rather than asserting one. Correct
  framing.
* **`check_accept_unknown_peers`** (`blind_spots.py:201-224`): `MISSING`, `None`
  and truthy all return `[]`; it fires only on an explicit falsy value. Correct
  polarity, and ERROR is the right severity.
* **`check_nonstandard_ports`** (`blind_spots.py:239-247`): all seven defaults
  match DDS-RTPS (PB 7400, DG 250, PG 2, d0 0, d1 10, d2 1, d3 11) and each field
  name matches `RtpsWellKnownPorts`. WARN with an explicit "not proof of a
  mismatch" caveat is right, since remote port mapping is not advertised.
  Unreadable fields are skipped, which is false-positive-safe.
* **`check_domain_tag`** uses the correct property name
  `dds.domain_participant.domain_tag`, and ERROR is justified — Connext requires
  tag equality before accepting a remote participant. (Its input path is
  [X8](#x8).)
* **`suppress()` fundamentals** (`findings.py:103-115`): only `>= ERROR`
  explainers suppress, `explainer != finding.id` prevents self-suppression,
  iteration over the rules tuple is deterministic, and nothing is discarded —
  `report.py:136-140` renders a SUPPRESSED FINDINGS section by id and explainer.
  The defect is scope ([X2](#x2)), not the mechanism.
* **`repr.not_advertised`** (`type_compat.py:305-324`) is OK severity and states
  that no incompatibility may be inferred — correct, since an empty
  representation sequence is exactly what a default-QoS Connext writer looks
  like. It is the finding [Q3](#q3) should be cross-referencing.
* `compat.py` — no defects found. `to_int`'s `bool` special-case, the `MISSING`
  sentinel discipline, and `call`'s method-vs-property handling are all correct;
  `at_least`'s latent `ver[1]` IndexError is unreachable (no callers).
* `domain_scan.py` — no defects found.
* DDS entity lifecycle *inside* the DDS code — `discovery.create_participant`
  (close-on-except, factory QoS restored in `finally`),
  `domain_scan.scan_active_domains`, and `probe.probe_endpoint` /
  `probe_reader_endpoint` (`finally: _close_all(...)`, with correct
  partial-construction ordering) all hold the "always closes what it created"
  contract. The leaks in this review are process-level only: [H7](#h7),
  [M11](#m11).
* `parse_tshark_fields` / `inspect_pcap` — 9 `-e` fields, 9 parser slots,
  verified column-aligned against a real capture. This is what makes [C1](#c1)
  specifically a discovery-path defect.
* No `struct.unpack` or raw-byte slicing anywhere in the wire modules — all
  decoding is delegated to tshark and stays string-typed, so there is no
  short-buffer crash surface.
* Every peer-controlled `int()` conversion traced is guarded:
  `vendors.vendor_octets` (`vendors.py:91-100`), `records.locator_ip`,
  `typewalk._enum_sanity`, `system_scan._parse_version`.
  `wire.endpoint_entity_id` converts only `\d+` runs and masks to 32 bits.
* `capture_filter` (`wire.py:290`) validates peer-supplied locator ports with
  `0 < port <= 65535` before interpolating them into the BPF string, and passes
  the filter as a single argv element — no injection path.
* `_is_builtin_writer` (`wire.py:271`) matching on `c2`/`c3` suffixes is correct:
  user-defined writer entity kinds are `0x02`/`0x03`, so a user id ends in
  `02`/`03`, never `c2`/`c3`.
* `run_tests.sh`'s `tail -40` does preserve the exit code (`pipefail`) and the
  skip summary; only the failure bodies are lost ([M15](#m15)).

---

# Recommended order of work

Ordered by consequence per unit of effort, not by severity label.

1. **[Q1](#q1)** + **[Q2](#q2)** — the two false ERRORs. These are the worst
   findings in the review in operational terms: the tool asserts, at ERROR
   severity with exit code 1 and a specific remedy, that two healthy endpoints
   will never communicate. Both are small fixes (distinguish unreadable from
   empty; treat `None` as no-claim), and both are on the flagship
   `qos.rxo_mismatch` path.
2. **[C1](#c1)** — one-line deletion at `wire.py:406`, plus fixing the
   `test_wire_discovery.py` fixture to derive its column count from the command.
   The cheapest high-value fix in the list, and it un-latents
   [C1a](#c1a)/[C1b](#c1b)/[C1c](#c1c), which should be fixed in the same change
   so the feature lands working rather than landing broken a second time.
3. **[X1](#x1)** + **[C2](#c2)** — the two false clean bills of health on rung
   0/1. `X1` is a dead conditional plus a severity that makes its own suppression
   rule unreachable; `C2` is a missing `diagnose_domain()` call in
   `run_headless_all`. Both are small, and both are cases where the audit that
   exists specifically to catch "nothing is here and I can tell you why" returns
   nothing.
4. **[X2](#x2)** — scope the suppression. This is the one finding that can hide
   *any* other finding, so its blast radius is the whole tool. It needs a design
   decision (key the explainer set by topic/pair, and require a liveness
   condition for rung-0 explainers) before code.
5. **[S2](#s2)** — one table-driven test through `_endpoint_from_data`. The only
   thing standing between a one-character typo and a fleet-wide false diagnosis,
   and it also bounds [S10](#s10)'s and [Q1](#q1)'s blast radius.
6. **[X3](#x3)** + **[X4](#x4)** — move the 08-06 H5 `is_writer` guard into
   `check_type_state`, and make the assignability finding report evaluated vs
   resolved honestly. Both small, both on the cross-vendor path this tool exists
   for.
7. **[C3](#c3)** + **[H5](#h5)** — both in `system_overview.py`, both about the
   same two states (empty domain, failed scan) being handled inconsistently
   across five screens. One pass over all five with `report.py:111-120` as the
   reference implementation.
8. **[H1](#h1)** + **[M12](#m12)** + **[M13](#m13)** + **[L6](#l6)** — the
   machine-readable contract, as one change: prompts and progress to stderr,
   JSON on every exit path, a distinct exit code for "could not run".
9. **[S1](#s1)** + **[S3](#s3)** + **[S4](#s4)** — three small test-integrity
   fixes that make the rest of the suite's green mean something.
10. **Theme 2 as a design task** — [Q3](#q3), [Q4](#q4), [X5](#x5), [X8](#x8):
    give every check an explicit evaluated/unreadable account in its evidence,
    render it in the observed line, and forbid any `Severity >= WARN` resting on
    a value the tool did not read. Doing this once is worth more than the four
    findings individually, and it prevents the next check from arriving with the
    same defect.
11. **[H2](#h2)** + **[H4](#h4)** — the dedup/linkage split (theme 1). Also a
    design change; wants a decision before code.
12. **[H8](#h8)** + **[H9](#h9)** — decide whether the TUI should capture packets
    at all by default; if yes, bound the capture and disclose it; if no, gate it
    behind a key. Both fixes are in the same two functions.
13. **[H6](#h6)** + **[H7](#h7)** + **[M11](#m11)** + **[L7](#l7)** — cleanup and
    trap correctness, one pass each in `run_manual_scenario.sh` and
    `__main__.py`.
14. **[M4](#m4)** + **[M6](#m6)** + **[M7](#m7)** — the concurrency cluster.
    These interact (fixing [M6](#m6) alone worsens [M4](#m4)/[M7](#m7)), so they
    need one decision about where the lock goes and should not be attempted
    piecemeal.
15. **[M5](#m5)** + **[M1](#m1)** — the two scaling fixes, both index-building.
    Defer until a system large enough to feel them is available to measure
    against.
16. **[X6](#x6)**, **[X7](#x7)**, **[Q5](#q5)**, **[Q6](#q6)**, **[Q7](#q7)**,
    **[X10](#x10)** — the remaining semantic corrections, each small and
    independent. [Q6](#q6) should be verified against RTI's actual
    expression-vs-expression behaviour before being changed.
17. Everything else, as encountered.

Not on this list: `HAR-6` (three red Fast DDS vendor e2e tests) from
`IMPROVEMENT_BACKLOG.md`, which is unchanged by this review and is still the
prerequisite for trusting the vendor tier at all. Note that [C1](#c1) may bear on
it — a Fast DDS discovery investigation conducted through
`inspect_discovery_pcap` would have been reading mislabelled columns.

# Test gaps implied by these findings

Each of these would have caught a finding above, and none exists today.

| Missing test | Would have caught |
|---|---|
| `parse_discovery_fields` fed the output of the actual `-e` list, or asserting `len(command -e entries) == parser slots` | [C1](#c1) |
| `run_headless_all` on a registry with zero participants and a blind-spot condition set, asserting a non-empty audit | [C2](#c2) |
| `SystemOverviewScreen` / `IssueListScreen` on an empty registry whose snapshot has one ERROR, asserting the count is shown | [C3](#c3) |
| Any test of `--format json` that parses stdout of the *wrapper script* | [H1](#h1) |
| A registry with N endpoints sharing one FINAL type, asserting exactly one `type.extensibility` issue | [H2](#h2) |
| `_endpoint()` on a `qos.rxo_mismatch` issue, asserting `o` resolves an endpoint | [H3](#h3) |
| Two participants disagreeing on type name, asserting both are linked to the `type.name_conflict` issue | [H4](#h4) |
| Every `TopologyHealthScreen` action driven with `snapshot = None` | [H5](#h5) |
| `refresh_participants` where one of three handles raises inside `transport_info`, asserting the other two are upserted | [H10](#h10) |
| `_endpoint_from_data` / `_participant_from_data` field-by-field against a realistic fake, asserting every field is non-`None` | [S2](#s2) |
| `engine.sweep` / `_sweep_row` at all, and `run_headless_all` against their real output | [S4](#s4) |
| `_spdp2_enabled` with an integer-valued mask, not a string | [S5](#s5) |
| One healthy-system assertion requiring zero findings at **any** severity | [S6](#s6) |
| `system_scan(max_age=3.0, captured_at=None)` twice, asserting the second is cached, and with `max_age=0`, asserting it is not | [S7](#s7) |
| `walk_sample` and `_walk_union` against duck-typed fakes in the unit tier | [S8](#s8), [M3](#m3) |
| `check_payload_walk` / `check_cache_drops` / `check_inconsistent_topic` at all, with a `FakeProbe` that can fire them | [S9](#s9) |
| A representation list containing `-1`, asserting no `qos.rxo_mismatch`; a wildcard partition pair, asserting overlap | [S10](#s10) |
| `run_headless_topic` with `-o` and with `--pcap` | [S11](#s11) |
| `extensibility_map` over a reused-struct DAG, asserting node visits are bounded | [M1](#m1) |
| `LiveCapture` / `finish_discovery` called twice concurrently | [M4](#m4) |
| `expire_type_wait` racing `note_type`, asserting no endpoint ends UNAVAILABLE with a non-`None` type | [M7](#m7) |
| `locator_ip` on an IPv6 and a SHMEM locator, asserting no dotted quad is returned | [L1](#l1) |
| A writer whose `partition` is `None` against a reader with a named partition, asserting **no** `qos.rxo_mismatch` | [Q1](#q1) |
| A writer whose `presentation` is `None` against a reader with `coherent_access=true`, asserting no ERROR | [Q2](#q2) |
| A writer advertising an empty representation sequence, asserting the OK finding says the policy was not evaluated | [Q3](#q3), [Q4](#q4) |
| `check_no_multicast_no_peers` with a non-empty `multicast_receive_addresses` and a single unicast peer, asserting a finding | [X1](#x1) |
| `suppress()` with an explainer on topic A and a symptom on topic B, asserting the symptom stays active | [X2](#x2) |
| `check_type_state` called directly on a reader endpoint, asserting no writer-phrased finding | [X3](#x3) |
| `check_assignability` with 3 resolved readers of which 2 raise in `is_assignable_from`, asserting the OK text is not an all-clear | [X4](#x4) |
| `_property_value` against a policy that iterates as tuples or strings, asserting the checks do not silently return `[]` | [X8](#x8) |
| `builtin_discovery_plugins = SPDP\|SPDP2`, asserting no `blind.spdp2` ERROR | [X6](#x6) |

---

# Terra: Current-Branch Reassessment — 2026-08-10

Terra: This section is a second review of the findings above against current
branch `rti-doctor-review-fixes` at `5727d0c` (`test(rti_doctor): align Fast DDS
fixtures with TypeLookup defaults`). It preserves the original review and records
only the reassessment outcome; it is not a claim that Claude authored these
conclusions.

Terra: The current branch remains materially affected by the review. The second
pass classified 47 findings as confirmed current defects or test/tooling gaps,
and 24 as partly confirmed: their code shape is present, but the claimed runtime
trigger, DDS semantic consequence, or severity requires external binding, DDS
specification, or live-system evidence before scheduling a behavioral change.
No finding was fully refuted or fixed by the one production change after the
review's original `290707c` baseline.

## Terra: Executed Validation

Terra: `./run_tests.sh unit` passed with 183 tests across 10 modules. This is a
useful regression baseline, not a rebuttal of the review: many confirmed items
are deliberately in untested paths, test harnesses, or integration behavior.

Terra: A focused in-process reproduction confirmed the discovery layout defect:
the parser exposes 12 slots while `inspect_discovery_pcap()` asks `tshark` for
13 fields. Parsing a representative shifted row resulted in `vendor_id == ""`
and `topic_name == "endpoints"` rather than their intended values.

Terra: The same reproduction confirmed the two false-QoS-error paths. A writer
with unreadable `partition` and `presentation` against a reader requesting a
named partition and `coherent_access=true` produces `PARTITION` and
`PRESENTATION coherent_access` mismatches.

## Terra: Confirmed Findings

Terra: **Discovery, blind spots, and QoS:** `C1`, `C1a`, `C1b`, `C1c`, `C2`,
`X1`, `X2`, `Q1`, `Q2`, `Q4`, and `Q7` remain confirmed. In particular, `C1` is
live, not merely historical: `wire.py` still requests the duplicate
`rtps.sm.wrEntityId`; `--all` still bypasses `diagnose_domain()`; suppression is
still global by finding ID; and unreadable PARTITION/PRESENTATION data can still
produce an ERROR.

Terra: **Type and user interface:** `X3`, `X4`, `H2`, `H3`, `H4`, `H8`, `M6`,
`M8`, `M9`, and `M10` remain confirmed. `check_type_state()` is not role-aware
internally; assignability labels evaluated readers as resolved; FINAL-type notes
are emitted per endpoint; paired QoS issues cannot be opened through one TUI
path; topic-scoped issues do not link to participants; report navigation starts
a capture on `any`; participant refresh runs on the UI thread; topology and
health use different observation times; issue filters are stale after refresh;
and partial payload verdicts omit the overall problem summary.

Terra: **CLI, lifecycle, and test tooling:** `H1`, `H6`, `H7`, `H9`, `M11`,
`M12`, `M13`, `M14`, `M15`, `S1`, `S2`, `S4`, `S5`, `S6`, `S7`, `S8`, `S10`,
`S11`, `S13`, `L2`, `L5`, `L6`, `L7`, and `L8` remain confirmed. This includes
non-JSON stdout on the documented JSON path, cleanup traps that read expired
function locals, resource setup outside the main cleanup guard, unbounded
captures, missing JSON on expected non-success paths, overloaded exit statuses,
an accepted infinite ready timeout, incomplete test registration, and fixture
cleanup/argument validation defects.

## Terra: Partly Confirmed Findings

Terra: `C3` is partly confirmed. When an empty domain has a blind-spot ERROR,
the TUI hides counts while the text report retains them. Ordinary empty domains
now intentionally have no active issues, so the original wording overstates the
scope of the inconsistency.

Terra: `Q3` is partly confirmed. Empty representation IDs skip the
DATA_REPRESENTATION comparison and still permit `qos.compatible`; the claimed
specific default-writer XCDR1 versus XCDR2-only mismatch needs live DDS evidence
before it is treated as a known false negative. `Q5` and `Q6` are also partly
confirmed: their guards and wildcard behavior are present, but the asserted
valid representation-list and partition-expression semantics need DDS/spec
verification.

Terra: `X5`, `X6`, `X7`, `X8`, and `X10` are partly confirmed. The relevant
fallbacks and overly narrow checks exist, but the claimed mask representation,
mixed-SPDP behavior, security alias/property semantics, property-policy shape,
and representation-ID consequences were not reproduced against the installed
binding.

Terra: `H5`, `H10`, `M4`, `M5`, `M7`, `M16`, `M17`, `S3`, `S9`, `S12`, `S14`,
`L1`, `L3`, and `L4` are partly confirmed. The missing guards, races, repeated
work, dependency-manifest facts, fail-open fixture behavior, mid-file test
runner, stale selection, and evidence-key collision paths are present. Their
precise runtime trigger or impact remains conditional. Two corrections to the
original review are important: `S3` is 13 classes after the runner out of 18,
not 13 of 20; and the claimed `/dev/null` reproduction for `S12` is stale because
the current non-TTY guard exits before starting a fixture.

Terra: `M1`, `M2`, and `M3` are partly confirmed. The recursion lacks a visited
set, version components are zipped without length validation, and union-label
read failures can collapse into the default-member path. The extreme performance
case, Wireshark field trigger, and live DynamicData failure described in the
original review require reproduction before prioritization.

## Terra: Reassessment Consequences

Terra: The first repair batch should remain `C1`, `Q1`, `Q2`, `C2`, and `X1`,
with focused regression tests. These are directly demonstrated defects with a
clear false-data, false-error, or false-clean outcome.

Terra: Do not implement behavioral fixes for `Q5`, `Q6`, `X5` through `X8`, or
`X10` solely from this review. Record them as deferred until their DDS and
binding assumptions are confirmed. The decision workflow for all remaining
findings is defined by `DESIGN_DECISIONS.md` and the `iterate issues` prompt.
