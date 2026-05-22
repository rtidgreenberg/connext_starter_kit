# rs_gui_v2 Tests

The current test suite covers the headless app core only. It does not import
DDS, Dear PyGui, or any `rs_gui_v1` implementation modules.

Run from `services/rs_gui_v2`:

```bash
../../connext_dds_env/bin/python test/run_all_tests.py -v
```

Current layers:

- `test_events_and_state.py`: immutable command, event, result, and state DTOs
- `test_headless_entrypoint.py`: headless app entry point startup/shutdown
- `test_import_boundaries.py`: no app-core imports from DDS, UI libraries, or
  `rs_gui_v1` implementation modules, with Connext imports limited to explicit
  adapter modules
- `test_rti_admin_adapter.py`: RTI Service Admin adapter encoding and outcome
  mapping using fake Connext modules
- `test_runtime_lifecycle.py`: runtime lifecycle, bounded queues, and task
  supervision
- `test_services_facades.py`: service admin and monitoring facades backed by
  deterministic fake clients
- `test_services_models.py`: service references, readiness, command outcomes,
  monitoring snapshots, and service-state snapshots

Future layers will add live adapter fixtures, discovery, DynamicData
subscriptions, workspace persistence, and GUI tests after the wireframe approval
gate.