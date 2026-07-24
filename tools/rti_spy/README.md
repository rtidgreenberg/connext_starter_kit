# RTI Spy

`rti_spy` is a Python/Textual DDS monitoring tool for RTI Connext DDS. It
discovers participants, readers, and writers through builtin topics and can
subscribe to discovered writer topics using DynamicData.

## Quick Start

From the repository root:

```bash
./tools/rti_spy/run_rtispy.sh
```

If `--domain` is omitted and the launcher is running in an interactive terminal,
`rti_spy` prompts for a DDS domain before opening the UI. Press Enter to use
domain `1`. In non-interactive runs it falls back to domain `1`.

## What the Launcher Does

`run_rtispy.sh` auto-detects the Connext version from `NDDSHOME` and picks a
matching, isolated Python environment and `rti.connext` version:

| NDDSHOME version | Python  | venv                    | rti.connext |
|-------------------|---------|-------------------------|-------------|
| 7.3.x              | 3.9     | `connext_dds_env_7.3/`  | 7.3.1       |
| 7.7.x (default)    | 3.10    | `connext_dds_env/`      | 7.7.0       |

It will:

- detect `NDDSHOME` (or use `$NDDSHOME` if already set/exported)
- detect the Connext version and select the matching Python/venv/`rti.connext` above
- detect `RTI_LICENSE_FILE`
- create or rebuild the matching versioned virtual environment if needed
- install the matching `rti.connext` version, then the rest of `tools/rti_spy/requirements.txt`
- start `rtispy.py`

Switching between a Connext 7.3.x and 7.7.x install (via `NDDSHOME`) reuses each
version's own venv, so no rebuild/reinstall is needed when switching back and forth.

## Requirements

- RTI Connext DDS 7.3.x or 7.7.x available locally
- Python 3.10 available as `python3.10` (for 7.7.x), and/or Python 3.9 available
  as `python3.9` (for 7.3.x). If missing, the launcher prints the exact
  `sudo apt install python3.9 python3.9-venv` command needed and stops.
- A valid RTI license file

`tools/rti_spy/requirements.txt` no longer pins `rti.connext`; the version is
selected automatically to match `NDDSHOME`. The Textual UI dependencies are
still listed there.

## CLI

The app entrypoint accepts:

```text
-d, --domain      DDS domain ID
-i, --interval    Refresh interval in seconds (default: 10)
--debug-log       Optional log file for discovery/subscription events
```

Direct invocation:

```bash
./connext_dds_env/bin/python tools/rti_spy/rtispy.py --domain 1
```

## Testing

Run the startup tests:

```bash
PYTHONPATH=tools/rti_spy ./connext_dds_env/bin/python -m unittest tools/rti_spy/test/test_startup_live.py
```

Run the discovery/subscription integration test:

```bash
PYTHONPATH=tools/rti_spy ./connext_dds_env/bin/python -m unittest tools/rti_spy/test/test_live_e2e_integration.py
```
