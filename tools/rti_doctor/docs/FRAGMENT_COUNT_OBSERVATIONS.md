# Fragment counter observations

Evidence record for what `DataReaderProtocolStatus` fragment counters actually
report on Connext 7.7.0, established 2026-08-14 by dissecting a capture rather
than by reading the field names. Written because two of them do not mean what
they are called, and rti_doctor had been explaining one of them away with a
mechanism that turned out not to exist.

This is a measurement note about one build. It is not a claim that RTI's
documentation is wrong in general, and the disagreement it records is left open
rather than resolved.

## Environment

| Component | Version / setting |
|---|---|
| Connext DDS Professional | 7.7.0 (`NDDSHOME=~/rti_connext_dds-7.7.0`) |
| Python | 3.11.13, venv `connext_dds_env_7.7_py311` |
| Fixture | `large-data` scenario, [fixture_publisher.py](../test/fixture_publisher.py) |
| Type | `struct DoctorRich { @key long id; sequence<octet,200000> blob; }` |
| Sample size | 150 148 bytes serialized (runs A–C); 70 112 (run D) |
| Fragment size | 65 315 bytes, so 3 fragments per sample (runs A–C); 2 (run D) |
| Probe reader | created by rti_doctor, QoS mirrored from the writer |

Reproduce with:

```bash
./tools/rti_doctor/test/run_manual_scenario.sh --scenario large-data --domain 55
./tools/rti_doctor/run_rti_doctor.sh --domain 55 \
    --topic DoctorManual_large_data --network-capture -o /tmp/frag.txt
```

## What was measured

Four runs, two transports, two sample sizes. Every column moves together except
`received_sample_count`.

| Run | Transport | Sample size | Frags/sample | `received_sample_count` | `received_fragment_count` | `reassembled_sample_count` | `dropped_fragment_count` | `sent_nack_fragment_count` |
|---|---|---|---|---|---|---|---|---|
| A | UDPv4 + SHMEM | 150 148 | 3 | 3 | 9 | 9 | 9 | 0 |
| B | UDPv4 only | 150 148 | 3 | 2 | 6 | 6 | 6 | 0 |
| C | UDPv4 + SHMEM | 150 148 | 3 | 1 | 3 | 3 | 3 | 0 |
| D | UDPv4 + SHMEM | 70 112 | 2 | 1 | 2 | 2 | 2 | 0 |

In every run `duplicate_sample_count` was 0, the payload walked clean, and the
probe reported `payload FULL`. Run B forced UDP-only by omitting
`--network-capture`, which restores the shared-memory restriction — the ratio
is identical on both transports, so nothing here is a shared-memory artifact.

**Run D exists to break a confound, and it is the reason the conclusion below
can be stated at all.** Runs A–C all used the stock fixture, whose 150 148-byte
sample is exactly 3 fragments. At a fixed 3:1 ratio "counts fragments" and
"counts three times the samples" predict the same number in every row, so those
three runs cannot distinguish them. Run D shrinks the blob to 70 000 octets, two
fragments per sample: `reassembled_sample_count` reported **2**, where a
per-sample multiple would have reported 3. Reproduce it by copying
`fixture_publisher.py` and changing the one literal:

```python
sample["blob"] = [counter % 256] * 70000   # was 150000
```

## The capture, fragment by fragment

RTI Network Capture of the probe participant during run A, dissected with
tshark. Submessage census for the whole file:

| Submessage | Count |
|---|---|
| `INFO_TS` (0x09) | 13 |
| `INFO_DST` (0x0e) | 10 |
| `DATA_FRAG` (0x16) | 9 |
| `HEARTBEAT` (0x07) | 6 |
| `DATA` (0x15) | 4 |
| `ACKNACK` (0x06) | 2 |

Nine `DATA_FRAG`, against `received_fragment_count = 9`. Broken out:

```
frame  seq  frag#  numFrags  fragSize
  8    241    1       1       65315
  9    241    2       1       65315
 10    241    3       1       65315
 13      1    1       1       65315
 14      1    2       1       65315
 15      1    3       1       65315
 16    242    1       1       65315
 17    242    2       1       65315
 18    242    3       1       65315
```

Three sequence numbers, fragments 1–3 of each, **every fragment appearing
exactly once**. 3 samples × 3 fragments = 9, and 3 × 150 148 = 450 444 bytes,
which is exactly the `received_sample_bytes` reported.

```bash
tshark -n -r <capture>.pcap -Y 'rtps.sm.id==0x16' -T fields \
    -e frame.number -e rtps.sm.seqNumber -e rtps.data_frag.number \
    -e rtps.data_frag.num_fragments -e rtps.data_frag.size
```

Run D's capture was dissected the same way and confirms the 2:1 ratio: every
sequence number in it carried exactly fragments 1 and 2, same 65 315-byte
fragment size.

Two cautions about reading a capture against these counters, both visible in run
D and neither a contradiction:

- **The windows differ.** Run D's capture holds 16 `DATA_FRAG` while the probe
  reported `received_fragment_count = 2`. The participant capture spans the
  whole diagnosis; the counters cover only the probe reader's lifetime, which is
  a fraction of a second. Run A's 9-against-9 agreement is the two windows
  happening to coincide, not a rule. Compare ratios, not totals.
- **Run D's capture carried sequence numbers the probe never counted**, in two
  ranges. Not chased, and not needed for the ratio question this run existed to
  settle — recorded so the next person seeing it knows it was noticed rather
  than missed.

## Conclusions

**`received_fragment_count` counts fragments, and is accurate.** It matched the
wire exactly in every run.

**`reassembled_sample_count` counts fragments, not samples.** Run C rules out
"samples" on its own — one delivered sample, `reassembled_sample_count = 3` —
and run D rules out any per-sample multiple, reporting 2 for a two-fragment
sample where 3× would have given 3. It tracks `received_fragment_count` in all
four runs and never tracks `received_sample_count`. Comparing it against "valid
samples taken" compares two different units.

**`dropped_fragment_count` equalling `received_fragment_count` is what a working
path looks like here.** Every fragment arrived once, every sample was
reassembled and delivered intact, and no fragment was ever missing. Whatever the
counter is recording, on this build it is not loss.

## What this disproved

**Our own explanation.** The comment in `check_fragmentation` had claimed the
drops were "redundant copies from ordinary repair traffic". Nothing arrived
twice, and `sent_nack_fragment_count` was 0, so no repair was requested. The
explanation was not merely unsupported — it was wrong, and it was the text
reassuring the operator.

**The reading that the field counts samples.** Asked directly, RTI's Connext AI
assistant answered that `reassembled_sample_count` increments only once a
complete sample has been reassembled, so 9 would mean nine samples. Run A
already contradicted that (3 samples received) and runs C and D make it
unambiguous (1 sample, count of 3; then 1 sample, count of 2).

## Open disagreement

The same assistant stated that a clean fragmented path shows
`dropped_fragment_count = 0`, citing RTI's `fragmented_data_statistics` example.
This build does not behave that way: the counter reliably equals the fragment
count on a path where every fragment arrives once and every sample is delivered.

**That citation is second-hand and has not been checked.** Nobody here has
opened the referenced example or the C API page; the claim is repeated as it was
given. Since the same source got `reassembled_sample_count` wrong in the same
conversation, it should not be treated as settled fact — read the primary source
before concluding that RTI and this build genuinely disagree.

Unresolved, and deliberately so — the mechanism behind the increment is not
visible from outside the middleware, and guessing at it is what produced the
wrong comment in the first place. Worth raising with RTI support if it ever
matters more than it currently does.

## What the code does about it

[`check_fragmentation`](../rti_doctor/checks/probe_payload.py) reports what was
measured, in the units it was measured in, and leans on neither the
documentation nor a theory of the mechanism:

- `received_sample_count` is printed alongside the fragment counters. Its
  absence is what let the other two be misread; with it present the 1:3 ratio
  explains itself.
- The finding states that `dropped_fragment_count` equals
  `received_fragment_count` on a working path, and that
  `reassembled_sample_count` counts fragments despite its name.
- The severity rule is unchanged and deliberately narrow: reassembly is called
  broken only when nothing was delivered at all, which is the one reading these
  counters do support.

## Confidence, and what is not established

Stated precisely, because the first two explanations of these counters were both
confident and both wrong.

**Settled.** `reassembled_sample_count` is not a count of samples, and is not
any per-sample multiple: runs C and D between them exclude both. On this build,
on a path where every sample is delivered, all three fragment counters equal the
fragment count.

**Verified twice, not four times.** Only runs A and D had their captures
dissected. "Every fragment arrives exactly once" is measured on run A only; run
D's capture confirms the fragments-per-sample ratio but was not audited for
duplicates. Runs B and C rest on counters alone.

**One source, partly unverified.** Both statements of RTI's position here came
from one Connext AI conversation, and one of them - that
`reassembled_sample_count` counts complete samples - is demonstrably wrong. The
other, that a clean path shows `dropped_fragment_count = 0`, has not been
checked against the primary source.

**Not established.**

- What `dropped_fragment_count` increments on. A per-fragment buffer release
  after reassembly fits every observation, but nothing here measures the
  mechanism, and inventing one is what produced the wrong comment originally.
- Whether the equality holds at higher fragment counts. Only 2:1 and 3:1 were
  measured; the fixture's 200 000-octet bound caps how far this can be pushed
  without a new type.
- Whether it holds on a lossy path where repair actually runs. Every run was
  local and clean, and `sent_nack_fragment_count` was 0 throughout — so nothing
  here says what these counters do when fragments genuinely go missing, which is
  the case an operator most needs them for.
- Whether 6.1.2 or 7.3.x behave the same. Only 7.7.0 was measured.
