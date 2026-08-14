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
| Sample size | 150 148 bytes serialized |
| Fragment size | 65 315 bytes, so 3 fragments per sample |
| Probe reader | created by rti_doctor, QoS mirrored from the writer |

Reproduce with:

```bash
./tools/rti_doctor/test/run_manual_scenario.sh --scenario large-data --domain 55
./tools/rti_doctor/run_rti_doctor.sh --domain 55 \
    --topic DoctorManual_large_data --network-capture -o /tmp/frag.txt
```

## What was measured

Three runs, two transports, three different sample counts. Every column moves
together except `received_sample_count`.

| Run | Transport | `received_sample_count` | `received_fragment_count` | `reassembled_sample_count` | `dropped_fragment_count` | `sent_nack_fragment_count` |
|---|---|---|---|---|---|---|
| A | UDPv4 + SHMEM | 3 | 9 | 9 | 9 | 0 |
| B | UDPv4 only | 2 | 6 | 6 | 6 | 0 |
| C | UDPv4 + SHMEM | 1 | 3 | 3 | 3 | 0 |

In every run `duplicate_sample_count` was 0, the payload walked clean, and the
probe reported `payload FULL`. Run B forced UDP-only by omitting
`--network-capture`, which restores the shared-memory restriction — the ratio
is identical on both transports, so nothing here is a shared-memory artifact.

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

## Conclusions

**`received_fragment_count` counts fragments, and is accurate.** It matched the
wire exactly in every run.

**`reassembled_sample_count` counts fragments, not samples.** Run C settles it
with no room for interpretation: one delivered sample, `reassembled_sample_count
= 3`. It tracks `received_fragment_count` in all three runs and never tracks
`received_sample_count`. Comparing it against "valid samples taken" compares two
different units.

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

**The reading that the field counts samples.** RTI's own answer to this question
was that `reassembled_sample_count` increments only when a complete sample has
been reassembled, so 9 would mean nine samples. Run A already contradicted that
(3 samples received) and run C makes it unambiguous (1 sample, count of 3).

## Open disagreement

RTI's guidance is that a clean fragmented path shows `dropped_fragment_count =
0`, citing the `fragmented_data_statistics` example. This build does not behave
that way: the counter reliably equals the fragment count on a path where every
fragment arrives once and every sample is delivered.

Both cannot describe the same thing. Unresolved, and deliberately so — the
mechanism behind the increment is not visible from outside the middleware, and
guessing at it is what produced the wrong comment in the first place. Worth
raising with RTI support if it ever matters more than it currently does.

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

## Open questions

- What does `dropped_fragment_count` increment on? A per-fragment buffer release
  after reassembly would fit every observation, but that is inference.
- Does the ratio hold for samples needing many more fragments, or for a lossy
  path where repair actually runs? Every run here was local and clean.
- Does 6.1.2 or 7.3.x behave the same? Only 7.7.0 was measured.
