# Auto Monitoring and DDS Callback Plan

## Goal

Change the Recording Service GUI so monitoring is always active and event-driven:

- create DDS DataReaders for the 3 monitoring topics automatically
- use DDS listener callbacks instead of polling-based reads
- remove the manual `Start Monitoring` button
- begin visualizing service data as soon as the service is launched
- add a real DDS end-to-end test that verifies monitoring after launch

## Scope

Files expected to change:

- `services/recording_service_gui/recording_service_gui.py`
- `services/recording_service_gui/test_gui.py`
- `services/recording_service_gui/README.md`
- optionally `services/recording_service_gui/run_gui.sh` if startup behavior needs clarification only

Test assets likely reused:

- `services/recording_service_gui/test/test_recorder_config.xml`
- `services/recording_service_gui/test/test_publisher.py`

## Current State

Current GUI behavior:

- monitoring readers exist behind a manual `Start Monitoring` action
- monitoring data is consumed by periodic polling
- GUI updates happen in polling loops
- no DDS launch-to-monitor end-to-end test currently verifies post-launch detection

Current DDS integration tests only verify:

- readers can be created
- controller can be initialized

## Desired State

After implementation:

1. GUI creates monitoring readers automatically
2. DDS listeners receive `config`, `event`, and `periodic` samples via `on_data_available`
3. listeners enqueue normalized updates to the GUI thread
4. GUI displays service state and metrics without pressing a monitor button
5. launch path starts the service while monitoring is already active
6. DDS test verifies service detection after launch

## Implementation Plan

### Phase 1 - Refactor monitoring backend

#### 1. Replace polling-centric monitoring with callback-centric monitoring

Refactor `MonitoringSubscriber` to:

- create the same 3 DynamicData readers
- attach `dds.DynamicData.DataReaderListener` listeners
- process samples in `on_data_available`
- avoid direct tkinter interaction from listener threads

Implementation shape:

- one shared listener class with a `reader_kind` field, or
- one listener per topic type

Each callback should:

- `take()` all available samples
- parse DynamicData fields
- convert data into normalized Python dict messages
- push messages into a thread-safe queue owned by the GUI

#### 2. Define message model between DDS callbacks and GUI

Create internal queue event types such as:

- `service_detected`
- `service_state`
- `service_name`
- `periodic_metrics`
- `sqlite_status`
- `topic_discovered`
- `log_event`
- `monitor_error`

This keeps DDS code separate from UI logic.

### Phase 2 - Update GUI behavior

#### 3. Remove the manual monitoring button

In `RecordingServiceGUI`:

- remove the `Start Monitoring` / `Stop Monitoring` button from the control bar
- remove the monitoring separator tied only to that button
- remove user-facing manual monitor toggling from the normal flow

#### 4. Start monitoring automatically

Preferred behavior:

- initialize monitoring during GUI construction so the app is always observing the admin domain

Alternative fallback:

- lazily initialize on first launch if startup-time monitoring is too aggressive

Preferred option is the first one.

#### 5. Process callback events on the tkinter thread

Keep a tkinter-safe queue processor that:

- reads listener-generated events
- updates labels and button states
- appends to the log panel
- tracks detected topics
- updates service detection state

This queue processor should remain timer-driven, but it only drains queued callback data.
It should not read DDS directly.

#### 6. Update detection timeout behavior

Revise `Service Not Detected` logic:

- timeout begins on launch
- if no callback-delivered monitoring data arrives within the timeout, show warning
- if callback data arrives later, clear warning and update the state normally

Because monitoring is always on, there should no longer be a separate monitoring-start timestamp in the UX sense unless needed internally.

### Phase 3 - Testing

#### 7. Keep and adapt unit/widget coverage

Update non-DDS tests to reflect the new behavior:

- remove assumptions about the monitor button
- verify monitoring auto-initialization path
- verify callback queue processing updates labels correctly
- verify launch path does not require manual monitor start

Mock-based tests should cover:

- event queue delivery
- state transitions from queued events
- timeout behavior before and after callback data

#### 8. Add DDS end-to-end monitoring test

Add a real DDS integration test in `test_gui.py` or a dedicated test module that:

1. starts Recording Service with `test/test_recorder_config.xml`
2. creates the GUI or monitoring subscriber in the same admin domain
3. waits for callback-driven monitoring data
4. verifies the service becomes detected
5. verifies at least one of:
   - service name populated
   - state transitions observed
   - uptime populated
   - DB directory/file info populated

#### 9. Add launch-to-monitor GUI integration test

If feasible, add a higher-level integration test that verifies:

- GUI launch path executes service command
- monitoring is already active
- GUI receives monitoring updates without any monitor button interaction

If launching the real service from the test is too environment-sensitive, keep this as a gated integration test.

## DDS Test Strategy

### Minimum DDS test to add

A new real DDS test should validate:

- service starts successfully
- monitoring topics publish samples
- callback path receives and surfaces those samples

### Candidate test name

- `test_integration_service_detected_after_launch`

### Candidate assertions

- service detection becomes `True`
- service name matches configured instance
- at least one monitoring sample is received within timeout

### Environment requirements

- RTI Python bindings available
- XML monitoring/admin types generated
- `rtirecordingservice` executable available in `NDDSHOME`
- valid RTI license available

## Risks

### 1. DDS callbacks run off the UI thread

Risk:

- tkinter is not thread-safe

Mitigation:

- listeners must only enqueue data
- all widget updates remain in the tkinter thread

### 2. Listener lifetime and garbage collection

Risk:

- listener objects may be garbage-collected if not retained

Mitigation:

- store listener instances on `MonitoringSubscriber`

### 3. DynamicData callback parsing complexity

Risk:

- malformed or partial samples may raise exceptions

Mitigation:

- isolate parsing per sample and log non-fatal errors

### 4. End-to-end launch tests can be flaky

Risk:

- environment timing, discovery latency, or missing executables

Mitigation:

- use retry/wait loops with clear timeout
- skip gracefully when environment prerequisites are unavailable

## Acceptance Criteria

Implementation is complete when:

- no monitor button is present in the GUI
- monitoring readers are created automatically
- service data appears without manual monitor start
- DDS callbacks, not direct polling, are used to consume monitoring samples
- GUI remains thread-safe and stable on close
- a real DDS test verifies monitoring after service launch
- full test suite passes

## Suggested Execution Order

1. refactor `MonitoringSubscriber` for callback listeners
2. add queue-based GUI event processing for callback messages
3. remove monitor button and manual monitor flow
4. update timeout semantics
5. update unit/widget tests
6. add DDS end-to-end monitoring test
7. update README
8. run full verification
