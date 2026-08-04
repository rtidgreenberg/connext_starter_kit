# Cyclone DDS to Connext DDS Investigation

Evidence record for the observed one-way interoperability failure. Updated
2026-08-03. This is a diagnostic note, not a claim of general incompatibility
between the two implementations.

## Environment

| Component | Version / setting |
|---|---|
| Cyclone DDS Python package | 11.0.1 |
| Cyclone shared library | 11.0.1 |
| Connext DDS Professional | 7.7.0 |
| Connext XTypes mask | `0x000001A9`, set and verified through the Python API before participant creation |
| Test transport | Local standard RTPS/UDP discovery and user data |

The source fixtures are [cyclone_publisher.py](test/vendors/cyclone_publisher.py)
and [connext_cyclone_reader.py](test/vendors/connext_cyclone_reader.py).

## Reproduction

The controlled manual fixture has identical field order and member IDs on both
sides:

```text
id: int32, label: string, nested: { n_id: int32, n_val: float64 },
scores: sequence<float64>
```

The Connext endpoint sets `FINAL` extensibility and XCDR1 only. The original
Cyclone class had no explicit `@final` annotation; it was an intended strict
control, but the trace below shows its emitted type metadata was not final in the
required sense. The Cyclone writer records `PublicationMatchedStatus`; the
Connext reader records
`SubscriptionMatchedStatus` and valid received samples.

| Control | Cyclone writer | Connext reader | Result |
|---|---:|---:|---|
| Keyed `id`, FINAL/XCDR1 | `max_matched=0` | `matched=1`, `samples=0` | No delivery |
| Keyed `id`, FINAL/XCDR1, Connext other-vendor profile | `max_matched=0` | `matched=1`, `samples=0` | No delivery |
| Unkeyed `id`, FINAL/XCDR1, original TypeName retained | `max_matched=0`, 119 writes | `matched=1`, `samples=0` | No delivery |
| Unkeyed `id`, explicit Cyclone `@final`, XCDR1, Connext 7.7 TypeObject v1 only | `max_matched=1`, 118 writes | `matched=1`, `samples=1` | Delivered |
| Unkeyed `id`, explicit Cyclone `@final`, XCDR1, Connext 7.3 default | `max_matched=1`, 119 writes | `matched=1`, `samples=1` | Delivered |
| Keyed `id`, explicit Cyclone `@final`, XCDR1, Connext 7.7 TypeObject v1 only | `max_matched=1`, 119 writes | `matched=1`, `samples=1` | Delivered |
| Keyed `id`, explicit Cyclone `@final`, XCDR1, Connext 7.3 default, trace-backed rerun | `max_matched=1`, 133 writes | `matched=1`, `samples=1` | Delivered |
| Generated shared IDL: keyed appendable/XCDR2, Connext 7.7 default | `max_matched=0`, 294 writes | `matched=1`, `samples=0` | No delivery |
| Generated shared IDL: keyed appendable/XCDR2, Connext 7.7 TypeObject v1 only | `max_matched=1`, 294 writes | `matched=1`, `samples=1` | Delivered |
| Generated shared IDL: keyed appendable/XCDR2, Connext 7.3 default | `max_matched=1`, 293 writes | `matched=1`, `samples=1` | Delivered |

The final unkeyed run used domain 199 and topic
`FinalXcdr1NoKeySameTypeName`. Its endpoint evidence is retained in
[Cyclone log](../../test_output/cyclone_unkeyed_final_xcdr1_same_name_publisher.log)
and [Connext log](../../test_output/connext_unkeyed_final_xcdr1_same_name_reader.log).

## Conclusions From Local Evidence

1. Connext locally accepts the discovered Cyclone writer, but Cyclone never
  reciprocally associates the Connext reader. A Connext local match count is
  therefore not end-to-end communication proof.
2. Explicit XCDR1, explicit member IDs, and the Connext vendor XTypes mask do
  not resolve this fixture.
3. Removing the key while retaining the same DDS TypeName and payload layout
   does not resolve it. This falsifies the focused key-member metadata
   hypothesis for this reproduction.
4. `BuiltinQosLib::Generic.OtherDDSVendorCompatibility` does not resolve it.
5. The trace confirms the rejection is in Cyclone's remote type assignability
  evaluation. It is not an absence of TypeLookup traffic.

## Trace-Confirmed Rejection

The finest trace for the unkeyed, XCDR1-only domain-200 control contains:

```text
assignability check failed: rd type [COMPLETE ...] wr type [MINIMAL ...],
t1=[COMPLETE ...] (STRUCTURE) t2=[MINIMAL ...] (STRUCTURE) id 0:
wr type not delimited
```

Cyclone resolved the Connext reader's Complete TypeIdentifier and found it equal
to the writer's Complete TypeIdentifier at the enclosing type. It then rejected
the nested member during assignability because the writer type was not delimited.
The full evidence is [Cyclone finest trace](../../test_output/cyclone_final_xcdr1_trace.log).

This invalidated the earlier assertion that the manual fixture already exercised
a strict, cross-vendor `FINAL` control. Cyclone's `@final` annotation was then
explicitly applied to both the enclosing and nested types. The rerun on domain
201 remained asymmetric: Cyclone reported `max_matched=0` after 119 writes and
Connext reported `matched=1`, `samples=0`. Therefore, explicit Cyclone final
annotations alone do not resolve the failure. The trace identifies a concrete
metadata mismatch; it does not establish a Cyclone 11.0.1 regression.

Connext AI identified a participant-level TypeObject v1 compatibility control
for Connext 7.7: set `type_code_max_serialized_length=0`, set a positive
`type_object_max_serialized_length`, and clear only
`DiscoveryConfigBuiltinChannelKindMask.TYPE_LOOKUP_SERVICE` from the effective
default builtin-channel mask. This is independent of application
`DataRepresentation` and the process-global XTypes compliance mask. The manual
Connext fixture exposes it as `--type-object-v1-only` for the next 7.7/7.3
comparison. Local API inspection shows that 7.3 has no TypeLookup-service mask
bit and defaults to `SERVICE_REQUEST`; it was tested as a separate baseline.

The 7.7 TypeObject-v1-only control succeeded on domain 204: Cyclone reported
`max_matched=1` and Connext received one valid sample. This establishes that
Connext 7.7's default TypeObject v2/TypeInformation propagation was the
controlling incompatibility for this fixture. It does not require changing the
application XCDR1 `DataRepresentation` or the `0x000001A9` payload-compliance
mask.

The generated shared-IDL control reaches the same conclusion for a keyed,
`@appendable` type using XCDR2 user data. With default Connext 7.7 propagation,
Cyclone never reciprocally matched; with TypeObject-v1-only propagation, it
matched and Connext received a valid sample. Thus the TypeObject setting, not
the final/XCDR1-only manual fixture, controls this cross-vendor behavior.

The same generated appendable/XCDR2 type delivered with the default Connext
7.3.1 participant. The shared 7.3 reader initially failed before participant
creation because it imported generated code before applying the required `0x1A9`
XTypes compliance mask. Generated type decorators validate that mask at import
time in 7.3, so the reader now sets it immediately after importing
`rti.connextdds`, before importing the generated module.

The same fixture also delivered with an unmodified Connext 7.3.1 participant on
domain 205. This is consistent with local API inspection: 7.3 defaults to the
legacy `SERVICE_REQUEST` builtin-channel mask and a positive TypeObject-v1 size,
while 7.7 defaults to the TypeLookup-service mask and TypeObject-v2 propagation.

The keyed schema also delivers with 7.7 TypeObject-v1-only propagation and the
default 7.3 participant. An earlier concurrent 7.3 keyed run reported zero
matches, but the dedicated trace-backed rerun on domain 208 matched and delivered
without an assignability rejection; the earlier result is therefore inconclusive.
The historical Cyclone key-member TypeObject mismatch remains relevant upstream
context, but is not reproduced by this fixture with the compatible Connext
TypeObject-v1 propagation.

## Relevant Upstream History

- Cyclone DDS 11.0.0 release notes report expanded XCDR1 support and many XTypes
  interoperability fixes. Cyclone DDS 11.0.1 includes TypeLookup request/reply
  header interoperability fixes. Neither note describes an intentional removal
  of Connext compatibility.
- [Issue #1576](https://github.com/eclipse-cyclonedds/cyclonedds/issues/1576)
  records the same directional pattern: RTI publisher to Cyclone subscriber
  worked while Cyclone publisher to RTI subscriber did not. It is historical
  evidence, not proof that this Linux reproduction has the same root cause.
- [Issue #1572](https://github.com/eclipse-cyclonedds/cyclonedds/issues/1572)
  clarifies that application `DataRepresentation` does not control the
  TypeInformation/TypeObject metadata encoding. That metadata uses internal
  little-endian XCDR2 serialization, so forcing application XCDR1 cannot avoid
  a TypeInformation incompatibility.
- [Issue #1544](https://github.com/eclipse-cyclonedds/cyclonedds/issues/1544)
  and [PR #1108](https://github.com/eclipse-cyclonedds/cyclonedds/pull/1108)
  document a real historical cross-vendor key-member TypeObject flag mismatch:
  Cyclone emits `IS_MUST_UNDERSTAND` for keys. That motivated the unkeyed
  control above, which did not change this failure.

## Validated Operational Configuration

For a Connext 7.7 participant that must interoperate with this Cyclone 11.0.1
fixture, use a participant QoS derived from the default and configure:

```python
participant_qos.resource_limits.type_code_max_serialized_length = 0
participant_qos.resource_limits.type_object_max_serialized_length = 65536
channels = participant_qos.discovery_config.enabled_builtin_channels
participant_qos.discovery_config.enabled_builtin_channels = (
  dds.DiscoveryConfigBuiltinChannelKindMask(
    int(channels) & ~int(
      dds.DiscoveryConfigBuiltinChannelKindMask.TYPE_LOOKUP_SERVICE)))
```

Create the participant with that immutable QoS. This produces the validated
TypeObject-v1-only behavior. Keep `DataRepresentation` and the XTypes compliance
mask as separate decisions: they control application-payload representation and
serialization compliance, respectively, not the discovery TypeObject version.

Connext 7.3.1 already uses the corresponding compatibility-oriented default
(`SERVICE_REQUEST` and a positive TypeObject-v1 size), and delivered without
this override in both keyed and unkeyed controls.

## Observer Boundaries and Doctor Guidance

RTPS vendor ID `01.10` identifies the Cyclone DDS implementation family, but
does not contain an authoritative Cyclone product version. `rti_doctor` must
therefore present this investigation as a vendor-family recommendation, not a
claim that an observed peer is Cyclone 11.0.1.

An observer can read endpoint `DataRepresentation` QoS and, with a user-data
capture, the actual selected XCDR/XCDR2 encapsulation. It can observe whether
TypeInformation, legacy TypeObject propagation, or TypeLookup traffic is present.
It cannot recover the peer's exact XTypes compliance mask or participant
resource-limit/builtin-channel settings: those are local configuration. Absence
of propagated type information is evidence of the wire outcome, not proof that
`type_object_max_serialized_length` was set to zero.

The Cyclone vendor note in `rti_doctor` now recommends the Connext 7.7
TypeObject-v1-only control only when the observed situation matches this
investigation: a Cyclone writer is discovered, Connext locally sees a match, and
reciprocal user data does not arrive. The recommendation requires end-to-end
validation from reciprocal user-data traffic; it never asserts a remote mask,
exact Cyclone version, or participant QoS value.