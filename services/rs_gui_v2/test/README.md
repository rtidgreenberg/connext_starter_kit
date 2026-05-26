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
  view models, Convert/Replay command intents, workspace save/load command
  intents, event-log scheduling, and fake-renderer smoke coverage without
  requiring a display
- `test_gui_factory.py`: default GUI shell session assembly for mock and
  headless modes, including Topics/Plots snapshot wiring, CLI mock GUI checks,
  and fake-renderer coverage
- `test_gui_plots_tab.py`: mocked Plots-tab plot rows, series summaries,
  pause/resume affordances, bounded recent point rows, and diagnostics
- `test_gui_plots_controller.py`: Plots-tab controller wiring from
  data-session plot snapshots into shell snapshots, including provider
  failures and headless degraded states
- `test_gui_convert_tab.py`: mocked Convert-tab Converter presets, structured
  input/output storage, job snapshots, log rows, XML/CLI previews, action
  enablement, and `convert.*` command intents
- `test_gui_replay_tab.py`: mocked Replay-tab service candidates, database
  selection state, start/pause/resume/stop/shutdown affordances, timeline rows,
  duplicate-target diagnostics, and command intents
- `test_gui_replay_controller.py`: fake-first Replay-tab controller state
  transitions and `replay.*` command handling before live Replay Service wiring
- `test_gui_topics_tab.py`: mocked Topics-tab discovery rows, field picker,
  subscription/sample inspector state, `topics.*` command builders, and
  fake-renderer command callback coverage
- `test_gui_topics_controller.py`: Topics-tab controller wiring from the
  discovery facade and data-session snapshots into shell snapshots, including
  fake discovery scans, command-driven selection/subscription state,
  sample-inspector state, and headless degraded states
- `test_gui_session.py`: runtime-backed GUI session wiring from app-core command
  queues through Record, Replay, and Topics controllers into shell snapshots and
  event logs
- `test_gui_workspace.py`: GUI workspace projection, save/load command routing,
  and restoration of Topics/Plots intent using workspace-local test output
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
- `test_live_soak.py`: unit coverage for the live soak gate configuration,
  workspace bounds, pass/fail evaluation, and JSON report writing
- `test_discovery_churn.py`: unit coverage for the live discovery churn gate
  configuration, namespace filtering, pass/fail evaluation, and JSON report
  writing
- `test_service_churn.py`: unit coverage for the live service churn gate
  configuration, launch request construction, pass/fail evaluation, and JSON
  report writing
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

Live fixture gate:

```bash
../../connext_dds_env/bin/python test/live_soak.py --duration-sec 10 --publish-rate-hz 100
```

`live_soak.py` is intentionally not named `test_*.py`: it uses the real RTI
Connext Python API, creates live DDS participants, and writes its report under
`test_output/rs_gui_v2/`. The regular suite covers its deterministic logic;
run the live gate explicitly when validating Milestone L soak behavior.

```bash
../../connext_dds_env/bin/python test/discovery_churn.py --iterations 3
```

`discovery_churn.py` is explicit-only: it creates unique live DynamicData topics
with one writer and one reader, observes them through `RtiTopicDiscoveryClient`,
closes the endpoints, and verifies the run namespace converges to zero live
topics. It enables bounded stale-endpoint pruning because Connext 7.6 built-in
readers in this environment may not deliver endpoint delete samples.

```bash
../../connext_dds_env/bin/python test/service_churn.py --iterations 2
```

`service_churn.py` is also explicit-only: it starts live Recording Service
processes, verifies Service Admin endpoint readiness, attempts remote shutdown,
and falls back to local process termination if shutdown does not reply. It sends
Service Admin commands with `application_name` set to the launched `-appName`
and command resource paths rooted at the XML recording-service name, such as
`/recording_services/deploy`. Use `--require-admin-shutdown` when remote
shutdown acknowledgment should be a hard pass/fail criterion.

Future layers will add GUI rendering tests against a real Dear PyGui
installation and broader live service restart fixtures.
