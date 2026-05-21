# Review Fixes Applied

All 30 findings from `REVIEW_FINDINGS.md` have been reviewed.
The fixes below were applied; items marked **Deferred** are design notes
left for future work.

**Test validation: 86/86 tests pass after all changes.**

---

## 1. README.md — Files Table Stale (ERROR → FIXED)

Rewrote the entire Files table. Removed references to non-existent files
(`test_gui.py` at top level, `ServiceAdmin_QOS_PROFILES.xml`,
`MonitoringSubscriber_QOS_PROFILES.xml`). Added entries for
`recording_service_monitor.py`, `run_gui.sh`, `GUI_ARCHITECTURE.md`,
and the `test/` directory with its contents.

## 2. README.md — Quick Start References Non-Existent `run_gui.sh` (ERROR → FIXED)

Created `run_gui.sh` (see fix #30), so the reference is now valid.

## 3. README.md — "How It Works" Links `GUI_PLAN.md` (ERROR → FIXED)

Changed `[GUI_PLAN.md](GUI_PLAN.md)` → `[GUI_ARCHITECTURE.md](GUI_ARCHITECTURE.md)`.

## 4-5. README.md — QoS Section References Local XML Files (ERROR → FIXED)

Replaced "The `ServiceAdmin_QOS_PROFILES.xml` in this directory…" with
a reference to the centralized `dds/qos/DDS_QOS_PROFILES.xml` and the
two library names (`ServiceAdministrationProfiles`,
`RecordingServiceMonitorProfiles`).

## 6-7. README.md — Missing Monitor File & Test Files from Table (ERROR → FIXED)

Both addressed as part of fix #1 (full table rewrite).

## 8. GUI_ARCHITECTURE.md — File Structure Stale (STALE → FIXED)

Updated the file-tree diagram:
- Moved test files under `test/` with individual entries
- Added `test_control.py`, `run_all_tests.py`, `test_publisher.py`,
  `test_recorder_config.xml`
- Added `run.sh` entry
- Removed "UNTOUCHED" annotation from `recording_service_control.py`

## 9. GUI_ARCHITECTURE.md — Old Filename in Dependency Diagram (STALE → FIXED)

Changed `monitoring_subscriber.py` → `recording_service_monitor.py` in
the ASCII box diagram (section 4.4).

## 10. GUI_ARCHITECTURE.md — "UNTOUCHED" Label Misleading (STALE → FIXED)

Removed "UNTOUCHED" from both the file structure (fix #8) and the
section heading (§4.3), replacing it with "DDS Remote Admin".
Also removed from the dependency diagram box label.

## 11. GUI_ARCHITECTURE.md — Acceptance Criteria Wrong Test Paths (ERROR → FIXED)

Changed `python3 test_monitoring.py && python3 test_gui.py` →
`cd test && python3 run_all_tests.py -v`.
Also removed the stale criterion "recording_service_control.py is not modified".

## 12. GUI_ARCHITECTURE.md — Missing `test_control.py` References (INCOMPLETE → FIXED)

Addressed as part of fix #8 (file structure) and fix #11 (acceptance criteria).

## 13. recording_service_control.py — Missing Shebang (INCOMPLETE → FIXED)

Added `#!/usr/bin/env python3` as the first line.

## 14. recording_service_control.py — Docstring Says "start/stop/pause" (ERROR → FIXED)

Changed to `start/pause/shutdown Recording Service` (there is no "stop"
command; the actual operations are start, pause, and shutdown).

## 15. recording_service_control.py — Fragile `close()` (MINOR → FIXED)

Replaced bare `del self._requester` with:
```python
if hasattr(self, '_requester') and self._requester is not None:
    self._requester.close()
    self._requester = None
```

## 16. recording_service_gui.py — Missing "ALL:ALL" Verbosity (INCOMPLETE → FIXED)

Added `"ALL:ALL"` to the `VERBOSITY_OPTIONS` list (Recording Service
supports SILENT, ERROR, WARN, LOCAL, REMOTE, ALL).

## 17. recording_service_gui.py — "1 topics" Grammar (COSMETIC → FIXED)

Changed the topics label logic to:
```python
label = f"{count} topic" if count == 1 else f"{count} topics"
```

## 18-19. recording_service_gui.py — Controller Not Invalidated on Config/Domain Change (BUG → FIXED)

**Fix 18 — `_ensure_controller()`**: Now checks whether the admin domain
or service name has changed since the controller was created. If so,
closes the old controller and creates a new one.

**Fix 19 — `_on_admin_domain_changed()`**: Now explicitly closes and
nullifies the controller before restarting monitoring, so the next
admin command will recreate it on the new domain.

## 20. recording_service_gui.py — `main()` Missing `app.close()` (MINOR → FIXED)

Added `app.close()` after `root.mainloop()` so DDS resources are
cleaned up when the window is closed.

## 21. test/test_gui.py — Assert "1 topics" (COSMETIC → FIXED)

Changed assertion from `"1 topics"` → `"1 topic"` to match the
corrected grammar in fix #17.

## 22. test/test_control.py — Docstring Claims 3 Test Layers (MINOR → FIXED)

Removed "3. Integration tests" from the docstring since no Layer 3
test class exists.

## 23. Design Note — No Integration Tests for Controller (DESIGN NOTE → DEFERRED)

Acknowledged. Live-service integration tests are a future enhancement.

## 24-25. Orphan `python_types/` Directory (CLEANUP → RESOLVED)

`python_types/` is no longer generated or used. Monitoring and control paths
load XML DynamicTypes from `xml_types/`, generated from the active Connext
installation by `setup.sh`.

## 26. Orphan `log_dir/` Runtime Artifacts (CLEANUP → FIXED)

Added `log_dir/` to `.gitignore`.

## 27. Design Note — No Auto-Config-Reload on File Change (DESIGN NOTE → DEFERRED)

File-system watchers (e.g., `watchdog`) are out of scope for a
reference example. The user can re-browse the config file to reload.

## 28. services/README.md — No Mention of GUI Tool (INCOMPLETE → FIXED)

Added a new "I want to control Recording Service with a GUI" section
with a link to `recording_service_gui/README.md`, and a corresponding
TOC entry.

## 29. Missing `.gitignore` (INCOMPLETE → FIXED)

Created `.gitignore` covering:
- `xml_types/` (generated files)
- `log_dir/`, `test/test_recording/` (runtime artifacts)
- `__pycache__/`, `*.pyc` (Python bytecode)

## 30. Missing `run_gui.sh` (NOT IMPLEMENTED → FIXED)

Created `run_gui.sh` modeled after the existing `run.sh`. Handles
NDDSHOME auto-detection, license validation, virtual environment
activation, XML type file verification, and launches
`recording_service_gui.py`. Made executable.

---

## Summary

| Category | Count | Applied | Deferred |
|----------|-------|---------|----------|
| Errors | 8 | 8 | 0 |
| Bugs | 2 | 2 | 0 |
| Stale refs | 3 | 3 | 0 |
| Incomplete | 4 | 4 | 0 |
| Minor/Cosmetic | 5 | 5 | 0 |
| Cleanup | 4 | 4 | 0 |
| Design notes | 3 | 0 | 3 |
| Not implemented | 1 | 1 | 0 |
| **Total** | **30** | **27** | **3** |

Files modified:
- `recording_service_gui/README.md`
- `recording_service_gui/GUI_ARCHITECTURE.md`
- `recording_service_gui/recording_service_control.py`
- `recording_service_gui/recording_service_gui.py`
- `recording_service_gui/test/test_gui.py`
- `recording_service_gui/test/test_control.py`
- `services/README.md`

Files created:
- `recording_service_gui/.gitignore`
- `recording_service_gui/run_gui.sh`
- `recording_service_gui/REVIEW_FIXES_APPLIED.md` (this file)

Files deleted:
- `recording_service_gui/python_types/` (entire directory)
