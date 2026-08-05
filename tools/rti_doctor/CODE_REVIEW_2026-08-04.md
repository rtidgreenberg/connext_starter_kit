# RTI Doctor Code Review — 2026-08-04

Review date: 2026-08-04
Reviewer: static multi-perspective review (no tests run, nothing built, nothing
executed). All conclusions are derived from reading source.

Scope: `tools/rti_doctor/rti_doctor/` (all implementation modules), the CLI and
TUI execution paths, packet-capture handling, and the accompanying tests under
`tools/rti_doctor/test/`.

Relationship to the prior review: `CODE_REVIEW.md` (2026-08-03) lists seven
findings and claims all were applied. This review does not re-report them.
Three of them are **incompletely or incorrectly fixed**, and those regressions
are reported here as new findings (H4, H6, M1, M7).

## Verification status

Findings marked **Confirmed** were verified by reading the exact code at the
cited lines during this review. Findings marked **Confirmed (binding-dependent)**
depend additionally on the shape of the `rti.connextdds` binding — the attribute
was checked against the installed stubs/symbols, but not executed, and should be
re-checked against the target Connext version before the fix is written.

---

## Summary

| # | Sev | Finding | Area |
|---|---|---|---|
| H1 | High | PRESENTATION access scope is never compared; the check reads a field the policy does not have | Static QoS |
| H2 | High | Probe verdicts are attributed to the selected writer with no writer-identity correlation | Probe |
| H3 | High | GUID-prefix filtering *replaces* builtin-writer exclusion, so discovery traffic is counted as user payload | Wire |
| H4 | High | Disposed-endpoint key fallback cannot recover a key, so departed endpoints live forever | Discovery |
| H5 | High | A probe that throws after reader creation still reports `payload FULL` and exit 0 | Probe |
| H6 | High | A tshark that dies mid-capture is reported as a successful, empty capture | Wire |
| H7 | High | Quitting the TUI mid-sweep hangs the process; a second Ctrl-C closes the participant under a live probe thread | TUI |
| H8 | High | `DATAREPRESENTATION` matches the `PRESENTATION` substring, so the most common cross-vendor fault is explained with the wrong rule | Probe |
| H9 | High | Three incompatible Doctor-JSON parsers in the test suite; the fault suite will spuriously fail on Connext shutdown noise | Tests |
| M1 | Med | Loop variable shadows `name`: every diagnostic participant announces itself as `system_resource_limits` | Discovery |
| M2 | Med | tshark's stderr is an undrained PIPE; live capture stalls and silently truncates | Wire |
| M3 | Med | `-E occurrence=f` contradicts the multi-submessage parsing, so DATA_FRAG is never detected | Wire |
| M4 | Med | DATA_REPRESENTATION uses set intersection instead of the directional writer-`value[0]` rule | Static QoS |
| M5 | Med | `_merge_participant` treats `False` as "absent", so `partial_configuration` can never be cleared | Discovery |
| M6 | Med | One bad sample permanently discards the rest of the `take()` batch | Discovery |
| M7 | Med | `type.name_conflict` ERROR contradicts the tool's own assignability evidence | Type |
| M8 | Med | A truncated payload walk is reported as "fully deserialized" / verdict `FULL` | Payload |
| M9 | Med | `inspect_pcap` has no subprocess timeout and buffers every payload as hex in RAM | Wire |
| M10 | Med | Timeout/interval/domain arguments accept zero, negative and NaN | CLI |
| M11 | Med | `capture.start()` sits outside the `try/finally`; Ctrl-C in its startup window orphans tshark | CLI |
| M12 | Med | SPDP2 detection substring-matches the string form of a bitmask, so it cannot fire | Blind spots |
| M13 | Med | `check_no_multicast_locators` fires on every writer, from a field publications never carry | Static |
| M14 | Med | `check_window` and `check_fragmentation` convert weak evidence into WARN/ERROR verdicts | Probe |
| M15 | Med | TUI probe/sweep use bare `asyncio.create_task`; detached-widget writes and duplicate-topic false ERRORs | TUI |
| L1–L8 | Low | See [Low](#low) | Various |

### Implementation status

| Finding | Status | Resolution |
|---|---|---|
| H2 | **Fixed** | The probe now resolves the selected writer's instance handle from `reader.matched_publications` via `matched_publication_data(...).key`, scopes `matched_count` and `samples_taken` to it, and filters walked samples on `sample.info.publication_handle`. When the binding cannot report matched publications, or no key resolves, `correlated` stays False and observations remain topic-scoped — every rung-4 finding now states its scope rather than implying writer identity. An unattributable `requested_incompatible_qos` becomes `match.incompatible_qos_topic` at WARN, a distinct id deliberately absent from `SUPPRESSION_RULES` so a maybe cannot suppress `data.silent` or `match.none`. |
| H4 | **Fixed** | `_sample_key`'s reader fallback now reads `key_value(...).key.value` — `key_value()` returns the topic's DATA type, not a `BuiltinTopicKey`, so the one-hop `.value` always returned None and `remove_endpoint("")` was a silent no-op. An all-zero key is rejected as the unpopulated default rather than used as an identity, and an unkeyable disposal sample logs at WARNING instead of vanishing. |
| M5 | **Fixed** | `_merge_participant` skips only genuine absence (`None` / `""`). The old `value not in (None, "", 0)` compared by equality and `False == 0`, so `partial_configuration=False` — the sample saying discovery completed — was discarded as a missing field. |
| M6 | **Fixed** | Extracted `_drain_endpoints`, which wraps each sample in its own try/except so one unparseable record cannot discard the rest of a `take()` batch, and logs the sample index. A failing `take()` itself is also contained. |
| H8 | **Fixed** | `_policy_rule` selects the longest matching key instead of the first. Substring matching is retained deliberately — Connext decorates `last_policy` with version-dependent affixes — so longest-match also protects against the next overlapping key. |
| H1 | **Fixed** | Added `_enum_name`; the enum attribute is now a parameter, and PRESENTATION reads `("access_scope", "kind")` — the `kind` fallback keeps it binding-agnostic. `HIGHEST_OFFERED` removed from `PRESENTATION_ORDER` so `_ordered_rule` declines to evaluate it. Mismatch label is now `PRESENTATION access_scope`. |
| M1 | **Fixed** | Loop variable renamed to `policy_name`; the `name` parameter now reaches `qos.participant_name.name`. |
| M4 | **Fixed** | `writer_ids[0] not in set(reader_ids)` replaces the set intersection; rule text corrected to state the directional relationship. |
| — | **Fixed** | `test_checks.py`: `Presentation` fake now uses `access_scope`; the RxO matrix asserts exactly on `evidence["mismatches"]` instead of a title substring (which could pass on the wrong policy); six regression tests added; new `TestProbeMatchPolicyRules` — `probe_match` previously had no test file importing it. |

Test evidence for the above:

```text
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python -m unittest \
  tools.rti_doctor.test.test_checks tools.rti_doctor.test.test_wire \
  tools.rti_doctor.test.test_findings

Ran 108 tests in 0.011s
OK
```

The new tests were verified to be load-bearing, not merely green. Reverting the
static-QoS fixes (first-match `_policy_rule`, `attributes=("kind",)` for
Presentation, and the DATA_REPRESENTATION set intersection) turns
`test_checks.py` red with 7 failures, including
`test_broader_reader_access_scope_is_incompatible` and
`test_reader_must_accept_the_writers_first_representation` reporting
`qos.compatible` where `qos.rxo_mismatch` is required. Reverting H2 — forcing
`_correlate` to return None and `attributable` to True — turns it red with 6
failures spanning both halves of the fix, the correlation core and the finding
severity. Reverting H4/M5/M6 - the one-hop `key_value(...).value`, the
`(None, "", 0)` predicate and the loop-wide try/except - turns it red with 4
failures. The fixes were restored and the suite re-run green in each case.

No DDS, network, docker or tshark was involved; the three suites above are the
deterministic tier. Nothing else was run or built.

All other findings are open. Note that `wire.py`, `report.py`, `engine.py`,
`__main__.py` and `discovery.py` received unrelated feature work
(`DiscoveryObservation` / `summarize_discovery`, and a `--type-object-v1-only`
participant flag) after this review was written; the wire findings (H3, H6, M2,
M3, M9) should be re-confirmed against the current file before being fixed.

The dominant theme is unchanged from the prior review and worth stating plainly:
**this tool's value is that its findings are true, and the recurring defect class
is a definite conclusion drawn from evidence that does not support it** — either
topic-scoped evidence attributed to one endpoint (H2, H3), or absence of
evidence treated as evidence of absence (H1, M4, M13, L2, L3).

---

## High

### H1 — PRESENTATION access scope is never compared; the check reads a field the policy does not have

**Confirmed (binding-dependent).**
Anchors: [qos_match.py:26-32](rti_doctor/checks/qos_match.py#L26-L32),
[qos_match.py:23](rti_doctor/checks/qos_match.py#L23),
[qos_match.py:163-168](rti_doctor/checks/qos_match.py#L163-L168)

`_kind_name()` reads `policy.kind`. Every other policy it is applied to
(Reliability, Durability, Liveliness, DestinationOrder, Ownership) has `.kind`.
`PresentationQosPolicy` does not — it exposes `access_scope`, `coherent_access`,
`ordered_access`, `drop_incomplete_coherent_set`. The correct name is used
elsewhere in this same tool: [probe.py:200](rti_doctor/probe.py#L200) does
`sub_qos.presentation.access_scope = presentation.access_scope`.

So on real discovery data `compat.get(policy, "kind", None)` returns `None`,
`_rank()` returns `(None, None)`, and `_ordered_rule()` bails out at
[qos_match.py:69](rti_doctor/checks/qos_match.py#L69) — silently, because that
early return is the deliberate "cannot evaluate, say nothing" path. The
access-scope comparison is dead code in production.

**Failure scenario.** A publisher with `access_scope = INSTANCE` and a subscriber
requesting `GROUP`. Real DDS refuses to match — the project's own matrix asserts
exactly that ([test_rxo_vendor_e2e.py:24](test/test_rxo_vendor_e2e.py#L24)
scenario `presentation_scope`, `matched == 0` asserted at
[test_rxo_vendor_e2e.py:95-96](test/test_rxo_vendor_e2e.py#L95-L96)).
`compare_endpoints()` returns no mismatch, so `check_rxo_pairs()` emits
`qos.compatible` — "No observable QoS mismatch" — for a pair that provably never
communicates. This is the headline rung-4 function reporting the opposite of the
truth.

**Why no test catches it.** [test_checks.py:567-571](test/test_checks.py#L567-L571)
defines a fake `Presentation` with `self.kind = Kind(scope)`, a shape the real
binding does not have, so the matrix test passes against a fiction. The
coherent/ordered subtests at
[test_checks.py:592-595](test/test_checks.py#L592-L595) use the real field names,
which is why those two work.

**Latent second defect, once the field name is fixed.** `PRESENTATION_ORDER`
ranks `HIGHEST_OFFERED: 3`, above `GROUP: 2`. `HIGHEST_OFFERED` applies only to a
Subscriber and means "use whatever each remote Publisher offers" — i.e. always
compatible. Ranked at 3, *every* writer (max rank 2) would fail against a
`HIGHEST_OFFERED` reader, turning a false negative into a 100% false positive
ERROR asserting the pair "will never communicate".

**Relation to prior review.** `CODE_REVIEW.md:80-85` states the comparison
"checks only Presentation's `access_scope`" and the fix table claims coherent and
ordered were added. The reality is inverted: the two booleans work, and
access_scope has never worked against real data.

**Fix.** Read `access_scope` (e.g. `compat.first(policy, ("access_scope", "kind"))`
to stay binding-agnostic); remove `HIGHEST_OFFERED` from the ordered map and
short-circuit to compatible when the reader requests it; change the test fake to
`self.access_scope = …` so the test pins the production field name.

### H2 — Probe verdicts are attributed to the selected writer with no writer-identity correlation

**Confirmed.**
Anchors: [probe.py:231](rti_doctor/probe.py#L231) (topic-wide reader),
[probe.py:245-256](rti_doctor/probe.py#L245-L256) (matched count and samples),
[probe.py:277-280](rti_doctor/probe.py#L277-L280);
consumed at [probe_match.py:130-142](rti_doctor/checks/probe_match.py#L130-L142),
[probe_match.py:65-121](rti_doctor/checks/probe_match.py#L65-L121),
[probe_payload.py:38-117](rti_doctor/checks/probe_payload.py#L38-L117)

The probe creates a plain `DynamicData.DataReader` on the *topic name*.
`subscription_matched_status`, `requested_incompatible_qos_status`,
`datareader_protocol_status` and every taken sample are therefore **topic-scoped**,
but every rung-4/5 finding phrases them as facts about the one selected writer.
`matched_publications` and `sample.info.publication_handle` are used nowhere in
the tool.

**Failure scenario A — false OK, the worst case.** Topic `T` has W1 (selected;
advertised locator unroutable from this host — the tool's own `locator.unroutable`
scenario) and W2 (healthy, same type, local). The probe matches W2 and walks W2's
sample. Report: `match.ok` "Reader matched the writer" (OK), `payload.full`
"Payload fully deserialized" (OK), verdict "matched, 1 sample(s) received,
payload FULL", exit code 0 — for a writer that never matched and never delivered
a byte.

**Failure scenario B — false ERROR.** Topic `T` has W1 (selected, `RELIABLE`) and
W2 (`BEST_EFFORT`). `build_reader_qos` mirrors W1, so the probe requests
`RELIABLE`; W2 raises `requested_incompatible_qos`. Report: ERROR
`match.incompatible_qos` whose root_cause asserts "it reflects a policy the
writer offers that no compliant reader can accept"
([probe_match.py:104-107](rti_doctor/checks/probe_match.py#L104-L107)) — false for
W1. Exit code 1 on a healthy pair. It additionally suppresses `data.silent`
([findings.py:91](rti_doctor/findings.py#L91)), hiding a genuine silence symptom
behind a spurious explainer.

This is the same defect class the prior review closed for the pcap path
(`CODE_REVIEW.md:11-49`), in the live-probe path, which was never covered.

**Fix.** Retain the selected endpoint's builtin key/GUID; intersect
`reader.matched_publications` with it before emitting `match.ok` / `match.none`;
filter taken samples on `sample.info.publication_handle` before counting
`samples_taken` or walking; when a `requested_incompatible_qos` event cannot be
attributed to the selected writer, report it as a topic-level WARN, not an ERROR
about this writer.

### H3 — GUID-prefix filtering *replaces* builtin-writer exclusion

**Confirmed.**
Anchors: [wire.py:56-65](rti_doctor/wire.py#L56-L65),
[wire.py:113-116](rti_doctor/wire.py#L113-L116),
[wire.py:166-174](rti_doctor/wire.py#L166-L174)

```python
if writer_guid_prefix is not None:
    observations = [item for item in observations
                    if _same_guid_prefix(item.writer_guid_prefix, writer_guid_prefix)]
else:
    observations = [item for item in observations if not _is_builtin_writer(item)]
```

The two filters are mutually exclusive branches. The GUID prefix is the
*participant* prefix — the peer's SPDP, SEDP and participant-message writers
(`…00c2`, `…03c2`, `…02c2`) share it with the target user writer. The tshark
display filter is `rtps.param.serialize.encap_kind`, which Wireshark emits for
*every* DATA submessage including builtin parameter lists; the comment at
[wire.py:166-168](rti_doctor/wire.py#L166-L168) acknowledges exactly this hazard,
but the code only defends against it in the `else` branch.

**Failure scenario.** `--capture-interface eth0 --topic Foo` against a Cyclone
writer publishing XCDR2 (`0x0007`). The capture also contains that participant's
SEDP and participant-message DATA. Appendix C reports `User-data packets: 41`
when only 6 were the topic's samples, and `Encapsulation IDs: 0x0001, 0x0003,
0x0007` — presenting PL_CDR_LE discovery encapsulation as observed wire
representation for the topic. This is the contamination class the prior review's
High finding was meant to close; the fix narrowed to the right participant but
stopped excluding that participant's builtin writers.

[test_wire.py:80-86](test/test_wire.py#L80-L86) encodes the defect: both fixture
observations carry entity id `000200c2` (the builtin participant-message writer)
and the test asserts they are retained.

**Fix.** Apply `_is_builtin_writer` exclusion unconditionally, then the prefix
filter, then the entity filter. Add a fixture where the target participant emits
both an SEDP DATA and a user DATA, and assert only the latter is summarized.

### H4 — Disposed-endpoint key fallback cannot recover a key, so departed endpoints live forever

**Confirmed (binding-dependent).**
Anchor: [discovery.py:333-341](rti_doctor/discovery.py#L333-L341), used from
[discovery.py:305](rti_doctor/discovery.py#L305) and
[discovery.py:328](rti_doctor/discovery.py#L328)

```python
key = compat.get(compat.get(data, "key", None), "value", None)   # primary: two hops
if key is None:
    key = compat.get(reader.key_value(info.instance_handle), "value", None)  # fallback: one hop
```

`DataReader.key_value(handle)` returns an instance of the topic's *data type*
(`PublicationBuiltinTopicData` / `SubscriptionBuiltinTopicData`) with its key
fields filled — not a `BuiltinTopicKey`. It has no `.value`; the key is at
`.key.value`, which is exactly the two-hop access the primary path performs one
line above. The fallback therefore always evaluates to `None`, `_sample_key`
returns `""`, and `remove_endpoint("")` pops nothing and logs nothing.

**Failure scenario.** An application deletes one DataWriter but keeps its
participant alive. Connext delivers an invalid `DCPSPublication` sample. RTI's
documented pattern is to recover the key via `get_key_value` precisely because
the disposal sample's data is not populated — which is why this fallback exists.
Either the data object is unpopulated (`data.key.value` → `[0,0,0,0]` →
`remove_endpoint("[0, 0, 0, 0]")`, a no-op) or unreadable (fallback → `""`, a
no-op). Either way the dead writer stays in `endpoints`, keeps appearing in
`writers()`, `find_writer()`, sweeps and the RxO census, and its probe times out
— the exact symptom the prior review's finding #2 described. Only the
participant-departure case is genuinely fixed, by `refresh_participants`
([discovery.py:394-395](rti_doctor/discovery.py#L394-L395)).

[test_checks.py:387-401](test/test_checks.py#L387-L401) builds a fake whose
invalid sample carries `data.key.value = "w1"`, exercising only the primary path.

**Fix.** `compat.get(compat.get(reader.key_value(...), "key", None), "value", None)`;
treat an all-zero key as unusable; log at WARNING when a disposal sample cannot
be keyed instead of discarding it silently.

### H5 — A probe that throws after reader creation still reports `payload FULL` and exit 0

**Confirmed.**
Anchors: [probe.py:242](rti_doctor/probe.py#L242) (`result.created = True`),
[probe.py:264-267](rti_doctor/probe.py#L264-L267) (single `except` sets
`create_error`), [probe.py:277](rti_doctor/probe.py#L277) (bare attribute read);
consumed at [probe_match.py:48](rti_doctor/checks/probe_match.py#L48),
[report.py:100-104](rti_doctor/report.py#L100-L104),
[report.py:231-234](rti_doctor/report.py#L231-L234)

`probe_endpoint`'s single `except Exception` wraps everything after reader
creation, including the poll loop and `_snapshot_statuses`. Once
`result.created = True`, every downstream consumer ignores `create_error`:
`check_probe_error` returns `[]` because `probe.created` is truthy;
`ReportData.outcome` reads `create_error` only under `if not result.created`;
`_render_counter_appendix` prints the reason only under
`if result is None or not result.created`. So `create_error` appears **nowhere in
the text report** — only in `render_json` and a `logging.error`.

**Failure scenario.** The probe matches and walks one sample, then
`result.subscription_matched = reader.subscription_matched_status`
([probe.py:277](rti_doctor/probe.py#L277) — a bare attribute read, not
`compat.get`) raises. `result.protocol` and `result.cache` stay `{}`, so
Appendix B renders every counter as `n/a (not available on Connext 7.7.0)` —
indistinguishable from the version-gap case the compat layer exists to signal.
`check_silent`, `check_fragmentation`, `check_window`, `check_deserialize_failure`
and `check_cache_drops` all see empty counters and emit nothing. `check_matched`
uses `probe.matched_count` from the poll loop, so it emits `match.ok`. Final
verdict: `matched, 1 sample(s) received, payload FULL`, exit code 0 — for a probe
that crashed before collecting any evidence.

**Fix.** Give `_snapshot_statuses` its own try/except recording a distinct
`snapshot_error`; never assign `create_error` once `created` is `True`; emit a
WARN/ERROR finding for a partial probe so the verdict cannot claim FULL.

### H6 — A tshark that dies mid-capture is reported as a successful, empty capture

**Confirmed.**
Anchors: [wire.py:232](rti_doctor/wire.py#L232),
[wire.py:246-253](rti_doctor/wire.py#L246-L253); prior finding
`CODE_REVIEW.md:102-120`

```python
def finish(self):
    if self.process is not None and self.process.poll() is None:
        ...   # terminate / kill / read stderr / check returncode
    if self.error:
        return {...}
    result = inspect_pcap(self.output_path, ...)
```

The `poll() is None` guard gates the **entire** error-detection block, not just
the termination. If tshark exits *during* the probe — interface goes down, disk
fills, capture privileges dropped, OOM-killed — `poll()` returns non-`None`, the
block is skipped, `self.error` stays `None`, its stderr is never read (and the
pipe FD never closed), and `inspect_pcap()` parses the truncated file.

**Failure scenario.** tshark dies at t=2s with returncode 2 and
`tshark: The file … could not be created: No space left on device` on stderr.
Appendix C renders `User-data packets: 0`, `Encapsulation IDs: none observed`,
`Serialized bytes: 0` with **no** error line. A reader concludes the target
writer emitted nothing on the wire — the opposite of the truth — and the exit
code is 0.

The prior review's fix added `TimeoutExpired` recovery
([wire.py:239-247](rti_doctor/wire.py#L239-L247)), which is correct and tested at
[test_wire.py:100-118](test/test_wire.py#L100-L118), but only for the
still-running branch.

**Fix.** Always check `returncode` and drain stderr when `self.process is not
None`, regardless of liveness; treat any nonzero/unexpected code as a capture
error.

### H7 — Quitting the TUI mid-sweep hangs the process; a second Ctrl-C closes the participant under a live probe thread

**Confirmed.**
Anchors: [report_screen.py:158](rti_doctor/views/report_screen.py#L158),
[report_screen.py:170-173](rti_doctor/views/report_screen.py#L170-L173),
[__main__.py:384-390](rti_doctor/__main__.py#L384-L390),
[engine.py:110-112](rti_doctor/engine.py#L110-L112)

`SweepScreen._run_sweep` runs the whole sweep via
`await asyncio.to_thread(self.session.sweep, progress, True)`, which uses the
event loop's **default** ThreadPoolExecutor. Textual's `App.run()` is
`asyncio.run(...)`, and `asyncio.runners.run` unconditionally executes
`loop.run_until_complete(loop.shutdown_default_executor())` in its `finally` —
i.e. `ThreadPoolExecutor.shutdown(wait=True)`.

**Failure scenario.** 40 writers discovered, user presses `D`, then `q` after 5
seconds. Cancelling the coroutine cannot cancel the running thread, so
`Session.sweep` keeps probing writers 3…40 at `--probe-timeout` (default 10s)
each. The terminal is restored, the UI is gone, nothing is printed, and the
process sits for ~6 more minutes. During that window `progress()` calls
`self.app.call_from_thread(...)` into a shutting-down loop; the exception is
swallowed by `engine.py`'s `except Exception` at DEBUG level, so there is no
explanation either.

**Escalation.** Because the process looks hung, the user presses Ctrl-C again.
That KeyboardInterrupt lands inside `run_until_complete(shutdown_default_executor())`,
so `app.run()` raises and [__main__.py:388](rti_doctor/__main__.py#L388)
`participant.close()` executes **while the sweep thread is inside
`dds.DynamicData.DataReader(...)` / `reader.take()` on that same participant**
([probe.py:241](rti_doctor/probe.py#L241), [probe.py:250](rti_doctor/probe.py#L250)).
That is a use-after-close against the Connext C++ core, not a Python exception.

**Fix.** Run probe and sweep as Textual workers
(`self.run_worker(..., thread=True, exclusive=True)`) so they are cancelled on
unmount; have `Session.sweep` poll a cancellation flag between writers; join all
worker threads before `participant.close()`.

### H8 — `DATAREPRESENTATION` matches the `PRESENTATION` substring, so the most common cross-vendor fault is explained with the wrong rule

**Confirmed.** Anchors:
[probe_match.py:37-42](rti_doctor/checks/probe_match.py#L37-L42),
`RXO_RULES` insertion order at
[probe_match.py:24](rti_doctor/checks/probe_match.py#L24) (`PRESENTATION`) and
[probe_match.py:30](rti_doctor/checks/probe_match.py#L30) (`DATAREPRESENTATION`)

```python
key = str(policy_text).upper().replace("_", "").replace(" ", "")
for name, rule in RXO_RULES.items():
    if name in key:
        return rule
```

`"DATA_REPRESENTATION"` normalizes to `"DATAREPRESENTATION"`, which **contains
the substring `"PRESENTATION"`**. Dict iteration is insertion order and
`PRESENTATION` is inserted six entries earlier, so the substring test hits it
first and returns the Presentation rule.

**Failure scenario.** A genuine XCDR1/XCDR2 incompatibility — the single most
common Connext↔Cyclone failure this tool exists to diagnose — produces an ERROR
whose title correctly reads `Incompatible QoS: DATA_REPRESENTATION`
([probe_match.py:113](rti_doctor/checks/probe_match.py#L113), which uses the raw
policy text) but whose root_cause reads *"The reader's presentation access scope
must be no broader than the writer's, and coherent/ordered access must be
compatible."* The finding contradicts itself and sends the user to the wrong
policy. The remedy line has the same problem.

`probe_match` is imported by **no test file** —
[test_checks.py:15-16](test/test_checks.py#L15-L16) imports `blind_spots`,
`static_discovery`, `probe_payload`, `qos_match` and `type_compat` but not this
module, which owns `match.ok`, `match.none` and `match.incompatible_qos`: the
tool's live compatible/incompatible verdicts.

**Fix.** Replace substring scanning with exact lookup on the normalized key, so
the result is order-independent. Add a unit test per key in `RXO_RULES` asserting
`_policy_rule` returns that key's own text.

### H9 — Three incompatible Doctor-JSON parsers in the test suite

Anchors: [test_fault_vendor_e2e.py:71](test/test_fault_vendor_e2e.py#L71),
[test_fault_vendor_e2e.py:197-198](test/test_fault_vendor_e2e.py#L197-L198),
[test_vendor_wire_e2e.py:96-106](test/test_vendor_wire_e2e.py#L96-L106)

| Site | Strategy | Tolerates trailing Connext noise? |
|---|---|---|
| `test_fault_vendor_e2e.py:71` | `json.loads(completed.stdout)` | No |
| `test_fault_vendor_e2e.py:197-198` | `stdout[stdout.find("{"):]` then `json.loads` | No |
| `test_vendor_wire_e2e.py:96-106` | `JSONDecoder().raw_decode` + explicit allowlist of `ERROR PRESPsService_cleanup:` lines | Yes |

[test_vendor_wire_e2e.py:104](test/test_vendor_wire_e2e.py#L104) documents that
Connext emits `ERROR PRESPsService_cleanup:` on stdout after the JSON report. The
fault suite's two parsers both consume to end-of-string and will raise
`JSONDecodeError`, producing `self.fail("Doctor did not emit JSON")` — a
misleading failure pointing at Doctor when the report was correct. One suite
knows about this shutdown noise; the suite that most needs to be trustworthy does
not.

**Fix.** Promote the wire suite's parser verbatim into a shared helper and have
every Doctor-invoking test use it.

---

## Medium

### M1 — Loop variable shadows `name`: every diagnostic participant announces itself as `system_resource_limits`

**Confirmed.** Anchors: [discovery.py:222](rti_doctor/discovery.py#L222),
[discovery.py:231-232](rti_doctor/discovery.py#L231-L232),
[discovery.py:238](rti_doctor/discovery.py#L238)

```python
def create_participant(domain_id, name="RTI DOCTOR", registry=None):
  ...
  for name in ("entity_factory", "monitoring", "system_resource_limits"):   # rebinds `name`
    setattr(factory_qos, name, getattr(previous_factory_qos, name))
  ...
  qos.participant_name.name = name    # == "system_resource_limits"
```

The QoS-copy loop introduced by the prior review's factory-QoS fix rebinds the
`name` parameter. The parameter is entirely dead:
[__main__.py:184](rti_doctor/__main__.py#L184) passes `"RTI DOCTOR"` and
[test_live_integration.py:66](test/test_live_integration.py#L66) passes
`"RTI DOCTOR TEST"`; both are discarded. Every run joins the domain as a
participant named `system_resource_limits`. For a tool whose whole premise is
being inserted into someone else's live system and being accountable for what it
added, being unidentifiable in `rtiddsspy` / peer logs is a real defect. No test
asserts the participant name.

**Fix.** Rename the loop variable (`for policy_name in (...)`). Assert the
participant name in the live test.

### M2 — tshark's stderr is an undrained PIPE; live capture stalls and silently truncates

**Confirmed.** Anchors: [wire.py:219-222](rti_doctor/wire.py#L219-L222),
[wire.py:231-247](rti_doctor/wire.py#L231-L247)

`Popen(..., stderr=subprocess.PIPE)` with nothing reading the pipe between
`start()` and `finish()`. When writing to a capture file, tshark prints a
continuous per-packet count to stderr — exactly what `-q` exists to suppress. At
~4–10 bytes per packet the 64 KiB pipe buffer fills after roughly 8–16k packets;
tshark then blocks in `write(2)` and stops draining the capture socket.

**Failure scenario.** `--capture-interface eth0 -t LargeData` on a busy domain.
Partway through the probe the pipe fills, packets are dropped and never written.
`finish()` terminates it, returncode is `-15`, so `self.error` stays `None`
([wire.py:246](rti_doctor/wire.py#L246)). Appendix C reports a packet/byte count
that stopped at an arbitrary point, presented as a complete direct observation —
and this appendix is the tool's headline claim that it measured the wire rather
than trusting discovery.

**Fix.** Pass `-q`, and/or redirect stderr to a temp file that `finish()` reads.

### M3 — `-E occurrence=f` contradicts the multi-submessage parsing, so DATA_FRAG is never detected

**Confirmed.** Anchors: [wire.py:169-174](rti_doctor/wire.py#L169-L174) vs
[wire.py:109-110](rti_doctor/wire.py#L109-L110)

```python
def _has_submessage(observation, identifier):
  return identifier in observation.submessage_id.split(",")
```

The comma-split only makes sense for tshark's all-occurrences form; with
`occurrence=f` the field is a single value. Wireshark adds `rtps.sm.id` once per
submessage, and both Connext and Cyclone prepend `INFO_TS` (`0x09`) — often
`INFO_DST` (`0x0e`) too — ahead of `DATA`/`DATA_FRAG`. The recorded value is
therefore the *info* submessage, not the data one.

**Failure scenario.** A 200 KB fragmented sample produces frames whose first
`rtps.sm.id` is `0x09`. `_has_submessage(item, "0x16")` is `False` for all of
them, so Appendix C reports `DATA_FRAG submessages: 0` and `DATA submessages: N`
— the opposite of the truth, on the one diagnostic (fragmentation) the appendix
exists to support. The same restriction makes `payload_bytes` count only the
first `rtps.issueData` per RTPS message, undercounting whenever Connext batches
multiple DATA submessages into one frame.
[test_vendor_wire_e2e.py:115](test/test_vendor_wire_e2e.py#L115) asserts only
`data_packets + data_fragments > 0`, so it passes either way.

Related fragility on the same input: `_is_builtin_writer`
([wire.py:116](rti_doctor/wire.py#L116)) depends on tshark rendering
`rtps.sm.wrEntityId` as bare hex ending in `c2`/`c3`, and `_has_submessage`
depends on `rtps.sm.id` rendering as exactly `"0x16"`. Neither has a fallback if
a tshark version pads or symbolizes those fields — the filters just silently stop
matching.

**Fix.** Use `-E occurrence=a` and keep the comma-split; sum `rtps.issueData`
occurrences rather than taking the first; classify a frame as fragmented when
`0x16` appears anywhere in the list.

### M4 — DATA_REPRESENTATION uses set intersection instead of the directional writer-`value[0]` rule

**Confirmed.** Anchor: [qos_match.py:217-228](rti_doctor/checks/qos_match.py#L217-L228)

A DataWriter offers exactly **one** effective representation (`value[0]`, after
resolving AUTO); the pair is compatible iff that value is in the reader's
sequence. A non-empty intersection is not equivalent.

**Failure scenario.** Writer advertises `[XCDR1, XCDR2]` (effective: XCDR1);
reader advertises `[XCDR2]`. `set(writer_ids) & set(reader_ids) = {XCDR2}` → no
mismatch recorded → `qos.compatible` "No observable QoS mismatch", while the
writer serializes XCDR1 and the reader rejects it. This is precisely the
cross-vendor case the tool exists for.

**Fix.** Compare `writer_ids[0]` against `set(reader_ids)`; retain the existing
`-1`/AUTO and empty-sequence guards. Correct the rule text at
[qos_match.py:226-227](rti_doctor/checks/qos_match.py#L226-L227), which states the
relationship backwards.

### M5 — `_merge_participant` treats `False` as "absent", so `partial_configuration` can never be cleared

**Confirmed.** Anchor: [discovery.py:135](rti_doctor/discovery.py#L135)

`if value not in (None, "", 0)` uses `==` semantics, and `False == 0` is `True`.
`partial_configuration` is a boolean, so an incoming `False` is treated as a
missing field and never written.

**Failure scenario.** Under SPDP2 the first `DCPSParticipant` sample is the
bootstrap sample with `partial_configuration = True`; `upsert_participant` stores
it. The complete sample follows with `False`, and the merge refuses to apply it.
`check_partial_configuration`
([static_discovery.py:327-347](rti_doctor/checks/static_discovery.py#L327-L347))
then fires "Participant discovery data is marked partial" on every subsequent
report for that peer, with a remedy — "Re-run once discovery has settled before
trusting locator or transport findings" — that can never be satisfied, and which
undermines the locator/transport findings in the same report.

Secondary instance of the same predicate: a legitimate `domain_id == 0` (the most
common domain) and any genuinely-zero endpoint mask can never overwrite an
earlier `None`.

**Fix.** Skip only when `value is None or value == ""`; handle booleans and ints
explicitly.

### M6 — One bad sample permanently discards the rest of the `take()` batch

**Confirmed.** Anchors: [discovery.py:299-307](rti_doctor/discovery.py#L299-L307),
[discovery.py:322-330](rti_doctor/discovery.py#L322-L330)

The `try` wraps the whole loop, not each sample. `take()` has already removed all
samples from the reader cache, so an exception while processing sample *i*
destroys samples *i+1…n* with no possibility of redelivery.

**Failure scenario.** A Fast DDS participant publishes eight endpoints in one
SEDP burst; the third raises in `_endpoint_from_data` (a locator whose `str()`
raises, an unreadable field for that vendor's SEDP). The remaining five writers
never enter the registry. `run_headless_topic` then prints `No writer found on
topic 'X'` and exits 2, or `check_no_endpoints`
([static_discovery.py:350-376](rti_doctor/checks/static_discovery.py#L350-L376))
reports "Participant discovered, but none of its endpoints are visible" — a
fabricated diagnosis caused by the tool's own dropped samples. The only trace is
one `logging.error` line.

**Fix.** Move the `try/except` inside the loop; include the sample index or
instance handle in the log line.

### M7 — `type.name_conflict` ERROR contradicts the tool's own assignability evidence

Anchors: [type_compat.py:107-141](rti_doctor/checks/type_compat.py#L107-L141)
(severity at :128, claim at :133-136)

Two distinct type names on one topic produce an ERROR whose root_cause states "at
least one pairing cannot match". With resolvable TypeObjects and the default
`AUTO_TYPE_COERCION`, Connext matches on TypeObject assignability and registered
type-name equality is *not* required; name equality is the fallback only when
TypeObject info is unavailable. rti_doctor deliberately maximises TypeObject
resolution (`request_types_filter = "*"`,
[discovery.py:208-213](rti_doctor/discovery.py#L208-L213)), so the resolved case
is the expected one.

**Failure scenario.** Topic `T`: writer type `sensors::Sensor`, reader type
`Sensor`, both TypeObjects resolved and assignable. The running system
communicates. The report emits ERROR `type.name_conflict` (exit 1) *and*, from
`check_assignability`
([type_compat.py:199-213](rti_doctor/checks/type_compat.py#L199-L213)), OK
`type.assignability` — two contradictory conclusions in one report, with the
weaker evidence winning the verdict. Secondary: with only writers on the topic
and no readers, "at least one pairing cannot match" is vacuous — zero pairings —
yet the ERROR still fires.

**Fix.** Gate severity on type-resolution state: ERROR only when at least one side
is `TYPE_UNAVAILABLE`; otherwise WARN/INFO worded as a naming difference; suppress
or downgrade whenever `type.assignability` resolves True for the same pair.

### M8 — A truncated payload walk is reported as "fully deserialized" / verdict `FULL`

**Confirmed.** Anchors: [typewalk.py:76-86](rti_doctor/typewalk.py#L76-L86)
(`verdict` never references `self.truncated`),
[probe_payload.py:376-386](rti_doctor/checks/probe_payload.py#L376-L386)
(`payload.full` at `Severity.OK`),
[findings.py:179-183](rti_doctor/findings.py#L179-L183)

Truncation is set at [typewalk.py:466-468](rti_doctor/typewalk.py#L466-L468)
(collections beyond `MAX_ELEMENTS_PER_COLLECTION = 64`) and
[typewalk.py:334-348](rti_doctor/typewalk.py#L334-L348) (`MAX_DEPTH`,
`MAX_MEMBERS`) — in every case, members that were **never read**.

To be fair to the current code, truncation *is* surfaced: it appears as a clause
in the finding's `observed` string and as `evidence["truncated"]`. What it does
not affect is the severity (`OK`) or the verdict (`PAYLOAD_FULL`) — the two things
a human or CI job actually reads.

**Failure scenario.** The writer's type has `sequence<Element, 500> items` and an
encoding disagreement corrupts elements 65 onward. The walk visits 64 elements,
all readable, sets `truncated = True`, records zero failures. Report: OK finding
"Payload fully deserialized", top-line verdict "matched, 1 sample(s) received,
payload FULL", exit 0.

**Fix.** Return an explicit incomplete verdict when `report.truncated`; emit the
finding as INFO/WARN worded "every member visited was readable; the walk was
truncated at N elements/depth" rather than `payload.full` at OK.

### M9 — `inspect_pcap` has no subprocess timeout and buffers every payload as hex in RAM

**Confirmed.** Anchors: [wire.py:173-177](rti_doctor/wire.py#L173-L177),
[wire.py:184](rti_doctor/wire.py#L184), [wire.py:49-53](rti_doctor/wire.py#L49-L53)

`-e rtps.issueData` and `-e rtps.reassembled.data` emit the **entire** serialized
payload as colon-separated hex — roughly 3 bytes of text per payload byte — solely
so `_hex_bytes()` can divide the string length by two. `capture_output=True`
holds the whole thing in one string, and `.splitlines()` immediately makes a
second full copy.

**Failure scenario.** A 200 MB pcapng of reassembled multi-megabyte samples (the
suite has a `TestLargeData` case) builds a ~600 MB stdout string plus a ~600 MB
list of lines. On a 1 GB container: `MemoryError` inside `finish()`, which is
itself inside the `finally` at [__main__.py:281](rti_doctor/__main__.py#L281), so
it replaces whatever the diagnosis produced and no report is emitted. There is
also no `timeout=`, so a pathological `--pcap` argument hangs the tool
indefinitely with no output.

**Fix.** Drop the payload fields and derive sizes from a length field
(`frame.len` or `rtps.sm.octetsToNextHeader`); stream stdout line by line via
`Popen`; pass an explicit `timeout`.

### M10 — Timeout/interval/domain arguments accept zero, negative and NaN

**Confirmed.** Anchors: [__main__.py:54-66](rti_doctor/__main__.py#L54-L66),
[__main__.py:76-77](rti_doctor/__main__.py#L76-L77),
[__main__.py:43-45](rti_doctor/__main__.py#L43-L45)

`--probe-timeout`, `--type-wait`, `--settle`, `--scan-timeout` and `--interval`
are plain `type=float` with no validator; argparse accepts `-5` here because no
option string looks like a negative number. `--settle` is the only one guarded
([__main__.py:212](rti_doctor/__main__.py#L212), `max(0.0, seconds)`), which shows
the intent.

- `--probe-timeout -1`: `deadline = start + timeout` is in the past, the
  observation loop never executes, `samples_taken` stays 0, `data.silent` fires as
  ERROR, exit 1 — a fabricated fault report about a working peer.
- `--type-wait -1`: [records.py:137](rti_doctor/records.py#L137) is true on first
  evaluation, so every endpoint whose TypeObject is still in flight is immediately
  `TYPE_UNAVAILABLE` and reported as `type.no_type_info` ERROR.
- `--interval 0`: [app.py:33](rti_doctor/app.py#L33) schedules an unthrottled
  refresh that re-enters DDS discovery every tick.
- `--probe-timeout nan`: every `time.monotonic() < deadline` is `False` — same
  silent-probe outcome, no diagnostic.

Separately, both interactive prompts reject a negative domain ID
([__main__.py:121-123](rti_doctor/__main__.py#L121-L123),
[__main__.py:172-174](rti_doctor/__main__.py#L172-L174)) but `resolve_domain_id`
short-circuits on `--domain` with no validation. `rti_doctor -d -1 -t Foo` reaches
`create_participant(-1, …)` in `build_session`, which runs *before* `main`'s
`try/finally`, so the user gets a raw Connext traceback. `wire.capture_filter`
also computes `base + (-1 * 250)` and returns a valid-looking-but-wrong BPF range.

**Fix.** A shared `positive_float` argparse type rejecting `<= 0` and non-finite
values; validate `--domain` in `parse_args` with the same rule as the prompts.

### M11 — `capture.start()` sits outside the `try/finally`; Ctrl-C in its startup window orphans tshark

**Confirmed.** Anchors: [__main__.py:277](rti_doctor/__main__.py#L277) vs
[__main__.py:279-282](rti_doctor/__main__.py#L279-L282),
[wire.py:224](rti_doctor/wire.py#L224)

`LiveCapture.start()` spawns tshark and then does an unconditional
`time.sleep(1.0)` as its liveness check. A KeyboardInterrupt during that sleep is
not an `OSError`, so it escapes `start()`, skips the `try`, and `finish()` is
never called. The user hits Ctrl-C after realising they picked the wrong
interface; rti_doctor exits 130 and tshark keeps running detached, capturing into
`test_output/rti_doctor_captures/*.pcapng` until the disk fills.

Related, from the same call site: `finish()` — which performs a sleep of up to 4s
([wire.py:236-238](rti_doctor/wire.py#L236-L238)) and a full `inspect_pcap()` —
runs bare inside the `finally`, so an exception there replaces the original
diagnosis exception. And any exception from `diagnose_endpoint` aborts
`run_headless_topic` with a traceback and **no report at all** — which the prior
review (`CODE_REVIEW.md:102-120`) explicitly asked to be eliminated and which was
not done.

**Fix.** Move `capture.start()` inside the `try`, or make `LiveCapture` a context
manager; wrap the `finish()` call in its own try/except returning
`{"error": …}`; catch diagnosis failures so a report with an error verdict is
still rendered.

### M12 — SPDP2 detection substring-matches the string form of a bitmask, so it cannot fire

**Confirmed (binding-dependent).** Anchor:
[blind_spots.py:70-77](rti_doctor/checks/blind_spots.py#L70-L77)

> **Correction (2026-08-05).** The original text of this finding claimed "the
> constant is `SDP2`, and `"SPDP2" in "SDP2"` is False". That is **wrong**.
> `__init__.pyi:8446-8451` defines `NONE`, `SDP`, `SDP2`, `SEDP`, `SPDP` **and**
> `SPDP2` — both constants exist. Disregard that sub-claim. The confidence on
> the remainder is also lower than originally stated; see below.

`discovery_config.builtin_discovery_plugins` is a
`DiscoveryConfigBuiltinPluginKindMask` (`__init__.pyi:7643`) — a bitset wrapper
exposing `__and__`, `__contains__`, `test(pos)`, `count()`, `size()`, whose
`__str__` is documented only as "Convert mask to string". If that renders
`std::bitset::to_string()` binary digits, as the type's shape strongly suggests,
then `"SPDP2" not in str(plugins).upper()` returns early on every real
participant and the check cannot fire.

**Confidence: ~80%, not proof.** `__str__`'s format is not documented and could
not be established without executing the binding. What *is* certain is that the
check is testing a rendering contract the binding never promises.

**Failure scenario.** A Connext participant running SPDP2 against Fast DDS/Cyclone
peers. `blind.spdp2` never fires, so the ERROR that would explain the empty table
is absent; `blind.empty_domain`
([blind_spots.py:289-309](rti_doctor/checks/blind_spots.py#L289-L309)) lists SPDP2
nowhere in its cause list, and the `SUPPRESSION_RULES` entries keyed on
`blind.spdp2` ([findings.py:78](rti_doctor/findings.py#L78),
[findings.py:96](rti_doctor/findings.py#L96)) can never trigger. The user is sent
to check firewalls and domain IDs for a configuration the tool was written to
detect. [test_checks.py:33-36](test/test_checks.py#L33-L36) passes a plain Python
string as the mask, so the fixture cannot catch it.

**Fix.** Test the bit —
`plugins & dds.DiscoveryConfigBuiltinPluginKindMask.SPDP2` — falling back to the
string scan only when the constant is unavailable; build the fixture from the real
mask type.

### M13 — `check_no_multicast_locators` fires on every writer, from a field publications never carry

**Confirmed (binding-dependent).** Anchor:
[static_discovery.py:230-247](rti_doctor/checks/static_discovery.py#L230-L247);
source at [discovery.py:288](rti_doctor/discovery.py#L288)

`multicast_locators` exists only on `SubscriptionBuiltinTopicData`;
`PublicationBuiltinTopicData` has only `unicast_locators`. So
`compat.get(data, "multicast_locators", [])` returns the `[]` default for every
writer — and the check only runs for writers
([static_discovery.py:233](rti_doctor/checks/static_discovery.py#L233)).

Every run, for every writer including one that genuinely advertises a multicast
locator, reports `observed: "endpoint multicast_locators is empty"` and concludes
"User data will be delivered over unicast to each matched reader." Only INFO, but
it is a fabricated observation about the peer derived from a structurally
unavailable field — the exact pattern
[records.py:179-184](rti_doctor/records.py#L179-L184) warns against.

**Fix.** Read with `compat.MISSING` and stay silent when the field is unavailable
for this endpoint kind; if the question matters for writers, derive it from the
participant's discovered locators.

### M14 — `check_window` and `check_fragmentation` convert weak evidence into WARN/ERROR verdicts

Anchors: [probe_payload.py:191-219](rti_doctor/checks/probe_payload.py#L191-L219),
[probe_payload.py:145](rti_doctor/checks/probe_payload.py#L145),
[probe_payload.py:166-188](rti_doctor/checks/probe_payload.py#L166-L188)

*`check_window`*: `out_of_range_rejected_sample_count` is cumulative, but
`uncommitted_sample_count` is a point-in-time gauge of samples received and not
yet deliverable — normally because an earlier sequence number is outstanding. The
check fires on either being nonzero at the single post-window snapshot. A healthy
reliable writer at moderate rate with `uncommitted = 2` produces WARN "Samples
rejected or held by the receive window" whose root_cause asserts "the reader's
receive window was full and samples outside it were discarded". The root_cause
itself qualifies with "a *persistently* high uncommitted count" — nothing in the
check measures persistence.

*`check_fragmentation`*: `problem = probe.samples_taken == 0 and not reassembled`
has no reference to `probe.elapsed` or the writer's rate, yet the title asserts
"no sample was ever reassembled". A large-data writer using asynchronous
publishing behind a rate-limited flow controller needs longer than the default
probe window to push one sample → ERROR with a `message_size_max` remedy and exit
1, against a working system. The counters equally match "we watched for 10s in the
middle of a 30s transfer."

**Fix.** Trigger the window WARN on `out_of_range_rejected_sample_count` alone and
carry `uncommitted_sample_count` as INFO context, or sample it twice and require
persistence. For fragmentation, require corroboration (e.g. `sent_nack_fragment_count`
climbing while `reassembled` stays pinned across two samples), otherwise word it
as a window-bounded WARN naming `probe.elapsed`.

### M15 — TUI probe/sweep use bare `asyncio.create_task`

Anchors: [report_screen.py:74](rti_doctor/views/report_screen.py#L74),
[report_screen.py:91-99](rti_doctor/views/report_screen.py#L91-L99),
[app.py:41](rti_doctor/app.py#L41), [probe.py:231](rti_doctor/probe.py#L231)

Three defects from one root cause (Textual's worker API is bypassed):

1. ~~**Detached-widget exception escapes.**~~ **Withdrawn (2026-08-05).** Verified
   against the installed Textual 8.2.8: `Widget.refresh` short-circuits on an
   unmounted widget (`textual/widget.py:4363-4366`), so writing to a detached
   `Static` does not raise. The residual defect at this site is different and
   real: popping the ReportScreen with `b` does not cancel `_run_probe`, so a
   full `--probe-timeout` probe keeps creating DDS entities against the peer for
   a screen the user has left, and discards the result.
2. **Duplicate Topic → spurious ERROR.** Two ReportScreens on the same topic (or a
   ReportScreen opened while a sweep is probing that topic) both execute
   `dds.DynamicData.Topic(participant, endpoint.topic_name, endpoint.type)`. The
   second raises "topic already exists", is caught at
   [probe.py:265](rti_doctor/probe.py#L265), and surfaces as ERROR
   `probe.not_created` — "Could not create a reader for this endpoint" — for a
   healthy writer. The same false ERROR sticks permanently if a previous
   `topic.close()` failed, since `_close_all` swallows close errors at log level.
3. **No strong task reference** retained; CPython documents that a task with no
   strong reference may be garbage-collected mid-execution.

**Fix.** `self.run_worker(..., thread=True, exclusive=True)` for both; guard the
except-handler's widget writes with `if self.is_mounted`; serialize probes on a
session-level lock.

---

## Low

- **L1 — `find_writer()` is nondeterministic when a topic has more than one writer.**
  [discovery.py:98-104](rti_doctor/discovery.py#L98-L104) does
  `(resolved or candidates)[0]` over `dict.values()`, i.e. discovery-arrival order;
  `Session.sweep` deliberately sorts ([engine.py:103](rti_doctor/engine.py#L103))
  but this path does not. With an HA publisher pair, consecutive runs diagnose
  different writers, give different exit codes, and attribute wire evidence
  differently. The report never says which was chosen. *Fix:* sort by key, and name
  the selected writer's GUID in the report scope line when the topic has >1 writer.
- **L2 — Presentation `coherent_access`/`ordered_access` collapse "unreadable" into
  "not offered".** [qos_match.py:195-204](rti_doctor/checks/qos_match.py#L195-L204):
  `compat.get(..., None)` yields `None` both when the writer genuinely offers
  `false` and when the policy is unreadable; an ERROR then claims the pair "will
  never communicate". *Fix:* use `compat.MISSING` and skip when either side is
  unreadable.
- **L3 — Unreadable PARTITION is treated as the default partition.**
  [qos_match.py:96-101](rti_doctor/checks/qos_match.py#L96-L101) returns `[]` for
  both "no names" and "unreadable", and `_partitions_overlap` substitutes `[""]`.
  An unreadable policy on one side plus a named partition on the other yields an
  ERROR from an absence of evidence. *Fix:* return `None` for unreadable and skip,
  matching `_ordered_rule`'s stance at
  [qos_match.py:69](rti_doctor/checks/qos_match.py#L69).
- **L4 — `repr.no_common` warns about a hypothetical reader the registry could have
  checked.** [type_compat.py:307-324](rti_doctor/checks/type_compat.py#L307-L324)
  derives the WARN from the writer's own advertisement alone, while the registry
  already holds the discovered readers. On a healthy all-XCDR2 system every writer
  collects this WARN. *Fix:* rename to `repr.xcdr2_only` at INFO, or consult
  `registry.endpoints_on_topic`.
- **L5 — Unparseable endpoint identity silently degrades to interface-wide
  evidence.** [wire.py:85-98](rti_doctor/wire.py#L85-L98) returns `None` when
  `re.findall(r"\d+", …)` does not yield four values (reachable when
  `EndpointRecord.key` is `""` — see H4). `summarize()` then takes the permissive
  branch, and `_render_wire_appendix`
  ([report.py:304-306](rti_doctor/report.py#L304-L306)) only prints the "Writer
  GUID prefix filter" line when the key is present — so nothing marks the output as
  unfiltered. *Fix:* return a structured error rather than falling through.
- **L6 — A capture that never happened never affects the verdict or exit code.**
  `--capture-interface eth0` without tshark or `CAP_NET_RAW` produces
  `Result: unavailable: …` buried in Appendix C and exits **0**; no finding is
  generated from `wire_evidence`, so
  [__main__.py:295-296](rti_doctor/__main__.py#L295-L296) cannot see it. A CI job
  that explicitly requested wire evidence goes green having collected none.
- **L7 — `probe.attempted` means different things in text and JSON.**
  [report.py:98-104](rti_doctor/report.py#L98-L104) rewrites
  `outcome.attempted = False` when `created` is false; `render_json`
  ([report.py:380-381](rti_doctor/report.py#L380-L381)) emits the raw
  `result.attempted`, which is `True` in that state.
- **L8 — Records are mutated in place on Connext receive threads while the main/UI
  thread reads them.** The `DiscoveryRegistry` docstring
  ([discovery.py:18-25](rti_doctor/discovery.py#L18-L25)) argues that snapshotting
  via `list()` makes a lock unnecessary — true for the *container*, not the
  *records*: the snapshot copies references and `_merge_endpoint`
  ([discovery.py:144-166](rti_doctor/discovery.py#L144-L166)) then mutates the same
  `EndpointRecord` field-by-field. A PEER block can show `Type name` from a new
  sample beside `Representation` from the old. Also: `refresh_participants()` runs
  synchronously on the Textual event loop ([app.py:35-38](rti_doctor/app.py#L35-L38)),
  stalling input on large domains; and the capture file is written relative to the
  process CWD with default umask ([__main__.py:269-271](rti_doctor/__main__.py#L269-L271)),
  though it contains user payloads.

---

## Verified clean

Recorded so a future review does not re-litigate these:

- **Suppression and verdict integrity** ([findings.py:74-136](rti_doctor/findings.py#L74-L136)):
  every rule traced. No suppressed finding can lower the reported worst severity or
  the exit code; every explainer is itself ERROR and unsuppressed. One dead entry:
  [findings.py:91](rti_doctor/findings.py#L91) names `match.incompatible_qos` (the
  probe-side id); the static-analysis id is `qos.rxo_mismatch` and is registered as
  an explainer for nothing — harmless today because the two paths do not co-occur,
  but it will silently fail to suppress if the rungs are ever merged.
- **RxO direction and ordering** for RELIABILITY, DURABILITY, LIVELINESS kind,
  DESTINATION_ORDER, OWNERSHIP, DEADLINE, LATENCY_BUDGET and liveliness
  `lease_duration` ([qos_match.py:19-22](rti_doctor/checks/qos_match.py#L19-L22),
  [qos_match.py:134-193](rti_doctor/checks/qos_match.py#L134-L193)) are all correct,
  use the right attribute names, and correctly return "no verdict" when either side
  is unreadable. The infinity handling at
  [qos_match.py:42-61](rti_doctor/checks/qos_match.py#L42-L61) gives the right
  loosest-value semantics.
- **No shell injection anywhere.** Every subprocess is a list-argv `Popen`/`run`
  with no `shell=True`; the interface name and BPF filter are separate argv
  elements and the filter is composed only from integers.
- **Probe entity teardown** ([probe.py:228](rti_doctor/probe.py#L228),
  [probe.py:268-270](rti_doctor/probe.py#L268-L270)): pre-bound to `None`, `finally`
  always runs, closes reader → subscriber → topic, cannot raise.
- **`create_participant` failure path** closes a partially built participant and
  restores the previous factory QoS in `finally` — the prior finding is genuinely
  fixed apart from the variable shadowing in M1.
- **`records.representation_ids` / `representation_text`**
  ([records.py:179-218](rti_doctor/records.py#L179-L218)) draw exactly the right
  distinction between "empty sequence" and "unknown", and
  `type_compat.check_representation`'s `repr.not_advertised` branch is a model of
  the standard this review applies elsewhere.
- **`_jsonable`** ([report.py:397-404](rti_doctor/report.py#L397-L404)) plus
  `default=str` means no non-serializable object can crash `json.dumps`.
- **`compat.py`**: `to_int`'s `EventCount`/`SequenceNumber` unwrapping, `call()` vs
  `get()` for DynamicType methods, and the `MISSING` vs `None` discipline are all
  correct. `at_least()` / `version_tuple()` are unused — dead, not wrong.
- **`domain_scan.scan_active_domains`** closes its temporary participant in a
  `finally` on every path, including KeyboardInterrupt.
- **`vendors.py`** vendor-id table matches the RTPS assignments; unknown ids render
  rather than guess. Only gap: `01.0A` (Connext Micro) is unmapped, so `is_rti()` is
  `False` for it — looks deliberate.
- **README flag list** ([README.md:69-84](README.md#L69-L84)) matches `parse_args`
  exactly — no documented-but-missing or implemented-but-undocumented flags.
- **`--pcap` / `--capture-interface`** are correctly mutually exclusive.

---

## Structure and test suite

### S1 — Six E2E suites re-implement the same five primitives, and have drifted

These are not stale copies of one original; each has drifted independently.

**Domain selection — overlapping ranges, non-unique topics (Medium).**

| File:line | Base | Span | Effective range | Topic uniqueness |
|---|---|---|---|---|
| [test_live_integration.py:35](test/test_live_integration.py#L35) | 20 | 1..100 | 21–120 | fixed `"DoctorTopic"` |
| [test_rxo_vendor_e2e.py:21](test/test_rxo_vendor_e2e.py#L21) | 30 | 1..100 | 31–130 | `RxOE2E_{domain}_{mode}` — **no uuid** |
| [test_fault_vendor_e2e.py:28](test/test_fault_vendor_e2e.py#L28) | 40 | 1..80 | 41–120 | `uuid4().hex` |
| [test_fastdds_extensibility_vendor_e2e.py:19](test/test_fastdds_extensibility_vendor_e2e.py#L19) | 80 | 1..70 | 81–150 | `uuid4().hex` |
| [test_vendor_wire_e2e.py:29](test/test_vendor_wire_e2e.py#L29) | 120 | 1..100 | 121–220 | `{prefix}{domain}` |
| [test_extensibility_vendor_e2e.py:16](test/test_extensibility_vendor_e2e.py#L16) | 140 | 1..80 | 141–220 | `DoctorExtensibility{domain}` — **no uuid** |

The `DOMAIN_BASE` constants read as if deliberately partitioned per suite. They
are not — `21–120`, `31–130` and `41–120` overlap almost totally. Combined with
the two topic-name schemes that carry no uuid, two suites (or two developers on
one subnet, or a parallel CI runner) can land on the same domain *and* topic. The
RxO suite is the worst case: it asserts `matched == 0` for mismatch runs, so a
stray compatible endpoint flips a passing test to failure with no diagnostic, and
a stray reader can make a "compatible" run pass for the wrong reason.

The ranges are individually safe from the privileged-port wrap the prior review
fixed (`7400 + 250·220 = 62400`) — that part is genuinely resolved.

**Sleep-based vs readiness-based synchronization (Medium).**
[__main__.py:243-251](rti_doctor/__main__.py#L243-L251) already contains exactly
the readiness loop these tests need, and
[test_live_integration.py:73-83](test/test_live_integration.py#L73-L83) is a
hand-copy of it. Four suites instead guess with a constant
([test_fault_vendor_e2e.py:90](test/test_fault_vendor_e2e.py#L90),
[test_rxo_vendor_e2e.py:67](test/test_rxo_vendor_e2e.py#L67),
[test_extensibility_vendor_e2e.py:49](test/test_extensibility_vendor_e2e.py#L49),
[test_fastdds_extensibility_vendor_e2e.py:68](test/test_fastdds_extensibility_vendor_e2e.py#L68)).
The comments admit it — "The existing RxO suite establishes this ordering" — that
is inherited folklore, not a checked condition, and it is the stated root cause of
the permanently-disabled Fast DDS class (S3).

**Doctor invocation flags (Medium).** Only the wire suite retries exit code 2
("no writer found"), the canonical discovery race. The fault suite asserts
`returncode == 0` or `== 1`; a race returns 2 and fails with only `doctor.stderr`.
`--settle 1 --type-wait 3` ([test_fault_vendor_e2e.py:63-69](test/test_fault_vendor_e2e.py#L63-L69))
is the tightest window in the repo, while the same file's Fast DDS variant 130
lines later chose `--settle 4` with no explanation for the difference.

**One concrete process leak (Medium).**
[test_vendor_wire_e2e.py:57-62](test/test_vendor_wire_e2e.py#L57-L62):
`setUpClass` starts `cls.reader` (a 45-second subscriber) inside
`start_publisher()`, then raises `SkipTest` when the publisher died.
`tearDownClass` is not invoked after a `setUpClass` skip, so the reader runs
unreaped for 45s on the shared domain — exactly the cross-talk above.

**`SCENARIOS` is declared three times, identically (Medium)** — in
[rxo_connext_matrix.py:15-20](test/vendors/rxo_connext_matrix.py#L15-L20),
[rxo_cyclone_matrix.py](test/vendors/rxo_cyclone_matrix.py), and
[test_rxo_vendor_e2e.py:22-27](test/test_rxo_vendor_e2e.py#L22-L27). Adding a
scenario to the Connext matrix without updating the Cyclone one produces a
`KeyError` inside `_assert_compatible_data_flow` rather than a clear
"unsupported scenario" error. *Fix:* one `vendors/_scenarios.py` imported by all
three.

*Fix for the group:* a shared `test/_e2e.py` with `reserve_domain()` returning a
disjoint per-suite band, unconditional `f"{suite}_{uuid4().hex}"` topics, the
wire suite's JSON parser (H9), and the extracted readiness wait.

### S2 — `wire.summarize`'s `writer_entity_id` filter is unreachable in production

**Confirmed.** [wire.py:63](rti_doctor/wire.py#L63):
`if writer_entity_id is not None and writer_guid_prefix is None:`. Both
production call sites ([__main__.py:275-276](rti_doctor/__main__.py#L275-L276),
[wire.py:251-253](rti_doctor/wire.py#L251-L253)) always supply both, so the
entity-id filter never applies. Meanwhile
[test_wire.py:61](test/test_wire.py#L61) passes only the entity id — testing a
configuration that never occurs. The test passes; the path it covers is
unreachable from the CLI. *Fix:* apply both filters conjunctively, or delete the
parameter, and retarget the test at the real call shape.

### S3 — Skip conditions that mean "never runs anywhere"

- [test_fault_vendor_e2e.py:150-152](test/test_fault_vendor_e2e.py#L150-L152) —
  unconditional `@unittest.skip` on the entire `TestConnextFastDdsFaultControls`
  class. All four Connext↔Fast DDS fault tests are permanently dead. Two of them
  carry a second, redundant `@unittest.skip` — dead code inside dead code.
- The Fast DDS extensibility suite requires docker plus a manually built pinned
  image; the wire suite requires tshark plus capture privileges; the live suite
  requires a licensed Connext.

Net: on a machine with none of Connext, Cyclone, docker or tshark, the only tests
that execute are `test_checks.py`, `test_wire.py` and `test_findings.py` — the 62
tests `CODE_REVIEW.md:214` cites. Those touch **none** of `probe.py`,
`typewalk.py`, `engine.py`, `__main__.py`, `probe_match.py`, or
`discovery.create_participant`. That is roughly 1,900 of the package's 2,600
lines with no reachable coverage in a default environment.

### S4 — `typewalk.py` produces the headline verdict and has no deterministic test

[typewalk.py:14](rti_doctor/typewalk.py#L14) imports `rti.connextdds` at module
scope, so nothing in its 579 lines can be tested without a licensed Connext
install. `WalkReport.verdict` is what becomes `payload FULL` / `PARTIAL` /
`FAILED` — the first line of every report — and `_enum_sanity`,
`_collection_length`, `_member_present` and the truncation ceilings all decide
whether an unread member counts as absent, truncated or failed. The only coverage
is [test_live_integration.py:123-136](test/test_live_integration.py#L123-L136),
skipped whenever Connext is unavailable. *Fix:* the traversal needs `dds`, but the
verdict arithmetic, `_short_repr`, `_enum_sanity` and the ceiling logic do not —
move the import behind a function or split the pure logic into `typewalk_core`,
then unit-test the FULL/PARTIAL/FAILED/absent-only matrix with fake
`MemberResult`s. This is also what M8 needs.

### S5 — The exit-code contract is triplicated and untested

[__main__.py:296](rti_doctor/__main__.py#L296),
[__main__.py:328](rti_doctor/__main__.py#L328),
[__main__.py:348-349](rti_doctor/__main__.py#L348-L349) implement the same policy
three times using **two different representations of severity** — the `Severity`
enum in two places, a string comparison on `row["severity"]` in the third. A
relabel of `Severity.ERROR.label` breaks the sweep path only, and no test would
catch it. Every E2E suite depends on these numbers
([test_fault_vendor_e2e.py:113,126](test/test_fault_vendor_e2e.py#L113)) but
nothing tests the mapping. *Fix:* `findings.exit_code(findings) -> int`, called
from all three, unit-tested.

### S6 — Tests that assert less than their names claim

- [test_vendor_wire_e2e.py:109](test/test_vendor_wire_e2e.py#L109) —
  `test_discovers_vendor_and_identifies_wire_representation` never asserts a
  vendor; nothing in the body reads a vendor field. For `TestFastDDSWireE2E`,
  `EXPECTED_ENCAPSULATION` is left `None` (Cyclone sets it), so the encapsulation
  assertion is skipped and only a shape regex remains — the test passes if *any*
  RTPS user data was seen on the interface. With `FIXED_DOMAIN = 0` and
  `FIXED_TOPIC = "HelloWorldTopic"`
  ([test_vendor_wire_e2e.py:157-158](test/test_vendor_wire_e2e.py#L157-L158)) —
  where every unrelated Fast DDS demo on the subnet publishes — it can pass
  against a neighbour's process.
- [test_live_integration.py:157-165](test/test_live_integration.py#L157-L165) —
  `test_probe_closes_its_entities`: `before` is `None` unless the participant has
  `find_datareaders`, and the `if before is not None` guard then skips the
  assertion, so the test passes vacuously with no signal.
- The extensibility matrices
  ([test_extensibility_vendor_e2e.py:70-92](test/test_extensibility_vendor_e2e.py#L70-L92),
  [test_fastdds_extensibility_vendor_e2e.py:94-104](test/test_fastdds_extensibility_vendor_e2e.py#L94-L104))
  assert data flow for all four FINAL/APPENDABLE combinations. There is no
  negative case anywhere, and neither suite invokes Doctor — so `type_compat`'s
  compatible/incompatible conclusion has no E2E coverage at all.

### S7 — Malformed external input is unparsed and untested

- [wire.py:31-46](rti_doctor/wire.py#L31-L46) `parse_tshark_fields` pads short
  lines to 8 fields but never truncates long ones. A tshark version emitting an
  extra column, or a field value containing a tab, shifts `fields[6]`/`fields[7]`
  and silently reports wrong byte counts — `_hex_bytes` will happily compute a
  byte count from a timestamp string. No test feeds it a malformed record.
- [wire.py:119-152](rti_doctor/wire.py#L119-L152) `capture_filter` has two tested
  branches; the bounds-guard failure and the terminal `return "udp"` fallback are
  untested — and that fallback re-introduces the interface-wide capture the prior
  review set out to remove.

### S8 — No test that the VENDOR XTypes mask was applied

[__main__.py:355-361](rti_doctor/__main__.py#L355-L361) applies the compliance
mask before any DDS entity exists, and the comment there is explicit that failing
to do so makes Doctor unable to decode a compliant peer. If it silently fails,
the tool reports `type.no_type_info` against a healthy peer — a false ERROR from
Doctor's own configuration. `build_session` records the outcome into report text
only; nothing asserts it. [test_fault_vendor_e2e.py:275-279](test/test_fault_vendor_e2e.py#L275-L279)
documents this exact false positive against Fast DDS as a reason two tests are
disabled.

### S9 — Dead code and misplaced logic

**Dead** (each name appears exactly once tree-wide — verified by grep):
[engine.py:140](rti_doctor/engine.py#L140) `health_label()`,
[checks/__init__.py:99-100](rti_doctor/checks/__init__.py#L99-L100) `all_checks()`,
[compat.py:67](rti_doctor/compat.py#L67) `at_least()`,
[records.py:231](rti_doctor/records.py#L231) `policy_name()`.

Not dead despite matching the same signature: `probe.py:98,102,106` are DDS
listener callbacks invoked by the binding, and `browse.action_sweep` /
`report_screen.action_open` are Textual actions resolved by name from `BINDINGS`.

**Business logic in `__main__.py` that belongs in a module**, highest value first:

1. The endpoint readiness loop ([__main__.py:243-251](rti_doctor/__main__.py#L243-L251))
   → `Session.wait_for_writer(topic, timeout)`. Extracting it makes it testable
   *and* gives the E2E suites the primitive they keep re-inventing (S1).
2. Exit-code policy → `findings.py` (S5).
3. Capture path construction ([__main__.py:268-277](rti_doctor/__main__.py#L268-L277))
   hardcodes the relative `test_output/rti_doctor_captures` → `wire.default_capture_path(domain_id)`,
   where it can be made CWD-independent (see L8).
4. Sweep JSON payload ([__main__.py:307-320](rti_doctor/__main__.py#L307-L320)) —
   `report.py` owns every other serializer, and this is consequently the one JSON
   shape with no coverage.
5. `_settle` and `build_session` — pure session/participant lifecycle. Consolidating
   the latter into `discovery.py` would let the mock-based construction-failure
   tests the prior review requested actually be written.

**Cosmetic only:** `__import__("importlib").util.find_spec(...)` in three suites
relies on `importlib.util` having been imported as a side effect by `unittest`;
`LiveCapture`'s `capture_filter` parameter shadows the module function of the same
name; `test_rxo_vendor_e2e.py:67` has a function-local `import time`; vendor-script
`--duration` defaults range from 6.0 to 45.0 (always overridden by the tests).

### S10 — `run_checks` downgrades a crashed check to INFO

[checks/__init__.py:44-64](rti_doctor/checks/__init__.py#L44-L64) converts any
check exception into an `internal.check_failed` **INFO** finding. The design is
right, but it means a crashing `check_rxo_pairs` silently downgrades a real
incompatibility to a quiet note and `run_headless_topic` exits 0. No test asserts
that `internal.check_failed` is produced or surfaced. Consider WARN, and add a test
with a deliberately raising check.

---

## Re-verification, 2026-08-05

Every open finding was re-checked against the then-current source after the
first fixes landed and after unrelated concurrent feature work touched
`wire.py`, `report.py`, `engine.py`, `__main__.py` and `discovery.py`.

**The wire batch is unchanged.** `git diff` confirms `wire.py` gained only
`DiscoveryObservation`, `parse_discovery_fields`, `summarize_discovery` and
`inspect_discovery_pcap`; every line H3/H6/M2/M3/M9/L5 targets is byte-identical
to what was reviewed. Only line numbers moved. Earlier caution about these being
stale was unnecessary.

| Finding | Re-verified | Note |
|---|---|---|
| H3, H6, M9, L5 | CONFIRMED | Unchanged. |
| M2, M3 | CONFIRMED structurally | The code defect is certain; the *magnitude* depends on tshark runtime behaviour that cannot be established statically. Worth fixing on the structural argument alone. |
| H5 | CONFIRMED, worsened | The correlation fix added two more call sites inside the same unguarded `try`. |
| H7 | CONFIRMED, premise now proven | Textual 8.2.8 `app.py:2346-2350` does call `asyncio.run`, so the executor-shutdown join is real rather than assumed. |
| M11 | CONFIRMED | All three parts. |
| M15 | CHANGED | Sub-claim 1 withdrawn — see the finding. Sub-claims 2 and 3 stand. |
| M7, M13, M14, L1, L2, L3, L4 | CONFIRMED | M13 verified by direct enumeration of the stub class body; high confidence. |
| M8 | CHANGED | Truncation is now disclosed in the finding's prose and `evidence`, but `WalkReport.verdict` still ignores `self.truncated`, so the headline verdict is still `payload FULL` at `Severity.OK`. |
| M12 | PARTIALLY CONFIRMED | One sub-claim was **wrong** — see the correction in the finding. Confidence on the remainder is ~80%, not proof. |

`match.incompatible_qos_topic` needs no registration anywhere: this codebase has
no central finding-id registry or renderer dispatch table, ids are consumed
polymorphically, and its deliberate absence from `SUPPRESSION_RULES` is the
point. A README line distinguishing it from `match.incompatible_qos` would be a
readability improvement, not a correctness one.

### Regressions found in this review's own fixes — fixed in `d5d457d`

The H2 correlation fix acquired the defect class it was written to remove. All
three were confirmed in source before being corrected:

- An **unreadable** matched publication was counted as "some other writer". The
  bail-out only fired when *every* publication was unresolvable, so a mixed
  result reported `correlated=True` with an empty target set — which the code
  treats as proof the writer did not match. The unreadable one could have *been*
  the selected writer. Result: `match.none` ERROR and exit 1 on a healthy pair,
  under a scope line claiming publication-handle correlation.
- `matched_other_count` was a running max but read as present tense, so a
  neighbour matching for one poll iteration and departing permanently downgraded
  a genuine ERROR to the topic-level WARN — exit 0 where CI needed 1 — and
  permanently stopped crediting the target's own samples.
- `samples_other` was written and never read while `samples_taken` changed
  meaning, so `check_silent` compared a writer-scoped count against the
  topic-wide `received_sample_count` and sent users to cache-drop findings that
  did not exist.

### New findings in the concurrent feature work

Not part of the original review; recorded here because they were found while
re-verifying. All are in work that was uncommitted at the time.

- **N1 (High) — `NameError` in two headless entry points.** `topology` is used at
  `__main__.py:378` and `:419` but the only import is function-local at `:306`,
  inside `run_headless_topic`, where it is unused. A function-local `import`
  binds a local, never a module global, so `rti_doctor --all` and the no-TTY
  headless path crash *after* the full sweep completes. Fix: add `topology` to
  the module-scope import at `__main__.py:9`.
- **N2 (Medium)** — `inspect_discovery_pcap` repeats M9 exactly: no `timeout=`,
  `capture_output=True`, and a `-Y rtps` filter that admits far more frames than
  `inspect_pcap`'s encap-kind filter.
- **N3 (Medium)** — `-E occurrence=f` across seven *per-submessage* fields takes
  the first `wrEntityId` and the first `rdEntityId` found anywhere in a frame,
  independently. Coalesced submessages therefore fabricate `(prefix, wr, rd)`
  tuples that never appeared on the wire, and a batched SEDP message contributes
  exactly one `topicName`, under-reporting topics.
- **N4 (Medium)** — `summarize_discovery` labels its output participants and
  endpoint observations, but `-Y rtps` admits ordinary user DATA/HEARTBEAT/ACKNACK,
  so `participants` counts senders of any RTPS packet and one logical writer
  yields several tuples. Same absence-of-scope problem the review flags elsewhere.
- **N5 (Low)** — the discovery path returns `pcap_source` while every renderer
  reads `source`; latent only because `inspect_discovery_pcap` has no caller.
- **N6 (Low)** — `topology.snapshot` merges scanned domains into `domain_ids`
  and prints them directly above counts drawn from a single-domain registry.
- **T3 (Medium)** — `registry.writers()`, `readers()`, `endpoints_for()`,
  `endpoints_on_topic()` and `topic_names()` comprehend over live `dict.values()`
  rather than copies, contradicting `DiscoveryRegistry`'s docstring claim that
  every consumer snapshots. `_drain_endpoints` mutates the same dict from Connext
  receive threads, so a concurrent update raises `RuntimeError: dictionary
  changed size during iteration`. Pre-existing, but `topology.snapshot` now walks
  the endpoint dict twice per writer per sweep, greatly widening the window.

## Recommended order of work

0. **H8, M1** — both are a few characters, both are shipping today. H8 mislabels
   the root cause of the most common cross-vendor fault; M1 makes every Doctor run
   unidentifiable on the domain.
1. **H1, M4** — static QoS correctness. Small, self-contained, and they are the
   difference between `qos.compatible` meaning something and meaning nothing. Fix
   the `test_checks.py` fakes in the same change, since the fakes are what let H1
   survive.
2. **H2** — probe/writer correlation. The largest change, and the one that makes
   rungs 4–5 trustworthy.
3. **H4, M5, M6** — discovery lifecycle and merge. All three are small and they
   compound: H4 leaves dead endpoints, M6 loses live ones, M5 poisons the report
   about the survivors.
4. **H3, H6, M2, M3, M9** — the wire path. Consider whether the appendix should be
   labelled provisional until these land.
5. **H5, H7, M11, M15** — lifecycle and error handling.
6. **M1** — one-line fix, do it immediately; it is the most visible defect to
   anyone else on the domain.
7. **S1, S5** — the shared test helper and the extracted exit-code function. These
   are prerequisites for trusting any of the fixes above: today a fix and a domain
   collision produce the same red.
8. Everything else.

## Test gaps implied by these findings

Each of these would have caught a finding above and none exists today:

| Missing test | Would have caught |
|---|---|
| Presentation `access_scope` mismatch built from the real binding type | H1 |
| Two writers on one topic, one selected, assertions scoped to the selection | H2, L1 |
| PCAP fixture with target-participant SEDP *and* user DATA | H3 |
| Disposal sample whose `data.key` is unpopulated | H4 |
| Probe where `_snapshot_statuses` raises | H5 |
| `LiveCapture` whose process has already exited at `finish()` | H6 |
| Assertion on the participant name | M1 |
| Fragmented capture fixture asserting `data_fragments > 0` specifically | M3 |
| Writer `[XCDR1, XCDR2]` vs reader `[XCDR2]` | M4 |
| Second participant sample with `partial_configuration = False` | M5 |
| Builtin batch where sample *i* raises | M6 |
| Walk that truncates, asserting the verdict is not `FULL` | M8 |
| `--probe-timeout -1` / `--type-wait -1` / `-d -1` argument validation | M10 |
| `builtin_discovery_plugins` fixture built from the real mask type | M12 |
| Any unit test at all importing `checks/probe_match.py` | H8 |
| Doctor stdout with trailing `ERROR PRESPsService_cleanup:` noise | H9 |
| `wire.parse_tshark_fields` with an extra column or an embedded tab | S7 |
| `findings.exit_code()` across all three severity paths | S5 |
| `WalkReport.verdict` matrix with synthetic `MemberResult`s | S4, M8 |
