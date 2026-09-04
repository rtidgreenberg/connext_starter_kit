# rs_gui

`rs_gui` is the operator GUI for RTI infrastructure services in this repo. The
supported UI is the Tk Record/Replay shell.

## Quick Start

From the repository root:

```bash
./services/rs_gui/run_rs_gui.sh
```

This defaults to `--gui`, which launches the Tk Record/Replay shell.

## Recorded QoS Analysis Prototype

The Replay tab's recorded QoS analysis is a very coarse prototype example for
reference only. It does not cover all DDS matching behavior or the lifecycle,
type-compatibility, security, transport, data-representation, and other edge
cases described by the analysis output. It must not be used as an authoritative
record of endpoint matching.

Select a playback data database from a Recording Service log directory. The
prototype locates and reads the sibling `discovery.db` without modifying the
recording, then reports candidate writer/reader QoS mismatches observed by that
Recording Service instance. A recording without `discovery.db` cannot be
analyzed.

We will add supported QoS mismatch analysis in an upcoming Connext Studio
release.

## What the Launcher Does

`run_rs_gui.sh` uses the shared repository Python environment in
`connext_dds_env/` and will:

- detect `NDDSHOME`
- detect `RTI_LICENSE_FILE`
- create or rebuild the shared Python 3.10 virtual environment if needed
- install packages from `services/rs_gui/requirements.txt`
- optionally run `setup.sh` when `--prepare-dds` is used
- run startup diagnostics unless `--skip-diagnostics` is used
- start `rs_gui_app.py`

## Requirements

- Python 3.10 available as `python3.10`
- RTI Connext DDS 7.7.x available locally
- Tkinter available in that Python install
- A valid RTI license file

## Common Launcher Modes

```bash
./services/rs_gui/run_rs_gui.sh --gui
./services/rs_gui/run_rs_gui.sh --mock-gui
./services/rs_gui/run_rs_gui.sh --mock-gui-check
./services/rs_gui/run_rs_gui.sh --headless-check
./services/rs_gui/run_rs_gui.sh --prepare-dds --gui
./services/rs_gui/run_rs_gui.sh --diagnostics-only --gui
./services/rs_gui/run_rs_gui.sh --skip-diagnostics --gui
```

Launcher-only flags:

```text
--prepare-dds
--diagnostics-only
--skip-diagnostics
--debug
--no-debug
```

App modes passed through to `rs_gui_app.py`:

```text
--gui
--mock-gui
--mock-gui-check
--headless-check
```

The direct app entrypoint also supports `--tk-gui` and `--tk-gui-check`.

## DDS XML Setup

If you need to refresh generated XML type artifacts for the active Connext
installation:

```bash
cd services/rs_gui
./setup.sh
```

Re-run `setup.sh` after switching `NDDSHOME` to a different Connext install.

## Direct Entrypoint

From `services/rs_gui`:

```bash
./run_rs_gui.sh --gui
```

## Testing

Run the main test suite from `services/rs_gui`:

```bash
export VENV_PYTHON=$(ls -d ../../connext_dds_env_*py311/bin/python | head -1)
"$VENV_PYTHON" test/run_all_tests.py -v
```

For environment and startup issues, see `TROUBLESHOOTING.md`.
