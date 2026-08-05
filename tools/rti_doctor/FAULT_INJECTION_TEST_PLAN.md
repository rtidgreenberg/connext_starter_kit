# RTI Doctor Fault-Injection Test Plan

## Purpose

Prove that `rti_doctor` reports supported, deliberately introduced DDS
interoperability faults for Connext, Cyclone DDS, and Fast DDS. Equally, prove
that the same test harness produces no Doctor `ERROR` findings when the
endpoints communicate normally.

This plan tests Doctor's diagnostic result, not merely the underlying DDS
implementations. Every scenario therefore has two independent assertions:

1. The endpoint pair exhibits the intended match/data-flow behavior.
2. A headless `rti_doctor --format json` run reports the expected finding (or
   reports no `ERROR` finding for a healthy control).

## Existing Coverage And Gaps

The current suite already has useful foundations:

| Existing test | What it proves | Gap remaining |
|---|---|---|
| `test_live_integration.py` | Connext fixtures produce a healthy report, `type.no_type_info`, fragmentation information, partition mirroring, and an RxO mismatch. | No external vendor is diagnosed by Doctor for a known fault. |
| `test_rxo_vendor_e2e.py` | Connext/Connext and Connext/Cyclone requested/offered pairs match or fail to transfer data as expected. | Does not run Doctor or check a Doctor finding. |
| `test_extensibility_vendor_e2e.py` and `test_fastdds_extensibility_vendor_e2e.py` | FINAL/APPENDABLE combinations transfer samples in Connext/Cyclone and Connext/Fast DDS directions. | Only healthy cases exist; Doctor's type diagnosis is not asserted. |
| `test_vendor_wire_e2e.py` | Doctor captures and recognizes healthy Cyclone and Fast DDS wire data. | It does not assert the whole report is fault-free, and it has no negative control. |
| `test_checks.py` | Synthetic endpoint records map many conditions to finding IDs. | It cannot prove discovery, type lookup, probing, report serialization, or vendor behavior together. |

The proposed work closes the end-to-end gaps without duplicating the current
low-level data-flow matrices.

## P0 Spike Results

The initial implementation added
`test/test_fault_vendor_e2e.py` and established these results:

| Pair | Healthy control | Reliability fault | Status |
|---|---|---|---|
| Connext writer -> Cyclone reader | Match, reader samples, no active Doctor `ERROR` finding. | No match/samples; Doctor emits active `qos.rxo_mismatch` naming RELIABILITY. | Passing. |
| Cyclone writer -> Connext reader | Match, reader samples, no active Doctor `ERROR` finding. | No match/samples; Doctor emits active `qos.rxo_mismatch` naming RELIABILITY. | Passing. |
| Connext writer -> Fast DDS reader | Match and reader samples. | No match/samples; Doctor emits active `qos.rxo_mismatch` naming RELIABILITY. | Passing with deterministic readiness. |
| Fast DDS writer -> Connext reader | Match and reader samples; Fast DDS metadata resolves a Connext `DynamicType`. The custom FINAL TypeObject variant intentionally reports `type.assignability`. | No match/samples; Doctor emits active `qos.rxo_mismatch` naming RELIABILITY. | Passing with the custom TypeObject outcome isolated. |

The Fast DDS P0 class uses a test-only discovery-aware file handshake. Both
fixtures create participants behind endpoint gates. Doctor waits to observe both
remote participants before writing its marker, after which the test releases
and confirms the reader endpoint followed by the writer endpoint. This prevents
fixed ordering sleeps and controls the one-shot SEDP announcement sequence.
All four Fast DDS P0 controls pass, and ten independent Connext BEST_EFFORT
writer to Fast DDS RELIABLE reader runs discovered the reader and emitted active
`qos.rxo_mismatch` with RELIABILITY evidence.

### Fast DDS Type Metadata Spikes

`test/test_fastdds_type_metadata_spike.py` uses Doctor's native Connext logger
to separate Fast DDS metadata-advertisement paths. The fixture follows the
current supported Fast DDS release and has three current cases:

| Fast DDS fixture mode | Connext observation | Result |
|---|---|---|
| Default generated TypeObject/TypeInformation | Writer is discovered and Connext resolves a `DynamicType`. | Current healthy metadata control. |
| Generated metadata suppressed | Writer remains discoverable and native logs contain no TypeInformation deserialize failure, but no `DynamicType` is available. | Does not trigger the parser-error path; valid containment for static peers, not a Doctor type-resolution fix. |
| Default metadata with TypeLookup requested | Connext resolves a `DynamicType`. | Current healthy TypeLookup control. |

The parser diagnostic and an unavailable type must remain separate evidence.
`PID_TYPE_INFORMATION` uses XCDR2 independently of the topic's user-data
representation, so changing the fixture's XCDR1 payload setting is not a
valid remediation. The custom FINAL TypeObject regression now resolves a
Connext `DynamicType` in the default mode. Connext's
`--type-object-v1-only` experiment does not discover that writer and remains an
explicit expected failure; it is separate from current default-mode Fast DDS
support. If default-mode resolution regresses, preserve the endpoint
`PID_TYPE_INFORMATION` capture and matched runtime/generator evidence for a
vendor support case; do not retain an older-version comparison lane.

### Fast DDS RTPS Capture Evidence

TShark 4.4.9 captured the Connext BEST_EFFORT writer / Fast DDS RELIABLE reader
fault in
`test_output/fastdds_rtps/connext_writer_fastdds_reader_reliability_fault.pcapng`.
The capture is decisive on the discovery path:

- Fast DDS uses vendor ID `0x010f` and advertises builtin endpoint set
  `0x00000c3f`, including the standard Subscription Announcer and Detector
  bitmasks.
- Its reader's SEDP sample is sent from builtin subscriptions writer
  `0x000004c2` to subscriptions reader `0x000004c7`. The endpoint GUID ends in
  `0x00000104`, an application DataReader entity ID without a key.
- The sample contains `PID_TOPIC_NAME` `DoctorFastDdsRtpsCapture`,
  `PID_TYPE_NAME` `DoctorExtensibility::Sample`, `PID_RELIABILITY = RELIABLE`,
  XCDR1 data representation, and the normal volatile/shared/default QoS
  policies.
- The fixture itself records zero matches and zero reader samples, while its
  Connext BEST_EFFORT writer continues to publish.

In a Doctor-first experiment, Doctor returned an active `qos.rxo_mismatch` with
the expected `writer offers BEST_EFFORT` / `reader requests RELIABLE` evidence.
That run also logged non-fatal
`DISCBuiltin_deserializeTypeInformation: FAILED TO DESERIALIZE` for Fast DDS
TypeInformation. Treat TypeInformation deserialization as a separate
cross-vendor regression target; it does not prevent Doctor from comparing the
captured Fast DDS reader QoS in the forward fault experiment.

## Test Contract

### Common Harness

`tools/rti_doctor/test/doctor_e2e.py` provides shared headless Doctor command
construction and report extraction for end-to-end tests. It accepts native
middleware preambles, finds the report JSON by its `domain_id`, and includes the
command plus stdout/stderr when parsing fails. `test_fault_vendor_e2e.py` and
the vendor wire suite use it. Keep vendor-specific retry and readiness logic in
the owning test.

The fault suite has reusable helpers for every scenario:

- Start the reader before the writer, using a unique topic and a safe test
  domain. Retain current vendor setup: local Cyclone Python runtime and the
  current Fast DDS Docker image.
- Use bounded file readiness gates rather than fixed sleeps. For Fast DDS P0,
  Doctor must observe both fixture participants before either endpoint is
  created; timeouts retain process streams and control markers.
- Run the real CLI with `--domain`, `--topic`, `--format json`,
  `--no-domain-scan`, a bounded settle period, a bounded type wait, and a
  bounded probe timeout.
- Parse JSON once and expose active, suppressed, and `ERROR` finding IDs.
- Assert endpoint facts first: expected match count and reader sample count.
  A negative scenario must show writers publishing while the incompatible
  reader remains unmatched and receives zero samples, unless its intended
  condition is payload-only.
- Assert Doctor facts second: the required finding ID and severity, a report
  verdict consistent with the failure, and any relevant suppression relation.
- Save process stdout/stderr, command metadata, and copied readiness-control
  files in `test_output/rti_doctor_faults/<run-id>/` on failure, or when
  `RTI_DOCTOR_KEEP_ARTIFACTS=1`; include PCAPNG when the capture path produces
  one. A retained successful Fast DDS P0 run has verified this complete bundle.

Use deterministic safe domain selection, or calculate candidates with valid,
non-privileged default RTPS ports. Do not use a random domain range without
that validation.

### Healthy Controls

Each vendor direction must have a matching healthy control that uses the same
schema, transport, discovery, and CLI parameters as its fault case. A healthy
control passes only when all of these are true:

- Writer and reader match and exchange one or more samples.
- Doctor discovers the target writer and returns valid JSON.
- Doctor emits no active finding whose severity is `ERROR` or higher.
- Doctor does not emit the fault ID asserted by the paired negative case.
- When a probe is applicable, the verdict says that the endpoint matched and
  the payload is readable; a missing wire observation is non-conclusive, not
  a fault, when capture prerequisites are unavailable.

The existing `TestHealthy` remains the Connext/Connext control. Add explicit
Cyclone and Fast DDS controls so that regression coverage does not rely only on
the narrow wire appendix assertions.

## Scenario Matrix

Implement the scenarios in the listed order. The `Doctor expectation` is the
contract to assert against the JSON report. Confirm the exact finding ID from
the corresponding check before locking the assertion; use a stable semantic
assertion in addition to an ID if the JSON schema remains marked unstable.

| Priority | Pair and direction | Fixture change from healthy control | Endpoint expectation | Doctor expectation |
|---|---|---|---|---|
| P0 | Connext -> Cyclone, Cyclone -> Connext | Requested/offered reliability: BEST_EFFORT writer and RELIABLE reader. | No match; reader gets no samples; writer continues publishing. | Active `qos.rxo_mismatch`, identifying RELIABILITY and both offered/requested values. |
| P0 | Connext -> Fast DDS, Fast DDS -> Connext | Same reliability mismatch. | No match and no reader samples. | Active `qos.rxo_mismatch` identifying RELIABILITY. |
| P0 | Connext -> Cyclone, Cyclone -> Connext | Identical compatible QoS. | Match and data flow. | No active `ERROR`; no RxO mismatch. |
| P0 | Connext -> Fast DDS, Fast DDS -> Connext | Identical compatible QoS. | Match and data flow. | No active `ERROR`; no RxO mismatch. |
| P1 | Connext -> Cyclone, Cyclone -> Connext | One mismatch at a time for every existing RxO matrix case: durability, liveliness kind/lease, destination order, Presentation scope/coherent/ordered flags, deadline, latency budget, ownership, data representation, and partition. | Each incompatible pair remains unmatched with no reader samples. | `qos.rxo_mismatch` names the single policy under test. |
| P1 | Connext -> Fast DDS, Fast DDS -> Connext | Reliability, durability, deadline, ownership, data representation, and partition mismatches supported by the Fast DDS fixture. Add remaining policies only after verifying Fast DDS exposes the needed QoS controls. | No match and no reader samples. | `qos.rxo_mismatch` names the changed policy; unsupported fixture capability is an explicit documented skip, not a silent omission. |
| P1 | Connext publisher -> Doctor | Disable TypeObject propagation using the existing `no_type_info` fixture mode. | Endpoint is discoverable; type is unavailable. | Active `type.no_type_info`; `probe.not_created` is suppressed by it; verdict says not probed. |
| P1 | Connext -> Cyclone and Connext -> Fast DDS | Same type name but incompatible field layout. Reuse the existing Connext conflict fixture and add equivalent third-party endpoint support as needed. | Discovery may occur; payload cannot be safely interpreted or endpoints do not match, according to vendor behavior. | A type incompatibility or unavailable-type finding, never a `payload FULL` verdict. Record the observed vendor-specific match behavior as test evidence. |
| P2 | Connext -> Cyclone, Cyclone -> Connext | Large sample exceeding a normal UDP datagram. | Match and data flow; DATA_FRAG is observable when capture is enabled. | `data.fragmentation` is informational only; no active `ERROR`. |
| P2 | Connext -> Fast DDS, Fast DDS -> Connext | Large sample / fragmentation fixture, if supported by the Docker image. | Match and data flow. | Informational fragmentation only; no active `ERROR`. |
| P2 | Connext -> Cyclone, Cyclone -> Connext | Healthy writer terminates after Doctor discovers it. | Discovery disposal occurs. | The departed writer is absent from a fresh sweep and no stale probe failure is emitted. |
| P2 | Connext -> Fast DDS, Fast DDS -> Connext | Healthy writer terminates after discovery. | Discovery disposal occurs. | Same stale-endpoint assertion, subject to confirmed vendor disposal propagation. |

### Scope Boundaries

- Do not call a communication failure a Doctor false negative unless the
  endpoint records expose enough information for Doctor to diagnose it.
  Unsupported or opaque metadata must produce Doctor's documented
  indeterminate/advisory behavior, not an invented incompatibility.
- Keep DDS Security, unrecognized vendors, and intentionally non-standard
  discovery transports in a separate capability suite. Doctor explicitly
  flags, rather than diagnoses, those boundaries.
- Type extensibility is currently covered by healthy FINAL/APPENDABLE matrices.
  Add a negative layout case only after capturing the actual endpoint discovery
  and match behavior for every vendor direction. The expected outcome must be
  recorded as a vendor-specific contract instead of assumed from a single DDS
  implementation.

## Implementation Steps

1. Refactor the current vendor endpoint scripts so every fixture accepts a
   common `--mode healthy|rxo-mismatch|type-conflict|large-data|exit-early`
   interface and produces one final JSON result with match and sample counts.
   Preserve existing commands as compatibility aliases.
2. Extract a small shared Python test helper for process lifecycle, safe-domain
   selection, JSON decoding, artifact retention, and headless Doctor execution.
   Keep it under `tools/rti_doctor/test/`; it must not become runtime code.
3. Add P0 reliability fault/control tests for both directions of Connext/Cyclone
   and Connext/Fast DDS. These are the acceptance slice: they prove a known
   cross-vendor fault and prove Doctor stays quiet with the paired repair.
4. Add the P1 RxO matrix by reusing the present scenario names from
   `test_rxo_vendor_e2e.py`. Run one policy per subtest so a failed policy is
   immediately identifiable.
5. Add type propagation, incompatible type, large-data, and endpoint-disposal
   scenarios. Gate optional external prerequisites with explicit `SkipTest`
   messages naming the missing runtime, Docker image, capture permission, or
   unsupported fixture capability.
6. Add a concise test-run section to `tools/rti_doctor/README.md` with quick
   P0 and full-suite commands plus prerequisite setup. Do not make packet
   capture mandatory for QoS-report assertions.

## Execution Tiers

| Tier | CI suitability | Contents | Required environment |
|---|---|---|---|
| Fast | Required on every change | Unit tests plus Connext fixture healthy, no-type-info, and bad-pair tests. | Connext Python API and license. |
| Cross-vendor P0 | Required when Cyclone/Fast DDS are provisioned | Healthy and reliability-fault controls in both directions; Doctor JSON assertions. | Fast: Connext + Cyclone Python. Full: additionally Docker and the current Fast DDS image. |
| Full interoperability | Scheduled/nightly | Entire RxO, type, fragmentation, and departure matrix. | All vendor runtimes; optional `tshark` and capture permission for wire evidence. |

The suite must report executed, skipped, and failed scenario counts by vendor
pair. A skipped third-party test is never counted as a passing interoperability
case.

## Acceptance Criteria

- Every P0 fault reports the intended Doctor diagnostic in each supported
  vendor direction, while its paired healthy control has no active Doctor
  `ERROR` finding.
- Every implemented RxO fault has both endpoint data-flow evidence and a
  Doctor-report assertion.
- A healthy Connext/Cyclone and Connext/Fast DDS run exercises the complete
  headless CLI path, not only the packet-capture appendix.
- Failures preserve enough local artifacts under `test_output/` to reproduce
  the scenario without rerunning on a shared DDS domain.
- Required test environments fail loudly on a real assertion failure; optional
  prerequisites create a reasoned skip message and are visible in CI output.
- The README documents the P0 command and full-matrix command, including the
  Fast DDS image build and any packet-capture permissions.

## Initial Commands After Implementation

```bash
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools.rti_doctor.test.test_live_integration

PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools.rti_doctor.test.test_fault_vendor_e2e

bash tools/rti_doctor/test/vendors/fastdds/build_image.sh
PYTHONPATH=tools/rti_doctor ./connext_dds_env/bin/python \
  -m unittest tools.rti_doctor.test.test_fault_vendor_e2e \
  tools.rti_doctor.test.test_vendor_wire_e2e \
  tools.rti_doctor.test.test_rxo_vendor_e2e \
  tools.rti_doctor.test.test_extensibility_vendor_e2e \
  tools.rti_doctor.test.test_fastdds_extensibility_vendor_e2e
```