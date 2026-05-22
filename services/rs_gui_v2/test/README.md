# rs_gui_v2 Tests

The current test suite covers the headless app core only. It does not import
DDS, Dear PyGui, or any `rs_gui_v1` implementation modules.

Run from `services/rs_gui_v2`:

```bash
../../connext_dds_env/bin/python test/run_all_tests.py -v
```

Current layers:

- `test_data_session.py`: DDS-free workspace-to-subscription coordination,
  type-resolution gating, sample cache updates, plot feeding, and shutdown
- `test_events_and_state.py`: immutable command, event, result, and state DTOs
- `test_field_extractors.py`: DDS-free field-path parsing, extraction from
  mapping/object/DynamicData-like values, invalid sample handling, and value
  classification
- `test_fields.py`: DDS-free field catalog DTOs, child path population, and
  plottable field filtering
- `test_discovery_catalog.py`: DDS-free topic inventory, type resolution,
  internal-topic filtering, and persisted topic-selection DTOs
- `test_headless_entrypoint.py`: headless app entry point startup/shutdown
- `test_gui_shell.py`: mocked Dear PyGui shell snapshots, Record-tab selector
  view models, command intents, event-log scheduling, and fake-renderer smoke
  coverage without requiring a display
- `test_gui_factory.py`: default GUI shell session assembly for mock and
  headless modes, including CLI mock GUI checks and fake-renderer coverage
- `test_gui_topics_tab.py`: mocked Topics-tab discovery rows, field picker,
  subscription/sample inspector state, and fake-renderer coverage
- `test_gui_topics_controller.py`: Topics-tab controller wiring from the
  discovery facade into shell snapshots, including fake discovery scans and
  headless degraded states
- `test_gui_session.py`: runtime-backed GUI session wiring from app-core command
  queues through the Record controller into shell snapshots and event logs
- `test_record_tab_controller.py`: Record tab wiring from the local process
  manager, Service Admin facade, monitoring facade, command history, duplicate
  candidate detection, and guarded termination state into GUI snapshots
- `test_import_boundaries.py`: no app-core imports from DDS, UI libraries, or
  `rs_gui_v1` implementation modules, with Connext imports limited to explicit
  adapter modules; GUI modules are also checked for no DDS or v1 imports
- `test_plotting.py`: DDS-free numeric plot buffers, bounded history,
  deterministic decimation, skipped/dropped counters, and UI-facing snapshots
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
- `test_workspace.py`: DDS-free versioned workspace JSON persistence,
  migration, validation, and declarative topic/field/plot selection round trips

Future layers will add live adapter fixtures and GUI rendering tests against a
real Dear PyGui installation after the mocked shell is wired to live app-core
snapshots.
