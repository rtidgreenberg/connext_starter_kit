# RS GUI v2 (RTI Services Operator GUI)

rs_gui is the next-generation operator application for RTI infrastructure
services. The supported Record/Replay UI is now Tkinter-based.

This directory currently includes:

- A runnable app entrypoint with modes for headless and GUI checks
- App-core modules that keep DDS logic separated from the GUI layer
- A growing test suite for headless runtime, GUI session wiring, adapters, and
  boundaries
- A Tk session-backed shell bridge with a working Record tab slice for launch,
  selection, tag, and control actions
- A Tk Replay tab slice for target selection, launch-path entry, and playback
  control actions through the existing Replay/session boundary
- Operator-facing Recording Service configure-and-launch controls in the Record
  tab, backed by the same process launch path validated by live churn gates
- A `setup.sh` tool that generates v2-owned XML DynamicData types from the
  active Connext installation

Architecture and planning references:

- [RS_GUI_ARCHITECTURE.md](RS_GUI_ARCHITECTURE.md)
- [RS_GUI_IMPLEMENTATION_PLAN.md](RS_GUI_IMPLEMENTATION_PLAN.md)
- [RS_GUI_WIREFRAME_PLAN.md](RS_GUI_WIREFRAME_PLAN.md)

## Prerequisites

- RTI Connext DDS 7.7 LTS installation available (preferred by setup tooling and GUI launcher)
- Repository Python virtual environment at `connext_dds_env/`
- Tkinter available in that environment for the Tk migration scaffold

## One-Time Setup (DDS XML Types)

Generate/refresh v2 XML type artifacts tied to the active `NDDSHOME`:

```bash
cd services/rs_gui
./setup.sh
```

What `setup.sh` does:

- Detects `NDDSHOME` (or auto-detects an RTI install)
- Uses `rtiddsgen -convertToXML` on RTI service IDL files
- Writes XML files into `xml_types/`
- Writes `xml_types/.generated_from_nddshome` metadata to detect stale types
- Installs rs_gui Python dependencies from `requirements.txt` using the
  repository virtual environment (`connext_dds_env/bin/python`) when available

Re-run `./setup.sh` whenever you switch Connext installations.

For the supported default path, leave `NDDSHOME` unset and `run_gui.sh` will
launch the GUI against `/home/rti/rti_connext_dds-7.7.0`. The same `NDDSHOME`
is then used for `rtirecordingservice` and `rtireplayservice` when the GUI
launches them.

Skip Python dependency installation if needed:

```bash
./setup.sh --skip-python-deps
```

## Install GUI Dependency

The rs_gui `requirements.txt` pins the current non-stdlib GUI dependencies
for this environment. Tkinter is provided by the Python runtime.

```bash
cd /home/rti/CAT/connext_starter_kit
./connext_dds_env/bin/python -m pip install -r services/rs_gui/requirements.txt
```

## Run

From `services/rs_gui`:

```bash
./run_gui.sh
```

This defaults to `--gui` mode, which now launches the Tk Record/Replay shell.

Default GUI startup does not create mock/demo service candidates and does not
launch Recording Service automatically. Use the Record tab launch controls to
start a managed Recording Service process.

Useful modes:

```bash
# Start and stop app core only (no GUI)
./run_gui.sh --headless-check

# Build mock GUI session-backed data and exit
./run_gui.sh --mock-gui-check

# Run the Tk shell with explicit mock/demo data
./run_gui.sh --mock-gui

# Build the Tk session-backed Record/Replay shell and exit
../../connext_dds_env/bin/python rs_gui_app.py --tk-gui-check

# Run the Tk session-backed Record/Replay shell
../../connext_dds_env/bin/python rs_gui_app.py --tk-gui

# Prepare DDS XML types first, then launch
./run_gui.sh --prepare-dds --gui

# Run startup diagnostics only
./run_gui.sh --diagnostics-only --gui
```

Diagnostics can be bypassed for temporary local debugging:

```bash
./run_gui.sh --skip-diagnostics --gui
```

## Direct Entrypoint

You can also run the app directly:

```bash
../../connext_dds_env/bin/python rs_gui_app.py --gui
```

CLI options:

- `--headless-check`
- `--mock-gui-check`
- `--mock-gui`
- `--gui`
- `--tk-gui-check`
- `--tk-gui`

## Tests

Run the rs_gui test suite from this folder:

```bash
../../connext_dds_env/bin/python test/run_all_tests.py -v
```

See [test/README.md](test/README.md) for test layer details.

## Live DDS Soak Gate

Run a bounded live DynamicData smoke/soak using the built-in telemetry fixture:

```bash
../../connext_dds_env/bin/python test/live_soak.py --duration-sec 10 --publish-rate-hz 100
```

The gate creates a live DynamicData reader and optional fixture publisher,
applies bounded reader history/resource limits, feeds the same data-session and
plot-buffer path used by the GUI, and writes a JSON report under
`services/rs_gui/live_reports/`.

Useful options:

```bash
# Subscribe to an externally provided topic instead of starting the fixture
../../connext_dds_env/bin/python test/live_soak.py --no-publisher --topic-name MyTopic --type-name MyType

# Short smoke used during development
../../connext_dds_env/bin/python test/live_soak.py --duration-sec 1 --warmup-sec 0.2 --publish-rate-hz 50
```

## Live Service Churn Gate

Run a bounded Recording Service launch/restart cleanup gate:

```bash
../../connext_dds_env/bin/python test/service_churn.py --iterations 2
```

The gate launches `rtirecordingservice` through the same
`ServiceProcessManager` path used by the GUI, assigns a fresh `-appName` for
each iteration, checks Service Admin endpoint readiness, attempts remote
shutdown using the launched app name plus the XML recording-service resource
name, falls back to local process termination when shutdown does not reply, and
writes a JSON report under `services/rs_gui/live_reports/`.

Useful options:

```bash
# Short development smoke
../../connext_dds_env/bin/python test/service_churn.py --iterations 1 --startup-timeout-sec 5 --shutdown-timeout-sec 4

# Require remote Service Admin shutdown acknowledgment
../../connext_dds_env/bin/python test/service_churn.py --iterations 1 --require-admin-shutdown

# Override the XML recording-service resource name used in command paths
../../connext_dds_env/bin/python test/service_churn.py --admin-resource-name ''
```

## Replay Service Operator Notes

Replay launch and close behavior now follows the same GUI-managed session path
used by Recording Service, but Replay needs an existing database directory as
input.

Current Replay defaults used by the GUI/controller path:

- Config name: `xcdr`
- Topic allow filter: `*`
- Topic deny filter: `rti/*`
- Close action: `shutdown_gui_launched`, which tries Replay admin shutdown first
  and falls back to local termination when admin endpoints are unavailable

When launching Replay from the GUI, prefer an absolute database path or a path
relative to the rs_gui working directory.

## Live Discovery Churn Gate

Run a bounded live DDS discovery convergence gate:

```bash
../../connext_dds_env/bin/python test/discovery_churn.py --iterations 3
```

The gate creates unique DynamicData topics with one writer and one reader,
observes them through the same `RtiTopicDiscoveryClient` path used by the GUI,
closes the endpoints, and verifies the run namespace converges to zero live
topics. On Connext 7.6, endpoint delete samples may not arrive through the
built-in readers in this environment, so the gate enables bounded stale-endpoint
pruning and records a JSON report under `services/rs_gui/live_reports/`.

Useful options:

```bash
# Short development smoke
../../connext_dds_env/bin/python test/discovery_churn.py --iterations 1 --settle-timeout-sec 8

# Tune convergence for slower discovery environments
../../connext_dds_env/bin/python test/discovery_churn.py --iterations 5 --stale-endpoint-sec 3 --settle-timeout-sec 10
```

## Notes

- `run_gui.sh --prepare-dds` uses `setup.sh` before launching.
- `run_gui.sh --gui` launches the Tk Record/Replay shell and no longer depends
  on the retired legacy renderer.
- XML types are local generated artifacts in `xml_types/`.
- `run_gui.sh` includes preflight startup diagnostics for environment,
  dependencies, generated XML metadata, and RTI service executables.
- Replay close cleanup may report local termination fallback when Service Admin
  endpoints are not ready; the important end-state is that the spawned process
  exits and no orphan `rtireplayservice` remains.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common startup issues.
