# Recording Service GUI — Project Review Findings

**Date:** March 13, 2026
**Scope:** All files under `services/recording_service_gui/`

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
| 24 | `python_types/` directory | Contains generated Python type files (`RecordingServiceMonitoring.py`, `ServiceCommon.py`, etc.) that are never imported — the project uses XML types via `xml_types/` instead. Leftover from an earlier approach | **Cleanup** |
| 25 | `log_dir/xcdr/` directory | Recording Service output directory — runtime artifact, should be in `.gitignore` | **Cleanup** |
| 26 | `test/test_recording/` directory | Recording Service SQLite output — runtime artifact, should be in `.gitignore` | **Cleanup** |
| 27 | `archive/` directory | 7 archived files. These serve as history but could be removed if version control provides that | **Optional cleanup** |

---

## 6. Cross-Project / Infrastructure Gaps

| # | Location | Issue | Severity |
|---|----------|-------|----------|
| 28 | `services/README.md` | No mention of `recording_service_gui/` at all — the parent README covers recording/replay/convert but doesn't link to the Python GUI/control tool | **Missing** |
| 29 | `recording_service_gui/` | No `.gitignore` for `xml_types/`, `python_types/`, `log_dir/`, `test/test_recording/`, `__pycache__/` | **Improvement** |
| 30 | `run_gui.sh` | Phase 3 of the architecture plan (create `run_gui.sh` launcher) was never completed — there's no GUI launcher script | **Not implemented** |

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
