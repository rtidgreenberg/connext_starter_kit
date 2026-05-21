# Recording Service GUI — Project Review Findings

**Date:** March 13, 2026
**Scope:** All files under `services/rs_gui_v1/`

---

## 1. README.md — Stale/Wrong References

| # | Line | Issue | Severity |
|---|------|-------|----------|
| 1 | L75 | Files table lists `run_gui.sh` — file doesn't exist (only in `archive/`) | **Error** |
| 2 | L77–78 | Files table lists `ServiceAdmin_QOS_PROFILES.xml` and `MonitoringSubscriber_QOS_PROFILES.xml` — both were archived and centralized into `dds/qos/DDS_QOS_PROFILES.xml` | **Error** |
| 3 | L76 | Files table lists `test_gui.py` at the top level — it's now in `test/` | **Error** |
| 4 | L113 | Links to `GUI_PLAN.md` — file is in `archive/GUI_PLAN.md`, not at top level. Should link to `GUI_ARCHITECTURE.md` instead | **Error** |
| 5 | L128–129 | Says "The `ServiceAdmin_QOS_PROFILES.xml` in this directory contains the QoS profiles" — file no longer exists here | **Error** |
| 6 | L70–79 | Files table is missing `recording_service_monitor.py`, `test_monitoring.py`, `test_control.py`, `run_all_tests.py`, `GUI_ARCHITECTURE.md` | **Incomplete** |
| 7 | L92 | Quick Start references `./run_gui.sh` which doesn't exist | **Error** |

---

## 2. GUI_ARCHITECTURE.md — Stale References

| # | Line | Issue | Severity |
|---|------|-------|----------|
| 8 | L36–37 | File structure shows `test_gui.py` and `test_monitoring.py` at top level — they're now in `test/` | **Stale** |
| 9 | L36–37 | File structure is missing `test_control.py` and `run_all_tests.py` | **Incomplete** |
| 10 | L214–215 | Dependency diagram says `monitoring_subscriber.py` — old filename, now `recording_service_monitor.py` | **Error** |
| 11 | L35 | Labels `recording_service_control.py` as "UNTOUCHED" — it was modified (QoS path updated) | **Misleading** |
| 12 | L401–402 | Acceptance criteria says `python3 test_monitoring.py && python3 test_gui.py` — paths need updating to `test/`, and `test_control.py` is missing | **Stale** |

---

## 3. Source Code Issues

| # | File | Line | Issue | Severity |
|---|------|------|-------|----------|
| 13 | `recording_service_control.py` | L1 | Missing `#!/usr/bin/env python3` shebang (the other two source files have it) | **Inconsistency** |
| 14 | `recording_service_control.py` | L22 | Docstring says "start/stop/pause" — there's no `stop` command, only `start`, `pause`, `shutdown` | **Minor error** |
| 15 | `recording_service_gui.py` | L935–938 | `main()` creates `app = RecordingServiceGUI(...)` but never calls `app.close()` after `mainloop()`. The `WM_DELETE_WINDOW` handler calls `close()`, but if the window is killed externally, DDS resources may leak | **Improvement** |
| 16 | `recording_service_gui.py` | L69–75 | `VERBOSITY_OPTIONS` is missing `"ALL:ALL"` (index 5). The controller CLI accepts 0–5 verbosity, but the GUI dropdown has no "ALL" option | **Incomplete** |
| 17 | `recording_service_gui.py` | L80–82 | `STATE_INVALID`, `STATE_RUNNING`, `STATE_PAUSED` are duplicated between `recording_service_gui.py` and `recording_service_monitor.py`. The GUI explicitly avoids importing from the monitor, but the values could drift | **Design note** |
| 18 | `recording_service_gui.py` | L659 | `_ensure_controller()` creates a new controller using the current `_config_name_var` as `service_name`, but never recreates it if the user changes the config name after controller creation. Changing the config name dropdown while a controller exists will send commands to the old service name | **Bug** |
| 19 | `recording_service_gui.py` | L659 | Similarly, if the admin domain changes, the existing controller is still on the old domain. Only monitoring is restarted on domain change, not the controller | **Bug** |
| 20 | `recording_service_control.py` | L339–347 | `close()` does `del self._requester` then `self._participant.close()`. If `_requester` attribute doesn't exist (e.g., init failed mid-way), `del self._requester` raises `AttributeError`, caught by bare `except`. Works but fragile — `hasattr` check would be cleaner | **Minor** |

---

## 4. Test Issues

| # | File | Line | Issue | Severity |
|---|------|------|-------|----------|
| 21 | `test/test_gui.py` | L421 | `_apply_config_update` sets label to `"1 topics"` — grammatically wrong (should be "1 topic"). The test asserts this incorrect string | **Cosmetic** |
| 22 | `test/test_control.py` | L19–21 | Docstring says "3. Integration tests — require a live Recording Service (skipped by default)" but there's no Layer 3 class — the DDS construction tests are labeled Layer 2 | **Misleading** |
| 23 | All test files | — | `object.__new__(ClassName)` is used to bypass `__init__` for unit testing internal methods. This works but is brittle — if new instance attributes are added, tests could break silently | **Design note** |

---

## 5. Orphan/Unused Files

| # | Item | Issue | Severity |
|---|------|-------|----------|
| 24 | `python_types/` directory | Removed from setup/runtime usage — the project uses XML types via `xml_types/` instead | **Resolved** |
| 25 | `log_dir/xcdr/` directory | Recording Service output directory — runtime artifact, should be in `.gitignore` | **Cleanup** |
| 26 | `test/test_recording/` directory | Recording Service SQLite output — runtime artifact, should be in `.gitignore` | **Cleanup** |
| 27 | `archive/` directory | 7 archived files. These serve as history but could be removed if version control provides that | **Optional cleanup** |

---

## 6. Cross-Project / Infrastructure Gaps

| # | Location | Issue | Severity |
|---|----------|-------|----------|
| 28 | `services/README.md` | No mention of `rs_gui_v1/` at all — the parent README covers recording/replay/convert but doesn't link to the Python GUI/control tool | **Missing** |
| 29 | `rs_gui_v1/` | No `.gitignore` for `xml_types/`, `log_dir/`, `test/test_recording/`, `__pycache__/` | **Improvement** |
| 30 | `run_gui.sh` | Phase 3 of the architecture plan (create `run_gui.sh` launcher) was never completed — there's no GUI launcher script | **Not implemented** |

---

## 7. Connext Version Decision Record

**Current requirement:** RTI Connext DDS 7.6.0 with matching
`rti.connext==7.6.0` Python bindings in `connext_dds_env`.

This section tracks the known differences between the original 7.3 target and
the current 7.6 requirement. Keep operational README content focused on current
usage; use this section for historical comparisons and rationale.

### 7.3.x limitations observed or confirmed

| Area | 7.3.x behavior / limitation | Impact on this GUI |
|------|-----------------------------|--------------------|
| Python nested unions | RTI issue PY-182: incorrect deserialization of nested unions with an unknown discriminator. Fixed in 7.4 and therefore included in 7.6. | Recording Service monitoring data uses nested union structures. Unknown discriminator handling can drop, misread, or fail to expose monitoring samples correctly. |
| Monitoring type path | Generated Python monitoring type modules were not reliable enough for the built-in Recording Service monitoring writers. | The monitor uses XML-loaded DynamicData types instead of generated Python type modules. |
| Version mixing | Running host tools/services from one Connext install while importing a different `rti.connext` package from user site or another environment produced misleading results. | The launcher and environment helper now enforce a matching Connext install and Python package version. |
| Request/Reply helper API | 7.3-era Requester behavior differs from 7.6 and did not provide a reliable high-level service-discovery path for built-in Recording Service ServiceAdmin. | The controller uses fixed ServiceAdmin topics, raw DDS endpoint matching, correlated replies, and bounded reply timeouts. |

### 7.6 capabilities the current implementation depends on

| Area | 7.6 behavior used | Rationale |
|------|-------------------|-----------|
| PY-182 fix included | 7.6 includes the 7.4 Python fix for nested unions with unknown discriminators. | Required for robust Recording Service monitoring data handling. |
| XTypes compliance mask | `rti.connextdds.compliance` provides `get_xtypes_mask()` / `set_xtypes_mask()` and `XTypesMask` bits. | The monitor configures `ACCEPT_UNKNOWN_DISCRIMINATOR_BIT` and clears `SELECT_DEFAULT_DISCRIMINATOR_BIT` so DynamicData readers accept unknown union discriminators without selecting a default branch. |
| Generated XML artifacts | `setup.sh` generates admin and monitoring XML from `$NDDSHOME/resource/idl`, then stamps `xml_types/` with the source install and version. | Keeps XML DynamicTypes aligned with the Recording Service and Python binding version being used; runtime rejects stale XML after switching Connext installs. |
| PyPI package availability | `rti.connext==7.6.0` is available for the repository Python 3.8 virtual environment. | Allows reproducible installation into `connext_dds_env` without relying on user-site packages. |
| Validated runtime target | Unit, GUI, controller, live monitoring, and tag E2E tests have passed with Connext 7.6.0. | 7.6 is the current verified baseline; 7.3 is not considered supported for this GUI/controller. |

### Decision

Do not relax the GUI/controller requirement below Connext 7.6.0 unless the
following are revalidated on the proposed target version:

- XML DynamicData monitoring receives config, event, and periodic samples.
- Nested union samples with unknown discriminators are accepted and parsed.
- `rti.connext` package version matches the host Connext install.
- Controller commands receive correlated `OK` replies from Recording Service
  ServiceAdmin.
- Live GUI monitoring and tag E2E tests pass.

---

## 8. Connext AI Follow-up Review — May 21, 2026

Scope: active Python scripts in `rs_gui_v1/`, with emphasis on
Recording Service admin commands and monitoring integration.

| ID | Severity | Finding | Status | Next Step |
|----|----------|---------|--------|-----------|
| C1 | Critical | `start()` and `pause()` send lowercase state strings in `string_body`; Connext AI says documented Recording Service state updates should serialize state updates as CDR in `octet_body`. | Resolved | State commands now send empty `string_body` and RTI-serialized `EntityState` DynamicData octets; covered by controller unit tests and live pause/resume E2E. |
| C2 | High | `_send_command()` waits for only one reply and returns the last valid sample from that batch; reply sequences may require waiting for a final reply. | Resolved | `related_request_id` already scopes waits/takes to the request, and Connext AI confirmed current Recording Service admin commands are expected to return one final reply. Keep a final-reply loop only for future generic multi-reply operations. |
| C3 | High | `CommandRequest.application_name` is optional and currently unset; Connext AI warns unset requests can target all matching services. | Resolved | `_send_command()` now sets `application_name` from the configured service name before `send_request()`; covered by controller unit test. |
| C4 | Medium | GUI commands share one `Requester` from a two-worker executor; concurrent admin operations could cross-talk unless strictly correlated or serialized. | Resolved | GUI admin commands now enter an explicit FIFO queue backed by a single worker, so only one controller request/reply exchange runs at a time; covered by GUI unit test. |
| C5 | Low | Discovery/QoS failures are hard to diagnose from current controller errors. | Resolved | Discovery timeouts now include domain/service/topic context, match counters, incompatible-QoS status when available, and likely-cause hints; covered by controller unit tests. |
| C6 | Medium | No live E2E test sends `pause`/`start` and verifies Recording Service state transitions. | Resolved | GUI E2E now invokes live Pause/Resume controls, verifies OK replies drive PAUSED/RUNNING GUI state and button changes, and documents that service monitoring may remain STARTED. |

Monitor-specific follow-up from the same review is tracked as M12 in
`CONNEXT_MONITOR_REVIEW_FINDINGS.md`: the XTypes compliance mask is process-wide.

---

## Summary by Severity

| Severity | Count |
|----------|-------|
| **Error** (wrong/broken references) | 8 |
| **Bug** (functional issues) | 2 |
| **Stale** (outdated but not broken) | 3 |
| **Incomplete** (missing content) | 4 |
| **Inconsistency** | 1 |
| **Minor / Cosmetic** | 4 |
| **Cleanup** (orphan files) | 4 |
| **Design note** (non-actionable observations) | 3 |
| **Not implemented** (planned but missing) | 1 |
| **Total** | **30** |
