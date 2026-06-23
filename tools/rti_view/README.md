# rti_view

`rti_view` is a DDS field viewer for RTI Connext DDS. It discovers writer
topics from builtin topics, lets you choose a DynamicData field, and shows that
field as text or as a live plot.

## Quick Start

From the repository root:

```bash
./tools/rti_view/run_rti_view.sh -d 0
```

If you already know the target topic and field:

```bash
./tools/rti_view/run_rti_view.sh -d 0 -t Telemetry -f position.x -m plot --history 30
```

## What the Launcher Does

`run_rti_view.sh` uses the shared repository Python environment in
`connext_dds_env/` and will:

- detect `NDDSHOME`
- detect `RTI_LICENSE_FILE`
- create or rebuild the shared Python 3.10 virtual environment if needed
- install packages from `tools/rti_view/requirements.txt`
- start `rti_view`

## Requirements

- Python 3.10 available as `python3.10`
- RTI Connext DDS 7.7.x available locally
- A valid RTI license file

`tools/rti_view/requirements.txt` currently pins `dearpygui==1.11.1` and
`rti.connext==7.7.*`.

## CLI

The app entrypoint accepts:

```text
-d, --domain     DDS domain ID (default: 0)
-t, --topic      Topic name
-f, --field      Field path, for example x or position.x
-m, --mode       text or plot (default: text)
--history        Plot history in seconds (default: 30)
--timeout        Discovery timeout in seconds (default: 10)
--debug [path]   Enable debug logging, optional output path
```

The portable startup string format is:

```bash
rti_view -d <domain> -t <topic> -f <field> -m <text|plot> [--history <seconds>]
```

## Development

Run the module directly:

```bash
PYTHONPATH=tools/rti_view ./connext_dds_env/bin/python -m rti_view --help
```

Run tests:

```bash
PYTHONPATH=tools/rti_view ./connext_dds_env/bin/python -m unittest discover -s tools/rti_view/test
```

For design details, see `ARCHITECTURE.md` in this directory.
