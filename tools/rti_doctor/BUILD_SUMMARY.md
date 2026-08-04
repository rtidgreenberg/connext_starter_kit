# rti_doctor — Build Summary

Delivery summary for the initial build of `rti_doctor`, the DDS interoperability
diagnostic. Written 2026-08-03.

- **Scale:** ~6,900 lines across 26 modules.
- **Tests:** 80 passing, with 1 intentional abstract-fixture skip.
- **Verified on:** Connext 7.7.0 and 7.3.1, end to end.
- **Cross-vendor wire evidence:** validated against Eclipse Cyclone DDS and
  Fast DDS 2.14.6 with vendor-generated payloads saved as PCAPNG.

Full usage documentation is in [README.md](README.md); design rationale and the
phase plan are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

---

## Direct RTPS wire evidence — implemented

Discovery reports what an endpoint advertises; it does not prove which payload
representation was selected. `rti_doctor` can now inspect an existing PCAPNG with
`--pcap`, or run a bounded UDP `tshark` capture for one diagnosis with
`--capture-interface`. It retains only RTPS user-data observations for the report
and records the Wireshark-decoded CDR encapsulation IDs, rather than inferring them
from discovery QoS.

The cross-vendor fixtures use matched publisher/reader pairs so their payloads are
real vendor-generated traffic. The validated Fast DDS 2.14.6 trace contains user
writer `0x00000103` with `rtps.param.serialize.encap_kind = 0x0001`. The Cyclone
fixture leaves `DataRepresentation` unspecified; its observed user writer
`0x00000202` also yields `0x0001` for this installed Cyclone version and fixture
type. This is an observed fixture result, not a general claim that Cyclone always
selects XCDR1: unspecified representation is resolved from type defaults and may
select XCDR2. Discovery and control writers ending in RTPS entity kinds `c2` or
`c3` are excluded from payload observations.

## XTypes compliance mask — implemented

Connext's default XTypes compliance mask (`0x18C` on 7.7.0) is deliberately **not**
fully OMG XTypes 1.3 compliant; it preserves some legacy Connext encoding
behavior. RTI's own cross-vendor guidance is the VENDOR mask (`0x1A9`).

`rti_doctor` now applies the VENDOR mask before creating any DDS entity — a
diagnostic must not fail to decode a peer because of its own encoding defaults —
and records what is actually in force in Appendix C of every report:

```text
  xtypes_compliance_mask     0x9a9 (VENDOR applied)
```

The application equivalent is `export NDDS_XTYPES_COMPLIANCE_MASK=0x000001a9`.

**Honest caveat, measured not assumed:** setting the vendor mask did **not** fix
the observed Cyclone no-data case. The mask governs serialization and
deserialization, not whether a peer decides to match, so it must not be presented
as a cure for "matched but no data".

The other tip from RTI's UMAA vendor-interoperability guide *did* matter:
Cyclone can advertise an **empty** representation sequence while resolving its
actual representation from type defaults. Mirroring an empty advertisement left
the probe on the Connext default. The probe now offers XCDR1+XCDR2 as a superset,
which is also RTI's documented recommendation for readers and can never itself
be the reason a match fails.

## Cross-vendor wire result

The automated wire suite validates a complete vendor-to-PCAP path for both
Cyclone DDS and Fast DDS: a vendor publisher matches its vendor reader, RTI Doctor
discovers the writer, `tshark` captures the UDP RTPS traffic, and the report stores
the encapsulation IDs decoded from the saved PCAPNG. This tests representation
identification as observed on the wire, independently of the discovery
`DataRepresentationQosPolicy`.

## Controlled Cyclone-to-Connext application test

The manual final/XCDR1 fixture has been independently reviewed against the
installed Connext Python API. Its DynamicData type explicitly declares matching
type names, `FINAL` extensibility, and sequential member IDs `0..3`; the Cyclone
writer explicitly offers XCDR1 and records its publication-match status. With
Connext's `0x1A9` XTypes mask, the result remains asymmetric: Connext reports one
match and receives no samples, while Cyclone writes 40 samples and reports zero
matches. Applying `BuiltinQosLib::Generic.OtherDDSVendorCompatibility` to the
Connext participant produces the same result. This rules out implicit member IDs,
the XCDR1 selector, and that built-in participant profile as the immediate
workaround; the next diagnostic target is Cyclone's rejection of Connext
discovery/type metadata.

## Scope decisions

| In scope | Why |
|---|---|
| RxO QoS comparison between discovered endpoints | The tool observes a running system, so both the writer's offered QoS and the reader's requested QoS come from discovery — nothing is user-supplied |
| Type assignability between discovered types | Both types are read off the wire |

| Out of scope | Why |
|---|---|
| Judging the user's own reader QoS | The tool does not know what QoS the real application requests; it could only guess |
| Comparing a discovered type against the user's IDL (`--local-types`) | Would require user-supplied types |
| A stable JSON schema | v1 ships the text report as the shareable artifact |
| Any change to `rti_spy` or `rti_view` | Self-contained by design |

Verified working on a real bad pair: RELIABILITY and OWNERSHIP incompatibility
detected between two live endpoints (a BEST_EFFORT writer and a
RELIABLE/EXCLUSIVE reader in separate participants).

## Connext version support

| Version | Status |
|---|---|
| 7.7.0 | **Verified** end to end; 58 unit + 17 live tests pass |
| 7.3.1 | **Verified** end to end; same tests pass under Python 3.9 |
| 6.1.2 | **Not verified — not installed on this machine.** Feature-detected only |

7.3 lacks `DiscoveryConfig.request_types_filter`, the setting that makes Connext
fetch a remote type it has no local matching reader for. The report prints
`n/a (not available on Connext 7.3.1)` in Appendix C, and `type.no_type_info`
correspondingly names our own missing filter as the first candidate cause rather
than blaming the peer.

A `6.1` bucket was added to [scripts/python_env.sh](../../scripts/python_env.sh),
which previously mapped 6.1.x to Python 3.10 and a 7.7 wheel — a combination for
which no matching wheel exists.

## Bugs found by testing

Ten real defects, each now covered by a regression test.

| Bug | Why it mattered |
|---|---|
| `is_aggregation_type` / `is_collection_type` are **methods**, not properties | `bool(bound_method)` is always True, so every member of every type was misclassified as a collection |
| `loan_value` holds a bind on the parent | Reading one aggregate member made every *sibling* read fail — phantom failures after the first nested member |
| `EventCount64` / `SequenceNumber` are not ints | Real counters rendered as "not available on this version" — the exact dishonesty the report rules forbid |
| Strings are DDS collection types | Strings were walked as containers of characters |
| `dropped_fragment_count > 0` treated as a fault | Healthy large data showed fragments=6/reassembled=6/dropped=6; dropped fragments are ordinary repair duplicates |
| "outside every local /24" heuristic | Warned on any peer in another subnet — normal in a routed network, and the real prefix length is unknown |
| SHMEM locators judged as IP addresses | Every healthy local peer got a false "unspecified address" warning |
| App-level `b` binding popped the base screen | Back at the top level revealed an empty placeholder |
| DataTable never focused | Enter and `d` never reached it, so every action silently no-oped |
| `_writer_is_reliable` referenced but undefined | Would have raised on the no-data path |

Two of these were my own checks producing false positives on healthy systems. The
"outside every local /24" check was deleted rather than softened: a peer on another
subnet is normal in a routed network, and assuming a `/24` prefix was a guess.

## Corrections to external guidance

Two details from Connext AI did not survive contact with the real API, and were
caught by introspecting it before writing code:

- **`SubscriptionBuiltinTopicData.type_consistency` does not exist** on 6.1, 7.3,
  or 7.7. A remote reader's type-consistency requirement is not observable from
  discovery data, so the planned `reader.type_consistency` check was dropped
  rather than written against a field that isn't there.
- **`DynamicTypePrintFormatProperty` has no `print_ordinals`** parameter; only
  `indent` and `min_serialized_size`.

## Known gaps

- **Fast DDS validation is transport-scoped.** The automated fixture forces the
  built-in UDPv4 transport and validates representation evidence, but it does not
  claim coverage for Fast DDS shared-memory or custom transport configurations.
- **Cyclone validation is representation-scoped.** The fixture deliberately
  selects XCDR1 to make the observed `0x0001` assertion deterministic; it does
  not replace a full cross-vendor payload-deserialization matrix.
- **The shared-IDL Cyclone binding is not regenerated from the current explicit-ID
  source.** Its local IDLC generator is unusable, so its appendable/XCDR2 fixture
  remains a separate, generated-artifact parity investigation.
- **OpenDDS and OpenSplice** are recognized by vendor id only, and are not in the
  test matrix. OpenDDS is visible at all only if configured for RTPS discovery
  rather than InfoRepo.
- **Vendor notes in `vendors.py`** are phrased as things to check and carry
  sources; only the Cyclone `FINAL`-extensibility note has been observed directly.
