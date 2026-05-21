# Connext Monitor Review Findings

**Date:** May 21, 2026  
**Scope:** `recording_service_monitor.py`  
**Reviewer:** Ask Connext / Connext AI  
**Runtime target:** RTI Connext DDS 7.6.0 with `rti.connext==7.6.0`

This document tracks the actionable findings from the Connext review of the
Recording Service monitoring subscriber. It is intended as a step-through work
list, separate from the README and the broader project review findings.

## Current State

- The monitor subscribes to Recording Service monitoring topics using XML-loaded
  DynamicData types.
- The monitor uses `rti.asyncio` reader loops backed by WaitSet dispatch instead
    of DDS DataReaderListeners, so parsing and `on_update` callbacks run on the
    monitor thread rather than a DDS listener thread.
- The active topics are:
  - `rti/service/monitoring/config`
  - `rti/service/monitoring/event`
  - `rti/service/monitoring/periodic`
- The deprecated DataReader property
  `dds.sample_assignability.accept_unknown_union_discriminator` has been
  removed from project Python source.
- Unknown union discriminator handling is now configured with the Connext XTypes
  compliance mask:
  - set `ACCEPT_UNKNOWN_DISCRIMINATOR_BIT`
  - clear `SELECT_DEFAULT_DISCRIMINATOR_BIT`
- Unit and live GUI monitoring E2E tests passed after the replacement.

## Findings Checklist

| ID | Severity | Finding | Status | Next Step |
|----|----------|---------|--------|-----------|
| M1 | High | `_selected_union_value()` falls back to `.value`, which can mask the no-selected-member case for preserved unknown discriminators. | Resolved | Helper now fails closed when no branch is selected; covered by `test_selected_union_value_rejects_no_selected_member`. |
| M2 | High | `_union_discriminator()` can silently return default `0` when discriminator access fails. | Resolved | Helper now prefers `.discriminator`, keeps `discriminator_value` as compatibility fallback, and raises if neither works. |
| M3 | High | Runtime behavior should be explicit: XML-loaded DynamicData samples must expose readable union discriminators for this monitor path. | Resolved | Code documents the assumption and `test_xml_dynamicdata_union_discriminator_is_readable` validates the XML-loaded parser path. |
| M4 | Medium | Deprecated unknown-union-discriminator property was semantically correct but deprecated. | Resolved | Keep XTypes compliance-mask regression coverage. |
| M5 | Medium | DDS listener callback parses data and calls `on_update` on the listener thread. | Resolved | Monitor now uses a private asyncio loop with `reader.take_async()` tasks; GUI still receives updates through queue handoff. |
| M6 | Medium | `close()` closes the participant without detaching reader listeners first. | Resolved | Listener path removed; `close()` cancels async reader tasks, closes the RTI asyncio dispatcher, then closes contained DDS entities and the participant once. |
| M7 | Medium | Broad swallowed exceptions can hide Connext API or DynamicData schema mismatches. | Resolved | Structural field-access failures now surface through parse-error updates; optional telemetry still defaults when fields are simply absent. |
| M8 | Medium | Only `ServiceMonitoring.xml` is loaded for monitoring types. This is valid only if that XML resolves all dependent types. | Resolved | `setup.sh` generates XML from `$NDDSHOME/resource/idl`, stamps `xml_types/` with the source Connext install, and runtime validates the stamp before loading types. |
| M9 | Low | `Subscriber` is local instead of stored on `self`. | Resolved | Subscriber is now stored as `self._subscriber` and used for reader construction. |
| M10 | Low | `python_types_dir` is only used to infer `xml_types_dir`; the name is misleading. | Resolved | Compatibility parameter removed; monitor API now uses `xml_types_dir` only. |
| M11 | Low | Invalid samples are skipped without checking instance state. | Deferred | Intentionally left as-is; service-disappearance detection is not needed for the current live status use case. |
| M12 | High | XTypes compliance mask changes are process-wide, not scoped to the monitor reader. | Resolved | Policy is centralized in `configure_recording_service_xtypes_policy()`, documented as process-wide/idempotent, and covered by compliance-mask tests; controller/admin paths passed in the same process. |

## Suggested Fix Order

1. **Union correctness:** M1 and M2 are resolved.
2. **Lifecycle:** M6 and M9 are resolved.
3. **Tests:** strict discriminator handling, async task cancellation, and
    idempotent close are covered.
4. **Docs/comments:** M3, M5, M8, and M10 are resolved.
5. **Exception cleanup:** M7 is resolved; structural failures now emit parse
    errors while optional telemetry remains tolerant of missing fields.
6. **Optional service disappearance behavior:** revisit M11 only if the GUI needs
   to react to disposed/unregistered monitoring instances.
7. **Process-wide XTypes policy:** M12 is resolved by centralizing the policy
    in the shared environment helper and documenting that it applies to the
    whole GUI process.

## Notes Per Finding

### M1: Strict Selected Union Branch Handling

Connext highlighted this as the main correctness risk. With preserved unknown
union discriminators, a union may have a discriminator value but no selected
member. The helper should not silently fall back to `.value`, especially because
`.value` can be `None` in exactly the case we care about.

Implemented behavior:

```python
def _selected_union_value(union_value, branch_name: str):
    selected = _field(union_value, "value", _MISSING)
    if selected is None:
        raise ValueError(
            f"Union discriminator {_union_discriminator(union_value)} "
            "selects no member")
    return _field(union_value, branch_name)
```

An even stricter option is to remove the `.value` check entirely and access only
the expected branch by name.

### M2: Strict Discriminator Access

Connext confirmed `.discriminator` is the preferred API. The compatibility
fallback `.discriminator_value` can remain, but the helper should raise if no
discriminator can be read instead of returning default `0`.

Implemented behavior:

```python
def _union_discriminator(union_value):
    for attr in ("discriminator", "discriminator_value"):
        try:
            value = getattr(union_value, attr)
            if callable(value):
                value = value()
            return _to_int_required(value)
        except Exception:
            pass
    raise ValueError("Unable to read union discriminator")
```

### M3: DynamicData Unknown Discriminator Assumption

Connext noted a subtle DynamicData caveat: documentation says raw DynamicData may
not expose the discriminator for unknown-member unions in every path. The live
7.6 monitor path has been validated by `test_xml_dynamicdata_union_discriminator_is_readable`,
and the code now documents this runtime assumption.

Implemented note near the helper:

```python
# XML-loaded monitoring samples in Connext Python 7.6 expose the service union
# discriminator through .discriminator. The monitor depends on this to ignore
# unknown service-family branches while parsing Recording Service branches.
```

### M4: Deprecated Property Removal

The old per-reader property value `"2"` had the right semantics: accept the
sample, preserve the unknown discriminator, and select no default branch. It is
now replaced by the non-deprecated process-wide XTypes compliance mask. Do not
reintroduce the deprecated DataReader property.

### M5: Listener Thread Work

Resolved by removing DataReaderListeners from the monitoring data path. The
monitor now owns a dedicated Python thread with a private asyncio loop and one
`reader.take_async()` task per monitoring DataReader. RTI's Python asyncio layer
uses WaitSet dispatch under the hood, so DDS listener threads are not used for
sample parsing or GUI update handoff.

The GUI callback contract remains intentionally small: `on_update(dict)` should
perform a queue handoff only, and tkinter widgets are updated by the main thread
when it drains that queue.

### M6: Async Teardown On Close

The listener path has been removed. `close()` is still idempotent and now follows
an asyncio teardown order that Connext AI considers acceptable for 7.6: cancel
reader tasks, wait for them to exit, close the RTI asyncio dispatcher, then
close contained DDS entities and the participant. Connext AI clarified that RTI
does not appear to document one mandatory 7.6 ordering, but entity destruction
must stay after the async receive side is quiesced.

### M7: Broad Exception Handling

Resolved with a selective policy:

- structural field access no longer treats arbitrary exceptions as "missing"
- missing optional fields still fall back to defaults
- unexpected DynamicData access failures flow through `_process_sample()` as
    `kind="error"` parse updates
- user callback exceptions are still swallowed by `_emit()` so GUI queue handoff
    failures cannot kill DDS monitoring tasks

Coverage:

- `test_field_default_does_not_hide_unexpected_access_errors`
- `test_missing_optional_metric_defaults_without_error`
- `test_unexpected_optional_field_error_is_reported`

### M8: XML Type Loading

Resolved by treating generated XML as a Connext-install-derived artifact rather
than a maintained repo type definition:

- `setup.sh` uses `$NDDSHOME/resource/idl` as the source of truth
- `ServiceMonitoring.xml` remains the monitor entry point generated from that
    install's service monitoring IDL graph
- setup writes `xml_types/.generated_from_nddshome` with the source install and
    version
- monitor and controller startup call `validate_generated_types()` before
    loading XML types
- launchers rerun setup automatically when generated XML or its stamp is
    missing/stale

Coverage:

- `test_generated_types_stamp_validates_matching_install`
- `test_generated_types_stamp_rejects_mismatched_install`
- `test_generated_types_stamp_requires_metadata_file`

### M9: Store Subscriber

Store the subscriber on the monitor instance for wrapper ownership clarity:

```python
self._subscriber = dds.Subscriber(self._participant)
```

Then pass `self._subscriber` when creating readers.

### M10: `python_types_dir` Compatibility Parameter

Resolved. The compatibility parameter was removed because monitoring now uses
XML DynamicData exclusively and no call path requires generated Python type
modules.

### M11: Invalid Sample Handling

Deferred by decision. Skipping invalid samples is fine for the current live
status use case. If the GUI later needs explicit service-disappearance
detection, inspect `sample.info.state.instance_state` for disposed/unregistered
samples and emit a stale/lost-service update.

### M12: Process-Wide XTypes Compliance Mask

Resolved. Connext AI confirmed that `compliance.set_xtypes_mask()` changes
process state, not only this monitor's readers. The setting is required for the
current Recording Service monitoring path, so it is now treated as an explicit
application startup policy in `configure_recording_service_xtypes_policy()`.

The helper:

- sets `ACCEPT_UNKNOWN_DISCRIMINATOR_BIT`
- clears `SELECT_DEFAULT_DISCRIMINATOR_BIT`
- preserves unrelated XTypes mask bits
- is safe to call repeatedly
- intentionally does not restore the previous mask

The monitor calls the helper before creating DDS entities. Normal ServiceAdmin
controller traffic is expected to be unaffected because compatible
`CommandRequest`/`CommandReply` schemas do not depend on unknown union
discriminator handling; live controller and GUI E2E tests passed in the same
process after this policy was enabled.

## Validation Plan

After each implementation pass, run:

```bash
cd services/rs_gui_v1
PYTHONNOUSERSITE=1 ../../connext_dds_env/bin/python test/test_monitoring.py -v
```

After union and lifecycle fixes, also run live monitoring:

```bash
cd services/rs_gui_v1
PYTHONNOUSERSITE=1 ../../connext_dds_env/bin/python test/test_e2e_gui_monitoring.py -v
```

Expected success criteria:

- Unit/integration monitor tests pass.
- Live GUI monitoring detects the Recording Service.
- Config, event, and periodic monitoring updates arrive.
- No parse errors are emitted for valid Recording Service samples.
- `close()` remains idempotent and cancels async reader tasks before participant
    teardown.
- No deprecated unknown-union-discriminator property remains in Python source.

## References

- [RTI Connext Python Data Types](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/api/connext_dds/api_python/types.html)
- [RTI Connext Python API](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/api/connext_dds/api_python/rti.connextdds.html)
- [RTI Connext Python Subscriptions](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/api/connext_dds/api_python/reader.html)
- [Type-Consistency Enforcement](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/manuals/connext_dds_professional/extensible_types_guide/extensible_types/Type_Consistency_Enforcement.htm)
- [Connext Property Reference](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/manuals/connext_dds_professional/properties_reference/property_full.html)
- [Connext Python 7.4 Fixes, including PY-182](https://community.rti.com/static/documentation/connext-dds/7.7.0/doc/manuals/connext_dds_professional/release_notes/whats_fixed/740/fixes_apis_python.html)
