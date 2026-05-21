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
- `test_runtime_lifecycle.py`: runtime lifecycle, bounded queues, and task
  supervision

Future layers will add service facades, DDS discovery, DynamicData
subscriptions, workspace persistence, and GUI tests after the wireframe approval
gate.