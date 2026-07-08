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

`run_rtispy.sh` uses the shared repository Python environment in
`connext_dds_env/` and will:

- detect `NDDSHOME`
- detect `RTI_LICENSE_FILE`
- create or rebuild the shared Python 3.10 virtual environment if needed
- install packages from `tools/rti_spy/requirements.txt`
- start `rtispy.py`

## Requirements

- Python 3.10 available as `python3.10`
- RTI Connext DDS 7.7.x available locally
- A valid RTI license file

`tools/rti_spy/requirements.txt` currently pins `rti.connext==7.7.0` and the
Textual UI dependencies.

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
