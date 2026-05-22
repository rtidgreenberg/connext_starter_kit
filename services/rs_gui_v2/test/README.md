# rs_gui_v2 Tests

The current test suite covers the headless app core only. It does not import
DDS, Dear PyGui, or any `rs_gui_v1` implementation modules.

Run from `services/rs_gui_v2`:

```bash
../../connext_dds_env/bin/python test/run_all_tests.py -v
```

Current layers:

- `test_events_and_state.py`: immutable command, event, result, and state DTOs
- `test_field_extractors.py`: DDS-free field-path parsing, extraction from
  mapping/object/DynamicData-like values, invalid sample handling, and value
  classification
- `test_fields.py`: DDS-free field catalog DTOs, child path population, and
  plottable field filtering
- `test_discovery_catalog.py`: DDS-free topic inventory, type resolution,
  internal-topic filtering, and persisted topic-selection DTOs
- `test_headless_entrypoint.py`: headless app entry point startup/shutdown
- `test_import_boundaries.py`: no app-core imports from DDS, UI libraries, or
  `rs_gui_v1` implementation modules, with Connext imports limited to explicit
  adapter modules
- `test_rti_admin_adapter.py`: RTI Service Admin adapter encoding and outcome
  mapping using fake Connext modules
- `test_rti_discovery_adapter.py`: RTI built-in topic discovery sample mapping,
  endpoint churn, and cleanup using fake Connext modules
- `test_rti_fields_adapter.py`: RTI DynamicType member traversal, scalar and
  collection classification, union handling, and depth limits using fake Connext
  modules
- `test_rti_monitoring_adapter.py`: RTI service monitoring reader setup and
  config/event/periodic snapshot normalization using fake Connext modules
- `test_rti_subscriptions_adapter.py`: RTI DynamicData topic/reader creation,
  sample metadata mapping, unresolved type handling, and cleanup using fake
  Connext modules
- `test_rti_types_adapter.py`: RTI XML DynamicData type registry lookup and
  provider failure mapping using fake Connext modules
- `test_runtime_lifecycle.py`: runtime lifecycle, bounded queues, and task
  supervision
- `test_services_facades.py`: service admin and monitoring facades backed by
  deterministic fake clients
- `test_services_models.py`: service references, readiness, command outcomes,
  monitoring snapshots, and service-state snapshots
- `test_subscriptions.py`: DDS-free subscription requests, sample envelopes,
  subscription state counters, and bounded sample cache behavior

Future layers will add live adapter fixtures, workspace file persistence,
plotting, and GUI tests after the wireframe approval gate.