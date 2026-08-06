# GPT Terra Static Code Review - 2026-08-06

Review date: 2026-08-06
Reviewer: GPT Terra
Method: static source analysis only. No tests, builds, linters, DDS sessions,
or packet captures were run. This review was intentionally limited to
read-only inspection while a separate agent continues the active fixes.

Reference: `CODE_REVIEW_2026-08-06.md` describes the current review/fix work.
This document is independent and records only a finding confirmed against the
source read during this pass. The working tree was active, so later edits may
change the cited behavior.

Re-verified: 2026-08-06 against the current active worktree. G1 remains
accurate; no tests, builds, linters, DDS sessions, or packet captures were run.

## Summary

| # | Severity | Finding | Area |
|---|---|---|---|
| G1 | Resolved | A coalesced RTPS frame was reported as selected-writer evidence although its aggregate fields could also describe another writer. | Packet capture |

## G1 - Frame-level capture filtering overclaims writer-specific evidence

Confirmed by static analysis and re-verified against the current active source.

**Resolved (conservative reporting).** The implementation still retains
frame-level tshark aggregation, because its fields do not preserve a reliable
byte-to-submessage association. The report now labels all counts, IDs, and byte
totals as belonging to frames matching the filters, rather than to the selected
writer. The target writer remains a filter, not an attribution claim.

Completed 2026-08-06 (second pass). The first pass relabelled the text appendix
only, so `--format json` still emitted bare `data_packets` / `writer_entity_ids`
/ `payload_bytes` keys that a machine consumer reads as writer-attributed.
`summarize()` now returns `scope`, `writer_attributed: false` and `scope_note`
alongside the counts - the same shape `summarize_discovery` already used for
`complete` / `completion_note` - and both renderers carry them. Two things were
found while closing it:

* The test gap below is closed by
  `test_a_coalesced_frame_is_not_presented_as_writer_attributed`, which builds
  one frame carrying the target writer *and* a second user writer and asserts
  the summary does not claim writer attribution. It also asserts the second
  writer's id and encapsulation *are* in the totals, so the aggregation the tool
  actually performs is recorded rather than implied.
* The first pass's labels (up to 36 characters) exceeded `_kv`'s default pad of
  16, so every value in Appendix C rendered flush against its own label
  (`Frames matching filters1`). The existing test asserted only that the label
  substrings were present, which cannot see a collision. Fixed with an explicit
  `WIRE_LABEL_PAD`, guarded by an assertion on the label *and* its value.

All three new tests were confirmed to fail against the pre-fix source.

`inspect_pcap()` requests every occurrence of each tshark field with
`occurrence=a`, then joins the occurrences into one `WireObservation` for the
entire UDP frame. `summarize()` accepts that observation when *any* aggregated
`writer_entity_id` equals the target. It subsequently aggregates all
encapsulation IDs and writer IDs, sums the frame-wide payload/reassembled byte
fields, and regards a frame containing a DATA or DATA_FRAG submessage as one
such submessage.

The implementation documents this as frame-level filtering, but the rendered
appendix still labels the result as a writer-filtered observation and prints
`DATA submessages`, `DATA_FRAG submessages`, `Serialized bytes`, and `Writer
entity IDs`. A single RTPS message can contain multiple DATA submessages from
one participant, including distinct writers. If it contains both the target and
another writer, the target match admits the complete frame. The appendix can
therefore show the other writer's entity ID and count its payload bytes or
representation as evidence for the selected writer.

Impact: a diagnostic report may claim that a selected endpoint used a wire
representation or transmitted bytes that belonged to another endpoint. The
packet capture is informational rather than the primary verdict source, so this
is Medium severity; it is nevertheless misleading exactly where the report is
meant to provide direct wire evidence.

Suggested resolution: preserve field-to-submessage association before applying
the writer filter. A robust approach is to emit one tshark record per RTPS
submessage (or use a packet decoder that retains submessage boundaries), filter
those records by writer identity, then calculate counts and byte totals from
the filtered records. If the current frame-level design is retained, report it
only as frame-level evidence and do not label the bytes, writer IDs, or
submessage counts as belonging to the selected writer.

Test gap: the existing aggregation test covers an `INFO_TS` plus one target
DATA/DATA_FRAG per frame. It does not cover a coalesced frame containing the
target writer and a different user writer, so it cannot detect this
misattribution.