# RTI Doctor Improvement Backlog

## Scope

This backlog follows the P0 Connext/Cyclone and Connext/Fast DDS fault-injection
work and the Fast DDS RTPS capture in `test_output/fastdds_rtps/`. It is the
canonical list of deferred and post-current-implementation improvements. It
separates test-harness reliability from RTI Doctor product behavior so a
passing test always means the intended thing.

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
| HAR-2 | Implemented: deterministic safe DDS domains. | Eight suites each picked from their own private `random.randint` band; one reached domain 230, whose RTPS ports sit just under the 16-bit ceiling. A collision was indistinguishable from the fault under test and was not reproducible from the failure output. | `test/domains.py` derives a port-safe domain from a stable key and refuses any whose range is privileged or wrapped. All eight suites use it. `RTI_DOCTOR_DOMAIN_OFFSET` shifts a machine's whole band so determinism does not make two developers collide every run. | Passed: `test_domains.py` asserts the port mapping, the ceiling, that no two of the repo's suites collide, and that a malformed offset is ignored rather than crashing every suite. |
| HAR-3 | Implemented: retain failure artifacts automatically. | RTPS capture was necessary to distinguish endpoint visibility from discovery timing. | On failure, write process stdout/stderr and command metadata below `test_output/rti_doctor_faults/<run-id>/`, with a copy of the readiness-control directory; honor `RTI_DOCTOR_KEEP_ARTIFACTS=1` for successful debugging runs. | A retained successful Fast DDS P0 bundle contained commands, all three process streams, Doctor log, and the Doctor/reader/writer start and ready markers without overwriting another run. |
| HAR-4 | Implemented: centralize headless Doctor execution and report parsing. | The P0 suite had duplicate CLI commands and Fast DDS can write a non-JSON Connext discovery diagnostic before JSON. | `test/doctor_e2e.py` builds the isolated CLI environment and extracts the report JSON after native preambles. Fault and wire E2E suites use it; the wire suite retains its topic-not-found retry before parsing. Parse failures include command, stdout, and stderr. | Focused helper tests cover clean reports, native preambles, malformed preambles, and non-report JSON. Fault and wire suites share the same report parser. |
| HAR-6 | Triage three Fast DDS vendor e2e failures. | `./run_tests.sh vendor` is red: 28 tests, **3 failures**, 12 skipped, 1 expected failure. Two are `test_fastdds_extensibility_vendor_e2e` (`final` and `appendable`) where the Fast DDS writer reports `matched: 0` after writing 100+ samples, i.e. Fast DDS never matched the Connext reader; the third is `test_fastdds_type_object_e2e`, where the Fast DDS writer never creates its endpoint marker. **Not caused by the HAR-2 migration**: the only change to those files was the domain source, and both failures reproduce identically at domain 167 and at domain 30. Note the `rti-doctor-fastdds-e2e` images were rebuilt shortly before this run, which is the first thing to rule out. | Establish whether this is an image/version regression, an environment issue, or a genuine Connext/Fast DDS interop change. Compare against a known-good image tag before changing any product code. | Each of the three is traced to a cause. If it is a real interop fault, it is exactly what Doctor exists to diagnose, and Doctor's own verdict for the pair should be checked against the truth. |
| HAR-8 | Write fixture scratch under `test_output/`, not the source tree. | The vendor fixtures create `test/rti_doctor_fastdds_repr_*/` readiness-marker directories beside the test code. A vendor run therefore dirties the working tree, and they were committed by accident once. Now gitignored, which hides the symptom rather than fixing it. | Point the readiness-control directories at `test_output/`, consistent with `HAR-3`'s failure artifacts. | A vendor run leaves `git status` clean. |
| HAR-7 | Run the live and vendor tiers in CI. | `.github/workflows/rti-doctor.yml` covers lint and the 169-test unit tier, which needs no license. The live tier (195 tests, including the H2 concurrency guard and the scale suite) and the vendor tier need a Connext license, and vendor additionally needs Docker images, so both depend on someone remembering to run them locally. | Provision a self-hosted runner with a licensed Connext install and the vendor images. Add a `live` job on pull requests and a nightly `vendor` job. | Every tier runs without a human deciding to run it. |
| HAR-5 | Add capture assertions for discovery, not only payload. | Existing wire tests validate DATA/DATA_FRAG and encapsulation; the Fast DDS issue was in SEDP timing and TypeInformation. | Add opt-in `tshark` assertions for SPDP builtin endpoint masks, SEDP entity IDs, endpoint GUIDs, topic/type names, and reliability QoS. Keep capture optional outside the dedicated network-evidence tier. | A Fast DDS discovery regression test confirms `0x00000c3f`, `0x000004c2 -> 0x000004c7`, and `PID_RELIABILITY` are present. |

## Priority 2: Improve Doctor Diagnostics

| ID | Improvement | Evidence | Implementation | Acceptance check |
|---|---|---|---|---|
| DOC-1 | Distinguish no counterpart from incomplete discovery. | `qos.no_counterpart` is correct for an empty system but indistinguishable from a late observer missing an endpoint announcement. | Include discovery age, participant presence, known remote builtin endpoint mask, and endpoint-announcement activity in the finding evidence. When a peer advertises the relevant SEDP announcer but no endpoint is observed, add an advisory stating that discovery may be incomplete. | A captured Fast DDS late-observer scenario gives an actionable incomplete-discovery advisory instead of implying no reader exists. |
| DOC-2 | Surface TypeInformation decode failure explicitly. | Connext logs `DISCBuiltin_deserializeTypeInformation: FAILED TO DESERIALIZE`, then Doctor emits generic `type.no_type_info`. | Capture this known discovery/type lookup error through the listener or Doctor debug log and attach it to `type.no_type_info` evidence. Add a distinct, actionable subtype or finding ID if the error can be correlated to the endpoint. | Fast DDS TypeInformation failure states that metadata deserialization failed, identifies the peer, and does not present the condition as merely absent propagation. |
| DOC-3 | Done, not backlog: make headless JSON output machine-safe. | Decision H1 made the text report the only output contract and retired `--format json`. | Delivered: `--format` and `report.render_json` are removed, and `test/doctor_e2e.parse_report` reads the text report instead. | Met: `--format` is rejected by the parser, and the vendor suites assert on finding ids and severities read back out of the text report. |
| DOC-4 | Expose discovered SEDP/QoS details in the report appendix. | TShark proved that the Fast DDS reader advertised RELIABLE, XCDR1, topic, and type even when type metadata was not decoded. | Where discovery bindings expose a field, include raw endpoint key/GUID, vendor ID, QoS policy values, and type-state transition timing in Markdown/text report evidence. Do not infer fields unavailable to Doctor. | A static report for a discovered peer includes enough evidence to explain every `qos.rxo_mismatch` without a PCAP. |

## Priority 3: Expand Coverage Once P0 Is Stable

| ID | Improvement | Implementation | Acceptance check |
|---|---|---|---|
| MAT-1 | Extend the Doctor-asserted Connext/Cyclone matrix from reliability to all existing RxO scenarios. | Reuse `test_rxo_vendor_e2e.py` scenario names, exercising one policy per subtest and both vendor directions. | Each incompatible pair has endpoint no-data evidence and active `qos.rxo_mismatch` naming the changed policy; paired controls have no active `ERROR`. |
| MAT-2 | Extend Fast DDS QoS fixtures beyond reliability. | Add only QoS controls that the current Fast DDS fixture can set and announce; document unsupported policies explicitly. | Each supported policy has a paired healthy/fault Doctor test in both directions. |
| MAT-3 | Add type-layout negative controls. | Measure FINAL/APPENDABLE incompatible layout behavior for each vendor direction before fixing expected report IDs. | No incompatible schema returns `payload FULL`; vendor-specific match and diagnosis behavior is asserted. |
| MAT-4 | Add endpoint-disposal tests. | Stop a discovered fixture endpoint, wait for builtin lifecycle disposal, and sweep again. | Doctor removes the departed endpoint and does not emit a stale probe failure. |
| MAT-5 | Add large-data cross-vendor tests. | Reuse or add fragmentation fixtures and validate the packet capture appendix separately from error severity. | `data.fragmentation` is informational while payload flow remains healthy. |

## Deferred Diagnostics

| ID | Improvement | Evidence | Implementation | Acceptance check |
|---|---|---|---|---|
| S5 | Harden SPDP2 numeric-bitmask support. | Current tests cover only the compatibility substring fallback; customer use is minimal. | Add direct numeric-mask tests for set and unset bits while retaining the fallback-string compatibility test. | The primary numeric path and fallback path produce the expected result for both enabled and disabled masks. |
| S6 | Re-enable advisory checks only with deterministic coverage. | `blind.security_enabled`, `transport.class_mismatch`, `security.mismatch`, and `discovery.partial` lack direct tests and are disabled from active reporting. | For each advisory, add direct positive and negative tests plus a healthy-path no-findings assertion; then explicitly restore that check to the active set. | Each restored advisory has deterministic coverage that proves it emits only for its intended condition and is absent from a healthy scenario. |
| S7 | Cover system-scan cache freshness. | `Session.system_scan()` supports recent-snapshot reuse for passive screen navigation and forced re-scan for explicit refresh, but tests currently bypass the cache and the view stub ignores `max_age`. | Add deterministic engine tests with a controllable clock and scan-call count for reuse, expiry, and forced re-scan. Rename the view-stub `scope` argument to `captured_at`; keep it non-caching. | Tests prove a scan is reused only inside `max_age`, expired snapshots rescan, and `max_age=0` or explicit `captured_at` always rescans. |
| S8 | Restore payload-health diagnosis. | Payload decode, field walking, decode/drop counters, and payload verdicts are outside the current discovery-and-matching product scope. | Define the report contract, add representative DynamicData fixtures and deterministic positive, negative, and healthy-path tests for each restored check before re-enabling `probe_payload.py` and `typewalk.py`. | Each restored payload-health finding is supported by direct deterministic fixtures, and healthy matching/discovery reports do not depend on payload verdicts. |

## Execution Order

1. Implement FDD-1, because it makes the existing forward Fast DDS P0 test
   repeatable and proves the test architecture.
2. Implement FDD-2 with a minimal fixture and preserved PCAP evidence.
3. Add HAR-1 through HAR-4 while promoting FDD-3; these prevent timing and
   output parsing defects from being misclassified as interoperability results.
4. Implement DOC-1, DOC-2, and DOC-4 so real diagnostic limitations are visible to
   users rather than hidden behind generic findings.
5. Expand the RxO/type/lifecycle matrix only after the P0 controls are reliable.

## Current Baseline

`tools.rti_doctor.test.test_fault_vendor_e2e` passes its four Connext/Cyclone
and four Fast DDS P0 tests when their Docker/runtime prerequisites are present.
The Fast DDS custom FINAL TypeObject compatibility result remains covered as a
specialized expected outcome rather than an older-version support lane.