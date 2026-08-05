# RTI Doctor Improvement Backlog

## Scope

This backlog follows the P0 Connext/Cyclone and Connext/Fast DDS fault-injection
work and the Fast DDS RTPS capture in `test_output/fastdds_rtps/`. It separates
test-harness reliability from RTI Doctor product behavior so a passing test
always means the intended thing.

## Priority 0: Unlock Reliable Fast DDS P0 Coverage

| ID | Improvement | Evidence | Implementation | Acceptance check |
|---|---|---|---|---|
| FDD-1 | Implemented: deterministic Doctor/Fast DDS endpoint readiness. | Fast DDS emits SEDP endpoint DATA immediately; a late Doctor observer reports `qos.no_counterpart`. | Doctor writes `--ready-file` after participant creation. The Fast DDS fixture waits on a start file and writes an endpoint-created marker; the test releases the writer only after a Fast DDS reader confirms endpoint creation. | Passed: ten Connext BEST_EFFORT writer -> Fast DDS RELIABLE reader runs each discovered the reader and reported active `qos.rxo_mismatch`. |
| FDD-2 | Partially implemented: resolve Fast DDS custom TypeObject compatibility variants. | The default custom FINAL TypeObject, default metadata, and TypeLookup controls now resolve `DynamicType`; deliberate metadata suppression remains unresolved by design. Connext's `--type-object-v1-only` experiment does not discover this Fast DDS writer and remains an expected failure. | The custom TypeObject test uses the deterministic endpoint-ready protocol and now requires default-mode resolution. Keep the v1-only experiment isolated; capture `PID_TYPE_INFORMATION` only if current default support regresses. Upgrade the fixture before investigating any reported vendor issue; do not maintain older-version comparison lanes. | Passed for supported default mode: the custom Fast DDS writer resolves `DynamicType`. The v1-only discovery experiment remains a separately tracked expected failure. |
| FDD-3 | Implemented: promote Fast DDS P0 tests where Docker is provisioned. | The class now has deterministic endpoint ordering; the custom Fast DDS FINAL TypeObject variant remains an isolated expected `type.assignability` outcome. | Class and reverse-direction skips removed. Retain explicit skips for absent Docker or image. | Passing: both directions run; reliability faults report exactly one active `qos.rxo_mismatch` naming RELIABILITY. The reverse healthy case separately asserts resolved metadata and the known custom FINAL TypeObject finding. |

## Priority 1: Improve Test Determinism And Evidence

| ID | Improvement | Evidence | Implementation | Acceptance check |
|---|---|---|---|---|
| HAR-1 | Implemented: replace sleep-based fixture ordering with discovery-aware readiness. | Participant-created markers alone did not prove Doctor had observed remote peers; Fast DDS one-shot SEDP announcements could still be missed. | Both endpoints create participants behind file gates. Doctor waits for the requested remote-participant count before writing its marker, then the test releases and confirms reader and writer endpoint creation in order. | Passed: all four Fast DDS P0 controls and ten consecutive Connext BEST_EFFORT writer -> Fast DDS RELIABLE reader fault runs discovered the endpoints and emitted active `qos.rxo_mismatch`. |
| HAR-2 | Use deterministic safe DDS domains. | Several suites select random domains; historical runs reached invalid or privileged RTPS ports. | Add one test helper that calculates RTPS discovery/user port ranges and chooses a valid, non-privileged domain. Give each test a unique topic. | The helper rejects unsafe candidates; no test binds a privileged or wrapped RTPS port. |
| HAR-3 | Implemented: retain failure artifacts automatically. | RTPS capture was necessary to distinguish endpoint visibility from discovery timing. | On failure, write process stdout/stderr and command metadata below `test_output/rti_doctor_faults/<run-id>/`, with a copy of the readiness-control directory; honor `RTI_DOCTOR_KEEP_ARTIFACTS=1` for successful debugging runs. | A retained successful Fast DDS P0 bundle contained commands, all three process streams, Doctor log, and the Doctor/reader/writer start and ready markers without overwriting another run. |
| HAR-4 | Implemented: centralize headless Doctor execution and report parsing. | The P0 suite had duplicate CLI commands and Fast DDS can write a non-JSON Connext discovery diagnostic before JSON. | `test/doctor_e2e.py` builds the isolated CLI environment and extracts the report JSON after native preambles. Fault and wire E2E suites use it; the wire suite retains its topic-not-found retry before parsing. Parse failures include command, stdout, and stderr. | Focused helper tests cover clean reports, native preambles, malformed preambles, and non-report JSON. Fault and wire suites share the same report parser. |
| HAR-5 | Add capture assertions for discovery, not only payload. | Existing wire tests validate DATA/DATA_FRAG and encapsulation; the Fast DDS issue was in SEDP timing and TypeInformation. | Add opt-in `tshark` assertions for SPDP builtin endpoint masks, SEDP entity IDs, endpoint GUIDs, topic/type names, and reliability QoS. Keep capture optional outside the dedicated network-evidence tier. | A Fast DDS discovery regression test confirms `0x00000c3f`, `0x000004c2 -> 0x000004c7`, and `PID_RELIABILITY` are present. |

## Priority 2: Improve Doctor Diagnostics

| ID | Improvement | Evidence | Implementation | Acceptance check |
|---|---|---|---|---|
| DOC-1 | Distinguish no counterpart from incomplete discovery. | `qos.no_counterpart` is correct for an empty system but indistinguishable from a late observer missing an endpoint announcement. | Include discovery age, participant presence, known remote builtin endpoint mask, and endpoint-announcement activity in the finding evidence. When a peer advertises the relevant SEDP announcer but no endpoint is observed, add an advisory stating that discovery may be incomplete. | A captured Fast DDS late-observer scenario gives an actionable incomplete-discovery advisory instead of implying no reader exists. |
| DOC-2 | Surface TypeInformation decode failure explicitly. | Connext logs `DISCBuiltin_deserializeTypeInformation: FAILED TO DESERIALIZE`, then Doctor emits generic `type.no_type_info`. | Capture this known discovery/type lookup error through the listener or Doctor debug log and attach it to `type.no_type_info` evidence. Add a distinct, actionable subtype or finding ID if the error can be correlated to the endpoint. | Fast DDS TypeInformation failure states that metadata deserialization failed, identifies the peer, and does not present the condition as merely absent propagation. |
| DOC-3 | Make headless JSON output machine-safe. | Native Connext diagnostics can precede JSON on stdout. | Direct library diagnostics to stderr where configurable; otherwise document and implement a single stable machine-output channel such as `--output`. Keep human diagnostics separate. | `--format json` produces exactly one JSON document on stdout in the TypeInformation-failure scenario. |
| DOC-4 | Expose discovered SEDP/QoS details in the report appendix. | TShark proved that the Fast DDS reader advertised RELIABLE, XCDR1, topic, and type even when type metadata was not decoded. | Where discovery bindings expose a field, include raw endpoint key/GUID, vendor ID, QoS policy values, and type-state transition timing in the JSON evidence. Do not infer fields unavailable to Doctor. | A static report for a discovered peer includes enough evidence to explain every `qos.rxo_mismatch` without a PCAP. |

## Priority 3: Expand Coverage Once P0 Is Stable

| ID | Improvement | Implementation | Acceptance check |
|---|---|---|---|
| MAT-1 | Extend the Doctor-asserted Connext/Cyclone matrix from reliability to all existing RxO scenarios. | Reuse `test_rxo_vendor_e2e.py` scenario names, exercising one policy per subtest and both vendor directions. | Each incompatible pair has endpoint no-data evidence and active `qos.rxo_mismatch` naming the changed policy; paired controls have no active `ERROR`. |
| MAT-2 | Extend Fast DDS QoS fixtures beyond reliability. | Add only QoS controls that the current Fast DDS fixture can set and announce; document unsupported policies explicitly. | Each supported policy has a paired healthy/fault Doctor test in both directions. |
| MAT-3 | Add type-layout negative controls. | Measure FINAL/APPENDABLE incompatible layout behavior for each vendor direction before fixing expected report IDs. | No incompatible schema returns `payload FULL`; vendor-specific match and diagnosis behavior is asserted. |
| MAT-4 | Add endpoint-disposal tests. | Stop a discovered fixture endpoint, wait for builtin lifecycle disposal, and sweep again. | Doctor removes the departed endpoint and does not emit a stale probe failure. |
| MAT-5 | Add large-data cross-vendor tests. | Reuse or add fragmentation fixtures and validate the packet capture appendix separately from error severity. | `data.fragmentation` is informational while payload flow remains healthy. |

## Execution Order

1. Implement FDD-1, because it makes the existing forward Fast DDS P0 test
   repeatable and proves the test architecture.
2. Implement FDD-2 with a minimal fixture and preserved PCAP evidence.
3. Add HAR-1 through HAR-4 while promoting FDD-3; these prevent timing and
   output parsing defects from being misclassified as interoperability results.
4. Implement DOC-1 through DOC-3 so real diagnostic limitations are visible to
   users rather than hidden behind generic findings.
5. Expand the RxO/type/lifecycle matrix only after the P0 controls are reliable.

## Current Baseline

`tools.rti_doctor.test.test_fault_vendor_e2e` passes its four Connext/Cyclone
and four Fast DDS P0 tests when their Docker/runtime prerequisites are present.
The Fast DDS custom FINAL TypeObject compatibility result remains covered as a
specialized expected outcome rather than an older-version support lane.