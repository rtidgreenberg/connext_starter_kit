# RTI Doctor Design Decisions

This log records explicit decisions made while resolving findings from
`CODE_REVIEW_2026-08-07.md`. It records *what was decided and why*, not what has
been built: implementation status is tracked per finding in
`CODE_REVIEW_2026-08-07.md`, which carries a Status column and a commit for each
fix. An entry here staying "Accepted" says nothing about whether it has shipped.

Entries are historical. When a later decision changes an earlier one, the
earlier entry keeps its original text and gains an **Amendment** line rather
than being rewritten, so the reasoning that was actually applied at the time
stays readable.

## Decision Template

### <ID>: <Title>

- **Date:** YYYY-MM-DD
- **Status:** Accepted | Deferred | Superseded
- **Amendment (date):** (only when a later decision changes this one)
- **Problem:**
- **Decision:**
- **Rationale:**
- **Consequences:**
- **Follow-up:**
- **References:**

## Decisions

### C1: Discovery Capture Field Misalignment

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `inspect_discovery_pcap()` requests 13 tshark fields while
	`parse_discovery_fields()` maps 12, shifting the discovery metadata after the
	GUID prefix.
- **Decision:** Define one ordered discovery-field layout shared by tshark command
	construction and parser validation/mapping. Remove the duplicate early
	`rtps.sm.wrEntityId` entry so the layout contains the intended 12 fields.
- **Rationale:** This corrects the live field shift and prevents command/parser
	drift from returning through independently maintained lists.
- **Consequences:** The discovery parser remains on its existing 12-field
	contract. Tests must construct discovery rows from the shared layout or assert
	that the command and parser expect the same field count.
- **Follow-up:** Implement the shared layout, update `test_wire_discovery.py`,
	and run focused discovery plus unit tests. Reassess C1a-C1c when the Fast DDS
	version feature becomes reachable.
- **References:** `CODE_REVIEW_2026-08-07.md` C1; `rti_doctor/wire.py`;
	`test/test_wire_discovery.py`.

### Q1: Unreadable Partition Becomes a False Error

- **Date:** 2026-08-10
- **Status:** Accepted
- **Extended by:** Q1a, which chooses the shared incomplete-evidence
	representation this entry's follow-up leaves open.
- **Problem:** Unreadable PARTITION data collapses into the explicit empty/default
	partition state and can produce a false `qos.rxo_mismatch` ERROR.
- **Decision:** Distinguish unreadable partition data from an explicit empty
	partition. Do not create a mismatch when either side is unreadable; emit an
	informational result or evidence record that PARTITION was not evaluated.
- **Rationale:** This prevents an unsupported incompatibility claim while making
	incomplete comparison evidence visible to the operator.
- **Consequences:** Explicit empty/default partition behavior remains unchanged.
	QoS output gains an incomplete-evidence path that should be reusable by other
	unreadable-policy findings.
- **Follow-up:** Add unreadable-partition coverage, preserve named/default
	partition coverage, and decide the common evidence/reporting representation for
	Q2 and Q4.
- **References:** `CODE_REVIEW_2026-08-07.md` Q1; `rti_doctor/checks/qos_match.py`;
	`test/test_checks.py`.

### Q2: Unreadable Presentation Boolean Becomes a False Error

- **Date:** 2026-08-10
- **Status:** Accepted
- **Extended by:** Q1a, which chooses the shared incomplete-evidence
	representation this entry's follow-up leaves open.
- **Problem:** Unreadable PRESENTATION boolean values are treated as explicit
	`false` offers and can produce a false `qos.rxo_mismatch` ERROR.
- **Decision:** Compare `coherent_access` and `ordered_access` only when both
	values are explicitly readable. When either value is unreadable, record an
	informational result or evidence entry that the boolean was not evaluated.
- **Rationale:** This follows the Q1 decision: unavailable discovery data must
	not be converted into an incompatibility claim, but the gap remains visible.
- **Consequences:** Explicit true/false comparison behavior remains unchanged.
	QoS reporting needs one shared incomplete-evidence representation for
	PARTITION, PRESENTATION, and later unreadable-policy work.
- **Follow-up:** Add unreadable writer and reader boolean tests, preserve the
	existing explicit-boolean mismatch tests, and design the common Q1/Q2/Q4
	evidence/reporting format.
- **References:** `CODE_REVIEW_2026-08-07.md` Q2; `rti_doctor/checks/qos_match.py`;
	`test/test_checks.py`.

### Q1a: Shared Incomplete-Evidence Representation for QoS

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Q1, Q2 and X4 each defer to "a common incomplete-evidence
	representation" without choosing one. Every RxO rule that declines on
	unreadable input returns nothing, so a pair where ten policies were compared
	and a pair where almost nothing was readable produce identical verdicts.
- **Decision:** `compare_endpoints` returns `(mismatches, unevaluated)`. Each
	rule returns either a mismatch dict or an unevaluated record - `{policy,
	reason}`, distinguished by the `reason` key - and the caller files it. The
	unevaluated list is carried as `evidence["policies_unevaluated"]` and rendered
	as a "Not evaluated (...)" sentence on the `observed` line of both
	`qos.compatible` and `qos.rxo_mismatch`. Every rule participates, not only the
	policies a finding named.
- **Rationale:** A channel populated for one policy is worse than none: its
	absence then certifies that everything else was compared. Reporting on both
	verdicts matters because a pair can carry a real mismatch and an unread policy
	at once, and the mismatch must not imply the rest was checked.
- **Consequences:** A readable value that no ordering applies to is a third
	outcome, not a gap - a reader requesting PRESENTATION `HIGHEST_OFFERED` matches
	every writer, so it is recorded as compatible via `reader_accepts_any` rather
	than as unevaluated. X4's assignability incomplete-evidence result should adopt
	the same `{policy, reason}` shape when it is done.
- **Follow-up:** Q4's other half - recording which policies *were* compared, and
	phrasing the OK line as "N of M policies compared" - is not decided. Q3 and Q5
	are now disclosed as unevaluated but their verdicts are unchanged and still need
	decisions.
- **References:** `CODE_REVIEW_2026-08-07.md` Q1, Q2, Q3, Q4, Q5, X4; Q1, Q2 and
	X4 decisions; `rti_doctor/checks/qos_match.py`; `test/test_checks.py`.

### C2: `--all` Omits the Domain Audit

- **Date:** 2026-08-10
- **Status:** Accepted; the deprecation timeline is superseded by S4
- **Amendment (2026-08-10):** S4 settled the removal timeline this entry left
	open, in the opposite direction: `--all` is removed outright rather than
	deprecated and kept for a compatibility release, so no deprecation message is
	emitted and the Consequences line below no longer applies. Everything else
	here - the two-stage workflow and the reasoning for it - stands and governs.
	C2a records the entry point that resulted.
- **Problem:** `--all` runs a costly full diagnosis for every discovered writer,
	but omits the system/domain checks that explain discovery failures. This does
	not scale to systems with hundreds of writers and presents the wrong workflow.
- **Decision:** Deprecate `--all`. Simplify the product workflow into two stages:
	a DDS system-level assessment for discovery, topology, and local configuration;
	then an explicit targeted diagnosis for one selected writer or topic.
- **Rationale:** System-level checks are inexpensive and answer whether the DDS
	system is visible and healthy. Per-writer diagnosis is intentionally focused,
	avoiding an expensive sweep that scales linearly with writer count and may add
	probes/captures for every writer.
- **Consequences:** `--all` must emit a deprecation message and be removed or
	changed in a later compatibility release. Documentation, CLI help, JSON
	consumers, and tests must direct users to system assessment plus targeted
	diagnosis instead of a complete writer sweep.
- **Follow-up:** Define the system-level output contract and targeted-selection
	UX, decide a deprecation/removal timeline for `--all`, and add scale coverage
	proving that system assessment does not run per-writer diagnostics.
- **References:** `CODE_REVIEW_2026-08-07.md` C2; `rti_doctor/__main__.py`;
	`rti_doctor/engine.py`; `test/test_cli.py`.

### C2a: Headless Entry Point for the System Assessment

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** C2 left "define the system-level output contract and
	targeted-selection UX" open, and S4 removed `--all`. The headless system report
	was selected only by a non-tty stdin, so with `--all` gone a user at a terminal
	had no way to ask for stage one at all: a tty always won and launched the TUI.
	The workflow C2 chose was therefore unreachable as documented.
- **Decision:** Add an explicit `--system` flag for stage one. It runs the same
	passive scan the TUI shows - the rung-0/1 blind-spot audit plus the system-wide
	discovery, type and RxO census - creating no reader and probing nothing. Name
	the dispatch rule `is_headless()` and use it in both `parse_args` and `main`, so
	the two cannot disagree about which mode an invocation is in. Stage one is a
	text report; `--format json` applies only to `--topic` and is refused at parse
	time on the system path.
- **Rationale:** The two stages must both be nameable, not inferred from whether
	stdin happens to be a terminal. Stage one must be the full passive census
	rather than the blind-spot audit alone, because `--all` was what a CI job ran to
	catch a system-wide RxO or type failure - assessing only rung 0/1 would have
	removed that gate along with the flag. Refusing JSON beats emitting text to a
	consumer that asked for JSON.
- **Consequences:** `rti_doctor -d N --format json` with no `--topic` now exits
	2 with an explanation instead of producing output. Stage one has no
	machine-readable form; H1 removes `--format json` entirely, so this is a
	narrowing of a surface already scheduled for removal. The system report carries
	the RTI_DOCTOR OWN CONFIGURATION section, so every report still states how the
	measurement was made.
- **Follow-up:** If a machine-readable system contract is ever wanted, decide it
	deliberately rather than reviving `--format json`. Stage one waits `--settle`
	and then `--type-wait` before scanning, both through the polling helper; revisit
	if that startup cost becomes a problem in CI.
- **References:** `CODE_REVIEW_2026-08-07.md` C2, S4; C2 and S4 decisions;
	`rti_doctor/__main__.py`; `test/test_cli.py`.

### C3: Empty-Domain Screens Disagree About the Issue Count

- **Date:** 2026-08-10 (recorded after the fact; the change shipped in
	`d339403`)
- **Status:** Accepted
- **Problem:** The landing screen and the issue list suppressed the issue
	counts whenever no participants were discovered, but the rung-0 blind-spot
	checks run unconditionally and are exactly the ones that fire on an empty
	domain. With a rung-0 finding present the issue list rendered its row while
	the status line above it said "there is nothing to report", the landing
	screen showed no count at all, and the severity menu showed the real one -
	three answers on screen at once, and a saved report that agreed with none of
	them.
- **Decision:** Suppress the counts only when there is genuinely nothing to
	count: both screens test `participants == 0` **and** an empty issue list. An
	empty domain that produced a finding reports that finding and its count,
	prefixed with "No DDS discovered on domain N" so the reader knows the count
	did not come from observed traffic. The severity menu is left unguarded.
- **Rationale:** "Nothing was observed" and "nothing is wrong" are different
	statements, and the tool exists to keep them apart - but the guard that was
	protecting the first had started denying the second. The counts are not the
	hazard; counts *without* the empty-domain caveat are, so the caveat travels
	with them instead of replacing them.
- **Consequences:** Three of the four surfaces now state the empty-domain
	caveat and the counts together. The fourth, `IssueSeverityScreen`, still
	renders a bare `Errors 0 | Warnings 0 | Info 0` on a quiet domain. That is
	accepted rather than fixed: it is reached only from a screen that has just
	said nothing was observed, and every severity selectable from it lands on a
	list that says the same, so a shared "these counts are meaningless"
	mechanism across all four surfaces was judged not to earn its cost. Revisit
	if a fifth surface appears, or if that menu ever becomes reachable directly.
- **Follow-up:** None outstanding. The regression test
	(`test_empty_domain_with_active_issue_shows_its_error_count`) covers the
	landing screen and the issue list; it does not cover the severity menu or
	the saved report, which is the gap to close first if this is reopened.
- **References:** `CODE_REVIEW_2026-08-07.md` C3;
	`rti_doctor/views/system_overview.py`; `rti_doctor/report.py`;
	`test/test_views.py`.

### X1: Local Multicast Defaults Check Is Not a System Diagnostic

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `blind.no_multicast_no_peers` reads RTI Doctor's own participant
	QoS, not remote discovery locators or deployed-participant configuration. RTI
	Doctor uses multicast-enabled defaults, so the check does not diagnose the DDS
	system and its `initial_peers` logic does not affect the result.
- **Decision:** Remove `blind.no_multicast_no_peers` and its unused multicast/
	initial-peer logic. Do not replace it with a local-default-QoS warning.
- **Rationale:** A diagnostic must not present RTI Doctor's own default settings
	as evidence about the deployed system. Remote locator data remains available
	for topology and capture use, but it is not sufficient to prove multicast
	reachability.
- **Consequences:** The blind-spot audit has one fewer local configuration
	finding. Any suppression rule, documentation, and tests referring to
	`blind.no_multicast_no_peers` must be removed or updated.
- **Follow-up:** Remove the check and associated suppression/test references;
	confirm no report or documentation promises multicast-reachability diagnosis.
- **References:** `CODE_REVIEW_2026-08-07.md` X1;
	`rti_doctor/checks/blind_spots.py`; `rti_doctor/findings.py`;
	`test/test_checks.py`.

### X2: Global Automatic Suppression Hides Unrelated Findings

- **Date:** 2026-08-10
- **Status:** Accepted
- **Extended by:** X2a, which defines the replacement causal-link
	representation this entry's follow-up leaves open.
- **Problem:** Suppression matches only on finding ID across the whole system, so
	one ERROR can remove unrelated symptoms from active findings and counts.
- **Decision:** Remove automatic suppression. Keep causal relationships as
	report context or links, but do not hide findings or exclude them from active
	counts, status, or exit behavior.
- **Rationale:** The system-level-then-targeted workflow favors complete and
	understandable evidence over reducing report rows. An independent failure must
	never be hidden by an inferred explanation elsewhere.
- **Consequences:** Reports may show both a likely cause and its symptoms. The
	`suppressed_by` model, suppression rules, related report sections, and tests
	need removal or conversion to non-suppressing causal references.
- **Follow-up:** Define the replacement causal-link representation, update
	renderers and exit/count calculations, remove `SUPPRESSION_RULES`, and add
	regression coverage that all findings remain active.
- **References:** `CODE_REVIEW_2026-08-07.md` X2; `rti_doctor/findings.py`;
	`rti_doctor/system_scan.py`; `rti_doctor/report.py`; `test/test_findings.py`.

### X2a: Causal Link Representation

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** X2 decided to keep causal relationships "as report context or
	links" without defining what replaces `suppressed_by`.
- **Decision:** `SUPPRESSION_RULES` becomes `CAUSAL_EXPLAINERS`, and
	`link_causes()` sets `Finding.explained_by` to the ids present in the same run
	that would explain that finding. `SystemIssue` carries the same field.
	Renderers print a "Likely explained by" line that states the link is by finding
	id alone and should be confirmed before acting on it. Nothing filters on the
	field.
- **Rationale:** The reader needs the hypothesis and the fact side by side. The
	caveat is part of the representation, not decoration: the link is unscoped, so
	it can point at a condition on another topic, and saying so is what makes an
	unscoped link safe to publish.
- **Consequences:** The ERROR-severity gate on explainers is dropped - it
	existed to justify hiding a finding, and nothing is hidden now, so a WARN cause
	is worth naming. The `active`/`suppressed` split, both SUPPRESSED report
	sections and `ReportData.blind_spot_findings` are gone. The JSON report's
	per-finding `suppressed_by` string becomes `explained_by`, a list.
- **Follow-up:** `CAUSAL_EXPLAINERS` membership is now an editorial judgement
	about what to *suggest* rather than what to hide, so entries should be reviewed
	against that lower bar; an unattributable topic-wide finding still must not be
	offered as the cause of a pair-scoped symptom.
- **References:** `CODE_REVIEW_2026-08-07.md` X2, X1; X2 decision;
	`rti_doctor/findings.py`; `rti_doctor/report.py`; `rti_doctor/system_scan.py`;
	`test/test_findings.py`.

### X3: Reader Type Failures Are Reported as Writer Failures

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Targeted diagnosis can call `check_type_state()` for a DataReader,
	but its unavailable-type finding is written exclusively for a writer and sends
	the operator to the publisher.
- **Decision:** Make `check_type_state()` role-aware. Preserve the existing
	writer wording and add a reader-specific title, evidence, root cause, and
	remedy that direct investigation to the subscriber/reader side.
- **Rationale:** Targeted diagnosis supports either endpoint role; remediation
	must identify the endpoint that actually lacks usable type information.
- **Consequences:** Writer reports retain their existing wording. Reader reports
	gain accurate guidance and focused test cases must cover both roles.
- **Follow-up:** Add direct reader and writer unavailable-type tests and confirm
	system-level rollups still intentionally evaluate only writers.
- **References:** `CODE_REVIEW_2026-08-07.md` X3;
	`rti_doctor/checks/type_compat.py`; `rti_doctor/engine.py`;
	`test/test_checks.py`.

### X4: Assignability OK Overstates What Was Checked

- **Date:** 2026-08-10
- **Status:** Accepted
- **Extended by:** Q1a, which chooses the incomplete-evidence shape this
	entry's follow-up defers.
- **Amendment (2026-08-10):** Implemented as decided, with two choices this
	entry left open. The `{policy, reason}` record gained `reader`/`reader_key`,
	because several readers can be unevaluable for different reasons and a
	per-policy record has nothing to name them with. The "informational result"
	is an unevaluated record on the existing OK/ERROR verdict - the Q1a
	precedent - except when no reader at all could be evaluated, where there is
	no verdict to carry it and an INFO finding is emitted instead. That finding
	is topic-scoped, which is how it avoids the per-writer noise this entry's
	consequences warn about: the unevaluable readers belong to the topic, so
	every writer on it faces the same ones.
- **Problem:** Assignability reporting labels only successfully evaluated readers
	as resolved and returns no finding when all resolved readers are unevaluable.
	This can present partial structural validation as a complete all-clear.
- **Decision:** Report resolved, evaluated, and unevaluable reader counts
	separately. Emit an informational incomplete-evidence result whenever one or
	more readers cannot be evaluated, including when none can be evaluated.
- **Rationale:** Connext AI confirms that native Connext `DynamicType` objects
	normally support `is_assignable_from()`, but cross-vendor/non-native type
	representations or failed binding calls can make structural evaluation
	unavailable. That state is neither compatible nor incompatible and must be
	visible.
- **Consequences:** Targeted diagnosis gains an informational assignability
	result for partial/failed evaluation. System-level reporting must aggregate or
	otherwise avoid producing repetitive per-writer informational noise.
- **Follow-up:** Preserve the explicit True/False outcomes, add tests for
	partial and wholly unevaluable reader sets, include evaluation failure reasons
	as evidence, and define the shared incomplete-evidence report format with Q1,
	Q2, and Q4.
- **References:** `CODE_REVIEW_2026-08-07.md` X4;
	`rti_doctor/checks/type_compat.py`; `test/test_checks.py`; Connext AI query
	on 2026-08-10 regarding `DynamicType.is_assignable_from()`.

### H1: JSON Mode Does Not Guarantee JSON on Standard Output

- **Date:** 2026-08-10
- **Status:** Accepted
- **Amendment (2026-08-10):** Implemented, with two departures from the
	follow-up. There was no deprecation period: `--format` is removed outright
	and now fails argument parsing, on the same reasoning as S4 - a flag that is
	accepted and ignored leaves a CI job believing it still gets JSON, and the
	only consumer was this repo's own test harness. And no Markdown contract was
	defined: the existing fixed-width plain-text report was adopted as the
	contract unchanged, because it already carries one
	`[SEVERITY] rung N  finding.id` line per finding with labelled fields under
	it, which is what `test/doctor_e2e.parse_report` reads. Converting the report
	to Markdown remains undecided and is not required by anything now shipping.
- **Problem:** The current JSON mode is mixed with wrapper banners, prompts, and
	progress output. Maintaining a strict machine-readable JSON contract is not a
	product goal for RTI Doctor.
- **Decision:** Make Markdown/text reports the primary output contract for human
	and LLM consumption. Deprecate and remove `--format json` rather than adding a
	strict JSON-only stdout mode.
- **Rationale:** RTI Doctor is a diagnostic reporting tool, not a machine API.
	Markdown preserves findings, evidence, and remedies in a readable form for
	both operators and LLM workflows without maintaining a second output schema.
- **Consequences:** Documentation, CLI help, tests, wrapper behavior, and any
	JSON consumers must migrate to Markdown/text reports. The remaining standard
	output may retain human-oriented progress and startup context.
- **Follow-up:** Define the Markdown report contract and deprecation/removal
	timeline; remove JSON rendering and tests; ensure the system-level and
	targeted reports remain easy to consume programmatically as text.
- **References:** `CODE_REVIEW_2026-08-07.md` H1; `rti_doctor/__main__.py`;
	`rti_doctor/report.py`; `run_rti_doctor.sh`; `test/test_cli.py`.

### H2: FINAL-Type Warning Repeats for Every Endpoint

- **Date:** 2026-08-10
- **Status:** Accepted
- **Amendment (2026-08-10):** Implemented as decided. The targeted severity
	chosen was INFO, not OK: the clean branch stays OK because there is nothing
	to say, while a FINAL or mixed type is something an operator should know
	before changing the IDL. The review's alternative - keep it in the census but
	escalate to WARN when `type.assignability` is False - was deliberately not
	built. With the note out of the census there is nothing left to escalate, and
	`type.assignability` already carries that verdict itself, so the escalation
	would only have restated one finding inside another.
- **Problem:** The system scan runs extensibility analysis for every endpoint,
	producing repeated FINAL-type warnings for one shared schema even when no
	observed incompatibility exists.
- **Decision:** Remove `check_extensibility()` from the system-level issue scan.
	Retain extensibility information as descriptive INFO/context in targeted
	writer/topic diagnosis.
- **Rationale:** In the system-level-then-targeted workflow, extensibility is
	context for investigating a selected type, not an independently actionable
	system-wide issue. This removes repeated warning noise without losing the
	information where it is useful.
- **Consequences:** System reports no longer list `type.extensibility` warnings.
	Targeted reports must continue to render the type map and clearly distinguish
	descriptive extensibility information from an observed assignability failure.
- **Follow-up:** Separate targeted and system check sets, change targeted
	extensibility severity/text to descriptive output, update report tests, and
	remove system-level warning-count expectations.
- **References:** `CODE_REVIEW_2026-08-07.md` H2;
	`rti_doctor/checks/type_compat.py`; `rti_doctor/system_scan.py`;
	`test/test_checks.py`.

### H3: A Paired QoS Issue Cannot Open a Targeted Report

- **Date:** 2026-08-10
- **Status:** Accepted
- **Amendment (2026-08-10):** Implemented, generalised past a pair. The
	selector takes any number of endpoints rather than exactly two, because H4
	lets a topic-scoped issue name several and a picker special-cased to
	writer-plus-reader would have had to be rebuilt immediately. The issue list's
	own open action was folded into the same function, which this entry did not
	ask for: it was silently opening the writer for the same row the detail
	screen refused, so `o` meant two different things depending on which screen
	the operator pressed it from.
- **Problem:** A `qos.rxo_mismatch` names both a writer and reader, but the issue
	detail open action requires exactly one combined endpoint and therefore cannot
	open either report.
- **Decision:** For a paired issue, open a compact selector that lets the user
	choose the writer or reader targeted report.
- **Rationale:** RxO is directional: the writer offers QoS while the reader
	requests the minimum acceptable QoS. Both sides are legitimate investigation
	targets, so defaulting silently to the writer would hide the reader-driven
	constraint.
- **Consequences:** The issue-detail screen gains a small paired-endpoint
	selection interaction. Single-endpoint issues retain direct open behavior.
- **Follow-up:** Implement the picker, label offered/requested roles clearly,
	correct the failed-action status text, and add UI coverage for pair and
	single-endpoint issue navigation.
- **References:** `CODE_REVIEW_2026-08-07.md` H3;
	`rti_doctor/views/system_overview.py`; `rti_doctor/checks/qos_match.py`.

### H4: Topic-Scoped Issue Linkage Is Lost During Deduplication

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `type.name_conflict` correctly produces one topic-scoped issue,
	but its topic scope currently withholds endpoint and participant identity. The
	participants therefore appear healthy and cannot filter to the issue.
- **Decision:** Keep the topic-scoped issue key, while carrying every involved
	endpoint and participant key as linkage metadata.
- **Rationale:** A type-name conflict is one topic-level condition, but all
	participating endpoints and participants need to surface and navigate to it.
- **Consequences:** Deduplication stays topic-scoped; participant and endpoint
	health/filter views show the shared issue without duplicating it.
- **Follow-up:** Collect all involved linkage keys when producing the
	topic-scoped finding, preserve them through issue aggregation, and add
	coverage for participant health and issue filtering.
- **References:** `CODE_REVIEW_2026-08-07.md` H4;
	`rti_doctor/checks/type_compat.py`; `rti_doctor/system_scan.py`;
	`rti_doctor/views/system_overview.py`.

### H5: Topology Actions Crash Before a First Successful Scan

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** After a first-scan failure, Topology has no snapshot, but view
	switching, issue filtering, and report saving dereference it and raise an
	action-handler exception.
- **Decision:** Guard every topology operation that requires a snapshot. When
	no data exists yet, retain the failed-scan state and show a concise message
	directing the operator to retry with `r`.
- **Rationale:** An empty snapshot would falsely imply a valid system
	assessment. Safe action guards preserve the distinction between no collected
	data and a healthy empty topology.
- **Consequences:** Topology controls remain available but explain why
	data-dependent actions cannot proceed before the first successful scan.
- **Follow-up:** Centralize the no-snapshot guard where practical; cover view
	switching, linked-issue navigation, and saving after an initial scan failure;
	preserve current stale-snapshot behavior after later failures.
- **References:** `CODE_REVIEW_2026-08-07.md` H5;
	`rti_doctor/views/system_overview.py`; `test/test_views.py`.

### H6: Manual Scenario Exit Cleanup Reads Expired Function Locals

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Scenario `EXIT` traps invoke cleanup functions after their
	enclosing function has returned. With `set -u`, function-local process IDs
	and container names are unset, causing successful runs to fail and potentially
	skipping Docker cleanup.
- **Decision:** Use shared cleanup helpers with explicit arguments. Each
	scenario trap captures its current process IDs and container names at trap
	registration, so cleanup remains valid after function scope ends.
- **Rationale:** Explicit captured state preserves local scenario ownership,
	avoids global mutable cleanup state, and gives normal exits and signals one
	cleanup route.
- **Consequences:** Trap setup must safely quote captured arguments. `INT` and
	`TERM` handlers must exit through the same `EXIT` cleanup path.
- **Follow-up:** Replace all three local cleanup functions, add a short-duration
	normal-completion regression test or harness, and verify containers are
	removed on both normal completion and interruption.
- **References:** `CODE_REVIEW_2026-08-07.md` H6;
	`test/run_manual_scenario.sh`.

### H7: Interactive CLI Setup Can Leak a Participant and Capture Process

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `main()` creates its session and may start a discovery capture
	before entering its cleanup `try/finally`. An interrupt or setup failure can
	therefore leave the participant or `tshark` capture process running.
- **Decision:** Enter the `try/finally` immediately after successful session
	creation and perform capture startup, readiness handling, ready-file creation,
	and all execution modes inside that boundary.
- **Rationale:** One ownership boundary makes resource cleanup unavoidable for
	all post-session control paths, matching the existing headless-topic pattern.
- **Consequences:** Early timeout-specific cleanup becomes unnecessary; the
	`finally` must remain resilient when capture startup only partly completes.
- **Follow-up:** Restructure `main()`, add mocked interruption/setup-failure
	lifecycle tests, and verify the participant and capture are each closed once
	on success, timeout, and exception.
- **References:** `CODE_REVIEW_2026-08-07.md` H7;
	`rti_doctor/__main__.py`; `test/test_cli.py`.

### H8: TUI Reports Start Packet Capture Without Operator Consent

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Opening a writer report in the TUI silently starts a privileged
	`tshark` capture on `any`, creates packet-capture artifacts, and delays the
	report even when the operator did not request wire evidence.
- **Decision:** Make packet capture an explicit `c` TUI action on both reader
	and writer endpoint reports, with the selected interface and artifact
	destination shown. For fields that require packet capture, such as Fast DDS
	version information, render a placeholder that says `Run capture to
	ascertain` when evidence is unavailable.
- **Rationale:** Wire evidence remains available for focused interoperability
	diagnosis, but collection is an intentional operator action. The placeholder
	identifies useful unknowns without treating them as errors or capturing
	traffic implicitly.
- **Consequences:** A normal targeted report performs DDS-only diagnosis.
	Reader and writer reports can each request a bounded capture. Capture-
	dependent report fields need an explicit unavailable state and update after a
	successful capture.
- **Follow-up:** Add the reader/writer capture interaction and status/progress
	display; render packet-only fields with the placeholder; test no-capture,
	reader capture, writer capture, and capture-failure report states; retain CLI
	`--capture-interface` behavior.
- **References:** `CODE_REVIEW_2026-08-07.md` H8;
	`rti_doctor/views/report_screen.py`; `rti_doctor/engine.py`;
	`rti_doctor/report.py`.

### H9: Startup Discovery Capture Is Unbounded and Discarded

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Startup discovery capture can run for the whole TUI session,
	captures all traffic within the domain RTPS port range, leaves PCAP/log
	artifacts, and blocks at shutdown parsing evidence that is then discarded.
- **Decision:** Remove automatic startup discovery capture. Collect Fast DDS
	version and other packet-only evidence only through the explicit `c` capture
	action on a selected reader or writer report.
- **Rationale:** System assessment remains DDS-level and passive. Packet capture
	is focused, intentional evidence gathering with a selected endpoint context.
- **Consequences:** System reports show packet-only facts as unavailable until
	the operator runs capture from an endpoint report. Startup no longer starts,
	stores, parses, or cleans up a long-lived discovery capture.
- **Follow-up:** Remove startup capture setup and shutdown parsing paths; route
	captured Fast DDS versions into the selected report; update CLI/TUI help and
	tests; verify no capture artifacts are created during a normal TUI session.
- **References:** `CODE_REVIEW_2026-08-07.md` H9;
	`rti_doctor/__main__.py`; `rti_doctor/engine.py`; `rti_doctor/wire.py`.

### H10: One Unreadable Participant Can Abort a Discovery Refresh

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** An exception while parsing one participant's builtin discovery
	data can abort the whole refresh cycle, skipping later participants and
	producing a fabricated incomplete topology.
- **Decision:** Isolate complete parsing and registry update per participant,
	matching endpoint-drain behavior. Mark the failing participant unreadable and
	skip departure sweeping for that cycle; do not construct or infer a partial
	participant record from unreadable data.
- **Rationale:** Preserve discovery progress for known-good participants while
	maintaining a high-confidence reporting standard. Unreadable data is not
	sufficient evidence for a participant record or a departure.
- **Consequences:** One problematic participant cannot erase later peers or
	cause false departures. Its own details remain absent until a later refresh
	succeeds, with a log record identifying the skipped discovery sample.
- **Follow-up:** Add a fixture where a middle participant raises while a later
	participant remains discoverable; assert no departure sweep occurs and no
	guessed partial record is emitted.
- **References:** `CODE_REVIEW_2026-08-07.md` H10;
	`rti_doctor/discovery.py`; `test/test_checks.py`.

### S1: Scale Tests Skip When the Scale Regression Occurs

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** The scale suite skips every test when discovery returns fewer
	than its required endpoints, including the test intended to verify that the
	test domain actually reached scale. A discovery regression can pass as a
	skipped suite.
- **Decision:** Assert required participant, topic, and endpoint counts as a
	hard `setUpClass()` precondition before scale tests run. Register fixture
	cleanup before that assertion.
- **Rationale:** Scale is a test prerequisite, not an optional condition. A
	partial domain must fail visibly rather than produce a false-green run.
- **Consequences:** A contended or broken live test environment fails with its
	observed versus expected topology counts. Fixture resources still stop even
	when readiness fails.
- **Follow-up:** Replace the per-test skip guard, use class-cleanup registration
	safe on `setUpClass()` failure, and add a regression test/harness for partial
	discovery reporting.
- **References:** `CODE_REVIEW_2026-08-07.md` S1;
	`test/test_scale.py`; `test/run_tests.sh`.

### S2: Discovery Field Mapping Can Silently Default

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Discovery mapper field names lack direct coverage. Tolerant
	`compat.get()` access turns a typo or renamed binding field into a silent
	default, which can hide vendor or QoS evidence.
- **Decision:** Add table-driven unit tests for `_endpoint_from_data()` and
	`refresh_participants()` using realistic fake builtin discovery objects.
	Assert every mapped field reaches its record with a non-default value.
- **Rationale:** The production mapper must tolerate fields that are genuinely
	unavailable, while tests must make the expected binding field names and
	mapping contract explicit and deterministic.
- **Consequences:** Unit tests fail on mapper typos or accidental field-name
	changes without making runtime discovery reads strict or brittle.
- **Follow-up:** Cover endpoint identity, vendor/protocol, all QoS policies,
	locators, and participant metadata; add a small live smoke assertion for
	representative binding fields where practical.
- **References:** `CODE_REVIEW_2026-08-07.md` S2;
	`rti_doctor/discovery.py`; `rti_doctor/compat.py`; `test/test_checks.py`.

### S3: Direct Test Execution Stops Before Later Test Classes

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `test_checks.py` invokes `unittest.main()` mid-file. Direct
	execution skips every test class defined afterward, including RxO and
	discovery-lifecycle coverage.
- **Decision:** Move the existing direct-execution `unittest.main()` block to
	the end of the module.
- **Rationale:** This conventional minimal change makes direct execution collect
	the full module while preserving the existing `python -m unittest` workflow.
- **Consequences:** Focused developer runs and CI module discovery execute the
	same test set.
- **Follow-up:** Add or update a collection-count assertion only if the suite
	gains a stable test-runner harness; verify direct module execution collects
	the later RxO and lifecycle classes.
- **References:** `CODE_REVIEW_2026-08-07.md` S3; `test/test_checks.py`.

### S4: Deprecated Full Sweep Has Untested Result Semantics

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `--all` test doubles hardcode successful sweep rows, leaving its
	error exit-code and finding-serialization behavior untested. The mode is
	already rejected as an unscalable workflow by C2.
- **Decision:** Remove `--all`, `run_headless_all()`, and sweep-specific tests
	as part of the accepted C2 deprecation/removal work.
- **Rationale:** Retiring the full per-writer diagnostic sweep implements the
	selected system-assessment-then-targeted-diagnosis workflow and avoids
	investing in a discarded execution contract.
- **Consequences:** CLI documentation and tests no longer expose `--all`.
	System-wide assessment uses the passive domain scan; detailed diagnosis is
	explicit and targeted.
- **Follow-up:** Remove parser/help handling, sweep code, related report output,
	and sweep-only test fixtures; verify the replacement domain and target flows.
- **References:** `CODE_REVIEW_2026-08-07.md` S4; C2 decision;
	`rti_doctor/__main__.py`; `rti_doctor/engine.py`; `test/test_cli.py`.

### Q7: Focused Readers Omit No-Writer Context

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** A focused reader with no discovered writers produces no match
	finding, while a focused writer with no readers produces `qos.no_counterpart`.
- **Decision:** Emit the same informational no-counterpart finding for readers,
	with role-correct wording that no DataWriter was discovered on the topic.
- **Rationale:** This is high-confidence discovery evidence that RxO comparison
	could not occur. It provides symmetric diagnosis context without asserting
	that a temporarily idle reader is faulty.
- **Consequences:** Targeted reader and writer reports consistently state when
	no requested/offered comparison was possible.
- **Follow-up:** Refactor the no-counterpart branch for role-specific labels,
	explanations, and tests for both endpoint roles.
- **References:** `CODE_REVIEW_2026-08-07.md` Q7;
	`rti_doctor/checks/qos_match.py`; `test/test_checks.py`.

### M6: TUI Discovery Polling Blocks the Event Loop

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** The TUI timer performs discovery polling and type-expiry work on
	Textual's event-loop thread. Moving only that work to a worker would increase
	the existing shared-registry and type-state concurrency exposure.
- **Decision:** Introduce a serialized discovery/scan coordinator: discovery
	updates are synchronized, scans operate on an immutable registry snapshot,
	and the UI renders completed results.
- **Rationale:** Immutable scan input prevents scans from observing a changing
	registry, while worker-based discovery keeps the UI responsive. This provides
	one correctness boundary for the related M4/M7 concurrency concerns.
- **Consequences:** Discovery and scan ownership becomes explicit. Snapshot
	construction and synchronization need focused lifecycle and concurrency
	tests.
- **Follow-up:** Define snapshot contents and coordinator ownership; move timer
	polling off the event loop; route all registry mutations through the
	coordinator; test refresh/scan interleavings and UI responsiveness.
- **References:** `CODE_REVIEW_2026-08-07.md` M6; related M4/M7;
	`rti_doctor/app.py`; `rti_doctor/engine.py`; `rti_doctor/records.py`.

### M8: Topology Rows and Health Use Different Observation Times

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Topology rows read the mutable live registry while Health reads
	the prior system-scan snapshot, allowing one row to combine current counts
	with stale health.
- **Decision:** Render all topology rows, counts, and health values from the
	same immutable system-scan snapshot.
- **Rationale:** A topology view must represent one observation time. This is
	the UI view-model consequence of the accepted M6 coordinator and snapshot
	design.
- **Consequences:** New discoveries appear on the next completed refresh rather
	than partway through an existing table render. Health always corresponds to
	the entities and counts shown alongside it.
- **Follow-up:** Include the required participant, endpoint, and topic display
	data in the scan snapshot; update topology renderers and test a discovery
	change between scan snapshots.
- **References:** `CODE_REVIEW_2026-08-07.md` M8; M6 decision;
	`rti_doctor/views/system_overview.py`; `rti_doctor/system_scan.py`.

### M9: Scoped Issue Lists Freeze Their Initial Issue Keys

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** Topology's `i` action passes a captured issue-key set to the
	issue list. After refresh, newly discovered issues for the selected entity or
	topic cannot appear, and the list is misleadingly labeled as all issues.
- **Decision:** Pass a semantic scope descriptor (participant, endpoint, or
	topic) rather than captured issue keys. Reapply that predicate to every fresh
	snapshot and label the scoped list accurately.
- **Rationale:** Refresh must preserve the operator's selected entity/topic
	context while recomputing the matching issue set. The `i` screen remains a
	fast passive-triage shortcut; Enter opens the full targeted report and `c`
	explicitly collects RTPS evidence.
- **Consequences:** New linked issues appear after `r`; resolved issues vanish.
	The title/status makes the selected participant, endpoint, or topic scope
	clear instead of claiming an unfiltered all-issues view.
- **Follow-up:** Replace `issue_keys` with a scope predicate, update topology
	navigation, add refresh tests for newly added/removed scoped issues, and
	ensure topic-/participant-scoped linkage from H4 is included.
- **References:** `CODE_REVIEW_2026-08-07.md` M9; M6/M8/H4 decisions;
	`rti_doctor/views/system_overview.py`; `test/test_views.py`.

### M10: Partial Payload Verdicts Hide Active Problem Severity

- **Date:** 2026-08-10
- **Status:** Superseded by S8
- **Problem:** `PARTIAL` and failed payload verdict lines omit unrelated active
	ERROR and WARN findings, so the compact report summary can understate the
	diagnosis.
- **Decision:** Append the active-problem summary to every payload verdict,
	including PARTIAL, failed, and walk-cap/truncation outcomes.
- **Rationale:** Payload readability and overall diagnostic severity are
	independent dimensions. The existing concise verdict can show both without
	changing its report structure.
- **Consequences:** Every relevant verdict consistently appends text such as
	`; 2 ERROR, 1 WARN` while retaining the payload state and detail.
- **Follow-up:** Centralize suffix construction, add tests for every payload
	branch with active findings, and confirm the targeted report summary reflects
	the same severity as its findings list.
- **References:** `CODE_REVIEW_2026-08-07.md` M10;
	`rti_doctor/findings.py`; `test/test_findings.py`.

### M13: Startup Failure Shares the Finding-Error Exit Code

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** A DDS startup failure currently exits with `1`, the same code as
	a completed assessment that found ERROR findings. Automation cannot tell
	whether a diagnosis ran.
- **Decision:** Reserve exit code `4` for operational or startup failure. Catch
	and report expected startup exceptions without a traceback by default.
- **Rationale:** A completed diagnostic result must be distinguishable from an
	inability to start. Preserve `1` exclusively for completed assessments with
	ERROR findings.
- **Consequences:** Exit semantics are: `0` no ERROR findings, `1` completed
	assessment with ERROR findings, `2` selected target absent, `3` readiness
	timeout, `4` unable to start, and `130` interrupted.
- **Follow-up:** Document the exit contract; catch participant/session startup
	failures; add CLI tests for the `4` path and retain coverage for each existing
	nonzero outcome.
- **References:** `CODE_REVIEW_2026-08-07.md` M13;
	`rti_doctor/__main__.py`; `tools/rti_doctor/README.md`; `test/test_cli.py`.

### M14: Readiness Timeout Accepts Unbounded Values

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `--ready-timeout` accepts non-finite values, allowing an
	unbounded wait or an immediate misleading timeout.
- **Decision:** Keep the existing 15-second default and enforce a maximum
	`--ready-timeout` of 60 seconds. Reject non-finite, non-positive, and
	over-limit values.
- **Rationale:** Readiness is a bounded fixture/startup coordination hook, not
	a long-running wait mode. A clear default and cap prevent accidental hangs.
- **Consequences:** Callers needing longer startup coordination must fix their
	fixture readiness behavior rather than hiding it behind an indefinite wait.
- **Follow-up:** Centralize timeout-range validation, update CLI help, and add
	tests for `nan`, `inf`, zero, negative, 60-second, and over-limit values.
- **References:** `CODE_REVIEW_2026-08-07.md` M14;
	`rti_doctor/__main__.py`; `test/test_cli.py`.

### M15: Test Runner Truncates Failure Evidence

- **Date:** 2026-08-10
- **Status:** Accepted
- **Problem:** `run_tests.sh` limits verbose unittest output to 40 lines. A
	multi-failure run preserves its exit status but loses earlier tracebacks.
- **Decision:** Capture full test output under `tools/rti_doctor/test_output/`.
	Clear the runner's prior test-output artifacts at the start of each run; show
	a concise final summary on success and complete captured output on failure.
- **Rationale:** Passing runs stay readable while every failure retains the
	diagnostic evidence needed to repair it. Each invocation starts from a known
	clean test-output state.
- **Consequences:** The runner owns and clears its test-output artifacts. Failed
	runs leave their complete current-run log available within the workspace.
- **Follow-up:** Replace the direct `tail` pipeline without losing the unittest
	exit status; define the runner-owned output paths; test success/failure output
	behavior and cleanup.
- **References:** `CODE_REVIEW_2026-08-07.md` M15;
	`tools/rti_doctor/run_tests.sh`.

### S5: SPDP2 Bitmask Test Coverage

- **Date:** 2026-08-10
- **Status:** Deferred
- **Problem:** Existing SPDP2 tests exercise only the compatibility substring
	fallback, not the primary numeric bitmask path.
- **Decision:** Do not add or expand SPDP2 support in the current work. Defer
	bitmask-path hardening and dedicated coverage to the future roadmap.
- **Rationale:** Customer use of SPDP2 is currently minimal, so it is a lower
	priority than the selected core DDS assessment and targeted-diagnosis work.
- **Consequences:** SPDP2 behavior remains outside the current support and
	regression-coverage commitment.
- **Follow-up:** When SPDP2 support is prioritized, add direct numeric mask
	tests for set/unset bits and preserve a fallback-string compatibility test.
- **References:** `CODE_REVIEW_2026-08-07.md` S5;
	`rti_doctor/checks/blind_spots.py`; `test/test_checks.py`.

### S6: Untested Advisory Checks

- **Date:** 2026-08-10
- **Status:** Deferred
- **Problem:** Several advisory checks have no direct tests, so WARN/INFO
	findings can regress or create false noise without detection.
- **Decision:** Disable all currently untested advisory checks from active
	reporting. Place them on the future roadmap and re-enable them only after
	direct deterministic test coverage is added.
- **Rationale:** RTI Doctor should provide high-confidence information. An
	untested advisory does not meet the current support bar.
- **Consequences:** Current reports omit `blind.security_enabled`,
	`transport.class_mismatch`, `security.mismatch`, and
	`discovery.partial` until each is covered and explicitly re-enabled.
- **Follow-up:** Remove these checks from active check sets; maintain a roadmap
	inventory; when reprioritized, add direct positive/negative tests and a
	healthy-path no-findings assertion before re-enabling.
- **References:** `CODE_REVIEW_2026-08-07.md` S6;
	`rti_doctor/checks/blind_spots.py`; `rti_doctor/checks/static_discovery.py`;
	`test/test_checks.py`.

### S7: System-Scan Cache Freshness Coverage

- **Date:** 2026-08-10
- **Status:** Deferred
- **Problem:** The system-scan cache must reuse a recent snapshot for passive
	screen navigation but bypass the cache for an explicit operator refresh. The
	current tests bypass this contract, and the view stub ignores `max_age`.
- **Decision:** Defer the test hardening to the future roadmap. Add focused,
	deterministic engine tests using a controllable clock and scan-call count;
	rename the stale view-stub `scope` argument to `captured_at`, while keeping
	the stub intentionally non-caching.
- **Rationale:** The behavior is useful and production code already implements
	it, but the test gap does not justify expanding the current implementation
	scope. Source-level tests can cover the contract without timing-sensitive TUI
	tests.
- **Consequences:** The existing cache behavior remains in place until the
	future coverage work is performed. A regression could otherwise make an
	explicit refresh silently return stale system topology data.
- **Follow-up:** Add a backlog item with tests for cache reuse inside
	`max_age`, cache expiry, and forced re-scan with `max_age=0` or an explicit
	`captured_at`; update the view test stub signature.
- **References:** `CODE_REVIEW_2026-08-07.md` S7;
	`rti_doctor/engine.py`; `rti_doctor/views/system_overview.py`;
	`test/test_system_scan.py`; `test/test_views.py`.

### S8: Payload-Health Diagnosis Scope

- **Date:** 2026-08-10
- **Status:** Deferred
- **Problem:** Payload-health diagnosis depends on dynamic sample traversal,
	decode-status interpretation, and extensive fixture coverage. It is not a
	current operator priority compared with DDS discovery and reader/writer
	matching diagnosis.
- **Decision:** Remove payload-health checks and payload verdicts from the
	active RTI Doctor assessment scope. Defer `probe_payload.py`, `typewalk.py`,
	and their related report behavior to the future roadmap.
- **Rationale:** The current product should provide high-confidence discovery,
	topology, type-resolution, and QoS/matching evidence rather than a less
	validated payload-health claim.
- **Consequences:** Active targeted reports stop at matching diagnosis and do
	not report payload FULL, PARTIAL, decode health, fragmentation, cache-drop,
	or field-readability verdicts. M10 is superseded because payload verdicts are
	no longer an active report surface.
- **Follow-up:** Remove payload-health checks, renderers, and tests from the
	current implementation plan; retain one explicit backlog item defining the
	fixtures, deterministic coverage, and report contract required to restore
	payload diagnosis.
- **References:** `CODE_REVIEW_2026-08-07.md` S8 and M10;
	`rti_doctor/checks/probe_payload.py`; `rti_doctor/typewalk.py`;
	`rti_doctor/findings.py`; `test/test_findings.py`.