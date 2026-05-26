# RS GUI v2 (RTI Services Operator GUI)

rs_gui_v2 is the next-generation Dear PyGui-based operator application for RTI
infrastructure services. It is designed to cover recording, replay, conversion,
topic browsing, sample inspection, plotting, and persisted workspaces.

This directory currently includes:

- A runnable app entrypoint with modes for headless and GUI checks
- App-core modules that keep DDS logic separated from the GUI layer
- A growing test suite for headless runtime, GUI session wiring, adapters, and
  boundaries
- A `setup.sh` tool that generates v2-owned XML DynamicData types from the
  active Connext installation

Architecture and planning references:

- [RS_GUI_V2_ARCHITECTURE.md](RS_GUI_V2_ARCHITECTURE.md)
- [RS_GUI_V2_IMPLEMENTATION_PLAN.md](RS_GUI_V2_IMPLEMENTATION_PLAN.md)
- [RS_GUI_V2_WIREFRAME_PLAN.md](RS_GUI_V2_WIREFRAME_PLAN.md)

## Prerequisites

- RTI Connext DDS installation available (7.6.0 preferred by setup tooling)
- Repository Python virtual environment at `connext_dds_env/`
- Dear PyGui installed in that environment for real GUI rendering

## One-Time Setup (DDS XML Types)

Generate/refresh v2 XML type artifacts tied to the active `NDDSHOME`:

```bash
cd services/rs_gui_v2
./setup.sh
```

What `setup.sh` does:

- Detects `NDDSHOME` (or auto-detects an RTI install)
- Uses `rtiddsgen -convertToXML` on RTI service IDL files
- Writes XML files into `xml_types/`
- Writes `xml_types/.generated_from_nddshome` metadata to detect stale types
- Installs rs_gui_v2 Python dependencies from `requirements.txt` using the
  repository virtual environment (`connext_dds_env/bin/python`) when available

Re-run `./setup.sh` whenever you switch Connext installations.

Skip Python dependency installation if needed:

```bash
./setup.sh --skip-python-deps
```

## Install GUI Dependency

The rs_gui_v2 `requirements.txt` pins a known-compatible Dear PyGui version for
this environment. Install GUI dependencies with:

```bash
cd /home/rti/CAT/connext_starter_kit
./connext_dds_env/bin/python -m pip install -r services/rs_gui_v2/requirements.txt
```

## Run

From `services/rs_gui_v2`:

```bash
./run_gui.sh
```

This defaults to `--gui` mode.

Useful modes:

```bash
# Start and stop app core only (no GUI)
./run_gui.sh --headless-check

# Build mock GUI session-backed data and exit
./run_gui.sh --mock-gui-check

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
../../connext_dds_env/bin/python rs_gui_v2_app.py --gui
```

CLI options:

- `--headless-check`
- `--mock-gui-check`
- `--gui`

## Tests

Run the rs_gui_v2 test suite from this folder:

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
`test_output/rs_gui_v2/`.

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
writes a JSON report under `test_output/rs_gui_v2/`.

Useful options:

```bash
# Short development smoke
../../connext_dds_env/bin/python test/service_churn.py --iterations 1 --startup-timeout-sec 5 --shutdown-timeout-sec 4

# Require remote Service Admin shutdown acknowledgment
../../connext_dds_env/bin/python test/service_churn.py --iterations 1 --require-admin-shutdown

# Override the XML recording-service resource name used in command paths
../../connext_dds_env/bin/python test/service_churn.py --admin-resource-name ''
```

## Notes

- `run_gui.sh --prepare-dds` uses `setup.sh` before launching.
- `run_gui.sh --gui` validates that Dear PyGui is importable and prints an
  actionable install command if it is missing.
- XML types are local generated artifacts in `xml_types/`.
- `run_gui.sh` includes preflight startup diagnostics for environment,
  dependencies, generated XML metadata, and RTI service executables.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common startup issues.
